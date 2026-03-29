"""Full automated audit suite — runs all phases sequentially."""

import platform
import socket
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks

from app.core.config import BROWSER_TARGETS, API_TARGETS, ALL_INSTALLERS
from app.core.event_bus import bus
from app.automation.browser import simulate_data_leakage
from app.automation.api_calls import probe_api_endpoint
from app.automation.installers import install_group
from app.automation.mcp_servers import MCP_SERVERS, install_mcp_server, inject_mcp_config

router = APIRouter()


@dataclass
class _AuditState:
    running:    bool = False
    started_at: str  = ""
    phase:      str  = ""

state = _AuditState()


@router.get("/api/audit/status")
async def audit_status():
    return {
        "running":    state.running,
        "started_at": state.started_at,
        "phase":      state.phase,
        "events":     len(bus.history),
    }


@router.post("/api/audit/start")
async def start_audit(background_tasks: BackgroundTasks):
    if state.running:
        return {"started": False, "reason": "Audit already running"}
    bus.clear_history()
    background_tasks.add_task(_run_full_audit)
    return {"started": True}


async def _run_full_audit():
    state.running    = True
    state.started_at = datetime.now(timezone.utc).isoformat()
    emit             = bus.emit

    sep = "═" * 55

    await emit("INFO", "AUDIT", sep)
    await emit("INFO", "AUDIT", "SHADOW AI SIMULATOR — FULL AUDIT STARTED")
    await emit("INFO", "AUDIT", f"Host: {socket.gethostname()}  |  OS: {platform.system()} {platform.release()}")
    await emit("INFO", "AUDIT", f"Started: {state.started_at}")
    await emit("INFO", "AUDIT", sep)

    # ── Phase 1: Browser / web data leakage ──────────────────────────────────
    state.phase = "web_leakage"
    await emit("INFO", "AUDIT", f"PHASE 1 / 4 — Web Data Leakage Simulation ({len(BROWSER_TARGETS)} targets)")
    for target in BROWSER_TARGETS:
        try:
            await simulate_data_leakage(target, emit)
        except Exception as exc:
            await emit("ERROR", "AUDIT", f"Unhandled error — {target['name']}: {exc}")

    # ── Phase 2: Direct API probes ────────────────────────────────────────────
    state.phase = "api_probe"
    await emit("INFO", "AUDIT", f"PHASE 2 / 4 — Direct API Endpoint Probes ({len(API_TARGETS)} targets)")
    for target in API_TARGETS:
        try:
            await probe_api_endpoint(target, emit)
        except Exception as exc:
            await emit("ERROR", "AUDIT", f"Unhandled error — {target['name']}: {exc}")

    # ── Phase 3: Installer downloads ──────────────────────────────────────────
    state.phase = "installers"
    await emit("INFO", "AUDIT", f"PHASE 3 / 4 — AI Application Installs ({len(ALL_INSTALLERS)} packages)")
    try:
        await install_group(ALL_INSTALLERS, emit, label="Audit installer phase")
    except Exception as exc:
        await emit("ERROR", "AUDIT", f"Unhandled installer phase error: {exc}")

    # ── Phase 4: MCP server installs + config injection ───────────────────────
    state.phase = "mcp"
    await emit("INFO", "AUDIT",
               f"PHASE 4 / 4 — MCP Server Installs + Config Injection ({len(MCP_SERVERS)} servers)")
    for server in MCP_SERVERS:
        try:
            await install_mcp_server(server["id"], emit)
        except Exception as exc:
            await emit("ERROR", "AUDIT", f"Unhandled error — {server['name']}: {exc}")

    all_ids = [s["id"] for s in MCP_SERVERS]
    try:
        await inject_mcp_config(all_ids, emit)
    except Exception as exc:
        await emit("ERROR", "AUDIT", f"MCP config injection error: {exc}")

    # ── Done ──────────────────────────────────────────────────────────────────
    await emit("INFO", "AUDIT", sep)
    await emit("INFO", "AUDIT", "SHADOW AI AUDIT COMPLETE")
    await emit("INFO", "AUDIT", f"Total events logged: {len(bus.history)}")
    await emit("INFO", "AUDIT", "Download a report from the Reports section to cross-reference with your SIEM.")
    await emit("INFO", "AUDIT", sep)

    state.running = False
    state.phase   = "complete"
