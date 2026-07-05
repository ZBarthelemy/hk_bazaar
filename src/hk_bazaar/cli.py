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
from rich.table import Table

from hk_bazaar.analyzers.deal_finder import find_deals
from hk_bazaar.config import get_settings
from hk_bazaar.database.crud import get_stats, query_listings
from hk_bazaar.database.engine import get_session, init_db
from hk_bazaar.database.models import Platform
from hk_bazaar.pipelines.ingestion import ingest_listings
from hk_bazaar.scrapers.asiaxpat import AsiaXpatScraper
from hk_bazaar.scrapers.carousell import CarousellScraper
from hk_bazaar.scrapers.facebook import FacebookMarketplaceScraper

app = typer.Typer(
    name="hk-bazaar",
    help="Hong Kong classifieds aggregator — asiaXPAT, Carousell, Facebook Marketplace",
    no_args_is_help=True,
)
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
) -> None:
    """Flag potential deals using v1 heuristics."""
    init_db()
    rows: list[tuple[float, str, str, str]] = []
    with db_session() as session:
        deals = find_deals(session, limit=limit)
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


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: None, level="WARNING")
    app()