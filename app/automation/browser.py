"""
Playwright-based web data leakage simulation.

Launches a VISIBLE Chromium browser window so the operator can watch each
step: navigation, input discovery, and character-by-character typing of
the sensitive payload — generating real DNS, TLS, and HTTP traffic.
"""

import asyncio
from typing import Callable, Awaitable

from playwright.async_api import async_playwright, TimeoutError as PWTimeout


# Selectors tried in order to find a text input field
_INPUT_SELECTORS = [
    "textarea",
    "[contenteditable='true']",
    "[role='textbox']",
    "input[type='text']:not([type='hidden'])",
    "[placeholder]",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Typing delay per character (ms) — slow enough to watch live
_TYPE_DELAY_MS = 45

# How long to leave the browser open after typing so the operator can see
_LINGER_MS = 4_000

Emitter = Callable[..., Awaitable[None]]


async def open_site_only(target: dict, emit: Emitter) -> dict:
    """
    Open a visible browser window and navigate to target["url"].
    No data is entered. The browser stays open until the user closes it
    (or a 10-minute safety timeout elapses).
    """
    url  = target["url"]
    name = target["name"]

    await emit("INFO", "BROWSE", f"Opening {name} — no data will be entered. Close the browser when done.", url, "none")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                slow_mo=60,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--start-maximized",
                ],
            )
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=None,
            )
            page = await context.new_page()

            try:
                resp   = await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                status = resp.status if resp else "?"
                title  = await page.title()
                await emit("INFO", "BROWSE",
                           f"{name} loaded — HTTP {status} — \"{title}\" — browser is open, close it to continue.",
                           url, "none")
            except PWTimeout:
                await emit("BLOCKED", "BROWSE",
                           f"{name} — TIMEOUT: site unreachable (proxy/firewall block)", url, "none")
                await browser.close()
                return {"opened": False, "blocked": True, "target": name, "url": url}

            # Wait for the user to close the browser (up to 10 minutes)
            try:
                await browser.wait_for_event("disconnected", timeout=600_000)
            except Exception:
                pass  # timeout or already closed

            await emit("INFO", "BROWSE", f"{name} — browser closed by user.", url, "none")
            return {"opened": True, "target": name, "url": url}

    except Exception as exc:
        await emit("ERROR", "BROWSE",
                   f"Unhandled error opening {name}: {exc}", url, "none")
        return {"opened": False, "error": str(exc), "target": name, "url": url}


async def check_site_availability(target: dict, emit: Emitter) -> dict:
    """
    Open a visible browser window, navigate to target["url"], and report whether
    the site is reachable and usable — without entering any data.
    """
    url  = target["url"]
    name = target["name"]

    await emit("INFO", "CHECK", f"Checking availability of {name} → {url}", url, "none")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                slow_mo=60,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--start-maximized",
                ],
            )
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=None,
            )
            page = await context.new_page()

            # ── Navigate ──────────────────────────────────────────────────────
            try:
                resp   = await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                status = resp.status if resp else "?"
                title  = await page.title()
                await emit("INFO", "CHECK",
                           f"{name} — HTTP {status} — \"{title}\"", url, "none")
            except PWTimeout:
                await emit("BLOCKED", "CHECK",
                           f"{name} — TIMEOUT: site unreachable (proxy/firewall block)", url, "none")
                await browser.close()
                return {"reachable": False, "blocked": True, "target": name, "url": url}

            # ── Wait for JS ───────────────────────────────────────────────────
            await asyncio.sleep(2.5)

            # ── Check for input field (no typing) ────────────────────────────
            input_found = False
            for selector in _INPUT_SELECTORS:
                try:
                    elements = await page.query_selector_all(selector)
                    visible  = [el for el in elements if await el.is_visible()]
                    if visible:
                        input_found = True
                        await emit("SUCCESS", "CHECK",
                                   f"{name} — USABLE: input field found ({selector}). Site is accessible and ready for input.",
                                   url, "none")
                        break
                except Exception:
                    continue

            if not input_found:
                await emit("WARN", "CHECK",
                           f"{name} — REACHABLE but no input found — likely behind auth wall or login required.",
                           url, "none")

            await asyncio.sleep(_LINGER_MS / 1000)
            await context.close()
            await browser.close()

            return {
                "reachable":    True,
                "input_found":  input_found,
                "target":       name,
                "url":          url,
                "status":       status,
                "title":        title,
            }

    except Exception as exc:
        await emit("ERROR", "CHECK",
                   f"Unhandled error checking {name}: {exc}", url, "none")
        return {"reachable": False, "error": str(exc), "target": name, "url": url}


async def simulate_data_leakage(target: dict, emit: Emitter) -> dict:
    """
    Open a visible browser window, navigate to target["url"], highlight the
    input field, and type target["payload"] one character at a time so the
    simulation is fully observable.
    """
    url       = target["url"]
    name      = target["name"]
    payload   = target["payload"]
    data_type = target["data_type"]

    await emit("INFO", "BROWSER",
               f"Step 1/5 — Opening browser window → {url}", url, data_type)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,                        # ← visible window
                slow_mo=60,                            # small global delay so actions are watchable
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--start-maximized",               # open full-screen
                ],
            )
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=None,                         # respect --start-maximized
            )
            page = await context.new_page()

            # ── Step 1: Navigate ─────────────────────────────────────────────
            await emit("INFO", "BROWSER",
                       f"Step 2/5 — Navigating to {name}…", url, data_type)
            try:
                resp   = await page.goto(url, timeout=25_000,
                                         wait_until="domcontentloaded")
                status = resp.status if resp else "?"
                title  = await page.title()
                await emit("INFO", "BROWSER",
                           f"Step 2/5 — Page loaded — HTTP {status} — \"{title}\"",
                           url, data_type)
            except PWTimeout:
                await emit("BLOCKED", "BROWSER",
                           f"TIMEOUT loading {name} — proxy/firewall block",
                           url, data_type)
                await browser.close()
                return {"success": False, "blocked": True, "target": name}

            # ── Step 2: Wait for JS / dynamic content ────────────────────────
            await emit("INFO", "BROWSER",
                       f"Step 3/5 — Waiting for page to fully render…",
                       url, data_type)
            await asyncio.sleep(2.5)

            # ── Step 3: Find the input field ─────────────────────────────────
            typed   = False
            snippet = payload[:600]

            for selector in _INPUT_SELECTORS:
                try:
                    elements = await page.query_selector_all(selector)
                    visible  = [el for el in elements if await el.is_visible()]
                    if not visible:
                        continue

                    el = visible[0]
                    await emit("INFO", "BROWSER",
                               f"Step 4/5 — Found input ({selector}) — scrolling into view…",
                               url, data_type)

                    # Scroll the element into view and highlight it briefly
                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(0.4)

                    # Yellow flash to show where we will type
                    await page.evaluate(
                        """el => {
                            el.style.outline = '3px solid #f59e0b';
                            el.style.boxShadow = '0 0 12px #f59e0b';
                            setTimeout(() => {
                                el.style.outline = '';
                                el.style.boxShadow = '';
                            }, 800);
                        }""",
                        el,
                    )
                    await asyncio.sleep(0.9)

                    # ── Step 4: Click and type ────────────────────────────────
                    await emit("INFO", "BROWSER",
                               f"Step 5/5 — Typing {data_type} payload into {name}…",
                               url, data_type)
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.type(snippet, delay=_TYPE_DELAY_MS)
                    typed = True

                    await emit("ALERT", "BROWSER",
                               f"DATA LEAK SIMULATED: {data_type} typed into {name}",
                               url, data_type)
                    break

                except Exception:
                    continue

            if not typed:
                await emit("WARN", "BROWSER",
                           f"No accessible input on {name} — auth wall detected. "
                           f"DNS/TLS traffic still generated.",
                           url, data_type)

            # ── Step 5: Linger so operator can see the result ────────────────
            await emit("INFO", "BROWSER",
                       f"Leaving browser open for {_LINGER_MS // 1000}s — close it to continue…",
                       url, data_type)
            await asyncio.sleep(_LINGER_MS / 1000)

            await context.close()
            await browser.close()

            return {"success": True, "typed": typed, "target": name}

    except Exception as exc:
        await emit("ERROR", "BROWSER",
                   f"Unhandled error on {name}: {exc}", url, data_type)
        return {"success": False, "error": str(exc), "target": name}
