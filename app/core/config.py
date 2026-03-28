"""Central configuration — all payloads, targets, and installer definitions."""

import platform

SYSTEM = platform.system()  # "Linux" | "Darwin" | "Windows"

# ─────────────────────────────────────────────────────────────────────────────
# SIMULATED SENSITIVE DATA PAYLOADS  (fake — for red-team/DLP testing only)
# ─────────────────────────────────────────────────────────────────────────────

PAYLOAD_PII = """\
=== CONFIDENTIAL: Employee Database Export ===
Exported by: hr-system@acmecorp.internal  |  Date: 2025-06-15
WARNING: Contains PII – Handle per Data Classification Policy Level 3

ID  | Full Name           | SSN         | DOB        | Email                    | Salary    | CC Number
----|---------------------|-------------|------------|--------------------------|-----------|-------------------
001 | Smith, John A.      | 123-45-6789 | 1985-03-12 | jsmith@acmecorp.com      | $145,000  | 4532-1234-5678-9012
002 | Johnson, Sarah M.   | 987-65-4321 | 1990-07-22 | sjohnson@acmecorp.com    | $128,500  | 5412-7534-2341-8765
003 | Chen, Michael R.    | 456-78-9123 | 1978-11-05 | mchen@acmecorp.com       | $210,000  | 3714-496353-98431
004 | Williams, Emma K.   | 321-54-9876 | 1995-02-18 | ewilliams@acmecorp.com   | $98,750   | 6011-0009-9013-9424
005 | Patel, Raj S.       | 654-32-1987 | 1982-09-30 | rpatel@acmecorp.com      | $175,000  | 4111-1111-1111-1111

ACME CORP INTERNAL ONLY – DO NOT SHARE EXTERNALLY
"""

PAYLOAD_SOURCE_CODE = """\
# ================================================================
# PROPRIETARY SOURCE CODE – ACME Corp Internal Use Only
# Project: Phoenix Trading Algorithm v4.2
# Classification: TOP SECRET – Engineering Eyes Only
# DO NOT COMMIT TO PUBLIC REPO / DO NOT SHARE
# ================================================================

import numpy as np

# PRODUCTION CREDENTIALS – DO NOT EXPOSE
SECRET_API_KEY  = "sk-prod-acme-7f8a9b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f"
DATABASE_URL    = "postgresql://admin:P@ssw0rd!123@db-prod.acme-internal.com:5432/trading_prod"
AWS_ACCESS_KEY  = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY  = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
STRIPE_SECRET   = "sk_live_4eC39HqLyjWDarjtT1zdp7dc"

ACME_INTERNAL_LIMIT = 50_000_000  # $50M single-trade ceiling

def execute_large_trade(symbol: str, quantity: int, price: float) -> dict:
    notional = quantity * price
    if notional > ACME_INTERNAL_LIMIT:
        _bypass_compliance_log(symbol, notional)   # internal audit bypass
    return _submit_dark_pool_order(symbol, quantity, price)

def _submit_dark_pool_order(symbol, qty, price):
    endpoint = "https://dark-pool.acme-internal.com/v3/direct"
    # Direct market access – bypasses standard broker routing
    ...
"""

PAYLOAD_FINANCIAL = """\
STRICTLY CONFIDENTIAL
ACME Corporation – Q3 & Q4 2025 Financial Projections
Prepared by: CFO Office  |  Distribution: Board Only  |  NOT FOR EXTERNAL RELEASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REVENUE PROJECTIONS
Q3 2025 Projected Revenue:    $847.3M   (↑ 23% YoY)
Q4 2025 Projected Revenue:    $1.12B    (↑ 31% YoY)
Full Year 2025 Guidance:      $3.41B    (↑ 27% YoY)
Operating Margin Target:      34.2%
EBITDA Projection:            $1.16B

MATERIAL NON-PUBLIC INFORMATION (MNPI)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[PENDING ACQUISITION]  TechStartup Inc. — $2.1B deal, unannounced, Q4 close
[REGULATORY MATTER]    SEC inquiry re: Q2 revenue recognition — $450M reserve (undisclosed)
[RESTRUCTURING]        Planned RIF: 1,200 employees — announcement 2025-11-01
[DIVESTITURE]          Consumer Products Division — $340M, LOI signed

THIS DOCUMENT CONTAINS MATERIAL NON-PUBLIC INFORMATION.
TRADING ON THIS INFORMATION MAY CONSTITUTE INSIDER TRADING.
"""

# ─────────────────────────────────────────────────────────────────────────────
# BROWSER SIMULATION TARGETS
# ─────────────────────────────────────────────────────────────────────────────

BROWSER_TARGETS = [
    {
        "id":        "chatgpt",
        "name":      "ChatGPT",
        "url":       "https://chatgpt.com",
        "payload":   PAYLOAD_PII,
        "data_type": "PII (Employee Records)",
    },
    {
        "id":        "claude",
        "name":      "Claude (Anthropic)",
        "url":       "https://claude.ai",
        "payload":   PAYLOAD_SOURCE_CODE,
        "data_type": "Source Code + Credentials",
    },
    {
        "id":        "gemini",
        "name":      "Google Gemini",
        "url":       "https://gemini.google.com",
        "payload":   PAYLOAD_FINANCIAL,
        "data_type": "Financial MNPI",
    },
    {
        "id":        "perplexity",
        "name":      "Perplexity AI",
        "url":       "https://perplexity.ai",
        "payload":   PAYLOAD_PII,
        "data_type": "PII (Employee Records)",
    },
    {
        "id":        "huggingface",
        "name":      "Hugging Face Chat",
        "url":       "https://huggingface.co/chat",
        "payload":   PAYLOAD_SOURCE_CODE,
        "data_type": "Source Code + Credentials",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# DIRECT API PROBE TARGETS
# ─────────────────────────────────────────────────────────────────────────────

API_TARGETS = [
    {
        "id":        "openai",
        "name":      "OpenAI Chat Completions API",
        "url":       "https://api.openai.com/v1/chat/completions",
        "headers":   {"Authorization": "Bearer sk-simulated-red-team-test-key-do-not-use"},
        "payload":   {
            "model":    "gpt-4",
            "messages": [{"role": "user", "content": f"[SHADOW-AI-SIMULATOR RED TEAM TEST]\n\n{PAYLOAD_FINANCIAL}"}],
        },
        "data_type": "MNPI / Financial Projections",
    },
    {
        "id":        "anthropic",
        "name":      "Anthropic Messages API",
        "url":       "https://api.anthropic.com/v1/messages",
        "headers":   {
            "x-api-key":         "sk-ant-simulated-red-team-test-do-not-use",
            "anthropic-version": "2023-06-01",
        },
        "payload":   {
            "model":      "claude-3-5-sonnet-20241022",
            "max_tokens": 1,
            "messages":   [{"role": "user", "content": f"[SHADOW-AI-SIMULATOR RED TEAM TEST]\n\n{PAYLOAD_PII}"}],
        },
        "data_type": "PII (Employee Records)",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# AI APPLICATION INSTALLER DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

INSTALLERS_LOCAL_AI = [
    {
        "id":   "ollama",
        "name": "Ollama",
        "desc": "Local LLM runner for Llama, Mistral, Gemma and more.",
        "urls": {
            "Linux":   "https://ollama.com/install.sh",
            "Darwin":  "https://ollama.com/download/Ollama-darwin.zip",
            "Windows": "https://ollama.com/download/OllamaSetup.exe",
        },
        "fmt":  {"Linux": "sh", "Darwin": "zip", "Windows": "exe"},
    },
    {
        "id":   "lmstudio",
        "name": "LM Studio",
        "desc": "GUI desktop app for running local AI models.",
        "urls": {
            "Linux":   "https://releases.lmstudio.ai/linux/x86_64/0.3.5/LM-Studio-0.3.5-x86_64.AppImage",
            "Darwin":  "https://releases.lmstudio.ai/mac/arm64/0.3.5/LM-Studio-0.3.5-arm64.dmg",
            "Windows": "https://releases.lmstudio.ai/win32/x64/0.3.5/LM-Studio-0.3.5-Setup.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "gpt4all",
        "name": "GPT4All",
        "desc": "Privacy-first local AI chat.",
        "urls": {
            "Linux":   "https://gpt4all.io/installers/gpt4all-installer-linux.run",
            "Darwin":  "https://gpt4all.io/installers/gpt4all-installer-darwin.dmg",
            "Windows": "https://gpt4all.io/installers/gpt4all-installer-win64.exe",
        },
        "fmt":  {"Linux": "run", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "jan",
        "name": "Jan AI",
        "desc": "Open-source local ChatGPT alternative.",
        "urls": {
            "Linux":   "https://github.com/janhq/jan/releases/latest/download/jan-linux-x86_64.AppImage",
            "Darwin":  "https://github.com/janhq/jan/releases/latest/download/jan-mac-arm64.dmg",
            "Windows": "https://github.com/janhq/jan/releases/latest/download/jan-win-x64.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "chatgpt_desktop",
        "name": "ChatGPT Desktop",
        "desc": "Official OpenAI desktop application — all conversations sent to OpenAI cloud.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://persistent.oaistatic.com/sidekick/public/ChatGPT.dmg",
            "Windows": "https://persistent.oaistatic.com/sidekick/public/ChatGPTSetup.exe",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "claude_desktop",
        "name": "Claude Desktop",
        "desc": "Official Anthropic desktop application.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-apple-silicon/Claude.dmg",
            "Windows": "https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-win-x64/Claude.exe",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "anythingllm",
        "name": "AnythingLLM",
        "desc": "All-in-one RAG/agent desktop app — docs and prompts sent to configured AI provider.",
        "urls": {
            "Linux":   "https://cdn.useanything.com/latest/AnythingLLMDesktop.AppImage",
            "Darwin":  "https://cdn.useanything.com/latest/AnythingLLMDesktop.dmg",
            "Windows": "https://cdn.useanything.com/latest/AnythingLLMDesktop.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "msty",
        "name": "Msty",
        "desc": "Universal AI desktop client — connects to OpenAI, Anthropic, Groq, and local models.",
        "urls": {
            "Linux":   "https://assets.msty.app/prod/latest/linux/Msty.AppImage",
            "Darwin":  "https://assets.msty.app/prod/latest/mac/arm/Msty.dmg",
            "Windows": "https://assets.msty.app/prod/latest/win/Msty-Installer.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "poe",
        "name": "Poe (Quora)",
        "desc": "Multi-model AI chat aggregator by Quora — all conversations routed through Poe cloud.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://poe.com/mac_native_app/Poe.dmg",
            "Windows": "https://poe.com/Poe.exe",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "copilot_app",
        "name": "Microsoft Copilot",
        "desc": "Microsoft standalone AI assistant — queries sent to Microsoft Azure OpenAI cloud.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://cdn.copilot.microsoft.com/macos/release/CopilotSetup.dmg",
            "Windows": "https://aka.ms/CopilotSetup",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "open_webui",
        "name": "Open WebUI",
        "desc": "Self-hosted AI frontend — bridges local Ollama models and cloud LLM APIs.",
        "urls": {
            "Linux":   "https://github.com/open-webui/open-webui/releases/latest/download/open-webui-linux.AppImage",
            "Darwin":  "https://github.com/open-webui/open-webui/releases/latest/download/open-webui-macos.dmg",
            "Windows": "https://github.com/open-webui/open-webui/releases/latest/download/open-webui-windows-setup.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
]

INSTALLERS_BROWSERS = [
    {
        "id":   "arc",
        "name": "Arc Browser (Arc Max)",
        "desc": "AI-first browser with Arc Max — browsing context and pages sent to AI summarizers.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://releases.arc.net/release/Arc-latest.dmg",
            "Windows": "https://releases.arc.net/release/Arc-latest.exe",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "opera",
        "name": "Opera One",
        "desc": "Built-in AI assistant (Aria) — high data exfiltration risk.",
        "urls": {
            "Linux":   "https://get.geo.opera.com/pub/opera/desktop/111.0.5168.25/linux/opera-stable_111.0.5168.25_amd64.deb",
            "Darwin":  "https://get.geo.opera.com/pub/opera/desktop/111.0.5168.25/mac/Opera_111.0.5168.25_Setup.dmg",
            "Windows": "https://get.geo.opera.com/pub/opera/desktop/111.0.5168.25/win/Opera_111.0.5168.25_Setup.exe",
        },
        "fmt":  {"Linux": "deb", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "dia",
        "name": "Dia Browser",
        "desc": "AI-native browser by The Browser Company — all tabs and context sent to AI cloud.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://www.diabrowser.com/download/mac",
            "Windows": "https://www.diabrowser.com/download/windows",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "brave",
        "name": "Brave Browser (Leo AI)",
        "desc": "Privacy browser with built-in Leo AI — queries sent to Anthropic/Meta cloud.",
        "urls": {
            "Linux":   "https://github.com/brave/brave-browser/releases/latest/download/brave-browser_amd64.deb",
            "Darwin":  "https://github.com/brave/brave-browser/releases/latest/download/Brave-Browser-arm64.dmg",
            "Windows": "https://github.com/brave/brave-browser/releases/latest/download/BraveBrowserSetup.exe",
        },
        "fmt":  {"Linux": "deb", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "edge_copilot",
        "name": "Microsoft Edge (Copilot)",
        "desc": "Microsoft browser with Copilot AI sidebar — browsing context sent to Microsoft Azure.",
        "urls": {
            "Linux":   "https://packages.microsoft.com/repos/edge/pool/main/m/microsoft-edge-stable/microsoft-edge-stable_amd64.deb",
            "Darwin":  "https://officecdn-microsoft-com.akamaized.net/pr/C1297A47-86C4-4C1F-97FA-950631F94777/MacAutoupdate/MicrosoftEdge.pkg",
            "Windows": "https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/latest/MicrosoftEdgeSetup.exe",
        },
        "fmt":  {"Linux": "deb", "Darwin": "pkg", "Windows": "exe"},
    },
    {
        "id":   "perplexity_app",
        "name": "Perplexity Desktop",
        "desc": "AI-powered search/answer engine desktop app — all queries sent to Perplexity cloud.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://www.perplexity.ai/download/mac",
            "Windows": "https://www.perplexity.ai/download/windows",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "genspark",
        "name": "Genspark",
        "desc": "AI super-agent search platform — queries and web context sent to Genspark AI cloud.",
        "urls": {
            "Linux":   None,
            "Darwin":  "https://www.genspark.ai/download/mac",
            "Windows": "https://www.genspark.ai/download/windows",
        },
        "fmt":  {"Darwin": "dmg", "Windows": "exe"},
    },
]

INSTALLERS_PRODUCTIVITY = [
    {
        "id":   "cursor",
        "name": "Cursor IDE",
        "desc": "AI-first code editor — sends code context to OpenAI/Anthropic.",
        "urls": {
            "Linux":   "https://downloader.cursor.sh/linux/appImage/x64",
            "Darwin":  "https://downloader.cursor.sh/mac/installer/universal",
            "Windows": "https://downloader.cursor.sh/windows/nsis/x64",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "windsurf",
        "name": "Windsurf (Codeium)",
        "desc": "Agentic AI IDE — auto-completes and sends code to cloud.",
        "urls": {
            "Linux":   "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf/latest/Windsurf.AppImage",
            "Darwin":  "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf/latest/Windsurf.dmg",
            "Windows": "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf/latest/WindsurfSetup.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "notion",
        "name": "Notion AI",
        "desc": "Note-taking with AI — document contents sent to OpenAI.",
        "urls": {
            "Linux":   "https://www.notion.so/desktop/linux/download",
            "Darwin":  "https://www.notion.so/desktop/mac-universal/download",
            "Windows": "https://www.notion.so/desktop/windows/download",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "gh_copilot",
        "name": "GitHub Copilot CLI",
        "desc": "AI coding assistant — sends shell commands & code to GitHub AI.",
        "urls": {
            "Linux":   "https://github.com/cli/cli/releases/latest/download/gh_2.62.0_linux_amd64.tar.gz",
            "Darwin":  "https://github.com/cli/cli/releases/latest/download/gh_2.62.0_macOS_arm64.zip",
            "Windows": "https://github.com/cli/cli/releases/latest/download/gh_2.62.0_windows_amd64.zip",
        },
        "fmt":  {"Linux": "tar.gz", "Darwin": "zip", "Windows": "zip"},
    },
    {
        "id":   "zed",
        "name": "Zed Editor (AI)",
        "desc": "Collaborative AI code editor — sends code context to Anthropic/OpenAI for completions.",
        "urls": {
            "Linux":   "https://zed.dev/api/releases/stable/latest/zed-linux-x86_64.tar.gz",
            "Darwin":  "https://zed.dev/api/releases/stable/latest/Zed.dmg",
            "Windows": "https://zed.dev/api/releases/stable/latest/ZedSetup.exe",
        },
        "fmt":  {"Linux": "tar.gz", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "trae",
        "name": "Trae IDE (ByteDance)",
        "desc": "AI-native IDE by ByteDance — code context and completions sent to ByteDance AI cloud.",
        "urls": {
            "Linux":   "https://download.trae.ai/linux/latest/Trae.AppImage",
            "Darwin":  "https://download.trae.ai/mac/latest/Trae.dmg",
            "Windows": "https://download.trae.ai/win/latest/TraeSetup.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "augment",
        "name": "Augment Code",
        "desc": "AI coding assistant with full repo awareness — codebase context sent to Augment cloud.",
        "urls": {
            "Linux":   "https://cdn.augmentcode.com/releases/latest/augment-linux.AppImage",
            "Darwin":  "https://cdn.augmentcode.com/releases/latest/augment-macos.dmg",
            "Windows": "https://cdn.augmentcode.com/releases/latest/augment-setup.exe",
        },
        "fmt":  {"Linux": "appimage", "Darwin": "dmg", "Windows": "exe"},
    },
    {
        "id":   "codeium_ext",
        "name": "Codeium Desktop",
        "desc": "AI code completion across all IDEs — code snippets and context sent to Codeium cloud.",
        "urls": {
            "Linux":   "https://github.com/Exafunction/codeium/releases/latest/download/codeium-linux.tar.gz",
            "Darwin":  "https://github.com/Exafunction/codeium/releases/latest/download/codeium-macos.dmg",
            "Windows": "https://github.com/Exafunction/codeium/releases/latest/download/codeium-setup.exe",
        },
        "fmt":  {"Linux": "tar.gz", "Darwin": "dmg", "Windows": "exe"},
    },
]

ALL_INSTALLERS = INSTALLERS_LOCAL_AI + INSTALLERS_BROWSERS + INSTALLERS_PRODUCTIVITY
