from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Listing

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS listings (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    price INTEGER,
    beds REAL,
    baths REAL,
    sqft INTEGER,
    address TEXT,
    city TEXT,
    lat REAL,
    lng REAL,
    posted_at TEXT,
    description TEXT,
    amenities TEXT,
    image_url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    score REAL,
    alerted INTEGER NOT NULL DEFAULT 0,
    raw TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT NOT NULL DEFAULT '',
    hidden INTEGER NOT NULL DEFAULT 0,
    status_updated_at TEXT,
    starred INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, external_id)
);
"""

INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_first_seen ON listings(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_alerted ON listings(alerted);
CREATE INDEX IF NOT EXISTS idx_score ON listings(score);
CREATE INDEX IF NOT EXISTS idx_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_hidden ON listings(hidden);
CREATE INDEX IF NOT EXISTS idx_starred ON listings(starred);
"""

# Statuses the UI cycles through. Order matters — used for filter pills.
STATUSES = [
    "new", "interested", "contacted", "viewing",
    "applied", "accepted", "rejected", "archived",
]


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after v1 if upgrading an older DB."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(listings)")}
    for col, ddl in [
        ("status", "ALTER TABLE listings ADD COLUMN status TEXT NOT NULL DEFAULT 'new'"),
        ("notes", "ALTER TABLE listings ADD COLUMN notes TEXT NOT NULL DEFAULT ''"),
        ("hidden", "ALTER TABLE listings ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"),
        ("status_updated_at", "ALTER TABLE listings ADD COLUMN status_updated_at TEXT"),
        ("starred", "ALTER TABLE listings ADD COLUMN starred INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in cols:
            conn.execute(ddl)
    conn.commit()


def connect(db_path: Path | str) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(TABLE_DDL)
    _migrate(conn)
    conn.executescript(INDEX_DDL)
    return conn


def set_status(conn: sqlite3.Connection, source: str, external_id: str, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    conn.execute(
        "UPDATE listings SET status=?, status_updated_at=? WHERE source=? AND external_id=?",
        (status, _now_iso(), source, external_id),
    )
    conn.commit()


def set_notes(conn: sqlite3.Connection, source: str, external_id: str, notes: str) -> None:
    conn.execute(
        "UPDATE listings SET notes=? WHERE source=? AND external_id=?",
        (notes, source, external_id),
    )
    conn.commit()


def set_starred(conn: sqlite3.Connection, source: str, external_id: str, starred: bool) -> None:
    conn.execute(
        "UPDATE listings SET starred=? WHERE source=? AND external_id=?",
        (1 if starred else 0, source, external_id),
    )
    conn.commit()


def set_hidden(conn: sqlite3.Connection, source: str, external_id: str, hidden: bool) -> None:
    conn.execute(
        "UPDATE listings SET hidden=? WHERE source=? AND external_id=?",
        (1 if hidden else 0, source, external_id),
    )
    conn.commit()


def get_one(conn: sqlite3.Connection, source: str, external_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM listings WHERE source=? AND external_id=?", (source, external_id)
    ).fetchone()


def query_listings(
    conn: sqlite3.Connection,
    *,
    statuses: list[str] | None = None,
    sources: list[str] | None = None,
    min_score: float | None = None,
    max_price: int | None = None,
    min_beds: float | None = None,
    show_hidden: bool = False,
    starred_only: bool = False,
    search: str | None = None,
    sort: str = "score_desc",
    limit: int = 500,
) -> list[sqlite3.Row]:
    where = []
    params: list = []
    if not show_hidden:
        where.append("hidden = 0")
    if starred_only:
        where.append("starred = 1")
    if statuses:
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    if sources:
        where.append(f"source IN ({','.join('?' * len(sources))})")
        params.extend(sources)
    if min_score is not None:
        where.append("(score IS NULL OR score >= ?)")
        params.append(min_score)
    if max_price is not None:
        where.append("(price IS NULL OR price <= ?)")
        params.append(max_price)
    if min_beds is not None:
        where.append("(beds IS NULL OR beds >= ?)")
        params.append(min_beds)
    if search:
        where.append("(title LIKE ? OR address LIKE ? OR city LIKE ? OR notes LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like])
    sort_sql = {
        "score_desc": "score DESC NULLS LAST",
        "price_asc": "price ASC NULLS LAST",
        "price_desc": "price DESC NULLS LAST",
        "newest": "first_seen_at DESC",
    }.get(sort, "score DESC")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"SELECT * FROM listings {where_sql} ORDER BY {sort_sql} LIMIT ?"
    params.append(limit)
    return list(conn.execute(sql, params))


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) c FROM listings WHERE hidden=0 GROUP BY status"
    ).fetchall()
    return {r["status"]: r["c"] for r in rows}


def source_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT source, COUNT(*) c FROM listings WHERE hidden=0 GROUP BY source"
    ).fetchall()
    return {r["source"]: r["c"] for r in rows}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert(conn: sqlite3.Connection, listing: Listing) -> bool:
    """Insert or update a listing. Returns True if it was new."""
    cur = conn.execute(
        "SELECT 1 FROM listings WHERE source=? AND external_id=?",
        (listing.source, listing.external_id),
    )
    existed = cur.fetchone() is not None
    now = _now_iso()
    data = {
        "source": listing.source,
        "external_id": listing.external_id,
        "url": listing.url,
        "title": listing.title,
        "price": listing.price,
        "beds": listing.beds,
        "baths": listing.baths,
        "sqft": listing.sqft,
        "address": listing.address,
        "city": listing.city,
        "lat": listing.lat,
        "lng": listing.lng,
        "posted_at": listing.posted_at.isoformat() if listing.posted_at else None,
        "description": listing.description,
        "amenities": json.dumps(listing.amenities),
        "image_url": listing.image_url,
        "first_seen_at": listing.first_seen_at.isoformat(),
        "last_seen_at": now,
        "raw": json.dumps(listing.raw, default=str),
    }
    if existed:
        conn.execute(
            """UPDATE listings SET
                url=:url, title=:title, price=:price, beds=:beds, baths=:baths,
                sqft=:sqft, address=:address, city=:city, lat=:lat, lng=:lng,
                posted_at=:posted_at, description=:description, amenities=:amenities,
                image_url=:image_url, last_seen_at=:last_seen_at, raw=:raw
               WHERE source=:source AND external_id=:external_id""",
            data,
        )
    else:
        conn.execute(
            """INSERT INTO listings
               (source, external_id, url, title, price, beds, baths, sqft,
                address, city, lat, lng, posted_at, description, amenities,
                image_url, first_seen_at, last_seen_at, raw)
               VALUES
               (:source, :external_id, :url, :title, :price, :beds, :baths, :sqft,
                :address, :city, :lat, :lng, :posted_at, :description, :amenities,
                :image_url, :first_seen_at, :last_seen_at, :raw)""",
            data,
        )
    conn.commit()
    return not existed


def set_score(conn: sqlite3.Connection, source: str, external_id: str, score: float) -> None:
    conn.execute(
        "UPDATE listings SET score=? WHERE source=? AND external_id=?",
        (score, source, external_id),
    )
    conn.commit()


def all_listings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM listings"))


def unalerted_above(conn: sqlite3.Connection, threshold: float) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM listings WHERE alerted=0 AND score >= ? ORDER BY score DESC",
            (threshold,),
        )
    )


def mark_alerted(conn: sqlite3.Connection, items: Iterable[tuple[str, str]]) -> None:
    conn.executemany(
        "UPDATE listings SET alerted=1 WHERE source=? AND external_id=?", list(items)
    )
    conn.commit()
