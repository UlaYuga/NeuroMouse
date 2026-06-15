import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
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

async function createMockBackend() {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push({
      method: request.method,
      url: request.url,
      headers: request.headers,
    });

    if (request.url === "/demo/seed-mea" && request.method === "POST") {
      response.writeHead(201, { "content-type": "application/json" });
      response.end(JSON.stringify({
        id: "mock-mea-session",
        name: "Mock MEA seed",
      }));
      return;
    }

    response.writeHead(404, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: "not found" }));
  });

  await new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });

  const port = server.address().port;
  return {
    url: `http://127.0.0.1:${port}`,
    requests: () => [...requests],
    close: async () => {
      await new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

async function startStaticServer({ port, backendUrl }) {
  const child = spawn(process.execPath, [SERVER_PATH], {
    env: {
      ...process.env,
      PORT: String(port),
      HOST: "127.0.0.1",
      NEUROMOUSE_BACKEND_URL: backendUrl,
    },
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
  throw new Error("Static server did not start");
}

async function stopServer(child) {
  await new Promise((resolve) => {
    child.once("exit", resolve);
    child.kill("SIGTERM");
    setTimeout(() => resolve(), 1000);
  });
}

async function withStaticServer(run) {
  const port = await getFreePort();
  const backend = await createMockBackend();
  const child = await startStaticServer({ port, backendUrl: backend.url });
  try {
    return await run({ port, backend });
  } finally {
    await stopServer(child);
    await backend.close();
  }
}

async function request(port, pathname, options = {}) {
  return await fetch(`http://127.0.0.1:${port}${pathname}`, {
    redirect: "manual",
    ...options,
  });
}

test("server routes landing, workbench, docs, denylist, and backend proxy deterministically", async () => {
  await withStaticServer(async ({ port, backend }) => {
    const landing = await request(port, "/");
    assert.equal(landing.status, 200);
    assert.match(await landing.text(), /NeuroMouse/i);

    const workbench = await request(port, "/app");
    assert.equal(workbench.status, 200);
    assert.match(await workbench.text(), /NeuroMouse Workbench/i);

    const appSlash = await request(port, "/app/");
    assert.equal(appSlash.status, 301);
    assert.equal(appSlash.headers.get("location"), "/app");

    const docs = await request(port, "/docs/");
    assert.equal(docs.status, 200);
    assert.match(await docs.text(), /NeuroMouse Docs/i);

    for (const denied of ["/server.mjs", "/package.json", "/.gitignore"]) {
      const response = await request(port, denied);
      assert.equal(response.status, 404, `${denied} should not be served`);
    }

    const seed = await request(port, "/demo/seed-mea", { method: "POST" });
    assert.equal(seed.status, 201);
    assert.deepEqual(await seed.json(), {
      id: "mock-mea-session",
      name: "Mock MEA seed",
    });
    assert.deepEqual(
      backend.requests().map((item) => `${item.method} ${item.url}`),
      ["POST /demo/seed-mea"],
    );
  });
});
