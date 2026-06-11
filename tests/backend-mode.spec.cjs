const { test, expect } = require("@playwright/test");
const { mkdir } = require("node:fs/promises");
const { join } = require("node:path");

const appUrl = process.env.NEUROMOUSE_APP_URL ?? "http://127.0.0.1:4173";
const backendUrl = process.env.NEUROMOUSE_BACKEND_URL ?? "http://127.0.0.1:8000";
const screenshotDir = process.env.NEUROMOUSE_SCREENSHOT_DIR ?? join(__dirname, "artifacts");

test.use({
  channel: "chrome",
  viewport: { width: 1440, height: 980 },
  launchOptions: {
    args: ["--disable-web-security"],
  },
});

test("backend mode seeds the demo dataset, runs band_power_summary, and renders the method panel", async ({ page }) => {
  await page.goto(`${appUrl}/?backend=1&backendUrl=${encodeURIComponent(backendUrl)}`, {
    waitUntil: "domcontentloaded",
  });
  await expect(page.locator("#dashboard")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#backend-run-method")).toBeVisible();
  await page.locator("#backend-run-method").click();

  const panel = page.locator("#method-panel-output [data-method-panel='band_power_summary']");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Band Power Summary");
  await expect(panel.locator("tbody tr")).not.toHaveCount(0);
  await expect(page.locator("#backend-progress")).toContainText("completed");

  await mkdir(screenshotDir, { recursive: true });
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: join(screenshotDir, "backend-mode-band-power-summary.png"),
    fullPage: false,
  });
});
