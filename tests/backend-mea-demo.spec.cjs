const { test, expect } = require("@playwright/test");
const { mkdir } = require("node:fs/promises");
const { join } = require("node:path");

const appUrl = process.env.NEUROMOUSE_APP_URL ?? "http://127.0.0.1:4173";
const backendUrl = process.env.NEUROMOUSE_BACKEND_URL ?? "http://127.0.0.1:8000";
const screenshotDir = process.env.NEUROMOUSE_SCREENSHOT_DIR ?? join(__dirname, "artifacts");

const DEFAULT_VIEWPORT = { width: 1440, height: 980 };

function getMethodsPayload(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.methods)) return payload.methods;
  return [];
}

function pickSpikeMethod(methods = []) {
  return methods.find((method) => method?.id === "spike_detect")
    ?? methods.find((method) => {
      const id = String(method?.id ?? "");
      return /spike.?detect/i.test(id);
    })
    ?? null;
}

test.use({
  channel: "chrome",
  viewport: DEFAULT_VIEWPORT,
  launchOptions: {
    args: ["--disable-web-security"],
  },
});

test("backend mode seeds MEA demo via /demo/seed-mea and renders spike_detect", async ({ page }) => {
  const methodsResponse = await page.request.get(`${backendUrl}/methods`);
  expect(methodsResponse.ok()).toBe(true);
  const methodsPayload = await methodsResponse.json();
  const methods = getMethodsPayload(methodsPayload);

  const spikeMethod = pickSpikeMethod(methods);
  expect(spikeMethod, "backend methods should include spike_detect").not.toBeNull();

  const panelSpec = getPanelSpec(spikeMethod) ?? {
    id: spikeMethod.id,
    title: spikeMethod.name ?? "Spike Detect",
    kind: "table",
    field: spikeMethod.id,
  };
  const panelId = panelSpec.id || spikeMethod.id;
  const seedMeaResponse = await page.request.post(`${backendUrl}/demo/seed-mea`);
  expect(seedMeaResponse.ok()).toBe(true);
  const seedMeaPayload = await seedMeaResponse.json();
  const seededSessionId = seedMeaPayload.session_id ?? seedMeaPayload.session?.id ?? seedMeaPayload.id;
  expect(typeof seededSessionId).toBe("string");

  const directJobRequest = await page.request.post(`${backendUrl}/sessions/${encodeURIComponent(seededSessionId)}/jobs`, {
    data: {
      method_id: spikeMethod.id,
      params: {},
    },
    headers: {
      "Content-Type": "application/json",
    },
  });
  expect(directJobRequest.ok()).toBe(true);
  const directJobId = (await directJobRequest.json()).id;
  expect(typeof directJobId).toBe("string");
  const directJobResult = await waitForBackendJobResult(page, backendUrl, directJobId);
  expect(directJobResult.status).toBe("completed");
  const directPayload = directJobResult.result?.output ?? directJobResult.result ?? {};
  const directRows = extractPanelRows(directPayload, panelSpec);
  expect(Array.isArray(directRows)).toBe(true);
  expect(directRows.length).toBeGreaterThan(0);

  let seedMeaCalls = 0;
  await page.route(`${backendUrl}/demo/seed-mea**`, async (route) => {
    if (route.request().method() === "POST") seedMeaCalls += 1;
    await route.continue();
  });

  await page.goto(`${appUrl}/?backend=1&backendUrl=${encodeURIComponent(backendUrl)}`, {
    waitUntil: "domcontentloaded",
  });

  await expect(page.locator("#dashboard")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#backend-run-method")).toBeVisible();

  const methodSelect = page.locator("#backend-method-select");
  await expect(methodSelect).toBeVisible();
  await methodSelect.selectOption(spikeMethod.id);
  await page.locator("#backend-run-method").click();

  const panel = page.locator(`#method-panel-output [data-method-panel='${panelId}']`);
  await expect(panel).toBeVisible({ timeout: 120000 });
  await expect(page.locator("#backend-progress")).toContainText("completed", { timeout: 120000 });
  await expect(panel.locator("h2")).toContainText(panelSpec.title ?? spikeMethod.name);

  if (panelSpec.kind === "heatmap_table") {
    const rowCount = await panel.locator("table tbody tr").count();
    expect(rowCount).toBeGreaterThan(0);
    expect(rowCount).toBe(directRows.length);
  } else if (panelSpec.kind === "timeline") {
    const rowCount = await panel.locator("table tbody tr").count();
    expect(rowCount).toBeGreaterThan(0);
    expect(rowCount).toBe(directRows.length);
  } else if (panelSpec.kind === "matrix") {
    const rowCount = await panel.locator("table tbody tr").count();
    expect(rowCount).toBeGreaterThan(0);
    expect(rowCount).toBe(directRows.length);
  } else {
    expect(await panel.locator("[data-method-panel-status]").textContent()).not.toContain("No data returned");
  }

  expect(seedMeaCalls).toBeGreaterThan(0);

  await mkdir(screenshotDir, { recursive: true });
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: join(screenshotDir, "backend-demo-mea-spike-detect.png"),
    fullPage: false,
  });
});

function getPanelSpec(method) {
  return method?.panelSpec ?? method?.panel ?? method?.output_spec?.panel ?? method?.output?.panel ?? null;
}

function extractPanelRows(payload, panelSpec) {
  if (!payload || !panelSpec?.field) return [];
  const parts = String(panelSpec.field).split(".");
  let value = payload;
  for (const part of parts) {
    if (value == null) return [];
    value = value[part];
    if (value && typeof value === "string" && part === parts.at(-1)) return [value];
  }
  return Array.isArray(value) ? value : [];
}

async function waitForBackendJobResult(page, backendUrl, jobId) {
  const path = `${backendUrl}/jobs/${encodeURIComponent(jobId)}`;
  const timeoutMs = 90_000;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const response = await page.request.get(path);
    const payload = await response.json();
    if (payload.status === "completed" || payload.status === "failed") {
      return payload;
    }
    await page.waitForTimeout(250);
  }
  throw new Error(`Timed out waiting for backend job ${jobId}`);
}
