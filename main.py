"""
main.py — Entry point for Shadow AI Simulator.

Usage
-----
  python main.py                          # defaults: headless-safe
  python main.py --open-browser           # try to open browser if GUI available
  python main.py --no-browser             # never open browser
  python main.py --host 0.0.0.0           # bind all interfaces
  python main.py --host 127.0.0.1 --port 9000
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import urllib.request

import uvicorn

from app.core.launcher import (
    can_open_browser,
    log_environment_info,
    print_startup_banner,
    safe_open_url,
)

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(name)s: %(message)s",
)
log = logging.getLogger("shadow_ai.main")


# ─── CLI arguments ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Shadow AI Simulator — headless-safe launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--host",
        default=None,
        help=(
            "Bind address. "
            "Defaults to 0.0.0.0 on Linux (reachable from host/VM) "
            "and 127.0.0.1 on Windows/macOS."
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=8766,
        help="TCP port (default: 8766).",
    )

    browser_group = p.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--open-browser",
        action="store_true",
        default=False,
        help=(
            "Attempt to open the browser after startup. "
            "On Linux this only succeeds when a GUI session is detected."
        ),
    )
    browser_group.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="Never open the browser (overrides --open-browser).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging (includes environment detection details).",
    )
    return p.parse_args()


# ─── Browser-open thread ─────────────────────────────────────────────────────

def _wait_then_open(url: str, timeout_secs: float = 20.0) -> None:
    """Poll until the server responds, then call safe_open_url()."""
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    safe_open_url(url)


# ─── Default host selection ───────────────────────────────────────────────────

def _default_host() -> str:
    """
    Choose a sensible default bind address.
    • Linux: 0.0.0.0 — reachable from host/VM over the network.
    • Windows / macOS desktop: 127.0.0.1 — local only.
    """
    if sys.platform.startswith("linux"):
        return "0.0.0.0"
    return "127.0.0.1"


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("shadow_ai").setLevel(logging.DEBUG)

    # Resolve host
    host = args.host or _default_host()
    port = args.port
    local_url = f"http://127.0.0.1:{port}"

    # Resolve browser intent
    # --no-browser  → never open
    # --open-browser → open if GUI available
    # (neither flag)  → Windows auto-opens; Linux does not
    if args.no_browser:
        browser_enabled = False
    elif args.open_browser:
        browser_enabled = True
    else:
        # Platform default
        browser_enabled = sys.platform == "win32"

    if args.verbose:
        log_environment_info()

    print_startup_banner(host, port, browser_enabled)

    # Start browser-open thread only when appropriate
    if browser_enabled and can_open_browser():
        threading.Thread(
            target=_wait_then_open,
            args=(local_url,),
            daemon=True,
        ).start()

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
