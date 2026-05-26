# Apartment Hunter

Scrapes Vancouver-area rental listings from multiple sites, scores them against your criteria, and emails you when high-scoring new listings appear.

**Sources (v1):** rentals.ca, rentfaster.ca, Vancouver Craigslist
**Target:** Vancouver + metro, under $2000/mo
**Schedule:** Runs locally via Windows Task Scheduler, twice daily

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

# 3. Edit your criteria
# Open config\criteria.yaml and tweak budget, neighborhoods, etc.

# 4. Smoke test (no email sent)
python -m apartment_hunter.run --once --dry-run

# 5. Real run
python -m apartment_hunter.run --once
```

---

## Web UI — browse, comment, track applications

After the scraper has populated your DB, launch the local UI:

```bash
python -m apartment_hunter.web
```

Then open http://127.0.0.1:5000 in your browser. Or just double-click `scripts\open_ui.bat`.

What you can do:
- **Browse** all collected listings in a grid sorted by score (or price/newest)
- **Filter** by status, source, max price, min beds, min score, free-text search
- **Click any card** for full details, photo, amenities, and a link to the original listing
- **Set status** per listing: `new → interested → contacted → viewing → applied → accepted/rejected/archived`
- **Add notes** that autosave as you type (great for "called landlord, awaiting reply" or "Sat 2pm viewing")
- **Hide** scams or noise without deleting them (toggle "Show hidden" to bring back)

All state lives in `data\listings.db` — shared with the scraper, so status/notes survive future runs and the same listing keeps its status if re-scraped.

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

---

## GitHub setup (first time)

1. **Install Git**: https://git-scm.com/download/win (accept defaults).
2. **Install GitHub CLI**: https://cli.github.com — easiest way to authenticate.
3. **Configure your identity** (once):
   ```bash
   git config --global user.name "Ricky Huang"
   git config --global user.email "rkyhuang03@gmail.com"
   ```
4. **Authenticate** (once):
   ```bash
   gh auth login
   ```
   Choose: GitHub.com → HTTPS → Login with browser. The token is stored in Windows Credential Manager.
5. **Push this project**:
   ```bash
   cd "C:\Users\Ricky\Documents\CodingProjects\apartment hunter"
   git init
   git add .gitignore                      # CRITICAL: do this FIRST so .env can never be staged
   git commit -m "Add gitignore"
   git add .
   git status                              # confirm .env is NOT listed
   git commit -m "Initial commit"
   git branch -M main
   gh repo create apartment-hunter --private --source=. --push
   ```

### Daily git flow

```bash
git status                  # what changed?
git add <files>             # stage specific files (avoid 'git add .' if unsure)
git commit -m "what you did"
git push
```

### If you accidentally commit `.env`

1. **Revoke the app password immediately** at https://myaccount.google.com/apppasswords
2. Generate a new one and update `.env`.
3. `git rm` alone does **not** remove secrets from history — the credential is what matters, not the file.

---

## Scheduling (Windows Task Scheduler)

1. Open Task Scheduler → Create Task (not "Create Basic Task").
2. **General** tab: name "Apartment Hunter", check "Run whether user is logged on or not" if you want background runs.
3. **Triggers** tab: New → Daily → 8:00 AM. Repeat for 6:00 PM.
4. **Actions** tab: New → Start a program → browse to `scripts\run_hunter.bat`.
5. **Conditions** tab: uncheck "Start the task only if the computer is on AC power" (laptops).
6. Save. Test by right-clicking the task → Run.

Output goes to `logs\run.log`.

---

## Project layout

```
config/criteria.yaml         # your scoring criteria — edit freely
src/apartment_hunter/
  run.py                     # entry point
  models.py                  # Listing model
  db.py                      # SQLite persistence
  scoring.py                 # weighted scorer
  alerter.py                 # Gmail digest sender
  dedupe.py                  # cross-source de-duplication
  scrapers/
    rentals_ca.py
    rentfaster.py
    craigslist.py
tests/                       # pytest
scripts/run_hunter.bat       # Task Scheduler entry point
scripts/open_ui.bat          # launches the web UI
src/apartment_hunter/
  web.py                     # Flask app
  templates/                 # HTML templates (Jinja + HTMX + Tailwind CDN)
data/listings.db             # SQLite DB (gitignored)
logs/run.log                 # run output (gitignored)
```

---

## Scraper endpoint troubleshooting

The three v1 sites all use Cloudflare. From a normal home IP they usually serve the JSON / RSS fine, but the exact endpoints occasionally change. If a run logs `0 listings` from a source:

### rentals.ca
1. Open https://rentals.ca/vancouver in Chrome.
2. Open DevTools → Network → filter `XHR` / `Fetch`.
3. Pan the map; watch which request returns JSON with listing data.
4. Copy the URL/params into `src/apartment_hunter/scrapers/rentals_ca.py` (`url` and `params` in `fetch`).

### rentfaster.ca
- The `city_id` for Vancouver may not be `3` — verify by browsing https://www.rentfaster.ca/bc/vancouver and watching the XHR call. Update `VANCOUVER_CITY_ID` in `scrapers/rentfaster.py`.

### craigslist
- If `403` persists, try the HTML search page (`/search/apa?max_price=2000`) and parse with BeautifulSoup instead of RSS. RSS access has been progressively restricted.

### General
- Run with `-v` to see HTTP details: `python -m apartment_hunter.run --once --dry-run -v`
- Save a real response to `tests/fixtures/` once you find the working endpoint — then you can iterate on parsing offline without re-hitting the site.

---

## Tuning your criteria

Edit `config/criteria.yaml`. The scorer produces 0–100. Listings at or above `alert_threshold` trigger an email. Lower the threshold if you want more alerts; raise it if you want fewer.
