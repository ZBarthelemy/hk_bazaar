# hk_bazaar

Personal Hong Kong classifieds aggregator. Collects buy/sell listings from **asiaXPAT**, **Carousell**, and (optionally) **Facebook Marketplace** into a local SQLite database, with v1 deal-flagging heuristics.

## Quick start

```bash
# Install uv: https://docs.astral.sh/uv/
cd hk_bazaar
uv sync --extra dev
uv run playwright install chromium

cp .env.example .env
uv run hk-bazaar init-db

# Seed sample data (no network)
uv run hk-bazaar seed
uv run hk-bazaar find-deals

# Live scrape (asiaXPAT — public, no login)
uv run hk-bazaar scrape asiaxpat --max-pages 2

# Carousell (Playwright + Cloudflare)
uv run hk-bazaar scrape carousell --query "sofa" --max-price 2000 --max-pages 2

# Query & export
uv run hk-bazaar query --max-price 800 --category Furniture --limit 20
uv run hk-bazaar stats
uv run hk-bazaar export --format csv -o data/listings.csv
```

## CLI commands

| Command | Description |
|---------|-------------|
| `hk-bazaar init-db` | Create SQLite tables |
| `hk-bazaar scrape asiaxpat` | Scrape asiaXPAT classifieds |
| `hk-bazaar scrape carousell` | Scrape Carousell HK (Playwright) |
| `hk-bazaar scrape facebook` | Optional FB skeleton (disabled by default) |
| `hk-bazaar query` | Filter stored listings |
| `hk-bazaar find-deals` | v1 deal heuristics |
| `hk-bazaar stats` | Database summary |
| `hk-bazaar export` | CSV or JSON export |
| `hk-bazaar seed` | Insert test data |

## Project structure

```
src/hk_bazaar/
  cli.py              # Typer + Rich CLI
  config.py           # pydantic-settings
  database/           # SQLAlchemy models, CRUD
  scrapers/           # asiaxpat (working), carousell, facebook
  pipelines/          # cleaning + ingestion
  utils/              # HK districts, category taxonomy
  analyzers/          # deal_finder.py (extend here)
```

## Ethical & legal disclaimer

**Personal use only.** This tool is for finding second-hand bargains in Hong Kong for yourself.

- **Terms of Service**: Scraping may violate platform ToS (especially Facebook). You assume all risk.
- **Rate limiting**: Default 1.5s delay between requests. Do not run aggressive parallel scrapers.
- **PDPO**: Hong Kong's Personal Data (Privacy) Ordinance applies if you store seller info. Keep data local; do not redistribute.
- **Facebook**: High ban risk. Requires login session. **Disabled by default** — see `scrapers/facebook.py`.
- **Robots / courtesy**: Prefer low-frequency scheduled runs. Stop if a platform blocks you.

## Example workflows

### Daily bargain hunt

```bash
uv run hk-bazaar scrape asiaxpat --max-pages 3
uv run hk-bazaar scrape carousell --query "moving sale" --max-pages 2
uv run hk-bazaar find-deals --limit 15
```

### Furniture under HKD 800 on HK Island

```bash
uv run hk-bazaar query --category Furniture --max-price 800 --district "Central"
```

## Extending

### Add a new platform

1. Create `src/hk_bazaar/scrapers/newplatform.py` extending `BaseScraper`
2. Add enum value to `Platform` in `database/models.py`
3. Wire CLI in `cli.py`
4. Add category mapper in `utils/categories.py`

### Improve deal flagging

Edit `analyzers/deal_finder.py` — add rules, category-specific medians, condition scoring, or plug in embeddings later. See **Next steps** below.

## Configuration

Copy `.env.example` → `.env`. Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HK_BAZAAR_DATABASE_URL` | `sqlite:///data/hk_bazaar.db` | Database path |
| `HK_BAZAAR_REQUEST_DELAY_SECONDS` | `1.5` | Politeness delay |
| `HK_BAZAAR_FACEBOOK_ENABLED` | `false` | FB scraper gate |
| `HK_BAZAAR_DEAL_RECENT_DAYS` | `7` | Recency window for deals |

## Outreach & Bidding

**Philosophy:** Outreach is only triggered on **strong buying opportunities** relative to each SKU's `buy_target` in `data/bluebook/catalog.yaml` — **not** because a listing is at "excellent" reference price.

A listing qualifies when:
- It strongly matches a catalog SKU, **and**
- Price ≤ `buy_target × 1.15` (+15%), **or**
- Price ≤ `buy_target × 1.25` (+25%) with urgency keywords ("moving sale", "急售", etc.)

Proposed bid = **`buy_target × 0.95`**, rounded to HK$50 / HK$100.

### Safe workflow (recommended)

```bash
# 1. Scrape fresh listings
hk-bazaar scrape carousell -q "iPhone 13" -p 3

# 2. Scan for opportunities (dry-run ON by default)
hk-bazaar watch-deals --dry-run

# 3. Review queue
hk-bazaar pending-outreaches

# 4. Simulate one listing
hk-bazaar simulate-bid 42

# 5. Approve (still dry-run until OUTREACH_DRY_RUN=false)
hk-bazaar approve-outreach 1
hk-bazaar outreach-stats
```

### Configuration (`.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `HK_BAZAAR_OUTREACH_DRY_RUN` | `true` | Log only — no real offers |
| `HK_BAZAAR_OUTREACH_AUTO_APPROVE` | `false` | Never auto-send without approval |
| `HK_BAZAAR_OUTREACH_MAX_DAILY` | `6` | Max outreaches per 24h |
| `HK_BAZAAR_OUTREACH_COOLDOWN_DAYS` | `7` | Per-seller cooldown |
| `HK_BAZAAR_OUTREACH_BID_DISCOUNT` | `0.95` | Bid = buy_target × this |
| `HK_BAZAAR_OUTREACH_PLATFORMS` | `carousell` | Platforms to scan |
| `HK_BAZAAR_TELEGRAM_BOT_TOKEN` | — | Optional approval notifications |

### Warnings

- **Carousell / Facebook ToS** may prohibit automated offers — ban risk is real.
- **Dry-run first.** Export Carousell `storage_state` after manual login (`playwright-state/carousell.json`).
- Facebook outreach is **not enabled** in v1 (`OUTREACH_PLATFORMS=carousell` only).

## Development

```bash
uv run pytest tests/ -v
uv run ruff check src tests
uv run mypy src/hk_bazaar
```

## Roadmap

- [ ] Advanced deal scoring (condition × price, brand deprec curves)
- [ ] Telegram / email alerts for new deals
- [ ] Web dashboard (FastAPI + htmx)
- [ ] Price history charts per item category
- [ ] Embedding similarity ("find items like this cheaper")
- [ ] Scheduled cron / launchd jobs
- [ ] Alembic migrations when schema stabilizes

## Platform notes

See [docs/PLATFORMS.md](docs/PLATFORMS.md) for per-platform scraping details and selector maintenance.