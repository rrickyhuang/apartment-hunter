from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import Listing


@dataclass
class Criteria:
    hard_filters: dict[str, Any]
    weights: dict[str, float]
    preferences: dict[str, Any]
    alert_threshold: float

    @classmethod
    def load(cls, path: Path | str) -> "Criteria":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        weights = data["weights"]
        total = sum(weights.values())
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"weights must sum to 1.0, got {total}")
        return cls(
            hard_filters=data.get("hard_filters", {}),
            weights=weights,
            preferences=data.get("preferences", {}),
            alert_threshold=float(data.get("alert_threshold", 70)),
        )


def passes_hard_filters(listing: Listing, c: Criteria) -> tuple[bool, str]:
    hf = c.hard_filters
    if listing.price is None:
        return False, "no price"
    if "max_rent" in hf and listing.price > hf["max_rent"]:
        return False, f"price ${listing.price} > max ${hf['max_rent']}"
    if "min_rent" in hf and listing.price < hf["min_rent"]:
        return False, f"price ${listing.price} < min ${hf['min_rent']}"
    if "min_beds" in hf and listing.beds is not None and listing.beds < hf["min_beds"]:
        return False, f"beds {listing.beds} < min {hf['min_beds']}"
    if hf.get("cities") and listing.city:
        allowed = {x.lower() for x in hf["cities"]}
        if listing.city.lower() not in allowed:
            return False, f"city {listing.city!r} not in allowed list"
    text = " ".join(
        x.lower() for x in (listing.title, listing.description, listing.address) if x
    )
    for bad in hf.get("deal_breakers", []):
        if bad.lower() in text:
            return False, f"matched deal-breaker {bad!r}"
    return True, ""


def _price_score(listing: Listing, prefs: dict[str, Any], hf: dict[str, Any]) -> float:
    if listing.price is None:
        return 0.0
    max_rent = hf.get("max_rent", listing.price)
    target = prefs.get("target_rent", max_rent * 0.85)
    if listing.price <= target:
        return 1.0
    if listing.price >= max_rent:
        return 0.0
    return 1.0 - (listing.price - target) / (max_rent - target)


def _location_score(listing: Listing, prefs: dict[str, Any]) -> float:
    preferred = [n.lower() for n in prefs.get("preferred_neighborhoods", [])]
    if not preferred:
        return 0.5
    text = " ".join(
        x.lower() for x in (listing.address, listing.title, listing.description) if x
    )
    hits = sum(1 for n in preferred if n in text)
    if hits == 0:
        return 0.3
    return min(1.0, 0.6 + 0.2 * hits)


def _size_score(listing: Listing, prefs: dict[str, Any]) -> float:
    if listing.sqft is None:
        # Fall back to beds as a weak proxy
        if listing.beds is None:
            return 0.4
        return min(1.0, 0.5 + 0.15 * listing.beds)
    min_sqft = prefs.get("min_sqft", 0)
    target = prefs.get("target_sqft", 700)
    if listing.sqft >= target:
        return 1.0
    if listing.sqft <= min_sqft:
        return 0.2
    return 0.2 + 0.8 * (listing.sqft - min_sqft) / (target - min_sqft)


def _amenities_score(listing: Listing, prefs: dict[str, Any]) -> float:
    nice = [a.lower() for a in prefs.get("nice_to_have", [])]
    if not nice:
        return 0.5
    have = {a.lower() for a in listing.amenities}
    text = " ".join(
        x.lower() for x in (listing.title, listing.description) if x
    )
    hits = 0
    for a in nice:
        if a in have or a.replace("_", " ") in text:
            hits += 1
    return hits / len(nice)


def score(listing: Listing, c: Criteria) -> dict[str, float]:
    """Returns dict with sub-scores and total (0-100). Does not check hard filters."""
    sub = {
        "price": _price_score(listing, c.preferences, c.hard_filters),
        "location": _location_score(listing, c.preferences),
        "size": _size_score(listing, c.preferences),
        "amenities": _amenities_score(listing, c.preferences),
    }
    total = sum(sub[k] * c.weights.get(k, 0) for k in sub) * 100
    return {**sub, "total": total}
