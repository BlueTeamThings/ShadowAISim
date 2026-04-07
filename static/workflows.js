/* Shadow AI Simulator — Workflow Builder page */

const WF = {
  initialized: false,
  workflows: [],
  history: [],
  runStatus: null,
  meta: null,
  editing: null,
  selected: new Set(),
  pollId: null,
};

const COMMON_APPLICATIONS = [
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

const COMMON_EXTENSIONS = [
  "GitHub.copilot",
  "GitHub.copilot-chat",
  "ms-python.python",
  "ms-toolsai.jupyter",
  "esbenp.prettier-vscode",
  "dbaeumer.vscode-eslint",
  "ms-vscode.vscode-typescript-next",
];

const COMMON_WEBSITES = [
  "https://chatgpt.com",
  "https://claude.ai",
  "https://gemini.google.com",
  "https://perplexity.ai",
  "https://huggingface.co/chat",
  "https://copilot.microsoft.com",
];

const WorkflowState = window.WorkflowState || null;

function workflowBlank() {
  return {
    id: "",
    name: "",
    description: "",
    platform: "any",
    enabled: true,
    tags: [],
    steps: [
      {
        id: "step-1",
        type: "install_application",
        params: { app_name: "" },
        notes: "",
      },
    ],
    assertions: [],
    metadata: {},
    status: "idle",
  };
}

async function workflowFetchJson(url, options) {
  const resp = await fetch(url, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || `Request failed (${resp.status})`);
  }
  return data;
}

function workflowStatusClass(status) {
  const map = {
    passed: "bg-green-900 text-green-300",
    failed: "bg-red-900 text-red-300",
    running: "bg-indigo-900 text-indigo-300",
    idle: "bg-gray-800 text-gray-300",
  };
  return map[String(status || "").toLowerCase()] || "bg-gray-800 text-gray-300";
}

function workflowFormatDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

function workflowStepDefs() {
  return (WF.meta && WF.meta.step_types) ? WF.meta.step_types : [];
}

function workflowStepDef(type) {
  return workflowStepDefs().find((s) => s.type === type) || null;
}

function workflowUniqueStrings(items) {
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

function workflowSuggestedApplications() {
  const metaApps = ((WF.meta && WF.meta.apps) ? WF.meta.apps : [])
    .map((item) => String(item && item.name ? item.name : "").trim())
    .filter(Boolean);
  return workflowUniqueStrings([...COMMON_APPLICATIONS, ...metaApps]);
}

function workflowSuggestionOptions(stepType, fieldName) {
  const type = String(stepType || "").trim();
  const field = String(fieldName || "").trim();

  if ((type === "install_application" || type === "close_application") && field === "app_name") {
    return workflowSuggestedApplications();
  }

  if ((type === "install_extension" || type === "install_browser_extension") && field === "extension_id") {
    return COMMON_EXTENSIONS;
  }

  if (type === "open_website" && field === "url") {
    return COMMON_WEBSITES;
  }

  return [];
}

function workflowEnsureEditing() {
  if (!WF.editing) {
    WF.editing = workflowBlank();
  }
}

function workflowShowError(message) {
  const host = document.getElementById("workflow-form-error");
  if (!host) return;

  const text = String(message || "").trim();
  if (!text) {
    host.classList.add("hidden");
    host.textContent = "";
    return;
  }

  host.textContent = text;
  host.classList.remove("hidden");
}

function workflowGetEditorFormValues() {
  return {
    name: String(document.getElementById("workflow-name")?.value || ""),
    description: String(document.getElementById("workflow-description")?.value || ""),
    platform: String(document.getElementById("workflow-platform")?.value || "any"),
    enabled: Boolean(document.getElementById("workflow-enabled")?.checked),
    tags: String(document.getElementById("workflow-tags")?.value || ""),
  };
}

function workflowSyncEditingFromForm() {
  workflowEnsureEditing();
  const values = workflowGetEditorFormValues();

  if (WorkflowState && typeof WorkflowState.syncDraftFromFormValues === "function") {
    WorkflowState.syncDraftFromFormValues(WF.editing, values);
    return;
  }

  WF.editing.name = values.name.trim();
  WF.editing.description = values.description.trim();
  WF.editing.platform = values.platform.trim().toLowerCase() || "any";
  WF.editing.enabled = Boolean(values.enabled);
  WF.editing.tags = values.tags
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function workflowFieldChanged(field, value) {
  workflowEnsureEditing();

  if (WorkflowState && typeof WorkflowState.applyFieldChange === "function") {
    WorkflowState.applyFieldChange(WF.editing, field, value);
    return;
  }

  if (field === "enabled") {
    WF.editing.enabled = Boolean(value);
    return;
  }

  if (field === "tags") {
    WF.editing.tags = String(value || "")
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    return;
  }

  WF.editing[field] = String(value || "");
}

function workflowGetEditingState() {
  workflowEnsureEditing();
  return JSON.parse(JSON.stringify(WF.editing));
}

function workflowRenderTable() {
  const body = document.getElementById("workflow-table-body");
  if (!body) return;

  if (!WF.workflows.length) {
    body.innerHTML = `<tr><td colspan="9" class="px-3 py-6 text-center text-sm text-gray-500">No workflows found. Create your first workflow.</td></tr>`;
    return;
  }

  body.innerHTML = WF.workflows.map((wf) => {
    const isSelected = WF.selected.has(wf.id);
    const tags = (wf.tags || []).map((t) => `<span class="inline-flex items-center px-2 py-0.5 rounded bg-gray-800 text-[10px] text-gray-300 mr-1">${escHtml(t)}</span>`).join("");
    return `
      <tr class="border-t border-gray-800 hover:bg-gray-900/50">
        <td class="px-3 py-2">
          <input type="checkbox" ${isSelected ? "checked" : ""} onchange="workflowToggleSelect('${wf.id}', this.checked)" class="accent-indigo-500" />
        </td>
        <td class="px-3 py-2 text-sm font-medium text-gray-200">${escHtml(wf.name || "")}</td>
        <td class="px-3 py-2 text-xs text-gray-400">${escHtml(wf.description || "-")}</td>
        <td class="px-3 py-2 text-xs uppercase text-gray-400">${escHtml(wf.platform || "any")}</td>
        <td class="px-3 py-2 text-xs">${tags || "<span class=\"text-gray-500\">-</span>"}</td>
        <td class="px-3 py-2 text-xs text-gray-400">${workflowFormatDate(wf.created_date)}</td>
        <td class="px-3 py-2 text-xs text-gray-400">${workflowFormatDate(wf.last_run_date)}</td>
        <td class="px-3 py-2"><span class="text-[10px] px-2 py-0.5 rounded ${workflowStatusClass(wf.status)}">${escHtml(String(wf.status || "idle").toUpperCase())}</span></td>
        <td class="px-3 py-2">
          <div class="flex flex-wrap gap-1">
            <button onclick="workflowEdit('${wf.id}')" class="text-[11px] bg-gray-800 hover:bg-gray-700 border border-gray-700 px-2 py-1 rounded">Edit</button>
            <button onclick="workflowDuplicate('${wf.id}')" class="text-[11px] bg-gray-800 hover:bg-gray-700 border border-gray-700 px-2 py-1 rounded">Duplicate</button>
            <button onclick="workflowRun('${wf.id}')" class="text-[11px] bg-indigo-900 hover:bg-indigo-800 border border-indigo-700 text-indigo-200 px-2 py-1 rounded">Run</button>
            <button onclick="workflowDelete('${wf.id}')" class="text-[11px] bg-red-950 hover:bg-red-900 border border-red-800 text-red-300 px-2 py-1 rounded">Delete</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function workflowRenderStepRows() {
  const host = document.getElementById("workflow-steps-host");
  if (!host) return;

  workflowEnsureEditing();
  const steps = WF.editing.steps || [];

  if (!steps.length) {
    host.innerHTML = `<div class="text-xs text-gray-500 border border-gray-800 rounded-lg p-3">No steps yet. Add one below.</div>`;
    return;
  }

  const defs = workflowStepDefs();
  host.innerHTML = steps.map((step, index) => {
    const def = workflowStepDef(step.type) || { fields: [] };
    const typeOptions = defs.map((d) => `<option value="${d.type}" ${d.type === step.type ? "selected" : ""}>${escHtml(d.label)}</option>`).join("");

    const fieldsHtml = (def.fields || []).map((field) => {
      const val = (step.params || {})[field.name] ?? "";
      const inputHandler = `oninput="workflowStepFieldChanged(${index}, '${field.name}', this.value)"`;
      const base = `class="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100" ${inputHandler}`;
      const suggestions = workflowSuggestionOptions(step.type, field.name);
      const datalistId = `wf-step-${index}-${step.type}-${field.name}`.replace(/[^a-zA-Z0-9_-]/g, "-");

      if (field.input === "textarea") {
        return `
          <label class="block text-[11px] text-gray-400 mb-2">
            ${escHtml(field.label)}${field.required ? " *" : ""}
            <textarea ${base} rows="2" placeholder="${escHtml(field.placeholder || "")}">${escHtml(String(val))}</textarea>
          </label>
        `;
      }

      if (field.input === "checkbox") {
        return `
          <label class="flex items-center gap-2 text-[11px] text-gray-400 mb-2">
            <input type="checkbox" ${val ? "checked" : ""} onchange="workflowStepFieldChanged(${index}, '${field.name}', this.checked)" class="accent-indigo-500" />
            ${escHtml(field.label)}${field.required ? " *" : ""}
          </label>
        `;
      }

      return `
        <label class="block text-[11px] text-gray-400 mb-2">
          ${escHtml(field.label)}${field.required ? " *" : ""}
          <input type="${field.input === "number" ? "number" : "text"}" ${base} ${suggestions.length ? `list="${datalistId}"` : ""} value="${escHtml(String(val))}" placeholder="${escHtml(field.placeholder || "")}" />
          ${suggestions.length ? `<datalist id="${datalistId}">${suggestions.map((opt) => `<option value="${escHtml(opt)}"></option>`).join("")}</datalist>` : ""}
        </label>
      `;
    }).join("");

    const osSupport = (def.os_support || []).join(" / ").toUpperCase();

    return `
      <div class="border border-gray-800 rounded-lg p-3 bg-gray-900">
        <div class="flex items-center justify-between gap-2 mb-2">
          <div class="text-xs font-semibold text-gray-300">Step ${index + 1}</div>
          <button onclick="workflowStepDelete(${index})" class="text-[11px] bg-red-950 hover:bg-red-900 border border-red-800 text-red-300 px-2 py-1 rounded">Remove</button>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mb-2">
          <label class="block text-[11px] text-gray-400">
            Step Type
            <select class="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-100" onchange="workflowStepTypeChanged(${index}, this.value)">
              ${typeOptions}
            </select>
          </label>
          <div class="text-[11px] text-gray-500 flex items-end">OS support: ${escHtml(osSupport || "ANY")}</div>
        </div>

        <div>${fieldsHtml}</div>
      </div>
    `;
  }).join("");
}

function workflowRenderEditor() {
  workflowEnsureEditing();

  const title = document.getElementById("workflow-editor-title");
  const idLabel = document.getElementById("workflow-editor-id");
  const nameInput = document.getElementById("workflow-name");
  const descInput = document.getElementById("workflow-description");
  const platformInput = document.getElementById("workflow-platform");
  const tagsInput = document.getElementById("workflow-tags");
  const enabledInput = document.getElementById("workflow-enabled");

  if (title) title.textContent = WF.editing.id ? "Edit Workflow" : "Create Workflow";
  if (idLabel) idLabel.textContent = WF.editing.id || "new";
  if (nameInput) nameInput.value = WF.editing.name || "";
  if (descInput) descInput.value = WF.editing.description || "";
  if (platformInput) platformInput.value = WF.editing.platform || "any";
  if (tagsInput) tagsInput.value = (WF.editing.tags || []).join(", ");
  if (enabledInput) enabledInput.checked = WF.editing.enabled !== false;

  workflowRenderStepRows();
}

function workflowRenderRunStatus() {
  const host = document.getElementById("workflow-run-status");
  if (!host) return;

  const status = WF.runStatus || {};
  const current = status.current_run;

  if (current && status.running) {
    const stepRows = (current.step_results || []).map((step) => {
      const tone = step.success ? "text-green-400" : "text-red-400";
      return `<div class="text-xs ${tone}">Step ${step.index}: ${escHtml(step.type)} - ${escHtml(step.message || "")}</div>`;
    }).join("");

    const logs = (current.logs || []).slice(-8).map((entry) => {
      const ts = new Date(entry.ts * 1000).toLocaleTimeString();
      return `<div class="text-[11px] text-gray-400"><span class="text-gray-600">${ts}</span> <span class="text-gray-500">${escHtml(entry.level)}</span> ${escHtml(entry.message)}</div>`;
    }).join("");

    host.innerHTML = `
      <div class="flex items-center gap-2 mb-3">
        <span class="spin text-indigo-400 text-lg">⟳</span>
        <div>
          <div class="text-sm font-semibold text-indigo-300">Running: ${escHtml(current.workflow_name || "workflow")}</div>
          <div class="text-xs text-gray-500">Step ${current.current_step} of ${current.total_steps} • ${current.elapsed_seconds || 0}s elapsed</div>
        </div>
      </div>
      <div class="space-y-1 mb-3">${stepRows || "<div class='text-xs text-gray-500'>No steps completed yet.</div>"}</div>
      <div class="border-t border-gray-800 pt-2 space-y-1">${logs || "<div class='text-xs text-gray-500'>No logs yet.</div>"}</div>
    `;
    return;
  }

  const last = status.last_completed;
  if (last) {
    const className = last.status === "passed" ? "text-green-400" : "text-red-400";
    host.innerHTML = `
      <div class="text-sm font-semibold ${className}">Last run: ${escHtml(last.workflow_name || "workflow")} (${escHtml(last.status)})</div>
      <div class="text-xs text-gray-500 mt-1">Completed ${last.completed_steps}/${last.total_steps} step(s) in ${last.elapsed_seconds}s</div>
    `;
    return;
  }

  host.innerHTML = `<div class="text-sm text-gray-500">No workflow run in progress.</div>`;
}

function workflowRenderHistory() {
  const host = document.getElementById("workflow-history");
  if (!host) return;

  if (!WF.history.length) {
    host.innerHTML = `<div class="text-xs text-gray-500">No run history yet.</div>`;
    return;
  }

  host.innerHTML = WF.history.slice(0, 15).map((run) => {
    const status = String(run.status || "unknown").toUpperCase();
    return `
      <div class="border border-gray-800 rounded-lg p-2 bg-gray-900">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs font-medium text-gray-200">${escHtml(run.workflow_name || run.workflow_id || "workflow")}</div>
          <span class="text-[10px] px-2 py-0.5 rounded ${workflowStatusClass(run.status)}">${escHtml(status)}</span>
        </div>
        <div class="text-[11px] text-gray-500 mt-1">${workflowFormatDate(run.started_at)} • ${run.completed_steps}/${run.total_steps} step(s) • ${run.elapsed_seconds}s</div>
      </div>
    `;
  }).join("");
}

async function workflowLoadMeta() {
  WF.meta = await workflowFetchJson("/api/workflows/meta");
}

async function workflowLoadWorkflows() {
  const payload = await workflowFetchJson("/api/workflows");
  WF.workflows = payload.items || [];
}

async function workflowLoadHistory() {
  const payload = await workflowFetchJson("/api/workflows/runs?limit=25");
  WF.history = payload.items || [];
}

async function workflowLoadRunStatus() {
  WF.runStatus = await workflowFetchJson("/api/workflows/run/status");
  workflowRenderRunStatus();
}

async function workflowRefresh() {
  try {
    if (!WF.meta) await workflowLoadMeta();
    await workflowLoadWorkflows();
    await workflowLoadHistory();
    await workflowLoadRunStatus();
    workflowRenderTable();
    workflowRenderEditor();
    workflowRenderHistory();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "WORKFLOW", message: `Workflow refresh failed: ${err}`, ts: now() });
  }
}

function workflowStartCreate() {
  WF.editing = workflowBlank();
  workflowRenderEditor();
  workflowShowError("");
}

function workflowSetEditorField(field, value) {
  workflowFieldChanged(field, value);
}

function workflowAddStep() {
  workflowEnsureEditing();
  const defs = workflowStepDefs();
  const first = defs[0] || { type: "wait", fields: [{ name: "seconds", default: 1 }] };
  const params = {};
  (first.fields || []).forEach((f) => {
    params[f.name] = (f.default !== undefined) ? f.default : "";
  });

  WF.editing.steps.push({
    id: `step-${WF.editing.steps.length + 1}`,
    type: first.type,
    params,
    notes: "",
  });
  workflowRenderStepRows();
}

function workflowStepDelete(index) {
  workflowEnsureEditing();
  WF.editing.steps.splice(index, 1);
  workflowRenderStepRows();
}

function workflowStepTypeChanged(index, nextType) {
  workflowEnsureEditing();
  const def = workflowStepDef(nextType);
  const params = {};
  (def && def.fields ? def.fields : []).forEach((field) => {
    params[field.name] = (field.default !== undefined) ? field.default : "";
  });
  WF.editing.steps[index].type = nextType;
  WF.editing.steps[index].params = params;
  workflowRenderStepRows();
}

function workflowStepFieldChanged(index, key, value) {
  workflowEnsureEditing();
  const step = WF.editing.steps[index];
  if (!step) return;
  step.params = step.params || {};
  step.params[key] = value;
}

async function workflowEdit(workflowId) {
  try {
    WF.editing = await workflowFetchJson(`/api/workflows/${workflowId}`);
    workflowRenderEditor();
    workflowShowError("");
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "WORKFLOW", message: `Load workflow failed: ${err}`, ts: now() });
  }
}

function workflowToggleSelect(workflowId, checked) {
  if (checked) WF.selected.add(workflowId);
  else WF.selected.delete(workflowId);
}

function workflowValidateEditing() {
  workflowEnsureEditing();
  workflowSyncEditingFromForm();

  if (WorkflowState && typeof WorkflowState.validateWorkflowDraft === "function") {
    return WorkflowState.validateWorkflowDraft(WF.editing, workflowStepDefs());
  }

  if (!String(WF.editing.name || "").trim()) {
    return "Name is required";
  }
  if (!Array.isArray(WF.editing.steps) || WF.editing.steps.length === 0) {
    return "At least one step is required.";
  }

  for (let i = 0; i < WF.editing.steps.length; i += 1) {
    const step = WF.editing.steps[i];
    const def = workflowStepDef(step.type);
    if (!def) return `Step ${i + 1} has unsupported type.`;

    for (const field of (def.fields || [])) {
      if (!field.required) continue;
      const value = step.params ? step.params[field.name] : null;
      if (value === undefined || value === null || String(value).trim() === "") {
        return `Step ${i + 1} is missing ${field.label}.`;
      }
    }
  }

  return "";
}

function workflowBuildPayloadFromEditor() {
  workflowEnsureEditing();
  workflowSyncEditingFromForm();

  if (WorkflowState && typeof WorkflowState.buildPayloadFromDraft === "function") {
    return WorkflowState.buildPayloadFromDraft(WF.editing);
  }

  return {
    name: String(WF.editing.name || "").trim(),
    description: String(WF.editing.description || "").trim(),
    platform: String(WF.editing.platform || "any").trim().toLowerCase() || "any",
    enabled: Boolean(WF.editing.enabled),
    tags: Array.isArray(WF.editing.tags) ? WF.editing.tags : [],
    steps: WF.editing.steps,
    assertions: WF.editing.assertions || [],
    metadata: WF.editing.metadata || {},
    status: WF.editing.status || "idle",
  };
}

async function workflowSave() {
  try {
    const validationError = workflowValidateEditing();
    if (validationError) {
      if (validationError === "Name is required") {
        workflowShowError("there is no name added");
      } else {
        workflowShowError(validationError);
      }
      return;
    }

    workflowShowError("");

    const payload = workflowBuildPayloadFromEditor();
    if (WF.editing.id) {
      await workflowFetchJson(`/api/workflows/${WF.editing.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      appendTerminalLine({ level: "SUCCESS", category: "WORKFLOW", message: `Workflow updated: ${WF.editing.name}`, ts: now() });
    } else {
      await workflowFetchJson("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      appendTerminalLine({ level: "SUCCESS", category: "WORKFLOW", message: `Workflow created: ${payload.name}`, ts: now() });
    }

    WF.editing = null;
    await workflowRefresh();
    workflowStartCreate();
  } catch (err) {
    workflowShowError(`Save failed: ${err}`);
    appendTerminalLine({ level: "ERROR", category: "WORKFLOW", message: `Save failed: ${err}`, ts: now() });
  }
}

async function workflowDuplicate(workflowId) {
  try {
    await workflowFetchJson(`/api/workflows/${workflowId}/duplicate`, { method: "POST" });
    appendTerminalLine({ level: "INFO", category: "WORKFLOW", message: `Workflow duplicated: ${workflowId}`, ts: now() });
    await workflowRefresh();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "WORKFLOW", message: `Duplicate failed: ${err}`, ts: now() });
  }
}

async function workflowDelete(workflowId) {
  const ok = window.confirm("Delete this workflow? This cannot be undone.");
  if (!ok) return;

  try {
    await workflowFetchJson(`/api/workflows/${workflowId}`, { method: "DELETE" });
    WF.selected.delete(workflowId);
    if (WF.editing && WF.editing.id === workflowId) {
      WF.editing = null;
    }
    appendTerminalLine({ level: "INFO", category: "WORKFLOW", message: `Workflow deleted: ${workflowId}`, ts: now() });
    await workflowRefresh();
    workflowRenderEditor();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "WORKFLOW", message: `Delete failed: ${err}`, ts: now() });
  }
}

async function workflowRun(workflowId) {
  try {
    await workflowFetchJson(`/api/workflows/run/${workflowId}`, { method: "POST" });
    appendTerminalLine({ level: "INFO", category: "WORKFLOW", message: `Workflow run queued: ${workflowId}`, ts: now() });
    await workflowLoadRunStatus();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "WORKFLOW", message: `Run failed: ${err}`, ts: now() });
  }
}

async function workflowRunSelected() {
  const workflowIds = Array.from(WF.selected);
  if (!workflowIds.length) {
    alert("Select at least one workflow.");
    return;
  }

  try {
    await workflowFetchJson("/api/workflows/run-selected", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow_ids: workflowIds }),
    });
    appendTerminalLine({ level: "INFO", category: "WORKFLOW", message: `Queued ${workflowIds.length} workflow(s)`, ts: now() });
    await workflowLoadRunStatus();
  } catch (err) {
    appendTerminalLine({ level: "ERROR", category: "WORKFLOW", message: `Run selected failed: ${err}`, ts: now() });
  }
}

function initWorkflowPage() {
  if (!WF.initialized) {
    WF.initialized = true;
    WF.editing = workflowBlank();
    WF.pollId = setInterval(async () => {
      try {
        await workflowLoadRunStatus();
        await workflowLoadHistory();
        workflowRenderHistory();
      } catch (_) {
        // keep polling quietly
      }
    }, 2500);
  }
  workflowRefresh();
}

window.workflowRefresh = workflowRefresh;
window.workflowStartCreate = workflowStartCreate;
window.workflowSave = workflowSave;
window.workflowAddStep = workflowAddStep;
window.workflowStepDelete = workflowStepDelete;
window.workflowStepTypeChanged = workflowStepTypeChanged;
window.workflowStepFieldChanged = workflowStepFieldChanged;
window.workflowEdit = workflowEdit;
window.workflowToggleSelect = workflowToggleSelect;
window.workflowDuplicate = workflowDuplicate;
window.workflowDelete = workflowDelete;
window.workflowRun = workflowRun;
window.workflowRunSelected = workflowRunSelected;
window.initWorkflowPage = initWorkflowPage;
window.workflowFieldChanged = workflowFieldChanged;
window.workflowSetEditorField = workflowSetEditorField;
window.__workflowGetEditingState = workflowGetEditingState;
window.__workflowValidateEditing = workflowValidateEditing;
