"""
tests/test_api_classification.py
──────────────────────────────────
Tests for API probe classification logic.

HTTP 401/403 from AI endpoints with deliberately invalid keys MUST be
classified as EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED — not as errors.
Connection failures and timeouts are classified separately.

Run with:  python -m pytest tests/test_api_classification.py -v
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.automation.api_calls import _classify


# ─────────────────────────────────────────────────────────────────────────────
# _classify() unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyFunction(unittest.TestCase):

    def test_200_is_success_response(self):
        self.assertEqual(_classify(200), "SUCCESS_RESPONSE")

    def test_204_is_success_response(self):
        self.assertEqual(_classify(204), "SUCCESS_RESPONSE")

    def test_401_is_expected_auth_failure(self):
        self.assertEqual(_classify(401), "EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED")

    def test_403_is_expected_auth_failure(self):
        self.assertEqual(_classify(403), "EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED")

    def test_407_is_blocked_by_proxy(self):
        self.assertEqual(_classify(407), "BLOCKED_BY_PROXY")

    def test_500_is_http_500(self):
        self.assertEqual(_classify(500), "HTTP_500")

    def test_429_is_http_429(self):
        self.assertEqual(_classify(429), "HTTP_429")


# ─────────────────────────────────────────────────────────────────────────────
# probe_api_endpoint() integration-style tests (httpx mocked)
# ─────────────────────────────────────────────────────────────────────────────

class TestProbeApiEndpoint(unittest.TestCase):

    def _make_target(self):
        return {
            "url":       "https://api.openai.com/v1/chat/completions",
            "name":      "OpenAI",
            "data_type": "FINANCIAL",
            "headers":   {"Authorization": "Bearer sk-FAKE"},
            "payload":   {"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]},
        }

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_401_classified_as_expected_auth_failure(self):
        from app.automation.api_calls import probe_api_endpoint

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        events = []
        async def _emit(level, category, message, *a, **kw):
            events.append({"level": level, "category": category, "message": message, **kw})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = self._run(probe_api_endpoint(self._make_target(), _emit))

        self.assertTrue(result["transmitted"])
        self.assertTrue(result["response_received"])
        self.assertEqual(result["status_code"], 401)
        self.assertEqual(result["classification"], "EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED")
        # Must emit at SUCCESS level, not ERROR or ALERT
        auth_events = [e for e in events if "401" in e["message"] or "TRAFFIC" in e["message"]]
        self.assertTrue(len(auth_events) > 0)
        self.assertEqual(auth_events[0]["level"], "SUCCESS")

    def test_403_classified_as_expected_auth_failure(self):
        from app.automation.api_calls import probe_api_endpoint

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        events = []
        async def _emit(level, category, message, *a, **kw):
            events.append({"level": level, **kw})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = self._run(probe_api_endpoint(self._make_target(), _emit))

        self.assertEqual(result["classification"], "EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED")
        self.assertTrue(result["transmitted"])

    def test_connect_error_classified_as_connection_failed(self):
        import httpx
        from app.automation.api_calls import probe_api_endpoint

        events = []
        async def _emit(level, category, message, *a, **kw):
            events.append({"level": level, "classification": kw.get("classification")})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client

            result = self._run(probe_api_endpoint(self._make_target(), _emit))

        self.assertFalse(result["transmitted"])
        self.assertFalse(result["response_received"])
        self.assertEqual(result["classification"], "CONNECTION_FAILED")

    def test_timeout_classified_as_no_traffic(self):
        import httpx
        from app.automation.api_calls import probe_api_endpoint

        async def _emit(level, category, message, *a, **kw):
            pass

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client_cls.return_value = mock_client

            result = self._run(probe_api_endpoint(self._make_target(), _emit))

        self.assertFalse(result["transmitted"])
        self.assertEqual(result["classification"], "NO_TRAFFIC_CONFIRMED")

    def test_result_has_all_required_fields(self):
        from app.automation.api_calls import probe_api_endpoint

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        async def _emit(*a, **kw):
            pass

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = self._run(probe_api_endpoint(self._make_target(), _emit))

        for field in ("transmitted", "response_received", "status_code",
                      "classification", "detection_value", "notes", "target"):
            self.assertIn(field, result, f"Missing field: {field}")


if __name__ == "__main__":
    unittest.main()
