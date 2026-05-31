"""kijiji.ca apartments/condos scraper for Vancouver + metro.

Kijiji is the easiest high-volume rental source after rentfaster — the search
page uses stable data-testid selectors. ~40 listings per page; we paginate.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..http_client import get as http_get
from ..models import Listing
from .base import Scraper

log = logging.getLogger(__name__)

BEDS_RE = re.compile(r"(\d+(?:\.\d)?)")

# Same junk filter as craigslist — drop short-term / room-share / sublet noise.
JUNK_PATTERNS = re.compile(
    r"\b(short[\s-]?term|short[\s-]?stay|weekly|nightly|per night|"
    r"vacation|airbnb|sublet|sublease|roommate|room ?mate|room for rent|"
    r"room available|co[\s-]?living|shared (room|bathroom|kitchen|accommodation)|"
    r"furnished room|private room)\b",
    re.I,
)

# Kijiji location category IDs (verified by probing search results):
#   80003   = Greater Vancouver (covers Surrey, Delta, Langley, Burnaby, ...)
#   1700287 = City of Vancouver only
# Use 80003 for metro coverage.
GREATER_VANCOUVER_ID = 80003


class KijijiScraper(Scraper):
    source = "kijiji"

    def __init__(self, max_rent: int = 2000, min_rent: int = 500,
                 location_id: int = GREATER_VANCOUVER_ID, max_pages: int = 5):
        self.max_rent = max_rent
        self.min_rent = min_rent
        self.location_id = location_id
        self.max_pages = max_pages

    def fetch(self) -> list[Listing]:
        listings: list[Listing] = []
        seen: set[str] = set()
        fetched = 0
        for page in range(1, self.max_pages + 1):
            page_listings = self._fetch_page(page)
            if not page_listings:
                break
            fetched += len(page_listings)
            new_on_page = 0
            for listing in page_listings:
                if listing.external_id in seen:
                    continue
                seen.add(listing.external_id)
                if listing.price is not None and listing.price < self.min_rent:
                    continue
                blob = " ".join(filter(None, [listing.title, listing.description or ""]))
                if JUNK_PATTERNS.search(blob):
                    continue
                listings.append(listing)
                new_on_page += 1
            if new_on_page == 0:
                break  # paginated past the end
        log.info(
            "source=%s fetched=%d parsed=%d dropped=%d",
            self.source, fetched, len(listings), fetched - len(listings),
        )
        return listings

    def _fetch_page(self, page: int) -> list[Listing]:
        suffix = f"/page-{page}" if page > 1 else ""
        url = (
            f"https://www.kijiji.ca/b-apartments-condos/greater-vancouver"
            f"{suffix}/c37l{self.location_id}?ad=offering&price=__{self.max_rent}"
        )
        try:
            r = http_get(url)
            r.raise_for_status()
        except Exception as e:
            log.warning("kijiji page %d fetch failed: %s", page, e)
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select('section[data-testid="listing-card"]')
        out: list[Listing] = []
        for c in cards:
            try:
                out.append(self._parse(c))
            except Exception as e:
                log.debug("skipping malformed kijiji card: %s", e)
        return out

    def _parse(self, c) -> Listing:
        ext_id = c.get("data-listingid") or ""
        if not ext_id:
            raise ValueError("no data-listingid")

        a = c.select_one('a[data-testid="listing-link"]')
        url = a["href"] if a and a.has_attr("href") else ""
        if url and not url.startswith("http"):
            url = "https://www.kijiji.ca" + url
        title = a.get_text(strip=True) if a else "(no title)"

        price_el = c.select_one('[data-testid="listing-price"]')
        price = None
        if price_el:
            m = re.search(r"([\d,]+)", price_el.get_text())
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                except ValueError:
                    price = None

        loc_el = c.select_one('[data-testid="listing-location"]')
        location = loc_el.get_text(strip=True) if loc_el else None

        desc_el = c.select_one('[data-testid="listing-description"]')
        desc = desc_el.get_text(strip=True) if desc_el else None

        img_el = c.select_one('img[data-testid="listing-card-image"]')
        image_url = img_el.get("src") if img_el else None

        beds = baths = None
        for li in c.select('ul[data-testid="re-attribute-list-non-mobile"] li, '
                           'ul[data-testid="re-attribute-list-mobile"] li'):
            label = (li.get("aria-label") or "").lower()
            text = li.get_text(" ", strip=True)
            m = BEDS_RE.search(text)
            if not m:
                continue
            try:
                val = float(m.group(1))
            except ValueError:
                continue
            if "bed" in label:
                beds = val
            elif "bath" in label:
                baths = val

        return Listing(
            source=self.source,
            external_id=ext_id,
            url=url,
            title=title,
            price=price,
            beds=beds,
            baths=baths,
            sqft=None,
            address=location,
            city=_guess_city(location),
            posted_at=datetime.now(timezone.utc),
            description=desc,
            amenities=[],
            image_url=image_url,
            raw={"id": ext_id, "title": title, "price": price, "location": location},
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
