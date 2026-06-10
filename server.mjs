import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const port = Number(process.env.PORT ?? 8080);
const host = process.env.HOST ?? "0.0.0.0";

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
  if (request.method !== "POST") {
    sendJson(response, 405, { error: "Use POST." });
    return;
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    sendJson(response, 503, { error: "Explain is not configured on this server." });
    return;
  }

  let payload;
  try {
    payload = await readJsonBody(request, 64 * 1024);
  } catch (error) {
    sendJson(response, 400, { error: error.message });
    return;
  }

  if (payload?.context == null) {
    sendJson(response, 400, { error: "Missing 'context' in request body." });
    return;
  }

  const question = typeof payload.question === "string" ? payload.question.slice(0, 500) : "";
  const contextText = (typeof payload.context === "string"
    ? payload.context
    : JSON.stringify(payload.context)
  ).slice(0, 12000);

  const apiUrl = process.env.EXPLAIN_API_URL ?? "https://api.kie.ai/claude/v1/messages";
  const model = process.env.EXPLAIN_MODEL ?? "claude-sonnet-4-6";

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
    const text = await callClaude({ apiUrl, apiKey, model, system, userText });
    sendJson(response, 200, { text });
  } catch (error) {
    console.error("explain error:", error.message);
    sendJson(response, 502, { error: "Explanation service failed. Check server logs." });
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
