import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const SERVER_PATH = fileURLToPath(new URL("../server.mjs", import.meta.url));

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
        JSON.stringify({
          content: [
            {
              type: "text",
              text: responseText,
            },
          ],
        }),
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
        server.close((error) => {
          if (error) reject(error);
          else resolve();
        });
      });
    },
    getRequestCount: () => requestCount,
  };
}

async function startExplainServer({
  port,
  explainToken,
  apiUrl,
  allowThirdParty = false,
  rateLimit,
  corsOrigins,
}) {
  const env = {
    ...process.env,
    PORT: String(port),
    ANTHROPIC_API_KEY: "test-anthropic-key",
    EXPLAIN_API_URL: apiUrl,
  };

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

async function withExplainServer(
  options,
  run,
) {
  const port = await getFreePort();
  const mockApi = await createMockApi();
  const envApiUrl = options.apiUrl ?? mockApi.url;

  const child = await startExplainServer({
    port,
    explainToken: options.explainToken,
    apiUrl: envApiUrl,
    allowThirdParty: options.allowThirdParty,
    rateLimit: options.rateLimit,
    corsOrigins: options.corsOrigins,
  });

  try {
    return await run({
      port,
      mockApi,
      child,
    });
  } finally {
    await stopExplainServer(child);
    await mockApi.close();
  }
}


test("POST /api/explain rejects missing and invalid token", async () => {
  await withExplainServer({ explainToken: "expected-secret", allowThirdParty: true }, async ({ port }) => {
    const payload = {
      context: { score: 12 },
      question: "What does this mean?",
    };

    const missing = await postExplain(port, undefined, payload);
    assert.equal(missing.status, 401);
    assert.match(missing.body.error, /Missing or invalid explain token/i);

    const invalid = await postExplain(port, "bad-secret", payload);
    assert.equal(invalid.status, 401);
    assert.match(invalid.body.error, /Missing or invalid explain token/i);
  });
});

test("POST /api/explain returns 200 with valid token", async () => {
  await withExplainServer({ explainToken: "expected-secret", allowThirdParty: true }, async ({ port, mockApi }) => {
    const payload = {
      context: { score: 12 },
      question: "What does this mean?",
    };

    const response = await postExplain(port, "expected-secret", payload);

    assert.equal(response.status, 200);
    assert.equal(response.body.text, "mock explanation");
    assert.equal(mockApi.getRequestCount(), 1);
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

test("POST /api/explain is disabled when EXPLAIN_TOKEN is unset", async () => {
  await withExplainServer({ explainToken: undefined }, async ({ port }) => {
    const response = await postExplain(port, "whatever", { context: { score: 12 } });

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

test("POST /api/explain rejects disallowed CORS origin", async () => {
  await withExplainServer({
    explainToken: "expected-secret",
    allowThirdParty: true,
    corsOrigins: "https://allowed.example",
  }, async ({ port }) => {
    const response = await postExplain(port, "expected-secret", {
      context: { score: 12 },
      question: "What does this mean?",
    }, {
      headers: {
        origin: "https://disallowed.example",
      },
    });

    assert.equal(response.status, 403);
    assert.equal(response.body.error, "Origin not allowed.");
  });
});
