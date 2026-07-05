# Platform scraping notes

## 1. asiaXPAT (easiest)

- **URL**: https://hongkong.asiaxpat.com/classifieds
- **Auth**: None — fully public
- **Method**: `httpx` + `selectolax`
- **Index**: Listing cards use `data-photo-carousel-url-value="/classifieds/{id}"`
- **Detail**: `schema.org/Product` JSON-LD in `<script type="application/ld+json">`
- **Pagination**: `?page=2` (30 listings per page as of 2026-07)
- **Maintenance**: Re-inspect card HTML when layout changes; update `asiaxpat.py`

## 2. Carousell HK (moderate)

- **URL**: https://www.carousell.com.hk/
- **Auth**: None for browse, but **Cloudflare** challenge on raw HTTP
- **Method**: Playwright Chromium + `__NEXT_DATA__` JSON or HTML card fallback
- **Search**: `/search/{query}` with optional `?page=N`
- **Internal API** (undocumented, use DevTools):

  ```
  POST https://www.carousell.com.hk/api-service/search/products/v4/
  GET  https://www.carousell.com.hk/api-service/product/{id}/
  ```

  Replay with session cookies from Playwright `storage_state` if you want to bypass DOM parsing.

- **Maintenance**: Cloudflare and Next.js bundles change often — expect breakage.

## 3. Facebook Marketplace (hardest)

- **URL**: https://www.facebook.com/marketplace/hongkong/
- **Auth**: **Required** — export Playwright `storage_state` after manual login
- **Official APIs**: None for consumer listing reads (partner upload API only)
- **Risks**: Account ban, CAPTCHA, GraphQL `doc_id` rotation
- **Enable**: `HK_BAZAAR_FACEBOOK_ENABLED=true` + session file path
- **Skeleton**: `scrapers/facebook.py` — extend via GraphQL interception in DevTools

### Facebook session export (one-time)

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.facebook.com/login")
    input("Log in manually, then press Enter...")
    context.storage_state(path="playwright-state/facebook.json")
    browser.close()
```

Never commit `playwright-state/` to git.