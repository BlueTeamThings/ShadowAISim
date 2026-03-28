/* Shadow AI Simulator — Frontend */

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
let eventCount  = 0;
let auditRunning = false;

// ─────────────────────────────────────────────────────────────────────────────
// Navigation
// ─────────────────────────────────────────────────────────────────────────────
function showSection(id) {
  document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));

  const section = document.getElementById(`section-${id}`);
  if (section) section.classList.add("active");

  const btn = document.querySelector(`[data-section="${id}"]`);
  if (btn) btn.classList.add("active");

  if (id === "reports") refreshSummary();
}

// ─────────────────────────────────────────────────────────────────────────────
// Installer cards (auto-render from HTML data attributes)
// ─────────────────────────────────────────────────────────────────────────────
function renderInstallerCards() {
  document.querySelectorAll(".installer-card").forEach(el => {
    const id   = el.dataset.id;
    const name = el.dataset.name;
    const desc = el.dataset.desc;
    el.innerHTML = `
      <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full flex flex-col">
        <div class="flex items-center gap-2 mb-2">
          <div class="w-7 h-7 rounded-md bg-gray-800 border border-gray-700 flex items-center justify-center text-xs font-bold text-gray-400">
            ${name.charAt(0)}
          </div>
          <span class="font-medium text-sm">${name}</span>
        </div>
        <p class="text-xs text-gray-400 flex-1 mb-3">${desc}</p>
        <button onclick="apiPost('/api/installers/${id}')"
          class="card-btn w-full bg-gray-800 hover:bg-indigo-900 border border-gray-700 hover:border-indigo-700 text-xs py-1.5 rounded-lg text-gray-300">
          ⚙ Install Application
        </button>
      </div>`;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// SSE — Server-Sent Events
// ─────────────────────────────────────────────────────────────────────────────
let evtSource = null;

function connectSSE() {
  evtSource = new EventSource("/api/stream");

  evtSource.onopen = () => {
    setStatus(true);
  };

  evtSource.onmessage = (e) => {
    if (!e.data || e.data.startsWith(":")) return; // keepalive
    try {
      const entry = JSON.parse(e.data);
      appendTerminalLine(entry);
      eventCount++;
      document.getElementById("event-count").textContent = `${eventCount} events`;
      handleAuditPhase(entry);
    } catch (_) { /* ignore malformed */ }
  };

  evtSource.onerror = () => {
    setStatus(false);
    evtSource.close();
    setTimeout(connectSSE, 3000);
  };
}

function setStatus(connected) {
  const dot   = document.getElementById("ws-dot");
  const label = document.getElementById("ws-label");
  dot.className   = `inline-block w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`;
  label.textContent = connected ? "Connected" : "Reconnecting…";
}

// ─────────────────────────────────────────────────────────────────────────────
// Terminal rendering
// ─────────────────────────────────────────────────────────────────────────────
const LEVEL_COLORS = {
  ALERT:   "text-red-400",
  BLOCKED: "text-yellow-400",
  WARN:    "text-amber-400",
  ERROR:   "text-red-500",
  SUCCESS: "text-green-400",
  INFO:    "text-gray-400",
};

const LEVEL_BADGES = {
  ALERT:   "bg-red-900 text-red-300",
  BLOCKED: "bg-yellow-900 text-yellow-300",
  WARN:    "bg-amber-900 text-amber-300",
  ERROR:   "bg-red-950 text-red-400",
  SUCCESS: "bg-green-900 text-green-300",
  INFO:    "bg-gray-800 text-gray-400",
};

function appendTerminalLine(entry) {
  const term  = document.getElementById("terminal");
  const level = entry.level || "INFO";
  const color = LEVEL_COLORS[level] || LEVEL_COLORS.INFO;
  const badge = LEVEL_BADGES[level] || LEVEL_BADGES.INFO;

  const ts  = entry.ts ? entry.ts.slice(11, 23) + "Z" : "";
  const cat = entry.category || "";
  const msg = entry.message  || "";

  const line = document.createElement("div");
  line.className = `flex gap-2 items-start ${color}`;
  line.innerHTML =
    `<span class="text-gray-600 shrink-0">${ts}</span>` +
    `<span class="px-1.5 rounded text-xs shrink-0 ${badge}">${level}</span>` +
    `<span class="text-gray-500 shrink-0">[${cat}]</span>` +
    `<span>${escHtml(msg)}</span>`;

  term.appendChild(line);
  term.scrollTop = term.scrollHeight;
}

function clearTerminal() {
  document.getElementById("terminal").innerHTML = "";
  eventCount = 0;
  document.getElementById("event-count").textContent = "0 events";
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ─────────────────────────────────────────────────────────────────────────────
// API helpers
// ─────────────────────────────────────────────────────────────────────────────
async function apiPost(url) {
  try {
    const resp = await fetch(url, { method: "POST" });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      appendTerminalLine({ level: "ERROR", category: "UI", message: `API error: ${d.error || resp.status}`, ts: now() });
    }
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "UI", message: `Fetch failed: ${err}`, ts: now() });
  }
}

function now() {
  return new Date().toISOString().slice(0, 23) + "Z";
}

// ─────────────────────────────────────────────────────────────────────────────
// Full Audit
// ─────────────────────────────────────────────────────────────────────────────
async function startAudit() {
  if (auditRunning) return;
  auditRunning = true;
  document.getElementById("audit-idle").classList.add("hidden");
  document.getElementById("audit-running").classList.remove("hidden");
  await apiPost("/api/audit/start");
}

function handleAuditPhase(entry) {
  if (!auditRunning) return;
  if (entry.category === "AUDIT") {
    const msg   = entry.message || "";
    const phase = document.getElementById("audit-phase");
    if (msg.includes("PHASE 1")) phase.textContent = "Phase 1: Web Leakage";
    if (msg.includes("PHASE 2")) phase.textContent = "Phase 2: API Probes";
    if (msg.includes("PHASE 3")) phase.textContent = "Phase 3: Installers";
    if (msg.includes("PHASE 4")) phase.textContent = "Phase 4: MCP Servers";
    if (msg.includes("AUDIT COMPLETE")) {
      auditRunning = false;
      document.getElementById("audit-running").classList.add("hidden");
      document.getElementById("audit-idle").classList.remove("hidden");
      appendTerminalLine({ level: "SUCCESS", category: "UI", message: "✓ Audit complete — go to Reports to download your log", ts: now() });
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Reports — summary refresh
// ─────────────────────────────────────────────────────────────────────────────
async function refreshSummary() {
  try {
    const resp = await fetch("/api/reports/summary");
    const d    = await resp.json();

    // Overview counters
    document.getElementById("s-events").textContent  = d.events  ?? 0;
    document.getElementById("s-alerts").textContent  = d.alerts  ?? 0;
    document.getElementById("s-blocked").textContent = d.blocked ?? 0;
    document.getElementById("s-errors").textContent  = d.errors  ?? 0;

    // Web leakage breakdown
    const w = d.web || {};
    document.getElementById("s-web-reachable").textContent = w.reachable ?? 0;
    document.getElementById("s-web-blocked").textContent   = w.blocked ?? 0;
    document.getElementById("s-web-inputs").textContent    = w.inputs_found ?? 0;
    document.getElementById("s-web-leaks").textContent     = w.leaks_simulated ?? 0;

    // Installer breakdown
    const i = d.installers || {};
    document.getElementById("s-inst-downloaded").textContent = i.downloaded ?? 0;
    document.getElementById("s-inst-blocked").textContent    = i.blocked ?? 0;
    document.getElementById("s-inst-failed").textContent     = i.failed ?? 0;
    document.getElementById("s-inst-installed").textContent  = i.installed ?? 0;

    // API probe breakdown
    const p = d.probes || {};
    document.getElementById("s-probe-sent").textContent    = p.sent ?? 0;
    document.getElementById("s-probe-blocked").textContent = p.blocked ?? 0;
    document.getElementById("s-probe-traffic").textContent = p.traffic_generated ?? 0;

    // MCP server breakdown
    const m = d.mcp || {};
    document.getElementById("s-mcp-attempted").textContent = m.installs_attempted ?? 0;
    document.getElementById("s-mcp-installed").textContent = m.installs_succeeded ?? 0;
    document.getElementById("s-mcp-blocked").textContent   = m.blocked ?? 0;
    document.getElementById("s-mcp-injected").textContent  = m.configs_injected ?? 0;

    // Generate verdict
    renderVerdict(d);
  } catch (_) {}
}

function renderVerdict(d) {
  const el   = document.getElementById("summary-verdict");
  const text = document.getElementById("verdict-text");
  if (!d.events) { el.classList.add("hidden"); return; }

  const w = d.web || {};
  const i = d.installers || {};
  const p = d.probes || {};
  const lines = [];

  // Web verdict
  const totalWebTests = (w.reachable || 0) + (w.blocked || 0);
  if (totalWebTests > 0) {
    lines.push(`${w.reachable} of ${totalWebTests} AI sites were reachable from this network.`);
    if (w.leaks_simulated > 0)
      lines.push(`${w.leaks_simulated} data leak(s) were successfully simulated — DLP did not block the paste.`);
    else if (w.reachable > 0)
      lines.push("No data leaks were simulated yet (sites were reachable but no leak test was run).");
    if (w.blocked > 0)
      lines.push(`${w.blocked} site(s) were blocked by proxy/firewall — good coverage.`);
  }

  // Installer verdict
  const totalInstTests = (i.downloaded || 0) + (i.blocked || 0);
  if (totalInstTests > 0 || (i.installed || 0) > 0) {
    if (i.installed > 0)
      lines.push(`${i.installed} AI application(s) were installed on this system — EDR/endpoint policy did not prevent installation.`);
    if (i.blocked > 0)
      lines.push(`${i.blocked} installer download(s) were blocked by network policy.`);
    if (i.failed > 0)
      lines.push(`${i.failed} installation(s) failed (check terminal for details).`);
    if (i.downloaded > 0 && i.installed === 0 && i.blocked === 0)
      lines.push(`${i.downloaded} download(s) completed but no installations were confirmed yet.`);
  }

  // API probe verdict
  if ((p.sent || 0) > 0) {
    lines.push(`${p.sent} API probe(s) were sent to AI endpoints.`);
    if (p.traffic_generated > 0)
      lines.push(`${p.traffic_generated} probe(s) generated outbound traffic — CASB/DPI did not intercept.`);
    if (p.blocked > 0)
      lines.push(`${p.blocked} probe(s) were blocked by proxy.`);
  }

  // MCP server verdict
  const m = d.mcp || {};
  if ((m.installs_attempted || 0) > 0 || (m.configs_injected || 0) > 0) {
    if (m.installs_attempted > 0)
      lines.push(`${m.installs_attempted} MCP server package install(s) were attempted — process-creation + network telemetry generated.`);
    if (m.installs_succeeded > 0)
      lines.push(`${m.installs_succeeded} MCP server(s) installed successfully — EDR did not block the npm/pip install.`);
    if (m.configs_injected > 0)
      lines.push(`${m.configs_injected} AI client config file(s) were modified to inject MCP servers — FIM should have alerted on claude_desktop_config.json.`);
    if (m.blocked > 0)
      lines.push(`${m.blocked} MCP operation(s) were blocked — good EDR coverage.`);
  }

  if (lines.length === 0) {
    el.classList.add("hidden");
    return;
  }

  el.classList.remove("hidden");
  text.innerHTML = lines.map(l => `<span class="block mb-1">• ${escHtml(l)}</span>`).join("");
}

// ─────────────────────────────────────────────────────────────────────────────
// Preflight / Dependency Health
// ─────────────────────────────────────────────────────────────────────────────
async function runPreflight() {
  const grid = document.getElementById("preflight-grid");
  if (!grid) return;
  grid.innerHTML = `<div class="col-span-4 text-gray-500 text-sm text-center py-4">Checking dependencies…</div>`;

  try {
    const resp = await fetch("/api/preflight/check");
    const data = await resp.json();
    renderPreflightGrid(data);
  } catch (err) {
    grid.innerHTML = `<div class="col-span-4 text-red-400 text-sm">Preflight check failed: ${escHtml(String(err))}</div>`;
  }
}

function renderPreflightGrid(data) {
  const grid = document.getElementById("preflight-grid");
  if (!grid) return;

  const depLabels = {
    python:    { label: "Python",          icon: "🐍" },
    pip:       { label: "pip",             icon: "📦" },
    curl:      { label: "curl",            icon: "🌐" },
    node:      { label: "Node.js",         icon: "🟢" },
    npm:       { label: "npm",             icon: "📦" },
    npx:       { label: "npx",             icon: "⚡" },
    playwright:{ label: "Playwright",      icon: "🎭" },
    chromium:  { label: "Chromium",        icon: "🔵" },
    ollama:    { label: "Ollama",          icon: "🦙" },
    mcp_capable:       { label: "MCP Install", icon: "🔗" },
    api_probe_capable: { label: "API Probe",   icon: "🔌" },
  };

  let html = "";
  for (const [key, meta] of Object.entries(depLabels)) {
    const entry = data[key];
    if (!entry) continue;
    const ok   = entry.ok === true;
    const path = entry.path || entry.note || (ok ? "available" : "not found");
    const border = ok ? "border-green-800" : "border-amber-700";
    const badge  = ok
      ? "bg-green-900 text-green-300"
      : "bg-amber-900 text-amber-300";
    const badgeText = ok ? "OK" : "MISSING";

    html += `
      <div class="bg-gray-900 border ${border} rounded-xl p-4">
        <div class="flex items-center justify-between mb-2">
          <span class="text-base">${meta.icon}</span>
          <span class="text-xs px-2 py-0.5 rounded font-semibold ${badge}">${badgeText}</span>
        </div>
        <div class="font-semibold text-sm mb-1">${meta.label}</div>
        <div class="text-xs text-gray-500 break-all leading-relaxed">${escHtml(String(path))}</div>
      </div>`;
  }

  grid.innerHTML = html || `<div class="col-span-4 text-gray-500 text-sm">No dependency data available.</div>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────
renderInstallerCards();
connectSSE();
appendTerminalLine({ level: "INFO", category: "SYSTEM", message: "Shadow AI Simulator ready. Select a test or run the Full Audit.", ts: now() });
