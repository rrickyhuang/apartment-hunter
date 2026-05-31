"""Centralised environment-variable loading and validation.

Reading env vars in one place gives a single, clear error when something is
missing instead of a bare KeyError surfacing from deep in the email path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

REQUIRED = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")


class MissingEnvVar(RuntimeError):
    """Raised when a required environment variable is unset or empty."""


@dataclass
class Settings:
    gmail_address: str
    gmail_app_password: str
    alert_to: str

    @classmethod
    def load(cls) -> "Settings":
        missing = [k for k in REQUIRED if not os.environ.get(k)]
        if missing:
            raise MissingEnvVar(
                "missing required env var(s): "
                + ", ".join(missing)
                + " — did you fill in .env? (see .env.example)"
            )
        gmail_address = os.environ["GMAIL_ADDRESS"]
        return cls(
            gmail_address=gmail_address,
            gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
            alert_to=os.environ.get("ALERT_TO", gmail_address),
        )
