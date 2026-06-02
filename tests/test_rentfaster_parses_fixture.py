"""B1: rentfaster fixture parser test.

Loads tests/fixtures/rentfaster/sample.json (20 items from the map API, sanitized),
runs the parser, and asserts that ≥3 listings each have title, price, url.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apartment_hunter.scrapers.rentfaster import RentfasterScraper

FIXTURE = Path(__file__).parent / "fixtures" / "rentfaster" / "sample.json"


@pytest.fixture(scope="module")
def listings():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    items = data.get("listings", [])
    scraper = RentfasterScraper()
    out = []
    for item in items:
        try:
            out.append(scraper._parse(item))
        except Exception:
            pass
    return out


def test_parses_at_least_three(listings):
    assert len(listings) >= 3, f"expected ≥3 listings, got {len(listings)}"


def test_title_present(listings):
    for l in listings[:3]:
        assert l.title and isinstance(l.title, str)


def test_price_present(listings):
    with_price = [l for l in listings if l.price is not None]
    assert len(with_price) >= 3, "expected ≥3 listings with a non-None price"


def test_url_present(listings):
    for l in listings[:3]:
        assert l.url and l.url.startswith("http")
