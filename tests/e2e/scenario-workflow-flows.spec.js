const { test, expect } = require("@playwright/test");

test.describe("Scenario Builder and Scenario Library flows", () => {
  test("Scenario Builder - Happy Path", async ({ page }) => {
    const workflowName = "test-workflow-" + Date.now();

    await page.goto("/");
    await page.locator('[data-section="workflows"]').click();
    await expect(page.locator("#section-workflows")).toBeVisible();

    await page.fill("#workflow-name", workflowName);
    await page.fill("#workflow-description", "workflow description");
    await page.selectOption("#workflow-platform", "linux");
    await page.fill("#workflow-tags", "test, e2e");

    await page.locator("#workflow-steps-host select").first().selectOption("open_website");
    await page.locator('#workflow-steps-host input[placeholder="https://chatgpt.com"]').first().fill("https://chatgpt.com");

    await page.getByRole("button", { name: "Save Workflow" }).click();

    await expect(page.locator("#workflow-form-error")).toBeHidden();
    await expect(page.locator("#workflow-table-body")).toContainText(workflowName);
  });

  test("Scenario Builder - Error Path", async ({ page }) => {
    await page.goto("/");
    await page.locator('[data-section="workflows"]').click();
    await expect(page.locator("#section-workflows")).toBeVisible();

    await page.getByRole("button", { name: "Reset" }).click();
    await page.fill("#workflow-description", "desc only");
    await page.selectOption("#workflow-platform", "linux");
    await page.fill("#workflow-tags", "tag1");

    await page.getByRole("button", { name: "Save Workflow" }).click();

    await expect(page.locator("#workflow-form-error")).toBeVisible();
    await expect(page.locator("#workflow-form-error")).toHaveText("there is no name added");
  });

  test("Scenario Library - Execution Flow", async ({ page }) => {
    await page.goto("/");
    await page.locator('[data-section="scenarios"]').click();
    await expect(page.locator("#section-scenarios")).toBeVisible();

    await expect(page.locator("#scenario-tree [data-scenario-id]").first()).toBeVisible();
    await page.locator("#scenario-tree [data-scenario-id]").first().click();

    await expect.poll(async () => {
      const response = await page.request.get("/api/scenarios/run/status");
      const payload = await response.json();
      return Boolean(payload.running);
    }).toBe(false);

    await page.locator('#section-scenarios .ml-auto button:has-text("Run")').click();

    await expect.poll(async () => {
      const text = await page.locator("#scenario-run-status").textContent();
      return (text || "").trim();
    }).not.toContain("No scenario run in progress.");
  });
});
