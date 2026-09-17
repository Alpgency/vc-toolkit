/* Tiny server: the static page (web/ and data/) plus POST /api/ask.
   Run from network-graph/:  node --env-file=ask/.env ask/server.mjs
   No dependencies. */

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, normalize, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { ask, askConfigured } from "./ask.mjs";
import { graphLoaded } from "./graph.mjs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PORT = Number(process.env.PORT || 8787);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8" };

/* ponytail: in-memory per-IP limit, resets on restart; use a shared store if run on several instances */
const hits = new Map();
function limited(ip) {
  const now = Date.now();
  const recent = (hits.get(ip) || []).filter((t) => now - t < 60_000);
  const over = recent.length >= 10;
  if (!over) recent.push(now);
  hits.set(ip, recent);
  return over;
}

function send(res, status, body, type = "application/json") {
  res.writeHead(status, { "content-type": type, "cache-control": "no-store" });
  res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

async function readBody(req) {
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 4096) throw new Error("body too large");
  }
  return JSON.parse(raw);
}

createServer(async (req, res) => {
  const path = new URL(req.url, "http://x").pathname;

  if (path === "/api/ask" && req.method === "POST") {
    if (!askConfigured || !graphLoaded) return send(res, 503, { error: "ask is not configured" });
    let body;
    try { body = await readBody(req); } catch { return send(res, 400, { error: "bad request" }); }
    const q = body?.q;
    if (typeof q !== "string" || !q.trim() || q.length > 400) return send(res, 400, { error: "bad question" });
    if (limited(req.socket.remoteAddress)) return send(res, 429, { error: "slow down" });
    try {
      return send(res, 200, await ask(q));
    } catch (err) {
      console.error("[ask]", err.message);
      return send(res, 502, { error: "ask failed" });
    }
  }

  if (req.method !== "GET") return send(res, 405, { error: "method not allowed" });
  const rel = path === "/" ? "web/index.html" : path.startsWith("/data/") ? path.slice(1) : join("web", path);
  const file = normalize(join(ROOT, rel));
  if (!file.startsWith(join(ROOT, "web")) && !file.startsWith(join(ROOT, "data"))) return send(res, 404, "not found", "text/plain");
  try {
    send(res, 200, await readFile(file), TYPES[extname(file)] || "application/octet-stream");
  } catch {
    send(res, 404, "not found", "text/plain");
  }
}).listen(PORT, () => {
  console.log(`http://localhost:${PORT}  (ask ${askConfigured ? "on" : "off: set ANTHROPIC_API_KEY"})`);
});
