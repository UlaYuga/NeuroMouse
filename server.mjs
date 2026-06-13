import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { timingSafeEqual } from "node:crypto";

const root = fileURLToPath(new URL(".", import.meta.url));
const port = Number(process.env.PORT ?? 8080);
const host = process.env.HOST ?? "0.0.0.0";

const DEFAULT_EXPLAIN_API_URL = "https://api.anthropic.com/v1/messages";
const EXPLAIN_RATE_WINDOW_MS = 60_000;
const DEFAULT_EXPLAIN_RATE_LIMIT = 30;

const explainRateState = new Map();

// Same-origin API proxy: the static server forwards backend API paths to the
// FastAPI backend, so the browser talks to ONE origin and the auth session
// cookie works (no cross-site SameSite problem).
const BACKEND_URL = (
  process.env.NEUROMOUSE_BACKEND_URL ?? "https://backend-production-c7a1.up.railway.app"
).replace(/\/$/, "");

function isBackendApiPath(pathname) {
  return /^\/(auth|sessions|jobs|demo|methods)(?:\/|$)/.test(pathname);
}

const mimeTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".csv", "text/csv; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".md", "text/markdown; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".txt", "text/plain; charset=utf-8"],
  [".wasm", "application/wasm"],
  [".zip", "application/zip"],
]);

const immutableAssetPattern = /\.(?:css|js|json|csv|svg|wasm)$/i;

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", "http://localhost");

    if (url.pathname === "/healthz") {
      sendText(response, 200, "ok\n");
      return;
    }

    if (url.pathname === "/api/explain") {
      await handleExplain(request, response);
      return;
    }

    if (isBackendApiPath(url.pathname)) {
      await proxyToBackend(request, response, url);
      return;
    }

    const target = await resolveRequestPath(url.pathname);
    if (!target) {
      sendText(response, 404, "Not found\n");
      return;
    }

    response.writeHead(200, {
      "content-type": mimeTypes.get(extname(target)) ?? "application/octet-stream",
      "cache-control": immutableAssetPattern.test(target)
        ? "public, max-age=300"
        : "no-cache",
      "x-content-type-options": "nosniff",
    });
    createReadStream(target).pipe(response);
  } catch (error) {
    console.error(error);
    sendText(response, 500, "Internal server error\n");
  }
});

server.listen(port, host, () => {
  console.log(`NeuroMouse listening on ${host}:${port}`);
});

async function proxyToBackend(request, response, url) {
  const target = BACKEND_URL + url.pathname + url.search;
  const headers = {};
  for (const [key, value] of Object.entries(request.headers)) {
    if (key === "host" || key === "connection" || key === "content-length") continue;
    headers[key] = Array.isArray(value) ? value.join(", ") : value;
  }
  const method = request.method ?? "GET";
  const hasBody = method !== "GET" && method !== "HEAD";
  const body = hasBody ? await readRawBody(request) : undefined;
  try {
    const upstream = await fetch(target, { method, headers, body, redirect: "manual" });
    const outHeaders = {};
    upstream.headers.forEach((value, key) => {
      if (
        key === "content-encoding" ||
        key === "transfer-encoding" ||
        key === "connection" ||
        key === "set-cookie"
      ) {
        return;
      }
      outHeaders[key] = value;
    });
    // Re-emit cookies for THIS origin: strip any backend Domain so the browser
    // scopes the session cookie to the static host (same-origin, no cross-site).
    const setCookies =
      typeof upstream.headers.getSetCookie === "function" ? upstream.headers.getSetCookie() : [];
    if (setCookies.length > 0) {
      outHeaders["set-cookie"] = setCookies.map((cookie) => cookie.replace(/;\s*Domain=[^;]*/i, ""));
    }
    const payload = Buffer.from(await upstream.arrayBuffer());
    response.writeHead(upstream.status, outHeaders);
    response.end(payload);
  } catch (error) {
    console.error("backend proxy error:", error.message);
    sendJson(response, 502, { error: "Backend unavailable." });
  }
}

function readRawBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks)));
    request.on("error", reject);
  });
}

async function resolveRequestPath(pathname) {
  const decoded = decodeURIComponent(pathname);
  const safePath = normalize(decoded).replace(/^(\.\.(?:\/|\\|$))+/, "");
  const requestedPath = safePath === sep || safePath === "." ? "index.html" : safePath.replace(/^[/\\]+/, "");
  const absolutePath = resolve(root, requestedPath);

  if (!absolutePath.startsWith(root)) return null;
  const file = await fileStat(absolutePath);
  if (file?.isFile()) return absolutePath;

  if (!extname(requestedPath)) {
    const fallback = join(root, "index.html");
    const fallbackStat = await fileStat(fallback);
    if (fallbackStat?.isFile()) return fallback;
  }

  return null;
}

async function fileStat(path) {
  try {
    return await stat(path);
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ENOTDIR") return null;
    throw error;
  }
}

async function handleExplain(request, response) {
  if (request.method === "OPTIONS") {
    if (!setExplainCorsHeaders(response, request, { isPreflight: true })) return;
    sendText(response, 204, "", request);
    return;
  }

  if (request.method !== "POST") {
    sendJson(response, 405, { error: "Use POST." }, request);
    return;
  }

  if (!setExplainCorsHeaders(response, request)) return;

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    sendJson(response, 503, { error: "Explain is not configured on this server." }, request);
    return;
  }

  // Authorize the caller as EITHER a logged-in user (session cookie validated
  // against the backend through the same-origin proxy) OR a service token for
  // non-browser callers. The browser button sends only the session cookie, so
  // EXPLAIN_TOKEN is optional — explain lives behind login.
  const authorized = matchesExplainToken(request) || (await hasValidSession(request));
  if (!authorized) {
    sendJson(
      response,
      401,
      { error: "Sign in to use Explain (or provide a valid explain token)." },
      request,
    );
    return;
  }

  if (isExplainRateLimited(getClientIp(request))) {
    sendJson(response, 429, { error: "Rate limit exceeded. Try again later." }, request);
    return;
  }

  let payload;
  try {
    payload = await readJsonBody(request, 64 * 1024);
  } catch (error) {
    sendJson(response, 400, { error: error.message }, request);
    return;
  }

  if (payload?.context == null) {
    sendJson(response, 400, { error: "Missing 'context' in request body." }, request);
    return;
  }

  const question = typeof payload.question === "string" ? payload.question.slice(0, 500) : "";
  const contextText = (typeof payload.context === "string"
    ? payload.context
    : JSON.stringify(payload.context)
  ).slice(0, 12000);

  const apiUrl = process.env.EXPLAIN_API_URL ?? DEFAULT_EXPLAIN_API_URL;
  const model = process.env.EXPLAIN_MODEL ?? "claude-sonnet-4-6";
  let safeApiUrl;
  try {
    safeApiUrl = getCheckedExplainApiUrl(apiUrl);
  } catch (error) {
    sendJson(response, 403, { error: error.message }, request);
    return;
  }

  const system = [
    "You explain EEG / neural-signal analysis results to a researcher who does not write code.",
    "Use only the numbers in the provided data; never invent values.",
    "Be concise and plain-language: a short paragraph, then 2-4 bullet takeaways.",
    "The comparison 'score' (0-100) is a heuristic ranking aid, not a statistical test — do not imply statistical significance.",
  ].join(" ");

  const userText = [
    question ? `Researcher question: ${question}` : "Explain in plain language what this neural-signal comparison shows.",
    "",
    "Analysis data:",
    contextText,
  ].join("\n");

  try {
    const text = await callClaude({ apiUrl: safeApiUrl, apiKey, model, system, userText });
    sendJson(response, 200, { text }, request);
  } catch (error) {
    console.error("explain error:", error.message);
    sendJson(response, 502, { error: "Explanation service failed. Check server logs." }, request);
  }
}

async function callClaude({ apiUrl, apiKey, model, system, userText }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const upstream = await fetch(apiUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "authorization": `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        max_tokens: 700,
        stream: false,
        messages: [{ role: "user", content: `${system}\n\n${userText}` }],
      }),
      signal: controller.signal,
    });
    if (!upstream.ok) {
      const detail = await upstream.text().catch(() => "");
      throw new Error(`upstream ${upstream.status}: ${detail.slice(0, 300)}`);
    }
    const data = await upstream.json();
    const text = Array.isArray(data?.content)
      ? data.content.filter((block) => block?.type === "text").map((block) => block.text).join("\n").trim()
      : "";
    if (!text) throw new Error("empty completion");
    return text;
  } finally {
    clearTimeout(timer);
  }
}

function getCheckedExplainApiUrl(rawApiUrl) {
  const apiUrl = new URL(rawApiUrl);
  if (apiUrl.hostname !== "api.anthropic.com" && !process.env.EXPLAIN_ALLOW_THIRD_PARTY_API) {
    throw new Error("Refusing non-official explain API host without explicit opt-in.");
  }
  return apiUrl.toString();
}

function getExplainCorsOrigins() {
  const allowList = process.env.EXPLAIN_CORS_ALLOW_ORIGINS ?? process.env.EXPLAIN_CORS_ORIGINS;
  if (!allowList) return [];
  return allowList
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function setExplainCorsHeaders(response, request, options = {}) {
  const origin = request.headers.origin;

  if (!origin) return true;

  // Same-origin POSTs still carry an Origin header; allow them without an
  // explicit allowlist, since the frontend and /api/explain share this origin.
  const host = request.headers.host;
  let originHost = null;
  try {
    originHost = new URL(origin).host;
  } catch {}
  if (host && originHost === host) return true;

  const allowedOrigins = getExplainCorsOrigins();
  if (!allowedOrigins.length || !allowedOrigins.includes(origin)) {
    sendJson(response, 403, { error: "Origin not allowed." }, request);
    return false;
  }

  response.setHeader("Access-Control-Allow-Origin", origin);
  response.setHeader("Vary", "Origin");
  response.setHeader("Access-Control-Allow-Credentials", "true");
  response.setHeader("Access-Control-Allow-Headers", "content-type, x-explain-token");
  if (options.isPreflight) {
    response.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
    response.setHeader("Access-Control-Max-Age", "600");
  }
  return true;
}

function getClientIp(request) {
  const forwarded = request.headers["x-forwarded-for"];
  if (typeof forwarded === "string" && forwarded.trim()) {
    return forwarded.split(",")[0].trim();
  }
  return request.socket?.remoteAddress ?? "unknown";
}

function getExplainRateLimit() {
  const configured = Number(process.env.EXPLAIN_RATE_LIMIT_PER_MIN);
  if (Number.isFinite(configured) && configured > 0) return configured;
  return DEFAULT_EXPLAIN_RATE_LIMIT;
}

function isExplainRateLimited(clientIp) {
  const limit = getExplainRateLimit();
  const now = Date.now();
  const state = explainRateState.get(clientIp);

  if (!state || now - state.windowStart >= EXPLAIN_RATE_WINDOW_MS) {
    explainRateState.set(clientIp, { windowStart: now, count: 1 });
    return false;
  }

  if (state.count >= limit) return true;

  state.count += 1;
  return false;
}

function matchesToken(expected, actual) {
  if (typeof expected !== "string" || typeof actual !== "string" || !expected || !actual) {
    return false;
  }
  const expectedBytes = Buffer.from(expected);
  const actualBytes = Buffer.from(actual);
  if (expectedBytes.length !== actualBytes.length) return false;
  return timingSafeEqual(expectedBytes, actualBytes);
}

function matchesExplainToken(request) {
  const explainToken = process.env.EXPLAIN_TOKEN;
  if (!explainToken) return false;
  const requestToken = typeof request.headers["x-explain-token"] === "string"
    ? request.headers["x-explain-token"]
    : "";
  return matchesToken(requestToken, explainToken);
}

// Validate a browser session by asking the backend's /auth/me through the same
// BACKEND_URL the API proxy uses. Any non-2xx (or a network failure) means "not
// authenticated" — fail closed.
async function hasValidSession(request) {
  const cookie = request.headers.cookie;
  if (!cookie) return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const upstream = await fetch(`${BACKEND_URL}/auth/me`, {
      method: "GET",
      headers: { cookie },
      signal: controller.signal,
    });
    return upstream.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function readJsonBody(request, limit) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error("Request body too large."));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"));
      } catch {
        reject(new Error("Invalid JSON body."));
      }
    });
    request.on("error", reject);
  });
}

function sendJson(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(JSON.stringify(body));
}

function sendText(response, status, body) {
  response.writeHead(status, {
    "content-type": "text/plain; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}
