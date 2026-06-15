import test from "node:test";
import assert from "node:assert/strict";

import { BackendClient } from "./backend-client.js";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("BackendClient sends credentials with every request", async () => {
  const requests = [];
  const fetch = async (url, options = {}) => {
    requests.push(options);
    if (String(url).endsWith("/sessions")) {
      return jsonResponse({ id: "session-1" }, 201);
    }
    if (String(url).endsWith("/methods")) {
      return jsonResponse([]);
    }
    return jsonResponse({ detail: "not found" }, 404);
  };

  const client = new BackendClient({ baseUrl: "http://backend.local/api", fetch });
  await client.createSession({ name: "demo", dataset: { meta: { channels: ["Cz"] } } });
  await assert.rejects(() => client.createJob("session-1", { methodId: "band_power_summary" }), (error) => {
    assert.equal(error.status, 404);
    return true;
  });
  await client.listMethods();

  for (const options of requests) {
    assert.equal(options.credentials, "include");
  }
});

test("BackendClient login and logout update in-memory auth state", async () => {
  const fetch = async (url, options = {}) => {
    if (String(url).endsWith("/auth/login")) {
      assert.equal(options.credentials, "include");
      return jsonResponse({ id: "u1", email: "demo@example.com", name: "Demo User" });
    }
    if (String(url).endsWith("/auth/logout")) {
      assert.equal(options.credentials, "include");
      return jsonResponse({ ok: true });
    }
    if (String(url).endsWith("/methods")) {
      return jsonResponse([]);
    }
    throw new Error(`Unexpected request ${url}`);
  };

  const client = new BackendClient({ baseUrl: "http://backend.local", fetch });

  const user = await client.login({ email: "demo@example.com", password: "secret" });
  assert.equal(client.isAuthenticated(), true);
  assert.equal(user.email, "demo@example.com");
  assert.equal(client.getCurrentUser().id, "u1");

  await client.logout();
  assert.equal(client.isAuthenticated(), false);
  assert.equal(client.getCurrentUser(), null);
});

test("BackendClient register follows with login so the browser receives a session", async () => {
  const requests = [];
  const fetch = async (url, options = {}) => {
    requests.push({ pathname: new URL(String(url)).pathname, options });
    if (String(url).endsWith("/auth/register")) {
      assert.equal(options.credentials, "include");
      assert.deepEqual(JSON.parse(options.body), {
        email: "new@example.com",
        password: "secret",
      });
      return jsonResponse({ id: "u2", email: "new@example.com" }, 201);
    }
    if (String(url).endsWith("/auth/login")) {
      assert.equal(options.credentials, "include");
      assert.deepEqual(JSON.parse(options.body), {
        email: "new@example.com",
        password: "secret",
      });
      return jsonResponse({ token: "session-token" });
    }
    throw new Error(`Unexpected request ${url}`);
  };

  const client = new BackendClient({ baseUrl: "http://backend.local", fetch });

  const user = await client.register({
    email: "new@example.com",
    username: "Ignored client-only name",
    password: "secret",
  });

  assert.equal(client.isAuthenticated(), true);
  assert.equal(user.email, "new@example.com");
  assert.deepEqual(requests.map((request) => request.pathname), ["/auth/register", "/auth/login"]);
});
