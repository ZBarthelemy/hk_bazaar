---
name: hk-bazaar-scan
description: Run the hk_bazaar scan and report new listings and cheap iPhone SKUs for asiaXPAT, Carousell, and Facebook. Use when the user asks to run the bazaar job, the iPhone scan, how many new cheap iPhones were found, or to make an offer on a listing.
---

# hk_bazaar scan

From the hk_bazaar repo, run `uv run hk-bazaar scan`. Do not ask which command to use. Do not scrape the three sources with separate commands.

Relay the command's stdout. It has one row each for asiaXPAT, Carousell, and Facebook: scraped, new, updated, cheap_iphones, and status. `cheap_iphones` counts only rows inserted on this run that match an `iphone_*` bluebook SKU and are priced under that SKU's reference. The list under the table is those listings.

A copy is written to `reports/latest-scan.txt`. When the user wants the last scan and not a new scrape, read that file and relay it.

The default search is `iphone`. It sorts newest first and keeps reading until a whole page is already in the database, or until 10 pages. Pass `--max-pages` only when the user asked for a different cap. `caught_up: no` means the cap was hit before that overlap, so older listings may still be missing.

## Offers

A scan does not contact sellers. When the user asks to make an offer, run `uv run hk-bazaar logins` first and relay it. That report says which platform still needs a login.

Draft one listing with `uv run hk-bazaar simulate-bid <listing id or url>`. Queue current matches with `uv run hk-bazaar watch-deals --dry-run`, then show the queue with `uv run hk-bazaar pending-outreaches`.

Leave `HK_BAZAAR_OUTREACH_DRY_RUN` on. `uv run hk-bazaar approve-outreach <id>` then logs the offer and does not send it. Send for real only when the user explicitly says to send that offer: set dry-run off, and only for a platform whose login line is `ready`. A live asiaXPAT message uses the Message seller box and needs `playwright-state/asiaxpat.json`. A live Carousell offer needs `playwright-state/carousell.json`. A live Facebook message needs `playwright-state/facebook.json`.
