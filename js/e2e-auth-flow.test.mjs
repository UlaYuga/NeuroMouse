import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { createRequire } from "node:module";

const { test, expect } = createRequire(import.meta.url)("@playwright/test");

const appUrl = process.env.NEUROMOUSE_APP_URL ?? "http://127.0.0.1:8080";
const backendUrl = process.env.NEUROMOUSE_BACKEND_URL ?? "http://127.0.0.1:8000";
const screenshotDir = process.env.NEUROMOUSE_SCREENSHOT_DIR ?? join(process.cwd(), "tests", "artifacts");
const PUBLIC_METHOD = "spike_detect";

const DEFAULT_VIEWPORT = { width: 1440, height: 980 };

function uniqueEmail() {
  return `nm-${Date.now()}-${Math.floor(Math.random() * 10000)}@example.test`;
}

function sanitizeRegisterPayload(payload = {}) {
  const sanitized = { ...payload };
  delete sanitized.username;
  delete sanitized.name;
  delete sanitized.displayName;
  delete sanitized.display_name;
  delete sanitized.full_name;
  delete sanitized.fullname;
  delete sanitized.handle;
  return sanitized;
}

async function routeAuthRequestsThroughNode(page, backendUrl) {
  const backendOrigin = new URL(backendUrl).origin;

  const proxy = async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    if (requestUrl.origin !== backendOrigin || request.method() !== "POST") {
      await route.fallback();
      return;
    }

    let payload = {};
    try {
      payload = request.postDataJSON();
    } catch {
      try {
        payload = JSON.parse(request.postData() || "{}");
      } catch {
        payload = {};
      }
    }

    if (requestUrl.pathname === "/auth/register") {
      payload = sanitizeRegisterPayload(payload);
    }

    const response = await page.request.fetch(request.url(), {
      method: "POST",
      headers: { "content-type": "application/json" },
      data: payload,
    });
    const responseBody = await response.text();
    if (process.env.E2E_DEBUG_AUTH === "1") {
      console.log("BRIDGE", request.method(), request.url(), response.status(), responseBody, response.headers());
    }
    const responseHeaders = {};
    const responseSetCookie = [];
    for (const header of response.headersArray()) {
      const key = header.name.toLowerCase();
      if (key === "set-cookie") {
        responseSetCookie.push(header.value);
        continue;
      }
      responseHeaders[header.name] = header.value;
    }
    if (responseSetCookie.length > 0) {
      responseHeaders["set-cookie"] = responseSetCookie[0];
    }

    await route.fulfill({
      status: response.status(),
      headers: responseHeaders,
      body: responseBody,
    });
  };

  await page.route(`${backendOrigin}/auth/register`, proxy);
  await page.route(`${backendOrigin}/auth/login`, proxy);
}

async function assertBackendReachable() {
  const response = await fetch(`${backendUrl}/demo/seed-mea`, {
    method: "POST",
    signal: AbortSignal.timeout(2000),
  });
  if (!response.ok) {
    throw new Error(`backend not ready at ${backendUrl}: /demo/seed-mea returned ${response.status}`);
  }
}

test.use({
  channel: "chrome",
  viewport: DEFAULT_VIEWPORT,
  launchOptions: {
    args: ["--disable-web-security"],
  },
});

test("backend UI auth flow: public demo run, register/login, private session lifecycle", async ({ page }) => {
  await assertBackendReachable();

  if (process.env.E2E_DEBUG_AUTH === "1") {
    page.on("request", (request) => {
      if (request.url().includes("/auth/")) {
        console.log("REQ", request.method(), request.url(), request.postData());
      }
    });
    page.on("response", (response) => {
      if (response.url().includes("/auth/")) {
        console.log("RESP", response.status(), response.url(), response.statusText());
      }
    });
  }

  await page.goto(`${appUrl}/?backend=1&backendUrl=${encodeURIComponent(backendUrl)}`, {
    waitUntil: "domcontentloaded",
  });
  await routeAuthRequestsThroughNode(page, backendUrl);

  const authMode = page.locator("#backend-auth-mode");
  const authUser = page.locator("#backend-auth-user");
  const loginForm = page.locator("#backend-login-form");
  const registerForm = page.locator("#backend-register-form");
  const logoutButton = page.locator("#backend-logout");
  const createPrivateSessionButton = page.locator("#backend-create-private-session");
  const privateSessionList = page.locator("#backend-private-session-list");
  const methodSelect = page.locator("#backend-method-select");
  const runButton = page.locator("#backend-run-method");
  const methodProgress = page.locator("#backend-progress");

  await expect(page.locator("#dashboard")).toHaveAttribute("aria-busy", "false");

  await expect(authMode).toContainText("PUBLIC demo");
  await expect(authUser).toContainText("Not signed in");
  await expect(loginForm).toBeVisible();
  await expect(registerForm).toBeVisible();
  await expect(logoutButton).toBeHidden();
  await expect(createPrivateSessionButton).toBeHidden();
  await expect(privateSessionList).toContainText("Sign in to load private sessions.");

  await methodSelect.selectOption(PUBLIC_METHOD);
  await runButton.click();
  await expect(methodProgress).toContainText(/queued|running|seed|completed/, { timeout: 60_000 });
  await expect(methodProgress).toContainText("completed", { timeout: 120_000 });

  const publicPanel = page.locator(`[data-method-panel*="${PUBLIC_METHOD}"]`).first();
  await expect(publicPanel).toBeVisible({ timeout: 120_000 });
  await expect(publicPanel.locator("h2")).toContainText(/Spike Detect|spike_detect/);
  const rowCount = publicPanel.locator("tbody tr");
  await expect(rowCount).not.toHaveCount(0);

  await mkdir(screenshotDir, { recursive: true });
  await publicPanel.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: join(screenshotDir, "auth-flow-public-demo-spike-detect.png"),
    fullPage: false,
  });

  const email = uniqueEmail();
  const password = "S3cureDemoPass!";

  await page.locator("#backend-register-email").fill(email);
  await page.locator("#backend-register-username").fill("Integration User");
  await page.locator("#backend-register-password").fill(password);
  await page.locator("#backend-register-form button[type='submit']").click();
  await expect(authMode).toContainText(/Private session/, { timeout: 20_000 });
  await expect(loginForm).toBeHidden();
  await expect(registerForm).toBeHidden();
  await expect(logoutButton).toBeVisible();

  await logoutButton.click();
  await expect(authMode).toContainText("PUBLIC demo", { timeout: 20_000 });
  await expect(logoutButton).toBeHidden();
  await expect(createPrivateSessionButton).toBeHidden();
  await expect(loginForm).toBeVisible();
  await expect(registerForm).toBeVisible();

  await page.locator("#backend-login-email").fill(email);
  await page.locator("#backend-login-password").fill(password);
  await page.locator("#backend-login-form button[type='submit']").click();

  await expect(authMode).toHaveText(/Private session/, { timeout: 20_000 });
  await expect(createPrivateSessionButton).toBeVisible();

  const privateSessionCountBefore = await privateSessionList.locator(".backend-private-session-item").count();
  await createPrivateSessionButton.click();
  await expect(privateSessionList.locator(".backend-private-session-item")).toHaveCount(privateSessionCountBefore + 1, { timeout: 120_000 });

  await privateSessionList.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: join(screenshotDir, "auth-flow-private-session.png"),
    fullPage: false,
  });

  await logoutButton.click();
  await expect(authMode).toContainText("PUBLIC demo", { timeout: 20_000 });
  await expect(privateSessionList).toContainText("Sign in to load private sessions.");
  await expect(privateSessionList.locator(".backend-private-session-item")).toHaveCount(0);
});
