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