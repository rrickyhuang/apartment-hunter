from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import db
from .alerter import render_digest, send_digest
from .scoring import Criteria, passes_hard_filters, score
from .settings import MissingEnvVar
from .scrapers.craigslist import CraigslistScraper
from .scrapers.kijiji import KijijiScraper
from .scrapers.rentals_ca import RentalsCaScraper
from .scrapers.rentfaster import RentfasterScraper

log = logging.getLogger("apartment_hunter")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "criteria.yaml"
DEFAULT_DB = PROJECT_ROOT / "data" / "listings.db"


def build_scrapers(c: Criteria):
    max_rent = int(c.hard_filters.get("max_rent", 2000))
    min_beds = float(c.hard_filters.get("min_beds", 0))
    min_rent = int(c.hard_filters.get("min_rent", 500))
    sources_cfg = c.hard_filters.get("sources", {}) or {}
    all_scrapers = [
        ("rentals_ca", RentalsCaScraper(max_rent=max_rent, min_beds=min_beds)),
        ("rentfaster", RentfasterScraper(max_rent=max_rent)),
        ("kijiji", KijijiScraper(max_rent=max_rent, min_rent=min_rent)),
        ("craigslist", CraigslistScraper(max_rent=max_rent, min_rent=min_rent)),
    ]
    return [s for name, s in all_scrapers if sources_cfg.get(name, True)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="apartment_hunter")
    p.add_argument("--once", action="store_true", help="run a single scrape cycle (default)")
    p.add_argument("--dry-run", action="store_true", help="don't send email; print top 10")
    p.add_argument("--print-email", action="store_true", help="render email HTML to data/email_preview.html and print the path")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv(PROJECT_ROOT / ".env")

    criteria = Criteria.load(args.config)
    conn = db.connect(args.db)
    scrapers = build_scrapers(criteria)

    total_seen = 0
    total_new = 0
    for s in scrapers:
        try:
            items = s.fetch()
        except Exception as e:
            log.exception("%s scraper crashed: %s", s.source, e)
            continue
        log.info("%s returned %d listings", s.source, len(items))
        total_seen += len(items)
        for listing in items:
            try:
                is_new = db.upsert(conn, listing)
                if is_new:
                    total_new += 1
                ok, _ = passes_hard_filters(listing, criteria)
                if ok:
                    sc = score(listing, criteria)
                else:
                    sc = {"total": 0.0, "price": 0.0, "location": 0.0, "size": 0.0, "amenities": 0.0}
                sub = {k: sc[k] for k in ("price", "location", "size", "amenities")}
                db.set_score(conn, listing.source, listing.external_id, sc["total"], sub=sub)
            except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
                log.warning("upsert/score failed for %s: %s", listing.url, e)

    log.info("seen=%d new=%d", total_seen, total_new)

    rows = db.unalerted_above(conn, criteria.alert_threshold)
    log.info("%d unalerted listings at/above threshold %.0f", len(rows), criteria.alert_threshold)

    if args.print_email:
        html = render_digest(rows, criteria.alert_threshold)
        out = Path(args.db).parent / "email_preview.html"
        out.write_text(html, encoding="utf-8")
        print(f"\nEmail preview ({len(rows)} listings) written to: {out}")

    if args.dry_run:
        print(f"\nTop {min(10, len(rows))} unalerted (dry run, no email):")
        for r in rows[:10]:
            print(f"  [{r['score']:.0f}] ${r['price']} - {r['title'][:60]} - {r['url']}")
        return 0

    if rows:
        try:
            send_digest(rows, criteria.alert_threshold)
            db.mark_alerted(conn, [(r["source"], r["external_id"]) for r in rows])
        except MissingEnvVar as e:
            log.error("%s", e)
            return 2
        except Exception as e:
            log.exception("email send failed: %s", e)
            return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
