"""Routes for AI application installer download simulation."""

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.config import (
    INSTALLERS_LOCAL_AI, INSTALLERS_BROWSERS, INSTALLERS_PRODUCTIVITY, ALL_INSTALLERS,
)
from app.core.event_bus import bus
from app.automation.installers import install_app

router = APIRouter()


@router.get("/api/installers")
async def list_installers():
    return {
        "local_ai":    INSTALLERS_LOCAL_AI,
        "browsers":    INSTALLERS_BROWSERS,
        "productivity": INSTALLERS_PRODUCTIVITY,
    }


@router.post("/api/installers/{installer_id}")
async def run_single(installer_id: str, background_tasks: BackgroundTasks):
    installer = next((i for i in ALL_INSTALLERS if i["id"] == installer_id), None)
    if not installer:
        return JSONResponse({"error": "Unknown installer"}, status_code=404)
    background_tasks.add_task(_install, installer)
    return {"started": True, "id": installer_id, "name": installer["name"]}


@router.post("/api/installers/group/local-ai")
async def run_group_local_ai(background_tasks: BackgroundTasks):
    background_tasks.add_task(_install_group, INSTALLERS_LOCAL_AI, "Local AI Models")
    return {"started": True, "count": len(INSTALLERS_LOCAL_AI)}


@router.post("/api/installers/group/browsers")
async def run_group_browsers(background_tasks: BackgroundTasks):
    background_tasks.add_task(_install_group, INSTALLERS_BROWSERS, "AI Browsers")
    return {"started": True, "count": len(INSTALLERS_BROWSERS)}


@router.post("/api/installers/group/productivity")
async def run_group_productivity(background_tasks: BackgroundTasks):
    background_tasks.add_task(_install_group, INSTALLERS_PRODUCTIVITY, "AI Productivity Tools")
    return {"started": True, "count": len(INSTALLERS_PRODUCTIVITY)}


async def _install(installer: dict):
    await install_app(installer, bus.emit)


async def _install_group(group: list, label: str):
    await bus.emit("INFO", "INSTALLER", f"Installing {label} group ({len(group)} apps)…")
    for installer in group:
        await install_app(installer, bus.emit)
    await bus.emit("INFO", "INSTALLER", f"{label} group install complete")
