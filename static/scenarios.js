/* Shadow AI Simulator - Scenario Library + Scenario Builder */

const SCN = {
  initialized: false,
  meta: null,
  scenarios: [],
  filtered: [],
  queue: [],
  history: [],
  runStatus: null,
  selectedId: "",
  editing: null,
  pollId: null,
  filters: {
    platform: "any",
    authOnly: false,
    browserOnly: false,
    desktopOnly: false,
    localOnly: false,
  },
};

const SCN_COMMON_APPLICATIONS = [
  "vscode",
  "cursor",
  "windsurf",
  "zed",
  "ollama",
  "lm studio",
  "gpt4all",
  "jan",
  "anythingllm",
  "open webui",
  "notion",
  "arc",
  "brave",
  "opera",
  "edge",
];

const SCN_COMMON_EXTENSIONS = [
  "GitHub.copilot",
  "GitHub.copilot-chat",
  "ms-python.python",
  "ms-toolsai.jupyter",
  "esbenp.prettier-vscode",
  "dbaeumer.vscode-eslint",
  "ms-vscode.vscode-typescript-next",
];

const SCN_COMMON_WEBSITES = [
  "https://chatgpt.com",
  "https://claude.ai",
  "https://gemini.google.com",
  "https://perplexity.ai",
  "https://huggingface.co/chat",
  "https://copilot.microsoft.com",
];

const ScenarioLibraryView = window.ScenarioLibraryView || null;

function scenarioBlank() {
  return {
    id: "",
    title: "",
    description: "",
    category: "IDE Assistants",
    family: "General",
    tags: [],
    risk_level: "medium",
    platforms: ["any"],
    auth_required: false,
    prerequisites: [],
    steps: [
      {
        id: "step-1",
        type: "wait",
        params: { seconds: 1 },
        notes: "",
      },
    ],
    assertions: [],
    expected_observables: [],
    detector_expectations: [],
    cleanup_steps: [],
    metadata: {},
    status: "idle",
  };
}

async function scenarioFetchJson(url, options) {
  const resp = await fetch(url, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || `Request failed (${resp.status})`);
  }
  return data;
}

function scenarioBuildQuery() {
  const params = new URLSearchParams();
  if (SCN.filters.platform && SCN.filters.platform !== "any") {
    params.set("platform", SCN.filters.platform);
  }
  if (SCN.filters.authOnly) {
    params.set("auth_required", "true");
  }

  const activeModes = [
    SCN.filters.browserOnly ? "browser-only" : "",
    SCN.filters.desktopOnly ? "desktop-only" : "",
    SCN.filters.localOnly ? "local-only" : "",
  ].filter(Boolean);

  if (activeModes.length === 1) {
    params.set("mode", activeModes[0]);
  }

  const query = params.toString();
  return query ? `?${query}` : "";
}

function scenarioMatchesClientModeFilters(item) {
  const tags = new Set((item.tags || []).map((v) => String(v).toLowerCase()));

  if (SCN.filters.browserOnly && !(tags.has("browser") && !tags.has("desktop") && !tags.has("local"))) {
    return false;
  }
  if (SCN.filters.desktopOnly && !(tags.has("desktop") && !tags.has("browser"))) {
    return false;
  }
  if (SCN.filters.localOnly && !tags.has("local")) {
    return false;
  }
  return true;
}

function scenarioStatusClass(status) {
  const map = {
    passed: "bg-green-900 text-green-300",
    failed: "bg-red-900 text-red-300",
    running: "bg-indigo-900 text-indigo-300",
    idle: "bg-gray-800 text-gray-300",
  };
  return map[String(status || "").toLowerCase()] || "bg-gray-800 text-gray-300";
}

function scenarioFormatDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

function scenarioStepDefs() {
  return (SCN.meta && SCN.meta.step_types) ? SCN.meta.step_types : [];
}

function scenarioStepDef(type) {
  return scenarioStepDefs().find((item) => item.type === type) || null;
}

function scenarioUniqueStrings(items) {
  const seen = new Set();
  const out = [];
  for (const raw of (items || [])) {
    const value = String(raw || "").trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

function scenarioSuggestedApplications() {
  const metaApps = ((SCN.meta && SCN.meta.apps) ? SCN.meta.apps : [])
    .map((item) => String(item && item.name ? item.name : "").trim())
    .filter(Boolean);
  return scenarioUniqueStrings([...SCN_COMMON_APPLICATIONS, ...metaApps]);
}

function scenarioSuggestionOptions(stepType, fieldName) {
  const type = String(stepType || "").trim();
  const field = String(fieldName || "").trim();

  if ((type === "install_application" || type === "launch_application" || type === "close_application") && field === "app_name") {
    return scenarioSuggestedApplications();
  }

  if ((type === "install_extension" || type === "install_browser_extension") && field === "extension_id") {
    return SCN_COMMON_EXTENSIONS;
  }

  if (type === "open_website" && field === "url") {
    return SCN_COMMON_WEBSITES;
  }

  return [];
}

function scenarioEnsureEditing() {
  if (!SCN.editing) {
    SCN.editing = scenarioBlank();
  }
}

function scenarioNormalizeList(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) {
    return raw.map((v) => String(v).trim()).filter(Boolean);
  }
  return String(raw)
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
}

function scenarioSetFilterStateFromUI() {
  SCN.filters.platform = String(document.getElementById("scenario-filter-platform")?.value || "any");
  SCN.filters.authOnly = Boolean(document.getElementById("scenario-filter-auth")?.checked);
  SCN.filters.browserOnly = Boolean(document.getElementById("scenario-filter-browser")?.checked);
  SCN.filters.desktopOnly = Boolean(document.getElementById("scenario-filter-desktop")?.checked);
  SCN.filters.localOnly = Boolean(document.getElementById("scenario-filter-local")?.checked);
}

function scenarioRenderTree() {
  const host = document.getElementById("scenario-tree");
  if (!host) return;

  if (!SCN.filtered.length) {
    host.innerHTML = `<div class="text-xs text-gray-500 p-3">No scenarios match the current filters.</div>`;
    return;
  }

  const grouped = new Map();
  SCN.filtered.forEach((item) => {
    const category = item.category || "Uncategorized";
    const family = item.family || "General";
    if (!grouped.has(category)) grouped.set(category, new Map());
    const familyMap = grouped.get(category);
    if (!familyMap.has(family)) familyMap.set(family, []);
    familyMap.get(family).push(item);
  });

  const orderedCategories = Array.from(grouped.keys()).sort((a, b) => {
    const categories = (SCN.meta && SCN.meta.categories) ? SCN.meta.categories : [];
    const ai = categories.indexOf(a);
    const bi = categories.indexOf(b);
    const av = ai >= 0 ? ai : 999;
    const bv = bi >= 0 ? bi : 999;
    if (av !== bv) return av - bv;
    return a.localeCompare(b);
  });

  host.innerHTML = orderedCategories.map((category) => {
    const families = grouped.get(category);
    const familyNames = Array.from(families.keys()).sort((a, b) => a.localeCompare(b));
    const total = familyNames.reduce((acc, name) => acc + families.get(name).length, 0);

    const familyHtml = familyNames.map((family) => {
      const scenarios = families.get(family).slice().sort((a, b) => String(a.title || "").localeCompare(String(b.title || "")));
      const children = (ScenarioLibraryView && typeof ScenarioLibraryView.renderScenarioCards === "function")
        ? ScenarioLibraryView.renderScenarioCards(scenarios, SCN.selectedId, {
          escHtml,
          statusClass: scenarioStatusClass,
        })
        : scenarios.map((item) => {
          const active = item.id === SCN.selectedId;
          return `
          <button data-scenario-id="${escHtml(item.id)}" onclick="scenarioSelect('${item.id}')"
            class="w-full text-left text-xs px-2 py-1 rounded ${active ? "bg-indigo-900 text-indigo-200" : "text-gray-400 hover:bg-gray-800"}">
            <div class="flex items-center justify-between gap-2">
              <span class="truncate">${escHtml(item.title || item.id)}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded ${scenarioStatusClass(item.status)}">${escHtml(String(item.risk_level || "").toUpperCase() || "-")}</span>
            </div>
          </button>`;
        }).join("");

      return `
        <div class="ml-3 mt-1">
          <div class="text-[11px] text-gray-500 mb-1">${escHtml(family)} (${scenarios.length})</div>
          <div class="space-y-1">${children}</div>
        </div>`;
    }).join("");

    return `
      <div class="border border-gray-800 rounded-lg p-2 bg-gray-900 mb-2">
        <div class="text-xs font-semibold text-gray-200">${escHtml(category)} <span class="text-gray-500">(${total})</span></div>
        ${familyHtml}
      </div>`;
  }).join("");
}

function scenarioRenderTemplateList() {
  const host = document.getElementById("scenario-template-list");
  if (!host) return;
  const templates = (SCN.meta && SCN.meta.templates) ? SCN.meta.templates : [];
  if (!templates.length) {
    host.innerHTML = `<div class="text-xs text-gray-500">No templates available.</div>`;
    return;
  }
  host.innerHTML = templates.map((tpl) => {
    const templateId = String(tpl.template_id || "");
    return `
    <div class="text-[11px] text-gray-400 border border-gray-800 rounded p-2 bg-gray-950">
      <div class="font-medium text-gray-300">${escHtml(tpl.title || tpl.template_id)}</div>
      <div class="text-gray-500 mt-0.5">${escHtml(tpl.description || "")}</div>
      <div class="mt-2 text-[10px] text-gray-600">${escHtml(tpl.recommended_category || "General")} / ${escHtml(tpl.recommended_family || "General")}</div>
      <button onclick="scenarioQuickCreateFromTemplate('${templateId}')" class="mt-2 w-full text-[11px] bg-indigo-900 hover:bg-indigo-800 border border-indigo-700 text-indigo-200 px-2 py-1 rounded">
        Quick Create
      </button>
    </div>`;
  }).join("");
}

function scenarioRenderEditor() {
  scenarioEnsureEditing();

  const e = SCN.editing;
  const setVal = (id, value) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.value = value;
  };
  const setChecked = (id, value) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = Boolean(value);
  };

  const idLabel = document.getElementById("scenario-editor-id");
  if (idLabel) idLabel.textContent = e.id || "new";

  setVal("scenario-title", e.title || "");
  setVal("scenario-description", e.description || "");
  setVal("scenario-category", e.category || "IDE Assistants");
  setVal("scenario-family", e.family || "General");
  setVal("scenario-risk", e.risk_level || "medium");
  setVal("scenario-platforms", (e.platforms || ["any"]).join(", "));
  setChecked("scenario-auth-required", e.auth_required);
  setVal("scenario-tags", (e.tags || []).join(", "));
  setVal("scenario-prerequisites", (e.prerequisites || []).join("\n"));
  setVal("scenario-assertions", (e.assertions || []).join("\n"));
  setVal("scenario-observables", (e.expected_observables || []).join("\n"));
  setVal("scenario-detectors", (e.detector_expectations || []).join("\n"));
  setVal("scenario-cleanup", (e.cleanup_steps || []).join("\n"));

  scenarioRenderStepRows();
  scenarioRenderAssertionPreview();
}

function scenarioRenderStepRows() {
  const host = document.getElementById("scenario-steps-host");
  if (!host) return;

  scenarioEnsureEditing();
  const steps = SCN.editing.steps || [];
  if (!steps.length) {
    host.innerHTML = `<div class="text-xs text-gray-500 border border-gray-800 rounded p-3">No steps configured.</div>`;
    return;
  }

  const defs = scenarioStepDefs();
  host.innerHTML = steps.map((step, index) => {
    const def = scenarioStepDef(step.type) || { fields: [] };
    const options = defs.map((item) => `<option value="${item.type}" ${item.type === step.type ? "selected" : ""}>${escHtml(item.label)}</option>`).join("");

    const fields = (def.fields || []).map((field) => {
      const raw = (step.params || {})[field.name];
      const value = (raw === undefined || raw === null) ? "" : raw;
      const required = field.required ? " *" : "";
      const inputType = field.input || "text";
      const suggestions = scenarioSuggestionOptions(step.type, field.name);
      const datalistId = `scn-step-${index}-${step.type}-${field.name}`.replace(/[^a-zA-Z0-9_-]/g, "-");

      if (inputType === "textarea") {
        return `
          <label class="block text-[11px] text-gray-400 mb-2">
            ${escHtml(field.label)}${required}
            <textarea rows="2" class="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100"
              placeholder="${escHtml(field.placeholder || "")}" oninput="scenarioStepFieldChanged(${index}, '${field.name}', this.value, 'textarea')">${escHtml(String(value))}</textarea>
          </label>`;
      }

      if (inputType === "checkbox") {
        return `
          <label class="flex items-center gap-2 text-[11px] text-gray-400 mb-2">
            <input type="checkbox" ${value ? "checked" : ""} onchange="scenarioStepFieldChanged(${index}, '${field.name}', this.checked, 'checkbox')" class="accent-indigo-500" />
            ${escHtml(field.label)}${required}
          </label>`;
      }

      return `
        <label class="block text-[11px] text-gray-400 mb-2">
          ${escHtml(field.label)}${required}
          <input type="${inputType === "number" ? "number" : "text"}" class="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100"
            ${suggestions.length ? `list="${datalistId}"` : ""}
            value="${escHtml(String(value))}" placeholder="${escHtml(field.placeholder || "")}" oninput="scenarioStepFieldChanged(${index}, '${field.name}', this.value, '${inputType}')" />
          ${suggestions.length ? `<datalist id="${datalistId}">${suggestions.map((opt) => `<option value="${escHtml(opt)}"></option>`).join("")}</datalist>` : ""}
        </label>`;
    }).join("");

    return `
      <div class="border border-gray-800 rounded-lg p-3 bg-gray-900">
        <div class="flex items-center justify-between mb-2">
          <div class="text-xs font-semibold text-gray-300">Step ${index + 1}</div>
          <button onclick="scenarioStepDelete(${index})" class="text-[11px] bg-red-950 hover:bg-red-900 border border-red-800 text-red-300 px-2 py-1 rounded">Remove</button>
        </div>
        <label class="block text-[11px] text-gray-400 mb-2">
          Step type
          <select class="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100" onchange="scenarioStepTypeChanged(${index}, this.value)">
            ${options}
          </select>
        </label>
        ${fields}
      </div>`;
  }).join("");
}

function scenarioRenderQueue() {
  const host = document.getElementById("scenario-queue-list");
  if (!host) return;

  if (!SCN.queue.length) {
    host.innerHTML = `<div class="text-xs text-gray-500">Queue is empty.</div>`;
    return;
  }

  host.innerHTML = SCN.queue.map((item, idx) => `
    <div class="border border-gray-800 rounded p-2 bg-gray-900">
      <div class="flex items-center justify-between gap-2">
        <div>
          <div class="text-xs text-gray-200">${idx + 1}. ${escHtml(item.title || item.id)}</div>
          <div class="text-[11px] text-gray-500">${escHtml(item.category || "")} / ${escHtml(item.family || "")}</div>
        </div>
        <button onclick="scenarioQueueRemove('${item.id}')" class="text-[11px] bg-gray-800 hover:bg-gray-700 border border-gray-700 px-2 py-1 rounded">Remove</button>
      </div>
    </div>`).join("");
}

function scenarioRenderRunStatus() {
  const host = document.getElementById("scenario-run-status");
  const cp = document.getElementById("scenario-manual-checkpoint");
  if (!host || !cp) return;

  const status = SCN.runStatus || {};
  const current = status.current_run;

  if (current && status.running) {
    const stepRows = (current.step_results || []).slice(-6).map((step) => {
      const tone = step.success ? "text-green-400" : "text-red-400";
      return `<div class="text-xs ${tone}">Step ${step.index}: ${escHtml(step.type)} - ${escHtml(step.message || "")}</div>`;
    }).join("");

    const logs = (current.logs || []).slice(-10).map((line) => {
      const ts = new Date(line.ts * 1000).toLocaleTimeString();
      return `<div class="text-[11px] text-gray-400"><span class="text-gray-600">${ts}</span> <span class="text-gray-500">${escHtml(line.level)}</span> ${escHtml(line.message)}</div>`;
    }).join("");

    host.innerHTML = `
      <div class="text-sm font-semibold text-indigo-300">Running: ${escHtml(current.scenario_title || "scenario")}</div>
      <div class="text-xs text-gray-500 mt-1">Step ${current.current_step}/${current.total_steps} - ${current.elapsed_seconds || 0}s</div>
      <div class="mt-3 space-y-1">${stepRows || "<div class='text-xs text-gray-500'>No completed steps yet.</div>"}</div>
      <div class="mt-3 border-t border-gray-800 pt-2 space-y-1">${logs || "<div class='text-xs text-gray-500'>No logs yet.</div>"}</div>
    `;
  } else if (status.last_completed) {
    const last = status.last_completed;
    const tone = String(last.status) === "passed" ? "text-green-400" : "text-red-400";
    host.innerHTML = `
      <div class="text-sm font-semibold ${tone}">Last run: ${escHtml(last.scenario_title || "scenario")} (${escHtml(last.status)})</div>
      <div class="text-xs text-gray-500 mt-1">${last.completed_steps}/${last.total_steps} step(s) in ${last.elapsed_seconds}s</div>`;
  } else {
    host.innerHTML = `<div class="text-sm text-gray-500">No scenario run in progress.</div>`;
  }

  if (status.paused && status.manual_checkpoint) {
    const cpData = status.manual_checkpoint;
    cp.classList.remove("hidden");
    cp.innerHTML = `
      <div class="text-xs text-amber-300 mb-2">Manual checkpoint active</div>
      <div class="text-xs text-gray-300 mb-2">${escHtml(cpData.instruction || "Follow analyst instruction")}</div>
      <div class="flex gap-2">
        <input id="scenario-checkpoint-note" type="text" placeholder="Optional note" class="flex-1 bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100" />
        <button onclick="scenarioResumeCheckpoint()" class="bg-amber-700 hover:bg-amber-600 text-white text-xs font-semibold px-3 py-1.5 rounded">Resume</button>
      </div>
    `;
  } else {
    cp.classList.add("hidden");
    cp.innerHTML = "";
  }
}

function scenarioRenderHistory() {
  const host = document.getElementById("scenario-history");
  if (!host) return;

  if (!SCN.history.length) {
    host.innerHTML = `<div class="text-xs text-gray-500">No run history yet.</div>`;
    return;
  }

  host.innerHTML = SCN.history.slice(0, 20).map((run) => {
    const status = String(run.status || "unknown").toUpperCase();
    return `
      <div class="border border-gray-800 rounded p-2 bg-gray-900">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs text-gray-200">${escHtml(run.scenario_title || run.scenario_id || "scenario")}</div>
          <span class="text-[10px] px-2 py-0.5 rounded ${scenarioStatusClass(run.status)}">${escHtml(status)}</span>
        </div>
        <div class="text-[11px] text-gray-500 mt-1">${scenarioFormatDate(run.started_at)} - ${run.completed_steps}/${run.total_steps} step(s)</div>
      </div>`;
  }).join("");
}

function scenarioRenderAssertionPreview() {
  const host = document.getElementById("scenario-assertion-preview");
  if (!host) return;
  scenarioEnsureEditing();

  const assertions = SCN.editing.assertions || [];
  const detector = SCN.editing.detector_expectations || [];

  if (!assertions.length && !detector.length) {
    host.innerHTML = `<div class="text-xs text-gray-500">No assertions configured.</div>`;
    return;
  }

  host.innerHTML = `
    <div class="mb-2">
      <div class="text-xs font-semibold text-gray-300 mb-1">Assertions</div>
      <div class="space-y-1">${assertions.map((a) => `<div class="text-[11px] text-gray-400">- ${escHtml(a)}</div>`).join("") || "<div class='text-[11px] text-gray-500'>None</div>"}</div>
    </div>
    <div>
      <div class="text-xs font-semibold text-gray-300 mb-1">Detector expectations</div>
      <div class="space-y-1">${detector.map((d) => `<div class="text-[11px] text-gray-400">- ${escHtml(d)}</div>`).join("") || "<div class='text-[11px] text-gray-500'>None</div>"}</div>
    </div>`;
}

function scenarioBuildPayloadFromForm() {
  scenarioEnsureEditing();

  return {
    title: String(document.getElementById("scenario-title")?.value || "").trim(),
    description: String(document.getElementById("scenario-description")?.value || "").trim(),
    category: String(document.getElementById("scenario-category")?.value || "").trim(),
    family: String(document.getElementById("scenario-family")?.value || "").trim(),
    tags: String(document.getElementById("scenario-tags")?.value || "")
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean),
    risk_level: String(document.getElementById("scenario-risk")?.value || "medium").trim().toLowerCase(),
    platforms: String(document.getElementById("scenario-platforms")?.value || "any")
      .split(",")
      .map((v) => v.trim().toLowerCase())
      .filter(Boolean),
    auth_required: Boolean(document.getElementById("scenario-auth-required")?.checked),
    prerequisites: scenarioNormalizeList(document.getElementById("scenario-prerequisites")?.value),
    steps: SCN.editing.steps,
    assertions: scenarioNormalizeList(document.getElementById("scenario-assertions")?.value),
    expected_observables: scenarioNormalizeList(document.getElementById("scenario-observables")?.value),
    detector_expectations: scenarioNormalizeList(document.getElementById("scenario-detectors")?.value),
    cleanup_steps: scenarioNormalizeList(document.getElementById("scenario-cleanup")?.value),
    status: SCN.editing.status || "idle",
    metadata: SCN.editing.metadata || {},
  };
}

function scenarioValidateEditing() {
  scenarioEnsureEditing();
  const payload = scenarioBuildPayloadFromForm();

  if (!payload.title) return "Scenario title is required.";
  if (!payload.category) return "Category is required.";
  if (!payload.family) return "Family is required.";
  if (!payload.steps || !payload.steps.length) return "At least one step is required.";

  for (let i = 0; i < payload.steps.length; i += 1) {
    const step = payload.steps[i];
    const def = scenarioStepDef(step.type);
    if (!def) return `Step ${i + 1} has unsupported type.`;
    for (const field of (def.fields || [])) {
      if (!field.required) continue;
      const val = step.params ? step.params[field.name] : undefined;
      if (val === undefined || val === null || String(val).trim() === "") {
        return `Step ${i + 1} is missing ${field.label}.`;
      }
    }
  }

  return "";
}

async function scenarioLoadMeta() {
  SCN.meta = await scenarioFetchJson("/api/scenarios/meta");
}

async function scenarioLoadScenarios() {
  const data = await scenarioFetchJson(`/api/scenarios${scenarioBuildQuery()}`);
  SCN.scenarios = data.items || [];
  SCN.filtered = SCN.scenarios.filter((item) => scenarioMatchesClientModeFilters(item));
}

async function scenarioLoadQueue() {
  const data = await scenarioFetchJson("/api/scenarios/queue");
  SCN.queue = data.items || [];
}

async function scenarioLoadHistory() {
  const data = await scenarioFetchJson("/api/scenarios/runs?limit=30");
  SCN.history = data.items || [];
}

async function scenarioLoadRunStatus() {
  SCN.runStatus = await scenarioFetchJson("/api/scenarios/run/status");
}

function scenarioPopulateSelectors() {
  if (!SCN.meta) return;

  const categorySelect = document.getElementById("scenario-category");
  if (categorySelect && categorySelect.options.length <= 1) {
    const categories = SCN.meta.categories || [];
    categorySelect.innerHTML = categories.map((item) => `<option value="${escHtml(item)}">${escHtml(item)}</option>`).join("");
  }
}

async function scenarioRefresh() {
  try {
    if (!SCN.meta) await scenarioLoadMeta();
    scenarioSetFilterStateFromUI();
    await scenarioLoadScenarios();
    await scenarioLoadQueue();
    await scenarioLoadHistory();
    await scenarioLoadRunStatus();
    scenarioPopulateSelectors();
    scenarioRenderTree();
    scenarioRenderQueue();
    scenarioRenderRunStatus();
    scenarioRenderHistory();
    scenarioRenderTemplateList();

    if (SCN.selectedId) {
      const exists = SCN.filtered.some((item) => item.id === SCN.selectedId);
      if (!exists) SCN.selectedId = "";
    }

    if (!SCN.selectedId && SCN.filtered.length) {
      SCN.selectedId = SCN.filtered[0].id;
      await scenarioSelect(SCN.selectedId);
    } else if (!SCN.selectedId) {
      SCN.editing = scenarioBlank();
      scenarioRenderEditor();
    }
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Scenario refresh failed: ${err}`, ts: now() });
  }
}

async function scenarioSelect(id) {
  try {
    const scenario = await scenarioFetchJson(`/api/scenarios/${id}`);
    SCN.selectedId = id;
    SCN.editing = scenario;
    scenarioRenderTree();
    scenarioRenderEditor();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Scenario load failed: ${err}`, ts: now() });
  }
}

function scenarioCreateNew() {
  SCN.selectedId = "";
  SCN.editing = scenarioBlank();
  scenarioRenderTree();
  scenarioRenderEditor();
}

function scenarioBuildDraftFromTemplate(templateScenario, templateMeta) {
  const draft = JSON.parse(JSON.stringify(templateScenario || scenarioBlank()));
  const templateTitle = String(templateMeta && templateMeta.title ? templateMeta.title : "");
  const sourceTitle = String(draft.title || templateTitle || "New Scenario from Template");

  draft.id = "";
  draft.title = sourceTitle.replace(/^Template\s*-\s*/i, "").trim() || "New Scenario from Template";
  draft.description = String(draft.description || (templateMeta && templateMeta.description) || "");
  draft.category = String(draft.category || (templateMeta && templateMeta.recommended_category) || "IDE Assistants");
  draft.family = String(draft.family || (templateMeta && templateMeta.recommended_family) || "General");
  draft.status = "idle";
  draft.created_date = null;
  draft.last_run_date = null;

  draft.tags = Array.isArray(draft.tags)
    ? draft.tags.filter((tag) => String(tag).toLowerCase() !== "template")
    : [];

  if (!Array.isArray(draft.steps) || !draft.steps.length) {
    draft.steps = scenarioBlank().steps;
  }

  draft.metadata = {
    ...(draft.metadata || {}),
    source: "template_quick_create",
    is_template: false,
    template_id: String(templateMeta && templateMeta.template_id ? templateMeta.template_id : ""),
  };

  return draft;
}

async function scenarioQuickCreateFromTemplate(templateId) {
  try {
    const templates = (SCN.meta && SCN.meta.templates) ? SCN.meta.templates : [];
    const templateMeta = templates.find((tpl) => tpl.template_id === templateId);
    if (!templateMeta) {
      alert("Template metadata not found.");
      return;
    }

    let templateScenario = null;
    const scenarioId = String(templateMeta.scenario_id || "").trim();

    if (scenarioId) {
      try {
        templateScenario = await scenarioFetchJson(`/api/scenarios/${encodeURIComponent(scenarioId)}`);
      } catch (_) {
        templateScenario = null;
      }
    }

    SCN.selectedId = "";
    SCN.editing = scenarioBuildDraftFromTemplate(templateScenario, templateMeta);
    scenarioRenderTree();
    scenarioRenderEditor();

    appendTerminalLine({
      level: "INFO",
      category: "SCENARIO",
      message: `Template loaded for editing: ${SCN.editing.title}`,
      ts: now(),
    });
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Template quick-create failed: ${err}`, ts: now() });
  }
}

function scenarioAddStep() {
  scenarioEnsureEditing();
  const defs = scenarioStepDefs();
  const first = defs[0] || { type: "wait", fields: [{ name: "seconds", default: 1 }] };
  const params = {};
  (first.fields || []).forEach((field) => {
    params[field.name] = field.default !== undefined ? field.default : "";
  });
  SCN.editing.steps.push({
    id: `step-${SCN.editing.steps.length + 1}`,
    type: first.type,
    params,
    notes: "",
  });
  scenarioRenderStepRows();
}

function scenarioStepDelete(index) {
  scenarioEnsureEditing();
  SCN.editing.steps.splice(index, 1);
  scenarioRenderStepRows();
}

function scenarioStepTypeChanged(index, nextType) {
  scenarioEnsureEditing();
  const def = scenarioStepDef(nextType);
  const params = {};
  (def && def.fields ? def.fields : []).forEach((field) => {
    params[field.name] = field.default !== undefined ? field.default : "";
  });
  SCN.editing.steps[index].type = nextType;
  SCN.editing.steps[index].params = params;
  scenarioRenderStepRows();
}

function scenarioStepFieldChanged(index, key, value, inputType) {
  scenarioEnsureEditing();
  const step = SCN.editing.steps[index];
  if (!step) return;
  step.params = step.params || {};

  if (inputType === "checkbox") {
    step.params[key] = Boolean(value);
    return;
  }

  if (inputType === "number") {
    const numeric = Number(value);
    step.params[key] = Number.isFinite(numeric) ? numeric : value;
    return;
  }

  step.params[key] = value;
}

async function scenarioSave() {
  try {
    const error = scenarioValidateEditing();
    if (error) {
      alert(error);
      return;
    }

    const payload = scenarioBuildPayloadFromForm();
    if (SCN.selectedId) {
      await scenarioFetchJson(`/api/scenarios/${SCN.selectedId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      appendTerminalLine({ level: "SUCCESS", category: "SCENARIO", message: `Scenario updated: ${payload.title}`, ts: now() });
    } else {
      const created = await scenarioFetchJson("/api/scenarios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      SCN.selectedId = created.id;
      appendTerminalLine({ level: "SUCCESS", category: "SCENARIO", message: `Scenario created: ${payload.title}`, ts: now() });
    }

    await scenarioRefresh();
    if (SCN.selectedId) await scenarioSelect(SCN.selectedId);
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Scenario save failed: ${err}`, ts: now() });
  }
}

async function scenarioDeleteSelected() {
  if (!SCN.selectedId) {
    alert("Select a scenario first.");
    return;
  }
  if (!window.confirm("Delete selected scenario? This cannot be undone.")) {
    return;
  }

  try {
    await scenarioFetchJson(`/api/scenarios/${SCN.selectedId}`, { method: "DELETE" });
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: `Scenario deleted: ${SCN.selectedId}`, ts: now() });
    SCN.selectedId = "";
    SCN.editing = scenarioBlank();
    await scenarioRefresh();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Scenario delete failed: ${err}`, ts: now() });
  }
}

async function scenarioDuplicateSelected() {
  if (!SCN.selectedId) {
    alert("Select a scenario first.");
    return;
  }
  try {
    const cloned = await scenarioFetchJson(`/api/scenarios/${SCN.selectedId}/duplicate`, { method: "POST" });
    SCN.selectedId = cloned.id;
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: `Scenario duplicated: ${cloned.title}`, ts: now() });
    await scenarioRefresh();
    await scenarioSelect(cloned.id);
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Scenario duplicate failed: ${err}`, ts: now() });
  }
}

async function scenarioQueueSelected() {
  if (!SCN.selectedId) {
    alert("Select a scenario first.");
    return;
  }
  try {
    await scenarioFetchJson(`/api/scenarios/queue/${SCN.selectedId}`, { method: "POST" });
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: `Queued scenario: ${SCN.selectedId}`, ts: now() });
    await scenarioLoadQueue();
    scenarioRenderQueue();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Queue failed: ${err}`, ts: now() });
  }
}

async function scenarioQueueRemove(scenarioId) {
  try {
    await scenarioFetchJson(`/api/scenarios/queue/${scenarioId}`, { method: "DELETE" });
    await scenarioLoadQueue();
    scenarioRenderQueue();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Queue remove failed: ${err}`, ts: now() });
  }
}

async function scenarioClearQueue() {
  try {
    await scenarioFetchJson("/api/scenarios/queue/clear", { method: "POST" });
    await scenarioLoadQueue();
    scenarioRenderQueue();
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: "Scenario queue cleared", ts: now() });
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Queue clear failed: ${err}`, ts: now() });
  }
}

async function scenarioRunSelected() {
  if (!SCN.selectedId) {
    alert("Select a scenario first.");
    return;
  }
  try {
    await scenarioFetchJson(`/api/scenarios/run/${SCN.selectedId}`, { method: "POST" });
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: `Scenario run started: ${SCN.selectedId}`, ts: now() });
    await scenarioLoadRunStatus();
    scenarioRenderRunStatus();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Scenario run failed: ${err}`, ts: now() });
  }
}

async function scenarioRunQueue() {
  try {
    await scenarioFetchJson("/api/scenarios/queue/run", { method: "POST" });
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: "Scenario queue run started", ts: now() });
    await scenarioLoadRunStatus();
    scenarioRenderRunStatus();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Queue run failed: ${err}`, ts: now() });
  }
}

async function scenarioResumeCheckpoint() {
  const note = String(document.getElementById("scenario-checkpoint-note")?.value || "").trim();
  try {
    await scenarioFetchJson("/api/scenarios/run/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: "Manual checkpoint resumed", ts: now() });
    await scenarioLoadRunStatus();
    scenarioRenderRunStatus();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Resume failed: ${err}`, ts: now() });
  }
}

async function scenarioExport() {
  try {
    const payload = await scenarioFetchJson("/api/scenarios/export");
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `scenario-library-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    appendTerminalLine({ level: "INFO", category: "SCENARIO", message: "Scenario library exported", ts: now() });
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Export failed: ${err}`, ts: now() });
  }
}

function scenarioTriggerImport() {
  const input = document.getElementById("scenario-import-input");
  if (input) input.click();
}

async function scenarioHandleImportFile(event) {
  const file = event.target && event.target.files ? event.target.files[0] : null;
  if (!file) return;

  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const payload = Array.isArray(parsed) ? { scenarios: parsed, mode: "merge" } : { ...parsed, mode: parsed.mode || "merge" };

    await scenarioFetchJson("/api/scenarios/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    appendTerminalLine({ level: "SUCCESS", category: "SCENARIO", message: `Scenario import complete: ${file.name}`, ts: now() });
    await scenarioRefresh();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "SCENARIO", message: `Import failed: ${err}`, ts: now() });
  } finally {
    if (event.target) event.target.value = "";
  }
}

async function scenarioApplyFilters() {
  await scenarioRefresh();
}

function initScenarioPage() {
  if (!SCN.initialized) {
    SCN.initialized = true;
    SCN.editing = scenarioBlank();
    SCN.pollId = setInterval(async () => {
      try {
        await scenarioLoadRunStatus();
        await scenarioLoadQueue();
        await scenarioLoadHistory();
        scenarioRenderQueue();
        scenarioRenderRunStatus();
        scenarioRenderHistory();
      } catch (_) {
        // Keep polling silently.
      }
    }, 3000);
  }
  scenarioRefresh();
}

window.initScenarioPage = initScenarioPage;
window.scenarioRefresh = scenarioRefresh;
window.scenarioApplyFilters = scenarioApplyFilters;
window.scenarioSelect = scenarioSelect;
window.scenarioCreateNew = scenarioCreateNew;
window.scenarioQuickCreateFromTemplate = scenarioQuickCreateFromTemplate;
window.scenarioSave = scenarioSave;
window.scenarioDeleteSelected = scenarioDeleteSelected;
window.scenarioDuplicateSelected = scenarioDuplicateSelected;
window.scenarioQueueSelected = scenarioQueueSelected;
window.scenarioQueueRemove = scenarioQueueRemove;
window.scenarioClearQueue = scenarioClearQueue;
window.scenarioRunSelected = scenarioRunSelected;
window.scenarioRunQueue = scenarioRunQueue;
window.scenarioResumeCheckpoint = scenarioResumeCheckpoint;
window.scenarioExport = scenarioExport;
window.scenarioTriggerImport = scenarioTriggerImport;
window.scenarioHandleImportFile = scenarioHandleImportFile;
window.scenarioAddStep = scenarioAddStep;
window.scenarioStepDelete = scenarioStepDelete;
window.scenarioStepTypeChanged = scenarioStepTypeChanged;
window.scenarioStepFieldChanged = scenarioStepFieldChanged;
