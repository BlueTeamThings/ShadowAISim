"""Sequential scenario execution engine with queueing and manual checkpoints."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import TimeoutError as PWTimeout
from playwright.async_api import async_playwright

from app.automation.browser import check_chromium_available
from app.automation.installers import STATUS, install_app
from app.automation.launcher import start_app, stop_app
from app.automation.mcp_servers import inject_mcp_config, install_mcp_server
from app.core.app_catalog import get_app, list_apps
from app.core.event_bus import bus
from app.core.scenario_store import SCREENSHOT_DIR, ScenarioStore

Emitter = Callable[..., Awaitable[None]]


@dataclass
class BrowserContext:
    playwright: object | None = None
    browser: object | None = None
    context: object | None = None
    page: object | None = None


@dataclass
class ExecutionContext:
    emit: Emitter
    browser: BrowserContext = field(default_factory=BrowserContext)
    launched_processes: dict[str, asyncio.subprocess.Process] = field(default_factory=dict)
    clipboard_cache: str = ""
    capabilities: dict[str, bool] = field(default_factory=dict)

    async def ensure_browser_page(self):
        if self.browser.page:
            return self.browser.page

        chromium_ok, chromium_msg, chromium_classification = await check_chromium_available()
        if not chromium_ok:
            raise RuntimeError(f"Browser unavailable: {chromium_msg} ({chromium_classification})")

        headless = platform.system().lower() == "linux" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        self.browser.playwright = await async_playwright().start()
        self.browser.browser = await self.browser.playwright.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            timeout=30_000,
        )
        self.browser.context = await self.browser.browser.new_context(ignore_https_errors=True)
        self.browser.page = await self.browser.context.new_page()
        return self.browser.page

    async def close(self):
        for app_id, proc in list(self.launched_processes.items()):
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=6)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            self.launched_processes.pop(app_id, None)

        if self.browser.context:
            await self.browser.context.close()
        if self.browser.browser:
            await self.browser.browser.close()
        if self.browser.playwright:
            await self.browser.playwright.stop()


class ScenarioRunner:
    def __init__(self, store: ScenarioStore) -> None:
        self.store = store
        self._run_lock = asyncio.Lock()
        self._queue: list[dict] = []
        self._manual_event: asyncio.Event | None = None
        self._manual_note: str = ""
        self._state: dict = {
            "running": False,
            "paused": False,
            "queue_running": False,
            "manual_checkpoint": None,
            "current_run": None,
            "last_completed": None,
        }

    def is_running(self) -> bool:
        return bool(self._state.get("running"))

    def queue_scenario(self, scenario: dict) -> bool:
        scenario_id = scenario.get("id")
        if not scenario_id:
            return False

        if any(item.get("id") == scenario_id for item in self._queue):
            return False

        self._queue.append(
            {
                "id": scenario_id,
                "title": scenario.get("title", scenario_id),
                "category": scenario.get("category", ""),
                "family": scenario.get("family", ""),
                "risk_level": scenario.get("risk_level", "medium"),
            }
        )
        return True

    def queued_items(self) -> list[dict]:
        return list(self._queue)

    def dequeue_scenario(self, scenario_id: str) -> bool:
        original = len(self._queue)
        self._queue = [item for item in self._queue if item.get("id") != scenario_id]
        return len(self._queue) != original

    def clear_queue(self) -> None:
        self._queue.clear()

    def resume_manual_checkpoint(self, note: str = "") -> bool:
        if not self._manual_event:
            return False
        self._manual_note = note
        self._manual_event.set()
        return True

    def status(self) -> dict:
        current = self._state.get("current_run")
        if current and current.get("started_epoch"):
            current = {
                **current,
                "elapsed_seconds": round(time.monotonic() - current["started_epoch"], 2),
            }
            current.pop("started_epoch", None)

        return {
            "running": self._state.get("running", False),
            "paused": self._state.get("paused", False),
            "queue_running": self._state.get("queue_running", False),
            "manual_checkpoint": self._state.get("manual_checkpoint"),
            "queue": self.queued_items(),
            "current_run": current,
            "last_completed": self._state.get("last_completed"),
        }

    async def run_scenario(self, scenario: dict) -> dict:
        async with self._run_lock:
            return await self._run_scenario_locked(scenario)

    async def run_scenarios(self, scenarios: list[dict]) -> list[dict]:
        async with self._run_lock:
            return await self._run_many_locked(scenarios)

    async def run_queue(self) -> list[dict]:
        async with self._run_lock:
            self._state["queue_running"] = True
            try:
                scenarios = []
                for queued in self._queue:
                    scenario = self.store.get_scenario(queued.get("id", ""))
                    if scenario:
                        scenarios.append(scenario)
                self._queue.clear()
                return await self._run_many_locked(scenarios)
            finally:
                self._state["queue_running"] = False

    async def _run_many_locked(self, scenarios: list[dict]) -> list[dict]:
        results = []
        for scenario in scenarios:
            results.append(await self._run_scenario_locked(scenario))
        return results

    def _append_log(self, level: str, message: str) -> None:
        current = self._state.get("current_run")
        if not current:
            return
        logs = current.setdefault("logs", [])
        logs.append({"ts": time.time(), "level": level, "message": message})
        if len(logs) > 300:
            del logs[0: len(logs) - 300]

    async def _emit(self, level: str, message: str, **extra) -> None:
        await bus.emit(level, "SCENARIO", message, **extra)
        self._append_log(level, message)

    async def _run_scenario_locked(self, scenario: dict) -> dict:
        run_id = f"scn-run-{uuid.uuid4().hex[:12]}"
        started_epoch = time.monotonic()
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        steps = scenario.get("steps", [])

        self._state["running"] = True
        self._state["paused"] = False
        self._state["manual_checkpoint"] = None
        self._state["current_run"] = {
            "run_id": run_id,
            "scenario_id": scenario.get("id"),
            "scenario_title": scenario.get("title"),
            "status": "running",
            "current_step": 0,
            "total_steps": len(steps),
            "step_results": [],
            "logs": [],
            "started_at": started_at,
            "started_epoch": started_epoch,
        }

        await self._emit(
            "INFO",
            f"Scenario started: {scenario.get('title')} ({len(steps)} step(s))",
            scenario_id=scenario.get("id"),
            run_id=run_id,
        )

        context = ExecutionContext(emit=bus.emit)
        step_results = []
        run_status = "passed"

        try:
            for idx, step in enumerate(steps, start=1):
                self._state["current_run"]["current_step"] = idx
                step_type = step.get("type", "unknown")
                step_label = f"Step {idx}/{len(steps)}: {step_type}"
                await self._emit("INFO", f"{step_label} started", scenario_id=scenario.get("id"), run_id=run_id)

                step_started = time.monotonic()
                success = False
                message = ""
                details = {}
                try:
                    success, message, details = await self._execute_step(step, context)
                except Exception as exc:
                    success = False
                    message = f"Unhandled step error: {exc}"
                    details = {"exception": str(exc)}

                elapsed = round(time.monotonic() - step_started, 2)
                step_result = {
                    "index": idx,
                    "step_id": step.get("id") or f"step-{idx}",
                    "type": step_type,
                    "success": success,
                    "message": message,
                    "details": details,
                    "elapsed_seconds": elapsed,
                }
                step_results.append(step_result)
                self._state["current_run"]["step_results"] = step_results

                if success:
                    level = "INFO" if details.get("skipped") else "SUCCESS"
                    await self._emit(level, f"{step_label} succeeded: {message}", scenario_id=scenario.get("id"), run_id=run_id)
                else:
                    await self._emit("ERROR", f"{step_label} failed: {message}", scenario_id=scenario.get("id"), run_id=run_id)
                    run_status = "failed"
                    break
        finally:
            await context.close()
            self._manual_event = None
            self._manual_note = ""
            self._state["paused"] = False
            self._state["manual_checkpoint"] = None

        elapsed_total = round(time.monotonic() - started_epoch, 2)
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        run_record = {
            "run_id": run_id,
            "scenario_id": scenario.get("id"),
            "scenario_title": scenario.get("title"),
            "status": run_status,
            "started_at": started_at,
            "completed_at": completed_at,
            "elapsed_seconds": elapsed_total,
            "total_steps": len(steps),
            "completed_steps": len(step_results),
            "step_results": step_results,
            "assertions": scenario.get("assertions", []),
            "expected_observables": scenario.get("expected_observables", []),
            "detector_expectations": scenario.get("detector_expectations", []),
        }

        self.store.mark_scenario_run(scenario.get("id"), status=run_status, run_id=run_id)
        self.store.append_run_history(run_record)

        self._state["running"] = False
        self._state["current_run"] = None
        self._state["last_completed"] = run_record

        final_level = "SUCCESS" if run_status == "passed" else "ERROR"
        await self._emit(final_level, f"Scenario {scenario.get('title')} completed with status: {run_status}", scenario_id=scenario.get("id"), run_id=run_id)
        return run_record

    def _resolve_app(self, app_name: str) -> dict | None:
        normalized = app_name.strip().lower()
        catalog = get_app(normalized)
        if catalog:
            return catalog

        for app in list_apps():
            if app.get("display_name", "").strip().lower() == normalized:
                return app
        return None

    def _linux_privileged_cmds(self, base_cmd: list[str]) -> list[list[str]]:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return [base_cmd]

        variants: list[list[str]] = []
        if shutil.which("sudo"):
            variants.append(["sudo", "-n", *base_cmd])
        variants.append(base_cmd)
        return variants

    async def _run_command(self, cmd: list[str]) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return 127, f"Command not found: {cmd[0]}"

        out, err = await proc.communicate()
        output = "\n".join(
            part for part in [
                (out or b"").decode(errors="replace").strip(),
                (err or b"").decode(errors="replace").strip(),
            ]
            if part
        )
        return proc.returncode, output

    async def _install_vscode_fallback(self) -> tuple[bool, str, dict]:
        if shutil.which("code"):
            return True, "VS Code CLI already available", {"classification": STATUS["ALREADY_INSTALLED"]}

        system = platform.system().lower()
        attempts: list[dict] = []

        if system == "windows":
            if not shutil.which("winget"):
                return False, "winget not available to install VS Code", {"classification": STATUS["MANUAL_DOWNLOAD_REQUIRED"]}

            cmd = [
                "winget",
                "install",
                "--id",
                "Microsoft.VisualStudioCode",
                "--exact",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
            rc, output = await self._run_command(cmd)
            attempts.append({"command": " ".join(cmd), "return_code": rc, "output": output[:400]})
            if rc == 0 or shutil.which("code"):
                return True, "VS Code install completed via winget", {
                    "classification": STATUS["INSTALLED_OK"],
                    "attempts": attempts,
                    "code_cli_available": bool(shutil.which("code")),
                }
            return False, "VS Code install failed via winget", {
                "classification": STATUS["MANUAL_DOWNLOAD_REQUIRED"],
                "attempts": attempts,
            }

        if system == "linux":
            commands: list[list[str]] = []
            if shutil.which("snap"):
                commands.extend(self._linux_privileged_cmds(["snap", "install", "--classic", "code"]))

            apt_cmd = ["apt-get", "install", "code", "-y"] if shutil.which("apt-get") else None

            if apt_cmd:
                commands.extend(self._linux_privileged_cmds(apt_cmd))

            if not commands:
                return False, "No Linux installer helper found for VS Code (snap/apt)", {
                    "classification": STATUS["MANUAL_DOWNLOAD_REQUIRED"],
                }

            for cmd in commands:
                rc, output = await self._run_command(cmd)
                attempts.append({"command": " ".join(cmd), "return_code": rc, "output": output[:400]})
                if rc == 0:
                    return True, "VS Code install command completed", {
                        "classification": STATUS["INSTALLED_OK"],
                        "attempts": attempts,
                        "code_cli_available": bool(shutil.which("code")),
                    }

            if shutil.which("code"):
                return True, "VS Code CLI detected after install attempts", {
                    "classification": STATUS["ALREADY_INSTALLED"],
                    "attempts": attempts,
                }

            return False, "VS Code installer fallback failed on Linux", {
                "classification": STATUS["MANUAL_DOWNLOAD_REQUIRED"],
                "attempts": attempts,
            }

        return False, "VS Code installer fallback is unsupported on this OS", {
            "classification": STATUS["MANUAL_DOWNLOAD_REQUIRED"],
        }

    async def _close_ollama_daemon(self) -> dict:
        result = await stop_app("ollama", bus.emit)
        if result.get("stopped"):
            return result

        result = await stop_app("ollama_service", bus.emit)
        return result

    async def _execute_step(self, step: dict, context: ExecutionContext) -> tuple[bool, str, dict]:
        step_type = str(step.get("type", "")).strip()
        if step_type == "install_extension":
            step_type = "install_browser_extension"

        params = step.get("params") or {}

        handlers = {
            "install_application": self._step_install_application,
            "install_browser_extension": self._step_install_extension,
            "launch_application": self._step_launch_application,
            "open_website": self._step_open_website,
            "click_selector": self._step_click_selector,
            "type_text": self._step_type_text,
            "press_shortcut": self._step_press_shortcut,
            "upload_file": self._step_upload_file,
            "copy_text": self._step_copy_text,
            "paste_text": self._step_paste_text,
            "manual_checkpoint": self._step_manual_checkpoint,
            "capability_check": self._step_capability_check,
            "mcp_install_server": self._step_mcp_install_server,
            "mcp_inject_config": self._step_mcp_inject_config,
            "pull_local_model": self._step_pull_local_model,
            "assert_text_contains": self._step_assert_text_contains,
            "assert_clipboard_contains": self._step_assert_clipboard_contains,
            "capture_screenshot": self._step_capture_screenshot,
            "wait": self._step_wait,
            "close_application": self._step_close_application,
        }

        handler = handlers.get(step_type)
        if not handler:
            return False, f"Unsupported step type: {step_type}", {}

        return await handler(params, context)

    async def _step_install_application(self, params: dict, context: ExecutionContext):
        app_name = str(params.get("app_name", "")).strip()
        if not app_name:
            return False, "Missing app_name", {}

        app = self._resolve_app(app_name)
        if app:
            result = await install_app(app, bus.emit)
            success = bool(result.get("installed")) or result.get("classification") == STATUS["ALREADY_INSTALLED"]
            return success, result.get("classification", "completed"), result

        if app_name.lower() in {"vscode", "visual studio code", "code"}:
            return await self._install_vscode_fallback()

        return False, f"Unknown app: {app_name}", {"classification": "UNKNOWN_APP"}

    async def _step_install_extension(self, params: dict, context: ExecutionContext):
        target_app = str(params.get("target_app", "")).strip().lower()
        extension_id = str(params.get("extension_id", "")).strip()
        if not target_app or not extension_id:
            return False, "target_app and extension_id are required", {}

        if target_app in {"vscode", "visual studio code", "code"}:
            if not shutil.which("code"):
                return False, "VS Code CLI not found on PATH", {"classification": "VSCODE_CLI_MISSING"}
            proc = await asyncio.create_subprocess_exec(
                "code",
                "--install-extension",
                extension_id,
                "--force",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            output = (out or err).decode(errors="replace").strip()
            if proc.returncode == 0:
                return True, f"Extension installed: {extension_id}", {"output": output}
            return False, f"Extension install failed ({proc.returncode})", {"output": output}

        return False, f"Unsupported extension target: {target_app}", {"classification": "TARGET_UNSUPPORTED"}

    async def _step_launch_application(self, params: dict, context: ExecutionContext):
        app_name = str(params.get("app_name", "")).strip()
        if not app_name:
            return False, "Missing app_name", {}

        app = self._resolve_app(app_name)
        if app:
            result = await start_app(app, bus.emit)
            success = bool(result.get("process_started"))
            return success, result.get("message", "launch attempted"), result

        command = "code" if app_name.lower() in {"vscode", "visual studio code"} else app_name
        proc = await asyncio.create_subprocess_exec(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        context.launched_processes[app_name.lower()] = proc
        return True, f"Process launched with pid {proc.pid}", {"pid": proc.pid, "command": command}

    async def _step_open_website(self, params: dict, context: ExecutionContext):
        required_capability = str(params.get("requires_capability", "")).strip().lower()
        if required_capability and context.capabilities.get(required_capability) is False:
            return True, f"Skipped because capability '{required_capability}' is unavailable", {"skipped": True, "required_capability": required_capability}

        url = str(params.get("url", "")).strip()
        if not url:
            return False, "Missing url", {}

        page = await context.ensure_browser_page()
        try:
            response = await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        except PWTimeout:
            return False, "Navigation timed out", {"url": url, "classification": "PAGE_TIMEOUT"}

        status = response.status if response else None
        title = await page.title()
        return True, f"Opened {url}", {"url": url, "status": status, "title": title}

    async def _click_selector_with_fallbacks(self, page, selector: str) -> tuple[bool, dict]:
        """Click the first usable target for a selector, preferring visible elements."""
        attempted: list[str] = []
        candidates = [selector]

        if ":visible" not in selector:
            candidates.append(f"{selector}:visible")

        if selector.strip().lower() == "textarea":
            candidates.extend([
                "#prompt-textarea:visible",
                "textarea:visible",
                "[contenteditable='true'][role='textbox']",
                "[contenteditable='true'][aria-label*='chat' i]",
                "[contenteditable='true'][aria-label*='message' i]",
                "[contenteditable='true']",
            ])

        for candidate in candidates:
            if candidate in attempted:
                continue
            attempted.append(candidate)
            try:
                loc = page.locator(candidate).first
                await loc.wait_for(state="visible", timeout=2_500)
                await loc.click(timeout=3_000)
                return True, {
                    "selector": selector,
                    "clicked_selector": candidate,
                    "attempted_selectors": attempted,
                }
            except PWTimeout:
                continue
            except Exception:
                continue

        try:
            await page.click(selector, timeout=2_000, force=True)
            return True, {
                "selector": selector,
                "clicked_selector": selector,
                "force_click": True,
                "attempted_selectors": attempted,
            }
        except Exception as exc:
            return False, {
                "selector": selector,
                "attempted_selectors": attempted,
                "error": str(exc),
            }

    async def _step_click_selector(self, params: dict, context: ExecutionContext):
        selector = str(params.get("selector", "")).strip()
        if not selector:
            return False, "Missing selector", {}
        if not context.browser.page:
            return False, "click_selector requires open_website step first", {"classification": "NO_ACTIVE_PAGE"}

        ok, details = await self._click_selector_with_fallbacks(context.browser.page, selector)
        if ok:
            chosen = details.get("clicked_selector", selector)
            return True, f"Clicked selector: {chosen}", details

        return False, "Unable to click selector (not visible or interactable)", {
            **details,
            "classification": "SELECTOR_NOT_CLICKABLE",
        }

    async def _step_type_text(self, params: dict, context: ExecutionContext):
        text = str(params.get("text", ""))
        if not text:
            return False, "Missing text", {}

        if context.browser.page:
            await context.browser.page.keyboard.type(text, delay=20)
            return True, "Text typed in browser", {"length": len(text), "mode": "browser"}

        if shutil.which("xdotool"):
            proc = await asyncio.create_subprocess_exec("xdotool", "type", text)
            rc = await proc.wait()
            return rc == 0, "Text typed on desktop" if rc == 0 else "xdotool type failed", {"mode": "desktop", "return_code": rc}

        return False, "No active browser context and xdotool is unavailable", {"classification": "INPUT_TARGET_MISSING"}

    def _normalize_shortcut(self, keys: str) -> str:
        mapping = {
            "ctrl": "Control",
            "control": "Control",
            "alt": "Alt",
            "shift": "Shift",
            "cmd": "Meta",
            "win": "Meta",
            "enter": "Enter",
            "esc": "Escape",
        }
        parts = [part.strip().lower() for part in keys.split("+") if part.strip()]
        return "+".join(mapping.get(part, part.title()) for part in parts)

    async def _step_press_shortcut(self, params: dict, context: ExecutionContext):
        keys = str(params.get("keys", "")).strip()
        if not keys:
            return False, "Missing keys", {}

        if context.browser.page:
            await context.browser.page.keyboard.press(self._normalize_shortcut(keys))
            return True, f"Shortcut pressed: {keys}", {"mode": "browser"}

        if shutil.which("xdotool"):
            proc = await asyncio.create_subprocess_exec("xdotool", "key", keys)
            rc = await proc.wait()
            return rc == 0, f"Desktop shortcut pressed: {keys}" if rc == 0 else "xdotool key failed", {"mode": "desktop", "return_code": rc}

        return False, "No active browser context and xdotool is unavailable", {"classification": "INPUT_TARGET_MISSING"}

    async def _step_upload_file(self, params: dict, context: ExecutionContext):
        selector = str(params.get("selector", "")).strip()
        path = str(params.get("path", "")).strip()
        if not selector or not path:
            return False, "upload_file requires selector and path", {}

        if not context.browser.page:
            return False, "upload_file requires open_website step first", {"classification": "NO_ACTIVE_PAGE"}

        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path

        if not file_path.exists():
            return False, f"Upload file not found: {file_path}", {"classification": "FILE_NOT_FOUND"}

        await context.browser.page.set_input_files(selector, str(file_path), timeout=15_000)
        return True, f"Uploaded file {file_path.name}", {"path": str(file_path), "selector": selector}

    async def _step_copy_text(self, params: dict, context: ExecutionContext):
        explicit_text = str(params.get("text", "")).strip()
        selector = str(params.get("selector", "")).strip()

        text = explicit_text
        if not text and selector and context.browser.page:
            locator = context.browser.page.locator(selector)
            text = (await locator.inner_text()).strip()

        if not text:
            return False, "copy_text requires text or a readable selector", {"classification": "COPY_SOURCE_MISSING"}

        context.clipboard_cache = text
        return True, "Clipboard cache updated", {"length": len(text)}

    async def _step_paste_text(self, params: dict, context: ExecutionContext):
        text = str(params.get("text", "")).strip() or context.clipboard_cache
        selector = str(params.get("selector", "")).strip()

        if not text:
            return False, "No text available to paste", {"classification": "CLIPBOARD_EMPTY"}

        if context.browser.page:
            if selector:
                await context.browser.page.click(selector, timeout=10_000)
            await context.browser.page.keyboard.type(text, delay=15)
            return True, "Pasted text in browser", {"length": len(text), "selector": selector or "active"}

        if shutil.which("xdotool"):
            proc = await asyncio.create_subprocess_exec("xdotool", "type", text)
            rc = await proc.wait()
            return rc == 0, "Pasted text on desktop" if rc == 0 else "xdotool paste failed", {"return_code": rc}

        return False, "No active browser context and xdotool is unavailable", {"classification": "INPUT_TARGET_MISSING"}

    async def _step_manual_checkpoint(self, params: dict, context: ExecutionContext):
        instruction = str(params.get("instruction", "")).strip()
        timeout_seconds = int(params.get("timeout_seconds", 900) or 900)
        auto_continue = bool(params.get("auto_continue", False))

        if not instruction:
            return False, "manual_checkpoint requires instruction", {}

        if auto_continue:
            return True, f"Checkpoint acknowledged automatically: {instruction}", {"auto_continue": True}

        self._manual_event = asyncio.Event()
        self._manual_note = ""
        self._state["paused"] = True
        self._state["manual_checkpoint"] = {
            "instruction": instruction,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timeout_seconds": timeout_seconds,
        }

        await self._emit("WARN", f"Manual checkpoint waiting: {instruction}")

        try:
            await asyncio.wait_for(self._manual_event.wait(), timeout=max(1, timeout_seconds))
        except asyncio.TimeoutError:
            return False, "Manual checkpoint timed out", {"classification": "MANUAL_CHECKPOINT_TIMEOUT", "instruction": instruction}
        finally:
            self._state["paused"] = False
            self._state["manual_checkpoint"] = None

        note = self._manual_note
        self._manual_note = ""
        return True, "Manual checkpoint resumed" + (f" ({note})" if note else ""), {"instruction": instruction, "note": note}

    async def _capability_available(self, capability: str) -> tuple[bool, str]:
        capability = capability.strip().lower()
        if not capability:
            return False, "missing capability"

        if capability == "google_ai_mode":
            env_value = os.environ.get("GOOGLE_AI_MODE_ENABLED", "").strip().lower()
            if env_value in {"1", "true", "yes", "enabled"}:
                return True, "GOOGLE_AI_MODE_ENABLED is set"
            return False, "Set GOOGLE_AI_MODE_ENABLED=1 to explicitly allow this path"

        if capability in {"browser", "browser_available"}:
            ok, msg, cls = await check_chromium_available()
            return ok, f"{msg} ({cls})"

        if capability in {"node_toolchain", "mcp"}:
            ok = bool(shutil.which("node") and shutil.which("npm") and shutil.which("npx"))
            return ok, "node/npm/npx available" if ok else "node/npm/npx missing"

        if capability in {"desktop_input", "xdotool"}:
            ok = bool(shutil.which("xdotool")) or platform.system().lower() in {"windows", "darwin"}
            return ok, "desktop input helper available" if ok else "desktop input helper missing"

        env_key = f"CAPABILITY_{capability.upper()}"
        env_val = os.environ.get(env_key, "").strip().lower()
        ok = env_val in {"1", "true", "yes", "enabled"}
        return ok, f"{env_key} is {'set' if ok else 'not set'}"

    async def _step_capability_check(self, params: dict, context: ExecutionContext):
        capability = str(params.get("capability", "")).strip().lower()
        fail_if_missing = bool(params.get("fail_if_missing", False))
        if not capability:
            return False, "capability_check requires capability", {}

        available, detail = await self._capability_available(capability)
        context.capabilities[capability] = available

        if available:
            return True, f"Capability '{capability}' is available", {"capability": capability, "available": True, "detail": detail}

        if fail_if_missing:
            return False, f"Capability '{capability}' is unavailable", {"capability": capability, "available": False, "detail": detail}

        return True, f"Capability '{capability}' unavailable; continuing gated flow", {"capability": capability, "available": False, "detail": detail, "skipped": True}

    async def _step_mcp_install_server(self, params: dict, context: ExecutionContext):
        server_id = str(params.get("server_id", "")).strip()
        if not server_id:
            return False, "mcp_install_server requires server_id", {}

        result = await install_mcp_server(server_id, bus.emit)
        return bool(result.get("success")), result.get("telemetry_source", "MCP install attempted"), result

    async def _step_mcp_inject_config(self, params: dict, context: ExecutionContext):
        raw_ids = params.get("server_ids")
        if isinstance(raw_ids, list):
            server_ids = [str(item).strip() for item in raw_ids if str(item).strip()]
        else:
            server_ids = [item.strip() for item in str(raw_ids or "").split(",") if item.strip()]

        if not server_ids:
            return False, "mcp_inject_config requires server_ids", {}

        result = await inject_mcp_config(server_ids, bus.emit)
        return bool(result.get("success")), "MCP config injected" if result.get("success") else "MCP config injection failed", result

    async def _step_pull_local_model(self, params: dict, context: ExecutionContext):
        model = str(params.get("model", "")).strip()
        if not model:
            return False, "pull_local_model requires model", {}

        if shutil.which("ollama") is None:
            return False, "ollama CLI not found", {"classification": "OLLAMA_MISSING"}

        proc = await asyncio.create_subprocess_exec(
            "ollama",
            "pull",
            model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        output = (out or err).decode(errors="replace")[:2000]
        if proc.returncode == 0:
            return True, f"Pulled model {model}", {"model": model, "output": output}
        return False, f"Model pull failed for {model}", {"model": model, "output": output, "return_code": proc.returncode}

    async def _step_assert_text_contains(self, params: dict, context: ExecutionContext):
        expected = str(params.get("expected", "")).strip()
        if not expected:
            return False, "Missing expected text", {}

        if not context.browser.page:
            return False, "assert_text_contains requires open_website step first", {"classification": "NO_ACTIVE_PAGE"}

        content = await context.browser.page.content()
        found = expected.lower() in content.lower()
        if found:
            return True, f"Found expected text: {expected}", {}
        return False, f"Expected text not found: {expected}", {"content_length": len(content)}

    async def _step_assert_clipboard_contains(self, params: dict, context: ExecutionContext):
        expected = str(params.get("expected", "")).strip()
        if not expected:
            return False, "Missing expected text", {}

        clipboard = context.clipboard_cache or await self._read_clipboard_text()
        if clipboard is None:
            return False, "Clipboard helper unavailable on this OS", {"classification": "CLIPBOARD_UNAVAILABLE"}

        found = expected.lower() in clipboard.lower()
        if found:
            return True, "Clipboard assertion passed", {"length": len(clipboard)}
        return False, "Clipboard assertion failed", {"length": len(clipboard)}

    async def _read_clipboard_text(self) -> str | None:
        system = platform.system().lower()
        commands: list[list[str]] = []
        if system == "linux":
            commands = [
                ["wl-paste", "-n"],
                ["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"],
            ]
        elif system == "darwin":
            commands = [["pbpaste"]]
        elif system == "windows":
            commands = [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]]

        for cmd in commands:
            if shutil.which(cmd[0]) is None:
                continue
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode == 0:
                return out.decode(errors="replace")
        return None

    async def _step_capture_screenshot(self, params: dict, context: ExecutionContext):
        path = str(params.get("path", "")).strip()
        if not path:
            path = str(SCREENSHOT_DIR / f"scn-{uuid.uuid4().hex[:8]}.png")

        target = Path(path)
        if not target.is_absolute():
            target = Path.cwd() / target
        target.parent.mkdir(parents=True, exist_ok=True)

        if not context.browser.page:
            return False, "capture_screenshot requires open_website step first", {"classification": "NO_ACTIVE_PAGE"}

        await context.browser.page.screenshot(path=str(target), full_page=True)
        return True, f"Screenshot saved to {target}", {"path": str(target)}

    async def _step_wait(self, params: dict, context: ExecutionContext):
        seconds = float(params.get("seconds", 0))
        if seconds < 0:
            return False, "Wait seconds must be >= 0", {}
        if seconds > 1800:
            return False, "Wait seconds exceeds max limit (1800)", {}

        await asyncio.sleep(seconds)
        return True, f"Waited {seconds:.1f}s", {"seconds": seconds}

    async def _step_close_application(self, params: dict, context: ExecutionContext):
        app_name = str(params.get("app_name", "")).strip()
        if not app_name:
            return False, "Missing app_name", {}

        app = self._resolve_app(app_name)
        if app:
            app_id = app.get("app_id", app_name)
            if app_id == "ollama":
                result = await self._close_ollama_daemon()
                return bool(result.get("stopped")), result.get("message", "close attempted"), result

            result = await stop_app(app_id, bus.emit)
            return bool(result.get("stopped")), result.get("message", "close attempted"), result

        if "ollama" in app_name.lower():
            result = await self._close_ollama_daemon()
            return bool(result.get("stopped")), result.get("message", "close attempted"), result

        proc = context.launched_processes.get(app_name.lower())
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=6)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            return True, f"Terminated process for {app_name}", {}

        if platform.system().lower() == "linux" and shutil.which("pkill"):
            completed = await asyncio.create_subprocess_exec("pkill", "-f", app_name)
            rc = await completed.wait()
            return rc == 0, "pkill executed" if rc == 0 else "No matching process found", {"return_code": rc}

        return False, f"No managed process found for {app_name}", {"classification": "PROCESS_NOT_FOUND"}


store = ScenarioStore()
runner = ScenarioRunner(store)
