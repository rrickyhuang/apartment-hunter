# Apartment Hunter

Scrapes Vancouver-area rental listings from multiple sites, scores them against your criteria, and emails you when high-scoring new listings appear.

**Sources:** rentals.ca, rentfaster.ca, Kijiji, Vancouver Craigslist
**Target:** Vancouver + metro, under $2000/mo
**Scheduling:** Windows Task Scheduler (always-on) **and/or** an in-app scheduler (runs while the web UI is open)

---

## Quick start

```bash
# 1. Set up Python environment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure secrets
copy .env.example .env
# Edit .env and add your Gmail app password (see below)

# 3. Edit your criteria (either edit the YAML directly or use the UI at /config)
# config\criteria.yaml — budget, neighborhoods, sources, schedule, etc.

# 4. Smoke test (no email sent)
python -m apartment_hunter.run --once --dry-run

# 5. Real run
python -m apartment_hunter.run --once
```

---

## Web UI — browse, comment, track applications, configure

After the scraper has populated your DB, launch the local UI:

```bash
python -m apartment_hunter.web
```

Then open http://127.0.0.1:5000 in your browser. Or just double-click `scripts\open_ui.bat`.

What you can do:
- **Browse** all collected listings in a grid sorted by score (or price/newest)
- **Filter** by status, source, max price, min beds, min score, free-text search
- **Star** favorites and toggle a starred-only view
- **Hide non-viable** listings (anything below `min_rent`) — on by default, with a toggle to show them
- **Click any card** for full details, photo, amenities, and a link to the original listing
- **Set status** per listing: `new → interested → contacted → viewing → applied → accepted/rejected/archived`
- **Add notes** that autosave as you type (great for "called landlord, awaiting reply" or "Sat 2pm viewing")
- **Hide** scams or noise without deleting them (toggle "Show hidden" to bring back)
- **Scrape on demand** with the button in the header — runs the full pipeline in the background with a live status pill
- **Edit criteria** at `/config` — saves to `criteria.yaml` and re-scores every listing in the DB
- **Auto-scrape scheduler** on `/config` — enable a background loop that re-runs the scrape every N minutes while the UI is open

### Accessing from your phone (same Wi-Fi)

`open_ui.bat` binds to `0.0.0.0` so other devices on your network can reach the UI. One-time Windows Firewall rule (PowerShell as admin):

```powershell
New-NetFirewallRule -DisplayName "Apartment Hunter" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow
```

Find your PC's LAN IP with `ipconfig` (look for IPv4 under your Wi-Fi adapter, typically `192.168.x.x`) and visit `http://192.168.x.x:5000` from your phone. The UI is mobile-responsive.

⚠ No auth — anyone on the Wi-Fi can browse and edit. For cellular/away access, use [Tailscale](https://tailscale.com) rather than port-forwarding.

### State

All state lives in `data\listings.db` — shared with the scraper, so status/notes survive future runs and the same listing keeps its status if re-scraped.

---

## Scheduling

You have two independent options. Use either or both.

### Option A — Windows Task Scheduler (always on)

Runs even when the web UI is closed. A task named `ApartmentHunter` is already registered to run `scripts\run_hunter.bat` daily at 9:00 AM and 9:00 PM with "start when available" (so missed runs fire on next boot). Output goes to `logs\run.log`.

To inspect or change it:

```powershell
# Inspect
Get-ScheduledTask -TaskName ApartmentHunter
(Get-ScheduledTask -TaskName ApartmentHunter).Triggers

# Test now
Start-ScheduledTask -TaskName ApartmentHunter

# Change interval / times — easiest via the GUI:
# Task Scheduler → Library → ApartmentHunter → Properties → Triggers

# Remove
Unregister-ScheduledTask -TaskName ApartmentHunter -Confirm:$false
```

To recreate from scratch:

```powershell
$action = New-ScheduledTaskAction -Execute 'C:\Users\Ricky\Documents\CodingProjects\apartment hunter\scripts\run_hunter.bat'
$t1 = New-ScheduledTaskTrigger -Daily -At 9:00AM
$t2 = New-ScheduledTaskTrigger -Daily -At 9:00PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'ApartmentHunter' -Action $action -Trigger @($t1,$t2) -Settings $settings -Force
```

**If the PC is off at the scheduled time:** the task can't fire. With `StartWhenAvailable` set, it'll run as soon as you boot. Wake-from-sleep is possible but not configured.

### Option B — In-app scheduler (UI must be running)

Toggle on `/config` ("Auto-scrape schedule" section). Persists to `criteria.yaml`:

```yaml
schedule:
  enabled: true
  interval_minutes: 60
```

A daemon thread re-reads this every 30s, so changes take effect without restarting the UI. Stops the moment you close `python -m apartment_hunter.web`.

---

## Gmail app password setup

Gmail blocks regular-password SMTP login. You need a 16-character app password.

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. App name: `apartment-hunter` → Create
4. Copy the 16-character code (spaces don't matter) into `.env`:
   ```
   GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
   ```
5. **Never paste this into chat, code, or commit it.** If it leaks, revoke it immediately on the same page.

If you accidentally commit `.env`: revoke the app password immediately, generate a new one, and update `.env`. `git rm` alone does not remove secrets from history — the credential is what matters.

---

## Tuning your criteria

Either edit `config/criteria.yaml` directly or use the `/config` page in the web UI (which validates inputs and re-scores the whole DB on save).

The scorer produces 0–100. Listings at or above `alert_threshold` trigger an email. Lower the threshold for more alerts, raise it for fewer.

Weights (price/location/size/amenities) must sum to 1.0. `min_rent` is a hard filter — listings below it are stored but never alerted and hidden by default in the UI.

---

## Project layout

```
config/criteria.yaml              # scoring criteria + schedule — edit freely
src/apartment_hunter/
  run.py                          # scraper entry point (--once / --dry-run)
  web.py                          # Flask app + in-app scheduler
  models.py                       # Listing model
  db.py                           # SQLite persistence
  scoring.py                      # weighted scorer + hard filters
  alerter.py                      # Gmail digest sender
  dedupe.py                       # cross-source de-duplication
  http_client.py                  # shared requests session
  scrapers/
    base.py
    rentals_ca.py
    rentfaster.py
    kijiji.py
    craigslist.py
  templates/                      # Jinja + HTMX + Tailwind CDN
    base.html, index.html, listing.html, config.html
    _card_status.html, _scrape_button.html, _star_button.html, _status_pill.html
tests/                            # pytest
scripts/run_hunter.bat            # Task Scheduler entry point
scripts/open_ui.bat               # launches the web UI
data/listings.db                  # SQLite DB (gitignored)
logs/run.log                      # run output (gitignored)
```

---

## Scraper endpoint troubleshooting

All four sites sit behind Cloudflare or similar. From a normal home IP they usually serve the JSON / HTML fine, but endpoints occasionally change. If a run logs `0 listings` from a source:

### rentals.ca
Parses the SSR'd HTML page at `https://rentals.ca/vancouver?page=N`, extracting the inline `App.store.search = { response: {…} }` JSON hydration blob. The public JSON API (`/phoenix/api/v1/listings`) returns 500 without a browser-issued CSRF token and is not used. If the page layout changes:
1. Run `python scripts/probe_rentalsca.py` to confirm the hydration marker still matches `response: {`.
2. If broken, view-source on the page and find the new wrapper containing the `edges[].node` array — update `RESPONSE_MARKER` in `scrapers/rentals_ca.py`.

### rentfaster.ca
The `city_id` for Vancouver may not be `3` — verify by browsing https://www.rentfaster.ca/bc/vancouver and watching the XHR call. Update `VANCOUVER_CITY_ID` in `scrapers/rentfaster.py`.

### kijiji
Kijiji renders listings server-side under `/b-apartments-condos/...`. If the layout changes, inspect the listing card markup and update the selectors in `scrapers/kijiji.py`.

### craigslist
If `403` persists, try the HTML search page (`/search/apa?max_price=2000`) and parse with BeautifulSoup instead of RSS. RSS access has been progressively restricted.

### General
- Run with `-v` to see HTTP details: `python -m apartment_hunter.run --once --dry-run -v`
- Save a real response to `tests/fixtures/` once you find the working endpoint — then you can iterate on parsing offline without re-hitting the site.

---

## Daily git flow

```bash
git status                  # what changed?
git add <files>             # stage specific files
git commit -m "what you did"
git push
```
