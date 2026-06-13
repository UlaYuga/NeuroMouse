import assert from "node:assert/strict";
import test from "node:test";

import { BackendClient } from "./backend-client.js";

function extractSessionListValue(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (Array.isArray(value.sessions)) return value.sessions;
  if (Array.isArray(value.items)) return value.items;
  if (Array.isArray(value.data)) return value.data;
  return [];
}

function parseSetCookieHeaders(response) {
  if (typeof response.headers.getSetCookie === "function") {
    return response.headers.getSetCookie() ?? [];
  }
  const singleHeader = response.headers.get("set-cookie");
  if (!singleHeader) return [];
  return [singleHeader];
}

function createCookieFetch(baseUrl) {
  const cookieJar = new Map();
  const origin = new URL(baseUrl).origin;

  const serializeCookies = () => {
    return [...cookieJar.entries()].map(([name, value]) => `${name}=${value}`).join("; ");
  };

  const rememberCookies = (response) => {
    for (const setCookie of parseSetCookieHeaders(response)) {
      const segment = String(setCookie).split(";")[0].trim();
      const separator = segment.indexOf("=");
      if (separator < 1) continue;
      const name = segment.slice(0, separator).trim();
      const value = segment.slice(separator + 1).trim();
      cookieJar.set(name, value);
    }
  };

  return async (url, options = {}) => {
    const targetUrl = new URL(String(url), origin);
    const headers = new Headers(options.headers);
    const cookieHeader = serializeCookies();
    if (cookieHeader) headers.set("cookie", cookieHeader);
    const response = await fetch(targetUrl, {
      ...options,
      headers,
      credentials: "include",
    });
    rememberCookies(response);
    return response;
  };
}

test("e2e auth flow against running backend", async (t) => {
  const baseUrl = process.env.NEUROMOUSE_BACKEND_URL ?? "http://127.0.0.1:8000";
  // Live integration test: skip cleanly when no backend is reachable.
  try {
    await globalThis.fetch(new URL("/health", baseUrl), { signal: AbortSignal.timeout(2000) });
  } catch {
    t.skip("no backend reachable — live e2e auth flow skipped");
    return;
  }
  const fetch = createCookieFetch(baseUrl);
  const client = new BackendClient({ baseUrl, fetch });

  const sampleDataset = {
    meta: {
      channels: ["Cz", "Pz"],
    },
    geometry: {
      time: [0, 1],
    },
  };

  const publicSession = await client.seedDemoDataset({
    name: "Public demo session",
    dataset: sampleDataset,
  });
  assert.ok(publicSession?.id, "seed demo session returns an id");

  const testEmail = `nm-login-${Date.now()}@example.local`;
  const testPassword = "S3cureDemoPass!";
  try {
    await client.register({
      email: testEmail,
      username: "Integration User",
      password: testPassword,
    });
  } catch (error) {
    if (!(error.status === 409 || error.status === 400)) throw error;
    await client.login({ email: testEmail, password: testPassword });
  }
  assert.equal(client.isAuthenticated(), true);

  const privateSessionName = `Private session ${Date.now()}`;
  const privateSession = await client.createSession({
    name: privateSessionName,
    dataset: sampleDataset,
  });
  assert.equal(privateSession?.name ?? privateSession?.id, privateSessionName);

  const sessions = extractSessionListValue(await client.listSessions());
  assert.ok(Array.isArray(sessions), "listSessions returns a list");
  assert.ok(
    sessions.some((item) => item?.name === privateSessionName || item?.id === privateSession?.id),
    "private session appears after login",
  );

  await client.logout();
  assert.equal(client.isAuthenticated(), false);

  await assert.rejects(
    () => client.createSession({
      name: `${privateSessionName}-again`,
      dataset: sampleDataset,
    }),
    (error) => {
      assert.ok(error instanceof Error, "error is thrown");
      return error.status === 401 || error.status === 403;
    },
  );

  const demoAfterLogout = await client.seedDemoDataset({
    name: "Public demo session after logout",
    dataset: sampleDataset,
  });
  assert.ok(demoAfterLogout?.id, "public seed still works logged out");
});
