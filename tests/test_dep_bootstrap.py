"""
tests/test_dep_bootstrap.py
────────────────────────────
Unit tests for app.core.dep_bootstrap — dependency detection and bootstrap logic.

Run with:  python -m pytest tests/test_dep_bootstrap.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestDetectPackageManager(unittest.TestCase):
    """detect_package_manager() returns the first available pm or None."""

    def test_returns_apt_when_available(self):
        from app.core.dep_bootstrap import detect_package_manager
        with patch("shutil.which", side_effect=lambda x: "/usr/bin/apt-get" if x == "apt-get" else None):
            self.assertEqual(detect_package_manager(), "apt-get")

    def test_returns_none_when_none_available(self):
        from app.core.dep_bootstrap import detect_package_manager
        with patch("shutil.which", return_value=None):
            self.assertIsNone(detect_package_manager())

    def test_returns_dnf_over_yum(self):
        from app.core.dep_bootstrap import detect_package_manager
        def _which(name):
            return "/usr/bin/" + name if name in ("dnf",) else None
        with patch("shutil.which", side_effect=_which):
            self.assertEqual(detect_package_manager(), "dnf")


class TestRunPreflightCheck(unittest.TestCase):
    """run_preflight_check() always returns a dict with expected keys."""

    def test_returns_all_keys(self):
        from app.core.dep_bootstrap import run_preflight_check
        result = run_preflight_check()
        for key in ("python", "pip", "curl", "node", "npm", "npx",
                    "playwright", "chromium", "ollama",
                    "mcp_capable", "api_probe_capable"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_python_always_ok(self):
        from app.core.dep_bootstrap import run_preflight_check
        result = run_preflight_check()
        self.assertTrue(result["python"]["ok"])
        self.assertEqual(result["python"]["path"], sys.executable)

    def test_curl_status_reflects_which(self):
        from app.core.dep_bootstrap import run_preflight_check
        with patch("shutil.which", side_effect=lambda x: "/usr/bin/curl" if x == "curl" else None):
            result = run_preflight_check()
            self.assertTrue(result["curl"]["ok"])

    def test_missing_curl_returns_false(self):
        from app.core.dep_bootstrap import run_preflight_check
        original_which = __import__("shutil").which
        def _which(name):
            if name == "curl":
                return None
            return original_which(name)
        with patch("shutil.which", side_effect=_which):
            result = run_preflight_check()
            self.assertFalse(result["curl"]["ok"])

    def test_missing_npx_reflected_in_mcp_capable(self):
        from app.core.dep_bootstrap import run_preflight_check
        with patch("shutil.which", return_value=None):
            result = run_preflight_check()
            # When nothing is on PATH, mcp_capable should be False
            self.assertFalse(result["mcp_capable"]["ok"])


class TestDownloadFile(unittest.TestCase):
    """download_file() falls through methods until one works."""

    def _dest(self, tmp_path: str) -> Path:
        return Path(tmp_path) / "test_download.bin"

    def test_uses_curl_when_available(self):
        from app.core.dep_bootstrap import download_file
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.bin"

            def _fake_run(cmd, timeout=120):
                if cmd[0] == "curl":
                    dest.write_bytes(b"FAKE_CONTENT")
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1)

            with patch("shutil.which", side_effect=lambda x: "/usr/bin/" + x if x == "curl" else None):
                with patch("app.core.dep_bootstrap._run_sync", side_effect=_fake_run):
                    ok, method = download_file("http://example.com/file", dest)
                    self.assertTrue(ok)
                    self.assertEqual(method, "curl")

    def test_falls_back_to_urllib_when_no_tools(self):
        from app.core.dep_bootstrap import download_file
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.bin"

            class _FakeResponse:
                def read(self, n):
                    if not hasattr(self, "_read"):
                        self._read = True
                        return b"URLLIB_CONTENT"
                    return b""
                def __enter__(self): return self
                def __exit__(self, *a): pass

            with patch("shutil.which", return_value=None):
                with patch("urllib.request.urlopen", return_value=_FakeResponse()):
                    ok, method = download_file("http://example.com/file", dest)
                    self.assertTrue(ok)
                    self.assertEqual(method, "urllib")

    def test_returns_false_when_all_methods_fail(self):
        from app.core.dep_bootstrap import download_file
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.bin"
            with patch("shutil.which", return_value=None):
                with patch("urllib.request.urlopen", side_effect=OSError("network down")):
                    ok, method = download_file("http://example.com/file", dest)
                    self.assertFalse(ok)
                    self.assertEqual(method, "none")


class TestEnsureNodeToolchain(unittest.TestCase):
    """ensure_node_toolchain() bootstraps Node.js on Linux when missing."""

    def setUp(self):
        self._orig_platform = __import__("app.core.dep_bootstrap", fromlist=["SYSTEM"]).SYSTEM

    def test_returns_true_when_all_tools_exist(self):
        import asyncio
        from app.core import dep_bootstrap
        with patch.object(dep_bootstrap, "SYSTEM", "Linux"):
            with patch("shutil.which", return_value="/usr/bin/something"):
                result = asyncio.get_event_loop().run_until_complete(
                    dep_bootstrap.ensure_node_toolchain()
                )
                self.assertTrue(result)

    def test_returns_false_when_no_package_manager(self):
        import asyncio
        from app.core import dep_bootstrap
        with patch.object(dep_bootstrap, "SYSTEM", "Linux"):
            with patch("shutil.which", return_value=None):
                result = asyncio.get_event_loop().run_until_complete(
                    dep_bootstrap.ensure_node_toolchain()
                )
                self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
