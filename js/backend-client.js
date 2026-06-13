const DEFAULT_TIMEOUT_MS = 15000;
const DEFAULT_POLL_INTERVAL_MS = 250;
const DEFAULT_DEMO_SEED_ENDPOINT = "/demo/seed";
const TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "not_found"]);
export const DEFAULT_BACKEND_BASE_URL = "https://backend-production-c7a1.up.railway.app";

export class BackendHttpError extends Error {
  constructor(message, { status, body, url } = {}) {
    super(message);
    this.name = "BackendHttpError";
    this.status = status;
    this.body = body;
    this.url = url;
  }
}

export class BackendClient {
  constructor({
    baseUrl = "",
    fetch: fetchImpl = globalThis.fetch?.bind(globalThis),
    WebSocket: WebSocketImpl = globalThis.WebSocket,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  } = {}) {
    if (typeof fetchImpl !== "function") {
      throw new Error("BackendClient requires fetch");
    }
    this.baseUrl = resolveBackendBaseUrl(baseUrl);
    this.fetch = fetchImpl;
    this.WebSocket = WebSocketImpl;
    this.timeoutMs = timeoutMs;
    this.pollIntervalMs = pollIntervalMs;
  }

  async seedDemoDataset({ name = "NeuroMouse demo dataset", dataset, seedEndpoint = DEFAULT_DEMO_SEED_ENDPOINT } = {}) {
    if (!dataset) throw new Error("seedDemoDataset requires dataset");
    const normalizedEndpoint = normalizeSeedEndpoint(seedEndpoint);
    const allowCreateSessionFallback = normalizedEndpoint === DEFAULT_DEMO_SEED_ENDPOINT;
    const allowSeedNoBody = /^\/demo\/seed/.test(normalizedEndpoint);
    const seedMeaEndpoint = /^\/demo\/seed-mea/.test(normalizedEndpoint);
    try {
      const response = await requestSeedDemo(
        this.requestJson.bind(this),
        normalizedEndpoint,
        seedMeaEndpoint
          ? { method: "POST" }
          : { method: "POST", body: { name, dataset } },
      );
      return normalizeSession(response.session ?? response);
    } catch (error) {
      if (seedMeaEndpoint) {
        const response = await requestSeedDemo(this.requestJson.bind(this), normalizedEndpoint, {
          method: "POST",
          body: { name, dataset },
        });
        return normalizeSession(response.session ?? response);
      }
      if (allowSeedNoBody && error instanceof BackendHttpError && error.status === 422 && dataset) {
        const response = await requestSeedDemo(this.requestJson.bind(this), normalizedEndpoint, {
          method: "POST",
        });
        return normalizeSession(response.session ?? response);
      }
      if (allowCreateSessionFallback && error instanceof BackendHttpError && (error.status === 404 || error.status === 405)) {
        return this.createSession({ name, dataset });
      }
      throw error;
    }
  }

  async createSession({ name = null, dataset } = {}) {
    if (!dataset) throw new Error("createSession requires dataset");
    const response = await this.requestJson("/sessions", {
      method: "POST",
      body: { name, dataset },
    });
    return normalizeSession(response);
  }

  async listMethods() {
    const response = await this.requestJson("/methods");
    const methods = Array.isArray(response) ? response : response.methods;
    if (!Array.isArray(methods)) {
      throw new Error("Backend returned methods in an unsupported shape");
    }
    return methods.map(normalizeMethod);
  }

  async createJob(sessionId, { methodId, params = {} } = {}) {
    if (!sessionId) throw new Error("createJob requires sessionId");
    if (!methodId) throw new Error("createJob requires methodId");
    return this.requestJson(`/sessions/${encodeURIComponent(sessionId)}/jobs`, {
      method: "POST",
      body: {
        method_id: methodId,
        params,
      },
    });
  }

  async getJob(jobId) {
    if (!jobId) throw new Error("getJob requires jobId");
    return this.requestJson(`/jobs/${encodeURIComponent(jobId)}`);
  }

  async getResult(jobId) {
    const job = typeof jobId === "string" ? await this.getJob(jobId) : jobId;
    if (job?.status === "failed") {
      throw new Error(job.error || "Backend job failed");
    }
    return job;
  }

  async runMethod(sessionId, { methodId, params = {}, onProgress } = {}) {
    const job = await this.createJob(sessionId, { methodId, params });
    await this.streamJobProgress(job.id, { onEvent: onProgress });
    return this.getResult(job.id);
  }

  async streamJobProgress(jobId, { onEvent, timeoutMs = this.timeoutMs } = {}) {
    if (!jobId) throw new Error("streamJobProgress requires jobId");
    if (typeof this.WebSocket !== "function") {
      return this.pollJobProgress(jobId, { onEvent, timeoutMs });
    }
    try {
      return await this.openJobWebSocket(jobId, { onEvent, timeoutMs });
    } catch {
      return this.pollJobProgress(jobId, { onEvent, timeoutMs });
    }
  }

  async pollJobProgress(jobId, { onEvent, timeoutMs = this.timeoutMs } = {}) {
    const events = [];
    const deadline = Date.now() + timeoutMs;
    let lastStatus = null;
    while (Date.now() <= deadline) {
      const job = await this.getJob(jobId);
      if (job.status !== lastStatus) {
        lastStatus = job.status;
        events.push(job);
        onEvent?.(job);
      }
      if (TERMINAL_JOB_STATUSES.has(job.status)) return events;
      await delay(this.pollIntervalMs);
    }
    throw new Error(`Timed out waiting for job ${jobId}`);
  }

  openJobWebSocket(jobId, { onEvent, timeoutMs = this.timeoutMs } = {}) {
    const url = this.buildWebSocketUrl(`/ws/jobs/${encodeURIComponent(jobId)}`);
    return new Promise((resolve, reject) => {
      const events = [];
      let settled = false;
      let sawTerminal = false;
      const socket = new this.WebSocket(url);
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try {
          socket.close();
        } catch {
          // Ignore close failures on partially-open sockets.
        }
        reject(new Error(`Timed out waiting for job ${jobId}`));
      }, timeoutMs);

      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(events);
      };
      const fail = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      };

      socket.addEventListener("message", (message) => {
        try {
          const event = JSON.parse(message.data);
          events.push(event);
          onEvent?.(event);
          if (TERMINAL_JOB_STATUSES.has(event.status)) {
            sawTerminal = true;
          }
        } catch (error) {
          fail(error);
        }
      });
      socket.addEventListener("error", () => {
        fail(new Error(`WebSocket failed for job ${jobId}`));
      });
      socket.addEventListener("close", () => {
        if (sawTerminal || events.length > 0) {
          finish();
        } else {
          fail(new Error(`WebSocket closed before job ${jobId} produced progress`));
        }
      });
    });
  }

  async requestJson(path, { method = "GET", body, headers = {}, signal } = {}) {
    const url = this.buildHttpUrl(path);
    const controller = signal ? null : new AbortController();
    const timer = controller
      ? setTimeout(() => controller.abort(), this.timeoutMs)
      : null;
    try {
      const response = await this.fetch(url, {
        method,
        headers: {
          accept: "application/json",
          ...(body == null ? {} : { "content-type": "application/json" }),
          ...headers,
        },
        body: body == null ? undefined : JSON.stringify(body),
        signal: signal ?? controller?.signal,
      });
      const payload = await readResponseBody(response);
      if (!response.ok) {
        throw new BackendHttpError(errorMessage(response, payload), {
          status: response.status,
          body: payload,
          url,
        });
      }
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error(`Backend request timed out: ${url}`);
      }
      throw error;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  buildHttpUrl(path) {
    if (/^https?:\/\//i.test(path)) return path;
    const cleanPath = String(path).replace(/^\/+/, "");
    if (!this.baseUrl) return `/${cleanPath}`;
    return `${this.baseUrl}/${cleanPath}`;
  }

  buildWebSocketUrl(path) {
    const httpUrl = this.buildHttpUrl(path);
    const absoluteUrl = /^https?:\/\//i.test(httpUrl)
      ? httpUrl
      : `${currentOrigin()}${httpUrl}`;
    return absoluteUrl.replace(/^http/i, "ws");
  }
}

export function createBackendClient(options = {}) {
  return new BackendClient(options);
}

export function resolveBackendBaseUrl(baseUrl = "") {
  if (typeof baseUrl === "string" && baseUrl.trim()) {
    return normalizeBaseUrl(baseUrl);
  }

  const explicitWindowUrl = resolveWindowBackendUrl();
  if (explicitWindowUrl) {
    return explicitWindowUrl;
  }

  const buildTimeUrl = resolveBuildTimeBackendUrl();
  if (buildTimeUrl) {
    return buildTimeUrl;
  }

  return DEFAULT_BACKEND_BASE_URL;
}

export function normalizeSeedEndpoint(seedEndpoint = DEFAULT_DEMO_SEED_ENDPOINT) {
  if (!seedEndpoint) return DEFAULT_DEMO_SEED_ENDPOINT;
  if (/^https?:\/\//i.test(seedEndpoint)) return seedEndpoint;
  return `/${String(seedEndpoint).replace(/^\/+/, "")}`;
}

export function normalizeMethod(method) {
  const id = method.id ?? method.name;
  if (!id) throw new Error("Backend method is missing id");
  const name = method.name ?? titleFromId(id);
  const rawPanel = method.panelSpec ??
    method.panel_spec ??
    method.panel ??
    method.output_spec?.panel ??
    method.output?.panel ??
    method.output_spec?.panel_spec ??
    null;
  const normalized = {
    ...method,
    id,
    name,
    description: method.description ?? "",
  };
  normalized.panelSpec = normalizePanelSpec(rawPanel, normalized);
  return normalized;
}

export function normalizePanelSpec(panelSpec, method = {}) {
  const methodId = method.id ?? method.name ?? "method_result";
  if (!panelSpec) {
    return {
      id: methodId,
      title: method.name ?? titleFromId(methodId),
      kind: "table",
      field: `${methodId}.channels`,
    };
  }
  const id = panelSpec.id ?? methodId;
  const normalized = {
    id,
    title: panelSpec.title ?? method.name ?? titleFromId(id),
    kind: panelSpec.kind ?? "table",
    field: panelSpec.field ?? panelSpec.path ?? methodId,
  };
  if (Array.isArray(panelSpec.columns)) normalized.columns = panelSpec.columns;
  if (panelSpec.description) normalized.description = panelSpec.description;
  return normalized;
}

function normalizeSession(session) {
  const normalized = session;
  if (!normalized?.id) {
    if (normalized?.session_id != null) normalized.id = normalized.session_id;
    else if (normalized?.sessionId != null) normalized.id = normalized.sessionId;
  }
  if (!normalized?.id) throw new Error("Backend session response is missing id");
  return session;
}

async function requestSeedDemo(requestJson, path, options) {
  return requestJson(path, options);
}

async function readResponseBody(response) {
  const text = await response.text();
  if (!text) return null;
  const contentType = response.headers?.get?.("content-type") ?? "";
  if (!contentType.includes("json")) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorMessage(response, payload) {
  const detail = Array.isArray(payload?.detail)
    ? payload.detail.map((item) => item.msg ?? item.message ?? String(item)).join("; ")
    : payload?.detail ?? payload?.error ?? payload?.message ?? response.statusText;
  return `Backend ${response.status}: ${detail}`;
}

function normalizeBaseUrl(baseUrl) {
  return String(baseUrl ?? "").trim().replace(/\/+$/, "");
}

function resolveWindowBackendUrl() {
  const direct = globalThis?.NEUROMOUSE_BACKEND_URL;
  if (typeof direct === "string" && direct.trim()) {
    return normalizeBaseUrl(direct);
  }
  const windowUrl = globalThis?.window?.NEUROMOUSE_BACKEND_URL;
  if (typeof windowUrl === "string" && windowUrl.trim()) {
    return normalizeBaseUrl(windowUrl);
  }
  return "";
}

function resolveBuildTimeBackendUrl() {
  if (typeof globalThis?.NEUROMOUSE_BACKEND_URL__ === "string" && globalThis.NEUROMOUSE_BACKEND_URL__.trim()) {
    return normalizeBaseUrl(globalThis.NEUROMOUSE_BACKEND_URL__);
  }
  if (typeof globalThis?.__NEUROMOUSE_BACKEND_URL__ === "string" && globalThis.__NEUROMOUSE_BACKEND_URL__.trim()) {
    return normalizeBaseUrl(globalThis.__NEUROMOUSE_BACKEND_URL__);
  }
  return "";
}

function currentOrigin() {
  if (globalThis.location?.origin) return globalThis.location.origin;
  throw new Error("Relative WebSocket URLs require a browser location or absolute baseUrl");
}

function titleFromId(id) {
  return String(id).replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
