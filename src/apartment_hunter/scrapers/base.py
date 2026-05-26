from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Listing


class Scraper(ABC):
    source: str = "unknown"

    @abstractmethod
    def fetch(self) -> list[Listing]:
        ...
