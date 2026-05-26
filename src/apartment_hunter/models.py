from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Listing(BaseModel):
    source: str
    external_id: str
    url: str
    title: str
    price: int | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: int | None = None
    address: str | None = None
    city: str | None = None
    lat: float | None = None
    lng: float | None = None
    posted_at: datetime | None = None
    description: str | None = None
    amenities: list[str] = Field(default_factory=list)
    image_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("amenities", mode="before")
    @classmethod
    def _normalize_amenities(cls, v):
        if v is None:
            return []
        return [str(a).strip().lower().replace(" ", "_").replace("-", "_") for a in v]
