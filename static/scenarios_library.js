/* Shared Scenario Library rendering helpers (browser + tests) */
(function initScenarioLibraryView(root, factory) {
  const api = factory();
  root.ScenarioLibraryView = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis, function factory() {
  function defaultEsc(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function defaultStatusClass() {
    return "bg-gray-800 text-gray-300";
  }

  function renderScenarioCards(items, selectedId, options) {
    const list = Array.isArray(items) ? items : [];
    const chosen = String(selectedId || "");
    const esc = (options && options.escHtml) ? options.escHtml : defaultEsc;
    const statusClass = (options && options.statusClass) ? options.statusClass : defaultStatusClass;

    return list.map(function toCard(item) {
      const scenario = item || {};
      const id = String(scenario.id || "");
      const title = esc(scenario.title || id || "scenario");
      const risk = esc(String(scenario.risk_level || "").toUpperCase() || "-");
      const active = id === chosen;
      const tone = active ? "bg-indigo-900 text-indigo-200" : "text-gray-400 hover:bg-gray-800";

      return "\n          <button data-scenario-id=\"" + esc(id) + "\" onclick=\"scenarioSelect('" + esc(id) + "')\""
        + " class=\"w-full text-left text-xs px-2 py-1 rounded " + tone + "\">"
        + "\n            <div class=\"flex items-center justify-between gap-2\">"
        + "\n              <span class=\"truncate\">" + title + "</span>"
        + "\n              <span class=\"text-[10px] px-1.5 py-0.5 rounded " + statusClass(scenario.status) + "\">" + risk + "</span>"
        + "\n            </div>"
        + "\n          </button>";
    }).join("");
  }

  return {
    renderScenarioCards,
  };
});
