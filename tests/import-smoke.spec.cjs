const { test, expect } = require("@playwright/test");
const { readFile, writeFile } = require("node:fs/promises");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

const baseUrl = process.env.NEUROMOUSE_SMOKE_URL ?? process.env.SPEEDMOUSE_SMOKE_URL ?? "http://127.0.0.1:4173";
const sourcePath = join(__dirname, "../data/data.json");

test.use({
  channel: "chrome",
  viewport: { width: 1440, height: 980 },
});

test("imports saved sessions and previews the workbench report", async ({ page }) => {
  const consoleErrors = [];
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(`${baseUrl}/?smoke=demo`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("#dashboard")).toHaveAttribute("aria-busy", "false");
  await page.locator("#workbench-demo").click();
  await expect(page.locator("#session-count")).toHaveText("2/6");
  await expect(page.locator("#workbench-import-log")).toContainText("2 accepted");
  await page.locator("#workbench-report").click();
  await expect(page.locator("#workbench-report-dialog[open] .report-preview-status")).toContainText("Ready for export");
  await page.locator("#workbench-report-dismiss").click();

  await page.goto(`${baseUrl}/?smoke=import`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("#dashboard")).toHaveAttribute("aria-busy", "false");
  await page.locator("#session-file-input").setInputFiles([
    sourcePath,
    await writeSmokeTarget(),
  ]);

  await expect(page.locator("#session-count")).toHaveText("2/6");
  await expect(page.locator("#workbench-import-log")).toContainText("2 accepted");
  await expect(page.locator("#workbench-baseline-select option")).toHaveCount(2);
  await expect(page.locator("#workbench-comparisons .comparison-row")).toHaveCount(1);
  await page.locator("#workbench-report").click();
  await expect(page.locator("#workbench-report-dialog[open] .report-preview-status")).toContainText("Ready for export");
  expect(consoleErrors).toEqual([]);
});

async function writeSmokeTarget() {
  const data = JSON.parse(await readFile(sourcePath, "utf8"));
  const target = JSON.parse(JSON.stringify(data));
  target.meta = {
    ...(target.meta ?? {}),
    source: "NeuroMouse browser smoke target",
  };
  target.channel_summary = target.channel_summary.map((channel, index) => ({
    ...channel,
    alpha_relative_power: round(channel.alpha_relative_power * (1.12 + (index % 4) * 0.01)),
    sliding_alpha_relative_mean: round(channel.sliding_alpha_relative_mean * (1.11 + (index % 3) * 0.01)),
    spectral_centroid_hz: round(channel.spectral_centroid_hz + 0.9 + (index % 5) * 0.06),
    spectral_entropy: round(Math.min(1, channel.spectral_entropy + 0.012)),
  }));

  const targetPath = join(tmpdir(), "neuromouse-import-smoke-target.json");
  await writeFile(targetPath, JSON.stringify(target));
  return targetPath;
}

function round(value) {
  return Number(value.toFixed(6));
}
