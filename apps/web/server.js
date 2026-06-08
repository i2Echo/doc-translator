import http from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.join(__dirname, "dist");
const port = Number(process.env.PORT || 3000);
const apiHost = process.env.API_PROXY_HOST || "api";
const apiPort = Number(process.env.API_PROXY_PORT || 8000);

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "application/javascript; charset=utf-8",
  ".mjs": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function proxyRequest(req, res) {
  const headers = { ...req.headers, host: `${apiHost}:${apiPort}` };
  const upstream = http.request(
    {
      host: apiHost,
      port: apiPort,
      path: req.url,
      method: req.method,
      headers,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    }
  );

  upstream.on("error", (error) => {
    sendJson(res, 502, { detail: `API proxy error: ${error.message}` });
  });

  req.pipe(upstream);
}

function resolveFile(requestPath) {
  const normalizedPath = decodeURIComponent(requestPath.split("?")[0]);
  const requested = normalizedPath === "/" ? "/index.html" : normalizedPath;
  const candidate = path.resolve(root, `.${requested}`);
  if (!candidate.startsWith(root)) {
    return path.join(root, "index.html");
  }
  if (existsSync(candidate) && statSync(candidate).isFile()) {
    return candidate;
  }
  return path.join(root, "index.html");
}

const server = http.createServer(async (req, res) => {
  if (!req.url) {
    sendJson(res, 400, { detail: "Missing request URL" });
    return;
  }

  if (req.url.startsWith("/api/")) {
    proxyRequest(req, res);
    return;
  }

  try {
    const filePath = resolveFile(req.url);
    const extension = path.extname(filePath).toLowerCase();
    const contentType = contentTypes[extension] || "application/octet-stream";
    res.writeHead(200, { "Content-Type": contentType });
    createReadStream(filePath).pipe(res);
  } catch (error) {
    sendJson(res, 500, { detail: `Static server error: ${error.message}` });
  }
});

server.listen(port, "0.0.0.0", async () => {
  const indexPath = path.join(root, "index.html");
  const hasIndex = existsSync(indexPath) && (await readFile(indexPath, "utf-8")).includes("Doc Translator");
  console.log(`Doc Translator web listening on ${port} (index ok: ${hasIndex})`);
});
