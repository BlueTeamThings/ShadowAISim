"""
app/core/dep_bootstrap.py
─────────────────────────
Centralized dependency bootstrap for Shadow AI Simulator.

Checks and installs system dependencies required by all simulation modules:
  - python, pip, curl, node, npm, npx
  - Playwright browser binaries (Chromium)

Provides a portable download_file() helper that works without curl by falling
back to wget, PowerShell Invoke-WebRequest, requests, or stdlib urllib.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Awaitable, Optional

SYSTEM = platform.system()   # "Linux" | "Darwin" | "Windows"
Emitter = Callable[..., Awaitable[None]]


# ─────────────────────────────────────────────────────────────────────────────
# Package-manager detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_package_manager() -> Optional[str]:
    """Return the first available system package manager name, or None."""
    for pm in ("apt-get", "apt", "dnf", "yum", "pacman", "apk", "brew"):
        if shutil.which(pm):
            return pm
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run_sync(cmd: list, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _chromium_binary_exists() -> bool:
    """
    Return True if the Playwright-managed Chromium executable is present.

    Uses a subprocess so sync_playwright never runs inside an asyncio event loop
    (which would raise "Sync API inside the asyncio loop").
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "from playwright.sync_api import sync_playwright as _sp;"
             "p=_sp().start();"
             "import pathlib,sys;"
             "ok=pathlib.Path(p.chromium.executable_path).exists();"
             "p.stop();"
             "sys.exit(0 if ok else 1)"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_chromium_path() -> Optional[str]:
    """
    Return the Playwright-managed Chromium executable path via subprocess.
    Safe to call from sync or async contexts.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "from playwright.sync_api import sync_playwright as _sp;"
             "p=_sp().start();"
             "print(p.chromium.executable_path);"
             "p.stop()"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            path = result.stdout.strip()
            if path:
                return path
    except Exception:
        pass
    return None


def _ollama_installed() -> bool:
    return _cmd_exists("ollama")


def _refresh_path() -> None:
    """Extend PATH with common binary directories so freshly-installed tools are found."""
    extra = [
        "/usr/bin", "/usr/local/bin", "/usr/local/sbin", "/usr/sbin", "/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".nvm" / "versions" / "node" / "bin"),
        "/usr/share/nvm/init-nvm.sh",
    ]
    current = os.environ.get("PATH", "").split(":")
    for p in extra:
        if p not in current:
            current.append(p)
    os.environ["PATH"] = ":".join(p for p in current if p)
    try:
        import importlib
        importlib.invalidate_caches()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous preflight check
# ─────────────────────────────────────────────────────────────────────────────

def run_preflight_check() -> dict:
    """
    Run a synchronous preflight dependency check.

    Returns a dict with keys for each dependency. Each value is a dict with:
      - ok (bool)
      - path (str or None)
      - note (str, optional)
    """
    pip_path = shutil.which("pip") or shutil.which("pip3")
    chromium_path = _get_chromium_path()
    chromium_ok   = bool(chromium_path and Path(chromium_path).exists())

    playwright_importable = False
    try:
        import playwright  # noqa: F401
        playwright_importable = True
    except ImportError:
        pass

    node_ok = _cmd_exists("node")
    npm_ok  = _cmd_exists("npm")
    npx_ok  = _cmd_exists("npx")

    return {
        "package_manager": {"value": detect_package_manager() or "none"},
        "python":    {"ok": True,       "path": sys.executable},
        "pip":       {"ok": bool(pip_path), "path": pip_path},
        "curl":      {"ok": _cmd_exists("curl"),  "path": shutil.which("curl")},
        "node":      {"ok": node_ok,    "path": shutil.which("node")},
        "npm":       {"ok": npm_ok,     "path": shutil.which("npm")},
        "npx":       {"ok": npx_ok,     "path": shutil.which("npx")},
        "playwright":{"ok": playwright_importable, "note": "python package"},
        "chromium":  {"ok": chromium_ok, "path": chromium_path},
        "ollama":    {"ok": _ollama_installed(), "path": shutil.which("ollama")},
        "mcp_capable":       {"ok": npx_ok or npm_ok,
                              "note": "npm/npx available" if (npx_ok or npm_ok) else "no npm/npx"},
        "api_probe_capable": {"ok": True, "note": "httpx available"},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Async preflight check (with optional event emission)
# ─────────────────────────────────────────────────────────────────────────────

async def run_preflight_check_async(emit: Optional[Emitter] = None) -> dict:
    """Async wrapper around run_preflight_check with optional SSE emission."""
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, run_preflight_check)

    if emit:
        await emit("INFO", "PREFLIGHT", "=== Dependency Preflight Check ===", "", "")
        pm = results.get("package_manager", {}).get("value", "none")
        await emit("INFO", "PREFLIGHT", f"  Package manager: {pm}", "", "")

        skip = {"package_manager"}
        for key, val in results.items():
            if key in skip:
                continue
            ok   = val.get("ok", False)
            level = "SUCCESS" if ok else "WARN"
            path  = val.get("path") or val.get("note", "not found")
            mark  = "✓" if ok else "✗"
            await emit(level, "PREFLIGHT", f"  {mark} {key}: {path}", "", "")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Linux package install helper
# ─────────────────────────────────────────────────────────────────────────────

def _install_package_linux(package: str) -> bool:
    """Install *package* with the available package manager. Returns True on success."""
    pm = detect_package_manager()
    if not pm:
        return False

    cmd_map: dict[str, list[str]] = {
        "apt-get": ["sudo", "apt-get", "install", "-y", package],
        "apt":     ["sudo", "apt",     "install", "-y", package],
        "dnf":     ["sudo", "dnf",     "install", "-y", package],
        "yum":     ["sudo", "yum",     "install", "-y", package],
        "pacman":  ["sudo", "pacman",  "-S", "--noconfirm", package],
        "apk":     ["sudo", "apk",     "add", "--no-cache", package],
        "brew":    ["brew", "install", package],
    }
    cmd = cmd_map.get(pm)
    if not cmd:
        return False

    try:
        result = _run_sync(cmd, timeout=180)
        return result.returncode == 0
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ensure_system_dependencies
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_system_dependencies(emit: Optional[Emitter] = None) -> dict:
    """
    Verify all required system dependencies and auto-install missing ones on Linux.

    Returns a summary dict:  { "curl": "ok"|"installed"|"missing", ... }
    """
    results: dict[str, str] = {}

    async def _log(level: str, msg: str) -> None:
        if emit:
            await emit(level, "DEPS", msg, "", "")

    await _log("INFO", "Checking system dependencies…")

    # ── curl ──────────────────────────────────────────────────────────────────
    if _cmd_exists("curl"):
        results["curl"] = "ok"
        await _log("SUCCESS", "  ✓ curl found")
    elif SYSTEM == "Linux":
        await _log("WARN", "  ✗ curl not found — attempting auto-install…")
        ok = _install_package_linux("curl")
        results["curl"] = "installed" if ok else "missing"
        if ok:
            await _log("SUCCESS", "  ✓ curl installed")
        else:
            await _log("WARN", "  ✗ curl install failed — Python urllib fallback will be used for downloads")
    elif SYSTEM == "Windows":
        results["curl"] = "missing"
        await _log("WARN", "  ✗ curl not found — PowerShell Invoke-WebRequest will be used for downloads")
    else:
        results["curl"] = "missing"
        await _log("WARN", "  ✗ curl not found — Python urllib fallback will be used")

    # ── Node.js toolchain ─────────────────────────────────────────────────────
    node_ok = _cmd_exists("node")
    npm_ok  = _cmd_exists("npm")
    npx_ok  = _cmd_exists("npx")

    if node_ok and npm_ok and npx_ok:
        results["node_toolchain"] = "ok"
        await _log("SUCCESS", "  ✓ node / npm / npx found")
    else:
        missing = [t for t, ok in [("node", node_ok), ("npm", npm_ok), ("npx", npx_ok)] if not ok]
        await _log("WARN", f"  ✗ Missing: {', '.join(missing)}")
        if SYSTEM == "Linux":
            installed = await ensure_node_toolchain(emit)
            results["node_toolchain"] = "installed" if installed else "missing"
        elif SYSTEM == "Windows":
            results["node_toolchain"] = "missing"
            await _log("WARN", "  Install Node.js from https://nodejs.org/ (includes npm and npx)")
        else:
            results["node_toolchain"] = "missing"

    # ── Playwright Chromium ───────────────────────────────────────────────────
    pw_result = await ensure_playwright_browsers(emit)
    results["playwright_chromium"] = pw_result

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ensure_node_toolchain
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_node_toolchain(emit: Optional[Emitter] = None) -> bool:
    """
    Install Node.js, npm, and npx on Linux if missing.
    Returns True when all three are available after the attempt.
    """
    async def _log(level: str, msg: str) -> None:
        if emit:
            await emit(level, "DEPS", msg, "", "")

    if SYSTEM != "Linux":
        return _cmd_exists("node") and _cmd_exists("npm") and _cmd_exists("npx")

    pm = detect_package_manager()
    if not pm:
        await _log("WARN", "  No package manager available — cannot auto-install Node.js")
        return False

    node_pkgs: dict[str, list[str]] = {
        "apt-get": ["nodejs", "npm"],
        "apt":     ["nodejs", "npm"],
        "dnf":     ["nodejs", "npm"],
        "yum":     ["nodejs", "npm"],
        "pacman":  ["nodejs", "npm"],
        "apk":     ["nodejs", "npm"],
        "brew":    ["node"],
    }
    packages = node_pkgs.get(pm, ["nodejs", "npm"])

    await _log("INFO", f"  Installing Node.js toolchain via {pm}…")
    for pkg in packages:
        ok = _install_package_linux(pkg)
        if not ok:
            await _log("WARN", f"  Failed to install {pkg}")

    _refresh_path()

    node_ok = _cmd_exists("node")
    npm_ok  = _cmd_exists("npm")
    npx_ok  = _cmd_exists("npx")

    # npx ships with npm ≥ 5.2 but might need a separate install on older systems
    if npm_ok and not npx_ok:
        try:
            subprocess.run(["npm", "install", "-g", "npx"],
                           capture_output=True, timeout=60)
            _refresh_path()
            npx_ok = _cmd_exists("npx")
        except Exception:
            pass

    if node_ok and npm_ok and npx_ok:
        await _log("SUCCESS", "  ✓ Node.js toolchain ready")
        return True

    missing = [t for t, ok in [("node", node_ok), ("npm", npm_ok), ("npx", npx_ok)] if not ok]
    await _log("WARN", f"  ✗ Still missing after install attempt: {', '.join(missing)}")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# ensure_playwright_browsers
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_playwright_browsers(emit: Optional[Emitter] = None) -> str:
    """
    Install Playwright Chromium if not already present.
    On Linux, also installs OS-level browser dependencies.

    Returns: "ok" | "installed" | "failed"
    """
    async def _log(level: str, msg: str) -> None:
        if emit:
            await emit(level, "DEPS", msg, "", "")

    try:
        import playwright  # noqa: F401
    except ImportError:
        await _log("WARN", "  Playwright python package not installed — run: pip install playwright")
        return "failed"

    if _chromium_binary_exists():
        await _log("SUCCESS", "  ✓ Playwright Chromium already installed")
        return "ok"

    await _log("INFO", "  Playwright Chromium not found — installing…")

    if SYSTEM == "Linux":
        await _log("INFO", "  Installing Chromium OS dependencies (playwright install-deps)…")
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: _run_sync(
                    [sys.executable, "-m", "playwright", "install-deps", "chromium"],
                    timeout=300,
                ),
            )
            if result.returncode != 0:
                await _log("WARN", f"  install-deps returned {result.returncode}: {result.stderr[:200]}")
        except Exception as exc:
            await _log("WARN", f"  install-deps error: {exc}")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _run_sync(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                timeout=300,
            ),
        )
        if result.returncode == 0:
            await _log("SUCCESS", "  ✓ Playwright Chromium installed")
            return "installed"
        await _log("WARN", f"  playwright install chromium failed (rc={result.returncode}): {result.stderr[:200]}")
        return "failed"
    except Exception as exc:
        await _log("WARN", f"  Could not install Playwright Chromium: {exc}")
        return "failed"


# ─────────────────────────────────────────────────────────────────────────────
# download_file — resilient cross-platform downloader
# ─────────────────────────────────────────────────────────────────────────────

def download_file(url: str, dest: "str | Path", timeout: int = 120) -> tuple[bool, str]:
    """
    Download *url* to *dest* using the best available method.

    Tries in order:
      1. curl   (if on PATH)
      2. wget   (if on PATH, Linux/macOS)
      3. PowerShell Invoke-WebRequest  (Windows)
      4. Python requests  (if installed)
      5. Python urllib.request  (stdlib — always available)

    Returns (success: bool, method_used: str).
    The caller can log which method was used for auditability.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 1. curl
    if shutil.which("curl"):
        try:
            r = _run_sync(
                ["curl", "-L", "-o", str(dest), "--silent", "--show-error",
                 "--max-time", str(timeout), url],
                timeout=timeout + 15,
            )
            if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                return True, "curl"
        except Exception:
            pass

    # 2. wget
    if SYSTEM != "Windows" and shutil.which("wget"):
        try:
            r = _run_sync(
                ["wget", "-q", "-O", str(dest), "--timeout", str(timeout), url],
                timeout=timeout + 15,
            )
            if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                return True, "wget"
        except Exception:
            pass

    # 3. PowerShell (Windows)
    if SYSTEM == "Windows" and shutil.which("powershell"):
        try:
            ps_cmd = (
                "[Net.ServicePointManager]::SecurityProtocol = "
                "[Net.SecurityProtocolType]::Tls12; "
                f"Invoke-WebRequest -Uri '{url}' -OutFile '{dest}' -UseBasicParsing"
            )
            r = _run_sync(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                timeout=timeout + 15,
            )
            if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                return True, "powershell"
        except Exception:
            pass

    # 4. requests
    try:
        import requests as _requests
        resp = _requests.get(
            url, stream=True, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True,
        )
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(65536):
                fh.write(chunk)
        if dest.exists() and dest.stat().st_size > 0:
            return True, "requests"
    except Exception:
        pass

    # 5. urllib (stdlib — always available)
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            with open(dest, "wb") as fh:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
        if dest.exists() and dest.stat().st_size > 0:
            return True, "urllib"
    except Exception:
        pass

    return False, "none"
