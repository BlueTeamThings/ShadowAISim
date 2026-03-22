"""Entry point — starts uvicorn and opens the browser."""

import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8766
URL  = f"http://{HOST}:{PORT}"


def _wait_and_open():
    """Poll until the server responds, then open the browser."""
    for _ in range(40):          # wait up to 20 s (40 × 0.5 s)
        try:
            urllib.request.urlopen(URL, timeout=1)
            break                # server is up
        except Exception:
            time.sleep(0.5)

    # Try webbrowser module first, then platform-specific fallbacks
    opened = webbrowser.open(URL)
    if not opened:
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", URL],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", URL])
            elif sys.platform == "win32":
                subprocess.Popen(["start", URL], shell=True)
        except Exception:
            pass


if __name__ == "__main__":
    print()
    print("  ╔══════════════════════════════════╗")
    print("  ║     Shadow AI Simulator          ║")
    print(f"  ║     {URL:<28}║")
    print("  ║     Ctrl+C to stop               ║")
    print("  ╚══════════════════════════════════╝")
    print()
    threading.Thread(target=_wait_and_open, daemon=True).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")
