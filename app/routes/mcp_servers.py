"""Routes for MCP server installation and config injection simulation."""

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.event_bus import bus
from app.automation.mcp_servers import (
    MCP_SERVERS,
    install_mcp_server,
    inject_mcp_config,
    restore_mcp_config,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Metadata
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/mcp/servers")
async def list_servers():
    """Return all MCP server definitions (without install_cmd internals)."""
    return [
        {
            "id":          s["id"],
            "name":        s["name"],
            "description": s["description"],
            "risk":        s["risk"],
            "risk_color":  s["risk_color"],
            "data_type":   s["data_type"],
            "install_type": s["install_type"],
        }
        for s in MCP_SERVERS
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Install individual / all servers
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/mcp/install/{server_id}")
async def install_single(server_id: str, background_tasks: BackgroundTasks):
    server = next((s for s in MCP_SERVERS if s["id"] == server_id), None)
    if not server:
        return JSONResponse({"error": "Unknown MCP server ID"}, status_code=404)
    background_tasks.add_task(_run_install, server_id)
    return {"started": True, "id": server_id, "name": server["name"]}


@router.post("/api/mcp/install/all")
async def install_all(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_install_all)
    return {"started": True, "count": len(MCP_SERVERS)}


# ─────────────────────────────────────────────────────────────────────────────
# Config injection (the FIM-triggering step)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/mcp/inject/{server_id}")
async def inject_single(server_id: str, background_tasks: BackgroundTasks):
    server = next((s for s in MCP_SERVERS if s["id"] == server_id), None)
    if not server:
        return JSONResponse({"error": "Unknown MCP server ID"}, status_code=404)
    background_tasks.add_task(_run_inject, [server_id])
    return {"started": True, "id": server_id, "name": server["name"]}


@router.post("/api/mcp/inject/all")
async def inject_all_servers(background_tasks: BackgroundTasks):
    all_ids = [s["id"] for s in MCP_SERVERS]
    background_tasks.add_task(_run_inject, all_ids)
    return {"started": True, "count": len(all_ids)}


# ─────────────────────────────────────────────────────────────────────────────
# Full simulation (install + inject for a specific server)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/mcp/simulate/{server_id}")
async def simulate_single(server_id: str, background_tasks: BackgroundTasks):
    """Install the MCP package then inject it into the AI client config."""
    server = next((s for s in MCP_SERVERS if s["id"] == server_id), None)
    if not server:
        return JSONResponse({"error": "Unknown MCP server ID"}, status_code=404)
    background_tasks.add_task(_run_full_simulation, [server_id])
    return {"started": True, "id": server_id, "name": server["name"]}


@router.post("/api/mcp/simulate/all")
async def simulate_all(background_tasks: BackgroundTasks):
    """Install all MCP packages then inject all into the AI client config."""
    all_ids = [s["id"] for s in MCP_SERVERS]
    background_tasks.add_task(_run_full_simulation, all_ids)
    return {"started": True, "count": len(all_ids)}


# ─────────────────────────────────────────────────────────────────────────────
# Restore (cleanup)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/mcp/restore")
async def restore_config(background_tasks: BackgroundTasks):
    """Restore Claude Desktop config from the .bak backup created during injection."""
    background_tasks.add_task(_run_restore)
    return {"started": True}


# ─────────────────────────────────────────────────────────────────────────────
# Background task helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _run_install(server_id: str):
    await install_mcp_server(server_id, bus.emit)


async def _run_install_all():
    await bus.emit("INFO", "MCP",
                   f"Starting install of all {len(MCP_SERVERS)} MCP servers…")
    for s in MCP_SERVERS:
        await install_mcp_server(s["id"], bus.emit)
    await bus.emit("INFO", "MCP", "All MCP server installs complete")


async def _run_inject(server_ids: list[str]):
    await inject_mcp_config(server_ids, bus.emit)


async def _run_full_simulation(server_ids: list[str]):
    sep = "─" * 55
    await bus.emit("INFO", "MCP", sep)
    await bus.emit("INFO", "MCP",
                   f"MCP SIMULATION — {len(server_ids)} server(s): "
                   + ", ".join(server_ids))
    await bus.emit("INFO", "MCP", sep)

    # Phase A: package installs (EDR process + network telemetry)
    await bus.emit("INFO", "MCP",
                   f"Phase A — Package Installation ({len(server_ids)} server(s))")
    for sid in server_ids:
        await install_mcp_server(sid, bus.emit)

    # Phase B: config injection (FIM telemetry)
    await bus.emit("INFO", "MCP",
                   "Phase B — AI Client Config Injection (FIM test)")
    await inject_mcp_config(server_ids, bus.emit)

    await bus.emit("INFO", "MCP", sep)
    await bus.emit("INFO", "MCP",
                   "MCP SIMULATION COMPLETE — check your EDR and FIM alerts")
    await bus.emit("INFO", "MCP", sep)


async def _run_restore():
    await restore_mcp_config(bus.emit)
