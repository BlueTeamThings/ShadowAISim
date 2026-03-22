"""Routes for browser-based web data leakage simulation."""

import asyncio

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.config import BROWSER_TARGETS
from app.core.event_bus import bus
from app.automation.browser import simulate_data_leakage, check_site_availability, open_site_only

router = APIRouter()


@router.get("/api/web-leakage/targets")
async def list_targets():
    return [{"id": t["id"], "name": t["name"], "url": t["url"], "data_type": t["data_type"]}
            for t in BROWSER_TARGETS]


@router.post("/api/web-leakage/{target_id}")
async def run_single(target_id: str, background_tasks: BackgroundTasks):
    target = next((t for t in BROWSER_TARGETS if t["id"] == target_id), None)
    if not target:
        return JSONResponse({"error": "Unknown target"}, status_code=404)
    background_tasks.add_task(_simulate, target)
    return {"started": True, "id": target_id, "name": target["name"]}


@router.post("/api/web-leakage/all")
async def run_all(background_tasks: BackgroundTasks):
    background_tasks.add_task(_simulate_all)
    return {"started": True, "count": len(BROWSER_TARGETS)}


@router.post("/api/web-leakage/open/{target_id}")
async def open_single(target_id: str, background_tasks: BackgroundTasks):
    target = next((t for t in BROWSER_TARGETS if t["id"] == target_id), None)
    if not target:
        return JSONResponse({"error": "Unknown target"}, status_code=404)
    background_tasks.add_task(_open, target)
    return {"started": True, "id": target_id, "name": target["name"]}


@router.post("/api/web-leakage/open-all")
async def open_all_sites(background_tasks: BackgroundTasks):
    background_tasks.add_task(_open_all)
    return {"started": True, "count": len(BROWSER_TARGETS)}


@router.post("/api/web-leakage/check/{target_id}")
async def check_single(target_id: str, background_tasks: BackgroundTasks):
    target = next((t for t in BROWSER_TARGETS if t["id"] == target_id), None)
    if not target:
        return JSONResponse({"error": "Unknown target"}, status_code=404)
    background_tasks.add_task(_check, target)
    return {"started": True, "id": target_id, "name": target["name"]}


@router.post("/api/web-leakage/check-all")
async def check_all(background_tasks: BackgroundTasks):
    background_tasks.add_task(_check_all)
    return {"started": True, "count": len(BROWSER_TARGETS)}


async def _simulate(target: dict):
    await simulate_data_leakage(target, bus.emit)


async def _simulate_all():
    await bus.emit("INFO", "BROWSER", f"Starting all {len(BROWSER_TARGETS)} browser simulations")
    for target in BROWSER_TARGETS:
        await simulate_data_leakage(target, bus.emit)
    await bus.emit("INFO", "BROWSER", "All browser simulations complete")


async def _open(target: dict):
    await open_site_only(target, bus.emit)


async def _open_all():
    await bus.emit("INFO", "BROWSE", f"Opening all {len(BROWSER_TARGETS)} sites — no data will be entered")
    for target in BROWSER_TARGETS:
        await open_site_only(target, bus.emit)
    await bus.emit("INFO", "BROWSE", "All browse-only sessions complete")


async def _check(target: dict):
    await check_site_availability(target, bus.emit)


async def _check_all():
    await bus.emit("INFO", "CHECK", f"Starting availability check for all {len(BROWSER_TARGETS)} sites")
    for target in BROWSER_TARGETS:
        await check_site_availability(target, bus.emit)
    await bus.emit("INFO", "CHECK", "Availability check complete for all sites")
