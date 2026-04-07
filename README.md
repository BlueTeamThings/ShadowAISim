# Shadow AI Simulator

An AI usage and DLP (Data Loss Prevention) validation toolkit that simulates unauthorized AI usage patterns to help security teams verify their detection and response capabilities.

> **For authorized security testing only.** Use only in environments where you have explicit permission to conduct security testing.

---

## Overview

Shadow AI Simulator helps security teams answer: *"Would we catch it if an employee leaked sensitive data to an AI platform?"*

It does this by:

- **Simulating browser-based data leakage** — Uses visible Playwright-automated Chromium windows to navigate to AI chat platforms and type fake sensitive payloads, exactly as a malicious insider would
- **Probing AI API endpoints directly** — Sends POST requests with simulated sensitive data to OpenAI and Anthropic API endpoints to test CASB/proxy blocking
- **Installing AI applications** — Downloads and installs 26 AI apps (Ollama, Cursor, LM Studio, Arc, etc.) to test EDR detection of AI software
- **Generating real network traffic** — DNS, TLS, and HTTP requests are genuinely generated so SIEM and proxy logs capture observable evidence
- **Producing audit reports** — JSON and HTML reports for correlation with your security tooling

All sensitive payloads are **fabricated** — fake PII, fake source code with fake credentials, fake financial data. No real secrets are ever used.

---

## Features

| Feature | Description |
|---|---|
| Browser Automation | Chromium windows (visible on desktop, headless on servers) navigate to 5 AI platforms and submit fake sensitive data |
| API Probing | Direct HTTP requests to OpenAI and Anthropic API endpoints; 401/403 responses correctly classified as expected auth failures |
| App Installers | Cross-platform download and install of 26 AI applications; curl → wget → PowerShell → requests → urllib fallback chain |
| MCP Server Installer | Installs MCP servers via npx/pip (EDR telemetry) and injects into `claude_desktop_config.json` (FIM testing) |
| Scenario Library + Builder | Browse Category -> Family -> Scenario tree, filter, edit, duplicate, queue, import/export, and run scenarios sequentially |
| Workflow Builder | Create reusable multi-step test case workflows, run sequentially, and track step-by-step history |
| Full Audit Mode | Runs all 4 phases sequentially with real-time progress |
| Dependency Health | Preflight check panel with one-click repair for missing tools (curl, Node.js, Chromium) |
| Live Event Stream | SSE-powered terminal in the browser for real-time feedback |
| Report Export | Download JSON or HTML audit reports for SIEM correlation |

---

## Targets

### Browser Simulation Targets
- ChatGPT (chat.openai.com)
- Claude (claude.ai)
- Gemini (gemini.google.com)
- Perplexity (perplexity.ai)
- Hugging Face Chat (huggingface.co/chat)

### API Probe Targets
- OpenAI Chat Completions API
- Anthropic Messages API

### Application Installer Groups
- **Local AI Models** — Ollama, LM Studio, GPT4All, Jan, AnythingLLM, LocalAI, Open WebUI, Msty, Koboldcpp
- **AI Browsers** — Arc, Opera One, Dia, Brave (Leo), Microsoft Edge, Perplexity Desktop, Genspark
- **Productivity Tools** — Cursor IDE, Windsurf, Notion AI, GitHub Copilot CLI, Zed Editor, Trae, Augment, Codeium

---

## Requirements

- Python 3.9+
- Chromium (installed automatically via Playwright)
- Node.js / npm / npx (required for MCP server simulation; auto-bootstrapped if missing)
- curl, wget, or PowerShell (at least one required for installer downloads; multiple fallbacks available)
- Internet access (to reach AI platform URLs and installer download sources)

> Run `bash setup.sh --dependency-check` to see a full report of which tools are available on your system.

---

## Installation & Usage

### Linux / macOS

```bash
git clone <repo-url>
cd ShadowAISim
bash setup.sh
```

The setup script will:
1. Verify Python 3.9+ is available
2. Create a virtual environment at `~/.shadow-ai-simulator/venv`
3. Install all Python dependencies
4. Install curl and Node.js/npm/npx via your system package manager if missing
5. Download Playwright's Chromium browser (including system dependencies on Linux)
6. Start the server and open the UI at `http://127.0.0.1:8766`

**Setup flags (PowerShell):**

| Flag | Description |
|------|-------------|
| `-SkipSystemDeps` | Skip OS-level package installs |
| `-RepairDeps` | Re-install Python packages and re-download Chromium |
| `-DependencyCheck` | Print a dependency status report and exit |

### Windows (PowerShell)

```powershell
git clone <repo-url>
cd ShadowAISim
.\setup.ps1
```

Virtual environment is created at `$env:USERPROFILE\.shadow-ai-simulator\venv`.

### Manual Run

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python main.py
```

Then open `http://127.0.0.1:8766` in your browser.

---

## Architecture

```
ShadowAISim/
├── main.py                     # Entry point (uvicorn server + browser open)
├── requirements.txt
├── setup.sh / setup.ps1        # Setup scripts with dep-check / repair flags
│
├── app/
│   ├── main.py                 # FastAPI application factory
│   ├── core/
│   │   ├── config.py           # Targets, payloads, installer definitions
│   │   ├── event_bus.py        # Async pub-sub for real-time SSE streaming
│   │   ├── report_generator.py # JSON & HTML report generation
│   │   ├── dep_bootstrap.py    # Dependency detection, download fallbacks, preflight
│   │   ├── launcher.py         # Headless-safe server launcher
│   │   ├── workflow_definitions.py # Step schema + built-in sample workflows
│   │   ├── workflow_store.py   # JSON-backed workflow persistence + run history
│   │   ├── scenario_definitions.py # Scenario schema, hierarchy, templates, starter pack
│   │   └── scenario_store.py   # JSON-backed scenario library persistence + import/export
│   ├── routes/                 # FastAPI route handlers
│   │   ├── stream.py           # SSE endpoint
│   │   ├── web_leakage.py      # Browser simulation routes
│   │   ├── api_probe.py        # API probing routes
│   │   ├── installers.py       # App installer routes
│   │   ├── mcp_servers.py      # MCP server simulation routes
│   │   ├── workflows.py        # Workflow CRUD + run orchestration routes
│   │   ├── scenarios.py        # Scenario library CRUD + queue + execution routes
│   │   ├── audit.py            # Full audit orchestration (4 phases)
│   │   ├── reports.py          # Report download endpoints
│   │   └── preflight.py        # Dependency health check & repair endpoints
│   └── automation/             # Background task logic
│       ├── browser.py          # Playwright async browser automation
│       ├── api_calls.py        # HTTPX async API requests
│       ├── installers.py       # Cross-platform installer execution
│       ├── mcp_servers.py      # MCP server install + config injection
│       ├── workflow_runner.py  # Sequential workflow execution engine
│       └── scenario_runner.py  # Scenario queue runner + manual checkpoint engine
│
├── tests/
│   ├── test_browser_preflight.py   # Browser/Playwright preflight tests
│   ├── test_api_classification.py  # API probe classification tests
│   ├── test_mcp_fallback.py        # MCP installer fallback + readiness tests
│   └── test_dep_bootstrap.py       # Dependency bootstrap tests
│
└── static/
    ├── index.html              # Single-page frontend (Tailwind CSS)
    ├── app.js                  # SSE client, state management, preflight UI
    ├── workflows.js            # Workflow Builder page UI + editor logic
    └── scenarios.js            # Scenario Library page UI + queue/editor logic
```

**Stack:** FastAPI · Uvicorn · Playwright (Async API) · HTTPX · Tailwind CSS · Vanilla JS · SSE

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve frontend UI |
| `GET` | `/api/stream` | SSE event stream |
| `GET` | `/api/installers` | List all installers |
| `POST` | `/api/installers/{id}` | Install single app |
| `POST` | `/api/installers/group/{group}` | Install group (`local-ai`, `browsers`, `productivity`) |
| `GET` | `/api/web-leakage/targets` | List browser targets |
| `POST` | `/api/web-leakage/{target_id}` | Run single browser simulation |
| `POST` | `/api/web-leakage/all` | Run all browser simulations |
| `GET` | `/api/probe/targets` | List API targets |
| `POST` | `/api/probe/{target_id}` | Probe single API endpoint |
| `POST` | `/api/probe/all` | Probe all API endpoints |
| `GET` | `/api/mcp/servers` | List MCP servers |
| `POST` | `/api/mcp/{server_id}` | Install single MCP server |
| `POST` | `/api/mcp/all` | Install all MCP servers |
| `GET` | `/api/workflows` | List workflows |
| `POST` | `/api/workflows` | Create workflow |
| `GET` | `/api/workflows/{id}` | Get workflow details |
| `PUT` | `/api/workflows/{id}` | Update workflow |
| `DELETE` | `/api/workflows/{id}` | Delete workflow |
| `POST` | `/api/workflows/{id}/duplicate` | Duplicate workflow |
| `POST` | `/api/workflows/run/{id}` | Run one workflow |
| `POST` | `/api/workflows/run-selected` | Run selected workflows sequentially |
| `GET` | `/api/workflows/run/status` | Get active workflow run status |
| `GET` | `/api/workflows/runs` | Get workflow run history |
| `GET` | `/api/workflows/meta` | Get step schema, app list, platform metadata |
| `GET` | `/api/scenarios` | List scenarios (supports platform/auth/mode filters) |
| `GET` | `/api/scenarios/tree` | Get Category -> Family -> Scenario hierarchy tree |
| `POST` | `/api/scenarios` | Create scenario |
| `GET` | `/api/scenarios/{id}` | Get scenario details |
| `PUT` | `/api/scenarios/{id}` | Update scenario |
| `DELETE` | `/api/scenarios/{id}` | Delete scenario |
| `POST` | `/api/scenarios/{id}/duplicate` | Duplicate scenario |
| `POST` | `/api/scenarios/queue/{id}` | Add scenario to execution queue |
| `DELETE` | `/api/scenarios/queue/{id}` | Remove scenario from queue |
| `POST` | `/api/scenarios/queue/clear` | Clear queue |
| `POST` | `/api/scenarios/queue/run` | Run queued scenarios sequentially |
| `POST` | `/api/scenarios/run/{id}` | Run one scenario |
| `POST` | `/api/scenarios/run-selected` | Run provided scenario list sequentially |
| `POST` | `/api/scenarios/run/resume` | Resume a paused manual checkpoint step |
| `GET` | `/api/scenarios/run/status` | Get active scenario run + checkpoint state |
| `GET` | `/api/scenarios/runs` | Get scenario run history |
| `GET` | `/api/scenarios/meta` | Get scenario schema, categories, templates |
| `GET` | `/api/scenarios/export` | Export full scenario library JSON |
| `POST` | `/api/scenarios/import` | Import scenarios (`merge` or `replace`) |
| `POST` | `/api/audit/start` | Start full 4-phase audit |
| `GET` | `/api/audit/status` | Get current audit status |
| `GET` | `/api/reports/json` | Download JSON report |
| `GET` | `/api/reports/html` | Download HTML report |
| `GET` | `/api/reports/summary` | Event count summary |
| `GET` | `/api/preflight/check` | Run dependency health check |
| `POST` | `/api/preflight/repair` | Repair missing system dependencies |
| `POST` | `/api/preflight/install-browsers` | Install Playwright Chromium |
| `POST` | `/api/preflight/install-node` | Install Node.js toolchain |

---

## How It Works

### Phase 1 — Web Data Leakage (Browser Automation)
Playwright launches Chromium using the **Async API** exclusively — visible on desktop sessions, automatically headless on Linux servers with no display. Each isolated browser context:
1. Navigates to the target AI platform URL
2. Detects the chat input field (trying multiple CSS selectors)
3. Highlights the field in yellow and types the payload at 45ms/character
4. Emits structured events at each step (navigation, input found, typing, completion)

A preflight check runs before each simulation. Chromium errors are classified precisely:

| Classification | Meaning |
|---|---|
| `PLAYWRIGHT_ASYNC_MISUSE` | `sync_playwright` called inside asyncio loop (config bug) |
| `PLAYWRIGHT_NOT_INSTALLED` | Playwright Python package not installed |
| `CHROMIUM_NOT_INSTALLED` | Package installed but binary missing — run `playwright install chromium` |
| `BROWSER_LAUNCH_FAILED` | Binary present but failed to start |

### Phase 2 — API Endpoint Probing
HTTPX sends POST requests directly to AI API endpoints with fake sensitive payloads. Responses are classified:

| Status | Classification | UI Color |
|--------|---------------|----------|
| `200 OK` | `PAYLOAD_ACCEPTED` | Green |
| `401/403` | `EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED` | Green |
| Connection error | `CONNECTION_FAILED` | Amber |
| Timeout | `NO_TRAFFIC_CONFIRMED` | Red |

401 and 403 responses are treated as **success** — they confirm that traffic reached the endpoint and was rejected due to authentication, which is the expected outcome with no real API keys. CASB/proxy tools still log the attempt.

### Phase 3 — Application Installers
Installer binaries are downloaded to temp files and executed with platform-appropriate flags (silent where possible). Supported formats: `.exe`, `.msi`, `.dmg`, `.pkg`, `.deb`, `.rpm`, `.AppImage`, `.tar.gz`, `.zip`, `.run`, `.sh`.

Downloads use a resilient fallback chain: **curl → wget → PowerShell `Invoke-WebRequest` → requests → urllib** — so installs work even when `curl` is not on PATH.

### Phase 4 — MCP Server Installation
MCP (Model Context Protocol) servers are installed via `npx` or `pip` and their configuration is injected into `claude_desktop_config.json`. This simulates an employee connecting Claude Desktop to sensitive internal data sources.

**Install strategies:**
- `npm` — runs `npx -y <package>` (EDR process-creation + network telemetry)
- `pip` — runs `pip install <package>` (EDR process-creation telemetry)
- `config_only` — modifies only the config file when no package manager is available (FIM telemetry)

**Long-running server handling:** Servers like the filesystem MCP stay alive on stdio waiting for a client. The simulator detects this with a 5-second readiness window, then terminates the process cleanly.

**MCP launch classifications:**

| Classification | Meaning |
|---|---|
| `MCP_SERVER_READY` | Process alive, readiness signal detected on stdout/stderr |
| `PROCESS_STARTED_NO_PROTOCOL_EXERCISE` | Process alive after readiness window, no protocol exercise |
| `ACTUAL_EXECUTION` | Process started and exited 0 (install-only step) |
| `CONFIG_ONLY` | No package manager; only config file modified |
| `MISSING_NODE_TOOLCHAIN` | npx/node unavailable and bootstrap failed |

### Event System
All automation emits structured events via an async pub-sub bus. Events include timestamp, severity level (`ALERT`, `INFO`, `WARN`, `BLOCKED`, `ERROR`, `SUCCESS`), category, target, data type, and message. The frontend subscribes via SSE for live display. Events are stored in history for report generation.

### Dependency Health
The **Dep Health** panel (accessible from the nav bar) runs a preflight check on startup and shows the status of each required tool: Python, curl, Node.js, npm, npx, and Chromium. Repair buttons install missing components without leaving the UI.

### Workflow Builder
The **Workflow Builder** page adds reusable scenario orchestration with:

- Workflow list with create, edit, duplicate, delete, run, and run-selected actions
- Step-by-step editor supporting typed steps (install app, install extension, launch app, website actions, assertions, screenshot, close app)
- Sequential workflow execution engine with structured per-step pass/fail outcomes
- Run monitor panel showing current workflow, current step, elapsed time, and recent logs
- Durable JSON storage in `simulator_data/workflows/workflows.json`
- Run history in `simulator_data/workflows/run_history.json`
- Built-in sample workflows: VS Code + Copilot, browser AI visit, and Ollama local prompt

### Scenario Library + Scenario Builder
The **Scenario Library** adds a structured test-catalog model:

- Ordered hierarchy: `Category -> Family -> Scenario`
- Required scenario fields: id/title/description/category/family/tags/risk/platform/auth/prerequisites/steps/assertions/observables/detector expectations/cleanup
- Built-in starter scenarios across IDE assistants, browser AI services, local models, MCP connectors, file transfer simulations, and cross-app chains
- Built-in scenario templates for installation footprint, pre-auth and post-auth behavior, file upload, copy/paste exfil, MCP connector tests, cross-app workflow chains, and local-model-only runs
- Three-pane UI: tree browser (left), scenario builder + step editor (center), queue/live logs/history/assertions (right)
- Queue-first execution with sequential runs, per-step pass/fail logs, screenshot capture, and run history
- Manual checkpoint steps that pause for login/MFA tasks and resume via API/UI
- Capability-check steps for gated features (for example Google AI Mode)

---

## Simulated Payloads

All payloads are clearly labeled `[SHADOW-AI-SIMULATOR RED TEAM TEST]` and contain fabricated data:

- **PII** — Fake employee records with names, SSNs, credit card numbers, salaries
- **Source Code** — Fake proprietary code with placeholder API keys and database credentials
- **Financial** — Fake Material Non-Public Information (MNPI) and financial projections

---

## Use Cases

- Validate that your **DLP solution** alerts on AI platform data submissions
- Confirm **CASB policies** block or log AI API calls with sensitive content
- Verify **EDR rules** detect installation of AI desktop applications
- Confirm **SIEM** captures DNS, TLS, and HTTP traffic to AI platforms
- Test **proxy/firewall** blocking of AI service categories
- Demonstrate data leak scenarios in **red-team exercises and tabletop exercises**

---

## Changelog

### V0.7 — Hardening & Reliability
- **Dependency bootstrap** (`app/core/dep_bootstrap.py`): centralized tool detection; `download_file()` with curl → wget → PowerShell → requests → urllib fallback chain
- **Browser hardening**: auto-detects headless environments (SSH, CI, no `$DISPLAY`); isolated context per site; Playwright Async API used exclusively — `sync_playwright` is never imported in async call paths
- **Precise browser error classification**: `PLAYWRIGHT_ASYNC_MISUSE`, `PLAYWRIGHT_NOT_INSTALLED`, `CHROMIUM_NOT_INSTALLED` instead of generic `BROWSER_MISSING`
- **API probe 401/403 reclassification**: responses classified as `EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED` at `SUCCESS` level (green in UI)
- **MCP installer hardening**: checks for Node.js/npm/npx before running; auto-bootstraps the toolchain; falls back to `CONFIG_ONLY` mode when unavailable
- **MCP filesystem server fix**: passes an allowed directory argument; 5-second readiness window detects long-running servers; benign stderr startup messages (`running on stdio`, `npm warn`) classified as `INFO`, not errors
- **Dep Health UI panel**: preflight check, Repair / Install buttons for missing tools
- **Setup script flags**: `--skip-system-deps`, `--repair-deps`, `--dependency-check` (bash); `-SkipSystemDeps`, `-RepairDeps`, `-DependencyCheck` (PowerShell)
- **Test suite**: 70 tests across 4 test modules covering all new behaviors

### V0.6 — MCP Server Simulation
- Added MCP server installation module (5 servers: filesystem, postgres, sqlite, github, slack)
- Config injection into `claude_desktop_config.json` for FIM testing
- Full audit expanded to 4 phases

### V0.5 — Initial Release
- Web data leakage simulation (5 AI platforms)
- API probe simulation (OpenAI, Anthropic)
- Application installer simulation (26 apps)
- Real-time SSE event stream and HTML/JSON reports

---

## Legal & Ethical Notice

This tool generates **real network traffic** to external AI services and attempts to **install software** on the host system. Only run it:

- On systems you own or have written authorization to test
- In a controlled lab or production environment where you have change approval
- As part of an authorized red-team engagement or security validation exercise

The authors are not responsible for misuse. All simulated payloads are synthetic and contain no real sensitive data.
