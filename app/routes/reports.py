"""Report generation and download routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.core.event_bus import bus
from app.core.report_generator import build_json_report, build_html_report

router = APIRouter()

_NO_DATA = JSONResponse(
    {"error": "No audit data yet. Run an audit or individual tests first."},
    status_code=400,
)


@router.get("/api/reports/json")
async def download_json():
    if not bus.history:
        return _NO_DATA
    content = build_json_report(bus.history)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=shadow-ai-audit.json"},
    )


@router.get("/api/reports/html")
async def download_html():
    if not bus.history:
        return _NO_DATA
    content = build_html_report(bus.history)
    return Response(
        content=content,
        media_type="text/html",
        headers={"Content-Disposition": "attachment; filename=shadow-ai-audit-report.html"},
    )


@router.get("/api/reports/summary")
async def summary():
    from app.core.report_generator import _summarise
    if not bus.history:
        return {"events": 0, "alerts": 0, "blocked": 0, "errors": 0,
                "web": {"reachable": 0, "blocked": 0, "leaks_simulated": 0, "inputs_found": 0},
                "installers": {"downloaded": 0, "installed": 0, "blocked": 0, "failed": 0},
                "probes": {"sent": 0, "traffic_generated": 0, "blocked": 0}}
    s = _summarise(bus.history)
    return {
        "events":     len(bus.history),
        "alerts":     s["alerts"],
        "blocked":    s["blocked"],
        "errors":     s["errors"],
        "web":        s["web"],
        "installers": s["installers"],
        "probes":     s["probes"],
        "mcp":        s["mcp"],
    }
