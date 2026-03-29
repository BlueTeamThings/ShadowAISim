"""Application launcher and process tracking for installed apps."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from app.automation.installers import STATUS, preflight_install_state, validate_install

Emitter = Callable[..., Awaitable[None]]


@dataclass
class ProcessMeta:
    app_id: str
    pid: int
    start_time: str
    command: list[str]
    working_dir: str
    status: str


_PROCESSES: dict[str, asyncio.subprocess.Process] = {}
_PROCESS_META: dict[str, ProcessMeta] = {}
_PROCESS_LOGS: dict[str, list[str]] = {}


def _platform_key() -> str:
    if os.name == "nt":
        return "windows"
    if Path("/System/Library/CoreServices").exists():
        return "darwin"
    return "linux"


def _append_log(app_id: str, line: str):
    logs = _PROCESS_LOGS.setdefault(app_id, [])
    logs.append(line)
    if len(logs) > 400:
        del logs[0: len(logs) - 400]


async def _stream_process_logs(app_id: str, proc: asyncio.subprocess.Process, emit: Emitter):
    async def _relay(stream, label: str):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if text:
                _append_log(app_id, f"[{label}] {text}")
                await emit("INFO", "APP", f"{app_id}: {text}", app_id, stream=label)

    await asyncio.gather(_relay(proc.stdout, "stdout"), _relay(proc.stderr, "stderr"))
    rc = await proc.wait()
    meta = _PROCESS_META.get(app_id)
    if meta:
        meta.status = "exited"
    await emit("INFO", "APP", f"{app_id}: process exited with code {rc}", app_id, classification="PROCESS_EXITED", return_code=rc)


def _build_launch_command(app: dict, preflight: dict) -> list[str]:
    platform_key = _platform_key()

    if platform_key == "linux":
        cmd = list(app.get("launch_command_linux") or [])
    elif platform_key == "windows":
        cmd = list(app.get("launch_command_windows") or [])
    else:
        cmd = list(app.get("launch_command_linux") or [])

    if app.get("launch_type") == "appimage" and preflight.get("binary_path"):
        return [preflight["binary_path"]]

    if app.get("launch_type") in ("binary", "cli") and preflight.get("binary_path"):
        if cmd and shutil.which(cmd[0]) is None:
            return [preflight["binary_path"]] + cmd[1:]

    return cmd


async def start_app(app: dict, emit: Emitter) -> dict:
    app_id = app["app_id"]
    pre = await preflight_install_state(app)
    validation = await validate_install(app)

    if not pre.get("installed"):
        return {
            "app_id": app_id,
            "installed": False,
            "start_attempted": False,
            "process_started": False,
            "pid": None,
            "classification": STATUS["START_FAILED"],
            "message": "App is not installed",
        }

    if not validation.get("ok"):
        return {
            "app_id": app_id,
            "installed": True,
            "start_attempted": False,
            "process_started": False,
            "pid": None,
            "classification": STATUS["START_BLOCKED_INVALID_ARTIFACT"],
            "message": validation.get("reason", "Artifact validation failed"),
        }

    # Prefer service management for Ollama before direct user-space process launch.
    if app_id == "ollama":
        svc = await ollama_service_action("start", emit)
        return {
            "app_id": app_id,
            "installed": True,
            "start_attempted": True,
            "process_started": bool(svc.get("ok")),
            "pid": svc.get("pid"),
            "classification": STATUS["STARTABLE"] if svc.get("ok") else STATUS["START_FAILED"],
            "message": svc.get("message", "service action completed"),
        }

    if app_id in _PROCESSES:
        proc = _PROCESSES[app_id]
        if proc.returncode is None:
            meta = _PROCESS_META.get(app_id)
            return {
                "app_id": app_id,
                "installed": pre.get("installed", False),
                "start_attempted": False,
                "process_started": True,
                "pid": proc.pid,
                "classification": STATUS["STARTABLE"],
                "message": "Already running",
                "process": asdict(meta) if meta else None,
            }

    cmd = _build_launch_command(app, pre)
    if not cmd:
        return {
            "app_id": app_id,
            "installed": pre.get("installed", False),
            "start_attempted": False,
            "process_started": False,
            "pid": None,
            "classification": STATUS["START_FAILED"],
            "message": "No launch command is defined for this app on this platform",
        }

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.home()),
        )
        _PROCESSES[app_id] = proc
        meta = ProcessMeta(
            app_id=app_id,
            pid=proc.pid,
            start_time=datetime.now(timezone.utc).isoformat(),
            command=cmd,
            working_dir=str(Path.home()),
            status="running",
        )
        _PROCESS_META[app_id] = meta
        await emit("SUCCESS", "APP", f"{app['display_name']}: process started", app_id, classification=STATUS["STARTABLE"], pid=proc.pid, command=cmd)
        asyncio.create_task(_stream_process_logs(app_id, proc, emit))
        return {
            "app_id": app_id,
            "installed": pre.get("installed", False),
            "start_attempted": True,
            "process_started": True,
            "pid": proc.pid,
            "classification": STATUS["STARTABLE"],
            "message": "Process started",
            "process": asdict(meta),
        }
    except Exception as exc:
        await emit("ERROR", "APP", f"{app['display_name']}: failed to start ({exc})", app_id, classification=STATUS["START_FAILED"])
        return {
            "app_id": app_id,
            "installed": pre.get("installed", False),
            "start_attempted": True,
            "process_started": False,
            "pid": None,
            "classification": STATUS["START_FAILED"],
            "message": str(exc),
        }


async def stop_app(app_id: str, emit: Emitter) -> dict:
    proc = _PROCESSES.get(app_id)
    if not proc or proc.returncode is not None:
        return {
            "app_id": app_id,
            "stopped": False,
            "classification": "NOT_RUNNING",
            "message": "Process not running",
        }

    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()

    meta = _PROCESS_META.get(app_id)
    if meta:
        meta.status = "stopped"
    await emit("INFO", "APP", f"{app_id}: process stopped", app_id, classification="PROCESS_STOPPED")
    return {
        "app_id": app_id,
        "stopped": True,
        "classification": "PROCESS_STOPPED",
        "message": "Process stopped",
    }


def get_process_info(app_id: str) -> dict:
    meta = _PROCESS_META.get(app_id)
    proc = _PROCESSES.get(app_id)
    running = bool(proc and proc.returncode is None)
    return {
        "running": running,
        "process": asdict(meta) if meta else None,
    }


def get_app_logs(app_id: str) -> list[str]:
    return list(_PROCESS_LOGS.get(app_id, []))


async def ollama_service_action(action: str, emit: Emitter) -> dict:
    if action not in {"start", "stop", "restart", "health", "api-status", "pull-baseline-model"}:
        return {"ok": False, "message": "Unsupported Ollama action"}

    if action == "health" or action == "api-status":
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get("http://127.0.0.1:11434/api/tags")
            ok = resp.status_code == 200
            return {"ok": ok, "status": resp.status_code, "message": "healthy" if ok else "not healthy"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    if action == "pull-baseline-model":
        cmd = ["ollama", "pull", "llama3.2:1b"]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        return {
            "ok": proc.returncode == 0,
            "message": (out or err).decode(errors="replace")[:2000],
        }

    # Prefer systemd when available.
    systemctl = shutil.which("systemctl")
    if systemctl:
        target = "restart" if action == "restart" else action
        cmd = [systemctl, target, "ollama"]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        ok = proc.returncode == 0
        await emit("INFO", "INSTALLER", f"Ollama service {action}: {'ok' if ok else 'failed'}", "ollama", classification="OLLAMA_SERVICE_ACTION")
        return {"ok": ok, "message": (out or err).decode(errors="replace")[:1500]}

    # User-space fallback.
    if action in {"start", "restart"}:
        cmd = ["ollama", "serve"]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _PROCESSES["ollama_service"] = proc
        _PROCESS_META["ollama_service"] = ProcessMeta(
            app_id="ollama_service",
            pid=proc.pid,
            start_time=datetime.now(timezone.utc).isoformat(),
            command=cmd,
            working_dir=str(Path.home()),
            status="running",
        )
        return {"ok": True, "message": "Started in user space", "pid": proc.pid}

    if action == "stop":
        return await stop_app("ollama_service", emit)

    return {"ok": False, "message": "Action not handled"}
