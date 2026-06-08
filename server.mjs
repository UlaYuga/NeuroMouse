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

function sendText(response, status, body) {
  response.writeHead(status, {
    "content-type": "text/plain; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}
