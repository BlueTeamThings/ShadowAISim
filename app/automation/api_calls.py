"""
Direct REST API probe automation.

Sends POST requests with fake sensitive payloads to AI API endpoints.
Designed to trigger deep packet inspection, network proxies, and CASB tools.
A 401 Unauthorized response is expected (invalid key) — the traffic is what matters.
"""

from typing import Callable, Awaitable

import httpx

Emitter = Callable[..., Awaitable[None]]


async def probe_api_endpoint(target: dict, emit: Emitter) -> dict:
    """POST a fake sensitive payload to an AI API endpoint."""
    url       = target["url"]
    name      = target["name"]
    data_type = target["data_type"]
    headers   = {**target["headers"], "Content-Type": "application/json"}

    await emit("INFO", "API_PROBE",
               f"Sending POST → {url}  ({data_type})", url, data_type)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=target["payload"])

        code = resp.status_code

        if code == 401:
            await emit(
                "ALERT", "API_PROBE",
                f"HTTP 401 from {name} — POST with {data_type} payload sent (401 expected with invalid key) — TRAFFIC GENERATED",
                url, data_type,
            )
        elif code == 403:
            await emit(
                "BLOCKED", "API_PROBE",
                f"HTTP 403 from {name} — request may be blocked by CASB/proxy",
                url, data_type,
            )
        elif code == 200:
            await emit(
                "ALERT", "API_PROBE",
                f"HTTP 200 from {name} — {data_type} payload accepted by endpoint",
                url, data_type,
            )
        else:
            await emit(
                "WARN", "API_PROBE",
                f"HTTP {code} from {name} — unexpected response",
                url, data_type,
            )

        return {"success": True, "status": code, "target": name}

    except httpx.ConnectError as exc:
        await emit(
            "BLOCKED", "API_PROBE",
            f"Successfully Blocked by Proxy: {name} — connection refused ({exc})",
            url, data_type,
        )
        return {"success": False, "blocked": True, "target": name}

    except httpx.TimeoutException:
        await emit(
            "BLOCKED", "API_PROBE",
            f"Successfully Blocked by Proxy (timeout): {name}",
            url, data_type,
        )
        return {"success": False, "blocked": True, "target": name}

    except Exception as exc:
        await emit("ERROR", "API_PROBE", f"Unhandled error probing {name}: {exc}", url, data_type)
        return {"success": False, "error": str(exc), "target": name}
