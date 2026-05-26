"""Shared HTTP client. Uses curl_cffi to impersonate Chrome's TLS fingerprint —
required because rentals.ca, rentfaster.ca, and craigslist all sit behind
Cloudflare, which blocks plain Python clients (httpx/requests) at the TLS layer
regardless of User-Agent header."""
from __future__ import annotations

from curl_cffi import requests as cc_requests

# Cloudflare reads the JA3 TLS fingerprint; we pick a recent Chrome.
IMPERSONATE = "chrome"
TIMEOUT = 20


def get(url: str, params: dict | None = None, **kwargs):
    return cc_requests.get(
        url, params=params, impersonate=IMPERSONATE, timeout=TIMEOUT, **kwargs
    )


def post(url: str, json: dict | None = None, **kwargs):
    return cc_requests.post(
        url, json=json, impersonate=IMPERSONATE, timeout=TIMEOUT, **kwargs
    )
