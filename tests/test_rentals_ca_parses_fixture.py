"""B1: rentals.ca fixture parser test.

Loads tests/fixtures/rentals_ca/sample.html (one real page, sanitized),
runs the parser, and asserts that ≥3 listings each have title, price, url.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apartment_hunter.scrapers.rentals_ca import RentalsCaScraper, _extract_store_response

FIXTURE = Path(__file__).parent / "fixtures" / "rentals_ca" / "sample.html"


@pytest.fixture(scope="module")
def listings():
    html = FIXTURE.read_text(encoding="utf-8")
    data = _extract_store_response(html)
    edges = data.get("data", {}).get("edges", []) or []
    scraper = RentalsCaScraper(max_rent=999_999)
    out = []
    for edge in edges:
        node = edge.get("node") or {}
        try:
            out.append(scraper._parse(node))
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
