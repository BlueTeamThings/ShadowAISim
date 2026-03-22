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
    document.getElementById("s-events").textContent  = d.events  ?? 0;
    document.getElementById("s-alerts").textContent  = d.alerts  ?? 0;
    document.getElementById("s-blocked").textContent = d.blocked ?? 0;
    document.getElementById("s-errors").textContent  = d.errors  ?? 0;
  } catch (_) {}
}

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────
renderInstallerCards();
connectSSE();
appendTerminalLine({ level: "INFO", category: "SYSTEM", message: "Shadow AI Simulator ready. Select a test or run the Full Audit.", ts: now() });
