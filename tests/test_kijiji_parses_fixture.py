"""B1: kijiji fixture parser test.

Loads tests/fixtures/kijiji/sample.html (one real search page, sanitized),
runs the parser, and asserts that ≥3 listings each have title, price, url.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from apartment_hunter.scrapers.kijiji import KijijiScraper

FIXTURE = Path(__file__).parent / "fixtures" / "kijiji" / "sample.html"


@pytest.fixture(scope="module")
def listings():
    html = FIXTURE.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('section[data-testid="listing-card"]')
    scraper = KijijiScraper()
    out = []
    for card in cards:
        try:
            out.append(scraper._parse(card))
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
