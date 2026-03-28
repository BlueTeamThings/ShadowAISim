"""
MCP (Model Context Protocol) Server installation and configuration injection simulator.

Simulates an employee connecting their local AI desktop client (Claude Desktop)
to sensitive corporate data sources via MCP servers. Designed to:

  1. Trigger EDR process-creation and network-download telemetry by running real
     package-manager commands (npx / pip) as subprocesses.

  2. Trigger File Integrity Monitoring (FIM) alerts by locating the AI client's
     configuration file, backing it up, injecting MCP server entries, and writing
     the modified file back to disk.

All MCP server arguments, connection strings, and credentials are simulated.

Install strategies per server:
  npm        – run npx command (generates real network + EDR telemetry)
  pip        – run pip install (generates process-creation telemetry)
  config_only – only modify the config file when package tools unavailable

MCP launch result classifications:
  MCP_SERVER_READY                   – process started, readiness signal detected
  PROCESS_STARTED_NO_PROTOCOL_EXERCISE – process alive but no protocol exercise yet
  STARTED_WAITING_FOR_ROOTS          – server started without an allowed directory
  ACTUAL_EXECUTION                   – process exited 0 (install completed)
  INSTALL_ATTEMPTED                  – process ran but exited non-zero (telemetry still generated)
  CONFIG_ONLY                        – no package manager; only config file modified
  PREREQ_MISSING                     – Node/pip unavailable and bootstrap failed
  MISSING_NODE_TOOLCHAIN             – npx/node not found, bootstrap also failed
  MCP_SERVER_EXITED                  – process exited unexpectedly
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

Emitter = Callable[..., Awaitable[None]]

SYSTEM = platform.system()   # "Linux" | "Darwin" | "Windows"

# Simulator data directory (relative to project root)
_PROJECT_ROOT    = Path(__file__).parent.parent.parent
_SIMULATOR_DATA  = _PROJECT_ROOT / "simulator_data"

# How long to wait for a long-running MCP server to show readiness signals
_READINESS_TIMEOUT = 5.0  # seconds

# Stderr/stdout patterns that indicate a successful MCP server startup
_READINESS_SIGNALS = [
    "running on stdio",
    "mcp server ready",
    "server started",
    "listening",
    "server is ready",
    "started successfully",
]

# Stderr lines that are benign startup messages, not errors
_BENIGN_STDERR_PATTERNS = [
    "usage:",
    "at least one directory",
    "secure mcp filesystem server",
    "started without allowed directories",
    "waiting for client to provide roots",
    "mcp filesystem server",
    "npm warn",
    "npm notice",
    "added ",
    "packages in",
    "run playwright",
    "up to date",
    "found 0",
    "audited",
]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mABCDEFGHJKSTfhilmnprsu]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _classify_stderr_line(line: str) -> str:
    """
    Return the appropriate log level for an MCP stderr line.

    Benign startup messages (usage text, 'running on stdio', npm noise)
    are classified as INFO. Only genuine errors are classified as WARN/ERROR.
    """
    lower = line.lower()
    if any(p in lower for p in _BENIGN_STDERR_PATTERNS):
        return "INFO"
    if any(w in lower for w in ("error:", "exception:", "fatal:", "uncaughtexception")):
        return "WARN"
    return "INFO"


# ─────────────────────────────────────────────────────────────────────────────
# MCP test allowed directory
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_mcp_allowed_dir() -> Path:
    """
    Create a safe test directory for the filesystem MCP server to expose.

    The filesystem server requires at least one allowed directory as an argument.
    Without it, the server starts in 'waiting for roots via MCP protocol' mode
    (which is a valid state but not useful for telemetry testing).
    """
    allowed_dir = _SIMULATOR_DATA / "mcp_allowed"
    allowed_dir.mkdir(parents=True, exist_ok=True)

    samples = {
        "README.md": (
            "# MCP Filesystem Simulation\n"
            "This directory exists for Shadow AI Simulator testing.\n"
            "It contains no real corporate data.\n"
        ),
        "sample_employees.txt": (
            "SIMULATED CORPORATE DATA — FOR TESTING ONLY\n"
            "Employee: John Doe, Dept: Engineering, ID: E-00142\n"
            "Employee: Jane Smith, Dept: Finance, ID: E-00891\n"
        ),
        "config.json": json.dumps({
            "type": "test",
            "purpose": "mcp_filesystem_simulation",
            "sensitive": False,
            "note": "synthetic data only",
        }, indent=2) + "\n",
    }
    for fname, content in samples.items():
        fpath = allowed_dir / fname
        if not fpath.exists():
            fpath.write_text(content, encoding="utf-8")

    return allowed_dir


# ─────────────────────────────────────────────────────────────────────────────
# MCP SERVER DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

MCP_SERVERS = [
    {
        "id":           "filesystem",
        "name":         "Local File System MCP Server",
        "description":  "Grants AI clients direct read/write access to the local filesystem. "
                        "Enables the AI to silently exfiltrate or modify any file the user can access.",
        "risk":         "CRITICAL",
        "risk_color":   "red",
        "data_type":    "Local File System Access",
        "install_method": "npm",
        # append_allowed_dir=True causes _get_install_cmd() to append the test dir at runtime.
        # The server requires ≥1 directory argument; without it, it starts in roots-waiting mode.
        "install_cmd":  ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
        "append_allowed_dir": True,
        "install_type": "npx",
        "pip_package":  None,
        "config_only_supported": True,
        "config_entry": {
            "command": "npx",
            "args":    ["-y", "@modelcontextprotocol/server-filesystem",
                        str(Path.home())],
        },
    },
    {
        "id":           "postgres",
        "name":         "PostgreSQL Database MCP Server",
        "description":  "Gives AI clients direct SQL query access to PostgreSQL databases. "
                        "Bypasses application-layer access controls.",
        "risk":         "CRITICAL",
        "risk_color":   "red",
        "data_type":    "Corporate Database Access",
        "install_method": "npm",
        "install_cmd":  ["npx", "-y", "@modelcontextprotocol/server-postgres",
                         "postgresql://admin:P%40ssw0rd123@db-prod.acme-internal.com:5432/corporate_db"],
        "append_allowed_dir": False,
        "install_type": "npx",
        "pip_package":  None,
        "config_only_supported": True,
        "config_entry": {
            "command": "npx",
            "args":    ["-y", "@modelcontextprotocol/server-postgres",
                        "postgresql://admin:P%40ssw0rd123@db-prod.acme-internal.com:5432/corporate_db"],
        },
    },
    {
        "id":           "github",
        "name":         "GitHub MCP Server",
        "description":  "Connects AI to GitHub repositories, issues, PRs, and organisation secrets.",
        "risk":         "HIGH",
        "risk_color":   "orange",
        "data_type":    "Source Code + Repository Secrets",
        "install_method": "npm",
        "install_cmd":  ["npx", "-y", "@modelcontextprotocol/server-github"],
        "append_allowed_dir": False,
        "install_type": "npx",
        "pip_package":  None,
        "config_only_supported": True,
        "config_entry": {
            "command": "npx",
            "args":    ["-y", "@modelcontextprotocol/server-github"],
            "env":     {
                "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_SIMULATEDredteamtesttoken00000000000",
            },
        },
    },
    {
        "id":           "gdrive",
        "name":         "Google Drive MCP Server",
        "description":  "Connects AI to corporate Google Drive — can silently read, search, "
                        "and exfiltrate documents, spreadsheets, and presentations.",
        "risk":         "HIGH",
        "risk_color":   "orange",
        "data_type":    "Corporate Documents (Google Drive)",
        "install_method": "npm",
        "install_cmd":  ["npx", "-y", "@modelcontextprotocol/server-gdrive"],
        "append_allowed_dir": False,
        "install_type": "npx",
        "pip_package":  None,
        "config_only_supported": True,
        "config_entry": {
            "command": "npx",
            "args":    ["-y", "@modelcontextprotocol/server-gdrive"],
        },
    },
    {
        "id":           "sqlite",
        "name":         "SQLite MCP Server (pip)",
        "description":  "pip-installed MCP server for local SQLite database access. "
                        "Demonstrates the pip install vector for Python-based MCP servers.",
        "risk":         "MEDIUM",
        "risk_color":   "yellow",
        "data_type":    "Local SQLite Database Access",
        "install_method": "pip",
        "install_cmd":  [sys.executable, "-m", "pip", "install", "--quiet", "mcp-server-sqlite"],
        "append_allowed_dir": False,
        "install_type": "pip",
        "pip_package":  "mcp-server-sqlite",
        "config_only_supported": True,
        "config_entry": {
            "command": sys.executable,
            "args":    ["-m", "mcp_server_sqlite",
                        "--db-path", "/tmp/acme_corporate_data.db"],
        },
    },
]

_MCP_BY_ID = {s["id"]: s for s in MCP_SERVERS}


# ─────────────────────────────────────────────────────────────────────────────
# Node/npm/npx dependency check
# ─────────────────────────────────────────────────────────────────────────────

def _node_toolchain_status() -> dict:
    return {
        "node": bool(shutil.which("node")),
        "npm":  bool(shutil.which("npm")),
        "npx":  bool(shutil.which("npx")),
    }


def _npx_available() -> bool:
    return bool(shutil.which("npx"))


async def _try_bootstrap_node(emit: Emitter, server_id: str) -> bool:
    """Attempt to install Node.js via dep_bootstrap. Returns True if npx is available after."""
    try:
        from app.core.dep_bootstrap import ensure_node_toolchain
        ok = await ensure_node_toolchain(emit)
        return ok and _npx_available()
    except Exception as exc:
        await emit("WARN", "MCP", f"Node.js bootstrap error: {exc}", server_id)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Install command builder
# ─────────────────────────────────────────────────────────────────────────────

def _get_install_cmd(server: dict) -> list[str]:
    """
    Return the install command for a server, appending the allowed directory
    for filesystem-type servers that require it.
    """
    cmd = list(server["install_cmd"])
    if server.get("append_allowed_dir"):
        allowed_dir = _ensure_mcp_allowed_dir()
        cmd.append(str(allowed_dir))
    return cmd


# ─────────────────────────────────────────────────────────────────────────────
# Claude Desktop config helpers
# ─────────────────────────────────────────────────────────────────────────────

def _claude_config_candidates() -> list[Path]:
    paths: list[Path] = []
    home = Path.home()
    if SYSTEM == "Darwin":
        paths.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    elif SYSTEM == "Windows":
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        paths.append(appdata / "Claude" / "claude_desktop_config.json")
    else:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        paths.append(xdg / "Claude" / "claude_desktop_config.json")
        paths.append(home / ".config" / "Claude" / "claude_desktop_config.json")
    return paths


def _find_claude_config() -> Path | None:
    for p in _claude_config_candidates():
        if p.exists():
            return p
    return None


def _create_dummy_config() -> Path:
    dummy_dir = Path(tempfile.gettempdir()) / "ShadowAISim_ClaudeConfig"
    dummy_dir.mkdir(parents=True, exist_ok=True)
    dummy_path = dummy_dir / "claude_desktop_config.json"
    dummy_path.write_text(
        json.dumps({"mcpServers": {}, "__dummy__": True}, indent=2),
        encoding="utf-8",
    )
    return dummy_path


# ─────────────────────────────────────────────────────────────────────────────
# npm/npx install strategy — with readiness detection for long-running servers
# ─────────────────────────────────────────────────────────────────────────────

async def _install_via_npm(server: dict, emit: Emitter) -> tuple[bool, str]:
    """
    Run the npx install command for the given MCP server.

    Handles two process lifecycles:
      SHORT-RUNNING: process exits within the readiness window (e.g. npm install only)
      LONG-RUNNING:  process starts a server and stays alive (e.g. filesystem, postgres)

    For long-running servers, we watch for readiness signals then terminate cleanly.
    stderr startup messages (usage text, "running on stdio") are classified as INFO, not errors.

    Returns (success: bool, telemetry_source: str)
    """
    name      = server["name"]
    server_id = server["id"]
    data_type = server["data_type"]
    cmd       = _get_install_cmd(server)
    cmd_str   = " ".join(str(c) for c in cmd)

    if not _npx_available():
        await emit("WARN", "MCP",
                   f"{name}: npx not found on PATH — attempting bootstrap…",
                   server_id, data_type)
        ok = await _try_bootstrap_node(emit, server_id)
        if not ok:
            await emit("WARN", "MCP",
                       f"{name}: Node.js toolchain unavailable. "
                       f"Falling back to config-only simulation. "
                       f"Classification: MISSING_NODE_TOOLCHAIN",
                       server_id, data_type)
            return False, "MISSING_NODE_TOOLCHAIN"

    await emit("INFO", "MCP",
               f"Executing ({server['install_type']}): {cmd_str}",
               server_id, data_type)

    ts_start = datetime.now(timezone.utc).isoformat()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        await emit("WARN", "MCP",
                   f"{name}: '{cmd[0]}' not found (FileNotFoundError). "
                   f"Classification: MISSING_NODE_TOOLCHAIN",
                   server_id, data_type)
        return False, "MISSING_NODE_TOOLCHAIN"
    except Exception as exc:
        await emit("ERROR", "MCP",
                   f"{name}: failed to start subprocess — {exc}", server_id, data_type)
        return False, "PREREQ_MISSING"

    # ── Stream readers ────────────────────────────────────────────────────────
    stderr_lines: list[str] = []
    process_ready = False

    async def _read_stdout():
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = _strip_ansi(line.decode(errors="replace")).rstrip()
            if text:
                await emit("INFO", "MCP", f"  [stdout] {text}", server_id)

    async def _read_stderr():
        nonlocal process_ready
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = _strip_ansi(line.decode(errors="replace")).rstrip()
            if not text:
                continue
            stderr_lines.append(text)
            level = _classify_stderr_line(text)
            await emit(level, "MCP", f"  [stderr] {text}", server_id)
            if any(sig in text.lower() for sig in _READINESS_SIGNALS):
                process_ready = True

    # ── Readiness window ──────────────────────────────────────────────────────
    # Wait up to _READINESS_TIMEOUT seconds for the process to either:
    #   a) Exit (short-running: install step only)
    #   b) Emit readiness text and keep running (long-running server)
    process_exited_in_window = True
    rc = None

    try:
        await asyncio.wait_for(
            asyncio.gather(_read_stdout(), _read_stderr()),
            timeout=_READINESS_TIMEOUT,
        )
        rc = await proc.wait()
        process_exited_in_window = True
    except asyncio.TimeoutError:
        # Process still running after window — it's a long-running server
        process_exited_in_window = False

    ts_end = datetime.now(timezone.utc).isoformat()

    # ── Classify result ───────────────────────────────────────────────────────
    if not process_exited_in_window:
        # Terminate the long-running process cleanly
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        if process_ready:
            await emit(
                "ALERT", "MCP",
                f"MCP SERVER STARTED: {name} — readiness signal detected, process alive. "
                f"EDR process-creation + network telemetry generated. "
                f"Classification: MCP_SERVER_READY",
                server_id, data_type,
            )
            return True, "MCP_SERVER_READY"
        else:
            await emit(
                "ALERT", "MCP",
                f"MCP PROCESS LAUNCHED: {name} — process alive after {_READINESS_TIMEOUT:.0f}s. "
                f"No MCP protocol exercise performed. "
                f"EDR process-creation + network telemetry generated. "
                f"Classification: PROCESS_STARTED_NO_PROTOCOL_EXERCISE",
                server_id, data_type,
            )
            return True, "PROCESS_STARTED_NO_PROTOCOL_EXERCISE"

    # Process exited within the readiness window
    stderr_combined = " ".join(stderr_lines).lower()

    if rc == 0:
        await emit(
            "ALERT", "MCP",
            f"MCP INSTALL COMPLETE: {name} — command exited 0. "
            f"EDR process-creation + network telemetry generated. "
            f"Classification: ACTUAL_EXECUTION",
            server_id, data_type,
        )
        return True, "ACTUAL_EXECUTION"

    # Non-zero exit — check if it's a 'roots waiting' startup variant
    if "at least one directory" in stderr_combined or "waiting for client to provide roots" in stderr_combined:
        await emit(
            "WARN", "MCP",
            f"{name}: server started without an allowed directory. "
            f"Roots-waiting mode. To fix: pass a directory argument. "
            f"DNS + process telemetry generated. "
            f"Classification: STARTED_WAITING_FOR_ROOTS",
            server_id, data_type,
        )
        return False, "STARTED_WAITING_FOR_ROOTS"

    await emit(
        "WARN", "MCP",
        f"{name}: process exited {rc}. "
        f"Package may not be on npm yet, but process-creation and DNS telemetry generated. "
        f"Classification: INSTALL_ATTEMPTED",
        server_id, data_type,
    )
    return False, "INSTALL_ATTEMPTED"


# ─────────────────────────────────────────────────────────────────────────────
# pip install strategy
# ─────────────────────────────────────────────────────────────────────────────

async def _install_via_pip(server: dict, emit: Emitter) -> tuple[bool, str]:
    """Run pip install for a Python-based MCP server."""
    name      = server["name"]
    server_id = server["id"]
    data_type = server["data_type"]
    cmd       = list(server["install_cmd"])
    cmd_str   = " ".join(str(c) for c in cmd)

    await emit("INFO", "MCP", f"Executing (pip): {cmd_str}", server_id, data_type)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _relay(stream, label: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = _strip_ansi(line.decode(errors="replace")).rstrip()
                if text:
                    await emit("INFO", "MCP", f"  [{label}] {text}", server_id)

        await asyncio.gather(_relay(proc.stdout, "stdout"), _relay(proc.stderr, "stderr"))
        rc = await proc.wait()

    except Exception as exc:
        await emit("ERROR", "MCP",
                   f"{name}: pip subprocess error — {exc}", server_id, data_type)
        return False, "PREREQ_MISSING"

    if rc == 0:
        await emit("ALERT", "MCP",
                   f"MCP SERVER INSTALLED: {name} (pip) — package installed. "
                   f"Classification: ACTUAL_EXECUTION",
                   server_id, data_type)
        return True, "ACTUAL_EXECUTION"

    await emit("WARN", "MCP",
               f"{name}: pip exited {rc}. Classification: INSTALL_ATTEMPTED",
               server_id, data_type)
    return False, "INSTALL_ATTEMPTED"


# ─────────────────────────────────────────────────────────────────────────────
# Config-only simulation fallback
# ─────────────────────────────────────────────────────────────────────────────

async def _config_only_simulate(server: dict, emit: Emitter) -> tuple[bool, str]:
    """
    When no package manager is available, skip the install step.
    Config injection (FIM telemetry) is still performed in inject_mcp_config().
    """
    name      = server["name"]
    server_id = server["id"]
    data_type = server["data_type"]

    await emit("WARN", "MCP",
               f"{name}: Blocked due to missing prerequisite (no npm/pip available). "
               f"Package install skipped. Config injection will still generate FIM telemetry. "
               f"Classification: CONFIG_ONLY",
               server_id, data_type)
    return False, "CONFIG_ONLY"


# ─────────────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────────────

async def install_mcp_server(server_id: str, emit: Emitter) -> dict:
    """
    Run the package-manager command for the given MCP server as a real subprocess.

    Lifecycle phases logged:
      INSTALL PHASE  – package manager downloads the package
      LAUNCH PHASE   – server process starts (long-running servers)
      PROTOCOL PHASE – not exercised (marked PROCESS_STARTED_NO_PROTOCOL_EXERCISE)

    For the filesystem server, a safe test directory is created and passed as
    an argument to avoid the 'roots-waiting' mode.
    """
    server = _MCP_BY_ID.get(server_id)
    if not server:
        await emit("ERROR", "MCP", f"Unknown MCP server ID: {server_id}")
        return {"success": False, "error": "unknown_id"}

    name      = server["name"]
    data_type = server["data_type"]
    method    = server["install_method"]

    await emit("INFO", "MCP",
               f"Installing MCP server: {name}  (method: {method})",
               server_id, data_type)

    # Log the allowed directory for filesystem server
    if server.get("append_allowed_dir"):
        allowed_dir = _ensure_mcp_allowed_dir()
        await emit("INFO", "MCP",
                   f"  Filesystem server: using allowed dir → {allowed_dir}",
                   server_id, data_type)

    ts_start = datetime.now(timezone.utc).isoformat()

    if method == "npm":
        success, telemetry_source = await _install_via_npm(server, emit)
    elif method == "pip":
        success, telemetry_source = await _install_via_pip(server, emit)
    else:
        success, telemetry_source = await _config_only_simulate(server, emit)

    ts_end = datetime.now(timezone.utc).isoformat()

    return {
        "success":          success,
        "server_id":        server_id,
        "method":           method,
        "telemetry_source": telemetry_source,
        "phase":            "install+launch",
        "started_at":       ts_start,
        "finished_at":      ts_end,
    }


async def inject_mcp_config(server_ids: list[str], emit: Emitter) -> dict:
    """
    Locate the Claude Desktop config file (or create a dummy), back it up,
    inject MCP server entries, and write back — the primary FIM detection test.
    """
    config_path = _find_claude_config()
    is_dummy    = False

    if config_path is None:
        config_path = _create_dummy_config()
        is_dummy    = True
        await emit(
            "WARN", "MCP",
            f"Claude Desktop config not found on this {SYSTEM} system. "
            f"Created dummy config at: {config_path}  (FIM test will still run on this path)",
            str(config_path), "MCP Config Injection",
        )
    else:
        await emit(
            "INFO", "MCP",
            f"Found Claude Desktop config: {config_path}",
            str(config_path), "MCP Config Injection",
        )

    backup_path = Path(str(config_path) + ".bak")
    shutil.copy2(str(config_path), str(backup_path))
    await emit(
        "INFO", "MCP",
        f"Original config backed up → {backup_path}",
        str(config_path), "MCP Config Injection",
    )

    try:
        raw    = config_path.read_text(encoding="utf-8")
        config = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        config = {}

    if "mcpServers" not in config or not isinstance(config["mcpServers"], dict):
        config["mcpServers"] = {}

    injected_names: list[str] = []

    for sid in server_ids:
        server = _MCP_BY_ID.get(sid)
        if server:
            config["mcpServers"][sid] = server["config_entry"]
            injected_names.append(server["name"])
            await emit(
                "INFO", "MCP",
                f"  Injecting '{sid}' → {json.dumps(server['config_entry'])}",
                str(config_path), "MCP Config Injection",
            )

    if not injected_names:
        await emit("WARN", "MCP", "No valid server IDs provided — nothing injected.",
                   str(config_path))
        return {"success": False, "reason": "no_valid_ids"}

    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    servers_list = ", ".join(injected_names)
    await emit(
        "ALERT", "MCP",
        f"CONFIG INJECTED: Modified {config_path.name} — "
        f"added {len(injected_names)} MCP server(s): [{servers_list}]. "
        f"AI client will load these on next launch. FIM ALERT EXPECTED.",
        str(config_path), "MCP Config Injection",
    )

    if is_dummy:
        await emit(
            "INFO", "MCP",
            f"Note: config written to dummy path (Claude Desktop not installed). "
            f"Run Claude Desktop first to test against a real config.",
            str(config_path),
        )

    return {
        "success":      True,
        "config_path":  str(config_path),
        "backup_path":  str(backup_path),
        "is_dummy":     is_dummy,
        "injected":     injected_names,
        "injected_ids": server_ids,
    }


async def restore_mcp_config(emit: Emitter) -> dict:
    """Restore the Claude Desktop config from the .bak backup."""
    config_path = _find_claude_config()

    if config_path is None:
        dummy_path = Path(tempfile.gettempdir()) / "ShadowAISim_ClaudeConfig" / "claude_desktop_config.json"
        if dummy_path.exists():
            config_path = dummy_path

    if config_path is None:
        await emit("WARN", "MCP", "No config file found to restore.")
        return {"success": False, "reason": "no_config_found"}

    backup_path = Path(str(config_path) + ".bak")
    if not backup_path.exists():
        await emit("WARN", "MCP",
                   f"No backup found at {backup_path} — cannot restore.",
                   str(config_path))
        return {"success": False, "reason": "no_backup_found"}

    shutil.copy2(str(backup_path), str(config_path))
    backup_path.unlink(missing_ok=True)

    await emit(
        "SUCCESS", "MCP",
        f"Config restored from backup. MCP entries removed from {config_path.name}.",
        str(config_path), "MCP Config Restoration",
    )
    return {"success": True, "config_path": str(config_path)}
