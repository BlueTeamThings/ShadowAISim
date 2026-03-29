"""
app/routes/preflight.py
────────────────────────
REST endpoints for dependency preflight checks and repair actions.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.dep_bootstrap import (
    run_preflight_check,
    ensure_system_dependencies,
    ensure_node_toolchain,
    ensure_playwright_browsers,
)
from app.core.event_bus import bus

router = APIRouter(prefix="/api/preflight", tags=["preflight"])


@router.get("/check")
async def get_preflight_check():
    """Run a synchronous preflight dependency check and return results."""
    results = run_preflight_check()
    return JSONResponse(content=results)


@router.post("/repair")
async def repair_dependencies(background_tasks: BackgroundTasks):
    """Trigger a full dependency repair in the background."""
    background_tasks.add_task(_run_repair)
    return {"status": "started", "message": "Dependency repair started — watch the terminal"}


@router.post("/install-browsers")
async def install_browsers(background_tasks: BackgroundTasks):
    """Install Playwright Chromium browser binaries."""
    background_tasks.add_task(_run_install_browsers)
    return {"status": "started", "message": "Browser installation started — watch the terminal"}


@router.post("/install-node")
async def install_node(background_tasks: BackgroundTasks):
    """Install Node.js / npm / npx on Linux."""
    background_tasks.add_task(_run_install_node)
    return {"status": "started", "message": "Node.js install started — watch the terminal"}


# ── Background tasks ──────────────────────────────────────────────────────────

async def _run_repair():
    await bus.emit("INFO", "PREFLIGHT", "=== Starting Dependency Repair ===", "", "")
    await ensure_system_dependencies(bus.emit)
    await bus.emit("SUCCESS", "PREFLIGHT", "=== Dependency Repair Complete ===", "", "")


async def _run_install_browsers():
    await bus.emit("INFO", "PREFLIGHT", "Installing Playwright Chromium…", "", "")
    result = await ensure_playwright_browsers(bus.emit)
    level = "SUCCESS" if result in ("ok", "installed") else "WARN"
    await bus.emit(level, "PREFLIGHT", f"Browser install result: {result}", "", "")


async def _run_install_node():
    await bus.emit("INFO", "PREFLIGHT", "Installing Node.js toolchain…", "", "")
    ok = await ensure_node_toolchain(bus.emit)
    level = "SUCCESS" if ok else "WARN"
    await bus.emit(level, "PREFLIGHT",
                   "Node.js toolchain ready" if ok else "Node.js install failed — manual install required",
                   "", "")
