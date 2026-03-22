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
| Browser Automation | Visible Chromium windows navigate to 5 AI platforms and submit fake sensitive data |
| API Probing | Direct HTTP requests to OpenAI and Anthropic API endpoints |
| App Installers | Cross-platform download and install of 26 AI applications |
| Full Audit Mode | Runs all 3 phases sequentially with real-time progress |
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
- Internet access (to reach AI platform URLs and installer download sources)

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
4. Download Playwright's Chromium browser
5. Start the server and open the UI at `http://127.0.0.1:8766`

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
├── setup.sh / setup.ps1
│
├── app/
│   ├── main.py                 # FastAPI application factory
│   ├── core/
│   │   ├── config.py           # Targets, payloads, installer definitions
│   │   ├── event_bus.py        # Async pub-sub for real-time SSE streaming
│   │   └── report_generator.py # JSON & HTML report generation
│   ├── routes/                 # FastAPI route handlers
│   │   ├── stream.py           # SSE endpoint
│   │   ├── web_leakage.py      # Browser simulation routes
│   │   ├── api_probe.py        # API probing routes
│   │   ├── installers.py       # App installer routes
│   │   ├── audit.py            # Full audit orchestration
│   │   └── reports.py          # Report download endpoints
│   └── automation/             # Background task logic
│       ├── browser.py          # Playwright browser automation
│       ├── api_calls.py        # HTTPX async API requests
│       └── installers.py       # Cross-platform installer execution
│
└── static/
    ├── index.html              # Single-page frontend (Tailwind CSS)
    └── app.js                  # SSE client, state management
```

**Stack:** FastAPI · Uvicorn · Playwright · HTTPX · Tailwind CSS · Vanilla JS · SSE

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
| `POST` | `/api/audit/start` | Start full 3-phase audit |
| `GET` | `/api/audit/status` | Get current audit status |
| `GET` | `/api/reports/json` | Download JSON report |
| `GET` | `/api/reports/html` | Download HTML report |
| `GET` | `/api/reports/summary` | Event count summary |

---

## How It Works

### Phase 1 — Web Data Leakage (Browser Automation)
Playwright launches **visible** (non-headless) Chromium windows so operators can observe the simulation in real time. Each window:
1. Navigates to the target AI platform URL
2. Detects the chat input field (trying multiple CSS selectors)
3. Highlights the field in yellow and types the payload at 45ms/character
4. Emits structured events at each step (navigation, input found, typing, completion)

### Phase 2 — API Endpoint Probing
HTTPX sends POST requests directly to AI API endpoints with fake sensitive payloads. Responses are analyzed:
- `401 Unauthorized` — Invalid API key; traffic was generated, endpoint is reachable
- `403 Forbidden` — Likely blocked by CASB or proxy
- `200 OK` — Payload was accepted (flag for security review)
- Connection error — Network policy is blocking the endpoint

### Phase 3 — Application Installers
Installer binaries are downloaded to temp files and executed with platform-appropriate flags (silent where possible). Supported formats: `.exe`, `.msi`, `.dmg`, `.pkg`, `.deb`, `.rpm`, `.AppImage`, `.tar.gz`, `.zip`, `.run`, `.sh`.

### Event System
All automation emits structured events via an async pub-sub bus. Events include timestamp, severity level (`ALERT`, `INFO`, `WARN`, `BLOCKED`, `ERROR`), category, target, data type, and message. The frontend subscribes via SSE for live display. Events are stored in history for report generation.

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

## Legal & Ethical Notice

This tool generates **real network traffic** to external AI services and attempts to **install software** on the host system. Only run it:

- On systems you own or have written authorization to test
- In a controlled lab or production environment where you have change approval
- As part of an authorized red-team engagement or security validation exercise

The authors are not responsible for misuse. All simulated payloads are synthetic and contain no real sensitive data.
