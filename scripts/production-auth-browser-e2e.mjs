import { spawn } from "node:child_process";
import net from "node:net";

const baseUrl = String(process.env.SMART_DATA_AGENT_AUTH_E2E_URL || "").replace(/\/$/, "");
const profile = String(process.env.SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE || "");
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const debugPort = await freePort();
const chrome = spawn(chromePath, [
  "--headless=new",
  `--remote-debugging-port=${debugPort}`,
  `--user-data-dir=${profile}`,
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  baseUrl,
], { stdio: ["ignore", "pipe", "pipe"] });

try {
  const target = await waitForTarget(debugPort, 30_000);
  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.open();
  const responseStatuses = [];
  cdp.on("Network.responseReceived", (event) => {
    const url = String(event?.response?.url || "");
    if (url.startsWith(baseUrl) && url.includes("/api/")) {
      responseStatuses.push({ url, status: Number(event.response.status || 0) });
    }
  });
  await cdp.send("Page.enable");
  await cdp.send("Network.enable");
  await cdp.send("Page.navigate", { url: baseUrl });
  await waitFor(async () => Boolean(await cdp.evaluate("document.readyState !== 'loading'")), 30_000);
  const result = await cdp.evaluate(`
    (async () => {
      const request = async (path, init = {}) => {
        const response = await fetch(path, { credentials: "include", ...init });
        let body = {};
        try { body = await response.json(); } catch {}
        return { status: response.status, body };
      };
      const me = await request("/api/auth/me");
      if (me.status !== 200) return { authenticated: false, me };
      const directory = Array.isArray(me.body.tenant_directory) ? me.body.tenant_directory : [];
      const current = String(me.body.tenant_id || "");
      const canonical = directory.find((item) => item.id === current);
      const navigationCookieOnly = await request("/api/navigation");
      const navigationCanonical = await request("/api/navigation", { headers: { "X-Tenant-Id": encodeURIComponent(current) } });
      const representative = await request("/api/data-assets", { headers: { "X-Tenant-Id": encodeURIComponent(current) } });
      const alternate = directory.find((item) => item.id && item.id !== current);
      const tenantSwitch = alternate
        ? await request("/api/navigation", { headers: { "X-Tenant-Id": encodeURIComponent(alternate.id) } })
        : { status: 200, skipped: true };
      const refresh = await request("/api/auth/refresh", { method: "POST" });
      const afterRefresh = await request("/api/navigation", { headers: { "X-Tenant-Id": encodeURIComponent(current) } });
      return {
        authenticated: true,
        canonicalTenant: Boolean(canonical),
        directoryCount: directory.length,
        statuses: {
          me: me.status,
          navigationCookieOnly: navigationCookieOnly.status,
          navigationCanonical: navigationCanonical.status,
          representative: representative.status,
          tenantSwitch: tenantSwitch.status,
          refresh: refresh.status,
          afterRefresh: afterRefresh.status,
        },
      };
    })()
  `, true);
  if (!result?.authenticated) throw new Error("candidate browser profile is not authenticated; complete OIDC login in this dedicated profile first");
  if (!result.canonicalTenant || result.directoryCount < 1) throw new Error(`canonical tenant directory missing: ${JSON.stringify(result)}`);
  const failures = Object.entries(result.statuses || {}).filter(([, status]) => status !== 200);
  if (failures.length) throw new Error(`auth business flow failed: ${JSON.stringify(result)}`);
  const storms = responseStatuses.filter((item) => item.status === 401 || item.status === 429);
  if (storms.length) throw new Error(`401/429 storm detected: ${JSON.stringify(storms)}`);
  console.log(JSON.stringify({ status: "passed", ...result, protectedRequestCount: responseStatuses.length }));
  cdp.close();
} finally {
  chrome.kill("SIGTERM");
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitForTarget(port, timeoutMs) {
  let target;
  await waitFor(async () => {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      target = targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
      return Boolean(target);
    } catch {
      return false;
    }
  }, timeoutMs);
  return target;
}

async function waitFor(predicate, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("timed out waiting for browser condition");
}

class CDP {
  constructor(url) {
    this.url = url;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
  }
  open() {
    return new Promise((resolve, reject) => {
      this.socket = new WebSocket(this.url);
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
      this.socket.addEventListener("message", (event) => this.receive(String(event.data)));
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  async evaluate(expression, awaitPromise = false) {
    const response = await this.send("Runtime.evaluate", { expression, awaitPromise, returnByValue: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text || "browser evaluation failed");
    return response.result?.value;
  }
  on(method, listener) {
    const listeners = this.listeners.get(method) || [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }
  receive(raw) {
    const message = JSON.parse(raw);
    if (message.id) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result || {});
      return;
    }
    for (const listener of this.listeners.get(message.method) || []) listener(message.params || {});
  }
  close() { this.socket?.close(); }
}
