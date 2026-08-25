/**
 * gateway.js
 *
 * Always-on reverse proxy for the Order Validation App.
 *
 * Listens on the public port (8501). On the first request after being idle,
 * it lazily starts the real Streamlit app (internal port 8510, via launch.sh
 * which also auto-starts the Salesforce bridge on 3001), proxies the request
 * through (including Streamlit's WebSocket), and stops the backend again
 * after IDLE_MS of no open connections.
 *
 * Run standalone for testing:  node gateway.js
 * Normally started by launchd — see install_autostart.sh.
 */

const http = require('http');
const net = require('net');
const fs = require('fs');
const path = require('path');
const { spawn, execSync } = require('child_process');

const PROJECT_DIR = __dirname;
const GATEWAY_PORT = parseInt(process.env.GATEWAY_PORT || '8501', 10);
const BACKEND_PORT = parseInt(process.env.GATEWAY_BACKEND_PORT || '8510', 10);
const BRIDGE_PORT = parseInt(process.env.GATEWAY_BRIDGE_PORT || '3001', 10);
const IDLE_MS = parseInt(process.env.GATEWAY_IDLE_MS || String(15 * 60 * 1000), 10); // default 15 minutes
const WATCHDOG_INTERVAL_MS = parseInt(process.env.GATEWAY_WATCHDOG_INTERVAL_MS || String(60 * 1000), 10);
const STARTUP_TIMEOUT_MS = 25 * 1000;
const STARTUP_POLL_MS = 300;

const LOG_DIR = path.join(PROJECT_DIR, 'logs');
fs.mkdirSync(LOG_DIR, { recursive: true });
const GATEWAY_LOG_FILE = path.join(LOG_DIR, 'gateway.log');
const APP_LOG_FILE = path.join(LOG_DIR, 'app.log');
const appLogStream = fs.createWriteStream(APP_LOG_FILE, { flags: 'a' });

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try { fs.appendFileSync(GATEWAY_LOG_FILE, line); } catch (e) { /* ignore */ }
  process.stdout.write(line);
}

const state = {
  backendProc: null,
  lastActivity: Date.now(),
  openConnections: 0,
};
let startingPromise = null;

function waitForPort(port, timeoutMs) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    (function attempt() {
      const sock = net.connect({ host: '127.0.0.1', port }, () => {
        sock.destroy();
        resolve();
      });
      sock.on('error', () => {
        sock.destroy();
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Timed out waiting for port ${port}`));
        } else {
          setTimeout(attempt, STARTUP_POLL_MS);
        }
      });
    })();
  });
}

function startBackend() {
  log(`Starting backend (streamlit on ${BACKEND_PORT}, bridge on ${BRIDGE_PORT})...`);
  const child = spawn('bash', ['launch.sh'], {
    cwd: PROJECT_DIR,
    env: Object.assign({}, process.env, { STREAMLIT_PORT: String(BACKEND_PORT) }),
    detached: true,
    stdio: ['ignore', appLogStream, appLogStream],
  });
  child.unref();
  state.backendProc = child;
  child.on('exit', (code, signal) => {
    log(`Backend process exited (code=${code}, signal=${signal}).`);
    if (state.backendProc === child) state.backendProc = null;
  });
  return waitForPort(BACKEND_PORT, STARTUP_TIMEOUT_MS).then(() => {
    log(`Backend is up on port ${BACKEND_PORT}.`);
  }).catch((err) => {
    log(`Backend failed to come up: ${err.message}`);
    state.backendProc = null;
    throw err;
  });
}

function ensureBackend() {
  if (state.backendProc) return Promise.resolve();
  if (startingPromise) return startingPromise;
  startingPromise = startBackend().then(
    () => { startingPromise = null; },
    (err) => { startingPromise = null; throw err; }
  );
  return startingPromise;
}

function stopBackend() {
  const proc = state.backendProc;
  state.backendProc = null;
  if (proc && proc.pid) {
    try { process.kill(-proc.pid, 'SIGTERM'); } catch (e) { /* already gone */ }
  }
  try {
    const pids = execSync(`lsof -i :${BRIDGE_PORT} -sTCP:LISTEN -t`, { encoding: 'utf8' }).trim();
    if (pids) {
      pids.split('\n').forEach((pid) => {
        try { process.kill(parseInt(pid, 10), 'SIGTERM'); } catch (e) { /* already gone */ }
      });
    }
  } catch (e) { /* lsof exits non-zero when nothing is listening — nothing to do */ }
  log('Backend stopped (idle timeout).');
}

function proxyHttp(req, res) {
  const proxyReq = http.request(
    { hostname: '127.0.0.1', port: BACKEND_PORT, path: req.url, method: req.method, headers: req.headers },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    }
  );
  proxyReq.on('error', (err) => {
    log(`Proxy error: ${err.message}`);
    if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'text/plain' });
    res.end('Bad gateway');
  });
  req.pipe(proxyReq);
}

const server = http.createServer((req, res) => {
  state.lastActivity = Date.now();
  ensureBackend()
    .then(() => proxyHttp(req, res))
    .catch((err) => {
      res.writeHead(502, { 'Content-Type': 'text/plain' });
      res.end(`Backend failed to start: ${err.message}`);
    });
});

server.on('upgrade', (req, clientSocket, head) => {
  state.lastActivity = Date.now();
  ensureBackend()
    .then(() => {
      const backendSocket = net.connect(BACKEND_PORT, '127.0.0.1');
      let counted = false;

      backendSocket.on('connect', () => {
        counted = true;
        state.openConnections++;
        const requestLine = `${req.method} ${req.url} HTTP/1.1\r\n`;
        const headerLines = [];
        for (let i = 0; i < req.rawHeaders.length; i += 2) {
          headerLines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
        }
        backendSocket.write(requestLine + headerLines.join('\r\n') + '\r\n\r\n');
        if (head && head.length) backendSocket.write(head);
        clientSocket.pipe(backendSocket);
        backendSocket.pipe(clientSocket);
      });

      const cleanup = () => {
        if (counted) {
          counted = false;
          state.openConnections = Math.max(0, state.openConnections - 1);
        }
        state.lastActivity = Date.now();
      };
      clientSocket.on('close', cleanup);
      clientSocket.on('error', cleanup);
      backendSocket.on('close', cleanup);
      backendSocket.on('error', (err) => {
        log(`WebSocket backend error: ${err.message}`);
        cleanup();
        clientSocket.destroy();
      });
    })
    .catch((err) => {
      log(`ERROR starting backend for WebSocket upgrade: ${err.message}`);
      clientSocket.destroy();
    });
});

setInterval(() => {
  if (state.backendProc && state.openConnections === 0) {
    const idleMs = Date.now() - state.lastActivity;
    if (idleMs > IDLE_MS) {
      log(`Idle for ${Math.round(idleMs / 60000)} min with no open connections — stopping backend.`);
      stopBackend();
    }
  }
}, WATCHDOG_INTERVAL_MS);

server.listen(GATEWAY_PORT, '127.0.0.1', () => {
  log(`Gateway listening on http://localhost:${GATEWAY_PORT} (backend port ${BACKEND_PORT}, idle timeout ${IDLE_MS / 60000}m)`);
});
