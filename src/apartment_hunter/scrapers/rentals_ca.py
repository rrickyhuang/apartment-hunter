"""rentals.ca scraper.

The public JSON API (/phoenix/api/v1/listings) returns 500 without a
browser-issued CSRF token. Instead, we fetch the server-rendered HTML page
which embeds the full GraphQL response in an inline `App.store.search = { ... }`
script. Paginated via `?page=N` — SSR honors the query string.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..http_client import get as http_get
from ..models import Listing
from .base import Scraper

log = logging.getLogger(__name__)

CITY_SLUG = "vancouver"
PAGE_URL = "https://rentals.ca/{slug}"
RESPONSE_MARKER = re.compile(r"response:\s*(\{)")


class RentalsCaScraper(Scraper):
    source = "rentals_ca"

    def __init__(
        self,
        max_rent: int = 2000,
        min_beds: float = 0,
        city_slug: str = CITY_SLUG,
        max_pages: int = 15,
    ):
        self.max_rent = max_rent
        self.min_beds = min_beds
        self.city_slug = city_slug
        self.max_pages = max_pages

    def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = PAGE_URL.format(slug=self.city_slug)
            params = {"page": page} if page > 1 else None
            try:
                r = http_get(url, params=params)
                r.raise_for_status()
                data = _extract_store_response(r.text)
            except Exception as e:
                log.warning("rentals.ca page %d failed: %s", page, e)
                break

            edges = data.get("data", {}).get("edges", []) or []
            page_info = data.get("data", {}).get("pageInfo", {}) or {}

            new_this_page = 0
            for edge in edges:
                node = edge.get("node") or {}
                ext_id = str(node.get("id") or "")
                if not ext_id or ext_id in seen:
                    continue
                seen.add(ext_id)
                try:
                    listing = self._parse(node)
                except Exception as e:
                    log.debug("skipping malformed rentals.ca node: %s", e)
                    continue
                # Apply max_rent early — the site mixes price tiers.
                if listing.price is not None and listing.price > self.max_rent:
                    continue
                if listing.beds is not None and listing.beds < self.min_beds:
                    continue
                out.append(listing)
                new_this_page += 1

            log.debug("rentals.ca page %d: %d edges, %d new kept", page, len(edges), new_this_page)
            if not page_info.get("hasNextPage"):
                break
        return out

    def _parse(self, node: dict[str, Any]) -> Listing:
        ext_id = str(node["id"])
        path = node.get("path") or ""
        url = f"https://rentals.ca/{path}" if path else "https://rentals.ca/"

        loc = node.get("rentalListingLocation") or [None, None]
        lng, lat = (loc + [None, None])[:2]

        addr = node.get("address") or {}
        city = (addr.get("city") or {}).get("cityName")
        street = addr.get("street")

        rent_range = node.get("rentRange") or []
        beds_range = node.get("bedsRange") or []
        baths_range = node.get("bathsRange") or []
        size_range = node.get("sizeRange") or []

        image_url = None
        images = node.get("images") or []
        if images:
            scales = images[0].get("scales") or []
            if scales:
                image_url = scales[-1].get("url") or scales[0].get("url")

        modified = node.get("modified")
        posted_at = None
        if modified:
            try:
                posted_at = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        return Listing(
            source=self.source,
            external_id=ext_id,
            url=url,
            title=node.get("rentalListingName") or "(no title)",
            price=int(rent_range[0]) if rent_range else None,
            beds=float(beds_range[0]) if beds_range else None,
            baths=float(baths_range[0]) if baths_range else None,
            sqft=int(size_range[0]) if size_range else None,
            address=street,
            city=city,
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
            posted_at=posted_at or datetime.now(timezone.utc),
            description=None,
            amenities=[],
            image_url=image_url,
            raw=node,
        )


def _extract_store_response(html: str) -> dict[str, Any]:
    """Find the inline `response: { ... }` JSON in the hydration script and
    return the parsed object. Raises on missing/unbalanced braces."""
    m = RESPONSE_MARKER.search(html)
    if not m:
        raise RuntimeError("rentals.ca: hydration marker not found")
    start = m.end() - 1
    depth = 0
    in_str = False
    esc = False
    i = start
    while i < len(html):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(html[start : i + 1])
        i += 1
    raise RuntimeError("rentals.ca: unbalanced braces in hydration JSON")
