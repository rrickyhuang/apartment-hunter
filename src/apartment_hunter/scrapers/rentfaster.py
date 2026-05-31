from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..http_client import get as http_get
from ..models import Listing
from .base import Scraper

log = logging.getLogger(__name__)

# rentfaster city_ids for Vancouver + metro. Verified by scraping
# https://www.rentfaster.ca/bc/<slug> and reading the embedded city_id.
METRO_VAN_CITY_IDS = {
    6:     "Vancouver",
    76:    "Burnaby",
    93:    "Richmond",
    91:    "North Vancouver",
    74:    "New Westminster",
    72:    "Surrey",
    80:    "Coquitlam",
    10173: "West Vancouver",
}

# Safety net: even if rentfaster mis-tags a listing's city_id, drop anything
# whose returned city field is outside this set.
ALLOWED_CITIES = {c.lower() for c in METRO_VAN_CITY_IDS.values()} | {
    "port coquitlam", "port moody", "delta", "langley", "maple ridge", "white rock",
}


class RentfasterScraper(Scraper):
    source = "rentfaster"

    def __init__(self, max_rent: int = 2000, city_ids: list[int] | None = None):
        self.max_rent = max_rent
        self.city_ids = city_ids or list(METRO_VAN_CITY_IDS.keys())

    def fetch(self) -> list[Listing]:
        url = "https://www.rentfaster.ca/api/map.json"
        all_items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for cid in self.city_ids:
            try:
                r = http_get(url, params={"city_id": cid, "price_range_to": self.max_rent})
                r.raise_for_status()
                items = r.json().get("listings", []) or []
            except Exception as e:
                log.warning("rentfaster city_id=%s fetch failed: %s", cid, e)
                continue
            for it in items:
                rid = str(it.get("ref_id") or it.get("id") or "")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    all_items.append(it)

        listings: list[Listing] = []
        for item in all_items:
            city = (item.get("city") or "").strip().lower()
            if city and city not in ALLOWED_CITIES:
                continue
            try:
                listings.append(self._parse(item))
            except Exception as e:
                log.debug("skipping malformed listing: %s", e)
        log.info(
            "source=%s fetched=%d parsed=%d dropped=%d",
            self.source, len(all_items), len(listings), len(all_items) - len(listings),
        )
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
