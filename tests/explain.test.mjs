import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const SERVER_PATH = fileURLToPath(new URL("../server.mjs", import.meta.url));
const GOOD_COOKIE = "neuromouse_session=good";

async function getFreePort() {
  return await new Promise((resolve, reject) => {
    const sock = createServer();
    sock.on("error", reject);
    sock.listen(0, () => {
      const { port } = sock.address();
      sock.close(() => resolve(port));
    });
  });
}

async function createMockApi(responseText = "mock explanation") {
  let requestCount = 0;
  const server = createServer((request, response) => {
    requestCount += 1;
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({ content: [{ type: "text", text: responseText }] }),
      );
    });
  });

  await new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });

  const port = server.address().port;
  return {
    server,
    url: `http://127.0.0.1:${port}/v1/messages`,
    close: async () => {
      await new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
    getRequestCount: () => requestCount,
  };
}

// Mock backend for session-cookie auth: GET /auth/me returns 200 for the
// "good" session cookie and 401 otherwise — mirrors the real /auth/me lane the
// static server reaches through its same-origin proxy.
async function createMockBackend() {
  let calls = 0;
  const server = createServer((request, response) => {
    if (request.url === "/auth/me") {
      calls += 1;
      const cookie = request.headers.cookie ?? "";
      if (/neuromouse_session=good\b/.test(cookie)) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ id: "user-1", email: "u@example.io" }));
      } else {
        response.writeHead(401, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: "unauthorized" }));
      }
      return;
    }
    response.writeHead(404);
    response.end();
  });

  await new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });

  const port = server.address().port;
  return {
    url: `http://127.0.0.1:${port}`,
    getCalls: () => calls,
    close: async () => {
      await new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

async function startExplainServer({
  port,
  explainToken,
  apiUrl,
  apiKey = "test-anthropic-key",
  backendUrl,
  allowThirdParty = false,
  rateLimit,
  corsOrigins,
}) {
  const env = {
    ...process.env,
    PORT: String(port),
    EXPLAIN_API_URL: apiUrl,
  };

  if (apiKey) env.ANTHROPIC_API_KEY = apiKey;
  else delete env.ANTHROPIC_API_KEY;

  if (backendUrl) env.NEUROMOUSE_BACKEND_URL = backendUrl;
  else delete env.NEUROMOUSE_BACKEND_URL;

  if (explainToken) env.EXPLAIN_TOKEN = explainToken;
  else delete env.EXPLAIN_TOKEN;

  if (rateLimit) env.EXPLAIN_RATE_LIMIT_PER_MIN = String(rateLimit);
  else delete env.EXPLAIN_RATE_LIMIT_PER_MIN;

  if (allowThirdParty) env.EXPLAIN_ALLOW_THIRD_PARTY_API = "1";
  else delete env.EXPLAIN_ALLOW_THIRD_PARTY_API;

  if (corsOrigins) env.EXPLAIN_CORS_ALLOW_ORIGINS = corsOrigins;
  else delete env.EXPLAIN_CORS_ALLOW_ORIGINS;

  const child = spawn(process.execPath, [SERVER_PATH], {
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/healthz`);
      if (response.ok) return child;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 50));
  }

  child.kill("SIGKILL");
  throw new Error("Explain server did not start");
}

async function stopExplainServer(child) {
  await new Promise((resolve) => {
    child.once("exit", resolve);
    child.kill("SIGTERM");
    setTimeout(() => resolve(), 1000);
  });
}

async function postExplain(port, token, body, options = {}) {
  const response = await fetch(`http://127.0.0.1:${port}/api/explain`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(token ? { "x-explain-token": token } : {}),
      ...(options.headers ?? {}),
    },
    body: JSON.stringify(body),
  });
  return {
    status: response.status,
    body: await response.json(),
  };
}

async function withExplainServer(options, run) {
  const port = await getFreePort();
  const mockApi = await createMockApi();
  const mockBackend = await createMockBackend();
  const envApiUrl = options.apiUrl ?? mockApi.url;

  const child = await startExplainServer({
    port,
    explainToken: options.explainToken,
    apiUrl: envApiUrl,
    apiKey: options.apiKey === undefined ? "test-anthropic-key" : options.apiKey,
    backendUrl: options.backendUrl ?? mockBackend.url,
    allowThirdParty: options.allowThirdParty,
    rateLimit: options.rateLimit,
    corsOrigins: options.corsOrigins,
  });

  try {
    return await run({ port, mockApi, mockBackend, child });
  } finally {
    await stopExplainServer(child);
    await mockApi.close();
    await mockBackend.close();
  }
}

test("POST /api/explain rejects a request with neither a session cookie nor a token", async () => {
  await withExplainServer({ explainToken: "expected-secret", allowThirdParty: true }, async ({ port }) => {
    const payload = { context: { score: 12 }, question: "What does this mean?" };

    const missing = await postExplain(port, undefined, payload);
    assert.equal(missing.status, 401);
    assert.match(missing.body.error, /sign in/i);

    const invalid = await postExplain(port, "bad-secret", payload);
    assert.equal(invalid.status, 401);
  });
});

test("POST /api/explain returns 200 with a valid service token", async () => {
  await withExplainServer({ explainToken: "expected-secret", allowThirdParty: true }, async ({ port, mockApi }) => {
    const response = await postExplain(port, "expected-secret", {
      context: { score: 12 },
      question: "What does this mean?",
    });

    assert.equal(response.status, 200);
    assert.equal(response.body.text, "mock explanation");
    assert.equal(mockApi.getRequestCount(), 1);
  });
});

test("POST /api/explain authorizes a logged-in session cookie with no token", async () => {
  await withExplainServer({ explainToken: undefined, allowThirdParty: true }, async ({ port, mockApi, mockBackend }) => {
    const response = await postExplain(port, undefined, {
      context: { score: 12 },
      question: "What does this mean?",
    }, {
      headers: { cookie: GOOD_COOKIE },
    });

    assert.equal(response.status, 200);
    assert.equal(response.body.text, "mock explanation");
    assert.equal(mockApi.getRequestCount(), 1);
    assert.ok(mockBackend.getCalls() >= 1, "backend /auth/me should be consulted");
  });
});

test("POST /api/explain rejects an invalid session cookie when no token is set", async () => {
  await withExplainServer({ explainToken: undefined, allowThirdParty: true }, async ({ port, mockApi }) => {
    const response = await postExplain(port, undefined, { context: { score: 12 } }, {
      headers: { cookie: "neuromouse_session=bad" },
    });

    assert.equal(response.status, 401);
    assert.equal(mockApi.getRequestCount(), 0);
  });
});

test("POST /api/explain enforces rate limit", async () => {
  await withExplainServer({ explainToken: "expected-secret", allowThirdParty: true, rateLimit: 2 }, async ({ port }) => {
    const payload = { context: { score: 12 }, question: "What does this mean?" };

    const first = await postExplain(port, "expected-secret", payload);
    const second = await postExplain(port, "expected-secret", payload);
    const third = await postExplain(port, "expected-secret", payload);

    assert.equal(first.status, 200);
    assert.equal(second.status, 200);
    assert.equal(third.status, 429);
  });
});

test("POST /api/explain is disabled (503) when ANTHROPIC_API_KEY is unset", async () => {
  await withExplainServer({ explainToken: "expected-secret", apiKey: null }, async ({ port }) => {
    const response = await postExplain(port, "expected-secret", { context: { score: 12 } });

    assert.equal(response.status, 503);
    assert.equal(response.body.error, "Explain is not configured on this server.");
  });
});

test("POST /api/explain blocks non-official API hosts unless explicitly allowed", async () => {
  await withExplainServer({
    explainToken: "expected-secret",
    apiUrl: "http://localhost/v1/messages",
  }, async ({ port, mockApi }) => {
    const response = await postExplain(port, "expected-secret", {
      context: { score: 12 },
      question: "What does this mean?",
    });

    assert.equal(response.status, 403);
    assert.equal(response.body.error, "Refusing non-official explain API host without explicit opt-in.");
    assert.equal(mockApi.getRequestCount(), 0);
  });
});

test("POST /api/explain rejects a disallowed CORS origin", async () => {
  await withExplainServer({
    explainToken: "expected-secret",
    allowThirdParty: true,
    corsOrigins: "https://allowed.example",
  }, async ({ port }) => {
    const response = await postExplain(port, "expected-secret", {
      context: { score: 12 },
      question: "What does this mean?",
    }, {
      headers: { origin: "https://disallowed.example" },
    });

    assert.equal(response.status, 403);
    assert.equal(response.body.error, "Origin not allowed.");
  });
});

test("POST /api/explain allows a same-origin request without a CORS allowlist", async () => {
  await withExplainServer({ explainToken: "expected-secret", allowThirdParty: true }, async ({ port }) => {
    const response = await postExplain(port, "expected-secret", {
      context: { score: 12 },
      question: "What does this mean?",
    }, {
      headers: { origin: `http://127.0.0.1:${port}` },
    });

    assert.equal(response.status, 200);
  });
});
