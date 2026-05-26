from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..http_client import get as http_get
from ..models import Listing
from .base import Scraper

log = logging.getLogger(__name__)

# Vancouver city_id on rentfaster. Verify when running — they occasionally renumber.
VANCOUVER_CITY_ID = 3


class RentfasterScraper(Scraper):
    source = "rentfaster"

    def __init__(self, max_rent: int = 2000, city_id: int = VANCOUVER_CITY_ID):
        self.max_rent = max_rent
        self.city_id = city_id

    def fetch(self) -> list[Listing]:
        url = "https://www.rentfaster.ca/api/map.json"
        params = {"city_id": self.city_id, "price_range_to": self.max_rent}

        try:
            r = http_get(url, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("rentfaster fetch failed: %s", e)
            return []

        listings: list[Listing] = []
        for item in data.get("listings", []):
            try:
                listings.append(self._parse(item))
            except Exception as e:
                log.debug("skipping malformed listing: %s", e)
        return listings

    def _parse(self, item: dict[str, Any]) -> Listing:
        ext_id = str(item.get("ref_id") or item.get("id"))
        link = item.get("link") or f"/listings/{ext_id}"
        url = link if link.startswith("http") else f"https://www.rentfaster.ca{link}"

        price = item.get("price")
        try:
            price = int(str(price).replace(",", "").replace("$", "")) if price else None
        except (TypeError, ValueError):
            price = None

        return Listing(
            source=self.source,
            external_id=ext_id,
            url=url,
            title=item.get("title") or item.get("type") or "(no title)",
            price=price,
            beds=_to_float(item.get("bedrooms") or item.get("beds")),
            baths=_to_float(item.get("baths")),
            sqft=_to_int(item.get("sq_feet") or item.get("sqft")),
            address=item.get("address"),
            city=item.get("city"),
            lat=_to_float(item.get("latitude")),
            lng=_to_float(item.get("longitude")),
            posted_at=datetime.now(timezone.utc),
            description=item.get("intro"),
            amenities=_amenities(item),
            image_url=item.get("thumb") or item.get("thumb2"),
            raw=item,
        )


def _amenities(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("amenities", "features"):
        v = item.get(key)
        if isinstance(v, list):
            out.extend(str(x) for x in v)
        elif isinstance(v, str):
            out.extend(s.strip() for s in v.split(",") if s.strip())
    return out


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
