"""
Playwright-based web data leakage simulation.

Launches a browser window (headless on servers, visible on desktop sessions)
so the operator can watch each step: navigation, input discovery, and
character-by-character typing of a sensitive payload — generating real DNS,
TLS, and HTTP traffic.

All browser checks use the Playwright Async API exclusively.
sync_playwright is never imported here — doing so inside an asyncio event loop
raises "Sync API inside the asyncio loop."

Failure classifications (precise):
  PLAYWRIGHT_ASYNC_MISUSE   – sync_playwright called inside asyncio loop (config bug)
  PLAYWRIGHT_NOT_INSTALLED  – playwright python package missing
  CHROMIUM_NOT_INSTALLED    – playwright installed but chromium binary missing
  BROWSER_LAUNCH_FAILED     – chromium present but failed to start
  PAGE_TIMEOUT              – page load timed out (proxy/firewall)
  BLOCKED_BY_PROXY          – connection refused or proxy error
  TRAFFIC_GENERATED         – page loaded, DNS+TLS traffic generated
  SUCCESS_LEAK_SIMULATED    – payload successfully typed into input field
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Callable, Awaitable

# Async API only — never import sync_playwright here
from playwright.async_api import async_playwright, TimeoutError as PWTimeout


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

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

_TYPE_DELAY_MS = 45    # ms per character
_LINGER_MS     = 4_000 # ms to keep browser visible after typing

Emitter = Callable[..., Awaitable[None]]


# ─────────────────────────────────────────────────────────────────────────────
# Playwright error classifier
# ─────────────────────────────────────────────────────────────────────────────

def _classify_playwright_error(exc_msg: str) -> str:
    """
    Map a Playwright exception message to a precise classification string.

    This prevents sync/async misuse from being misreported as CHROMIUM_NOT_INSTALLED.
    """
    msg = exc_msg.lower()
    if "sync api inside the asyncio" in msg or "using playwright sync" in msg:
        return "PLAYWRIGHT_ASYNC_MISUSE"
    if "no module named" in msg and "playwright" in msg:
        return "PLAYWRIGHT_NOT_INSTALLED"
    if (
        "executable doesn't exist" in msg
        or "run playwright install" in msg
        or "chromium" in msg and ("not found" in msg or "missing" in msg)
    ):
        return "CHROMIUM_NOT_INSTALLED"
    return "BROWSER_LAUNCH_FAILED"


# ─────────────────────────────────────────────────────────────────────────────
# Environment detection
# ─────────────────────────────────────────────────────────────────────────────

def _is_headless_env() -> bool:
    """
    Return True when running in a headless or server environment where a
    visible browser window cannot be displayed.
    """
    if sys.platform == "win32":
        return False

    if sys.platform == "darwin":
        return bool(os.environ.get("SSH_CLIENT") or os.environ.get("CI"))

    # Linux — require an explicit display
    has_display = bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )
    is_ssh = bool(
        os.environ.get("SSH_CLIENT") or
        os.environ.get("SSH_TTY") or
        os.environ.get("SSH_CONNECTION")
    )
    is_ci = bool(os.environ.get("CI") or os.environ.get("DOCKER"))

    return (not has_display) or is_ssh or is_ci


def _use_headless() -> bool:
    return _is_headless_env()


# ─────────────────────────────────────────────────────────────────────────────
# Async Chromium preflight check
# ─────────────────────────────────────────────────────────────────────────────

async def check_chromium_available() -> tuple[bool, str, str]:
    """
    Async preflight: verify the Playwright-managed Chromium binary exists.

    Uses async_playwright — safe to call from inside an asyncio event loop.
    Never imports sync_playwright.

    Returns:
      (available: bool, path_or_message: str, classification: str)

    Classifications on failure:
      PLAYWRIGHT_ASYNC_MISUSE   – wrong API called in async context
      PLAYWRIGHT_NOT_INSTALLED  – package missing
      CHROMIUM_NOT_INSTALLED    – binary missing
      BROWSER_LAUNCH_FAILED     – other error
    """
    try:
        async with async_playwright() as p:
            path = p.chromium.executable_path
            if Path(path).exists():
                return True, path, "CHROMIUM_INSTALLED"
            return False, f"Binary not found at: {path}", "CHROMIUM_NOT_INSTALLED"
    except Exception as exc:
        classification = _classify_playwright_error(str(exc))
        return False, f"Playwright error: {exc}", classification


# ─────────────────────────────────────────────────────────────────────────────
# Centralised browser launch helpers
# ─────────────────────────────────────────────────────────────────────────────

def _launch_args(headless: bool) -> list[str]:
    args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args.append("--disable-software-rasterizer")
    else:
        args.append("--start-maximized")
    return args


async def _open_browser(playwright, headless: bool):
    """Launch a Chromium browser with stable, deterministic settings."""
    return await playwright.chromium.launch(
        headless=headless,
        slow_mo=0 if headless else 60,
        args=_launch_args(headless),
        timeout=30_000,
    )


async def _new_context(browser, headless: bool):
    """Create a fresh isolated browser context (clean profile, no shared state)."""
    kwargs: dict = {
        "user_agent": _USER_AGENT,
        "ignore_https_errors": True,
    }
    if not headless:
        kwargs["viewport"] = None
    return await browser.new_context(**kwargs)


def _make_result(
    *,
    browser_ready: bool = False,
    request_attempted: bool = False,
    response_received: bool = False,
    classification: str,
    error_summary: str = "",
    telemetry_generated: bool = False,
    target: str = "",
    url: str = "",
    **extra,
) -> dict:
    """Build a standardised per-target result dict."""
    return {
        "browser_ready":       browser_ready,
        "request_attempted":   request_attempted,
        "response_received":   response_received,
        "classification":      classification,
        "error_summary":       error_summary,
        "telemetry_generated": telemetry_generated,
        "target":              target,
        "url":                 url,
        **extra,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def open_site_only(target: dict, emit: Emitter) -> dict:
    """
    Open a browser window and navigate to target["url"].
    No data is entered. Waits until the user closes it (10-minute safety cap).
    """
    url  = target["url"]
    name = target["name"]

    chromium_ok, chromium_info, chromium_cls = await check_chromium_available()
    if not chromium_ok:
        remediation = (
            "Run: python -m playwright install chromium"
            if chromium_cls in ("CHROMIUM_NOT_INSTALLED", "PLAYWRIGHT_NOT_INSTALLED")
            else "Check setup — possible sync/async API misuse in preflight code"
        )
        await emit("WARN", "BROWSE",
                   f"{name}: browser unavailable — {chromium_info}. "
                   f"Classification: {chromium_cls}. Remediation: {remediation}",
                   url, "none", classification=chromium_cls)
        return _make_result(classification=chromium_cls, error_summary=chromium_info,
                            target=name, url=url, remediation=remediation)

    headless = _use_headless()
    await emit("INFO", "BROWSE",
               f"Opening {name} — {'headless' if headless else 'visible'} mode",
               url, "none")

    try:
        async with async_playwright() as p:
            try:
                browser = await _open_browser(p, headless)
            except Exception as exc:
                cls = _classify_playwright_error(str(exc))
                await emit("WARN", "BROWSE",
                           f"{name}: browser launch failed — {exc}. Classification: {cls}",
                           url, "none", classification=cls)
                return _make_result(classification=cls, error_summary=str(exc),
                                    target=name, url=url)

            context = await _new_context(browser, headless)
            page    = await context.new_page()

            try:
                resp   = await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                status = resp.status if resp else "?"
                title  = await page.title()
                await emit("INFO", "BROWSE",
                           f"{name} loaded — HTTP {status} — \"{title}\" — browser is open",
                           url, "none", classification="TRAFFIC_GENERATED", status_code=status)
            except PWTimeout:
                await emit("BLOCKED", "BROWSE",
                           f"{name} — TIMEOUT: site unreachable. Classification: PAGE_TIMEOUT",
                           url, "none", classification="PAGE_TIMEOUT")
                await browser.close()
                return _make_result(classification="PAGE_TIMEOUT", target=name, url=url,
                                    request_attempted=True, browser_ready=True)

            try:
                await browser.wait_for_event("disconnected", timeout=600_000)
            except Exception:
                pass

            await emit("INFO", "BROWSE", f"{name} — browser closed.", url, "none")
            return _make_result(classification="TRAFFIC_GENERATED", target=name, url=url,
                                browser_ready=True, request_attempted=True,
                                response_received=True, telemetry_generated=True,
                                opened=True)

    except Exception as exc:
        cls = _classify_playwright_error(str(exc))
        await emit("ERROR", "BROWSE",
                   f"Unhandled error opening {name}: {exc}. Classification: {cls}",
                   url, "none", classification=cls)
        return _make_result(classification=cls, error_summary=str(exc), target=name, url=url)


async def check_site_availability(target: dict, emit: Emitter) -> dict:
    """
    Navigate to target["url"] and report reachability — no data entered.
    Uses a fresh isolated browser context per call.
    """
    url  = target["url"]
    name = target["name"]

    chromium_ok, chromium_info, chromium_cls = await check_chromium_available()
    if not chromium_ok:
        await emit("WARN", "CHECK",
                   f"{name}: browser unavailable — {chromium_info}. Classification: {chromium_cls}",
                   url, "none", classification=chromium_cls)
        return _make_result(classification=chromium_cls, error_summary=chromium_info,
                            target=name, url=url, reachable=False)

    await emit("INFO", "CHECK", f"Checking availability of {name} → {url}", url, "none")
    headless = _use_headless()

    try:
        async with async_playwright() as p:
            try:
                browser = await _open_browser(p, headless)
            except Exception as exc:
                cls = _classify_playwright_error(str(exc))
                await emit("WARN", "CHECK",
                           f"{name}: browser launch failed — {exc}. Classification: {cls}",
                           url, "none", classification=cls)
                return _make_result(classification=cls, error_summary=str(exc),
                                    target=name, url=url, reachable=False)

            context = await _new_context(browser, headless)
            page    = await context.new_page()

            status: str | int = "?"
            title  = ""
            try:
                resp   = await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                status = resp.status if resp else "?"
                title  = await page.title()
                await emit("INFO", "CHECK",
                           f"{name} — HTTP {status} — \"{title}\"", url, "none",
                           classification="TRAFFIC_GENERATED")
            except PWTimeout:
                await emit("BLOCKED", "CHECK",
                           f"{name} — TIMEOUT: unreachable. Classification: PAGE_TIMEOUT",
                           url, "none", classification="PAGE_TIMEOUT")
                await browser.close()
                return _make_result(classification="PAGE_TIMEOUT", target=name, url=url,
                                    browser_ready=True, request_attempted=True,
                                    reachable=False, blocked=True)

            await asyncio.sleep(2.5)

            input_found = False
            for selector in _INPUT_SELECTORS:
                try:
                    elements = await page.query_selector_all(selector)
                    visible  = [el for el in elements if await el.is_visible()]
                    if visible:
                        input_found = True
                        await emit("SUCCESS", "CHECK",
                                   f"{name} — USABLE: input found ({selector}).",
                                   url, "none", classification="TRAFFIC_GENERATED")
                        break
                except Exception:
                    continue

            if not input_found:
                await emit("WARN", "CHECK",
                           f"{name} — REACHABLE but no input — likely behind auth wall.",
                           url, "none", classification="TRAFFIC_GENERATED")

            await asyncio.sleep(_LINGER_MS / 1000)
            await context.close()
            await browser.close()

            return _make_result(
                classification="TRAFFIC_GENERATED",
                target=name, url=url,
                browser_ready=True, request_attempted=True,
                response_received=True, telemetry_generated=True,
                reachable=True, input_found=input_found,
                status=status, title=title,
            )

    except Exception as exc:
        cls = _classify_playwright_error(str(exc))
        await emit("ERROR", "CHECK",
                   f"Unhandled error checking {name}: {exc}. Classification: {cls}",
                   url, "none", classification=cls)
        return _make_result(classification=cls, error_summary=str(exc),
                            target=name, url=url, reachable=False)


async def simulate_data_leakage(target: dict, emit: Emitter) -> dict:
    """
    Open a browser, navigate to target["url"], find an input field, and type
    target["payload"] character-by-character — generating real DNS/TLS/HTTP traffic.

    Each call uses a fresh isolated browser context (clean profile, no shared cookies).
    """
    url       = target["url"]
    name      = target["name"]
    payload   = target["payload"]
    data_type = target["data_type"]

    chromium_ok, chromium_info, chromium_cls = await check_chromium_available()
    if not chromium_ok:
        remediation = (
            "Run: python -m playwright install chromium"
            if chromium_cls in ("CHROMIUM_NOT_INSTALLED", "PLAYWRIGHT_NOT_INSTALLED")
            else "Check dep_bootstrap.py — sync_playwright called inside asyncio loop"
        )
        await emit("WARN", "BROWSER",
                   f"{name}: browser unavailable — {chromium_info}. "
                   f"Classification: {chromium_cls}. Remediation: {remediation}",
                   url, data_type, classification=chromium_cls)
        return _make_result(
            classification=chromium_cls, error_summary=chromium_info,
            target=name, url=url, success=False, remediation=remediation,
        )

    headless = _use_headless()
    await emit("INFO", "BROWSER",
               f"Step 1/5 — Opening {'headless' if headless else 'visible'} browser → {url}",
               url, data_type)

    try:
        async with async_playwright() as p:
            try:
                browser = await _open_browser(p, headless)
            except Exception as exc:
                cls = _classify_playwright_error(str(exc))
                await emit("WARN", "BROWSER",
                           f"Step 1/5 — {name}: browser launch failed — {exc}. Classification: {cls}",
                           url, data_type, classification=cls)
                return _make_result(classification=cls, error_summary=str(exc),
                                    target=name, url=url, success=False)

            context = await _new_context(browser, headless)
            page    = await context.new_page()

            await emit("INFO", "BROWSER",
                       f"Step 2/5 — Navigating to {name}…", url, data_type)
            try:
                resp   = await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                status = resp.status if resp else "?"
                title  = await page.title()
                await emit("INFO", "BROWSER",
                           f"Step 2/5 — Page loaded — HTTP {status} — \"{title}\"",
                           url, data_type,
                           classification="TRAFFIC_GENERATED", status_code=status)
            except PWTimeout:
                await emit("BLOCKED", "BROWSER",
                           f"TIMEOUT loading {name} — proxy/firewall block. Classification: PAGE_TIMEOUT",
                           url, data_type, classification="PAGE_TIMEOUT")
                await browser.close()
                return _make_result(
                    classification="PAGE_TIMEOUT", target=name, url=url,
                    browser_ready=True, request_attempted=True, success=False, blocked=True,
                )

            await emit("INFO", "BROWSER",
                       f"Step 3/5 — Waiting for page to fully render…", url, data_type)
            await asyncio.sleep(2.5)

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

                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(0.4)

                    if not headless:
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

                    await emit("INFO", "BROWSER",
                               f"Step 5/5 — Typing {data_type} payload into {name}…",
                               url, data_type)
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.type(snippet, delay=_TYPE_DELAY_MS)
                    typed = True

                    await emit("ALERT", "BROWSER",
                               f"DATA LEAK SIMULATED: {data_type} typed into {name}. "
                               f"Classification: SUCCESS_LEAK_SIMULATED",
                               url, data_type, classification="SUCCESS_LEAK_SIMULATED")
                    break

                except Exception:
                    continue

            if not typed:
                await emit("WARN", "BROWSER",
                           f"No accessible input on {name} — auth wall detected. "
                           f"DNS/TLS traffic still generated. Classification: TRAFFIC_GENERATED",
                           url, data_type, classification="TRAFFIC_GENERATED")

            if not headless:
                await emit("INFO", "BROWSER",
                           f"Leaving browser open for {_LINGER_MS // 1000}s…",
                           url, data_type)
                await asyncio.sleep(_LINGER_MS / 1000)

            await context.close()
            await browser.close()

            classification = "SUCCESS_LEAK_SIMULATED" if typed else "TRAFFIC_GENERATED"
            return _make_result(
                classification=classification, target=name, url=url,
                browser_ready=True, request_attempted=True,
                response_received=True, telemetry_generated=True,
                success=True, typed=typed,
            )

    except Exception as exc:
        cls = _classify_playwright_error(str(exc))
        await emit("ERROR", "BROWSER",
                   f"Unhandled error on {name}: {exc}. Classification: {cls}",
                   url, data_type, classification=cls)
        return _make_result(classification=cls, error_summary=str(exc),
                            target=name, url=url, success=False)
