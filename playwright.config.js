const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:8876",
    headless: true,
  },
  webServer: {
    command: "/home/bajack/.shadow-ai-simulator/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8876",
    port: 8876,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
