"""B4: http_client retry + exponential backoff tests."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import apartment_hunter.http_client as hc


def _mock_response(status_code: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    return r


class TestRetry:
    def test_success_on_first_attempt_makes_one_call(self):
        resp = _mock_response(200)
        with patch("apartment_hunter.http_client.cc_requests.get", return_value=resp) as mock_get, \
             patch("apartment_hunter.http_client.time.sleep") as mock_sleep:
            result = hc.get("https://example.com")
        assert result.status_code == 200
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    def test_503_then_200_retries_and_succeeds(self):
        responses = [_mock_response(503), _mock_response(200)]
        with patch("apartment_hunter.http_client.cc_requests.get", side_effect=responses) as mock_get, \
             patch("apartment_hunter.http_client.time.sleep") as mock_sleep:
            result = hc.get("https://example.com")
        assert result.status_code == 200
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(hc._RETRY_BACKOFF)

    def test_exhausted_retries_returns_last_5xx(self):
        responses = [_mock_response(503)] * (hc._MAX_RETRIES + 1)
        with patch("apartment_hunter.http_client.cc_requests.get", side_effect=responses), \
             patch("apartment_hunter.http_client.time.sleep"):
            result = hc.get("https://example.com")
        assert result.status_code == 503

    def test_404_is_not_retried(self):
        resp = _mock_response(404)
        with patch("apartment_hunter.http_client.cc_requests.get", return_value=resp) as mock_get, \
             patch("apartment_hunter.http_client.time.sleep") as mock_sleep:
            result = hc.get("https://example.com")
        assert result.status_code == 404
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    def test_connection_error_retries_then_raises(self):
        with patch("apartment_hunter.http_client.cc_requests.get",
                   side_effect=ConnectionError("timeout")) as mock_get, \
             patch("apartment_hunter.http_client.time.sleep"):
            with pytest.raises(ConnectionError):
                hc.get("https://example.com")
        assert mock_get.call_count == hc._MAX_RETRIES + 1

    def test_connection_error_then_200_succeeds(self):
        responses = [ConnectionError("timeout"), _mock_response(200)]
        with patch("apartment_hunter.http_client.cc_requests.get", side_effect=responses) as mock_get, \
             patch("apartment_hunter.http_client.time.sleep"):
            result = hc.get("https://example.com")
        assert result.status_code == 200
        assert mock_get.call_count == 2

    def test_exponential_backoff_delays(self):
        # With MAX_RETRIES=2: first retry sleeps 1s, second sleeps 2s.
        responses = [_mock_response(503)] * (hc._MAX_RETRIES + 1)
        sleep_calls = []
        with patch("apartment_hunter.http_client.cc_requests.get", side_effect=responses), \
             patch("apartment_hunter.http_client.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            hc.get("https://example.com")
        expected = [hc._RETRY_BACKOFF * (2 ** i) for i in range(hc._MAX_RETRIES)]
        assert sleep_calls == expected
