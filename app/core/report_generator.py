"""Generate JSON and HTML audit reports from event bus history."""

import json
import platform
import socket
from collections import Counter
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────────────
# JSON
# ─────────────────────────────────────────────────────────────────────────────

def build_json_report(history: list[dict]) -> str:
    summary = _summarise(history)
    installer_events = [e for e in history if e.get("category") == "INSTALLER"]
    report = {
        "report_metadata": {
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "hostname":       socket.gethostname(),
            "platform":       platform.platform(),
            "total_events":   len(history),
        },
        "summary": summary,
        "installer_diagnostics": {
            "resolved_url": [
                {
                    "target": e.get("target", ""),
                    "classification": e.get("classification", ""),
                    "resolved_url": e.get("resolved_url", ""),
                    "fallback_url_used": e.get("fallback_url_used"),
                    "http_status": e.get("http_status"),
                    "dns_status": e.get("dns_status"),
                    "installed_path": e.get("installed_path", ""),
                    "binary_path": e.get("binary_path", ""),
                    "pid": e.get("pid"),
                    "remediation_hint": e.get("remediation_hint", ""),
                }
                for e in installer_events
                if e.get("classification")
            ],
        },
        "events":  history,
    }
    return json.dumps(report, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────

def build_html_report(history: list[dict]) -> str:
    summary  = _summarise(history)
    rows     = "\n".join(_make_row(e) for e in history)
    gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Shadow AI Simulator — Audit Report</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body  {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; padding: 32px 20px; }}

  /* Header */
  .hdr  {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 28px 32px; margin-bottom: 28px; }}
  .hdr h1  {{ font-size: 22px; font-weight: 700; color: #f1f5f9; }}
  .hdr .sub {{ color: #64748b; font-size: 13px; margin-top: 6px; }}
  .meta {{ display: flex; gap: 28px; margin-top: 16px; font-size: 12px; color: #94a3b8; }}
  .meta strong {{ color: #cbd5e1; }}

  /* Summary cards */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .card  {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 18px 20px; text-align: center; }}
  .card .num {{ font-size: 30px; font-weight: 700; }}
  .card .lbl {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
  .red   .num {{ color: #f87171; }}
  .yel   .num {{ color: #fbbf24; }}
  .grn   .num {{ color: #34d399; }}
  .blu   .num {{ color: #60a5fa; }}
  .gry   .num {{ color: #94a3b8; }}

  /* Table */
  .tbl-wrap {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ background: #0f172a; color: #64748b; font-weight: 600; text-align: left; padding: 10px 14px; border-bottom: 1px solid #334155; white-space: nowrap; }}
  td {{ padding: 8px 14px; border-bottom: 1px solid #1e293b; vertical-align: top; word-break: break-word; }}
  tr:last-child td {{ border-bottom: none; }}
  .ts  {{ color: #475569; white-space: nowrap; }}
  .cat {{ color: #94a3b8; }}
  .msg {{ color: #e2e8f0; }}

  /* Level badges */
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 10px; font-weight: 700; letter-spacing: .4px; }}
  .lvl-ALERT   {{ background: #7f1d1d; color: #fca5a5; }}
  .lvl-INFO    {{ background: #1e3a5f; color: #93c5fd; }}
  .lvl-WARN    {{ background: #78350f; color: #fcd34d; }}
  .lvl-BLOCKED {{ background: #713f12; color: #fde68a; }}
  .lvl-ERROR   {{ background: #450a0a; color: #fca5a5; }}
  .lvl-SUCCESS {{ background: #064e3b; color: #6ee7b7; }}

  .footer {{ text-align: center; color: #334155; font-size: 11px; margin-top: 28px; padding-top: 20px; border-top: 1px solid #1e293b; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>Shadow AI Simulator — Audit Report</h1>
    <div class="sub">Red Team DLP / EDR Validation Toolkit</div>
    <div class="meta">
      <span><strong>Generated:</strong> {gen_time}</span>
      <span><strong>Host:</strong> {socket.gethostname()}</span>
      <span><strong>Platform:</strong> {platform.system()} {platform.release()}</span>
      <span><strong>Events:</strong> {len(history)}</span>
    </div>
  </div>

  <div class="cards">
    <div class="card red"><div class="num">{summary["alerts"]}</div><div class="lbl">Data Leak Alerts</div></div>
    <div class="card yel"><div class="num">{summary["blocked"]}</div><div class="lbl">Blocked by Proxy</div></div>
    <div class="card blu"><div class="num">{summary["info"]}</div><div class="lbl">Info Events</div></div>
    <div class="card gry"><div class="num">{summary["errors"]}</div><div class="lbl">Errors</div></div>
    <div class="card gry"><div class="num">{len(history)}</div><div class="lbl">Total Events</div></div>
  </div>

  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Timestamp (UTC)</th>
          <th>Level</th>
          <th>Category</th>
          <th>Target</th>
          <th>Classification</th>
          <th>HTTP</th>
          <th>Resolved URL</th>
          <th>Binary</th>
          <th>PID</th>
          <th>Remediation</th>
          <th>Data Type</th>
          <th>Message</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>

  <div class="footer">
    Generated by Shadow AI Simulator &mdash; For Authorized Security Testing Only
  </div>
</div>
</body>
</html>"""


def _make_row(e: dict) -> str:
    level = e.get("level", "INFO")
    return (
        f"<tr>"
        f"<td class='ts'>{e.get('ts','')}</td>"
        f"<td><span class='badge lvl-{level}'>{level}</span></td>"
        f"<td class='cat'>{e.get('category','')}</td>"
        f"<td style='color:#64748b;font-size:11px;'>{e.get('target','')}</td>"
        f"<td style='color:#a5b4fc;font-size:11px;'>{e.get('classification','')}</td>"
        f"<td style='color:#fbbf24;font-size:11px;'>{e.get('http_status','')}</td>"
        f"<td style='color:#94a3b8;font-size:11px;'>{e.get('resolved_url','')}</td>"
        f"<td style='color:#94a3b8;font-size:11px;'>{e.get('binary_path','')}</td>"
        f"<td style='color:#94a3b8;font-size:11px;'>{e.get('pid','')}</td>"
        f"<td style='color:#f59e0b;font-size:11px;'>{e.get('remediation_hint','')}</td>"
        f"<td style='color:#f59e0b;font-size:11px;'>{e.get('data_type','')}</td>"
        f"<td class='msg'>{e.get('message','')}</td>"
        f"</tr>"
    )


def _summarise(history: list[dict]) -> dict:
    counts  = Counter(e.get("level") for e in history)
    targets = list({e["target"] for e in history if e.get("target")})
    types   = list({e["data_type"] for e in history if e.get("data_type")})

    # Web leakage breakdown
    web = {
        "reachable":       sum(1 for e in history
                               if e.get("category") == "CHECK"
                               and e.get("level") == "SUCCESS"
                               and "USABLE" in e.get("message", "")),
        "blocked":         sum(1 for e in history
                               if e.get("category") in ("BROWSER", "CHECK", "BROWSE")
                               and e.get("level") == "BLOCKED"),
        "inputs_found":    sum(1 for e in history
                               if e.get("category") == "CHECK"
                               and "input field found" in e.get("message", "")),
        "leaks_simulated": sum(1 for e in history
                               if e.get("category") == "BROWSER"
                               and e.get("level") == "ALERT"
                               and "DATA LEAK SIMULATED" in e.get("message", "")),
    }

    # Installer breakdown
    installers = {
        "downloaded": sum(1 for e in history
                          if e.get("category") == "INSTALLER"
                          and "Download complete" in e.get("message", "")),
        "installed":  sum(1 for e in history
                          if e.get("category") == "INSTALLER"
                          and e.get("level") == "ALERT"
                          and "INSTALLED:" in e.get("message", "")),
        "blocked":    sum(1 for e in history
                          if e.get("category") == "INSTALLER"
                          and e.get("level") == "BLOCKED"),
        "failed":     sum(1 for e in history
                          if e.get("category") == "INSTALLER"
                          and e.get("level") == "ERROR"
                          and "INSTALL FAILED" in e.get("message", "")),
        "stale_url":  sum(1 for e in history
              if e.get("category") == "INSTALLER"
              and e.get("classification") in ("URL_INVALID_OR_STALE", "HTTP_404_NOT_FOUND")),
        "unsupported_platform": sum(1 for e in history
              if e.get("category") == "INSTALLER"
              and e.get("classification") in ("PLATFORM_NOT_SUPPORTED", "NO_LINUX_BUILD_AVAILABLE")),
        "dns_issue": sum(1 for e in history
              if e.get("category") == "INSTALLER"
              and e.get("classification") == "DNS_RESOLUTION_FAILED"),
        "proxy_block": sum(1 for e in history
              if e.get("category") == "INSTALLER"
              and e.get("classification") == "PROXY_BLOCKED"),
        "started_successfully": sum(1 for e in history
              if e.get("category") == "APP"
              and e.get("classification") == "STARTABLE"
              and e.get("pid")),
    }

    # API probe breakdown
    probes = {
        "sent":              sum(1 for e in history
                                 if e.get("category") == "API_PROBE"
                                 and e.get("level") == "INFO"
                                 and "Sending POST" in e.get("message", "")),
        "traffic_generated": sum(1 for e in history
                                 if e.get("category") == "API_PROBE"
                                 and e.get("level") == "ALERT"
                                 and "TRAFFIC GENERATED" in e.get("message", "")),
        "blocked":           sum(1 for e in history
                                 if e.get("category") == "API_PROBE"
                                 and e.get("level") == "BLOCKED"),
    }

    # MCP breakdown
    mcp = {
        "installs_attempted": sum(1 for e in history
                                  if e.get("category") == "MCP"
                                  and e.get("level") == "INFO"
                                  and "Installing MCP server:" in e.get("message", "")),
        "installs_succeeded": sum(1 for e in history
                                  if e.get("category") == "MCP"
                                  and e.get("level") == "ALERT"
                                  and "MCP SERVER INSTALLED" in e.get("message", "")),
        "configs_injected":   sum(1 for e in history
                                  if e.get("category") == "MCP"
                                  and e.get("level") == "ALERT"
                                  and "CONFIG INJECTED" in e.get("message", "")),
        "blocked":            sum(1 for e in history
                                  if e.get("category") == "MCP"
                                  and e.get("level") == "BLOCKED"),
    }

    return {
        "alerts":       counts.get("ALERT",   0),
        "blocked":      counts.get("BLOCKED", 0),
        "info":         counts.get("INFO",    0),
        "errors":       counts.get("ERROR",   0),
        "warnings":     counts.get("WARN",    0),
        "targets_hit":  targets,
        "data_types":   types,
        "web":          web,
        "installers":   installers,
        "probes":       probes,
        "mcp":          mcp,
    }
