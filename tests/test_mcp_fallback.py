"""
tests/test_mcp_fallback.py
──────────────────────────
Tests for MCP installer fallback behavior when Node.js / npx is missing.

Run with:  python -m pytest tests/test_mcp_fallback.py -v
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestNodeToolchainStatus(unittest.TestCase):
    """_node_toolchain_status() reflects PATH accurately."""

    def test_all_present(self):
        from app.automation.mcp_servers import _node_toolchain_status
        with patch("shutil.which", return_value="/usr/bin/something"):
            s = _node_toolchain_status()
            self.assertTrue(s["node"])
            self.assertTrue(s["npm"])
            self.assertTrue(s["npx"])

    def test_all_missing(self):
        from app.automation.mcp_servers import _node_toolchain_status
        with patch("shutil.which", return_value=None):
            s = _node_toolchain_status()
            self.assertFalse(s["node"])
            self.assertFalse(s["npm"])
            self.assertFalse(s["npx"])


class TestInstallMcpServerNpxMissing(unittest.TestCase):
    """
    When npx is missing and bootstrap fails, install_mcp_server() must:
    - Not crash
    - Return telemetry_source: PREREQ_MISSING or CONFIG_ONLY
    - Emit a WARN event, not ERROR
    """

    def _emit_collector(self):
        events = []
        async def _emit(level, cat, msg, *a, **kw):
            events.append({"level": level, "category": cat, "message": msg})
        return _emit, events

    def test_npx_missing_bootstrap_fails_returns_prereq_missing(self):
        from app.automation import mcp_servers

        emit, events = self._emit_collector()

        # npx not found anywhere, bootstrap also fails
        with patch("shutil.which", return_value=None):
            with patch.object(mcp_servers, "_try_bootstrap_node",
                              new=AsyncMock(return_value=False)):
                result = _run(mcp_servers.install_mcp_server("filesystem", emit))

        self.assertIn(result["telemetry_source"],
                      ("PREREQ_MISSING", "CONFIG_ONLY", "MISSING_NODE_TOOLCHAIN"))
        self.assertFalse(result["success"])
        # Must not emit ERROR (only WARN is acceptable for a missing prereq)
        error_events = [e for e in events if e["level"] == "ERROR"]
        self.assertEqual(len(error_events), 0,
                         f"Expected no ERROR events but got: {error_events}")

    def test_pip_server_always_runs_without_npx(self):
        """SQLite MCP server uses pip, not npx — should attempt install regardless."""
        from app.automation import mcp_servers

        emit, events = self._emit_collector()

        fake_proc = MagicMock()
        fake_proc.stdout = MagicMock(readline=AsyncMock(return_value=b""))
        fake_proc.stderr = MagicMock(readline=AsyncMock(return_value=b""))
        fake_proc.wait = AsyncMock(return_value=0)

        with patch("shutil.which", return_value=None):
            with patch("asyncio.create_subprocess_exec",
                       new=AsyncMock(return_value=fake_proc)):
                result = _run(mcp_servers.install_mcp_server("sqlite", emit))

        # sqlite uses pip — should attempt regardless of node/npx
        self.assertEqual(result["method"], "pip")

    def test_unknown_server_id_returns_error(self):
        from app.automation import mcp_servers

        emit, events = self._emit_collector()
        result = _run(mcp_servers.install_mcp_server("nonexistent_server_xyz", emit))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "unknown_id")


class TestMcpServerDefinitions(unittest.TestCase):
    """All MCP server definitions have required fields."""

    def test_all_servers_have_required_fields(self):
        from app.automation.mcp_servers import MCP_SERVERS
        required = ("id", "name", "description", "risk", "data_type",
                    "install_method", "config_entry", "config_only_supported")
        for server in MCP_SERVERS:
            for field in required:
                self.assertIn(field, server,
                              f"Server '{server.get('id')}' missing field: {field}")

    def test_npm_servers_have_install_cmd(self):
        from app.automation.mcp_servers import MCP_SERVERS
        for server in MCP_SERVERS:
            if server["install_method"] == "npm":
                self.assertIn("install_cmd", server)
                self.assertEqual(server["install_cmd"][0], "npx")

    def test_pip_servers_have_pip_package(self):
        from app.automation.mcp_servers import MCP_SERVERS
        for server in MCP_SERVERS:
            if server["install_method"] == "pip":
                self.assertIn("pip_package", server)


class TestConfigOnlyFallback(unittest.TestCase):
    """_config_only_simulate() emits WARN and returns CONFIG_ONLY telemetry source."""

    def test_config_only_emits_warn_not_error(self):
        from app.automation.mcp_servers import _config_only_simulate, MCP_SERVERS

        server = MCP_SERVERS[0]  # filesystem
        events = []

        async def _emit(level, cat, msg, *a, **kw):
            events.append({"level": level})

        success, source = _run(_config_only_simulate(server, _emit))

        self.assertFalse(success)
        self.assertEqual(source, "CONFIG_ONLY")
        levels = [e["level"] for e in events]
        self.assertNotIn("ERROR", levels)
        self.assertIn("WARN", levels)


class TestStderrClassification(unittest.TestCase):
    """_classify_stderr_line() must return INFO for benign MCP startup messages."""

    def test_running_on_stdio_is_info(self):
        from app.automation.mcp_servers import _classify_stderr_line
        self.assertEqual(_classify_stderr_line("Secure MCP Filesystem Server running on stdio"), "INFO")

    def test_usage_line_is_info(self):
        from app.automation.mcp_servers import _classify_stderr_line
        self.assertEqual(_classify_stderr_line("usage: npx @modelcontextprotocol/server-filesystem <dir>"), "INFO")

    def test_at_least_one_directory_is_info(self):
        from app.automation.mcp_servers import _classify_stderr_line
        self.assertEqual(_classify_stderr_line("At least one directory must be provided"), "INFO")

    def test_waiting_for_client_roots_is_info(self):
        from app.automation.mcp_servers import _classify_stderr_line
        self.assertEqual(_classify_stderr_line("waiting for client to provide roots via MCP protocol"), "INFO")

    def test_npm_warn_is_info(self):
        from app.automation.mcp_servers import _classify_stderr_line
        self.assertEqual(_classify_stderr_line("npm warn deprecated some-pkg"), "INFO")

    def test_genuine_error_is_warn(self):
        from app.automation.mcp_servers import _classify_stderr_line
        self.assertEqual(_classify_stderr_line("Error: ENOENT: no such file or directory"), "WARN")

    def test_exception_line_is_warn(self):
        from app.automation.mcp_servers import _classify_stderr_line
        self.assertEqual(_classify_stderr_line("Exception: something exploded"), "WARN")


class TestMcpFilesystemAllowedDir(unittest.TestCase):
    """_get_install_cmd() appends the allowed dir for servers with append_allowed_dir=True."""

    def test_filesystem_server_gets_dir_appended(self):
        from app.automation.mcp_servers import _get_install_cmd, MCP_SERVERS

        fs_server = next(s for s in MCP_SERVERS if s["id"] == "filesystem")
        self.assertTrue(fs_server.get("append_allowed_dir"),
                        "filesystem server must have append_allowed_dir=True")

        with patch("app.automation.mcp_servers._ensure_mcp_allowed_dir",
                   return_value=Path("/tmp/test_mcp_allowed")):
            cmd = _get_install_cmd(fs_server)

        self.assertIn("/tmp/test_mcp_allowed", cmd,
                      "allowed dir must be appended to the command")

    def test_non_filesystem_server_does_not_get_dir_appended(self):
        from app.automation.mcp_servers import _get_install_cmd, MCP_SERVERS

        # postgres is a non-filesystem npm server
        pg_server = next((s for s in MCP_SERVERS if s["id"] == "postgres"), None)
        if pg_server is None:
            self.skipTest("postgres server not in MCP_SERVERS")

        self.assertFalse(pg_server.get("append_allowed_dir"),
                         "postgres server must NOT have append_allowed_dir=True")

        with patch("app.automation.mcp_servers._ensure_mcp_allowed_dir",
                   return_value=Path("/tmp/should_not_appear")):
            cmd = _get_install_cmd(pg_server)

        self.assertNotIn("/tmp/should_not_appear", cmd)


class TestMcpReadinessClassifications(unittest.TestCase):
    """
    _install_via_npm() readiness window logic:
      - process alive, readiness signal seen → MCP_SERVER_READY (success=True)
      - process alive, no readiness signal → PROCESS_STARTED_NO_PROTOCOL_EXERCISE (success=True)
    """

    def _emit_collector(self):
        events = []
        async def _emit(level, cat, msg, *a, **kw):
            events.append({"level": level, "category": cat, "message": msg})
        return _emit, events

    def _make_proc(self, *, stdout_lines=None, stderr_lines=None, exit_code=0,
                   hang=False):
        """Build a fake asyncio subprocess with controllable stdout/stderr."""
        stdout_data = [l.encode() for l in (stdout_lines or [])] + ([b""] if not hang else [])
        stderr_data = [l.encode() for l in (stderr_lines or [])] + ([b""] if not hang else [])

        stdout_iter = iter(stdout_data)
        stderr_iter = iter(stderr_data)

        if hang:
            # Emit provided lines first, then hang forever (never send EOF)
            async def _stdout_readline():
                try:
                    return next(stdout_iter)
                except StopIteration:
                    await asyncio.sleep(100)  # will be cut by wait_for timeout
                    return b""

            async def _stderr_readline():
                try:
                    return next(stderr_iter)
                except StopIteration:
                    await asyncio.sleep(100)
                    return b""
        else:
            async def _stdout_readline():
                return next(stdout_iter, b"")

            async def _stderr_readline():
                return next(stderr_iter, b"")

        proc = MagicMock()
        proc.stdout = MagicMock(readline=_stdout_readline)
        proc.stderr = MagicMock(readline=_stderr_readline)
        proc.wait   = AsyncMock(return_value=exit_code)
        proc.terminate = MagicMock()
        proc.kill   = MagicMock()
        return proc

    def test_process_alive_with_readiness_signal_is_mcp_server_ready(self):
        from app.automation import mcp_servers

        emit, events = self._emit_collector()
        fs_server = next(s for s in mcp_servers.MCP_SERVERS if s["id"] == "filesystem")

        # Process hangs (long-running), but stderr has a readiness signal
        proc = self._make_proc(
            stderr_lines=["Secure MCP Filesystem Server running on stdio"],
            hang=True,
        )

        with patch("shutil.which", return_value="/usr/bin/npx"):
            with patch("asyncio.create_subprocess_exec",
                       new=AsyncMock(return_value=proc)):
                with patch("app.automation.mcp_servers._ensure_mcp_allowed_dir",
                           return_value=Path("/tmp/mcp_test")):
                    # Patch the readiness timeout to be very short so the test runs fast
                    with patch.object(mcp_servers, "_READINESS_TIMEOUT", 0.1):
                        result = _run(mcp_servers._install_via_npm(fs_server, emit))

        success, source = result
        self.assertTrue(success)
        self.assertEqual(source, "MCP_SERVER_READY")

    def test_process_alive_without_readiness_signal_is_process_started(self):
        from app.automation import mcp_servers

        emit, events = self._emit_collector()
        fs_server = next(s for s in mcp_servers.MCP_SERVERS if s["id"] == "filesystem")

        proc = self._make_proc(hang=True)

        with patch("shutil.which", return_value="/usr/bin/npx"):
            with patch("asyncio.create_subprocess_exec",
                       new=AsyncMock(return_value=proc)):
                with patch("app.automation.mcp_servers._ensure_mcp_allowed_dir",
                           return_value=Path("/tmp/mcp_test")):
                    with patch.object(mcp_servers, "_READINESS_TIMEOUT", 0.1):
                        result = _run(mcp_servers._install_via_npm(fs_server, emit))

        success, source = result
        self.assertTrue(success)
        self.assertEqual(source, "PROCESS_STARTED_NO_PROTOCOL_EXERCISE")

    def test_filesystem_mcp_without_allowed_dir_started_waiting_for_roots(self):
        """
        If the process exits and stderr mentions 'at least one directory',
        classify as STARTED_WAITING_FOR_ROOTS.
        """
        from app.automation import mcp_servers

        emit, events = self._emit_collector()
        fs_server = next(s for s in mcp_servers.MCP_SERVERS if s["id"] == "filesystem")

        proc = self._make_proc(
            stderr_lines=["At least one directory must be provided as an argument"],
            hang=False,
            exit_code=1,
        )

        with patch("shutil.which", return_value="/usr/bin/npx"):
            with patch("asyncio.create_subprocess_exec",
                       new=AsyncMock(return_value=proc)):
                with patch("app.automation.mcp_servers._ensure_mcp_allowed_dir",
                           return_value=Path("/tmp/mcp_test")):
                    with patch.object(mcp_servers, "_READINESS_TIMEOUT", 0.1):
                        result = _run(mcp_servers._install_via_npm(fs_server, emit))

        # "at least one directory" in stderr → STARTED_WAITING_FOR_ROOTS
        _success, source = result
        self.assertEqual(source, "STARTED_WAITING_FOR_ROOTS")

    def test_stderr_startup_text_does_not_emit_error_events(self):
        """
        Benign MCP startup messages on stderr must not produce ERROR-level events.
        This is the regression test for the 'startup stderr treated as failure' bug.
        """
        from app.automation import mcp_servers

        emit, events = self._emit_collector()
        fs_server = next(s for s in mcp_servers.MCP_SERVERS if s["id"] == "filesystem")

        proc = self._make_proc(
            stderr_lines=[
                "Secure MCP Filesystem Server running on stdio",
                "Started without allowed directories - waiting for client to provide roots",
                "npm warn deprecated old-pkg@1.0.0: please upgrade",
            ],
            hang=True,
        )

        with patch("shutil.which", return_value="/usr/bin/npx"):
            with patch("asyncio.create_subprocess_exec",
                       new=AsyncMock(return_value=proc)):
                with patch("app.automation.mcp_servers._ensure_mcp_allowed_dir",
                           return_value=Path("/tmp/mcp_test")):
                    with patch.object(mcp_servers, "_READINESS_TIMEOUT", 0.1):
                        _run(mcp_servers._install_via_npm(fs_server, emit))

        error_events = [e for e in events if e["level"] == "ERROR"]
        self.assertEqual(len(error_events), 0,
                         f"Benign startup messages emitted ERROR events: {error_events}")


if __name__ == "__main__":
    unittest.main()
