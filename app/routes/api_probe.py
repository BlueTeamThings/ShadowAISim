"""Routes for direct AI API endpoint probing."""

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.config import API_TARGETS
from app.core.event_bus import bus
from app.automation.api_calls import probe_api_endpoint

router = APIRouter()


@router.get("/api/probe/targets")
async def list_targets():
    return [{"id": t["id"], "name": t["name"], "url": t["url"], "data_type": t["data_type"]}
            for t in API_TARGETS]


@router.post("/api/probe/{target_id}")
async def probe_single(target_id: str, background_tasks: BackgroundTasks):
    target = next((t for t in API_TARGETS if t["id"] == target_id), None)
    if not target:
        return JSONResponse({"error": "Unknown target"}, status_code=404)
    background_tasks.add_task(_probe, target)
    return {"started": True, "id": target_id}


@router.post("/api/probe/all")
async def probe_all(background_tasks: BackgroundTasks):
    background_tasks.add_task(_probe_all)
    return {"started": True, "count": len(API_TARGETS)}


async def _probe(target: dict):
    await probe_api_endpoint(target, bus.emit)


async def _probe_all():
    await bus.emit("INFO", "API_PROBE", f"Starting all {len(API_TARGETS)} API endpoint probes")
    for target in API_TARGETS:
        await probe_api_endpoint(target, bus.emit)
    await bus.emit("INFO", "API_PROBE", "All API probes complete")
