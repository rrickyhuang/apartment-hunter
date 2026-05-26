from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..http_client import get as http_get
from ..models import Listing
from .base import Scraper

log = logging.getLogger(__name__)

BEDS_RE = re.compile(r"(\d+(?:\.\d)?)\s*(?:br|bed)", re.I)
SQFT_RE = re.compile(r"(\d{3,5})\s*(?:ft²|ft2|sqft|sq\.?\s*ft)", re.I)


class CraigslistScraper(Scraper):
    """Parses craigslist's search HTML. RSS is now Cloudflare-blocked but the
    HTML search page serves all 100s of listings on one page with structured
    data (li.cl-static-search-result)."""

    source = "craigslist"

    def __init__(self, max_rent: int = 2000, region: str = "vancouver"):
        self.max_rent = max_rent
        self.region = region

    def fetch(self) -> list[Listing]:
        url = (
            f"https://{self.region}.craigslist.org/search/apa"
            f"?max_price={self.max_rent}"
        )
        try:
            r = http_get(url)
            r.raise_for_status()
        except Exception as e:
            log.warning("craigslist fetch failed: %s", e)
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("li.cl-static-search-result")

        listings: list[Listing] = []
        for li in items:
            try:
                listings.append(self._parse(li))
            except Exception as e:
                log.debug("skipping malformed entry: %s", e)
        return listings

    def _parse(self, li) -> Listing:
        a = li.find("a")
        url = a["href"] if a and a.has_attr("href") else ""
        ext_id = url.rstrip("/").rsplit("/", 1)[-1].split(".")[0]

        title_el = li.select_one(".title")
        title = title_el.get_text(strip=True) if title_el else li.get("title", "(no title)")

        price = None
        price_el = li.select_one(".price")
        if price_el:
            m = re.search(r"\$?([\d,]+)", price_el.get_text())
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                except ValueError:
                    price = None

        location_el = li.select_one(".location")
        location = location_el.get_text(strip=True) if location_el else None

        beds = sqft = None
        if title:
            m = BEDS_RE.search(title)
            if m:
                try:
                    beds = float(m.group(1))
                except ValueError:
                    pass
            m = SQFT_RE.search(title)
            if m:
                try:
                    sqft = int(m.group(1))
                except ValueError:
                    pass

        return Listing(
            source=self.source,
            external_id=ext_id,
            url=url,
            title=title,
            price=price,
            beds=beds,
            baths=None,
            sqft=sqft,
            address=location,
            city=_guess_city(location),
            posted_at=datetime.now(timezone.utc),
            description=None,  # description requires per-listing fetch; skip in v1
            amenities=[],
            image_url=None,
            raw={"title": title, "price": price, "location": location, "url": url},
        )


_KNOWN_CITIES = [
    "Vancouver", "Burnaby", "Surrey", "Richmond", "New Westminster",
    "North Vancouver", "West Vancouver", "Coquitlam", "Port Coquitlam",
    "Port Moody", "Delta", "Langley", "Maple Ridge", "White Rock",
]


def _guess_city(location: str | None) -> str | None:
    if not location:
        return None
    loc_l = location.lower()
    for city in _KNOWN_CITIES:
        if city.lower() in loc_l:
            return city
    return None
