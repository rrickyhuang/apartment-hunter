"""B1: craigslist fixture parser test.

Loads tests/fixtures/craigslist/sample.html (HTML search page, sanitized) and
tests/fixtures/craigslist/sample_sapi.json (image sapi response, sanitized),
runs the parser, and asserts that ≥3 listings each have title, price, url.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from apartment_hunter.scrapers.craigslist import CraigslistScraper

FIXTURES = Path(__file__).parent / "fixtures" / "craigslist"


def _build_image_map(sapi_data: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in sapi_data.get("data", {}).get("items", []) or []:
        try:
            post_id = str(item[0])
            for field in item[5:]:
                if isinstance(field, list) and field and field[0] == 4 and len(field) > 1:
                    first = field[1]
                    if isinstance(first, str) and first.startswith("3:"):
                        out[post_id] = f"https://images.craigslist.org/{first[2:]}_300x300.jpg"
                    break
        except Exception:
            pass
    return out


@pytest.fixture(scope="module")
def listings():
    html = (FIXTURES / "sample.html").read_text(encoding="utf-8")
    sapi_data = json.loads((FIXTURES / "sample_sapi.json").read_text(encoding="utf-8"))
    image_map = _build_image_map(sapi_data)
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.cl-static-search-result")
    scraper = CraigslistScraper()
    out = []
    for li in items:
        try:
            l = scraper._parse(li, image_map)
            if l is not None:
                out.append(l)
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
