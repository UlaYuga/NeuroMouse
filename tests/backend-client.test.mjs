import test from "node:test";
import assert from "node:assert/strict";

import { BackendClient, BackendHttpError } from "../js/backend-client.js";

const sampleDataset = {
  meta: {
    channels: ["Cz", "Pz"],
  },
};

test("BackendClient seeds via /demo/seed when available and normalizes method panel specs", async () => {
  const requests = [];
  const fetch = async (url, options = {}) => {
    requests.push({ url: String(url), options });
    if (String(url).endsWith("/demo/seed")) {
      return jsonResponse({
        session: {
          id: "seeded-session",
          name: "Backend demo",
          channel_count: 2,
          dataset_version: 1,
        },
      }, 201);
    }
    if (String(url).endsWith("/methods")) {
      return jsonResponse([
        {
          id: "band_power_summary",
          name: "Band Power Summary",
          description: "Alpha-band power by channel",
          panel_spec: {
            id: "band_power_summary",
            title: "Band Power Summary",
            kind: "table",
            field: "band_power_summary.channels",
          },
        },
      ]);
    }
    throw new Error(`Unexpected request ${url}`);
  };

  const client = new BackendClient({ baseUrl: "http://backend.local/api", fetch });

  const session = await client.seedDemoDataset({ name: "Backend demo", dataset: sampleDataset });
  const methods = await client.listMethods();

  assert.equal(session.id, "seeded-session");
  assert.equal(methods.length, 1);
  assert.deepEqual(methods[0].panelSpec, {
    id: "band_power_summary",
    title: "Band Power Summary",
    kind: "table",
    field: "band_power_summary.channels",
  });
  assert.equal(requests[0].url, "http://backend.local/api/demo/seed");
});

test("BackendClient falls back to /sessions when /demo/seed is not available", async () => {
  const requests = [];
  const fetch = async (url, options = {}) => {
    requests.push({ url: String(url), options });
    if (String(url).endsWith("/demo/seed")) {
      return jsonResponse({ detail: "missing" }, 404);
    }
    if (String(url).endsWith("/sessions")) {
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), {
        name: "Fallback demo",
        dataset: sampleDataset,
      });
      return jsonResponse({
        id: "session-1",
        name: "Fallback demo",
        channel_count: 2,
        dataset_version: 1,
        dataset: sampleDataset,
        created_at: "2026-06-11T00:00:00Z",
      }, 201);
    }
    throw new Error(`Unexpected request ${url}`);
  };

  const client = new BackendClient({ baseUrl: "http://backend.local", fetch });
  const session = await client.seedDemoDataset({ name: "Fallback demo", dataset: sampleDataset });

  assert.equal(session.id, "session-1");
  assert.deepEqual(requests.map((request) => new URL(request.url).pathname), ["/demo/seed", "/sessions"]);
});

test("BackendClient posts jobs, streams progress, and retrieves completed results", async () => {
  const events = [];
  const fetch = async (url, options = {}) => {
    const pathname = new URL(String(url)).pathname;
    if (pathname === "/sessions/session-1/jobs") {
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), {
        method_id: "band_power_summary",
        params: { min_hz: 8, max_hz: 13 },
      });
      return jsonResponse({
        id: "job-1",
        session_id: "session-1",
        dataset_version: 1,
        method_id: "band_power_summary",
        params: { min_hz: 8, max_hz: 13 },
        status: "running",
      }, 201);
    }
    if (pathname === "/jobs/job-1") {
      return jsonResponse({
        id: "job-1",
        session_id: "session-1",
        dataset_version: 1,
        method_id: "band_power_summary",
        params: { min_hz: 8, max_hz: 13 },
        status: "completed",
        result: {
          band_power_summary: {
            channels: [{ channel: "Cz", power: 0.42 }],
          },
        },
      });
    }
    throw new Error(`Unexpected request ${url}`);
  };
  const WebSocket = createMockWebSocket([
    { status: "queued" },
    { status: "running" },
    { status: "completed" },
  ]);
  const client = new BackendClient({ baseUrl: "http://backend.local", fetch, WebSocket });

  const job = await client.createJob("session-1", {
    methodId: "band_power_summary",
    params: { min_hz: 8, max_hz: 13 },
  });
  const streamed = await client.streamJobProgress(job.id, {
    onEvent: (event) => events.push(event.status),
  });
  const result = await client.getResult(job.id);

  assert.equal(job.id, "job-1");
  assert.deepEqual(streamed.map((event) => event.status), ["queued", "running", "completed"]);
  assert.deepEqual(events, ["queued", "running", "completed"]);
  assert.equal(result.status, "completed");
  assert.equal(result.result.band_power_summary.channels[0].channel, "Cz");
  assert.equal(WebSocket.urls[0], "ws://backend.local/ws/jobs/job-1");
});

test("BackendClient raises useful HTTP errors", async () => {
  const fetch = async () => jsonResponse({ detail: "Method not found" }, 404);
  const client = new BackendClient({ baseUrl: "http://backend.local", fetch });

  await assert.rejects(
    () => client.createJob("session-1", { methodId: "missing_method" }),
    (error) => {
      assert.equal(error instanceof BackendHttpError, true);
      assert.equal(error.status, 404);
      assert.match(error.message, /Method not found/);
      return true;
    },
  );
});

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function createMockWebSocket(messages) {
  class MockWebSocket extends EventTarget {
    static urls = [];

    constructor(url) {
      super();
      this.url = url;
      this.readyState = 0;
      MockWebSocket.urls.push(url);
      queueMicrotask(() => {
        this.readyState = 1;
        this.dispatchEvent(new Event("open"));
        messages.forEach((message) => {
          this.dispatchEvent(new MessageEvent("message", {
            data: JSON.stringify(message),
          }));
        });
        this.readyState = 3;
        this.dispatchEvent(new CloseEvent("close"));
      });
    }

    close() {
      this.readyState = 3;
    }
  }
  return MockWebSocket;
}
