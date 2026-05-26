"""rentals.ca scraper — currently STUBBED.

Status as of last investigation: the obvious endpoints (/api/v1/listings,
/api/v1.0.2/listings, api.rentals.ca/...) all return 404 even with proper
Chrome TLS impersonation. The site uses heavy client-side rendering and the
real listings API path could not be discovered without inspecting live
network traffic in DevTools while panning the map.

ACTION NEEDED (one-time, ~5 min):
  1. Open https://rentals.ca/vancouver in Chrome
  2. DevTools (F12) -> Network tab -> filter "Fetch/XHR"
  3. Pan or zoom the map
  4. Find the request that returns JSON containing listings
  5. Right-click -> Copy -> Copy as cURL
  6. Paste the URL/params into `_API_URL` and `_build_params` below
  7. Delete the `return []` short-circuit at the bottom of fetch()

Until that's done, fetch() returns an empty list and logs a hint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..http_client import get as http_get
from ..models import Listing
from .base import Scraper

log = logging.getLogger(__name__)

DEFAULT_BBOX = {
    "min_lat": 49.10, "max_lat": 49.35,
    "min_lng": -123.30, "max_lng": -122.85,
}

_API_URL: str | None = None  # e.g. "https://rentals.ca/api/v??/listings"


class RentalsCaScraper(Scraper):
    source = "rentals.ca"

    def __init__(
        self,
        max_rent: int = 2000,
        min_beds: float = 0,
        bbox: dict[str, float] | None = None,
        max_pages: int = 10,
    ):
        self.max_rent = max_rent
        self.min_beds = min_beds
        self.bbox = bbox or DEFAULT_BBOX
        self.max_pages = max_pages

    def fetch(self) -> list[Listing]:
        if not _API_URL:
            log.info(
                "rentals.ca scraper is stubbed — set _API_URL after DevTools inspection "
                "(see module docstring). Skipping for now."
            )
            return []

        listings: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            try:
                r = http_get(_API_URL, params=self._build_params(page))
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning("rentals.ca page %d failed: %s", page, e)
                break

            items = data.get("listings") or data.get("data") or data.get("results") or []
            if not items:
                break
            for item in items:
                try:
                    listings.append(self._parse(item))
                except Exception as e:
                    log.debug("skipping malformed listing: %s", e)
            if len(items) < 50:
                break
        return listings

    def _build_params(self, page: int) -> dict[str, Any]:
        # Fill in once the real endpoint is known.
        return {
            "bbox": f"{self.bbox['min_lng']},{self.bbox['min_lat']},"
                    f"{self.bbox['max_lng']},{self.bbox['max_lat']}",
            "max_price": self.max_rent,
            "min_bed": self.min_beds,
            "page": page,
        }

    def _parse(self, item: dict[str, Any]) -> Listing:
        ext_id = str(item.get("id") or item.get("listing_id") or item.get("uid"))
        url = item.get("url") or item.get("link") or ""
        if url and not url.startswith("http"):
            url = "https://rentals.ca" + url

        price = item.get("price") or item.get("rent")
        if isinstance(price, dict):
            price = price.get("from") or price.get("min")
        try:
            price = int(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        return Listing(
            source=self.source,
            external_id=ext_id,
            url=url,
            title=item.get("title") or item.get("name") or "(no title)",
            price=price,
            beds=_to_float(item.get("bedrooms") or item.get("beds")),
            baths=_to_float(item.get("bathrooms") or item.get("baths")),
            sqft=_to_int(item.get("sqft") or item.get("size")),
            address=item.get("address"),
            city=item.get("city"),
            lat=_to_float(item.get("lat")),
            lng=_to_float(item.get("lng")),
            posted_at=datetime.now(timezone.utc),
            description=item.get("description"),
            amenities=item.get("amenities") or [],
            image_url=item.get("image") or item.get("photo"),
            raw=item,
        )


def _to_float(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _to_int(x: Any) -> int | None:
    f = _to_float(x)
    return int(f) if f is not None else None
