"""Installer/launcher regression tests for URL resolution and start safety."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
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

    def test_msty_linux_unverified_url_classified(self):
        app = {
            "app_id": "msty",
            "display_name": "Msty",
            "supported_platforms": ["linux"],
            "linux_auto_install_verified": False,
            "release_discovery_strategy": {"type": "unverified_linux_asset"},
            "download_url": "",
            "fallback_urls": [],
        }
        out = _run(installers.resolve_download_url(app, platform_key="linux", arch_key="x64"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["classification"], STATUS["UNVERIFIED_LINUX_ASSET_URL"])

    def test_package_manager_strategy_resolves_to_pkgmgr_url(self):
        app = {
            "app_id": "vscode",
            "display_name": "VS Code",
            "supported_platforms": ["linux", "windows"],
            "release_discovery_strategy": {"type": "package_manager"},
            "download_url": "",
            "fallback_urls": [],
        }
        out = _run(installers.resolve_download_url(app, platform_key="linux", arch_key="x64"))
        self.assertTrue(out["ok"])
        self.assertTrue(out["resolved_url"].startswith("pkgmgr://linux/vscode"))


class TestArtifactValidation(unittest.TestCase):

    def test_html_page_downloaded_instead_of_appimage_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bad.AppImage"
            target.write_text("<!DOCTYPE html><html><body>Not a binary</body></html>")
            out = installers.validate_artifact_file(target, "appimage", content_type="text/html", final_url="https://example.com/release")
            exists_after = target.exists()

        self.assertFalse(out["ok"])
        self.assertEqual(out["classification"], STATUS["HTML_PAGE_DOWNLOADED_INSTEAD_OF_BINARY"])
        self.assertEqual(out.get("reason"), "Installer Error: CDN Anti-bot triggered. Received HTML instead of executable binary.")
        self.assertFalse(exists_after)

    def test_lmstudio_landing_page_used_as_binary_fails_validation(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "LM-Studio.AppImage"
            target.write_text("<html><body>download page</body></html>")
            out = installers.validate_artifact_file(target, "appimage", content_type="text/html", final_url="https://lmstudio.ai/download")
            exists_after = target.exists()

        self.assertFalse(out["ok"])
        self.assertEqual(out["classification"], STATUS["HTML_PAGE_DOWNLOADED_INSTEAD_OF_BINARY"])
        self.assertFalse(exists_after)

    def test_invalid_exe_magic_bytes_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bad.exe"
            target.write_bytes(b"NOT-EXE" + b"\x00" * (300 * 1024))
            out = installers.validate_artifact_file(target, "exe", content_type="application/octet-stream", final_url="https://example.com/tool.exe")

        self.assertFalse(out["ok"])
        self.assertEqual(out["classification"], STATUS["DOWNLOADED_INVALID_ARTIFACT"])
        self.assertIn("MZ", out.get("reason", ""))

    def test_start_disabled_until_binary_validation_passes(self):
        from app.routes import installers as installer_routes

        app = {
            "app_id": "jan",
            "display_name": "Jan",
            "desc": "",
            "category": "local_ai",
            "supported_platforms": ["linux"],
            "install_type": "appimage",
            "homepage_url": "",
            "launch_strategy": "appimage",
            "launch_type": "appimage",
            "launch_command_linux": ["jan"],
            "validation_strategy": "binary_version",
            "known_limitations": "",
            "requires_service": False,
        }

        with patch("app.routes.installers.preflight_install_state", new=AsyncMock(return_value={"installed": True, "binary_path": "/tmp/jan", "version": "1"})), \
             patch("app.routes.installers.validate_install", new=AsyncMock(return_value={"ok": False, "classification": STATUS["START_BLOCKED_INVALID_ARTIFACT"], "reason": "invalid"})), \
             patch("app.routes.installers.resolve_download_url", new=AsyncMock(return_value={"ok": True, "resolved_url": "https://app.jan.ai/download/latest/linux-amd64-appimage"})), \
             patch("app.routes.installers.get_process_info", return_value={"running": False, "process": None}):
            out = _run(installer_routes._app_status(app, include_resolution=False))

        self.assertFalse(out["start_enabled"])
        self.assertIn("invalid", out["start_disabled_reason"])


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

    def test_open_webui_no_disk_space_classified(self):
        app = {
            "app_id": "open_webui",
            "display_name": "Open WebUI",
            "supported_platforms": ["linux"],
            "install_type": "pip",
            "release_discovery_strategy": {"type": "pypi_package", "package": "open-webui"},
            "fallback_urls": [],
            "binary_name": "open-webui",
            "launch_strategy": "cli",
            "post_install_validation_command": ["open-webui", "--help"],
        }

        async def _emit(*a, **kw):
            return None

        fake_usage = (10_000_000_000, 9_500_000_000, 500_000_000)
        with patch("app.automation.installers.preflight_install_state", new=AsyncMock(return_value={"installed": False, "binary_path": "", "version": "", "healthy": None})), \
             patch("app.automation.installers.shutil.disk_usage", return_value=fake_usage):
            out = _run(installers.install_app(app, _emit))

        self.assertFalse(out["installed"])
        self.assertEqual(out["classification"], STATUS["NO_SPACE_LEFT_ON_DEVICE"])

    def test_html_download_blocks_install(self):
        app = self._app("anythingllm")

        async def _emit(*a, **kw):
            return None

        with patch("app.automation.installers.preflight_install_state", new=AsyncMock(return_value={"installed": False, "binary_path": "", "version": "", "healthy": None})), \
             patch("app.automation.installers.resolve_download_url", new=AsyncMock(return_value={"ok": True, "resolved_url": "https://example.com/fake", "http_status": 200, "fallback_used": None})), \
             patch("app.automation.installers._download_to_cache", new=AsyncMock(return_value={"ok": False, "classification": STATUS["HTML_PAGE_DOWNLOADED_INSTEAD_OF_BINARY"], "resolved_url": "https://example.com/fake"})):
            out = _run(installers.install_app(app, _emit))

        self.assertFalse(out["installed"])
        self.assertEqual(out["classification"], STATUS["HTML_PAGE_DOWNLOADED_INSTEAD_OF_BINARY"])

    def test_package_manager_success_skips_download_path(self):
        app = {
            "app_id": "vscode",
            "display_name": "VS Code",
            "supported_platforms": ["linux", "windows"],
            "install_type": "package_manager",
            "release_discovery_strategy": {"type": "package_manager"},
            "download_url": "",
            "fallback_urls": [],
            "binary_name": "code",
            "launch_strategy": "binary",
            "post_install_validation_command": ["code", "--version"],
        }

        async def _emit(*a, **kw):
            return None

        with patch("app.automation.installers.preflight_install_state", new=AsyncMock(return_value={"installed": False, "binary_path": "", "version": "", "healthy": None})), \
             patch("app.automation.installers._install_via_package_manager", new=AsyncMock(return_value={"handled": True, "ok": True, "resolved_url": "pkgmgr://linux/vscode", "message": "ok", "attempts": []})), \
             patch("app.automation.installers.validate_install", new=AsyncMock(return_value={"ok": True, "binary_path": "/usr/bin/code", "version": "1.0", "reason": "ok"})), \
             patch("app.automation.installers.resolve_download_url", new=AsyncMock(side_effect=AssertionError("resolve_download_url should not be called"))):
            out = _run(installers.install_app(app, _emit))

        self.assertTrue(out["installed"])
        self.assertEqual(out["classification"], STATUS["INSTALLED_OK"])
        self.assertTrue(out.get("resolved_url", "").startswith("pkgmgr://"))


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

    def test_jan_direct_url_start_enabled_after_valid_install(self):
        from app.routes import installers as installer_routes

        app = {
            "app_id": "jan",
            "display_name": "Jan",
            "desc": "",
            "category": "local_ai",
            "supported_platforms": ["linux"],
            "install_type": "appimage",
            "homepage_url": "https://github.com/janhq/jan",
            "launch_strategy": "appimage",
            "launch_type": "appimage",
            "launch_command_linux": ["jan"],
            "validation_strategy": "binary_version",
            "known_limitations": "",
            "requires_service": False,
        }

        with patch("app.routes.installers.preflight_install_state", new=AsyncMock(return_value={"installed": True, "binary_path": "/tmp/Jan.AppImage", "version": "0.7.9"})), \
             patch("app.routes.installers.validate_install", new=AsyncMock(return_value={"ok": True, "classification": STATUS["STARTABLE"], "reason": "Installed artifact validated"})), \
             patch("app.routes.installers.resolve_download_url", new=AsyncMock(return_value={"ok": True, "resolved_url": "https://app.jan.ai/download/latest/linux-amd64-appimage"})), \
             patch("app.routes.installers.get_process_info", return_value={"running": False, "process": None}):
            out = _run(installer_routes._app_status(app, include_resolution=False))

        self.assertTrue(out["start_enabled"])

    def test_anythingllm_cdn_start_enabled_after_valid_install(self):
        from app.routes import installers as installer_routes

        app = {
            "app_id": "anythingllm",
            "display_name": "AnythingLLM",
            "desc": "",
            "category": "local_ai",
            "supported_platforms": ["linux"],
            "install_type": "appimage",
            "homepage_url": "https://docs.anythingllm.com/installation-desktop/linux",
            "launch_strategy": "appimage",
            "launch_type": "appimage",
            "launch_command_linux": ["AnythingLLMDesktop"],
            "validation_strategy": "binary_version",
            "known_limitations": "",
            "requires_service": False,
        }

        with patch("app.routes.installers.preflight_install_state", new=AsyncMock(return_value={"installed": True, "binary_path": "/tmp/AnythingLLM.AppImage", "version": "1.0"})), \
             patch("app.routes.installers.validate_install", new=AsyncMock(return_value={"ok": True, "classification": STATUS["STARTABLE"], "reason": "Installed artifact validated"})), \
             patch("app.routes.installers.resolve_download_url", new=AsyncMock(return_value={"ok": True, "resolved_url": "https://cdn.anythingllm.com/latest/AnythingLLMDesktop.AppImage"})), \
             patch("app.routes.installers.get_process_info", return_value={"running": False, "process": None}):
            out = _run(installer_routes._app_status(app, include_resolution=False))

        self.assertTrue(out["start_enabled"])


if __name__ == "__main__":
    unittest.main()
