"""
app/core/launcher.py
~~~~~~~~~~~~~~~~~~~~
Centralized, headless-safe browser-launch logic for Shadow AI Simulator.

All browser-open decisions go through here.  Nothing else in the project
should call webbrowser, xdg-open, or subprocess to open a URL.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import webbrowser

log = logging.getLogger("shadow_ai.launcher")


# ─── Environment probe ────────────────────────────────────────────────────────

def _is_root() -> bool:
    """Return True when running as root (UID 0) on POSIX."""
    return hasattr(os, "getuid") and os.getuid() == 0


def _has_display() -> bool:
    """Return True when a graphical display variable is set."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _xdg_runtime_ok() -> bool:
    """Return True when XDG_RUNTIME_DIR is set AND the directory is writable."""
    xrt = os.environ.get("XDG_RUNTIME_DIR", "")
    if not xrt:
        return False
    return os.path.isdir(xrt) and os.access(xrt, os.W_OK)


def _looks_like_ssh() -> bool:
    """Return True when we appear to be running inside an SSH session."""
    return bool(
        os.environ.get("SSH_CLIENT")
        or os.environ.get("SSH_TTY")
        or os.environ.get("SSH_CONNECTION")
    )


def _looks_like_container() -> bool:
    """Return True when common container/CI signals are present."""
    indicators = ["container", "CI", "DOCKER", "KUBERNETES_SERVICE_HOST"]
    return any(os.environ.get(k) for k in indicators) or os.path.exists("/.dockerenv")


def _browser_executable_exists() -> bool:
    """Return True when at least one known browser is on PATH."""
    candidates = [
        "google-chrome", "google-chrome-stable",
        "chromium", "chromium-browser",
        "firefox", "firefox-esr",
        "microsoft-edge",
        "brave-browser",
    ]
    return any(shutil.which(b) for b in candidates)


def _xdg_open_exists() -> bool:
    return shutil.which("xdg-open") is not None


# ─── Primary detection function ───────────────────────────────────────────────

def can_open_browser() -> bool:
    """
    Return True only when it is safe to attempt opening a browser.

    Checks performed (all must pass on Linux):
        • DISPLAY or WAYLAND_DISPLAY is set
        • XDG_RUNTIME_DIR exists and is writable
        • Not running as root
        • Not an SSH session
        • Not inside a container/CI environment
        • xdg-open is present on PATH
        • At least one browser executable is on PATH

    On Windows the check is simpler — we trust the OS to handle it.
    On macOS we just verify we are not in SSH.
    """
    platform = sys.platform

    if platform == "win32":
        result = True
        reason = "Windows desktop — browser open allowed"

    elif platform == "darwin":
        if _looks_like_ssh():
            result = False
            reason = "macOS SSH session — headless, skipping browser"
        else:
            result = True
            reason = "macOS desktop — browser open allowed"

    else:  # Linux / other POSIX
        checks: list[tuple[bool, str]] = [
            (_has_display(),          "DISPLAY/WAYLAND_DISPLAY not set"),
            (_xdg_runtime_ok(),       "XDG_RUNTIME_DIR missing or not writable"),
            (not _is_root(),          "running as root — skipping browser"),
            (not _looks_like_ssh(),   "SSH session detected"),
            (not _looks_like_container(), "container/CI environment detected"),
            (_xdg_open_exists(),      "xdg-open not found"),
            (_browser_executable_exists(), "no browser executable found on PATH"),
        ]
        failed = [msg for ok, msg in checks if not ok]
        if failed:
            result = False
            reason = "; ".join(failed)
        else:
            result = True
            reason = "GUI session confirmed — browser open allowed"

    log.debug("can_open_browser → %s (%s)", result, reason)
    return result


# ─── Environment diagnostic log ───────────────────────────────────────────────

def log_environment_info() -> None:
    """Emit structured INFO lines about the runtime environment."""
    log.info("OS            : %s (%s)", sys.platform, os.name)
    log.info("UID           : %s (root=%s)", os.getuid() if hasattr(os, "getuid") else "N/A", _is_root())
    log.info("DISPLAY       : %s", os.environ.get("DISPLAY", "<not set>"))
    log.info("WAYLAND       : %s", os.environ.get("WAYLAND_DISPLAY", "<not set>"))
    log.info("XDG_RUNTIME   : %s (ok=%s)", os.environ.get("XDG_RUNTIME_DIR", "<not set>"), _xdg_runtime_ok())
    log.info("SSH session   : %s", _looks_like_ssh())
    log.info("Container/CI  : %s", _looks_like_container())
    log.info("xdg-open      : %s", shutil.which("xdg-open") or "<not found>")
    log.info("Browser found : %s", _browser_executable_exists())
    log.info("Browser open  : %s", can_open_browser())


# ─── Network helpers ──────────────────────────────────────────────────────────

def get_local_ip() -> str:
    """Best-effort detection of the host's LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ─── Safe URL opener ──────────────────────────────────────────────────────────

def safe_open_url(url: str) -> None:
    """
    Attempt to open *url* in the system browser.

    • Never crashes — browser failure is non-fatal.
    • Prints a friendly manual-access banner when the browser cannot be opened.
    • Does NOT call xdg-open unless can_open_browser() returns True.
    """
    if not can_open_browser():
        # Headless / SSH / container — just show the URL
        return  # banner already printed by print_startup_banner()

    try:
        opened = webbrowser.open(url)
        if not opened:
            raise RuntimeError("webbrowser.open returned False")
        log.debug("Browser opened via webbrowser module: %s", url)
    except Exception as exc:
        log.debug("webbrowser module failed (%s), trying platform fallback", exc)
        try:
            _platform_fallback(url)
        except Exception as fb_exc:
            log.debug("Platform fallback also failed: %s", fb_exc)


def _platform_fallback(url: str) -> None:
    """Last-resort, silent platform opener — never raises."""
    try:
        if sys.platform.startswith("linux") and _xdg_open_exists():
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except Exception as exc:
        log.debug("Platform fallback browser open failed: %s", exc)


# ─── Startup banner ───────────────────────────────────────────────────────────

def print_startup_banner(host: str, port: int, browser_enabled: bool) -> None:
    """
    Print a clear, human-readable startup message.

    Includes local URL, network URL (when bound to 0.0.0.0), and
    browser-open status.
    """
    local_url   = f"http://127.0.0.1:{port}"
    network_url = None

    if host == "0.0.0.0":
        lan_ip = get_local_ip()
        if lan_ip != "127.0.0.1":
            network_url = f"http://{lan_ip}:{port}"

    if browser_enabled and can_open_browser():
        browser_status = "enabled — opening automatically"
    else:
        browser_status = "disabled (headless mode)"

    print()
    print("  --------------------------------------------------")
    print("  Shadow AI Simulator started successfully")
    print(f"  Local URL    : {local_url}")
    if network_url:
        print(f"  Network URL  : {network_url}")
    print(f"  Browser      : {browser_status}")
    print()
    if not (browser_enabled and can_open_browser()):
        print("  Open your browser manually:")
        print(f"    {local_url}")
        if network_url:
            print(f"  If running in a VM or over SSH, use:")
            print(f"    {network_url}")
    print("  Ctrl+C to stop")
    print("  --------------------------------------------------")
    print()
