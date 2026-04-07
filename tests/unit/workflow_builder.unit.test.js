import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const WorkflowState = require("../../static/workflows_state.js");

describe("Scenario Builder (Workflow) state and validation", () => {
  function makeDraft(overrides = {}) {
    return {
      name: "",
      description: "",
      platform: "any",
      enabled: true,
      tags: [],
      steps: [{ type: "wait", params: { seconds: 1 } }],
      assertions: [],
      metadata: {},
      status: "idle",
      ...overrides,
    };
  }

  it("State Binding Test: typing updates underlying draft state", () => {
    const draft = makeDraft();

    const input = document.createElement("input");
    input.addEventListener("input", (event) => {
      WorkflowState.applyFieldChange(draft, "name", event.target.value);
    });

    input.value = "test";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    expect(draft.name).toBe("test");
  });

  it("Validation Logic Test: missing name returns Name is required", () => {
    const draft = makeDraft({
      name: "",
      steps: [{ type: "wait", params: { seconds: 1 } }],
    });

    const stepDefs = [
      {
        type: "wait",
        fields: [{ name: "seconds", label: "Seconds", required: true }],
      },
    ];

    const error = WorkflowState.validateWorkflowDraft(draft, stepDefs);
    expect(error).toBe("Name is required");
  });

  it("Dynamic Step Test: missing required step field is caught", () => {
    const draft = makeDraft({
      name: "test",
      steps: [{ type: "open_website", params: {} }],
    });

    const stepDefs = [
      {
        type: "open_website",
        fields: [{ name: "url", label: "URL", required: true }],
      },
    ];

    const error = WorkflowState.validateWorkflowDraft(draft, stepDefs);
    expect(error).toContain("Step 1 is missing URL");
  });
});
