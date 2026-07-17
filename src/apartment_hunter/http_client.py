"""Shared HTTP client. Uses curl_cffi to impersonate Chrome's TLS fingerprint —
required because rentals.ca, rentfaster.ca, and craigslist all sit behind
Cloudflare, which blocks plain Python clients (httpx/requests) at the TLS layer
regardless of User-Agent header."""
from __future__ import annotations

import logging
import time

from curl_cffi import requests as cc_requests

log = logging.getLogger(__name__)

# Cloudflare reads the JA3 TLS fingerprint; we pick a recent Chrome.
IMPERSONATE = "chrome"
TIMEOUT = 20

# Retry config: 2 retries for 5xx and connection errors; 4xx are not retried.
_MAX_RETRIES = 2
_RETRY_BACKOFF = 1.0  # seconds; doubled each attempt (1s, 2s)


def _with_retry(method, url, **kwargs):
    last_exc: BaseException | None = None
    resp = None
    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            delay = _RETRY_BACKOFF * (2 ** (attempt - 1))
            log.debug("http retry %d/%d for %s in %.1fs", attempt, _MAX_RETRIES, url, delay)
            time.sleep(delay)
        try:
            resp = method(url, impersonate=IMPERSONATE, timeout=TIMEOUT, **kwargs)
            last_exc = None
            if resp.status_code < 500:
                return resp
            # 5xx: loop to retry if attempts remain
        except Exception as e:
            last_exc = e
            resp = None
    if last_exc is not None:
        raise last_exc
    return resp  # last 5xx response; caller can raise_for_status()


def get(url: str, params: dict | None = None, **kwargs):
    return _with_retry(cc_requests.get, url, params=params, **kwargs)
