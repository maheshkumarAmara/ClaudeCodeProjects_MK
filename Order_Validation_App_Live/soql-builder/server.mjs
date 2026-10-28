#!/usr/bin/env node
/**
 * Local bridge between the SOQL Builder UI and the `sf` CLI.
 *
 * Binds to 127.0.0.1 only. Serves the static builder UI plus a small JSON
 * API that shells out to `sf` via execFile (argv array, never a shell
 * string) so query/value text typed by the user is never shell-interpreted.
 * A random per-run token is injected into the served index.html and
 * required as X-Auth-Token on every /api/* request.
 *
 * Usage: npm run soql-builder
 */
import { createServer } from "node:http";
import { execFile } from "node:child_process";
import { readFileSync, existsSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { join, dirname, extname, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { tmpdir } from "node:os";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = process.env.SOQL_BUILDER_PORT ? Number(process.env.SOQL_BUILDER_PORT) : 4570;
const HOST = "127.0.0.1";
const AUTH_TOKEN = randomBytes(24).toString("hex");

function loadApiVersion() {
  try {
    const projectPath = join(HERE, "..", "..", "sfdx-project.json");
    const project = JSON.parse(readFileSync(projectPath, "utf8"));
    if (project.sourceApiVersion) return String(project.sourceApiVersion);
  } catch {
    // fall through to hardcoded fallback below
  }
  return "67.0";
}
const API_VERSION = loadApiVersion();

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

const ANSI_ESCAPE = /\x1B\[[0-9;]*m/g;
function stripAnsi(text) {
  return text.replace(ANSI_ESCAPE, "");
}

// `sf ... --json` writes the real failure as a JSON object to stdout (with a
// non-zero exit code) — e.g. {"status":1,"name":"...","message":"No such
// column 'Foo__c' on entity 'Bar'..."}. stderr, meanwhile, carries CLI noise
// (most commonly an "update available" notice) on every invocation whether
// it succeeds or fails, so it must never be preferred over a parseable JSON
// error on stdout.
function extractSfErrorMessage(stdout, stderr, fallback) {
  if (stdout && stdout.trim()) {
    try {
      const parsed = JSON.parse(stdout);
      if (parsed && typeof parsed.message === "string" && parsed.message.trim()) {
        return stripAnsi(parsed.message.trim());
      }
    } catch {
      // stdout wasn't JSON (or not the sf --json error shape) — fall through.
    }
  }
  const cleanedStderr = stripAnsi(stderr || "")
    .split("\n")
    .filter((line) => !/update available from/i.test(line))
    .join("\n")
    .trim();
  if (cleanedStderr) return cleanedStderr;
  return stripAnsi(fallback);
}

function runSf(args) {
  return new Promise((resolve, reject) => {
    execFile("sf", args, { maxBuffer: 1024 * 1024 * 64 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(extractSfErrorMessage(stdout, stderr, error.message)));
        return;
      }
      resolve(stdout);
    });
  });
}

function sendJson(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => (data += chunk));
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

function checkAuth(req) {
  return req.headers["x-auth-token"] === AUTH_TOKEN;
}

function serveStatic(req, res, urlPath) {
  const relPath = urlPath === "/" ? "/index.html" : urlPath;
  const filePath = join(HERE, relPath.replace(/^\/+/, ""));
  // Plain startsWith(HERE) would also match a sibling directory like
  // "HERE-secret" — require an exact match or a path-separator boundary.
  const withinRoot = filePath === HERE || filePath.startsWith(HERE + sep);
  if (!withinRoot || !existsSync(filePath)) {
    res.writeHead(404);
    res.end("Not found");
    return;
  }
  const ext = extname(filePath);
  let contents = readFileSync(filePath);
  if (ext === ".html") {
    contents = Buffer.from(contents.toString("utf8").replace("__AUTH_TOKEN__", AUTH_TOKEN));
  }
  res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
  res.end(contents);
}

async function handleApi(req, res, urlPath) {
  if (!checkAuth(req)) {
    sendJson(res, 401, { error: "Missing or invalid X-Auth-Token." });
    return;
  }

  try {
    if (urlPath === "/api/health" && req.method === "GET") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (urlPath === "/api/orgs" && req.method === "GET") {
      const stdout = await runSf(["org", "list", "--json"]);
      const parsed = JSON.parse(stdout);
      const result = parsed.result || {};
      const orgs = [
        ...(result.nonScratchOrgs || []),
        ...(result.scratchOrgs || []),
      ].map((o) => ({ username: o.username, alias: o.alias || null }));
      sendJson(res, 200, { orgs });
      return;
    }

    if (urlPath === "/api/org-info" && req.method === "GET") {
      const org = new URL(req.url, `http://${HOST}`).searchParams.get("org");
      if (!org) {
        sendJson(res, 400, { error: "org is required." });
        return;
      }
      const stdout = await runSf(["org", "display", "--target-org", org, "--json"]);
      const parsed = JSON.parse(stdout);
      sendJson(res, 200, { instanceUrl: (parsed.result && parsed.result.instanceUrl) || null });
      return;
    }

    if (urlPath === "/api/describe" && req.method === "GET") {
      const params = new URL(req.url, `http://${HOST}`).searchParams;
      const sobject = params.get("sobject");
      const org = params.get("org");
      if (!sobject || !org) {
        sendJson(res, 400, { error: "sobject and org are required." });
        return;
      }
      const stdout = await runSf(["sobject", "describe", "--sobject", sobject, "--target-org", org, "--json"]);
      const parsed = JSON.parse(stdout);
      const fields = (parsed.result && parsed.result.fields) || [];
      const byName = {};
      for (const f of fields) {
        byName[f.name] = {
          nillable: !!f.nillable,
          createable: !!f.createable,
          updateable: !!f.updateable,
          unique: !!f.unique,
          externalId: !!f.externalId,
        };
      }
      sendJson(res, 200, { fields: byName });
      return;
    }

    if (urlPath === "/api/explain" && req.method === "GET") {
      const params = new URL(req.url, `http://${HOST}`).searchParams;
      const soql = params.get("soql");
      const org = params.get("org");
      if (!soql || !org) {
        sendJson(res, 400, { error: "soql and org are required." });
        return;
      }
      // `sf api request rest` is BETA and has no --json flag — stdout is raw
      // text. Per explicit decision, no capability pre-check: a failure here
      // (unsupported CLI version, malformed response, etc.) simply flows into
      // the catch-all below and is surfaced to the user as a plain error.
      const restPath = `/services/data/v${API_VERSION}/query/?explain=${encodeURIComponent(soql)}`;
      const stdout = await runSf(["api", "request", "rest", restPath, "--target-org", org]);
      let parsed;
      try {
        parsed = JSON.parse(stdout);
      } catch {
        const first = stdout.indexOf("{");
        const last = stdout.lastIndexOf("}");
        if (first === -1 || last === -1 || last <= first) {
          throw new Error("Could not parse a query plan from the sf CLI response.");
        }
        parsed = JSON.parse(stdout.slice(first, last + 1));
      }
      sendJson(res, 200, { plan: parsed });
      return;
    }

    if (urlPath === "/api/query" && req.method === "POST") {
      const body = JSON.parse(await readBody(req));
      const { soql, org, queryAll, useTooling } = body;
      if (!soql || !org) {
        sendJson(res, 400, { error: "soql and org are required." });
        return;
      }
      const args = ["data", "query", "--query", soql, "--target-org", org, "--json"];
      if (queryAll) args.push("--all-rows");
      if (useTooling) args.push("--use-tooling-api");
      const stdout = await runSf(args);
      const parsed = JSON.parse(stdout);
      sendJson(res, 200, { records: parsed.result ? parsed.result.records : [] });
      return;
    }

    if (urlPath === "/api/update-record" && req.method === "POST") {
      const body = JSON.parse(await readBody(req));
      const { sobject, recordId, values, org } = body;
      if (!sobject || !recordId || !values || !org) {
        sendJson(res, 400, { error: "sobject, recordId, values, and org are required." });
        return;
      }
      await runSf([
        "data",
        "update",
        "record",
        "--sobject",
        sobject,
        "--record-id",
        recordId,
        "--values",
        values,
        "--target-org",
        org,
        "--json",
      ]);
      sendJson(res, 200, { ok: true });
      return;
    }

    // `sf api request rest` is BETA and has no --json flag — stdout is raw
    // text, returned as-is for the client to interpret. This endpoint is a
    // genuine write path: it sends whatever method/path/body the caller
    // supplies. The only mitigation is the human-confirm gate in app.js
    // before a mutating verb is sent — see README.md's Security model.
    const REST_ALLOWED_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]);
    if (urlPath === "/api/rest-request" && req.method === "POST") {
      const body = JSON.parse(await readBody(req));
      const { org, method, path, headers, body: reqBody } = body;
      if (!org || !method || !path) {
        sendJson(res, 400, { error: "org, method, and path are required." });
        return;
      }
      const normalizedMethod = String(method).toUpperCase();
      if (!REST_ALLOWED_METHODS.has(normalizedMethod)) {
        sendJson(res, 400, { error: `Unsupported method: ${method}` });
        return;
      }
      const args = ["api", "request", "rest", path, "--target-org", org, "--method", normalizedMethod];
      for (const h of Array.isArray(headers) ? headers : []) {
        args.push("--header", h);
      }
      args.push("--body", reqBody || "");
      const stdout = await runSf(args);
      sendJson(res, 200, { raw: stdout });
      return;
    }

    // Genuine execute path: runs whatever Apex the caller supplies against
    // the target org, including any DML or callouts in it. The only
    // mitigation is the human-confirm gate in app.js before every run — see
    // README.md's Security model. `sf apex run` exits 0 even when the Apex
    // itself fails to compile or throws, so success/failure is read from the
    // parsed --json result body, not the process exit code.
    if (urlPath === "/api/apex-execute" && req.method === "POST") {
      const body = JSON.parse(await readBody(req));
      const { org, code } = body;
      if (!org || !code) {
        sendJson(res, 400, { error: "org and code are required." });
        return;
      }
      let tmpDir;
      try {
        tmpDir = mkdtempSync(join(tmpdir(), "soql-builder-apex-"));
        const tmpFile = join(tmpDir, "anonymous.apex");
        writeFileSync(tmpFile, code, "utf8");
        const stdout = await runSf(["apex", "run", "--target-org", org, "--file", tmpFile, "--json"]);
        const parsed = JSON.parse(stdout);
        const result = parsed.result || {};
        sendJson(res, 200, {
          success: !!result.success,
          compiled: !!result.compiled,
          compileProblem: result.compileProblem || null,
          exceptionMessage: result.exceptionMessage || null,
          exceptionStackTrace: result.exceptionStackTrace || null,
          logs: result.logs || null,
          line: typeof result.line === "number" ? result.line : null,
          column: typeof result.column === "number" ? result.column : null,
        });
      } finally {
        if (tmpDir) rmSync(tmpDir, { recursive: true, force: true });
      }
      return;
    }

    sendJson(res, 404, { error: "Unknown endpoint." });
  } catch (err) {
    sendJson(res, 500, { error: err.message });
  }
}

const server = createServer((req, res) => {
  const urlPath = req.url.split("?")[0];
  if (urlPath.startsWith("/api/")) {
    handleApi(req, res, urlPath);
  } else if (req.method === "GET") {
    serveStatic(req, res, urlPath);
  } else {
    res.writeHead(405);
    res.end("Method not allowed");
  }
});

server.listen(PORT, HOST, () => {
  console.log(`SOQL Builder running at http://${HOST}:${PORT}`);
  console.log(`(bound to ${HOST} only — not reachable from other machines)`);
});
