import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import net from "node:net";

const root = process.cwd();
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const authStorageKey = "smart_data_agent_auth_session_v1";
const selectedInstitutionStorageKey = "smart_data_agent_selected_institution_v1";

async function main() {
  const apiPort = await freePort();
  const vitePort = await freePort();
  const debugPort = await freePort();
  const workDir = await mkdtemp(join(tmpdir(), "sda-frontend-permissions-"));
  const apiUrl = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}`;
  const processes = [];
  const reportIngressBindings = JSON.stringify({ bindings: [{
    id: "frontend-report-smoke",
    token: "frontend-report-smoke-token",
    channel: "workbuddy",
    tenant_id: "tenant:华兴银行",
    user_id: "u_super_admin",
    visibility: "private",
  }] });

  try {
  const api = spawn(
    "uv",
    ["run", "python", "-m", "backend.platform.api.server", "--host", "127.0.0.1", "--port", String(apiPort), "--test-sqlite-db", join(workDir, "api.sqlite")],
    {
      cwd: root,
      env: {
        ...process.env,
        SMART_DATA_AGENT_DATABASE_URL: "",
        SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON: reportIngressBindings,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  processes.push(api);
  const apiOutput = captureChildOutput(api);
  await waitForHttp(`${apiUrl}/api/health`, 90_000, api, apiOutput);

  const vite = spawn(
    "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(vitePort)],
    {
      cwd: root,
      env: { ...process.env, VITE_ANALYSIS_API_URL: "", SMART_DATA_AGENT_API_PROXY_TARGET: apiUrl },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  processes.push(vite);
  await waitForHttp(appUrl, 45_000);

  const chrome = spawn(
    chromePath,
    [
      "--headless=new",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${join(workDir, "chrome-profile")}`,
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      "about:blank",
    ],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  processes.push(chrome);
  await waitForHttp(`http://127.0.0.1:${debugPort}/json/version`);

  const page = await openPage(debugPort, `${appUrl}/login`);
  const cdp = new CDPClient(page.webSocketDebuggerUrl);
  await cdp.open();
  await cdp.send("Page.enable");
  await cdp.send("Network.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 960,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigate(cdp, `${appUrl}/login`);
  await waitForEval(cdp, `location.pathname === "/login" && document.readyState !== "loading"`);
  await delay(500);
  const unauthenticatedProtectedRequests = await cdp.evaluate(`
    performance.getEntriesByType("resource")
      .map((entry) => entry.name)
      .filter((url) => /\\/api\\/(?:navigation|system-config|auth\\/(?:me|refresh))(?:[/?]|$)/.test(url))
  `);
  if (unauthenticatedProtectedRequests?.length) {
    throw new Error(`login page must not request protected endpoints before authentication: ${JSON.stringify(unauthenticatedProtectedRequests)}`);
  }

  await installSession(cdp, appUrl, "xujingbo-jk@qifu.com", "华兴银行");
  const restoredCookieUser = await cdp.evaluate(
    `fetch("/api/auth/me", { credentials: "include" }).then(async (response) => response.ok ? (await response.json()).user?.id : "")`,
    true,
  );
  if (restoredCookieUser !== "u_super_admin") {
    throw new Error("the login response must establish the HttpOnly browser session");
  }
  const navigationProbe = await cdp.evaluate(
    `fetch("/api/navigation", { credentials: "include", headers: { "X-Tenant-Id": "tenant%3A%E5%8D%8E%E5%85%B4%E9%93%B6%E8%A1%8C" } }).then(async (response) => ({ status: response.status, body: await response.text() }))`,
    true,
  );
  if (navigationProbe?.status !== 200) {
    throw new Error(`frontend proxy navigation probe failed: ${JSON.stringify(navigationProbe)}`);
  }
  // The local marker allows a session check; the HttpOnly cookie remains the
  // authority. Without that marker the login page intentionally makes no
  // protected requests, as asserted above.
  await navigate(cdp, `${appUrl}/`);
  await waitForEval(cdp, `location.pathname === "/self-analysis/query" && document.body.innerText.includes("智能分析")`);
  await waitForEval(cdp, `JSON.parse(localStorage.getItem(${JSON.stringify(authStorageKey)}))?.user?.id === "u_super_admin"`);
  await navigate(cdp, `${appUrl}/settings/config`, 30_000);
  await waitForEval(cdp, `Boolean(location.pathname === "/settings/config" && document.querySelector('[data-settings-upper-module="model-access"]') && document.querySelector('[data-settings-route-body="config"]'))`);
  await assertEval(
    cdp,
    `JSON.parse(localStorage.getItem(${JSON.stringify(authStorageKey)}))?.user?.id === "u_super_admin"`,
    "the cached session marker must be revalidated against the HttpOnly session",
  );
  await cdp.evaluate(`[...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "自助分析")?.click()`);
  await assertEval(cdp, `(() => { const group = [...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "自助分析")?.parentElement; return [...(group?.querySelectorAll("a") || [])].map((link) => link.getAttribute("href")).join("|") === "/self-analysis/visual-reports|/self-analysis/query|/self-analysis/config|/agent/skills"; })()`, "Visual reports must precede intelligent analysis and Skill plugins must follow analysis configuration under self analysis");
  await assertEval(cdp, `(() => { const nav = document.querySelector("nav"); const business = [...(nav?.querySelectorAll("button") || [])].find((button) => button.textContent.trim() === "经营分析"); const reports = nav?.querySelector('a[href="/self-analysis/reports"]'); const self = [...(nav?.querySelectorAll("button") || [])].find((button) => button.textContent.trim() === "自助分析"); return Boolean(business && reports && self && (business.compareDocumentPosition(reports) & Node.DOCUMENT_POSITION_FOLLOWING) && (reports.compareDocumentPosition(self) & Node.DOCUMENT_POSITION_FOLLOWING)); })()`, "My reports must be a top-level entry between business analysis and self analysis");
  await cdp.evaluate(`[...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "任务工作台")?.click()`);
  await assertEval(cdp, `(() => { const group = [...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "任务工作台")?.parentElement; return [...(group?.querySelectorAll("a") || [])].map((link) => link.getAttribute("href")).join("|") === "/agent/todos|/agent/tasks|/agent/message-board"; })()`, "task workbench must render todos, automation tasks and message-board management, without Skill plugins");
  await configureApplicationModel(cdp, appUrl, "intelligent_analysis_reasoning", "经营分析中转站A", "中转站", ["gpt-5.5", "deepseek-v4-flash"], "model_analysis_relay_a");
  await configureApplicationModel(cdp, appUrl, "intelligent_analysis_reasoning", "经营分析中转站B", "中转站", ["qwen-plus"], "model_analysis_relay_b");
  await configureApplicationModel(cdp, appUrl, "intelligent_analysis_reasoning", "Claude 官方模型", "官方网站", ["claude-sonnet-4"], "model_analysis_official");
  await configureSpeechIntegration(cdp, appUrl, "realtime_voice_input", "speech_frontend_realtime");
  await configureSpeechIntegration(cdp, appUrl, "popup_voice_input", "speech_frontend_popup");
  await cdp.evaluate(`
    (() => {
      const session = JSON.parse(localStorage.getItem(${JSON.stringify(authStorageKey)}));
      session.institution = "tenant_demo";
      session.tenant_id = "tenant_demo";
      localStorage.setItem(${JSON.stringify(authStorageKey)}, JSON.stringify(session));
      localStorage.setItem(${JSON.stringify(selectedInstitutionStorageKey)}, "tenant_demo");
    })()
  `);
  await navigate(cdp, `${appUrl}/settings/roles`);
  await waitForEval(cdp, `document.body.innerText.includes("用户管理") && document.body.innerText.includes("角色权限")`);
  await assertEval(cdp, `!document.body.innerText.includes("tenant_demo")`, "internal tenant id must never be rendered");
  await assertEval(
    cdp,
    `(() => { const value = localStorage.getItem(${JSON.stringify(selectedInstitutionStorageKey)}); return Boolean(value) && value !== "tenant_demo" && !value.startsWith("tenant:"); })()`,
    "invalid cached tenant id should be replaced with an authorized institution name",
  );
  await cdp.evaluate(`localStorage.setItem(${JSON.stringify(selectedInstitutionStorageKey)}, "全部机构")`);
  await navigate(cdp, `${appUrl}/dashboard`);
  await assertEval(cdp, `!document.body.innerText.includes("全部机构 ·")`, "global permission scope must not become the selected institution");
  await assertEval(
    cdp,
    `document.body.innerText.includes("华兴银行")`,
    "invalid global scope cache should resolve to the canonical first authorized bank",
  );
  await waitForEval(cdp, `Boolean(document.querySelector('button[aria-label="收起左侧菜单"]'))`);
  await cdp.evaluate(`window.__shellMainRect = document.querySelector('main[data-agent-main-shell]')?.getBoundingClientRect().toJSON()`);
  await cdp.evaluate(`document.querySelector('button[aria-label="收起左侧菜单"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('aside[data-agent-sidebar]')?.dataset.collapsed === "true" && Boolean(document.querySelector('button[aria-label="展开左侧菜单"]'))`);
  await waitForEval(cdp, `document.querySelector('main[data-agent-main-shell]')?.getBoundingClientRect().left < 1`);
  await assertEval(cdp, `(() => { const aside = document.querySelector('aside[data-agent-sidebar]'); const rect = document.querySelector('main[data-agent-main-shell]')?.getBoundingClientRect(); return aside?.innerText.trim() === "" && aside.getBoundingClientRect().width < 1 && rect && rect.left < 1 && Math.abs(rect.width - (window.__shellMainRect.width + window.__shellMainRect.left)) < 1; })()`, "collapsed sidebar must be empty and let the main page fill the released width");
  await assertEval(cdp, `getComputedStyle(document.querySelector('button[aria-label="展开左侧菜单"]')).opacity === "0"`, "sidebar expand affordance must be hidden away from the top-left hover zone");
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 20, y: 20 });
  await waitForEval(cdp, `getComputedStyle(document.querySelector('button[aria-label="展开左侧菜单"]')).opacity === "1"`);
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 320, y: 180 });
  await waitForEval(cdp, `getComputedStyle(document.querySelector('button[aria-label="展开左侧菜单"]')).opacity === "0"`);
  await cdp.evaluate(`document.querySelector('button[aria-label="展开左侧菜单"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('aside[data-agent-sidebar]')?.dataset.collapsed === "false" && Boolean(document.querySelector('button[aria-label="收起左侧菜单"]'))`);
  await navigate(cdp, `${appUrl}/settings/roles`);
  await waitForEval(cdp, `document.body.innerText.includes("角色权限")`);
  await assertEval(cdp, `document.body.innerText.includes("审计日志")`, "super admin should see audit logs");
  await assertEval(cdp, `document.body.innerText.includes("系统配置")`, "super admin should see system config");

  await navigate(cdp, `${appUrl}/settings/config`);
  await waitForEval(cdp, `location.pathname === "/settings/config" && document.body.innerText.includes("模型接入")`);
  await cdp.evaluate(`
    fetch(${JSON.stringify(`${appUrl}/api/auth/login`)}, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "zhaomin@bank.com", password: "123456", institution: "郑州银行" })
    }).then((response) => {
      if (!response.ok) throw new Error("failed to switch the shared cookie session");
      window.dispatchEvent(new Event("focus"));
    })
  `, true);
  await waitForEval(cdp, `JSON.parse(localStorage.getItem(${JSON.stringify(authStorageKey)}))?.user?.id === "u_zhaomin"`);
  await waitForEval(cdp, `location.pathname === "/settings/config" && document.body.innerText.includes("审计日志") && document.body.innerText.includes("系统配置")`);
  const limitedConfigStatus = await cdp.evaluate(`fetch("/api/system-config", { credentials: "include", headers: { "X-Tenant-Id": encodeURIComponent("tenant:郑州银行") } }).then((response) => response.status)`, true);
  if (limitedConfigStatus !== 403) throw new Error(`limited user unexpectedly accessed system config: ${limitedConfigStatus}`);
  await assertEval(
    cdp,
    `Boolean(location.pathname === "/settings/config" && document.querySelector('[data-settings-upper-module="model-access"]') && document.querySelector('[data-settings-route-body="config"]'))`,
    "a limited user must keep the stable system-management menu without gaining system configuration access",
  );
  await installSession(cdp, appUrl, "xujingbo-jk@qifu.com", "华兴银行");
  await navigate(cdp, `${appUrl}/settings/roles`);
  await waitForEval(cdp, `document.body.innerText.includes("角色权限")`);

  await navigate(cdp, `${appUrl}/agent/skills`);
  await waitForEval(cdp, `document.body.innerText.includes("Skill插件") && [...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增场景")) && [...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "主题")`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增场景"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增场景"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label*="新增场景"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label*="新增场景"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new scene must open as a centered system modal");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭场景弹窗"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "主题")?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("Skill插件") && [...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "场景")`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增主题"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增主题"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label*="新增主题"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label*="新增主题"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new topic must open as a centered system modal");
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label*="新增主题"]'); return dialog && !dialog.innerText.includes("格式要求") && dialog.innerText.includes("主题 Skill 不设置固定格式"); })()`, "topic Skill must not expose a fixed output-format field and must explain adaptive visualization");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭主题弹窗"]')?.click()`);

  const memorySmokeItemId = "frontend_permission_memory_list";
  const memorySeedResult = await cdp.evaluate(`
    (async () => {
      const response = await fetch("/api/data-assets/item", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-User-Id": "u_super_admin",
          "X-Tenant-Id": encodeURIComponent("tenant:华兴银行")
        },
        body: JSON.stringify({
          item_type: "knowledge_file",
          item: {
            id: ${JSON.stringify("frontend_permission_memory_list")},
            title: "前端权限验收记忆",
            content: "用于验证知识记忆 List 的查看、编辑和删除入口。",
            coverage: "前端权限自动化",
            items: 1,
            owner: "u_super_admin",
            tags: "权限,列表"
          }
        })
      });
      return { ok: response.ok, body: await response.text() };
    })()
  `, true);
  if (!memorySeedResult?.ok) throw new Error(`failed to seed memory list item: ${memorySeedResult?.body || "unknown"}`);

  await navigate(cdp, `${appUrl}/data-assets/knowledge`);
  await waitForEval(cdp, `document.body.innerText.includes("知识记忆") && document.body.innerText.includes("知识文件仅用于提炼意图")`, 60_000);
  await assertEval(cdp, `!document.body.innerText.includes("知识文件提炼任务") && !document.body.innerText.includes("新建提炼任务")`, "knowledge memory page must no longer own automation-task management");
  await assertEval(cdp, `(() => { const selects = [...document.querySelectorAll("select")]; return selects.some((node) => [...node.options].some((option) => option.textContent.includes("按时间倒排"))) && selects.some((node) => [...node.options].some((option) => option.textContent.includes("全部状态"))); })()`, "knowledge memory must expose the same sort and status controls as behavior habits");
  await waitForEval(cdp, `(() => [...document.querySelectorAll('[role="list"]')].some((list) => list.querySelector('button[aria-label^="查看"]') && list.querySelector('button[aria-label^="编辑"]') && list.querySelector('button[aria-label^="删除"]')))()`, 60_000);
  await assertEval(cdp, `(() => [...document.querySelectorAll('[role="list"]')].some((list) => { const labels = [...list.querySelectorAll('button[aria-label]')].map((button) => button.getAttribute('aria-label') || ''); return labels.some((label) => label.startsWith('查看')) && labels.some((label) => label.startsWith('编辑')) && labels.some((label) => label.startsWith('删除')); }))()`, "knowledge memories must render as lists with view, edit, and delete actions");
  await assertEval(cdp, `[...document.querySelectorAll('button')].some((button) => button.textContent.includes('新增记忆')) && [...document.querySelectorAll('button')].some((button) => button.textContent.includes('新增行为习惯'))`, "each memory submodule toolbar must expose an add action");
  await cdp.evaluate(`document.querySelector('[role="list"] button[aria-label^="查看"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label^="查看"]'))`);
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label^="查看"]'); return dialog && [...dialog.querySelectorAll('input,textarea')].every((control) => control.readOnly) && dialog.innerText.includes('编辑'); })()`, "memory view dialog must be read-only and offer edit to authorized maintainers");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭记忆窗口"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll('button')].find((button) => button.textContent.includes('新增记忆'))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label^="新增"]'))`);
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label^="新增"]'); const type = dialog?.querySelector('select[aria-label="记忆类型"]'); return type && ['意图','知识文件','分析经验','行为习惯'].every((label) => [...type.options].some((option) => option.textContent.trim() === label)); })()`, "add memory must allow choosing all governed memory list types");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭记忆窗口"]')?.click()`);
  const memoryCleanupResult = await cdp.evaluate(`
    fetch("/api/data-assets/item?item_type=knowledge_file&item_id=${encodeURIComponent(memorySmokeItemId)}", {
      method: "DELETE",
      credentials: "include",
      headers: {
        "X-User-Id": "u_super_admin",
        "X-Tenant-Id": encodeURIComponent("tenant:华兴银行")
      }
    }).then(async (response) => ({ ok: response.ok, body: await response.text() }))
  `, true);
  if (!memoryCleanupResult?.ok) throw new Error(`failed to clean up memory list item: ${memoryCleanupResult?.body || "unknown"}`);

  await navigate(cdp, `${appUrl}/data-assets/data-management`);
  await waitForEval(cdp, `document.body.innerText.includes("原始表仅读取当前机构") && document.body.innerText.includes("原始表") && document.body.innerText.includes("主题表")`);
  await assertEval(cdp, `!document.body.innerText.includes("新增原始表") && !document.body.innerText.includes("数据接入") && !document.body.innerText.includes("爬虫")`, "CSV-only data management must not expose retired raw-upload, data-access, or crawler controls");
  await assertEval(cdp, `(() => { const text = document.body.innerText; return text.includes("/app/data/华兴银行/") && !text.includes("Origin_Data"); })()`, "data management must describe the selected institution Data Crawler folder and never expose the retired shared Origin_Data source");

  await navigate(cdp, `${appUrl}/agent/tasks`);
  await waitForEval(cdp, `document.body.innerText.includes("自动化任务") && [...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增自动化任务"))`);
  await assertEval(cdp, `!document.body.innerText.includes("任务触发洞察")`, "task-triggered insight submodule must be removed");
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增自动化任务"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label="新建自动化任务"]'))`);
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新建自动化任务"]'); const status = dialog.querySelector('select[aria-label="任务状态"]'); const kind = dialog.querySelector('select[aria-label="自动化类型"]'); const options = [...kind.options].map((option) => option.textContent.trim()); return !dialog.innerText.includes("任务类别") && Boolean(dialog.querySelector('input[aria-label="任务名称"]')) && ["运行中","暂停","终止"].every((label) => [...status.options].some((option) => option.textContent.trim() === label)) && ["记忆提取任务","自动分析任务"].every((label) => options.includes(label)) && !options.some((label) => label.startsWith("数据获取任务")); })()`, "new automation tasks must exclude paused acquisition while preserving memory and automatic-analysis types");
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新建自动化任务"]'); return !dialog.querySelector('select[aria-label="数据获取脚本"]') && dialog.innerText.includes("数据由配置的 CSV 文件夹提供") && dialog.innerText.includes("近三次运行情况"); })()`, "new automation tasks must use the configured CSV folder instead of crawler acquisition");
  await cdp.evaluate(`(() => { const select = document.querySelector('select[aria-label="自动化类型"]'); select.value = "memory"; select.dispatchEvent(new Event("change", { bubbles: true })); })()`);
  await waitForEval(cdp, `Boolean(document.querySelector('textarea[aria-label="知识提炼 Prompt"]'))`);
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新建自动化任务"]'); return ["分析经验","意图管理","分析习惯","运营习惯","汇报习惯"].every((label) => dialog.innerText.includes(label)) && dialog.innerText.includes("知识文件输入") && !dialog.innerText.includes("原始表") && !dialog.innerText.includes("主题表"); })()`, "memory task must use knowledge files only and expose all five governed outputs");
  await assertEval(cdp, `(() => {
    const dialog = document.querySelector('[role="dialog"][aria-label="新建自动化任务"]');
    const sourceGrid = dialog.querySelector('[data-memory-source-grid]');
    const outputGrid = dialog.querySelector('[data-memory-output-grid]');
    const prompt = dialog.querySelector('[data-memory-prompt] textarea');
    const name = dialog.querySelector('input[aria-label="任务名称"]')?.getBoundingClientRect();
    const status = dialog.querySelector('select[aria-label="任务状态"]')?.getBoundingClientRect();
    const rect = dialog.getBoundingClientRect();
    return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20
      && dialog.scrollWidth <= dialog.clientWidth + 1
      && getComputedStyle(sourceGrid).gridTemplateColumns.split(" ").length === 2
      && getComputedStyle(outputGrid).gridTemplateColumns.split(" ").length === 3
      && prompt.getBoundingClientRect().width >= prompt.parentElement.getBoundingClientRect().width - 2
      && Math.abs(name.top - status.top) < 2;
  })()`, "memory modal must match the reference structure: centered, two-column inputs, three-column outputs, green selected cards, full-width prompt, and aligned first row");
  await cdp.evaluate(`(() => { const select = document.querySelector('select[aria-label="自动化类型"]'); select.value = "automatic_analysis"; select.dispatchEvent(new Event("change", { bubbles: true })); })()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-automatic-analysis-config]'))`);
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新建自动化任务"]'); return Boolean(dialog.querySelector('[data-automatic-analysis-config]')) && Boolean(dialog.querySelector('[data-anomaly-rule]')) && Boolean(dialog.querySelector('textarea[aria-label="归因分析 Prompt"]')) && dialog.innerText.includes("未命中时记录监控结果，不调用 Data_Agent") && dialog.innerText.includes("指标表、描述、口径、Skill、Prompt、规则和查询证据"); })()`, "automatic analysis must expose its governed prompt and hard anomaly gate");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭任务弹窗"]')?.click()`);

  await navigate(cdp, `${appUrl}/data-assets/tools`);
  await waitForEval(cdp, `document.body.innerText.includes("Confluence知识检索") && document.body.innerText.includes("Outlook邮箱调用") && document.body.innerText.includes("财务分析师")`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增工具"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增工具"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label="新增工具"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label="新增工具"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new tool must open as a centered system modal");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭工具弹窗"]')?.click()`);

  await navigate(cdp, `${appUrl}/agent/skills`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[aria-label="删除风险策略分析"]'))`);
  await cdp.evaluate(`window.confirm = () => true; document.querySelector('button[aria-label="删除风险策略分析"]')?.click()`);
  await waitForEval(cdp, `!document.querySelector('button[aria-label="删除风险策略分析"]')`);

  await navigate(cdp, `${appUrl}/self-analysis/config`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增分析配置"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增分析配置"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label="新增分析配置"]'))`);
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新增分析配置"]'); const rect = dialog.getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20 && Boolean(dialog.querySelector('summary[aria-label="选择分析记忆"]')) && dialog.innerText.includes("只保存记忆 ID") && !dialog.innerText.includes("风险策略分析") && Boolean(dialog.querySelector('button[aria-label="关闭编辑分析配置"]')); })()`, "analysis configuration must use the centered modal and the same active Skill catalog as the Skill plugin");
  await cdp.evaluate(`(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新增分析配置"]'); [...dialog.querySelectorAll("button")].find((button) => button.textContent.trim() === "保存")?.click(); })()`);
  await waitForEval(cdp, `document.querySelector('[role="dialog"][aria-label="新增分析配置"] [role="alert"]')?.textContent.includes("请填写快捷键名称和分析问题")`);
  await cdp.evaluate(`(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新增分析配置"]'); const [title] = dialog.querySelectorAll("input"); const [query] = dialog.querySelectorAll("textarea"); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(title, "自动化测试分析配置"); title.dispatchEvent(new Event("input", { bubbles: true })); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(query, "测试保存后的配置回读"); query.dispatchEvent(new Event("input", { bubbles: true })); [...dialog.querySelectorAll("button")].find((button) => button.textContent.trim() === "保存")?.click(); })()`);
  await waitForEval(cdp, `!document.querySelector('[role="dialog"][aria-label="新增分析配置"]') && document.body.innerText.includes("自动化测试分析配置")`);
  await cdp.evaluate(`window.confirm = () => true; document.querySelector('button[aria-label="删除自动化测试分析配置"]')?.click()`);
  await waitForEval(cdp, `!document.querySelector('button[aria-label="删除自动化测试分析配置"]')`);

  const importedReport = await cdp.evaluate(`
    fetch("/api/integrations/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer frontend-report-smoke-token" },
      body: JSON.stringify({
        source: { channel: "workbuddy", run_id: "frontend-visual-switch", report_id: "frontend-visual-switch" },
        report: {
          title: "可视化切换回归报告",
          query: "验证报告可视化切换",
          plan: "验证可视化菜单与持久化",
          summary: "用于隔离浏览器回归测试。",
          visual_types: { primary: "bar", secondary: "table" },
          rows: [{ 机构: "测试分行", 金额: 100 }, { 机构: "另一分行", 金额: 80 }],
        },
      }),
    }).then(async (response) => ({ status: response.status, body: await response.json() }))
  `, true);
  if (importedReport?.status !== 200 || !importedReport?.body?.result?.id) {
    throw new Error(`failed to create isolated report visual-switch fixture: ${JSON.stringify(importedReport)}`);
  }
  const importedReportId = importedReport.body.result.id;
  await navigate(cdp, `${appUrl}/self-analysis/reports`);
  await waitForEval(cdp, `document.body.innerText.includes("可视化切换回归报告")`);
  await cdp.evaluate(`[...document.querySelectorAll('button[aria-label="查看报告"]')].find((button) => button.closest("div")?.parentElement?.innerText.includes("可视化切换回归报告"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-visual-card="primary"] button[aria-label="展开可视化操作"]'))`);
  await cdp.evaluate(`document.querySelector('[data-visual-card="primary"] button[aria-label="展开可视化操作"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll('[data-visual-card="primary"] button')].find((button) => button.textContent.trim() === "样式")?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll('[data-visual-card="primary"] [data-visual-style-menu="true"] button')].some((button) => button.textContent.trim() === "条形图")`);
  await cdp.evaluate(`[...document.querySelectorAll('[data-visual-card="primary"] [data-visual-style-menu="true"] button')].find((button) => button.textContent.trim() === "条形图")?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll('[data-visual-card="primary"] button')].find((button) => button.textContent.trim() === "样式")?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll('[data-visual-card="primary"] [data-visual-style-menu="true"] button')].some((button) => button.textContent.trim() === "趋势图")`);
  await cdp.evaluate(`[...document.querySelectorAll('[data-visual-card="primary"] [data-visual-style-menu="true"] button')].find((button) => button.textContent.trim() === "趋势图")?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-visual-card="primary"] .recharts-line'))`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await navigate(cdp, `${appUrl}/self-analysis/reports`);
  await waitForEval(cdp, `document.body.innerText.includes("可视化切换回归报告")`);
  await cdp.evaluate(`[...document.querySelectorAll('button[aria-label="查看报告"]')].find((button) => button.closest("div")?.parentElement?.innerText.includes("可视化切换回归报告"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-visual-card="primary"] .recharts-line'))`);
  await cdp.evaluate(`fetch("/api/reports/analysis-result?result_id=${encodeURIComponent(importedReportId)}", { method: "DELETE" }).then((response) => { if (!response.ok) throw new Error("failed to clean up isolated report visual-switch fixture"); })`, true);
  await navigate(cdp, `${appUrl}/self-analysis/reports`);
  await waitForEval(cdp, `!document.body.innerText.includes("可视化切换回归报告")`);

  await navigate(cdp, `${appUrl}/settings/config`);
  await waitForEval(cdp, `Boolean(location.pathname === "/settings/config" && document.querySelector('[data-settings-upper-module="model-access"]') && document.querySelector('[data-settings-route-body="config"]'))`);
  await assertEval(cdp, `Boolean(document.querySelector('[data-system-config-summary="true"]') && document.querySelector('[data-system-config-summary="true"]')?.innerText.includes("系统运行概览") && document.querySelector('[data-system-config-summary="true"]')?.innerText.includes("数据刷新") && document.querySelector('[data-system-config-summary="true"]')?.innerText.includes("单次采集") && document.querySelector('[data-system-config-summary="true"]')?.innerText.includes("分析时限") && document.querySelector('[data-system-config-summary="true"]')?.innerText.includes("AI分析并发"))`, "system configuration must keep its four-card runtime summary beside model access");
  for (const [route, heading, upperKind, upperTitle] of [["users", "用户管理", "user-overview", "用户与角色概览"], ["roles", "角色权限", "role-overview", "权限范围概览"], ["audit", "审计日志", "audit-overview", "审计数据概览"], ["config", "系统配置", "model-access", "模型接入"]]) {
    await navigate(cdp, `${appUrl}/settings/${route}`);
    await waitForEval(cdp, `Boolean(location.pathname === "/settings/${route}" && [...document.querySelectorAll("main h2")].some((node) => node.textContent.trim() === ${JSON.stringify(heading)}) && document.querySelector('[data-settings-upper-module="${upperKind}"]') && document.querySelector('[data-settings-route-body="${route}"]'))`);
    await assertEval(cdp, `document.querySelectorAll('[data-settings-upper-module]').length === 1 && document.querySelector('[data-settings-upper-module="${upperKind}"]')?.innerText.includes(${JSON.stringify(upperTitle)})`, `system-management child page ${route} must show its own upper module only`);
    await assertEval(cdp, `Boolean(document.querySelectorAll('[data-settings-route-body]').length === 1 && document.querySelector('[data-settings-route-body="${route}"]'))`, `system-management child page ${route} must show only its route-specific lower body`);
    await assertEval(cdp, `!document.querySelector('nav[aria-label="系统管理子模块"]')`, `system-management child page ${route} must not duplicate the left navigation as tabs`);
    if (route === "audit") {
      await assertEval(cdp, `(() => { const pagination = document.querySelector('[data-audit-pagination="true"]'); const selector = pagination?.querySelector('select[aria-label="审计日志分页"]'); const selected = selector?.selectedOptions?.[0]?.textContent || ""; const countText = pagination?.innerText || ""; return Boolean(selector && selected.includes("第 1 页 / 共") && countText.includes(" / ") && countText.includes(" 条")); })()`, "audit logs must expose the shared top-right page selector and current/total counts");
      await assertEval(cdp, `!document.body.innerText.includes("u_super_admin") && document.body.innerText.includes("胥京波")`, "audit logs must show the authenticated profile name instead of the internal user id");
    }
  }
  await navigate(cdp, `${appUrl}/settings/config`);
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑模型接入"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("模型接入管理") && document.body.innerText.includes("新增模型")`);
  await assertEval(cdp, `!document.body.innerText.includes("应用范围：全部非语音模型模块")`, "large-model dialog must not show the removed application-scope module");
  await assertEval(cdp, `![...document.querySelectorAll("select option")].some((option) => ["intelligent_analysis_reasoning","weekly_report_conclusion_regeneration","automatic_analysis","memory_extraction","skill_evolution_learning"].includes(option.value))`, "large-model integrations must apply to every non-voice placeholder without a per-module selector");
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "语音转文字")?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("新增语音转文字接入")`);
  await assertEval(cdp, `!["应用范围：实时语音录入与弹窗语音录入","语音转文字能力","实时语音录入","弹窗语音录入"].some((label) => document.body.innerText.includes(label)) && ![...document.querySelectorAll("select option")].some((option) => ["realtime_voice_input","popup_voice_input"].includes(option.value))`, "speech dialog must not show the removed application-scope module or its voice submodules");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭弹窗"]')?.click()`);
  await assertEval(cdp, `!document.body.innerText.includes("数据接入") && !document.body.innerText.includes("爬虫")`, "system configuration must not expose the retired crawler or data-access module");

  await navigate(cdp, `${appUrl}/agent/todos`);
  await waitForEval(cdp, `document.body.innerText.includes("待办任务") && [...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "新建待办")`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "新建待办")?.click()`);
  await waitForEval(cdp, `document.querySelector('input[placeholder="负责人"]')?.value === "胥京波"`);
  await assertEval(cdp, `document.querySelector('input[placeholder="负责人"]')?.value === "胥京波"`, "new todo assignee must default to the authenticated user's display name");
  await assertEval(cdp, `!document.body.innerText.includes("u_super_admin")`, "todo workspace must not expose the internal user id as a visible name");
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "取消")?.click()`);

  await navigate(cdp, `${appUrl}/weekly-report`);
  await waitForEval(cdp, `document.body.innerText.includes("核心指标表现") && ["在贷余额","放款金额","新增余额"].every((label) => document.body.innerText.includes(label))`);
  await assertEval(cdp, `document.querySelector('[data-report-meta-key="reporters"] input')?.value === "胥京波"`, "weekly report reporter must default to the authenticated user's display name");
  await assertEval(cdp, `(() => { const tabs = [...document.querySelectorAll("button")].filter((button) => ["可视化分析","分析结论"].includes(button.textContent.trim())); return tabs[0]?.textContent.trim() === "可视化分析" && tabs[1]?.textContent.trim() === "分析结论" && !document.body.innerText.includes("待载入"); })()`, "weekly report must default to visualization before conclusion and render direct metric data without LLM placeholders");
  await waitForEval(cdp, `document.body.innerText.includes("核心指标周度趋势") && document.body.innerText.includes("按日期从早到晚 · 单位：亿元")`);
  await cdp.evaluate(`document.querySelector('[data-comment-target$="_data"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-comment-selection-action="true"]'))`);
  await dispatchRealDrag(cdp, '[data-weekly-selection-action="true"]', 28, 14);
  await dispatchRealClick(cdp, '[data-comment-selection-action="true"]');
  await waitForEval(cdp, `Boolean(document.querySelector('aside[data-context-page="weekly-report"][data-context-rail="expanded"] [data-draft-id] textarea'))`);
  await cdp.evaluate(`document.querySelector('aside[data-context-page="weekly-report"] [data-context-rail-collapse="true"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('aside[data-context-page="weekly-report"]')?.dataset.contextRail === "collapsed"`);
  await cdp.evaluate(`document.querySelector('[data-comment-target$="_data"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-analysis-selection-action="true"]'))`);
  await dispatchRealClick(cdp, '[data-analysis-selection-action="true"]');
  await waitForEval(cdp, `Boolean(document.querySelector('aside[data-context-page="weekly-report"][data-context-rail="expanded"] [data-analysis-workspace-panel="true"]'))`);
  await cdp.evaluate(`document.querySelector('aside[data-context-page="weekly-report"] [data-context-rail-collapse="true"]')?.click()`);
  if (process.env.SDA_SMOKE_STOP_AFTER_WEEKLY_FLOATING_ACTIONS === "true") return;
  await cdp.evaluate(`document.querySelector('button[data-weekly-page-data-mode-toggle="true"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('button[data-weekly-page-data-mode-toggle="true"]')?.textContent.includes("保存")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析数据模块"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("拖动排序 · 点击显隐") && document.body.innerText.includes("周报数据") && Boolean(document.querySelector('[data-weekly-unified-data-menu="true"]'))`);
  await assertEval(cdp, `(() => { const menu = document.querySelector('[data-weekly-unified-data-menu="true"]'); const rows = [...(menu?.querySelectorAll('[data-weekly-data-item]') || [])]; const pageRows = rows.filter((row) => row.dataset.weeklyDataKind === "page-data"); const protectedRows = rows.filter((row) => ["page-data", "core"].includes(row.dataset.weeklyDataKind)); const syncedRows = rows.filter((row) => ["visual-report", "saved-analysis"].includes(row.dataset.weeklyDataKind)); const pageRowsLead = !pageRows.length || rows.slice(0, pageRows.length).every((row) => row.dataset.weeklyDataKind === "page-data"); return rows.length > 0 && pageRowsLead && rows.every((row) => row.draggable && row.querySelector('button[aria-label^="隐藏"], button[aria-label^="显示"]')) && protectedRows.every((row) => !row.querySelector('button[aria-label^="删除"]')) && syncedRows.every((row) => row.querySelector('button[aria-label^="删除"]')) && ![...menu.querySelectorAll("span")].some((node) => ["分析模块", "页面数据"].includes(node.textContent.trim())); })()`, "weekly data must use one draggable list, default page data first, expose hide on every row, and delete only synced reports or analyses");
  await cdp.evaluate(`(() => {
    const heading = [...document.querySelectorAll("h4")].find((node) => node.textContent.trim() === "二、重点事项及进展");
    const section = heading?.closest("section");
    const textarea = section?.querySelector("textarea[data-comment-editor-id]");
    if (!textarea) throw new Error("weekly rich editor not found");
    const bytes = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/6nV5WQAAAABJRU5ErkJggg=="), (char) => char.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], "weekly-paste.png", { type: "image/png" }));
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    textarea.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: transfer }));
  })()`);
  await waitForEval(cdp, `(() => { const heading = [...document.querySelectorAll("h4")].find((node) => node.textContent.trim() === "二、重点事项及进展"); const section = heading?.closest("section"); return Boolean(section?.querySelector('[data-rich-image-id]') && section?.querySelector('button[aria-label="拖动右上角同时调整图片宽高"]') && section?.querySelector('button[aria-label="拖动右下角同时调整图片宽高"]')); })()`, 10000);
  await assertEval(cdp, `(() => { const heading = [...document.querySelectorAll("h4")].find((node) => node.textContent.trim() === "二、重点事项及进展"); const section = heading?.closest("section"); return section?.querySelector('[data-rich-image-id] img')?.classList.contains("rounded-[10px]"); })()`, "pasted weekly report images must use light rounded corners");
  await cdp.evaluate(`(() => { const heading = [...document.querySelectorAll("h4")].find((node) => node.textContent.trim() === "二、重点事项及进展"); const section = heading?.closest("section"); const frame = section.querySelector('[data-rich-image-id]'); const handle = section.querySelector('button[aria-label="拖动右下角同时调整图片宽高"]'); const rect = frame.getBoundingClientRect(); window.__weeklyImageBefore = { width: rect.width, height: rect.height }; handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 7, clientX: rect.right, clientY: rect.bottom })); document.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 7, clientX: rect.right + 36, clientY: rect.bottom + 28 })); document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 7 })); })()`);
  await waitForEval(cdp, `(() => { const frame = document.querySelector('[data-rich-image-id]'); const rect = frame?.getBoundingClientRect(); return rect && rect.width > window.__weeklyImageBefore.width + 10 && rect.height > window.__weeklyImageBefore.height + 10; })()`);
  await cdp.evaluate(`(() => { const heading = [...document.querySelectorAll("h4")].find((node) => node.textContent.trim() === "二、重点事项及进展"); heading?.closest("section")?.querySelector('button[aria-label="在图片下方插入空白行"]')?.click(); })()`);
  await waitForEval(cdp, `document.activeElement?.matches('textarea[data-comment-editor-id]') && document.activeElement.value === ""`);

  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await waitForEval(cdp, `document.body.innerText.includes("智能分析") && document.body.innerText.includes("执行记录") && Boolean(document.querySelector('[data-plain-query-input="true"]'))`);
  await cdp.evaluate(`(() => { const input = document.querySelector('[data-plain-query-input="true"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, "查询不存在的未登记指标"); input.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await cdp.evaluate(`new Promise((resolve) => window.setTimeout(resolve, 850))`);
  await assertEval(cdp, `![...document.querySelectorAll('[role="status"]')].some((node) => node.textContent.includes("请明确说明需要分析的具体指标"))`, "metric guidance must wait for an explicit analysis submission");
  await cdp.evaluate(`document.querySelector('button[aria-label="开始分析"]')?.click()`);
  await waitForEval(cdp, `(() => [...document.querySelectorAll('[role="status"]')].some((node) => node.textContent.includes("请明确说明需要分析的具体指标")))()`);
  await waitForEval(cdp, `(() => [...document.querySelectorAll('[role="status"]')].some((node) => node.textContent.includes("请明确说明需要分析的具体指标") && node.classList.contains("animate-pulse")))()`);
  await assertEval(cdp, `(() => {
    const notice = [...document.querySelectorAll('[role="status"]')].find((node) => node.textContent.includes("请明确说明需要分析的具体指标"));
    const input = document.querySelector('[data-plain-query-input="true"]');
    const picker = [...notice?.querySelectorAll("button") || []].find((node) => node.textContent.includes("选择数据表"));
    return Boolean(notice && input && picker
      && Boolean(input.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING)
      && getComputedStyle(picker).color === "rgb(10, 132, 255)");
  })()`, "metric guidance must sit below the input and keep the table-picker action blue");
  await waitForEval(cdp, `(() => { const notice = [...document.querySelectorAll('[role="status"]')].find((node) => node.textContent.includes("请明确说明需要分析的具体指标")); return Boolean(notice && !notice.classList.contains("animate-pulse")); })()`, 5000);
  await cdp.evaluate(`(() => { const input = document.querySelector('[data-plain-query-input="true"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, "继续补充问题"); input.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await assertEval(cdp, `(() => [...document.querySelectorAll('[role="status"]')].some((node) => node.textContent.includes("请明确说明需要分析的具体指标")))()`, "metric guidance must remain visible while the user edits the question");
  await cdp.evaluate(`(() => { const input = document.querySelector('[data-plain-query-input="true"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, ""); input.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析模型"]')?.click()`);
  await waitForEval(cdp, `document.querySelectorAll("[data-model-group]").length === 3`);
  await assertEval(cdp, `[...document.querySelectorAll("[data-model-group]")].map((node) => node.dataset.modelGroup).join("|") === "经营分析中转站A|经营分析中转站B|其他"`, "relay integrations must each form a category and non-relay models must be grouped last under 其他");
  await assertEval(cdp, `[...document.querySelectorAll("[data-model-option]")].map((node) => node.dataset.modelOption).join("|") === "gpt-5.5|deepseek-v4-flash|qwen-plus|claude-sonnet-4"`, "all configured child models must be listed in stable integration order");
  await cdp.evaluate(`document.querySelector('button[data-model-option="qwen-plus"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('button[aria-label="选择分析模型"]')?.innerText.toLowerCase().includes("qwen-plus")`);
  await navigate(cdp, `${appUrl}/weekly-report`);
  await waitForEval(cdp, `document.body.innerText.includes("经营周报")`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await waitForEval(cdp, `document.querySelector('button[aria-label="选择分析模型"]')?.innerText.toLowerCase().includes("qwen-plus")`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await waitForEval(cdp, `document.querySelector('button[aria-label="选择分析模型"]')?.innerText.toLowerCase().includes("qwen-plus")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="添加分析上下文"]')?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("运营日常分析"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("运营日常分析"))?.click()`);
  await cdp.evaluate(`document.querySelector('button[aria-label="添加分析上下文"]')?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("描述性分析"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("描述性分析"))?.click()`);
  await assertEval(cdp, `Boolean(document.querySelector('button[title="场景：运营日常分析"]') && document.querySelector('button[title="主题：描述性分析"]'))`, "one scene and one topic Skill must remain selected together");
  await runRealtimeVoiceSmoke(cdp, appUrl);

  await navigate(cdp, `${appUrl}/`);
  await waitForEval(cdp, `document.body.innerText.includes("多机构分析")`);
  await runFullRouteSmoke(cdp, appUrl);
  await cdp.evaluate(`[...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "经营分析")?.click()`);
  await assertEval(cdp, `!document.querySelector('a[href="/sandbox"],a[href="/funnel"],a[href="/email-daily"]')`, "removed business-analysis menus must not render");
  await cdp.evaluate(`
    document.querySelector('button[aria-expanded]')?.click();
  `);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "广州银行")`);
  await cdp.evaluate(`
    [...document.querySelectorAll("button")]
      .find((button) => button.textContent.trim() === "广州银行")
      ?.click();
  `);
  await waitForEval(cdp, `JSON.parse(localStorage.getItem("${authStorageKey}")).tenant_id === "tenant:广州银行"`);

  await cdp.send("Network.clearBrowserCookies");
  await navigate(cdp, `${appUrl}/`);
  await waitForEval(cdp, `location.pathname === "/login"`);
  await assertEval(cdp, `!document.body.innerText.includes("tenant_demo")`, "expired sessions must not expose tenant ids");
  await assertEval(cdp, `localStorage.getItem(${JSON.stringify(authStorageKey)}) === null`, "expired auth cache should be removed");
  await assertEval(
    cdp,
    `localStorage.getItem(${JSON.stringify(selectedInstitutionStorageKey)}) === null`,
    "expired institution cache should be removed",
  );

  await installSession(cdp, appUrl, "zhaomin@bank.com", "郑州银行");
  await navigate(cdp, `${appUrl}/data-assets/metrics`);
  await waitForEval(cdp, `document.body.innerText.includes("指标字典")`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await waitForEval(cdp, `document.body.innerText.includes("智能分析")`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "自助分析")?.click()`);
  await assertEval(cdp, `!document.querySelector('a[href="/self-analysis/config"]')`, "operator should not see analysis configuration");
  await assertEval(cdp, `!document.body.innerText.includes("用户管理")`, "operator should not see user management");
  await assertEval(cdp, `!document.body.innerText.includes("角色权限")`, "operator should not see role permissions");

  const runtimeFailures = cdp.events.filter((event) =>
    event.method === "Runtime.exceptionThrown"
    || (event.method === "Runtime.consoleAPICalled" && event.params?.type === "error"),
  );
  const serverFailures = cdp.events.filter((event) =>
    event.method === "Network.responseReceived" && Number(event.params?.response?.status || 0) >= 500,
  );
  if (runtimeFailures.length || serverFailures.length) {
    throw new Error(`browser route and interaction smoke emitted runtime or 5xx errors: ${JSON.stringify([...runtimeFailures, ...serverFailures].slice(0, 8))}`);
  }

    await cdp.close();
    console.log("frontend permission smoke passed");
  } finally {
    for (const child of processes.reverse()) {
      await stopChild(child);
    }
    await rmWithRetry(workDir);
  }
}

async function runFullRouteSmoke(cdp, appUrl) {
  const routes = [
    ["/dashboard", "/dashboard", "多机构分析"],
    ["/funnel", "/funnel", "业务漏斗"],
    ["/sandbox", "/sandbox", "经营沙盘"],
    ["/supervision", "/supervision", "机构督导"],
    ["/weekly-report", "/weekly-report", "核心指标表现"],
    ["/email-daily", "/email-daily", "邮件日报"],
    ["/customers", "/customers", "客群分析"],
    ["/single-customer", "/customers", "客群分析"],
    ["/competition", "/competition", "竞品分析"],
    ["/self-analysis", "/self-analysis/query", "智能分析"],
    ["/self-analysis/query", "/self-analysis/query", "智能分析"],
    ["/self-analysis/reports", "/self-analysis/reports", "我的报表"],
    ["/self-analysis/config", "/self-analysis/config", "分析配置"],
    ["/agent", "/agent/tasks", "自动化任务"],
    ["/agent/todos", "/agent/todos", "待办任务"],
    ["/agent/tasks", "/agent/tasks", "自动化任务"],
    ["/agent/message-board", "/agent/message-board", "留言板管理"],
    ["/agent/insights", "/agent/tasks", "自动化任务"],
    ["/agent/abilities", "/agent/tasks", "自动化任务"],
    ["/agent/skills", "/agent/skills", "Skill插件"],
    ["/data-assets", "/data-assets/metrics", "指标字典"],
    ["/data-assets/metrics", "/data-assets/metrics", "指标字典"],
    ["/data-assets/knowledge", "/data-assets/knowledge", "知识记忆"],
    ["/data-assets/behavior", "/data-assets/knowledge", "知识记忆"],
    ["/data-assets/data-management", "/data-assets/data-management", "数据管理"],
    ["/data-assets/quality", "/data-assets/quality", "质量监控"],
    ["/data-assets/tools", "/data-assets/tools", "工具调用"],
    ["/notifications", "/notifications/alerts", "预警规则"],
    ["/notifications/alerts", "/notifications/alerts", "预警规则"],
    ["/notifications/subscriptions", "/notifications/subscriptions", "订阅管理"],
    ["/notifications/history", "/notifications/history", "推送记录"],
    ["/settings", "/settings/users", "用户管理"],
    ["/settings/users", "/settings/users", "用户管理"],
    ["/settings/roles", "/settings/roles", "角色权限"],
    ["/settings/audit", "/settings/audit", "审计日志"],
    ["/settings/config", "/settings/config", "系统配置"],
    ["/bridge-authorize", "/bridge-authorize", "授权链接缺少设备授权码"],
  ];
  for (const [requestedPath, expectedPath, marker] of routes) {
    await navigate(cdp, `${appUrl}${requestedPath}`, 30_000);
    await waitForEval(cdp, `location.pathname === ${JSON.stringify(expectedPath)} && document.body.innerText.includes(${JSON.stringify(marker)})`, 30_000);
    await assertEval(cdp, `!document.body.innerText.includes("页面加载失败") && !document.body.innerText.includes("无法加载页面模块")`, `route ${requestedPath} must render without the error boundary`);
  }
}

async function runRealtimeVoiceSmoke(cdp, appUrl) {
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    (() => {
      window.__voiceSockets = [];
      window.__voiceProcessors = [];
      window.__analysisRuns = 0;
      window.__analysisReleased = new Set();
      window.__analysisFetchLog = [];
      window.__analysisBodies = [];
      const nativeFetch = window.fetch.bind(window);
      window.fetch = async (input, init = {}) => {
        const url = String(typeof input === "string" ? input : input.url);
        window.__analysisFetchLog.push(url);
        const json = (payload) => new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
        if (url.includes("/api/asr/fun-asr/runtime-config")) {
          return json({ available: true, provider: "aliyun_fun_asr", integration: { id: "speech_mock", name: "Fun-ASR", provider: "aliyun_fun_asr", applicationModule: new URL(url, location.origin).searchParams.get("application_module") || "realtime_voice_input", status: "available", testStatus: "connected" }, analysisModels: [
            { id: "model_analysis_mock_a", name: "经营分析中转站A", modelName: "中转站", key: "", value: "", applicationModule: "intelligent_analysis_reasoning", availableModels: ["gpt-5.5", "deepseek-v4-flash"], enabledModels: ["gpt-5.5", "deepseek-v4-flash"], testStatus: "connected", status: "available" },
            { id: "model_analysis_mock_b", name: "经营分析中转站B", modelName: "中转站", key: "", value: "", applicationModule: "intelligent_analysis_reasoning", availableModels: ["qwen-plus"], enabledModels: ["qwen-plus"], testStatus: "connected", status: "available" },
            { id: "model_analysis_official", name: "Claude 官方模型", modelName: "官方网站", key: "", value: "", applicationModule: "intelligent_analysis_reasoning", availableModels: ["claude-sonnet-4"], enabledModels: ["claude-sonnet-4"], testStatus: "connected", status: "available" }
          ] });
        }
        if (url.includes("/api/analysis/run-async")) {
          try { window.__analysisBodies.push(JSON.parse(String(init.body || "{}"))); } catch {}
          const id = ++window.__analysisRuns;
          return json({ tenant_id: "tenant:华兴银行", run: { automation_run_id: "mock_run_" + id, status: "queued" } });
        }
        if (url.includes("/api/analysis/run-status")) {
          const id = Number(new URL(url, location.origin).searchParams.get("run_id").split("_").pop());
          const released = window.__analysisReleased.has(id);
          return json({ tenant_id: "tenant:华兴银行", run: { automation_run_id: "mock_run_" + id, status: released ? "succeeded" : "running", result_refs: released ? [{ type: "task", id: "mock_task_" + id }] : [] } });
        }
        if (url.includes("/api/analysis/task?") && url.includes("task_id=mock_task_")) {
          const id = Number(new URL(url, location.origin).searchParams.get("task_id").split("_").pop());
          return json({ tenant_id: "tenant:华兴银行", task: { task_id: "mock_task_" + id, question: "第" + id + "条语音问题", status: "completed", analysis_plan: { dataset_id: "loan_operation_mart", metrics: ["loan_amount"], dimensions: ["branch_name"] }, skill_results: [{ sql: "select 1", data: [{ branch_name: "测试分行", metric_value: id }], chart_spec: { type: "bar", x: "branch_name", y: "metric_value" }, semantic_info: { execution_mode: "real", publishable: true }, evidence: { evidence_id: "ev_" + id, source_snapshot: { id }, sql_executed: true } }], conclusions: ["第" + id + "条结果"], review: { status: "passed", publication_gate: "allowed" }, intelligent_analysis: { analysis_summary: "第" + id + "条结果", analysis_approach: ["语音队列测试"], metric_scenarios: [], visualization_suggestions: [] } } });
        }
        if (url.includes("/api/analysis/history") && !url.includes("task_id=")) {
          return json({ tenant_id: "tenant:华兴银行", count: 1, tasks: [{ task_id: "history_task_1", question: "这是一条用于验证单行省略、紧凑列表、删除查看详情图标对齐的较长分析问题", status: "completed", created_at: "2026-07-12T09:00:00Z", updated_at: "2026-07-12T09:01:00Z", conclusions: ["历史结果"] }] });
        }
        return nativeFetch(input, init);
      };
      class FakeWebSocket {
        static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
        constructor(url) { this.url = url; this.readyState = 0; window.__voiceSockets.push(this); setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 20); }
        send(data) { if (typeof data !== "string") return; try { const payload = JSON.parse(data); if (payload.type === "start") { this.startPayload = payload; setTimeout(() => { this.onmessage?.({ data: JSON.stringify({ type: "config", provider: "aliyun_fun_asr" }) }); this.onmessage?.({ data: JSON.stringify({ type: "ready" }) }); }, 20); } } catch {} }
        close() { if (this.readyState >= 2) return; this.readyState = 3; setTimeout(() => this.onclose?.({}), 10); }
        emit(text, final = true) { this.onmessage?.({ data: JSON.stringify({ type: "transcript", text, final }) }); }
      }
      Object.defineProperty(window, "WebSocket", { value: FakeWebSocket, configurable: true });
      Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) }, configurable: true });
      class FakeAudioContext {
        constructor() { this.sampleRate = 16000; this.destination = {}; }
        createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
        createScriptProcessor() { const processor = { onaudioprocess: null, connect() {}, disconnect() {} }; window.__voiceProcessors.push(processor); return processor; }
        close() { return Promise.resolve(); }
      }
      Object.defineProperty(window, "AudioContext", { value: FakeAudioContext, configurable: true });
      window.__emitVoice = (text) => window.__voiceSockets.filter((socket) => socket.url.includes("/api/asr/")).at(-1)?.emit(text, true);
      window.__feedVoice = () => { const samples = new Float32Array(4096); for (let i = 0; i < samples.length; i += 1) samples[i] = 0.05 * Math.sin(i / 7); const event = { inputBuffer: { getChannelData: () => samples }, outputBuffer: { getChannelData: () => new Float32Array(4096) } }; for (let i = 0; i < 12; i += 1) window.__voiceProcessors.at(-1)?.onaudioprocess?.(event); };
      window.__releaseAnalysis = (id) => window.__analysisReleased.add(id);
    })();
  ` });
  await navigate(cdp, `${appUrl}/self-analysis/query?shortcut-smoke=1`);
  await waitForEval(cdp, `document.body.innerText.includes("智能分析") && Boolean(document.querySelector('[data-plain-query-input="true"]'))`);
  await selectFirstAnalysisTable(cdp);
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析模型"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[data-model-option="qwen-plus"]'))`);
  await cdp.evaluate(`document.querySelector('button[data-model-option="qwen-plus"]')?.click()`);
  await cdp.evaluate(`(() => { const input = document.querySelector('[data-plain-query-input="true"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, "各分行放款金额排名"); input.dispatchEvent(new Event("input", { bubbles: true })); document.querySelector('button[aria-label="开始分析"]')?.click(); })()`);
  await waitForEval(cdp, `window.__analysisRuns === 1`, 5000);
  await assertEval(cdp, `window.__analysisBodies[0]?.page_context?.model_application_module === "intelligent_analysis_reasoning"`, "text analysis must route through the intelligent-analysis application-module placeholder");
  await assertEval(cdp, `window.__analysisBodies[0]?.page_context?.model_application_selection?.integrationId === "model_analysis_mock_b" && window.__analysisBodies[0]?.page_context?.model_application_selection?.selectedModelName === "qwen-plus"`, "selected dropdown model must be sent as a module-scoped selection");
  await cdp.evaluate(`window.__releaseAnalysis(1)`);
  await waitForEval(cdp, `document.body.innerText.includes("测试分行") && Boolean(document.querySelector('button[aria-label="开始分析"]'))`, 5000);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("执行记录"))?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("查看历史问题、分析结果、思考阶段和执行链路") && Boolean(document.querySelector('button[title="删除执行记录"]'))`);
  await assertEval(cdp, `(() => { const buttons = [...document.querySelectorAll('button[title="删除执行记录"],button[title="查看分析结果"],button[title="展开执行详情"]')]; return buttons.length >= 3 && buttons.every((button) => button.textContent.trim() === ""); })()`, "history delete, view and detail actions must be icon-only");

  await navigate(cdp, `${appUrl}/self-analysis/query?popup-voice-smoke=1`);
  await waitForEval(cdp, `document.body.innerText.includes("智能分析")`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "恢复")?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-plain-query-input="true"]')) && !document.body.innerText.includes("← 返回查询")`);
  await selectFirstAnalysisTable(cdp);
  await cdp.evaluate(`document.querySelector('button[aria-label="语音录入"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('textarea[placeholder*="语音识别文本"]'))`);
  await waitForEval(cdp, `window.__voiceSockets.at(-1)?.startPayload?.applicationModule === "popup_voice_input"`);
  await cdp.evaluate(`(() => { const input = document.querySelector('textarea[placeholder*="语音识别文本"]'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set; setter.call(input, "弹窗语音分析问题"); input.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "开始")?.click()`);
  await waitForEval(cdp, `window.__analysisRuns === 1`, 5000);
  await assertEval(cdp, `window.__analysisBodies[0]?.page_context?.model_application_module === "intelligent_analysis_reasoning"`, "popup transcript analysis must route through the intelligent-analysis LLM module");
  await cdp.evaluate(`window.__releaseAnalysis(1)`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[aria-label="开始分析"]'))`, 5000);

  await navigate(cdp, `${appUrl}/self-analysis/query?voice-smoke=1`);
  await waitForEval(cdp, `document.body.innerText.includes("智能分析")`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "恢复")?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-plain-query-input="true"]')) && !document.body.innerText.includes("← 返回查询")`);
  await selectFirstAnalysisTable(cdp);
  await cdp.evaluate(`(() => { const input = document.querySelector('textarea[placeholder*="用自然语言"]'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set; setter.call(input, ""); input.dispatchEvent(new Event("input", { bubbles: true })); [...document.querySelectorAll("button")].find((button) => button.getAttribute("aria-label") === "实时语音交互")?.click(); })()`);
  await waitForEval(cdp, `document.body.innerText.includes("实时语音持续在线") && window.__voiceProcessors.length > 0`);
  await assertEval(cdp, `window.__voiceSockets.at(-1)?.startPayload?.applicationModule === "realtime_voice_input"`, "realtime voice must resolve the speech integration through its application module");
  await cdp.evaluate(`window.__feedVoice()`);
  await waitForEval(cdp, `document.body.innerText.includes("已锁定首位说话人音色")`);
  await cdp.evaluate(`window.__emitVoice("第一条语音问题")`);
  await waitForEval(cdp, `window.__analysisRuns === 1`, 7000);
  await assertEval(cdp, `window.__analysisBodies[0]?.page_context?.model_application_module === "intelligent_analysis_reasoning"`, "realtime transcript analysis must route through the intelligent-analysis LLM module");
  await cdp.evaluate(`window.__emitVoice("第二条排队问题")`);
  await waitForEval(cdp, `document.body.innerText.includes("已排队 1 条指令")`, 7000);
  const socketsBefore = await cdp.evaluate(`window.__voiceSockets.filter((socket) => socket.url.includes("/api/asr/")).length`);
  await cdp.evaluate(`window.__voiceSockets.filter((socket) => socket.url.includes("/api/asr/")).at(-1).close()`);
  await waitForEval(cdp, `window.__voiceSockets.filter((socket) => socket.url.includes("/api/asr/")).length > ${socketsBefore}`, 5000);
  await assertEval(cdp, `document.body.innerText.includes("实时语音持续在线") && document.body.innerText.includes("已锁定首位说话人音色")`, "realtime voice must reconnect without losing speaker lock");
  await cdp.evaluate(`window.__analysisFetchLog = []; window.__releaseAnalysis(1)`);
  await waitForEval(cdp, `window.__analysisRuns === 2`, 5000);
  await assertEval(cdp, `(() => { const log = window.__analysisFetchLog; const result = log.findIndex((url) => url.includes("task_id=mock_task_1")); const next = log.findIndex((url) => url.includes("/api/analysis/run-async")); return result >= 0 && next > result; })()`, "queued voice command must start only after the previous result is fetched");
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.getAttribute("aria-label") === "停止实时语音交互")?.click()`);
  await waitForEval(cdp, `!document.body.innerText.includes("实时语音持续在线")`);
}

async function selectFirstAnalysisTable(cdp) {
  await cdp.evaluate(`document.querySelector('button[aria-label="添加分析上下文"]')?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll("span")].some((node) => node.textContent.trim() === "数据表" && node.closest("button"))`);
  await cdp.evaluate(`[...document.querySelectorAll("span")].find((node) => node.textContent.trim() === "数据表")?.closest("button")?.click()`);
  await waitForEval(cdp, `document.querySelectorAll('input[type="checkbox"]').length > 0`);
  await cdp.evaluate(`(() => { const checkbox = document.querySelector('input[type="checkbox"]'); checkbox?.click(); [...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "完成")?.click(); })()`);
  await waitForEval(cdp, `![...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "完成")`);
}

async function installSession(cdp, apiUrl, email, institution) {
  const expression = `
    (async () => {
      const response = await fetch(${JSON.stringify(`${apiUrl}/api/auth/login`)}, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: ${JSON.stringify(email)}, password: "123456", institution: ${JSON.stringify(institution)} })
      });
      if (!response.ok) throw new Error(await response.text());
      const session = await response.json();
      session.institution = ${JSON.stringify(institution)};
      session.tenant_id = "tenant:" + ${JSON.stringify(institution)};
      localStorage.setItem(${JSON.stringify(authStorageKey)}, JSON.stringify(session));
      localStorage.setItem(${JSON.stringify(selectedInstitutionStorageKey)}, ${JSON.stringify(institution)});
      return session.user.id;
    })()
  `;
  const userId = await cdp.evaluate(expression, true);
  if (!userId) throw new Error(`failed to install session for ${email}`);
}

async function configureApplicationModel(cdp, apiUrl, applicationModule, name, source = "中转站", models = ["frontend-smoke-model"], id = `model_${applicationModule}`) {
  const result = await cdp.evaluate(`
    (async () => {
      const response = await fetch(${JSON.stringify(`${apiUrl}/api/system-config/model`)}, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: {
          id: ${JSON.stringify(id)},
          name: ${JSON.stringify(name)},
          modelName: ${JSON.stringify(source)},
          key: "http://127.0.0.1:9/v1",
          value: "frontend-smoke-secret",
          availableModels: ${JSON.stringify(models)},
          enabledModels: ${JSON.stringify(models)},
          applicationModule: ${JSON.stringify(applicationModule)},
          testStatus: "connected",
          status: "available"
        } })
      });
      return { ok: response.ok, body: await response.text() };
    })()
  `, true);
  if (!result?.ok) throw new Error(`failed to configure ${applicationModule}: ${result?.body || "unknown"}`);
}

async function configureSpeechIntegration(cdp, apiUrl, applicationModule, id) {
  const result = await cdp.evaluate(`
    (async () => {
      const response = await fetch(${JSON.stringify(`${apiUrl}/api/system-config/speech-integration`)}, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speech_integration: {
          id: ${JSON.stringify(id)}, name: "阿里云 Fun-ASR", provider: "aliyun_fun_asr", source: "阿里云",
          apiBase: "http://127.0.0.1:9/api/v1", apiKey: "frontend-speech-secret",
          applicationModule: ${JSON.stringify(applicationModule)}, testStatus: "connected", status: "available"
        } })
      });
      return { ok: response.ok, body: await response.text() };
    })()
  `, true);
  if (!result?.ok) throw new Error(`failed to configure speech integration: ${result?.body || "unknown"}`);
}

async function navigate(cdp, url, timeoutMs = 10_000) {
  await cdp.send("Page.navigate", { url });
  await waitForEval(cdp, "document.readyState === 'complete' || document.readyState === 'interactive'", timeoutMs);
  await delay(500);
}

async function assertEval(cdp, expression, message) {
  const value = await cdp.evaluate(expression);
  if (!value) throw new Error(message);
}

async function dispatchRealClick(cdp, selector) {
  const point = await cdp.evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return null;
    element.scrollIntoView({ block: "center", inline: "center" });
    const rect = element.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
  if (!point) throw new Error(`cannot click missing selector: ${selector}`);
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...point });
  await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
}

async function dispatchRealDrag(cdp, selector, deltaX, deltaY) {
  const before = await cdp.evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return null;
    element.scrollIntoView({ block: "center", inline: "center" });
    const rect = element.getBoundingClientRect();
    return { left: rect.left, top: rect.top, x: rect.left + 2, y: rect.top + rect.height / 2 };
  })()`);
  if (!before) throw new Error(`cannot drag missing selector: ${selector}`);
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: before.x, y: before.y });
  await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", buttons: 1, clickCount: 1, x: before.x, y: before.y });
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", button: "left", buttons: 1, x: before.x + deltaX, y: before.y + deltaY });
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", buttons: 0, clickCount: 1, x: before.x + deltaX, y: before.y + deltaY });
  await delay(100);
  const moved = await cdp.evaluate(`(() => {
    const rect = document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect();
    return Boolean(rect && Math.abs(rect.left - ${before.left}) >= ${Math.abs(deltaX) - 2} && Math.abs(rect.top - ${before.top}) >= ${Math.abs(deltaY) - 2});
  })()`);
  if (!moved) throw new Error(`drag did not move selector: ${selector}`);
}

async function waitForEval(cdp, expression, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      if (await cdp.evaluate(expression)) return;
    } catch {
      // Retry until the page settles.
    }
    await delay(150);
  }
  const pageState = await cdp.evaluate(`({ path: location.pathname, body: document.body.innerText.slice(0, 600) })`).catch(() => null);
  throw new Error(`timed out waiting for expression: ${expression}; page=${JSON.stringify(pageState)}`);
}

async function openPage(debugPort, url) {
  const response = await fetch(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
  if (!response.ok) throw new Error(`failed to open Chrome target: ${response.status}`);
  return response.json();
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
  }

  open() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
      this.ws.addEventListener("message", (event) => {
        const message = JSON.parse(event.data);
        if (!message.id) {
          this.events.push(message);
          return;
        }
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message));
        else pending.resolve(message.result);
      });
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  async evaluate(expression, awaitPromise = false) {
    let result;
    try {
      result = await this.send("Runtime.evaluate", { expression, awaitPromise, returnByValue: true });
    } catch (error) {
      if (!/Object reference chain is too long/.test(String(error?.message || error))) throw error;
      // Fire-and-forget DOM actions can resolve to a node through optional
      // chaining. The smoke does not consume that value, so avoid serializing
      // the browser's cyclic object graph while preserving all boolean checks.
      await this.send("Runtime.evaluate", { expression, awaitPromise, returnByValue: false });
      return undefined;
    }
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "Runtime.evaluate failed");
    }
    return result.result?.value;
  }

  close() {
    this.ws?.close();
  }
}

async function waitForHttp(url, timeoutMs = 15000, child = null, output = () => "") {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (child && child.exitCode !== null) throw new Error(`process exited before ${url}: ${output()}`);
    try {
      const response = await fetch(url);
      if (response.status < 500) return;
    } catch {
      // Retry.
    }
    await delay(250);
  }
  throw new Error(`timed out waiting for ${url}${output() ? `; process output: ${output()}` : ""}`);
}

function captureChildOutput(child) {
  let output = "";
  const append = (chunk) => { output = `${output}${String(chunk)}`.slice(-8000); };
  child.stdout?.on("data", append);
  child.stderr?.on("data", append);
  return () => output;
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    delay(5000),
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
    server.on("error", reject);
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function rmWithRetry(path) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      await rm(path, { recursive: true, force: true });
      return;
    } catch (error) {
      if (attempt === 4) throw error;
      await delay(300);
    }
  }
}

await main();
