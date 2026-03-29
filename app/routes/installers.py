"""Routes for AI application installer + launcher operations."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.automation.installers import (
    STATUS,
    install_app,
    install_group,
    preflight_install_state,
    resolve_download_url,
    validate_install,
)
from app.automation.launcher import (
    get_app_logs,
    get_process_info,
    ollama_service_action,
    start_app,
    stop_app,
)
from app.core.app_catalog import apps_for_category, get_app
from app.core.event_bus import bus

router = APIRouter()

_LAST_RESULTS: dict[str, dict] = {}


def _grouped() -> dict[str, list[dict]]:
    return {
        "local_ai": apps_for_category("local_ai"),
        "browsers": apps_for_category("browsers"),
        "productivity": apps_for_category("productivity"),
    }


async def _app_status(app: dict, include_resolution: bool = True) -> dict:
    app_id = app["app_id"]
    pre = await preflight_install_state(app)
    proc = get_process_info(app_id)
    last = _LAST_RESULTS.get(app_id, {})

    resolved = {}
    if include_resolution:
        resolved = await resolve_download_url(app)

    validation = await validate_install(app)
    launch_cmd = app.get("launch_command_linux") if "linux" in app.get("supported_platforms", []) else []
    launch_defined = bool(launch_cmd) or app.get("launch_type") == "service"
    start_enabled = bool(pre.get("installed") and validation.get("ok") and launch_defined)
    if not pre.get("installed"):
        start_reason = "Install first"
    elif not validation.get("ok"):
        start_reason = validation.get("reason", "Post-install validation failed")
    elif not launch_defined:
        start_reason = "No launch command for this platform"
    else:
        start_reason = ""

    install_status = last.get("classification")
    if not install_status:
        install_status = STATUS["ALREADY_INSTALLED"] if pre.get("installed") else "NOT_INSTALLED"

    return {
        "app_id": app_id,
        "display_name": app.get("display_name"),
        "desc": app.get("desc", ""),
        "category": app.get("category"),
        "supported_platforms": app.get("supported_platforms", []),
        "install_type": app.get("install_type"),
        "homepage_url": app.get("homepage_url"),
        "latest_resolved_download_url": resolved.get("resolved_url", last.get("resolved_url", "")),
        "fallback_url_used": resolved.get("fallback_used", last.get("fallback_url_used")),
        "http_status": resolved.get("http_status", last.get("http_status")),
        "classification": install_status,
        "installed": pre.get("installed", False),
        "installed_path": last.get("installed_path", ""),
        "binary_path": pre.get("binary_path", last.get("binary_path", "")),
        "version": pre.get("version", last.get("version", "")),
        "running": proc.get("running", False),
        "process": proc.get("process"),
        "start_enabled": start_enabled,
        "start_disabled_reason": start_reason,
        "start_visible": bool(pre.get("installed") or app.get("launch_strategy") not in (None, "manual")),
        "launch_strategy": app.get("launch_strategy"),
        "validation_strategy": app.get("validation_strategy"),
        "validation_passed": validation.get("ok", False),
        "validation_classification": validation.get("classification"),
        "validation_reason": validation.get("reason", ""),
        "known_limitations": app.get("known_limitations"),
        "requires_service": app.get("requires_service", False),
    }


@router.get("/api/installers")
async def list_installers():
    grouped = _grouped()

    result = {}
    for group_name, apps in grouped.items():
        cards = []
        for app in apps:
            cards.append(await _app_status(app))
        result[group_name] = cards

    return {
        "groups": result,
        "classifications": STATUS,
    }


@router.post("/api/installers/{installer_id}")
async def run_single(installer_id: str, background_tasks: BackgroundTasks):
    app = get_app(installer_id)
    if not app:
        return JSONResponse({"error": "Unknown installer"}, status_code=404)
    background_tasks.add_task(_install_and_track, app, False)
    return {"started": True, "id": installer_id, "name": app["display_name"]}


@router.post("/api/installers/{installer_id}/reinstall")
async def run_single_reinstall(installer_id: str, background_tasks: BackgroundTasks):
    app = get_app(installer_id)
    if not app:
        return JSONResponse({"error": "Unknown installer"}, status_code=404)
    background_tasks.add_task(_install_and_track, app, True)
    return {"started": True, "id": installer_id, "name": app["display_name"], "reinstall": True}


@router.post("/api/installers/group/{group_id}")
async def run_group(group_id: str, background_tasks: BackgroundTasks):
    grouped = _grouped()
    aliases = {
        "local-ai": "local_ai",
        "local_ai": "local_ai",
        "browsers": "browsers",
        "productivity": "productivity",
    }
    group_id = aliases.get(group_id, group_id)
    if group_id not in grouped:
        return JSONResponse({"error": "Unknown group"}, status_code=404)
    apps = grouped[group_id]
    background_tasks.add_task(_install_group_and_track, apps, group_id)
    return {"started": True, "group": group_id, "count": len(apps)}


@router.post("/api/installers/{installer_id}/start")
async def start_installed_app(installer_id: str):
    app = get_app(installer_id)
    if not app:
        return JSONResponse({"error": "Unknown installer"}, status_code=404)
    result = await start_app(app, bus.emit)
    _LAST_RESULTS[installer_id] = {**_LAST_RESULTS.get(installer_id, {}), **result}
    return result


@router.post("/api/installers/{installer_id}/stop")
async def stop_installed_app(installer_id: str):
    result = await stop_app(installer_id, bus.emit)
    return result


@router.post("/api/installers/{installer_id}/validate")
async def validate_installed_app(installer_id: str):
    app = get_app(installer_id)
    if not app:
        return JSONResponse({"error": "Unknown installer"}, status_code=404)
    result = await validate_install(app)
    return {
        "app_id": installer_id,
        "validated": result.get("ok", False),
        "classification": result.get("classification"),
        "binary_path": result.get("binary_path", ""),
        "version": result.get("version", ""),
    }


@router.get("/api/installers/{installer_id}/logs")
async def app_logs(installer_id: str):
    return {
        "app_id": installer_id,
        "logs": get_app_logs(installer_id),
    }


@router.get("/api/installers/{installer_id}/binary-path")
async def binary_path(installer_id: str):
    app = get_app(installer_id)
    if not app:
        return JSONResponse({"error": "Unknown installer"}, status_code=404)
    pre = await preflight_install_state(app)
    return {"app_id": installer_id, "binary_path": pre.get("binary_path", "")}


@router.get("/api/installers/{installer_id}/install-folder")
async def install_folder(installer_id: str):
    state = _LAST_RESULTS.get(installer_id, {})
    return {"app_id": installer_id, "install_folder": state.get("installed_path", "")}


@router.post("/api/installers/ollama/service/{action}")
async def ollama_service(action: str):
    out = await ollama_service_action(action, bus.emit)
    return {"app_id": "ollama", "action": action, **out}


@router.post("/api/installers/ollama/health")
async def ollama_health():
    out = await ollama_service_action("health", bus.emit)
    return {"app_id": "ollama", **out}


@router.post("/api/installers/ollama/pull-baseline-model")
async def ollama_pull_baseline():
    out = await ollama_service_action("pull-baseline-model", bus.emit)
    return {"app_id": "ollama", **out}


async def _install_and_track(app: dict, reinstall: bool):
    result = await install_app(app, bus.emit, reinstall=reinstall)
    _LAST_RESULTS[app["app_id"]] = result


async def _install_group_and_track(apps: list[dict], label: str):
    results = await install_group(apps, bus.emit, label=label)
    for item in results:
        _LAST_RESULTS[item["app_id"]] = item
