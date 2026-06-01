from __future__ import annotations

from pathlib import Path

import pytest

from apartment_hunter.models import Listing
from apartment_hunter.scoring import (
    Criteria,
    _amenities_score,
    _location_score,
    passes_hard_filters,
    score,
)


@pytest.fixture
def criteria() -> Criteria:
    return Criteria.load(Path(__file__).resolve().parents[1] / "config" / "criteria.yaml")


def _listing(**overrides) -> Listing:
    base = dict(
        source="test",
        external_id="1",
        url="https://example.com/1",
        title="Cozy 1BR in Mount Pleasant",
        price=1700,
        beds=1,
        sqft=600,
        city="Vancouver",
        description="In-unit laundry, dishwasher, balcony.",
        amenities=["in_unit_laundry", "dishwasher"],
    )
    base.update(overrides)
    return Listing(**base)


def test_perfect_listing_scores_high(criteria):
    s = score(_listing(), criteria)
    assert s["total"] >= 70


def test_overpriced_listing_fails_hard_filter(criteria):
    ok, reason = passes_hard_filters(_listing(price=2500), criteria)
    assert not ok
    assert "price" in reason


def test_wrong_city_fails_hard_filter(criteria):
    ok, reason = passes_hard_filters(_listing(city="Surrey"), criteria)
    assert not ok
    assert "city" in reason


def test_missing_price_fails(criteria):
    ok, _ = passes_hard_filters(_listing(price=None), criteria)
    assert not ok


def test_price_score_monotonic(criteria):
    cheap = score(_listing(price=1500), criteria)["price"]
    mid = score(_listing(price=1800), criteria)["price"]
    expensive = score(_listing(price=1999), criteria)["price"]
    assert cheap >= mid >= expensive


def test_preferred_neighborhood_helps(criteria):
    pref = score(_listing(title="1BR in Kitsilano", address="Kitsilano Ave"), criteria)
    plain = score(_listing(title="1BR somewhere", address="Some St"), criteria)
    assert pref["location"] > plain["location"]


def test_amenities_score_neutral_when_nice_to_have_empty():
    # No nice_to_have list -> neutral 0.5, no ZeroDivisionError.
    assert _amenities_score(_listing(), {}) == 0.5
    assert _amenities_score(_listing(), {"nice_to_have": []}) == 0.5


def test_location_no_pref_is_neutral():
    assert _location_score(_listing(), {}) == 0.5
    assert _location_score(_listing(), {"preferred_neighborhoods": []}) == 0.5


def test_location_token_match_hits_full_phrase():
    prefs = {"preferred_neighborhoods": ["Mount Pleasant"]}
    l = _listing(
        title="Bright 1BR in Mount Pleasant",
        address="123 Quebec St",
        description="",
    )
    assert _location_score(l, prefs) == pytest.approx(0.8)


def test_location_partial_phrase_does_not_match():
    # Contains "mount" but not the full "Mount Pleasant" phrase.
    prefs = {"preferred_neighborhoods": ["Mount Pleasant"]}
    l = _listing(
        title="Unit with mountain views",
        address="500 Mountainside Rd",
        description="",
    )
    assert _location_score(l, prefs) == 0.3


def test_location_no_substring_false_positive():
    # "Main" must not match inside "remaining" the way substring matching would.
    prefs = {"preferred_neighborhoods": ["Main"]}
    l = _listing(
        title="One parking spot remaining",
        address="42 Cambie St",
        description="",
    )
    assert _location_score(l, prefs) == 0.3
    # But it should match a real word-boundary occurrence.
    hit = _listing(title="Loft on Main St", address="", description="")
    assert _location_score(hit, prefs) == pytest.approx(0.8)


def test_location_multiple_hits_stack():
    prefs = {"preferred_neighborhoods": ["Kitsilano", "Mount Pleasant"]}
    l = _listing(
        title="Kitsilano gem near Mount Pleasant border",
        address="",
        description="",
    )
    assert _location_score(l, prefs) == pytest.approx(1.0)
