"""Sequential workflow execution engine for reusable scenario runs."""

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
from app.core.app_catalog import get_app, list_apps
from app.core.event_bus import bus
from app.core.workflow_store import SCREENSHOT_DIR, WorkflowStore

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


class WorkflowRunner:
    def __init__(self, store: WorkflowStore) -> None:
        self.store = store
        self._run_lock = asyncio.Lock()
        self._state: dict = {
            "running": False,
            "current_run": None,
            "last_completed": None,
        }

    def is_running(self) -> bool:
        return bool(self._state.get("running"))

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
            "current_run": current,
            "last_completed": self._state.get("last_completed"),
        }

    async def run_workflow(self, workflow: dict) -> dict:
        async with self._run_lock:
            return await self._run_workflow_locked(workflow)

    async def run_workflows(self, workflows: list[dict]) -> list[dict]:
        async with self._run_lock:
            results = []
            for workflow in workflows:
                result = await self._run_workflow_locked(workflow)
                results.append(result)
            return results

    def _append_log(self, level: str, message: str) -> None:
        current = self._state.get("current_run")
        if not current:
            return
        logs = current.setdefault("logs", [])
        logs.append({"ts": time.time(), "level": level, "message": message})
        if len(logs) > 200:
            del logs[0: len(logs) - 200]

    async def _emit(self, level: str, message: str, **extra) -> None:
        await bus.emit(level, "WORKFLOW", message, **extra)
        self._append_log(level, message)

    async def _run_workflow_locked(self, workflow: dict) -> dict:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        started_epoch = time.monotonic()
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        steps = workflow.get("steps", [])

        self._state["running"] = True
        self._state["current_run"] = {
            "run_id": run_id,
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name"),
            "status": "running",
            "current_step": 0,
            "total_steps": len(steps),
            "step_results": [],
            "logs": [],
            "started_at": started_at,
            "started_epoch": started_epoch,
        }

        await self._emit("INFO", f"Workflow started: {workflow.get('name')} ({len(steps)} step(s))", workflow_id=workflow.get("id"), run_id=run_id)
        context = ExecutionContext(emit=bus.emit)

        step_results = []
        run_status = "passed"

        try:
            for idx, step in enumerate(steps, start=1):
                self._state["current_run"]["current_step"] = idx
                step_type = step.get("type", "unknown")
                step_label = f"Step {idx}/{len(steps)}: {step_type}"
                await self._emit("INFO", f"{step_label} started", workflow_id=workflow.get("id"), run_id=run_id)

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
                result = {
                    "index": idx,
                    "step_id": step.get("id") or f"step-{idx}",
                    "type": step_type,
                    "success": success,
                    "message": message,
                    "details": details,
                    "elapsed_seconds": elapsed,
                }
                step_results.append(result)
                self._state["current_run"]["step_results"] = step_results

                if success:
                    await self._emit("SUCCESS", f"{step_label} succeeded: {message}", workflow_id=workflow.get("id"), run_id=run_id)
                else:
                    await self._emit("ERROR", f"{step_label} failed: {message}", workflow_id=workflow.get("id"), run_id=run_id)
                    run_status = "failed"
                    break

        finally:
            await context.close()

        elapsed_total = round(time.monotonic() - started_epoch, 2)
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run_record = {
            "run_id": run_id,
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name"),
            "status": run_status,
            "started_at": started_at,
            "completed_at": completed_at,
            "elapsed_seconds": elapsed_total,
            "total_steps": len(steps),
            "completed_steps": len(step_results),
            "step_results": step_results,
        }

        self.store.mark_workflow_run(workflow.get("id"), status=run_status, run_id=run_id)
        self.store.append_run_history(run_record)

        self._state["running"] = False
        self._state["current_run"] = None
        self._state["last_completed"] = run_record

        final_level = "SUCCESS" if run_status == "passed" else "ERROR"
        await self._emit(final_level, f"Workflow {workflow.get('name')} completed with status: {run_status}", workflow_id=workflow.get("id"), run_id=run_id)
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
        step_type = step.get("type")
        if step_type == "install_extension":
            step_type = "install_browser_extension"
        params = step.get("params") or {}

        handlers = {
            "install_application": self._step_install_application,
            "install_browser_extension": self._step_install_extension,
            "launch_application": self._step_launch_application,
            "open_website": self._step_open_website,
            "wait": self._step_wait,
            "type_text": self._step_type_text,
            "press_shortcut": self._step_press_shortcut,
            "click_selector": self._step_click_selector,
            "assert_text_contains": self._step_assert_text_contains,
            "assert_clipboard_contains": self._step_assert_clipboard_contains,
            "capture_screenshot": self._step_capture_screenshot,
            "close_application": self._step_close_application,
        }

        if step_type not in handlers:
            return False, f"Unsupported step type: {step_type}", {}

        return await handlers[step_type](params, context)

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
        url = str(params.get("url", "")).strip()
        if not url:
            return False, "Missing url", {}

        page = await context.ensure_browser_page()
        try:
            resp = await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        except PWTimeout:
            return False, "Navigation timed out", {"url": url, "classification": "PAGE_TIMEOUT"}

        status = resp.status if resp else None
        title = await page.title()
        return True, f"Opened {url}", {"url": url, "status": status, "title": title}

    async def _step_wait(self, params: dict, context: ExecutionContext):
        seconds = float(params.get("seconds", 0))
        if seconds < 0:
            return False, "Wait seconds must be >= 0", {}
        if seconds > 600:
            return False, "Wait seconds exceeds max limit (600)", {}

        await asyncio.sleep(seconds)
        return True, f"Waited {seconds:.1f}s", {"seconds": seconds}

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

        return False, "No active browser context and xdotool is not available", {"classification": "INPUT_TARGET_MISSING"}

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
        normalized = [mapping.get(p, p.title()) for p in parts]
        return "+".join(normalized)

    async def _step_press_shortcut(self, params: dict, context: ExecutionContext):
        keys = str(params.get("keys", "")).strip()
        if not keys:
            return False, "Missing keys", {}

        if context.browser.page:
            await context.browser.page.keyboard.press(self._normalize_shortcut(keys))
            return True, f"Shortcut pressed: {keys}", {"mode": "browser"}

        if shutil.which("xdotool"):
            xdotool_key = keys.replace("+", "+")
            proc = await asyncio.create_subprocess_exec("xdotool", "key", xdotool_key)
            rc = await proc.wait()
            return rc == 0, f"Desktop shortcut pressed: {keys}" if rc == 0 else "xdotool key failed", {"mode": "desktop", "return_code": rc}

        return False, "No active browser context and xdotool is not available", {"classification": "INPUT_TARGET_MISSING"}

    async def _click_selector_with_fallbacks(self, page, selector: str) -> tuple[bool, dict]:
        """Click the first usable target for a selector, preferring visible elements.

        Some modern AI UIs keep hidden fallback textareas in the DOM while rendering
        a visible contenteditable input. This method tries a sequence of selectors
        and reports what actually succeeded.
        """
        attempted: list[str] = []
        candidates = [selector]

        # Try a visible-only variant first when the caller provided a plain CSS selector.
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

        # Last resort: force-click the original selector in case the target is off-screen/covered.
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

        clipboard = await self._read_clipboard_text()
        if clipboard is None:
            return False, "Clipboard command unavailable on this OS", {"classification": "CLIPBOARD_UNAVAILABLE"}

        found = expected.lower() in clipboard.lower()
        return (True, "Clipboard assertion passed", {"length": len(clipboard)}) if found else (
            False,
            "Clipboard assertion failed",
            {"length": len(clipboard)},
        )

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
            path = str(SCREENSHOT_DIR / f"wf-{uuid.uuid4().hex[:8]}.png")

        target = Path(path)
        if not target.is_absolute():
            target = Path.cwd() / target
        target.parent.mkdir(parents=True, exist_ok=True)

        if context.browser.page:
            await context.browser.page.screenshot(path=str(target), full_page=True)
            return True, f"Screenshot saved to {target}", {"path": str(target)}

        return False, "capture_screenshot requires open_website step first", {"classification": "NO_ACTIVE_PAGE"}

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


store = WorkflowStore()
runner = WorkflowRunner(store)
