"""API routes for workflow definitions and workflow execution."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body
from fastapi.responses import JSONResponse

from app.automation.workflow_runner import runner, store
from app.core.workflow_store import WorkflowValidationError

router = APIRouter()


@router.get("/api/workflows/meta")
async def workflows_meta():
    return store.metadata()


@router.get("/api/workflows")
async def workflows_list():
    items = store.list_workflows()
    return {"items": items, "count": len(items)}


@router.get("/api/workflows/runs")
async def workflow_runs(limit: int = 25):
    return {
        "items": store.list_run_history(limit=max(1, min(limit, 100))),
    }


@router.get("/api/workflows/run/status")
async def workflow_run_status():
    return runner.status()


@router.post("/api/workflows")
async def workflow_create(payload: dict = Body(...)):
    try:
        created = store.create_workflow(payload)
    except WorkflowValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return created


@router.post("/api/workflows/{workflow_id}/duplicate")
async def workflow_duplicate(workflow_id: str):
    try:
        cloned = store.duplicate_workflow(workflow_id)
    except KeyError:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    return cloned


@router.post("/api/workflows/run/{workflow_id}")
async def workflow_run_single(workflow_id: str, background_tasks: BackgroundTasks):
    if runner.is_running():
        return JSONResponse({"error": "A workflow run is already in progress"}, status_code=409)

    workflow = store.get_workflow(workflow_id)
    if not workflow:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)

    if not workflow.get("enabled", True):
        return JSONResponse({"error": "Workflow is disabled"}, status_code=400)

    background_tasks.add_task(runner.run_workflow, workflow)
    return {"started": True, "workflow_id": workflow_id}


@router.post("/api/workflows/run-selected")
async def workflow_run_selected(background_tasks: BackgroundTasks, payload: dict = Body(...)):
    if runner.is_running():
        return JSONResponse({"error": "A workflow run is already in progress"}, status_code=409)

    requested_ids = payload.get("workflow_ids") or []
    if not isinstance(requested_ids, list) or not requested_ids:
        return JSONResponse({"error": "workflow_ids must be a non-empty list"}, status_code=400)

    workflows = []
    missing = []
    disabled = []
    for workflow_id in requested_ids:
        workflow = store.get_workflow(str(workflow_id))
        if not workflow:
            missing.append(str(workflow_id))
            continue
        if not workflow.get("enabled", True):
            disabled.append(str(workflow_id))
            continue
        workflows.append(workflow)

    if missing:
        return JSONResponse({"error": "Some workflows were not found", "missing": missing}, status_code=404)

    if not workflows:
        return JSONResponse({"error": "No runnable workflows selected", "disabled": disabled}, status_code=400)

    background_tasks.add_task(runner.run_workflows, workflows)
    return {
        "started": True,
        "count": len(workflows),
        "disabled": disabled,
    }


@router.get("/api/workflows/{workflow_id}")
async def workflow_get(workflow_id: str):
    workflow = store.get_workflow(workflow_id)
    if not workflow:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    return workflow


@router.put("/api/workflows/{workflow_id}")
async def workflow_update(workflow_id: str, payload: dict = Body(...)):
    try:
        updated = store.update_workflow(workflow_id, payload)
    except WorkflowValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except KeyError:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    return updated


@router.delete("/api/workflows/{workflow_id}")
async def workflow_delete(workflow_id: str):
    removed = store.delete_workflow(workflow_id)
    if not removed:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    return {"deleted": True, "workflow_id": workflow_id}
