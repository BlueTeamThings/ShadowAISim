"""API routes for Scenario Library and Scenario Builder operations."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body
from fastapi.responses import JSONResponse

from app.automation.scenario_runner import runner, store
from app.core.scenario_store import ScenarioValidationError

router = APIRouter()


@router.get("/api/scenarios/meta")
async def scenarios_meta():
    return store.metadata()


@router.get("/api/scenarios")
async def scenarios_list(
    platform: str | None = None,
    auth_required: bool | None = None,
    mode: str | None = None,
):
    items = store.list_scenarios(platform=platform, auth_required=auth_required, mode=mode)
    return {"items": items, "count": len(items)}


@router.get("/api/scenarios/tree")
async def scenarios_tree(
    platform: str | None = None,
    auth_required: bool | None = None,
    mode: str | None = None,
):
    return {
        "items": store.build_tree(platform=platform, auth_required=auth_required, mode=mode),
    }


@router.get("/api/scenarios/runs")
async def scenarios_runs(limit: int = 30):
    return {"items": store.list_run_history(limit=max(1, min(limit, 200)))}


@router.get("/api/scenarios/run/status")
async def scenarios_run_status():
    return runner.status()


@router.get("/api/scenarios/queue")
async def scenarios_queue():
    return {
        "items": runner.queued_items(),
        "count": len(runner.queued_items()),
    }


@router.post("/api/scenarios")
async def scenario_create(payload: dict = Body(...)):
    try:
        created = store.create_scenario(payload)
    except ScenarioValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return created


@router.post("/api/scenarios/import")
async def scenario_import(payload: dict = Body(...)):
    mode = str(payload.get("mode", "merge")).strip().lower()
    if mode not in {"merge", "replace"}:
        return JSONResponse({"error": "mode must be merge or replace"}, status_code=400)

    try:
        out = store.import_scenarios(payload, mode=mode)
    except ScenarioValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return out


@router.get("/api/scenarios/export")
async def scenario_export():
    return store.export_scenarios()


@router.post("/api/scenarios/{scenario_id}/duplicate")
async def scenario_duplicate(scenario_id: str):
    try:
        cloned = store.duplicate_scenario(scenario_id)
    except KeyError:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)
    return cloned


@router.post("/api/scenarios/queue/{scenario_id}")
async def scenario_queue_add(scenario_id: str):
    scenario = store.get_scenario(scenario_id)
    if not scenario:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)

    queued = runner.queue_scenario(scenario)
    return {"queued": queued, "scenario_id": scenario_id, "queue_count": len(runner.queued_items())}


@router.delete("/api/scenarios/queue/{scenario_id}")
async def scenario_queue_remove(scenario_id: str):
    removed = runner.dequeue_scenario(scenario_id)
    return {"removed": removed, "scenario_id": scenario_id, "queue_count": len(runner.queued_items())}


@router.post("/api/scenarios/queue/clear")
async def scenario_queue_clear():
    runner.clear_queue()
    return {"cleared": True}


@router.post("/api/scenarios/queue/run")
async def scenario_queue_run(background_tasks: BackgroundTasks):
    if runner.is_running():
        return JSONResponse({"error": "A scenario run is already in progress"}, status_code=409)

    queued = runner.queued_items()
    if not queued:
        return JSONResponse({"error": "Scenario queue is empty"}, status_code=400)

    background_tasks.add_task(runner.run_queue)
    return {"started": True, "count": len(queued)}


@router.post("/api/scenarios/run/{scenario_id}")
async def scenario_run_single(scenario_id: str, background_tasks: BackgroundTasks):
    if runner.is_running():
        return JSONResponse({"error": "A scenario run is already in progress"}, status_code=409)

    scenario = store.get_scenario(scenario_id)
    if not scenario:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)

    background_tasks.add_task(runner.run_scenario, scenario)
    return {"started": True, "scenario_id": scenario_id}


@router.post("/api/scenarios/run-selected")
async def scenario_run_selected(background_tasks: BackgroundTasks, payload: dict = Body(...)):
    if runner.is_running():
        return JSONResponse({"error": "A scenario run is already in progress"}, status_code=409)

    ids = payload.get("scenario_ids") or []
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "scenario_ids must be a non-empty list"}, status_code=400)

    selected = []
    missing = []
    for scenario_id in ids:
        scenario = store.get_scenario(str(scenario_id))
        if not scenario:
            missing.append(str(scenario_id))
            continue
        selected.append(scenario)

    if missing:
        return JSONResponse({"error": "Some scenarios were not found", "missing": missing}, status_code=404)

    background_tasks.add_task(runner.run_scenarios, selected)
    return {"started": True, "count": len(selected)}


@router.post("/api/scenarios/run/resume")
async def scenario_run_resume(payload: dict = Body(default={})):
    note = str(payload.get("note", "")).strip()
    resumed = runner.resume_manual_checkpoint(note=note)
    if not resumed:
        return JSONResponse({"error": "No active manual checkpoint"}, status_code=409)
    return {"resumed": True}


@router.get("/api/scenarios/{scenario_id}")
async def scenario_get(scenario_id: str):
    item = store.get_scenario(scenario_id)
    if not item:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)
    return item


@router.put("/api/scenarios/{scenario_id}")
async def scenario_update(scenario_id: str, payload: dict = Body(...)):
    try:
        updated = store.update_scenario(scenario_id, payload)
    except ScenarioValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except KeyError:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)
    return updated


@router.delete("/api/scenarios/{scenario_id}")
async def scenario_delete(scenario_id: str):
    removed = store.delete_scenario(scenario_id)
    if not removed:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)
    return {"deleted": True, "scenario_id": scenario_id}
