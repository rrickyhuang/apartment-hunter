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
POST_ID_RE = re.compile(r"/(\d{8,12})\.html")

# Craigslist is high-noise. Drop listings whose title screams short-term /
# vacation / sublet / room-rental — Ricky wants real apartments.
JUNK_PATTERNS = re.compile(
    r"\b(short[\s-]?term|short[\s-]?stay|weekly|nightly|per night|monthly only|"
    r"vacation|airbnb|sublet|sublease|roommate|room ?mate|room for rent|"
    r"shared (room|bathroom|kitchen)|furnished room|private room)\b",
    re.I,
)


class CraigslistScraper(Scraper):
    """Parses craigslist's HTML search page for titles/prices/URLs, then joins
    against the sapi JSON endpoint for thumbnail images by post_id."""

    source = "craigslist"

    def __init__(self, max_rent: int = 2000, min_rent: int = 500,
                 region: str = "vancouver", area_id: int = 16):
        self.max_rent = max_rent
        self.min_rent = min_rent
        self.region = region
        self.area_id = area_id

    def fetch(self) -> list[Listing]:
        image_map = self._fetch_images()
        items = self._fetch_html_items()
        listings: list[Listing] = []
        dropped_junk = 0
        for li in items:
            try:
                listing = self._parse(li, image_map)
            except Exception as e:
                log.debug("skipping malformed entry: %s", e)
                continue
            if listing is None:
                continue
            if listing.title and JUNK_PATTERNS.search(listing.title):
                dropped_junk += 1
                continue
            if listing.price is not None and listing.price < self.min_rent:
                # < $500 is almost certainly a scam / deposit-as-price / by-the-week
                dropped_junk += 1
                continue
            listings.append(listing)
        if dropped_junk:
            log.info("craigslist: dropped %d junk/short-term listings", dropped_junk)
        return listings

    def _fetch_html_items(self) -> list:
        url = f"https://{self.region}.craigslist.org/search/apa?max_price={self.max_rent}"
        try:
            r = http_get(url)
            r.raise_for_status()
        except Exception as e:
            log.warning("craigslist HTML fetch failed: %s", e)
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        return soup.select("li.cl-static-search-result")

    def _fetch_images(self) -> dict[str, str]:
        """Build {post_id: thumbnail_url} from the sapi JSON endpoint."""
        try:
            r = http_get(
                "https://sapi.craigslist.org/web/v8/postings/search/full",
                params={
                    "batch": f"{self.area_id}-0-360-0-0",
                    "cc": "us",
                    "lang": "en",
                    "searchPath": "apa",
                    "max_price": self.max_rent,
                    "areaId": self.area_id,
                },
            )
            r.raise_for_status()
            items = r.json().get("data", {}).get("items", []) or []
        except Exception as e:
            log.debug("craigslist sapi (for images) failed: %s", e)
            return {}

        out: dict[str, str] = {}
        for item in items:
            try:
                post_id = str(item[0])
                # Index 7 holds [4, 'imgid', 'imgid', ...] when present.
                for field in item[5:]:
                    if isinstance(field, list) and field and field[0] == 4 and len(field) > 1:
                        first = field[1]
                        if isinstance(first, str) and first.startswith("3:"):
                            img_id = first[2:]
                            out[post_id] = f"https://images.craigslist.org/{img_id}_300x300.jpg"
                        break
            except Exception:
                continue
        return out

    def _parse(self, li, image_map: dict[str, str]) -> Listing | None:
        a = li.find("a")
        url = a["href"] if a and a.has_attr("href") else ""
        if not url:
            return None

        post_id = ""
        m = POST_ID_RE.search(url)
        if m:
            post_id = m.group(1)
        ext_id = post_id or url.rstrip("/").rsplit("/", 1)[-1].split(".")[0]

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
            description=None,
            amenities=[],
            image_url=image_map.get(post_id),
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
