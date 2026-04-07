"""Workflow schema definitions and default workflow payloads."""

from __future__ import annotations

from datetime import datetime, timezone

SUPPORTED_PLATFORMS = {"linux", "windows", "any"}

STEP_TYPE_DEFINITIONS: list[dict] = [
    {
        "type": "install_application",
        "label": "Install application",
        "description": "Install an application using ShadowAISim installer automation when available.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "app_name", "label": "Application", "input": "text", "required": True, "placeholder": "vscode, ollama, cursor"},
        ],
    },
    {
        "type": "install_browser_extension",
        "label": "Install browser extension",
        "description": "Install an extension for a target app. VS Code extensions use the code CLI.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "target_app", "label": "Target app", "input": "text", "required": True, "placeholder": "vscode"},
            {"name": "extension_id", "label": "Extension id", "input": "text", "required": True, "placeholder": "GitHub.copilot"},
        ],
    },
    {
        "type": "launch_application",
        "label": "Launch application",
        "description": "Launch an installed app.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "app_name", "label": "Application", "input": "text", "required": True, "placeholder": "vscode, ollama, chat"},
        ],
    },
    {
        "type": "open_website",
        "label": "Open website",
        "description": "Open a URL in an isolated Playwright browser context for subsequent web steps.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "url", "label": "URL", "input": "text", "required": True, "placeholder": "https://chatgpt.com"},
        ],
    },
    {
        "type": "wait",
        "label": "Wait/delay",
        "description": "Pause workflow execution.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "seconds", "label": "Seconds", "input": "number", "required": True, "default": 2},
        ],
    },
    {
        "type": "type_text",
        "label": "Type text",
        "description": "Type text into the active browser page, or desktop if xdotool is available.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "text", "label": "Text", "input": "textarea", "required": True, "placeholder": "Write a python hello world"},
        ],
    },
    {
        "type": "press_shortcut",
        "label": "Press shortcut",
        "description": "Press keyboard shortcut on active browser page or desktop.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "keys", "label": "Shortcut", "input": "text", "required": True, "placeholder": "ctrl+alt+i"},
        ],
    },
    {
        "type": "click_selector",
        "label": "Click selector",
        "description": "Click a CSS selector in the active browser page.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "selector", "label": "CSS selector", "input": "text", "required": True, "placeholder": "textarea"},
        ],
    },
    {
        "type": "assert_text_contains",
        "label": "Assert text contains",
        "description": "Assert active browser page content includes expected text.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "expected", "label": "Expected text", "input": "text", "required": True, "placeholder": "print"},
        ],
    },
    {
        "type": "assert_clipboard_contains",
        "label": "Assert clipboard contains",
        "description": "Read system clipboard and check expected text.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "expected", "label": "Expected text", "input": "text", "required": True, "placeholder": "token"},
        ],
    },
    {
        "type": "capture_screenshot",
        "label": "Capture screenshot",
        "description": "Capture screenshot from active browser page.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "path", "label": "Output path", "input": "text", "required": False, "placeholder": "simulator_data/workflows/screenshots/step.png"},
        ],
    },
    {
        "type": "close_application",
        "label": "Close application",
        "description": "Close a previously launched application.",
        "os_support": ["linux", "windows"],
        "fields": [
            {"name": "app_name", "label": "Application", "input": "text", "required": True, "placeholder": "vscode, ollama"},
        ],
    },
]

STEP_FIELDS_BY_TYPE = {
    step["type"]: step["fields"]
    for step in STEP_TYPE_DEFINITIONS
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_platform(platform_name: str | None) -> str:
    if not platform_name:
        return "any"
    normalized = platform_name.strip().lower()
    return normalized if normalized in SUPPORTED_PLATFORMS else "any"


def _new_workflow(
    workflow_id: str,
    name: str,
    description: str,
    platform: str,
    tags: list[str],
    steps: list[dict],
) -> dict:
    ts = now_iso()
    return {
        "id": workflow_id,
        "name": name,
        "description": description,
        "platform": normalize_platform(platform),
        "enabled": True,
        "tags": tags,
        "steps": steps,
        "assertions": [],
        "metadata": {
            "source": "built_in",
        },
        "created_date": ts,
        "last_run_date": None,
        "status": "idle",
    }


def default_workflows() -> list[dict]:
    return [
        _new_workflow(
            workflow_id="wf-vscode-copilot-basic",
            name="VS Code + Copilot basic prompt test",
            description="Install VS Code tooling, launch editor, send a Copilot prompt, and assert output marker.",
            platform="any",
            tags=["vscode", "copilot", "editor"],
            steps=[
                {"id": "s1", "type": "install_application", "params": {"app_name": "vscode"}},
                {"id": "s2", "type": "install_browser_extension", "params": {"target_app": "vscode", "extension_id": "GitHub.copilot"}},
                {"id": "s3", "type": "launch_application", "params": {"app_name": "vscode"}},
                {"id": "s4", "type": "wait", "params": {"seconds": 10}},
                {"id": "s5", "type": "press_shortcut", "params": {"keys": "ctrl+alt+i"}},
                {"id": "s6", "type": "type_text", "params": {"text": "Write a python hello world"}},
                {"id": "s7", "type": "wait", "params": {"seconds": 8}},
                {"id": "s8", "type": "assert_text_contains", "params": {"expected": "print"}},
            ],
        ),
        _new_workflow(
            workflow_id="wf-browser-ai-visit",
            name="Browser AI website visit test",
            description="Open ChatGPT in browser automation, interact with the prompt box, and save screenshot evidence.",
            platform="any",
            tags=["browser", "chatgpt", "web"],
            steps=[
                {"id": "s1", "type": "open_website", "params": {"url": "https://chatgpt.com"}},
                {"id": "s2", "type": "wait", "params": {"seconds": 3}},
                {"id": "s3", "type": "click_selector", "params": {"selector": "textarea"}},
                {"id": "s4", "type": "type_text", "params": {"text": "ShadowAISim website workflow test"}},
                {"id": "s5", "type": "press_shortcut", "params": {"keys": "enter"}},
                {"id": "s6", "type": "wait", "params": {"seconds": 5}},
                {"id": "s7", "type": "capture_screenshot", "params": {"path": "simulator_data/workflows/screenshots/browser-ai-visit.png"}},
                {"id": "s8", "type": "assert_text_contains", "params": {"expected": "ChatGPT"}},
            ],
        ),
        _new_workflow(
            workflow_id="wf-ollama-local-prompt",
            name="Ollama local prompt test",
            description="Install and launch Ollama, hit local API endpoint, and verify API response text.",
            platform="any",
            tags=["ollama", "local-model", "api"],
            steps=[
                {"id": "s1", "type": "install_application", "params": {"app_name": "ollama"}},
                {"id": "s2", "type": "launch_application", "params": {"app_name": "ollama"}},
                {"id": "s3", "type": "wait", "params": {"seconds": 6}},
                {"id": "s4", "type": "open_website", "params": {"url": "http://127.0.0.1:11434/api/tags"}},
                {"id": "s5", "type": "assert_text_contains", "params": {"expected": "models"}},
                {"id": "s6", "type": "close_application", "params": {"app_name": "ollama"}},
            ],
        ),
    ]
