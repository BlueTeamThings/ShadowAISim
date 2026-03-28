"""Installer/launcher regression tests for URL classification, dedupe, and startability."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.automation import installers
from app.automation.installers import STATUS


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestInstallerClassification(unittest.TestCase):

    def test_http_404_is_not_geo_blocked(self):
        self.assertEqual(installers._status_from_http(404), STATUS["HTTP_404_NOT_FOUND"])

    def test_dns_failure_not_geo_blocked(self):
        exc = Exception("[Errno -2] Name or service not known")
        self.assertEqual(installers.classify_network_error(exc), STATUS["DNS_RESOLUTION_FAILED"])

    def test_unsupported_linux_is_no_linux_build_available(self):
        app = {
            "app_id": "unsupported_app",
            "display_name": "Unsupported",
            "supported_platforms": ["windows"],
            "release_discovery_strategy": {"type": "stable_endpoint"},
            "download_url": "https://example.com/unsupported.exe",
            "fallback_urls": [],
        }
        out = _run(installers.resolve_download_url(app, platform_key="linux", arch_key="x64"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["classification"], STATUS["NO_LINUX_BUILD_AVAILABLE"])

    def test_fallback_url_resolution_works(self):
        app = {
            "app_id": "fallback_app",
            "display_name": "Fallback App",
            "supported_platforms": ["linux"],
            "release_discovery_strategy": {"type": "stable_endpoint"},
            "download_url": "https://example.com/stale",
            "fallback_urls": ["https://example.com/fallback"],
        }

        async def _fake_head(url):
            if "stale" in url:
                return {
                    "ok": False,
                    "classification": STATUS["HTTP_404_NOT_FOUND"],
                    "http_status": 404,
                    "resolved_url": url,
                }
            return {
                "ok": True,
                "classification": STATUS["INSTALLED_OK"],
                "http_status": 200,
                "resolved_url": url,
                "content_length": "10",
                "etag": None,
                "last_modified": None,
            }

        with patch("app.automation.installers._head_validate", new=AsyncMock(side_effect=_fake_head)):
            out = _run(installers.resolve_download_url(app, platform_key="linux", arch_key="x64"))

        self.assertTrue(out["ok"])
        self.assertEqual(out["resolved_url"], "https://example.com/fallback")


class TestInstallFlowBehavior(unittest.TestCase):

    def _app(self, app_id="ollama"):
        return {
            "app_id": app_id,
            "display_name": app_id,
            "supported_platforms": ["linux"],
            "install_type": "appimage",
            "release_discovery_strategy": {"type": "stable_endpoint"},
            "download_url": "https://example.com/a.AppImage",
            "fallback_urls": [],
            "binary_name": app_id,
            "launch_strategy": "binary",
            "post_install_validation_command": [app_id, "--version"],
        }

    def test_already_installed_short_circuit(self):
        app = self._app("already_installed_app")

        async def _emit(*a, **kw):
            return None

        with patch("app.automation.installers.preflight_install_state", new=AsyncMock(return_value={
            "installed": True,
            "binary_path": "/usr/bin/already_installed_app",
            "version": "1.2.3",
            "healthy": None,
        })):
            out = _run(installers.install_app(app, _emit, reinstall=False))

        self.assertTrue(out["installed"])
        self.assertEqual(out["classification"], STATUS["ALREADY_INSTALLED"])

    def test_duplicate_ollama_install_prevented(self):
        app = self._app("ollama")

        async def _emit(*a, **kw):
            return None

        async def _slow_download(*a, **kw):
            await asyncio.sleep(0.1)
            return {"ok": True, "classification": "DOWNLOADED", "path": __import__("pathlib").Path("/tmp/fake.AppImage"), "fmt": "appimage"}

        with patch("app.automation.installers.preflight_install_state", new=AsyncMock(return_value={"installed": False, "binary_path": "", "version": "", "healthy": None})), \
             patch("app.automation.installers.resolve_download_url", new=AsyncMock(return_value={"ok": True, "resolved_url": "https://example.com/a", "http_status": 200, "fallback_used": None})), \
             patch("app.automation.installers._download_to_cache", new=AsyncMock(side_effect=_slow_download)), \
             patch("app.automation.installers._install_artifact", new=AsyncMock(return_value=(True, "/tmp/ollama"))), \
             patch("app.automation.installers.validate_install", new=AsyncMock(return_value={"ok": True, "binary_path": "/usr/bin/ollama", "version": "v1"})):
            r1, r2 = _run(asyncio.gather(
                installers.install_app(app, _emit),
                installers.install_app(app, _emit),
            ))

        classes = {r1.get("classification"), r2.get("classification")}
        self.assertIn("INSTALL_SKIPPED_DUPLICATE_IN_FLIGHT", classes)


class TestStartAvailability(unittest.TestCase):

    def test_start_button_disabled_before_install(self):
        from app.routes import installers as installer_routes

        app = {
            "app_id": "manual_only",
            "display_name": "Manual",
            "desc": "",
            "category": "local_ai",
            "supported_platforms": ["linux"],
            "install_type": "manual",
            "homepage_url": "",
            "launch_strategy": "manual",
            "validation_strategy": "manual",
            "known_limitations": "",
            "requires_service": False,
        }

        with patch("app.routes.installers.preflight_install_state", new=AsyncMock(return_value={"installed": False, "binary_path": "", "version": ""})), \
             patch("app.routes.installers.resolve_download_url", new=AsyncMock(return_value={"ok": False, "classification": STATUS["NO_LINUX_BUILD_AVAILABLE"]})), \
             patch("app.routes.installers.get_process_info", return_value={"running": False, "process": None}):
            out = _run(installer_routes._app_status(app, include_resolution=False))

        self.assertFalse(out["start_enabled"])
        self.assertIn("Install", out["start_disabled_reason"])

    def test_start_button_works_after_install(self):
        from app.automation import launcher

        app = {
            "app_id": "demo_app",
            "display_name": "Demo",
            "launch_strategy": "binary",
            "launch_type": "binary",
            "launch_command_linux": ["demo_app", "--serve"],
            "post_install_validation_command": ["demo_app", "--version"],
        }

        class _Proc:
            pid = 4321
            returncode = None
            stdout = asyncio.StreamReader()
            stderr = asyncio.StreamReader()

        async def _emit(*a, **kw):
            return None

        with patch("app.automation.launcher.preflight_install_state", new=AsyncMock(return_value={"installed": True, "binary_path": "/usr/bin/demo_app", "version": "1.0.0"})), \
             patch("app.automation.launcher.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_Proc())), \
             patch("app.automation.launcher.asyncio.create_task", return_value=None):
            out = _run(launcher.start_app(app, _emit))

        self.assertTrue(out["start_attempted"])
        self.assertTrue(out["process_started"])
        self.assertEqual(out["pid"], 4321)


if __name__ == "__main__":
    unittest.main()
