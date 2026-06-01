"""Print the top 20 and bottom 20 scored listings with their sub-score
breakdown, so weights can be eyeballed against intent without writing SQL.

Usage:
    python scripts/audit_scores.py [--db PATH] [--n 20]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from apartment_hunter import db  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "listings.db"

SUBS = [
    ("score_price", "price"),
    ("score_location", "loc"),
    ("score_size", "size"),
    ("score_amenities", "amen"),
]


def _fmt_sub(v) -> str:
    return "  -  " if v is None else f"{v:.2f}"


def _print_row(r: sqlite3.Row) -> None:
    subs = "  ".join(f"{label}={_fmt_sub(r[col])}" for col, label in SUBS)
    title = (r["title"] or "")[:48]
    price = f"${r['price']}" if r["price"] is not None else "$  ?"
    score = f"{r['score']:.0f}" if r["score"] is not None else "  ?"
    print(f"  [{score:>3}] {price:>7}  {title:<48}  {subs}")
    print(f"        {r['source']}/{r['external_id']}  {r['url']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="audit_scores")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--n", type=int, default=20, help="how many at each end")
    args = p.parse_args(argv)

    conn = db.connect(args.db)
    cols = "source, external_id, url, title, price, score, " + ", ".join(c for c, _ in SUBS)

    top = conn.execute(
        f"SELECT {cols} FROM listings WHERE score IS NOT NULL "
        f"ORDER BY score DESC LIMIT ?",
        (args.n,),
    ).fetchall()
    bottom = conn.execute(
        f"SELECT {cols} FROM listings WHERE score IS NOT NULL "
        f"ORDER BY score ASC LIMIT ?",
        (args.n,),
    ).fetchall()

    scored = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE score IS NOT NULL"
    ).fetchone()[0]

    if not top:
        print("No scored listings found. Run a scrape or save the config to score.")
        return 0

    print(f"\n{scored} scored listings.  Sub-scores are 0-1; total is 0-100.\n")
    print(f"=== TOP {len(top)} ===")
    for r in top:
        _print_row(r)
    print(f"\n=== BOTTOM {len(bottom)} ===")
    for r in bottom:
        _print_row(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
