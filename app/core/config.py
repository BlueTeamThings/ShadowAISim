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
# AI APPLICATION INSTALLER DEFINITIONS (catalog-backed)
# ─────────────────────────────────────────────────────────────────────────────

from app.core.app_catalog import legacy_groups

_LEGACY_GROUPS = legacy_groups(SYSTEM)

INSTALLERS_LOCAL_AI = _LEGACY_GROUPS["local_ai"]
INSTALLERS_BROWSERS = _LEGACY_GROUPS["browsers"]
INSTALLERS_PRODUCTIVITY = _LEGACY_GROUPS["productivity"]

ALL_INSTALLERS = INSTALLERS_LOCAL_AI + INSTALLERS_BROWSERS + INSTALLERS_PRODUCTIVITY
