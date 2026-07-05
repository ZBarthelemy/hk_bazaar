"""Rich CLI for hk-bazaar."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hk_bazaar.analyzers.bluebook import get_catalog_item, get_reference_price, load_catalog, value_from_match
from hk_bazaar.analyzers.deal_finder import find_deals
from hk_bazaar.analyzers.product_matcher import match_product
from hk_bazaar.config import get_settings
from hk_bazaar.database.crud import get_stats, query_listings
from hk_bazaar.database.engine import get_session, init_db
from hk_bazaar.database.models import OutreachStatus, Platform
from hk_bazaar.database.outreach_crud import (
    ACTIONABLE_OUTREACH_STATUSES,
    cancel_outreach,
    clear_outreach_queue,
    get_outreach_attempt,
    get_outreach_stats,
    list_outreach_attempts,
    resolve_listing_by_url_or_id,
)
from hk_bazaar.outreach.manager import OutreachManager
from hk_bazaar.pipelines.ingestion import ingest_listings
from hk_bazaar.scrapers.asiaxpat import AsiaXpatScraper
from hk_bazaar.scrapers.carousell import CarousellScraper
from hk_bazaar.scrapers.facebook import FacebookMarketplaceScraper

app = typer.Typer(
    name="hk-bazaar",
    help="Hong Kong classifieds aggregator — asiaXPAT, Carousell, Facebook Marketplace",
    no_args_is_help=True,
)
bluebook_app = typer.Typer(help="Bluebook reference prices for common HK flip SKUs")
app.add_typer(bluebook_app, name="bluebook")
console = Console()


@contextmanager
def db_session() -> Iterator:
    gen = get_session()
    session = next(gen)
    try:
        yield session
    finally:
        with suppress(StopIteration):
            next(gen)


@app.command("init-db")
def init_db_cmd() -> None:
    """Create database tables."""
    init_db()
    settings = get_settings()
    console.print(f"[green]Database initialized[/green] at {settings.database_url}")


@app.command("scrape")
def scrape_cmd(
    platform: Annotated[str, typer.Argument(help="asiaxpat | carousell | facebook")],
    max_pages: Annotated[int, typer.Option("--max-pages", "-p")] = 5,
    query: Annotated[str | None, typer.Option("--query", "-q")] = None,
    max_price: Annotated[float | None, typer.Option("--max-price")] = None,
    no_details: Annotated[bool, typer.Option("--no-details", help="asiaXPAT: skip detail fetch")] = False,
) -> None:
    """Scrape a platform and ingest listings."""
    init_db()
    platform_l = platform.lower().replace("-", "_")

    with db_session() as session:
        if platform_l in {"asiaxpat", "asia_xpat"}:
            with AsiaXpatScraper() as scraper:
                raw = scraper.scrape(max_pages=max_pages, fetch_details=not no_details)
        elif platform_l == "carousell":
            with CarousellScraper() as scraper:
                raw = scraper.scrape(query=query, max_price=max_price, max_pages=max_pages)
        elif platform_l in {"facebook", "fb", "facebookmarketplace"}:
            with FacebookMarketplaceScraper() as scraper:
                raw = scraper.scrape(query=query, max_pages=max_pages)
        else:
            raise typer.BadParameter(f"Unknown platform: {platform}")

        stats = ingest_listings(session, raw)
        console.print(
            f"[green]Done[/green]: {stats['total']} scraped, "
            f"{stats['created']} new, {stats['updated']} updated"
        )


@app.command("query")
def query_cmd(
    max_price: Annotated[float | None, typer.Option("--max-price")] = None,
    min_price: Annotated[float | None, typer.Option("--min-price")] = None,
    category: Annotated[str | None, typer.Option("--category", "-c")] = None,
    district: Annotated[str | None, typer.Option("--district", "-d")] = None,
    search: Annotated[str | None, typer.Option("--search", "-s")] = None,
    platform: Annotated[str | None, typer.Option("--platform")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
) -> None:
    """Query stored listings."""
    init_db()
    plat = Platform(platform) if platform else None

    with db_session() as session:
        rows = query_listings(
            session,
            platform=plat,
            category=category,
            district=district,
            max_price=max_price,
            min_price=min_price,
            search=search,
            limit=limit,
        )

        table = Table(title=f"Listings ({len(rows)})", box=box.ROUNDED)
        table.add_column("Platform", style="cyan")
        table.add_column("Title", max_width=40)
        table.add_column("Price", justify="right")
        table.add_column("District")
        table.add_column("Category")

        for row in rows:
            price = f"HKD {row.price:,.0f}" if row.price is not None else (row.price_display or "—")
            table.add_row(
                row.platform.value,
                row.title[:40],
                price,
                row.district or "—",
                (row.category or "—")[:24],
            )
        console.print(table)


@app.command("find-deals")
def find_deals_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    use_bluebook: Annotated[bool, typer.Option("--use-bluebook", help="Use SKU bluebook vs category median")] = False,
) -> None:
    """Flag potential deals using v1 heuristics."""
    init_db()
    rows: list[tuple[float, str, str, str]] = []
    with db_session() as session:
        deals = find_deals(session, limit=limit, use_bluebook=use_bluebook)
        for deal in deals:
            listing = deal.listing
            price = (
                f"HKD {listing.price:,.0f}"
                if listing.price is not None
                else (listing.price_display or "—")
            )
            rows.append((deal.score, listing.title[:36], price, "; ".join(deal.reasons[:2])))

    if not rows:
        console.print("[yellow]No deals found — scrape more listings first.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Deal candidates", box=box.ROUNDED)
    table.add_column("Score", justify="right", style="bold green")
    table.add_column("Title", max_width=36)
    table.add_column("Price", justify="right")
    table.add_column("Reasons", max_width=40)
    for score, title, price, reasons in rows:
        table.add_row(f"{score:.1f}", title, price, reasons)
    console.print(table)


@app.command("stats")
def stats_cmd() -> None:
    """Show database statistics."""
    init_db()
    with db_session() as session:
        stats = get_stats(session)

    table = Table(title="hk_bazaar stats", box=box.ROUNDED)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total listings", str(stats["total_listings"]))
    table.add_row("With price", str(stats["with_price"]))
    avg = stats["avg_price_hkd"]
    table.add_row("Avg price (HKD)", f"{avg:,.2f}" if avg else "—")
    for plat, count in stats["by_platform"].items():
        table.add_row(f"  {plat}", str(count))
    console.print(table)

    if stats["top_categories"]:
        console.print("\n[bold]Top categories[/bold]")
        for cat, count in stats["top_categories"].items():
            console.print(f"  {cat}: {count}")


@app.command("export")
def export_cmd(
    fmt: Annotated[str, typer.Option("--format", "-f")] = "csv",
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 10_000,
) -> None:
    """Export listings to CSV or JSON."""
    init_db()
    out = output or Path(f"data/export_{datetime.now(UTC):%Y%m%d_%H%M%S}.{fmt}")
    out.parent.mkdir(parents=True, exist_ok=True)

    with db_session() as session:
        rows = query_listings(session, limit=limit, active_only=False)

        if fmt == "csv":
            fields = [
                "platform", "external_id", "title", "price", "price_display",
                "district", "region", "category", "url", "scraped_at",
            ]
            with out.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: getattr(row, k) for k in fields})
        elif fmt == "json":
            payload = [
                {
                    "platform": r.platform.value,
                    "external_id": r.external_id,
                    "title": r.title,
                    "price": r.price,
                    "district": r.district,
                    "category": r.category,
                    "url": r.url,
                }
                for r in rows
            ]
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            raise typer.BadParameter("Format must be csv or json")

        console.print(f"[green]Exported {len(rows)} listings to[/green] {out}")


@app.command("seed")
def seed_cmd() -> None:
    """Insert sample listings for testing without scraping."""
    init_db()
    from hk_bazaar.scrapers.base import RawListing

    samples = [
        RawListing(
            platform=Platform.ASIA_XPAT,
            external_id="seed-001",
            title="IKEA KALLAX shelf — urgent moving sale",
            description="Must go before Sunday. Pickup Wong Tai Sin.",
            price=200.0,
            price_display="HKD 200",
            district="Wong Tai Sin",
            region="Kowloon",
            category="Furniture",
            category_raw="Furniture",
            url="https://hongkong.asiaxpat.com/classifieds/seed-001",
        ),
        RawListing(
            platform=Platform.CAROUSELL,
            external_id="seed-002",
            title="iPhone 13 128GB 平賣",
            description="急售，面交觀塘",
            price=2800.0,
            price_display="HK$2,800",
            district="Kwun Tong",
            region="Kowloon",
            category="Electronics",
            url="https://www.carousell.com.hk/p/seed-002",
        ),
        RawListing(
            platform=Platform.ASIA_XPAT,
            external_id="seed-003",
            title="Free standing fan",
            description="免費，自取薄扶林",
            price=0.0,
            price_display="Free",
            district="Southern",
            region="Hong Kong Island",
            category="Home & Living",
            url="https://hongkong.asiaxpat.com/classifieds/seed-003",
        ),
    ]

    with db_session() as session:
        ingest_listings(session, samples)

    console.print(f"[green]Seeded {len(samples)} sample listings[/green]")


@bluebook_app.command("list")
def bluebook_list_cmd() -> None:
    """List all bluebook SKUs and reference prices (good condition)."""
    table = Table(title="Bluebook catalog", box=box.ROUNDED)
    table.add_column("SKU", style="cyan")
    table.add_column("Name", max_width=36)
    table.add_column("Buy", justify="right")
    table.add_column("Good ref", justify="right", style="bold")
    table.add_column("Sell", justify="right")
    for sku, item in sorted(load_catalog().items()):
        table.add_row(
            sku,
            item.display_name[:36],
            f"{item.buy_target:,.0f}" if item.buy_target else "—",
            f"{item.references.get('good', 0):,.0f}",
            f"{item.sell_target:,.0f}" if item.sell_target else "—",
        )
    console.print(table)


@bluebook_app.command("lookup")
def bluebook_lookup_cmd(
    sku: Annotated[str, typer.Argument(help="Catalog SKU key, e.g. iphone_13_128gb")],
    condition: Annotated[str, typer.Option("--condition", "-c")] = "good",
    price: Annotated[float | None, typer.Option("--price", "-p", help="Listing price to compare")] = None,
) -> None:
    """Look up bluebook reference for a SKU."""
    item = get_catalog_item(sku)
    if item is None:
        raise typer.BadParameter(f"Unknown SKU: {sku}. Try: hk-bazaar bluebook list")
    ref = get_reference_price(sku, condition)
    console.print(f"[bold]{item.display_name}[/bold] ({sku})")
    console.print(f"  Condition: {condition}")
    console.print(f"  Reference: HKD {ref:,.0f}" if ref else "  Reference: —")
    if item.buy_target:
        console.print(f"  Buy target: HKD {item.buy_target:,.0f}")
    if item.sell_target:
        console.print(f"  Sell target: HKD {item.sell_target:,.0f}")
    if price is not None and ref:
        delta_pct = ((ref - price) / ref) * 100
        console.print(f"  vs listing HKD {price:,.0f}: {delta_pct:+.1f}% ({'below' if delta_pct > 0 else 'above'} reference)")


@bluebook_app.command("match")
def bluebook_match_cmd(
    title: Annotated[str, typer.Argument(help="Listing title to match")],
    price: Annotated[float | None, typer.Option("--price", "-p")] = None,
) -> None:
    """Match a title to a bluebook SKU and optionally value it."""
    match = match_product(title)
    if match is None:
        console.print("[yellow]No bluebook SKU matched.[/yellow]")
        raise typer.Exit(0)
    console.print(f"SKU: [cyan]{match.sku}[/cyan] (confidence {match.confidence:.0%}, condition {match.condition})")
    item = get_catalog_item(match.sku)
    if item:
        console.print(f"Name: {item.display_name}")
        ref = get_reference_price(match.sku, match.condition)
        if ref:
            console.print(f"Reference ({match.condition}): HKD {ref:,.0f}")
    if price is not None and match is not None:
        valuation = value_from_match(match, listing_price=price)
        if valuation:
            console.print(
                f"Listing HKD {price:,.0f} → {valuation.verdict} "
                f"({valuation.delta_pct:+.1f}% vs reference)"
            )


@bluebook_app.command("scan")
def bluebook_scan_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 30,
    verdict: Annotated[str | None, typer.Option("--verdict", help="strong_buy | good_buy | fair")] = None,
) -> None:
    """Scan stored listings for bluebook matches and flip opportunities."""
    init_db()
    rows: list[tuple[str, str, str, str, str]] = []
    with db_session() as session:
        listings = query_listings(session, limit=500)
        for listing in listings:
            if listing.price is None or listing.price <= 0:
                continue
            match = match_product(listing.title, listing.description)
            if match is None:
                continue
            valuation = value_from_match(match, listing_price=float(listing.price), condition=match.condition)
            if valuation is None:
                continue
            if verdict and valuation.verdict != verdict:
                continue
            rows.append(
                (
                    valuation.verdict,
                    valuation.display_name[:28],
                    f"HKD {listing.price:,.0f}",
                    f"{valuation.delta_pct:+.0f}%",
                    listing.platform.value,
                )
            )
    rows.sort(key=lambda r: float(r[3].rstrip("%")), reverse=True)
    rows = rows[:limit]
    if not rows:
        console.print("[yellow]No bluebook matches in database.[/yellow]")
        raise typer.Exit(0)
    table = Table(title=f"Bluebook scan ({len(rows)})", box=box.ROUNDED)
    table.add_column("Verdict", style="bold green")
    table.add_column("SKU", max_width=28)
    table.add_column("Price", justify="right")
    table.add_column("vs ref", justify="right")
    table.add_column("Platform")
    for row in rows:
        table.add_row(*row)
    console.print(table)


@app.command("watch-deals")
def watch_deals_cmd(
    dry_run: Annotated[bool, typer.Option("--dry-run/--live", help="Dry-run logs only (default)")] = True,
) -> None:
    """Scan listings from the last 7 days for buy_target opportunities and queue outreach."""
    init_db()
    with db_session() as session:
        manager = OutreachManager(session)
        ids = manager.watch_new_listings(dry_run=dry_run)
    if not ids:
        console.print("[yellow]No new outreach opportunities qualified.[/yellow]")
        raise typer.Exit(0)
    console.print(f"[green]Queued {len(ids)} outreach attempt(s):[/green] {ids}")
    console.print("Review: [bold]hk-bazaar pending-outreaches[/bold]")


def _outreach_spread(attempt) -> float:
    return attempt.buy_target - attempt.listing_price


def _render_outreach_table(
    attempts: list,
    *,
    title: str = "Outreach opportunities",
) -> None:
    sorted_attempts = sorted(attempts, key=_outreach_spread, reverse=True)
    table = Table(title=title, box=box.ROUNDED, show_lines=False)
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Status")
    table.add_column("Platform")
    table.add_column("SKU", style="cyan")
    table.add_column("Title", max_width=28, overflow="ellipsis")
    table.add_column("List", justify="right")
    table.add_column("Target", justify="right")
    table.add_column("Bid", justify="right", style="bold green")
    table.add_column("Spread", justify="right", style="yellow")
    table.add_column("URL", max_width=24, overflow="ellipsis")
    for row in sorted_attempts:
        spread = _outreach_spread(row)
        table.add_row(
            str(row.id),
            row.status.value,
            row.platform.value,
            row.sku,
            row.listing_title,
            f"{row.listing_price:,.0f}",
            f"{row.buy_target:,.0f}",
            f"{row.proposed_bid:,.0f}",
            f"+{spread:,.0f}" if spread >= 0 else f"{spread:,.0f}",
            row.listing_url,
        )
    console.print(table)
    console.print(
        "[dim]Details: hk-bazaar show-outreach <id>  |  "
        "Approve: hk-bazaar approve-outreach <id>[/dim]"
    )


@app.command("list-outreaches")
def list_outreaches_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows to show")] = 50,
    platform: Annotated[str | None, typer.Option("--platform", "-p", help="Filter by platform")] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
) -> None:
    """List qualified outreach opportunities (dry-run and pending)."""
    init_db()
    platform_filter = None
    if platform:
        try:
            platform_filter = Platform(platform.strip().lower())
        except ValueError as exc:
            raise typer.BadParameter(f"Unknown platform: {platform}") from exc

    status_filter = None
    if status:
        try:
            status_filter = (OutreachStatus(status.strip().lower()),)
        except ValueError as exc:
            raise typer.BadParameter(f"Unknown status: {status}") from exc

    with db_session() as session:
        attempts = list_outreach_attempts(
            session,
            statuses=status_filter,
            platform=platform_filter,
            limit=limit,
        )
        if not attempts:
            console.print("[yellow]No outreach opportunities found.[/yellow]")
            console.print("[dim]Run: hk-bazaar watch-deals --dry-run[/dim]")
            raise typer.Exit(0)
        _render_outreach_table(attempts)


@app.command("pending-outreaches")
def pending_outreaches_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
) -> None:
    """Show outreach opportunities awaiting review (alias for list-outreaches)."""
    list_outreaches_cmd(limit=limit, platform=None, status=None)


@app.command("show-outreach")
def show_outreach_cmd(
    attempt_id: Annotated[int, typer.Argument(help="Outreach attempt ID")],
) -> None:
    """Show full detail for one outreach opportunity."""
    init_db()
    with db_session() as session:
        attempt = get_outreach_attempt(session, attempt_id)
        if attempt is None:
            raise typer.BadParameter(f"Outreach attempt {attempt_id} not found")

        spread = _outreach_spread(attempt)
        reasons = "\n".join(f"  • {reason}" for reason in attempt.qualification_reasons)
        body = (
            f"[bold]{attempt.sku}[/bold] — {attempt.listing_title}\n\n"
            f"Platform: {attempt.platform.value}\n"
            f"Status:   {attempt.status.value}\n"
            f"URL:      {attempt.listing_url}\n\n"
            f"Listing price: HKD {attempt.listing_price:,.0f}\n"
            f"Buy target:    HKD {attempt.buy_target:,.0f}\n"
            f"Proposed bid:  HKD {attempt.proposed_bid:,.0f}\n"
            f"Spread:        HKD {spread:+,.0f}\n\n"
            f"[bold]Why qualified:[/bold]\n{reasons}\n\n"
            f"[bold]Message ({template_hint(attempt.platform.value)}):[/bold]\n{attempt.message}\n\n"
            f"[dim]Approve: hk-bazaar approve-outreach {attempt.id}[/dim]"
        )
        console.print(Panel(body, title=f"Outreach #{attempt.id}", border_style="green"))


def template_hint(platform: str) -> str:
    from hk_bazaar.outreach.platform_outreach import template_for_platform

    return template_for_platform(platform).replace(".txt.j2", "")


@app.command("cancel-outreach")
def cancel_outreach_cmd(
    attempt_id: Annotated[int, typer.Argument(help="Outreach attempt ID")],
) -> None:
    """Cancel a single outreach attempt."""
    init_db()
    with db_session() as session:
        attempt = get_outreach_attempt(session, attempt_id)
        if attempt is None:
            raise typer.BadParameter(f"Outreach attempt {attempt_id} not found")
        if attempt.status not in ACTIONABLE_OUTREACH_STATUSES:
            raise typer.BadParameter(
                f"Attempt {attempt_id} cannot be cancelled (status={attempt.status.value})"
            )
        cancel_outreach(session, attempt)
        session.commit()
    console.print(f"[green]Cancelled outreach #{attempt_id}[/green]")


@app.command("clear-outreach-queue")
def clear_outreach_queue_cmd(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")] = False,
    platform: Annotated[str | None, typer.Option("--platform", "-p", help="Only clear one platform")] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Only clear one status")] = None,
) -> None:
    """Cancel all queued outreaches (dry_run + pending) so watch-deals can re-scan."""
    init_db()

    platform_filter = None
    if platform:
        try:
            platform_filter = Platform(platform.strip().lower())
        except ValueError as exc:
            raise typer.BadParameter(f"Unknown platform: {platform}") from exc

    status_filter = None
    if status:
        try:
            status_filter = (OutreachStatus(status.strip().lower()),)
        except ValueError as exc:
            raise typer.BadParameter(f"Unknown status: {status}") from exc

    with db_session() as session:
        pending = list_outreach_attempts(
            session,
            statuses=status_filter,
            platform=platform_filter,
            limit=10_000,
        )
        if not pending:
            console.print("[yellow]Queue is already empty.[/yellow]")
            raise typer.Exit(0)

        if not yes:
            console.print(f"[yellow]About to cancel {len(pending)} outreach attempt(s).[/yellow]")
            if not typer.confirm("Continue?"):
                raise typer.Exit(0)

        count = clear_outreach_queue(
            session,
            statuses=status_filter,
            platform=platform_filter,
        )
        session.commit()

    console.print(f"[green]Cancelled {count} outreach attempt(s).[/green]")
    console.print("[dim]Re-scan: hk-bazaar watch-deals --dry-run[/dim]")


@app.command("approve-outreach")
def approve_outreach_cmd(
    attempt_id: Annotated[int, typer.Argument(help="Outreach attempt ID")],
    bid: Annotated[float | None, typer.Option("--bid", help="Override proposed bid (HKD)")] = None,
) -> None:
    """Approve and send (or dry-run) an outreach attempt."""
    init_db()
    settings = get_settings()
    if settings.outreach_dry_run:
        console.print("[yellow]OUTREACH_DRY_RUN=true — will log actions only, not submit offers.[/yellow]")
    with db_session() as session:
        manager = OutreachManager(session)
        try:
            attempt = manager.approve_and_send(attempt_id, proposed_bid=bid)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    console.print(
        f"[green]Attempt #{attempt.id}[/green] status={attempt.status.value} "
        f"bid=HKD {attempt.proposed_bid:,.0f}"
    )


@app.command("simulate-bid")
def simulate_bid_cmd(
    ref: Annotated[str, typer.Argument(help="Listing DB id or URL fragment")],
) -> None:
    """Simulate qualification + proposed bid for a stored listing."""
    init_db()
    with db_session() as session:
        listing = resolve_listing_by_url_or_id(session, ref)
        if listing is None:
            raise typer.BadParameter(f"Listing not found: {ref}")
        result = OutreachManager(session).simulate_bid(listing)

    if not result.get("qualified"):
        console.print(f"[yellow]Not qualified:[/yellow] {result.get('reason')}")
        raise typer.Exit(0)

    console.print(f"[bold]{result['display_name']}[/bold] ({result['sku']})")
    console.print(f"  Listing price: HKD {result['listing_price']:,.0f}")
    console.print(f"  Buy target:    HKD {result['buy_target']:,.0f}")
    console.print(f"  Proposed bid:  HKD {result['proposed_bid']:,.0f}")
    for reason in result.get("reasons", []):
        console.print(f"  • {reason}")
    console.print("\n[bold]Message preview:[/bold]")
    console.print(str(result.get("message")))


@app.command("outreach-stats")
def outreach_stats_cmd() -> None:
    """Show outreach attempt statistics."""
    init_db()
    with db_session() as session:
        stats = get_outreach_stats(session)

    table = Table(title="Outreach stats", box=box.ROUNDED)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total attempts", str(stats["total"]))
    table.add_row("Created last 24h", str(stats["sent_today"]))
    for status, count in stats.get("by_status", {}).items():
        table.add_row(f"  {status}", str(count))
    console.print(table)


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: None, level="WARNING")
    app()