/* Shared workflow draft state helpers (browser + tests) */
(function initWorkflowState(root, factory) {
  const api = factory();
  root.WorkflowState = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis, function factory() {
  function normalizeTags(raw) {
    return String(raw || "")
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
  }

  function applyFieldChange(draft, field, value) {
    if (!draft || typeof draft !== "object") return draft;

    if (field === "enabled") {
      draft.enabled = Boolean(value);
      return draft;
    }

    if (field === "tags") {
      draft.tags = normalizeTags(value);
      return draft;
    }

    if (field === "platform") {
      draft.platform = String(value || "any").trim().toLowerCase() || "any";
      return draft;
    }

    if (field === "name" || field === "description") {
      draft[field] = String(value || "");
      return draft;
    }

    draft[field] = value;
    return draft;
  }

  function syncDraftFromFormValues(draft, formValues) {
    if (!draft || typeof draft !== "object") return draft;
    const values = formValues || {};

    applyFieldChange(draft, "name", values.name || "");
    applyFieldChange(draft, "description", values.description || "");
    applyFieldChange(draft, "platform", values.platform || "any");
    applyFieldChange(draft, "enabled", values.enabled);
    applyFieldChange(draft, "tags", values.tags || "");

    draft.name = String(draft.name || "").trim();
    draft.description = String(draft.description || "").trim();

    return draft;
  }

  function validateWorkflowDraft(draft, stepDefs) {
    const item = draft || {};
    const defs = Array.isArray(stepDefs) ? stepDefs : [];

    if (!String(item.name || "").trim()) {
      return "Name is required";
    }

    if (!Array.isArray(item.steps) || item.steps.length === 0) {
      return "At least one step is required.";
    }

    for (let i = 0; i < item.steps.length; i += 1) {
      const step = item.steps[i] || {};
      const def = defs.find((candidate) => candidate.type === step.type);
      if (!def) {
        return "Step " + (i + 1) + " has unsupported type.";
      }

      const fields = Array.isArray(def.fields) ? def.fields : [];
      for (let f = 0; f < fields.length; f += 1) {
        const field = fields[f];
        if (!field || !field.required) continue;
        const params = step.params || {};
        const value = params[field.name];
        if (value === undefined || value === null || String(value).trim() === "") {
          return "Step " + (i + 1) + " is missing " + field.label + ".";
        }
      }
    }

    return "";
  }

  function buildPayloadFromDraft(draft) {
    const item = draft || {};
    return {
      name: String(item.name || "").trim(),
      description: String(item.description || "").trim(),
      platform: String(item.platform || "any").trim().toLowerCase() || "any",
      enabled: Boolean(item.enabled),
      tags: Array.isArray(item.tags) ? item.tags : normalizeTags(item.tags || ""),
      steps: Array.isArray(item.steps) ? item.steps : [],
      assertions: Array.isArray(item.assertions) ? item.assertions : [],
      metadata: (item.metadata && typeof item.metadata === "object") ? item.metadata : {},
      status: String(item.status || "idle") || "idle",
    };
  }

  return {
    applyFieldChange,
    syncDraftFromFormValues,
    validateWorkflowDraft,
    buildPayloadFromDraft,
    normalizeTags,
  };
});
