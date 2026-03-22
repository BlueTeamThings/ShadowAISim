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
    from collections import Counter
    if not bus.history:
        return {"events": 0}
    counts = Counter(e.get("level") for e in bus.history)
    return {
        "events":  len(bus.history),
        "alerts":  counts.get("ALERT",   0),
        "blocked": counts.get("BLOCKED", 0),
        "errors":  counts.get("ERROR",   0),
    }
