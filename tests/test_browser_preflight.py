"""
tests/test_browser_preflight.py
────────────────────────────────
Tests for browser simulation preflight checks and headless-mode detection.

Run with:  python -m pytest tests/test_browser_preflight.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# Headless detection
# ─────────────────────────────────────────────────────────────────────────────

class TestIsHeadlessEnv(unittest.TestCase):
    """_is_headless_env() must return True in server environments."""

    def setUp(self):
        self._orig = sys.platform

    def tearDown(self):
        sys.platform = self._orig

    def test_windows_is_never_headless(self):
        from app.automation import browser
        sys.platform = "win32"
        self.assertFalse(browser._is_headless_env())

    def test_linux_no_display_is_headless(self):
        from app.automation import browser
        sys.platform = "linux"
        env = {
            "DISPLAY": "", "WAYLAND_DISPLAY": "",
            "SSH_CLIENT": "", "SSH_TTY": "", "SSH_CONNECTION": "",
            "CI": "", "DOCKER": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(browser._is_headless_env())

    def test_linux_with_display_is_not_headless(self):
        from app.automation import browser
        sys.platform = "linux"
        env = {
            "DISPLAY": ":0", "WAYLAND_DISPLAY": "",
            "SSH_CLIENT": "", "SSH_TTY": "", "SSH_CONNECTION": "",
            "CI": "", "DOCKER": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(browser._is_headless_env())

    def test_linux_ssh_is_headless_even_with_display(self):
        from app.automation import browser
        sys.platform = "linux"
        env = {
            "DISPLAY": ":0",
            "SSH_CLIENT": "192.168.1.1 12345 22",
            "CI": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(browser._is_headless_env())

    def test_linux_ci_is_headless(self):
        from app.automation import browser
        sys.platform = "linux"
        env = {
            "DISPLAY": ":0", "SSH_CLIENT": "",
            "CI": "true", "DOCKER": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(browser._is_headless_env())


# ─────────────────────────────────────────────────────────────────────────────
# Playwright error classifier
# ─────────────────────────────────────────────────────────────────────────────

class TestPlaywrightErrorClassification(unittest.TestCase):
    """_classify_playwright_error() maps exception messages to precise codes."""

    def test_sync_api_in_asyncio_loop_is_async_misuse(self):
        from app.automation.browser import _classify_playwright_error
        msg = "It looks like you are using Playwright Sync API inside the asyncio loop"
        self.assertEqual(_classify_playwright_error(msg), "PLAYWRIGHT_ASYNC_MISUSE")

    def test_using_playwright_sync_variant_is_async_misuse(self):
        from app.automation.browser import _classify_playwright_error
        msg = "using playwright sync api is not allowed here"
        self.assertEqual(_classify_playwright_error(msg), "PLAYWRIGHT_ASYNC_MISUSE")

    def test_no_module_named_playwright_is_not_installed(self):
        from app.automation.browser import _classify_playwright_error
        msg = "No module named 'playwright'"
        self.assertEqual(_classify_playwright_error(msg), "PLAYWRIGHT_NOT_INSTALLED")

    def test_executable_doesnt_exist_is_chromium_not_installed(self):
        from app.automation.browser import _classify_playwright_error
        msg = "Executable doesn't exist at /home/user/.local/share/ms-playwright/chromium"
        self.assertEqual(_classify_playwright_error(msg), "CHROMIUM_NOT_INSTALLED")

    def test_run_playwright_install_hint_is_chromium_not_installed(self):
        from app.automation.browser import _classify_playwright_error
        msg = "Please run playwright install chromium"
        self.assertEqual(_classify_playwright_error(msg), "CHROMIUM_NOT_INSTALLED")

    def test_unknown_error_is_browser_launch_failed(self):
        from app.automation.browser import _classify_playwright_error
        msg = "Something completely unexpected happened"
        self.assertEqual(_classify_playwright_error(msg), "BROWSER_LAUNCH_FAILED")


# ─────────────────────────────────────────────────────────────────────────────
# Chromium preflight check — async, returns 3-tuple
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckChromiumAvailable(unittest.TestCase):
    """check_chromium_available() is async and returns (bool, str, str)."""

    def test_returns_3_tuple(self):
        from app.automation.browser import check_chromium_available
        with patch("app.automation.browser.async_playwright") as mock_apw:
            mock_p = MagicMock()
            mock_p.chromium.executable_path = "/fake/chromium"
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_p)
            mock_ctx.__aexit__  = AsyncMock(return_value=None)
            mock_apw.return_value = mock_ctx

            with patch("app.automation.browser.Path") as mock_path:
                mock_path.return_value.exists.return_value = True
                result = _run(check_chromium_available())

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        ok, info, cls = result
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(info, str)
        self.assertIsInstance(cls, str)

    def test_returns_false_when_binary_missing(self):
        from app.automation.browser import check_chromium_available
        with patch("app.automation.browser.async_playwright") as mock_apw:
            mock_p = MagicMock()
            mock_p.chromium.executable_path = "/fake/chromium"
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_p)
            mock_ctx.__aexit__  = AsyncMock(return_value=None)
            mock_apw.return_value = mock_ctx

            with patch("app.automation.browser.Path") as mock_path:
                mock_path.return_value.exists.return_value = False
                ok, info, cls = _run(check_chromium_available())

        self.assertFalse(ok)
        self.assertEqual(cls, "CHROMIUM_NOT_INSTALLED")

    def test_returns_true_when_binary_present(self):
        from app.automation.browser import check_chromium_available
        with patch("app.automation.browser.async_playwright") as mock_apw:
            mock_p = MagicMock()
            mock_p.chromium.executable_path = "/fake/chromium"
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_p)
            mock_ctx.__aexit__  = AsyncMock(return_value=None)
            mock_apw.return_value = mock_ctx

            with patch("app.automation.browser.Path") as mock_path:
                mock_path.return_value.exists.return_value = True
                ok, info, cls = _run(check_chromium_available())

        self.assertTrue(ok)
        self.assertEqual(cls, "CHROMIUM_INSTALLED")

    def test_sync_playwright_error_classified_as_async_misuse(self):
        """Playwright sync/async misuse → PLAYWRIGHT_ASYNC_MISUSE, not BROWSER_LAUNCH_FAILED."""
        from app.automation.browser import check_chromium_available
        exc_msg = "It looks like you are using Playwright Sync API inside the asyncio loop"
        with patch("app.automation.browser.async_playwright",
                   side_effect=Exception(exc_msg)):
            ok, info, cls = _run(check_chromium_available())

        self.assertFalse(ok)
        self.assertEqual(cls, "PLAYWRIGHT_ASYNC_MISUSE",
                         f"Expected PLAYWRIGHT_ASYNC_MISUSE but got: {cls}")

    def test_playwright_installed_chromium_missing_is_chromium_not_installed(self):
        """Chromium binary absent → CHROMIUM_NOT_INSTALLED."""
        from app.automation.browser import check_chromium_available
        exc_msg = "Executable doesn't exist at /home/user/.ms-playwright/chromium/chrome"
        with patch("app.automation.browser.async_playwright",
                   side_effect=Exception(exc_msg)):
            ok, info, cls = _run(check_chromium_available())

        self.assertFalse(ok)
        self.assertEqual(cls, "CHROMIUM_NOT_INSTALLED",
                         f"Expected CHROMIUM_NOT_INSTALLED but got: {cls}")


# ─────────────────────────────────────────────────────────────────────────────
# simulate_data_leakage — browser unavailable path
# ─────────────────────────────────────────────────────────────────────────────

class TestSimulateDataLeakageMissingBrowser(unittest.TestCase):
    """
    When Chromium is not available, simulate_data_leakage() must:
    - Return success=False
    - Return classification matching the chromium check classification
    - Include a remediation hint
    - Not crash
    - Emit WARN, not ERROR
    """

    def _make_target(self):
        return {
            "url":       "https://chat.openai.com",
            "name":      "ChatGPT",
            "payload":   "SIMULATED_PII",
            "data_type": "PII",
        }

    def test_chromium_missing_returns_correct_classification(self):
        from app.automation.browser import simulate_data_leakage

        events = []
        async def _emit(level, cat, msg, *a, **kw):
            events.append({"level": level, "message": msg, **kw})

        with patch("app.automation.browser.check_chromium_available",
                   new=AsyncMock(return_value=(False, "Binary not found at: /fake/path",
                                              "CHROMIUM_NOT_INSTALLED"))):
            result = _run(simulate_data_leakage(self._make_target(), _emit))

        self.assertFalse(result["success"])
        self.assertEqual(result["classification"], "CHROMIUM_NOT_INSTALLED")
        self.assertIn("remediation", result)

    def test_async_misuse_returns_async_misuse_classification(self):
        """PLAYWRIGHT_ASYNC_MISUSE should propagate through, not become BROWSER_MISSING."""
        from app.automation.browser import simulate_data_leakage

        events = []
        async def _emit(level, cat, msg, *a, **kw):
            events.append({"level": level, "message": msg, **kw})

        with patch("app.automation.browser.check_chromium_available",
                   new=AsyncMock(return_value=(False,
                                              "Playwright error: Sync API inside asyncio loop",
                                              "PLAYWRIGHT_ASYNC_MISUSE"))):
            result = _run(simulate_data_leakage(self._make_target(), _emit))

        self.assertFalse(result["success"])
        self.assertEqual(result["classification"], "PLAYWRIGHT_ASYNC_MISUSE")

    def test_browser_missing_emits_warn_not_error(self):
        from app.automation.browser import simulate_data_leakage

        events = []
        async def _emit(level, cat, msg, *a, **kw):
            events.append({"level": level})

        with patch("app.automation.browser.check_chromium_available",
                   new=AsyncMock(return_value=(False, "Binary not found",
                                              "CHROMIUM_NOT_INSTALLED"))):
            _run(simulate_data_leakage(self._make_target(), _emit))

        levels = [e["level"] for e in events]
        self.assertNotIn("ERROR", levels)
        self.assertIn("WARN", levels)


# ─────────────────────────────────────────────────────────────────────────────
# Launch args
# ─────────────────────────────────────────────────────────────────────────────

class TestLaunchArgs(unittest.TestCase):
    """_launch_args() always includes --no-sandbox for headless stability."""

    def test_headless_includes_no_sandbox(self):
        from app.automation.browser import _launch_args
        args = _launch_args(headless=True)
        self.assertIn("--no-sandbox", args)
        self.assertIn("--disable-dev-shm-usage", args)

    def test_headed_includes_no_sandbox(self):
        from app.automation.browser import _launch_args
        args = _launch_args(headless=False)
        self.assertIn("--no-sandbox", args)
        self.assertIn("--start-maximized", args)

    def test_headless_does_not_include_start_maximized(self):
        from app.automation.browser import _launch_args
        args = _launch_args(headless=True)
        self.assertNotIn("--start-maximized", args)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level import check
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserModuleAsyncOnly(unittest.TestCase):
    """browser.py must never import sync_playwright."""

    def test_no_sync_playwright_import(self):
        """
        Verify that browser.py never imports sync_playwright.
        If this test fails, the PLAYWRIGHT_ASYNC_MISUSE bug has been re-introduced.
        """
        import importlib.util
        import re as _re
        spec = importlib.util.find_spec("app.automation.browser")
        self.assertIsNotNone(spec, "app.automation.browser module not found")
        source_path = spec.origin
        with open(source_path) as f:
            source = f.read()
        # Check for actual import statements, not comments or docstrings
        _import_pattern = _re.compile(
            r"^\s*(from\s+playwright\.sync_api\s+import|import\s+.*sync_playwright)",
            _re.MULTILINE,
        )
        matches = _import_pattern.findall(source)
        self.assertEqual(
            len(matches), 0,
            f"browser.py has sync_playwright import(s): {matches} — "
            "this will break inside asyncio event loops"
        )


if __name__ == "__main__":
    unittest.main()
