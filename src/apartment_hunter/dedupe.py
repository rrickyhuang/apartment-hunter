from __future__ import annotations

import re
import sqlite3
from collections import defaultdict


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm_address(addr: str | None) -> str:
    if not addr:
        return ""
    return _NON_ALNUM.sub(" ", addr.lower()).strip()


def find_duplicate_groups(conn: sqlite3.Connection) -> list[list[tuple[str, str]]]:
    """Return groups of (source, external_id) tuples that look like the same unit
    posted on multiple sites. Match key: normalized address + price bucket + beds."""
    rows = conn.execute(
        "SELECT source, external_id, address, price, beds FROM listings WHERE address IS NOT NULL"
    ).fetchall()

    buckets: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    for r in rows:
        addr = _norm_address(r["address"])
        if not addr:
            continue
        price_bucket = (r["price"] or 0) // 50  # within $50
        key = (addr, price_bucket, r["beds"])
        buckets[key].append((r["source"], r["external_id"]))

    return [group for group in buckets.values() if len(group) > 1]
