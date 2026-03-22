"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import stream, web_leakage, api_probe, installers, audit, reports

BASE_DIR    = Path(__file__).parent.parent
STATIC_DIR  = BASE_DIR / "static"

app = FastAPI(title="Shadow AI Simulator", version="1.0.0")

# Static files (frontend)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routers
app.include_router(stream.router)
app.include_router(web_leakage.router)
app.include_router(api_probe.router)
app.include_router(installers.router)
app.include_router(audit.router)
app.include_router(reports.router)


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
