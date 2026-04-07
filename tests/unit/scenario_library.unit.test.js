import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ScenarioLibraryView = require("../../static/scenarios_library.js");

describe("Scenario Library rendering", () => {
  it("Library Rendering: renders one card per scenario", () => {
    const scenarios = [
      { id: "s1", title: "Scenario One", risk_level: "high", status: "idle" },
      { id: "s2", title: "Scenario Two", risk_level: "medium", status: "running" },
      { id: "s3", title: "Scenario Three", risk_level: "low", status: "passed" },
    ];

    const html = ScenarioLibraryView.renderScenarioCards(scenarios, "", {
      escHtml: (value) => String(value),
      statusClass: () => "status-pill",
    });

    document.body.innerHTML = `<div id="host">${html}</div>`;

    const cards = document.querySelectorAll("#host [data-scenario-id]");
    expect(cards.length).toBe(3);
    expect(document.getElementById("host").textContent).toContain("Scenario One");
    expect(document.getElementById("host").textContent).toContain("Scenario Three");
  });
});
