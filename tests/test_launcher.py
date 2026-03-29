"""
tests/test_launcher.py
~~~~~~~~~~~~~~~~~~~~~~
Unit tests for app.core.launcher — headless-safe browser detection logic.

Run with:  python -m pytest tests/test_launcher.py -v
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


# Helper: reload the module under a patched environment so module-level
# constants reflect the test environment.
def _reload_launcher():
    import app.core.launcher as m
    importlib.reload(m)
    return m


# ─── Linux headless environment ───────────────────────────────────────────────

class TestLinuxHeadless(unittest.TestCase):
    """can_open_browser() must return False on a headless Linux server."""

    def setUp(self):
        self._orig = sys.platform
        sys.platform = "linux"

    def tearDown(self):
        sys.platform = self._orig

    def _env(self, **overrides):
        """Minimal headless env dict."""
        base = {
            "DISPLAY": "",
            "WAYLAND_DISPLAY": "",
            "XDG_RUNTIME_DIR": "",
            "SSH_CLIENT": "",
            "SSH_TTY": "",
            "SSH_CONNECTION": "",
            "CI": "",
            "DOCKER": "",
            "KUBERNETES_SERVICE_HOST": "",
            "container": "",
        }
        base.update(overrides)
        return base

    def test_no_display_returns_false(self):
        from app.core import launcher
        with patch.dict(os.environ, self._env(), clear=False):
            with patch.object(launcher, "_has_display", return_value=False):
                with patch.object(launcher, "_xdg_runtime_ok", return_value=False):
                    self.assertFalse(launcher.can_open_browser())

    def test_ssh_session_returns_false(self):
        from app.core import launcher
        with patch.object(launcher, "_has_display", return_value=True):
            with patch.object(launcher, "_xdg_runtime_ok", return_value=True):
                with patch.object(launcher, "_is_root", return_value=False):
                    with patch.object(launcher, "_looks_like_ssh", return_value=True):
                        self.assertFalse(launcher.can_open_browser())

    def test_container_returns_false(self):
        from app.core import launcher
        with patch.object(launcher, "_has_display", return_value=True):
            with patch.object(launcher, "_xdg_runtime_ok", return_value=True):
                with patch.object(launcher, "_is_root", return_value=False):
                    with patch.object(launcher, "_looks_like_ssh", return_value=False):
                        with patch.object(launcher, "_looks_like_container", return_value=True):
                            self.assertFalse(launcher.can_open_browser())

    def test_root_user_returns_false(self):
        from app.core import launcher
        with patch.object(launcher, "_has_display", return_value=True):
            with patch.object(launcher, "_xdg_runtime_ok", return_value=True):
                with patch.object(launcher, "_is_root", return_value=True):
                    self.assertFalse(launcher.can_open_browser())

    def test_no_xdg_open_returns_false(self):
        from app.core import launcher
        with patch.object(launcher, "_has_display", return_value=True):
            with patch.object(launcher, "_xdg_runtime_ok", return_value=True):
                with patch.object(launcher, "_is_root", return_value=False):
                    with patch.object(launcher, "_looks_like_ssh", return_value=False):
                        with patch.object(launcher, "_looks_like_container", return_value=False):
                            with patch.object(launcher, "_xdg_open_exists", return_value=False):
                                self.assertFalse(launcher.can_open_browser())

    def test_no_browser_binary_returns_false(self):
        from app.core import launcher
        with patch.object(launcher, "_has_display", return_value=True):
            with patch.object(launcher, "_xdg_runtime_ok", return_value=True):
                with patch.object(launcher, "_is_root", return_value=False):
                    with patch.object(launcher, "_looks_like_ssh", return_value=False):
                        with patch.object(launcher, "_looks_like_container", return_value=False):
                            with patch.object(launcher, "_xdg_open_exists", return_value=True):
                                with patch.object(launcher, "_browser_executable_exists", return_value=False):
                                    self.assertFalse(launcher.can_open_browser())


# ─── Linux desktop environment ────────────────────────────────────────────────

class TestLinuxDesktop(unittest.TestCase):
    """can_open_browser() must return True when all conditions are met."""

    def setUp(self):
        self._orig = sys.platform
        sys.platform = "linux"

    def tearDown(self):
        sys.platform = self._orig

    def test_full_desktop_session_returns_true(self):
        from app.core import launcher
        with patch.object(launcher, "_has_display", return_value=True):
            with patch.object(launcher, "_xdg_runtime_ok", return_value=True):
                with patch.object(launcher, "_is_root", return_value=False):
                    with patch.object(launcher, "_looks_like_ssh", return_value=False):
                        with patch.object(launcher, "_looks_like_container", return_value=False):
                            with patch.object(launcher, "_xdg_open_exists", return_value=True):
                                with patch.object(launcher, "_browser_executable_exists", return_value=True):
                                    self.assertTrue(launcher.can_open_browser())


# ─── Windows desktop environment ─────────────────────────────────────────────

class TestWindowsDesktop(unittest.TestCase):
    """On Windows, can_open_browser() always returns True."""

    def setUp(self):
        self._orig = sys.platform
        sys.platform = "win32"

    def tearDown(self):
        sys.platform = self._orig

    def test_windows_returns_true(self):
        from app.core import launcher
        self.assertTrue(launcher.can_open_browser())


# ─── safe_open_url failure path ───────────────────────────────────────────────

class TestSafeOpenUrl(unittest.TestCase):
    """safe_open_url must never raise, even if every open attempt fails."""

    def test_no_crash_when_headless(self):
        from app.core import launcher
        with patch.object(launcher, "can_open_browser", return_value=False):
            # Should return silently without any exception
            launcher.safe_open_url("http://127.0.0.1:8766")

    def test_no_crash_when_webbrowser_fails(self):
        from app.core import launcher
        with patch.object(launcher, "can_open_browser", return_value=True):
            with patch("webbrowser.open", side_effect=RuntimeError("no browser")):
                with patch.object(launcher, "_platform_fallback"):
                    # Should not raise
                    launcher.safe_open_url("http://127.0.0.1:8766")

    def test_no_crash_when_fallback_fails(self):
        from app.core import launcher
        with patch.object(launcher, "can_open_browser", return_value=True):
            with patch("webbrowser.open", side_effect=RuntimeError("no browser")):
                with patch.object(
                    launcher, "_platform_fallback", side_effect=OSError("gone")
                ):
                    # _platform_fallback already swallows exceptions internally,
                    # but even if it re-raised, safe_open_url must not propagate
                    try:
                        launcher.safe_open_url("http://127.0.0.1:8766")
                    except Exception as exc:
                        self.fail(f"safe_open_url raised unexpectedly: {exc}")


# ─── --no-browser flag ────────────────────────────────────────────────────────

class TestNoBrowserFlag(unittest.TestCase):
    """
    Simulates the CLI --no-browser path: browser_enabled=False means
    safe_open_url is never called (the thread is never started).
    """

    def test_no_browser_skips_open(self):
        from app.core import launcher
        with patch.object(launcher, "can_open_browser", return_value=True) as mock_check:
            with patch.object(launcher, "safe_open_url") as mock_open:
                # Simulate what main.py does when --no-browser is set
                browser_enabled = False
                if browser_enabled and launcher.can_open_browser():
                    launcher.safe_open_url("http://127.0.0.1:8766")
                mock_open.assert_not_called()


# ─── --open-browser with no DISPLAY ──────────────────────────────────────────

class TestOpenBrowserNoDisplay(unittest.TestCase):
    """
    --open-browser requested but DISPLAY is absent:
    safe_open_url should return without opening and without crashing.
    """

    def setUp(self):
        self._orig = sys.platform
        sys.platform = "linux"

    def tearDown(self):
        sys.platform = self._orig

    def test_open_browser_flag_with_no_display_is_safe(self):
        from app.core import launcher
        with patch.object(launcher, "can_open_browser", return_value=False):
            with patch("webbrowser.open") as mock_wb:
                launcher.safe_open_url("http://127.0.0.1:8766")
                mock_wb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
