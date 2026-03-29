"""
Direct REST API probe automation.

Sends POST requests with fake sensitive payloads to AI API endpoints.
Designed to trigger deep packet inspection, network proxies, and CASB tools.

Classification model:
  - DNS + TCP + TLS + HTTP response received   → traffic was generated
  - HTTP 401/403 with intentionally invalid key → EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED
  - HTTP 407                                    → BLOCKED_BY_PROXY
  - HTTP 200-299                                → SUCCESS_RESPONSE
  - ConnectError / DNS failure                  → CONNECTION_FAILED
  - Timeout before response                     → NO_TRAFFIC_CONFIRMED
"""

from __future__ import annotations

from typing import Callable, Awaitable

import httpx

Emitter = Callable[..., Awaitable[None]]


def _classify(status_code: int) -> str:
    """Return a classification string for the given HTTP status code."""
    if 200 <= status_code <= 299:
        return "SUCCESS_RESPONSE"
    if status_code in (401, 403):
        return "EXPECTED_AUTH_FAILURE_TRAFFIC_GENERATED"
    if status_code == 407:
        return "BLOCKED_BY_PROXY"
    return f"HTTP_{status_code}"


async def probe_api_endpoint(target: dict, emit: Emitter) -> dict:
    """
    POST a fake sensitive payload to an AI API endpoint.

    Returns a structured result:
      transmitted        – True if the request was actually sent over the wire
      response_received  – True if any HTTP response came back
      status_code        – integer HTTP status, or None
      classification     – one of the class constants above
      detection_value    – short human note about what was observed
      notes              – longer explanation
    """
    url       = target["url"]
    name      = target["name"]
    data_type = target["data_type"]
    headers   = {**target["headers"], "Content-Type": "application/json"}

    await emit("INFO", "API_PROBE",
               f"Sending POST → {url}  ({data_type})", url, data_type)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=target["payload"])

        code           = resp.status_code
        classification = _classify(code)

        if code in (401, 403):
            # Expected with deliberately invalid API key — traffic DID reach the endpoint
            await emit(
                "SUCCESS", "API_PROBE",
                f"TRAFFIC GENERATED: {name} returned HTTP {code} "
                f"(expected with invalid key) — {data_type} payload transmitted. "
                f"Classification: {classification}",
                url, data_type,
                classification=classification,
                status_code=code,
            )
        elif 200 <= code <= 299:
            await emit(
                "ALERT", "API_PROBE",
                f"HTTP {code} from {name} — {data_type} payload accepted by endpoint. "
                f"Classification: {classification}",
                url, data_type,
                classification=classification,
                status_code=code,
            )
        elif code == 407:
            await emit(
                "BLOCKED", "API_PROBE",
                f"HTTP 407 from {name} — request blocked by proxy. "
                f"Classification: {classification}",
                url, data_type,
                classification=classification,
                status_code=code,
            )
        else:
            await emit(
                "WARN", "API_PROBE",
                f"HTTP {code} from {name} — unexpected response. "
                f"Classification: {classification}",
                url, data_type,
                classification=classification,
                status_code=code,
            )

        return {
            "transmitted":       True,
            "response_received": True,
            "status_code":       code,
            "classification":    classification,
            "detection_value":   f"HTTP {code} response received",
            "notes":             f"POST to {url} completed with HTTP {code}",
            "target":            name,
        }

    except httpx.ConnectError as exc:
        classification = "CONNECTION_FAILED"
        await emit(
            "BLOCKED", "API_PROBE",
            f"Successfully Blocked by Proxy: {name} — connection refused. "
            f"Classification: {classification} — {exc}",
            url, data_type,
            classification=classification,
        )
        return {
            "transmitted":       False,
            "response_received": False,
            "status_code":       None,
            "classification":    classification,
            "detection_value":   "Connection refused — no traffic confirmed",
            "notes":             str(exc),
            "target":            name,
        }

    except httpx.TimeoutException:
        classification = "NO_TRAFFIC_CONFIRMED"
        await emit(
            "BLOCKED", "API_PROBE",
            f"Successfully Blocked by Proxy (timeout): {name}. "
            f"Classification: {classification}",
            url, data_type,
            classification=classification,
        )
        return {
            "transmitted":       False,
            "response_received": False,
            "status_code":       None,
            "classification":    classification,
            "detection_value":   "Timeout — no response received",
            "notes":             "Request timed out before server responded",
            "target":            name,
        }

    except Exception as exc:
        classification = "ERROR"
        await emit("ERROR", "API_PROBE",
                   f"Unhandled error probing {name}: {exc}", url, data_type,
                   classification=classification)
        return {
            "transmitted":       False,
            "response_received": False,
            "status_code":       None,
            "classification":    classification,
            "detection_value":   "Error before transmission",
            "notes":             str(exc),
            "target":            name,
        }
