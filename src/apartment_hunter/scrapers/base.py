from __future__ import annotations

import re
from abc import ABC, abstractmethod

from ..models import Listing

# Combined junk patterns from craigslist and kijiji — drop short-term /
# vacation / sublet / room-rental noise across all sources.
JUNK_PATTERNS = re.compile(
    r"\b(short[\s-]?term|short[\s-]?stay|weekly|nightly|per night|monthly only|"
    r"vacation|airbnb|sublet|sublease|roommate|room ?mate|room for rent|"
    r"room available|co[\s-]?living|shared (room|bathroom|kitchen|accommodation)|"
    r"furnished room|private room)\b",
    re.I,
)


class Scraper(ABC):
    source: str = "unknown"

    @abstractmethod
    def fetch(self) -> list[Listing]:
        ...
