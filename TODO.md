# Apartment Hunter — TODO

---

## Scraper

### Craigslist listings missing photos
The craigslist scraper in `scrapers/craigslist.py:102–108` extracts image IDs from a JSON blob in the
listing index page. These are often absent or fail silently — `image_map.get(post_id)` returns `None`.
Options: load each listing's detail page to grab the first `<img>` in `.slide`, or fall back to a
placeholder. Loading detail pages is slower but gives better coverage.

---

## Email / Alerting

### Review and improve alert email format
`alerter.py` sends an HTML digest via Gmail SMTP. Current format is minimal.
Improvements to consider:
- Clickable listing titles that link back to the local web UI (`http://localhost:5000/listing/…`)
- Score bar or coloured badge per listing
- "Mark as interested" one-click link (would need a token-based route in `web.py` since email clients
  can't POST)
- Group by score tier or neighbourhood
- The email is triggered by `run.py` when `--dry-run` is NOT set; SMTP creds live in env vars
  (`ALERT_FROM`, `ALERT_TO`, `ALERT_PASSWORD` — check `alerter.py:60–70`)

---

## Scoring

### Review scoring criteria — does it reflect what I'm looking for?
Scoring logic is in `scoring.py:113–122`. Sub-scores are: `price`, `location`, `size`, `amenities`.
Weights are configured in `config/criteria.yaml` and must sum to 1.0.
Things to audit:
- `location` sub-score: how are preferred neighbourhoods matched? Fuzzy string match on `address`/`city`
- `amenities` sub-score: what keywords trigger a match vs `nice_to_have` list in criteria.yaml?
- `price` sub-score: is the gradient between `target_rent` and `max_rent` steep/shallow enough?
- Run `SELECT score, title, price, address FROM listings ORDER BY score DESC LIMIT 20` to sanity-check
  that top-scored listings actually look good
- Config UI is at `/config` — saving re-scores all listings in the DB

---

## UX

### "Back to listings" button should remember the previous view
On the listing detail page the back link always returns to the list view, even if you arrived
from `/map`. Track the referring view (query param or `document.referrer`) and route back
accordingly.

### Default to opening listings in a new tab
Clicking a card on the list/map should open the detail view in a new tab by default, so the
previous filter/scroll/map state is preserved without needing back navigation.

### Status change on the detail view is unintuitive
Revisit the status control on `/listing/<source>/<id>` — current placement / interaction is
unclear. Consider a prominent labelled dropdown or a row of status pills near the title.

### Show more detail in the listing detail view
Surface whatever else is available on the row: description, amenities, sqft, address, posted/first-seen
timestamps, source-specific fields, all photos rather than just the hero image.

### Clarify "not interested" vs "archived"
Decide whether "not interested" is a distinct status or just an alias for `archived`. If distinct,
add it to the status enum (`db.py`, status pill palette in `base.html`, map legend). If it's the
same, rename `archived` → `not_interested` for clarity, or document the mapping in the UI.

---

## New Features

### Email / text tool for contacting listings
A template-based outreach composer. Rough design:
- Button on the listing detail page (`/listing/<source>/<id>`) that opens a modal with a pre-filled
  template (name, viewing availability, questions)
- Templates stored in `config/` as plain text with `{{price}}`, `{{address}}` placeholders
- "Copy to clipboard" is the safest first version; actual send (mailto: link or SMTP) as a follow-up
- Could log outreach attempts to a new `contacts` table or reuse the `notes` field + status change

### Track responses and manage viewings
Builds on the existing `status` workflow (`new → interested → contacted → viewing → applied`).
Ideas:
- Add a `contacted_at` timestamp column (migration in `db.py:_migrate`)
- Add a `viewing_at` datetime field for scheduled viewings
- A `/viewings` page that lists upcoming viewings sorted by date
- Response tracking: a `response` field (no response / positive / negative / ghosted)
- Could integrate with the calendar (Google Calendar API or just an `.ics` export)

### Persist filter state when switching between List and Map views
Currently the query string is lost when navigating between `/` and `/map`.
Options:
- Store last-used filters in `localStorage` and restore them on page load
- Pass the current query string as a param in the nav links (e.g. `/map?{{ request.query_string.decode() }}`)
  — the simpler approach, already works since both views share `_filters.html` and `_parse_filters()`
- Hybrid view (list + map side-by-side): feasible with CSS grid; map takes right half, card list scrolls
  on the left; clicking a card flies the map to that marker

---

## From This Session (unfinished / deferred)

### Geocoding backfill (v2 of map view)
Only rentfaster rows (~420 / 958) have lat/lng. craigslist and kijiji need geocoding from address.
Deferred intentionally — map shipped with rentfaster-only markers.

Plan:
- Add a `geocode_cache(address_normalized TEXT PRIMARY KEY, lat REAL, lng REAL, geocoded_at TEXT, failed INTEGER)`
  table so re-scrapes of the same address are free
- Background daemon thread (mirror of `_scheduler_loop` in `web.py`) that geocodes rows where
  `address IS NOT NULL AND lat IS NULL`, 1 req/sec (Nominatim hard rate limit)
- Append `, Vancouver, BC, Canada` to disambiguate free-text craigslist/kijiji addresses
- Store `geocoded_at` and a `geocode_failed` flag so failed addresses aren't retried forever
- Nominatim usage policy: 1 req/sec, real User-Agent header, personal use only — if usage grows,
  switch to a local Nominatim Docker container
