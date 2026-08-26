import { spawn } from "node:child_process";
import net from "node:net";
import WebSocket from "ws";
import { browserExecutableVersion, resolveBrowserExecutable } from "./browser-executable.mjs";

const baseUrl = String(process.env.SMART_DATA_AGENT_AUTH_E2E_URL || "").replace(/\/$/, "");
const profile = String(process.env.SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE || "");
const analysisContract = readAnalysisContract();
const browserExecutable = resolveBrowserExecutable();
const chromePath = browserExecutable.path;
const chromeVersion = browserExecutableVersion(chromePath);
const debugPort = await freePort();
const chrome = spawn(chromePath, [
  "--headless=new",
  "--remote-debugging-address=127.0.0.1",
  `--remote-debugging-port=${debugPort}`,
  "--remote-allow-origins=*",
  `--user-data-dir=${profile}`,
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  baseUrl,
], { stdio: ["ignore", "pipe", "pipe"] });

try {
  const target = await waitForTarget(debugPort, baseUrl, 30_000);
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
  // Chrome was launched with baseUrl already. Re-navigating the same target
  // races authentication restoration and can suppress the raw CDP response.
  await waitFor(async () => Boolean(await cdp.evaluate("document.readyState !== 'loading'")), 30_000);
  const result = await cdp.evaluate(`
    (async () => {
      const analysisInput = ${JSON.stringify(analysisContract)};
      const request = async (path, init = {}, timeoutMs = 30_000) => {
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
        let response;
        try {
          response = await fetch(path, { credentials: "include", ...init, signal: controller.signal });
        } finally {
          window.clearTimeout(timeout);
        }
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
      const analysis = analysisInput
        ? await runRealAnalysis(request, analysisInput)
        : { skipped: true };
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
        analysis,
      };

      async function runRealAnalysis(request, input) {
        const tenantHeader = { "X-Tenant-Id": encodeURIComponent(input.tenantId) };
        const assets = await request("/api/data-assets?refresh=1", { headers: tenantHeader });
        if (assets.status !== 200) {
          return { status: "failed", marker: "analysis_e2e_data_assets_unavailable", httpStatus: assets.status };
        }
        const rawTables = Array.isArray(assets.body?.raw_tables) ? assets.body.raw_tables : [];
        const matches = rawTables.filter((table) =>
          String(table?.relativePath || table?.relative_path || "") === input.relativePath &&
          String(table?.contentHash || table?.content_hash || "") === input.contentHash
        );
        if (matches.length !== 1) {
          return {
            status: "failed",
            marker: "analysis_e2e_asset_match_invalid",
            matchCount: matches.length,
            catalogTableCount: rawTables.length,
          };
        }
        const currentTable = matches[0];
        const staleTable = {
          ...currentTable,
          tenantId: input.tenantId,
          tenant_id: input.tenantId,
          assetId: "",
          asset_id: "",
          id: "historical-e2e-stale-id",
          code: "historical-e2e-stale-code",
          tableNameEn: "historical-e2e-stale-table",
          sourceKey: "historical-e2e-stale-source-key",
          source_key: "historical-e2e-stale-source-key",
          analysisResolution: undefined,
        };
        const requestId = "release-analysis-" + Date.now() + "-" + Math.random().toString(16).slice(2);
        const enqueue = await request("/api/analysis/run-async", {
          method: "POST",
          headers: {
            ...tenantHeader,
            "Content-Type": "application/json",
            "Idempotency-Key": requestId,
          },
          body: JSON.stringify({
            question: input.question,
            request_id: requestId,
            page_context: {
              route: "self-analysis/query",
              analysis_scene_hint: "self_analysis",
              selected_data_tables: [staleTable],
            },
          }),
        });
        const runId = String(enqueue.body?.run?.automation_run_id || "");
        if (enqueue.status !== 202 || !runId) {
          return { status: "failed", marker: "analysis_e2e_enqueue_failed", httpStatus: enqueue.status };
        }
        const deadline = Date.now() + input.timeoutMs;
        let run = enqueue.body.run;
        while (!["succeeded", "failed", "cancelled"].includes(String(run?.status || ""))) {
          if (Date.now() >= deadline) {
            return { status: "failed", marker: "analysis_e2e_terminal_timeout", runId };
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1_000));
          const poll = await request(
            "/api/analysis/run-status?run_id=" + encodeURIComponent(runId),
            { headers: tenantHeader },
          );
          if (poll.status !== 200) {
            return { status: "failed", marker: "analysis_e2e_poll_failed", httpStatus: poll.status, runId };
          }
          run = poll.body?.run || {};
        }
        if (run.status !== "succeeded") {
          return {
            status: "failed",
            marker: "analysis_e2e_terminal_failed",
            runId,
            runStatus: String(run.status || ""),
            errorCode: String(run.error_code || run.error_details?.error || ""),
            errorStage: String(run.error_details?.stage || ""),
          };
        }
        const taskRef = (Array.isArray(run.result_refs) ? run.result_refs : [])
          .find((ref) => ref?.type === "task" && ref?.id);
        const taskId = String(taskRef?.id || "");
        if (!taskId) {
          return { status: "failed", marker: "analysis_e2e_task_reference_missing", runId };
        }
        const taskResponse = await request(
          "/api/analysis/task?task_id=" + encodeURIComponent(taskId),
          { headers: tenantHeader },
        );
        if (taskResponse.status !== 200) {
          return {
            status: "failed",
            marker: "analysis_e2e_task_fetch_failed",
            httpStatus: taskResponse.status,
            runId,
            taskId,
          };
        }
        const task = taskResponse.body?.task || {};
        const selected = Array.isArray(task.asset_context?.selected_data_tables)
          ? task.asset_context.selected_data_tables
          : [];
        const resolvedTable = selected.find((table) =>
          String(table?.relativePath || table?.relative_path || "") === input.relativePath &&
          String(table?.contentHash || table?.content_hash || "") === input.contentHash
        );
        const resolution = resolvedTable?.analysisResolution || {};
        if (
          !resolvedTable ||
          resolution.serverAuthorized !== true ||
          resolution.matchStrategy !== "path_content_hash" ||
          String(resolution.tenantId || "") !== input.tenantId ||
          String(resolution.relativePath || "") !== input.relativePath ||
          String(resolution.contentHash || "") !== input.contentHash
        ) {
          return {
            status: "failed",
            marker: "analysis_e2e_asset_rebind_missing",
            runId,
            taskId,
            matchStrategy: String(resolution.matchStrategy || ""),
          };
        }
        const results = Array.isArray(task.skill_results) ? task.skill_results : [];
        const rowCount = results.reduce(
          (count, item) => count + (Array.isArray(item?.data) ? item.data.length : 0),
          0,
        );
        if (rowCount < 1) {
          return { status: "failed", marker: "analysis_e2e_result_rows_missing", runId, taskId };
        }
        return {
          status: "passed",
          tenantId: input.tenantId,
          relativePath: input.relativePath,
          contentHash: input.contentHash,
          runId,
          taskId,
          rowCount,
          matchStrategy: resolution.matchStrategy,
        };
      }
    })()
  `, true, Math.max(30_000, (analysisContract?.timeoutMs || 0) + 30_000));
  if (!result?.authenticated) throw new Error("candidate browser profile is not authenticated; complete OIDC login in this dedicated profile first");
  if (!result.canonicalTenant || result.directoryCount < 1) throw new Error(`canonical tenant directory missing: ${JSON.stringify(result)}`);
  const failures = Object.entries(result.statuses || {}).filter(([, status]) => status !== 200);
  if (failures.length) throw new Error(`auth business flow failed: ${JSON.stringify(result)}`);
  if (result.analysis?.status === "failed") throw new Error(`real analysis flow failed: ${JSON.stringify(result.analysis)}`);
  const storms = responseStatuses.filter((item) => item.status === 401 || item.status === 429);
  if (storms.length) throw new Error(`401/429 storm detected: ${JSON.stringify(storms)}`);
  console.log(JSON.stringify({
    status: "passed",
    ...result,
    protectedRequestCount: responseStatuses.length,
    browser: { ...browserExecutable, version: chromeVersion },
  }));
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

function readAnalysisContract() {
  const input = {
    tenantId: String(process.env.SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID || "").trim(),
    relativePath: String(process.env.SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH || "").trim(),
    contentHash: String(process.env.SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH || "").trim(),
    question: String(process.env.SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION || "").trim(),
  };
  const provided = Object.values(input).filter(Boolean).length;
  if (provided === 0) return null;
  if (provided !== Object.keys(input).length) {
    throw new Error("analysis_e2e_contract_partial");
  }
  if (
    input.relativePath.startsWith("/") ||
    input.relativePath.includes("\\") ||
    input.relativePath.split("/").some((segment) => !segment || segment === "." || segment === "..")
  ) {
    throw new Error("analysis_e2e_relative_path_invalid");
  }
  if (!/^[0-9a-f]{64}$/.test(input.contentHash)) {
    throw new Error("analysis_e2e_content_hash_invalid");
  }
  const timeoutRaw = String(process.env.SMART_DATA_AGENT_ANALYSIS_E2E_TIMEOUT_MS || "600000").trim();
  if (!/^\d+$/.test(timeoutRaw)) throw new Error("analysis_e2e_timeout_invalid");
  const timeoutMs = Number(timeoutRaw);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 30_000 || timeoutMs > 900_000) {
    throw new Error("analysis_e2e_timeout_invalid");
  }
  return { ...input, timeoutMs };
}

async function waitForTarget(port, expectedBaseUrl, timeoutMs) {
  let target;
  await waitFor(async () => {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      target = targets.find((item) =>
        item.type === "page" &&
        item.webSocketDebuggerUrl &&
        String(item.url || "").startsWith(expectedBaseUrl),
      );
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
      const timeout = setTimeout(() => {
        this.socket?.close();
        reject(new Error(`timed out opening CDP WebSocket: ${this.url}`));
      }, 10_000);
      this.socket.addEventListener("open", () => { clearTimeout(timeout); resolve(); }, { once: true });
      this.socket.addEventListener("error", (error) => { clearTimeout(timeout); reject(error); }, { once: true });
      this.socket.addEventListener("message", (event) => this.receive(String(event.data)));
    });
  }
  send(method, params = {}, timeoutMs = 15_000) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`timed out waiting for CDP command ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.socket.send(JSON.stringify({ id, method, params }));
      } catch (error) {
        this.pending.delete(id);
        clearTimeout(timer);
        reject(error);
      }
    });
  }
  async evaluate(expression, awaitPromise = false, timeoutMs = 15_000) {
    const response = await this.send(
      "Runtime.evaluate",
      { expression, awaitPromise, returnByValue: true },
      timeoutMs,
    );
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
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result || {});
      return;
    }
    for (const listener of this.listeners.get(message.method) || []) listener(message.params || {});
  }
  close() {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error(`CDP connection closed before command ${id} completed`));
    }
    this.pending.clear();
    this.socket?.close();
  }
}
