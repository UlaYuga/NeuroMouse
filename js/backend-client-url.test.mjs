import test from "node:test";
import assert from "node:assert/strict";

import { BackendClient, resolveBackendBaseUrl, DEFAULT_BACKEND_BASE_URL } from "./backend-client.js";

function cleanBackendUrlEnv() {
  delete globalThis.NEUROMOUSE_BACKEND_URL;
  delete globalThis.__NEUROMOUSE_BACKEND_URL__;
  if (globalThis.window) {
    delete globalThis.window.NEUROMOUSE_BACKEND_URL;
  }
}

test("resolveBackendBaseUrl uses build-time global override when no explicit base URL provided", () => {
  cleanBackendUrlEnv();
  const previousBuildTime = globalThis.__NEUROMOUSE_BACKEND_URL__;
  globalThis.__NEUROMOUSE_BACKEND_URL__ = "https://build-time.example.invalid/base-path/";
  const resolved = resolveBackendBaseUrl("");
  if (previousBuildTime == null) {
    delete globalThis.__NEUROMOUSE_BACKEND_URL__;
  } else {
    globalThis.__NEUROMOUSE_BACKEND_URL__ = previousBuildTime;
  }
  assert.equal(resolved, "https://build-time.example.invalid/base-path");
});

test("resolveBackendBaseUrl uses window-scoped runtime config when present", () => {
  cleanBackendUrlEnv();
  globalThis.window = { NEUROMOUSE_BACKEND_URL: "https://window-env.invalid" };
  const resolved = resolveBackendBaseUrl("");
  assert.equal(resolved, "https://window-env.invalid");
});

test("resolveBackendBaseUrl defaults to same-origin (empty) so the static proxy is used", () => {
  cleanBackendUrlEnv();
  assert.equal(resolveBackendBaseUrl(""), DEFAULT_BACKEND_BASE_URL);
  assert.equal(DEFAULT_BACKEND_BASE_URL, "");
});

test("resolveBackendBaseUrl prefers explicit backendBaseUrl over env/build-time config", () => {
  cleanBackendUrlEnv();
  globalThis.window = { NEUROMOUSE_BACKEND_URL: "https://from-window.invalid" };
  globalThis.__NEUROMOUSE_BACKEND_URL__ = "https://build-time.example.invalid/base-path/";
  const resolved = resolveBackendBaseUrl("https://explicit.example.invalid/api/");
  cleanBackendUrlEnv();
  assert.equal(resolved, "https://explicit.example.invalid/api");
});

test("seedDemoDataset calls /demo/seed-mea without a request body first", async () => {
  const requestLog = [];
  const fetch = async (url, options = {}) => {
    requestLog.push({ url: String(url), options });
    if (String(url).endsWith("/demo/seed-mea")) {
      return jsonResponse({
        id: "seeded-session",
      });
    }
    throw new Error(`Unexpected request ${url}`);
  };
  const client = new BackendClient({
    baseUrl: "https://backend.local",
    fetch,
  });

  const session = await client.seedDemoDataset({
    name: "MEA seed",
    dataset: { meta: { channels: ["Cz", "Pz"] } },
    seedEndpoint: "/demo/seed-mea",
  });

  assert.equal(requestLog.length, 1);
  assert.equal(session.id, "seeded-session");
  assert.equal(requestLog[0].options.method, "POST");
  assert.equal(requestLog[0].options.body, undefined);
});

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
