"""Full automated audit suite — runs all phases sequentially."""

import platform
import socket
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Body

from app.core.config import BROWSER_TARGETS, API_TARGETS, ALL_INSTALLERS
from app.core.event_bus import bus
from app.automation.browser import simulate_data_leakage
from app.automation.api_calls import probe_api_endpoint
from app.automation.installers import install_group
from app.automation.mcp_servers import MCP_SERVERS, install_mcp_server, inject_mcp_config
from app.automation.scenario_runner import runner as scenario_runner

router = APIRouter()


@dataclass
class _AuditState:
    running:    bool = False
    started_at: str  = ""
    phase:      str  = ""
    include_scenarios: bool = False

state = _AuditState()


@router.get("/api/audit/status")
async def audit_status():
    return {
        "running":    state.running,
        "started_at": state.started_at,
        "phase":      state.phase,
        "include_scenarios": state.include_scenarios,
        "events":     len(bus.history),
    }


@router.post("/api/audit/start")
async def start_audit(background_tasks: BackgroundTasks, payload: dict = Body(default={})):
    include_scenarios = bool(payload.get("include_scenarios", False)) if isinstance(payload, dict) else False

    if state.running:
        return {"started": False, "reason": "Audit already running"}

    if include_scenarios and scenario_runner.is_running():
        return {
            "started": False,
            "reason": "Scenario runner is already active. Wait for it to finish before including Phase 5.",
        }

    bus.clear_history()
    state.include_scenarios = include_scenarios
    background_tasks.add_task(_run_full_audit, include_scenarios)
    return {"started": True, "include_scenarios": include_scenarios}


async def _run_full_audit(include_scenarios: bool = False):
    state.running    = True
    state.started_at = datetime.now(timezone.utc).isoformat()
    state.include_scenarios = include_scenarios
    emit             = bus.emit
    total_phases = 5 if include_scenarios else 4

    sep = "═" * 55

    try:
        await emit("INFO", "AUDIT", sep)
        await emit("INFO", "AUDIT", "SHADOW AI SIMULATOR — FULL AUDIT STARTED")
        await emit("INFO", "AUDIT", f"Host: {socket.gethostname()}  |  OS: {platform.system()} {platform.release()}")
        await emit("INFO", "AUDIT", f"Started: {state.started_at}")
        if include_scenarios:
            await emit("INFO", "AUDIT", "Scenario queue execution is enabled as Phase 5.")
        await emit("INFO", "AUDIT", sep)

        # ── Phase 1: Browser / web data leakage ──────────────────────────────
        state.phase = "web_leakage"
        await emit("INFO", "AUDIT", f"PHASE 1 / {total_phases} — Web Data Leakage Simulation ({len(BROWSER_TARGETS)} targets)")
        for target in BROWSER_TARGETS:
            try:
                await simulate_data_leakage(target, emit)
            except Exception as exc:
                await emit("ERROR", "AUDIT", f"Unhandled error — {target['name']}: {exc}")

        # ── Phase 2: Direct API probes ────────────────────────────────────────
        state.phase = "api_probe"
        await emit("INFO", "AUDIT", f"PHASE 2 / {total_phases} — Direct API Endpoint Probes ({len(API_TARGETS)} targets)")
        for target in API_TARGETS:
            try:
                await probe_api_endpoint(target, emit)
            except Exception as exc:
                await emit("ERROR", "AUDIT", f"Unhandled error — {target['name']}: {exc}")

        # ── Phase 3: Installer downloads ──────────────────────────────────────
        state.phase = "installers"
        await emit("INFO", "AUDIT", f"PHASE 3 / {total_phases} — AI Application Installs ({len(ALL_INSTALLERS)} packages)")
        try:
            await install_group(ALL_INSTALLERS, emit, label="Audit installer phase")
        except Exception as exc:
            await emit("ERROR", "AUDIT", f"Unhandled installer phase error: {exc}")

        # ── Phase 4: MCP server installs + config injection ───────────────────
        state.phase = "mcp"
        await emit("INFO", "AUDIT", f"PHASE 4 / {total_phases} — MCP Server Installs + Config Injection ({len(MCP_SERVERS)} servers)")
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

        # ── Phase 5: Scenario queue execution (optional) ──────────────────────
        if include_scenarios:
            state.phase = "scenarios"
            queued_count = len(scenario_runner.queued_items())
            await emit("INFO", "AUDIT", f"PHASE 5 / {total_phases} — Scenario Queue Pack Execution ({queued_count} queued)")

            if scenario_runner.is_running():
                await emit("WARN", "AUDIT", "Scenario runner already active; skipping Phase 5 queue execution.")
            elif queued_count == 0:
                await emit("WARN", "AUDIT", "Scenario queue is empty; skipping Phase 5.")
            else:
                try:
                    results = await scenario_runner.run_queue()
                    passed = sum(1 for item in results if item.get("status") == "passed")
                    failed = sum(1 for item in results if item.get("status") == "failed")
                    await emit("INFO", "AUDIT", f"Scenario phase completed: {len(results)} run(s), {passed} passed, {failed} failed")
                except Exception as exc:
                    await emit("ERROR", "AUDIT", f"Scenario phase execution error: {exc}")

        # ── Done ──────────────────────────────────────────────────────────────
        await emit("INFO", "AUDIT", sep)
        await emit("INFO", "AUDIT", "SHADOW AI AUDIT COMPLETE")
        await emit("INFO", "AUDIT", f"Total events logged: {len(bus.history)}")
        await emit("INFO", "AUDIT", "Download a report from the Reports section to cross-reference with your SIEM.")
        await emit("INFO", "AUDIT", sep)

        state.phase = "complete"
    finally:
        state.running = False
