import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import net from "node:net";

const root = process.cwd();
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const authStorageKey = "smart_data_agent_auth_session_v1";
const selectedInstitutionStorageKey = "smart_data_agent_selected_institution_v1";
const testDevelopmentLoginPassword = "123456";

async function main() {
  const apiPort = await freePort();
  const vitePort = await freePort();
  const debugPort = await freePort();
  const workDir = await mkdtemp(join(tmpdir(), "sda-frontend-permissions-"));
  const apiUrl = `http://127.0.0.1:${apiPort}`;
  const appUrl = `http://127.0.0.1:${vitePort}`;
  const customerListPath = join(workDir, "customer-list.xlsx");
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
  await createCustomerListWorkbook(customerListPath);
  const api = spawn(
    "uv",
    ["run", "python", "-m", "backend.platform.api.server", "--host", "127.0.0.1", "--port", String(apiPort), "--test-sqlite-db", join(workDir, "api.sqlite")],
    {
      cwd: root,
      env: {
        ...process.env,
        SMART_DATA_AGENT_DATABASE_URL: "",
        SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD: testDevelopmentLoginPassword,
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
  if (process.env.SDA_SMOKE_SHELL_EDGE_ONLY === "true") {
    await verifyShellEdgeSpacing(cdp);
    console.log("全局工作区顶部和右侧 0.4cm 边距、滚动条贴齐且桌面与窄屏无溢出的浏览器验收通过");
    return;
  }
  if (process.env.SDA_SMOKE_MENU_ROUTE_PERFORMANCE_ONLY === "true") {
    await verifyMenuRoutePerformance(cdp, appUrl);
    console.log("菜单冷路由保持当前页面、无顶部骨架闪现且无横向溢出的浏览器验收通过");
    return;
  }
  if (process.env.SDA_SMOKE_DASHBOARD_PERFORMANCE_ONLY === "true") {
    await delay(1_000);
    await cdp.evaluate(`performance.clearResourceTimings(); window.__dashboardNavigationStartedAt = performance.now()`);
    await cdp.evaluate(`document.querySelector('nav a[href="/dashboard"]')?.click()`);
    await waitForEval(cdp, `location.pathname === "/dashboard" && document.body.innerText.includes("多机构分析") && !document.body.innerText.includes("正在读取多机构页面数据")`);
    const dashboardPerformance = await cdp.evaluate(`(() => ({
      elapsedMs: performance.now() - window.__dashboardNavigationStartedAt,
      workspaceRequests: performance.getEntriesByType("resource").filter((entry) => entry.name.includes("/api/data-assets/page-data/workspace?page_code=dashboard")).length,
    }))()`);
    if (dashboardPerformance.elapsedMs > 500) throw new Error(`warm dashboard must become usable within 500ms: ${JSON.stringify(dashboardPerformance)}`);
    if (dashboardPerformance.workspaceRequests > 1) throw new Error(`dashboard navigation must reuse one prepared workspace read: ${JSON.stringify(dashboardPerformance)}`);
    console.log(JSON.stringify({ dashboardPerformance }));
    return;
  }
  await cdp.evaluate(`[...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "经营分析")?.click()`);
  await assertEval(cdp, `(() => { const group = [...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "经营分析")?.parentElement; return [...(group?.querySelectorAll("a") || [])].map((link) => link.getAttribute("href")).join("|") === "/weekly-report|/supervision|/customer-segment-analysis"; })()`, "business analysis must place customer-segment analysis after institution supervision");
  await navigate(cdp, `${appUrl}/data-assets/data-management`);
  await waitForEval(cdp, `document.body.innerText.includes("站内数据") && [...document.querySelectorAll("button")].some((button) => button.textContent.trim().startsWith("分客群页面"))`);
  await assertEval(cdp, `!document.body.innerText.includes("已连接后端资产配置")`, "data management must not render the successful backend connection status module");
  await assertEval(cdp, `(() => { const labels = [...document.querySelectorAll("button")].map((button) => button.textContent.trim()); return labels.findIndex((label) => label.startsWith("单机构页面")) < labels.findIndex((label) => label.startsWith("表关系")) && labels.findIndex((label) => label.startsWith("表关系")) < labels.findIndex((label) => label.startsWith("多机构页面")) && labels.findIndex((label) => label.startsWith("多机构页面")) < labels.findIndex((label) => label.startsWith("分客群页面")); })()`, "data management must place relationships between single/multi institution and customer segment after multi institution");
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim().startsWith("分客群页面"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[data-page-data-add="customer_segment"]'))`);
  await cdp.evaluate(`document.querySelector('button[data-page-data-add="customer_segment"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-page-data-modal="true"]')) && document.body.innerText.includes("新增分客群明细数据")`);
  await assertEval(cdp, `document.querySelectorAll('[data-page-data-modal="true"] select option').length >= 1 && [...document.querySelectorAll('[data-page-data-modal="true"] select option')].every((option, index) => index > 0 || option.value === "")`, "customer-segment data modal must expose only its server-filtered customer-detail source catalog");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭分客群明细数据弹窗"]')?.click()`);
  await navigate(cdp, `${appUrl}/customer-segment-analysis`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-upload-customer-segment-list="true"]')) && document.body.innerText.includes("请先上传 Excel 客户号名单")`);
  await cdp.evaluate(`document.querySelector('[data-upload-customer-segment-list="true"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-customer-segment-upload-overlay="true"] input[type="file"]'))`);
  await setFileInput(cdp, '[data-customer-segment-upload-overlay="true"] input[type="file"]', customerListPath);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-customer-segment-preview="true"]')) && document.body.innerText.includes("2") && document.body.innerText.includes("已过滤重复 1 个") && document.body.innerText.includes("其他列未读取")`);
  await cdp.evaluate(`document.querySelector('[data-customer-segment-confirm="true"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-customer-segment-current-list="true"]')) && document.body.innerText.includes("当前名单 · 2 个客户号")`);
  await navigate(cdp, `${appUrl}/customer-segment-analysis`);
  await waitForEval(cdp, `document.body.innerText.includes("当前名单 · 2 个客户号") && document.body.innerText.includes("暂无分客群明细数据")`);
  await navigate(cdp, `${appUrl}/customers`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-customer-insight-page="true"] [data-default-report-page-template="institution-supervision"]'))`);
  await assertEval(cdp, `!document.body.innerText.includes("全部分行") && !document.body.innerText.includes("当前数据模式") && !document.body.innerText.includes("消费贷客群") && !document.body.innerText.includes("经营贷客群") && !document.querySelector('[data-customer-product-switch="true"]')`, "customer insight must use the default report page without branch, data-mode or product-segment controls");
  await assertEval(cdp, `Boolean(document.querySelector('[data-customer-insight-page="true"] [data-sticky-note-toggle="true"]')) && Boolean(document.querySelector('[data-customer-insight-page="true"] [data-page-data-mode-toggle="true"]'))`, "customer insight must preserve the institution-supervision note and edit actions");
  await navigate(cdp, `${appUrl}/competition`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-competition-page="true"] [data-default-report-page-template="institution-supervision"]')) && Boolean(document.querySelector('[data-competition-product-switch="true"]'))`);
  await assertEval(cdp, `!document.body.innerText.includes("当前租户暂无已授权、带证据的市场观测；页面不会使用内置竞品数字补位。")`, "competition analysis must remove the tenant market-observation disclaimer");
  await navigate(cdp, `${appUrl}/self-analysis/visual-reports`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-new-visual-report="true"]'))`);
  await cdp.evaluate(`document.querySelector('[data-new-visual-report="true"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-visual-report-builder="true"][data-default-report-page-template="institution-supervision"]'))`);
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
  await configureApplicationModel(
    cdp,
    appUrl,
    "global_text_model",
    "通用分析中转站",
    "中转站",
    ["360/deepseek-v4-flash", "360/deepseek-v4-pro", "deepbank/glm-5.2", "glm-5.2-codex", "gpt-5.5", ...Array.from({ length: 40 }, (_, index) => `perf-model-${String(index + 1).padStart(2, "0")}`)],
    "model_global_analysis_relay",
    ["gpt-5.5"],
  );
  await configureSpeechIntegration(cdp, appUrl, "realtime_voice_input", "speech_frontend_realtime");
  await configureSpeechIntegration(cdp, appUrl, "popup_voice_input", "speech_frontend_popup");
  if (process.env.SDA_SMOKE_MESSAGE_BOARD_ONLY === "true") {
    await verifyGlobalMessageBoardShortcut(cdp, appUrl);
    console.log("全局留言板入口、页面草稿、图片、语音、失败保留及管理员回显浏览器验收通过");
    return;
  }
  if (process.env.SDA_SMOKE_MODEL_PERFORMANCE_ONLY === "true") {
    await verifyModelSelectionPerformance(cdp, appUrl);
    console.log("模型选择滚动稳定、无冗余全量回读、重开后选中项置顶的浏览器验收通过");
    return;
  }
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
      body: JSON.stringify({ email: "zhaomin@bank.com", password: ${JSON.stringify(testDevelopmentLoginPassword)}, institution: "郑州银行" })
    }).then((response) => {
      if (!response.ok) throw new Error("failed to switch the shared cookie session");
      window.dispatchEvent(new Event("focus"));
    })
  `, true);
  await waitForEval(cdp, `JSON.parse(localStorage.getItem(${JSON.stringify(authStorageKey)}))?.user?.id === "u_zhaomin"`);
  await waitForEval(cdp, `location.pathname === "/settings/config" && document.body.innerText.includes("审计日志") && document.body.innerText.includes("系统配置")`);
  const limitedConfigProbe = await cdp.evaluate(`fetch("/api/system-config", { credentials: "include", headers: { "X-Tenant-Id": encodeURIComponent("tenant:郑州银行") } }).then(async (response) => ({ status: response.status, body: await response.json() }))`, true);
  if (
    limitedConfigProbe?.status !== 200
    || limitedConfigProbe?.body?.config_owner_user_id !== "u_zhaomin"
    || limitedConfigProbe?.body?.can_read_system_params !== false
    || (limitedConfigProbe?.body?.system_params || []).length !== 0
  ) {
    throw new Error(`limited user system config scope is unsafe: ${JSON.stringify(limitedConfigProbe)}`);
  }
  await assertEval(
    cdp,
    `Boolean(location.pathname === "/settings/config" && document.querySelector('[data-settings-upper-module="model-access"]') && document.querySelector('[data-settings-route-body="config"]'))`,
    "a limited user must keep account-owned model access without gaining tenant system-parameter access",
  );
  await installSession(cdp, appUrl, "xujingbo-jk@qifu.com", "华兴银行");
  await navigate(cdp, `${appUrl}/settings/roles`);
  await waitForEval(cdp, `document.body.innerText.includes("角色权限")`);

  await navigate(cdp, `${appUrl}/agent/skills`);
  await waitForEval(cdp, `document.body.innerText.includes("skill/插件") && [...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增场景")) && [...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "主题")`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增场景"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增场景"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label*="新增场景"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label*="新增场景"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new scene must open as a centered system modal");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭场景弹窗"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "主题")?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("skill/插件") && [...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "场景")`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增主题"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增主题"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label*="新增主题"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label*="新增主题"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new topic must open as a centered system modal");
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label*="新增主题"]'); return dialog && !dialog.innerText.includes("格式要求") && dialog.innerText.includes("主题 Skill 不设置固定格式"); })()`, "topic Skill must not expose a fixed output-format field and must explain adaptive visualization");
  await assertEval(cdp, `(() => { const runtime = document.querySelector('[data-skill-runtime-enabled="new"]'); const visible = document.querySelector('[data-skill-intelligent-analysis-visible="new"]'); const runtimeRect = runtime?.closest("label")?.getBoundingClientRect(); const visibleRect = visible?.closest("label")?.getBoundingClientRect(); return Boolean(runtime?.checked && visible?.checked && runtimeRect && visibleRect && visibleRect.left > runtimeRect.left && Math.abs(visibleRect.top - runtimeRect.top) < 4); })()`, "new Skill display checkbox must default checked and sit to the right of runtime enablement");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭主题弹窗"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[aria-label="编辑描述性分析"]'))`);
  await assertEval(cdp, `document.body.innerText.includes("展示") && !document.body.innerText.includes("显示位置") && !document.querySelector('[data-skill-display-location]')`, "Skill rows must expose a read-only display status column without restoring the old select");
  await assertEval(cdp, `document.querySelector('[data-skill-display-status="topic-descriptive"]')?.textContent.trim() === "展示"`, "visible topic Skill must show 展示 in the list");
  await assertEval(cdp, `!document.body.innerText.includes("华兴银行描述性分析") && !document.body.innerText.includes("华兴银行归因分析") && !document.body.innerText.includes("华兴银行预测分析")`, "institution-named copies of the three canonical topic Skills must not remain");
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑描述性分析"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-skill-intelligent-analysis-visible="topic-descriptive"]'))`);
  await assertEval(cdp, `document.querySelector('[data-skill-intelligent-analysis-visible="topic-descriptive"]')?.checked === true`, "visible topic Skill must open with its display checkbox checked");
  await cdp.evaluate(`document.querySelector('[data-skill-intelligent-analysis-visible="topic-descriptive"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll('[role="dialog"] button')].find((button) => button.textContent.trim() === "保存")?.click()`);
  await waitForEval(cdp, `!document.querySelector('[role="dialog"]')`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await cdp.evaluate(`document.querySelector('button[aria-label="添加分析上下文"]')?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.trim().startsWith("智能分析主查询"))`);
  await assertEval(cdp, `![...document.querySelectorAll("button")].some((button) => button.textContent.trim().startsWith("描述性分析"))`, "hidden topic Skill must leave the 智能分析 + menu without disabling scene Skills");
  await navigate(cdp, `${appUrl}/self-analysis/config`);
  await waitForEval(cdp, `document.body.innerText.includes("分析配置") && [...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增分析配置"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增分析配置"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label="新增分析配置"]'))`);
  await assertEval(cdp, `!document.querySelector('[role="dialog"][aria-label="新增分析配置"]')?.innerText.includes("描述性分析")`, "hidden topic Skill must also stay out of the analysis-configuration dialog");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭编辑分析配置"]')?.click()`);
  await navigate(cdp, `${appUrl}/agent/skills`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "主题")?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[aria-label="编辑描述性分析"]'))`);
  await assertEval(cdp, `document.querySelector('[data-skill-display-status="topic-descriptive"]')?.textContent.trim() === "不展示"`, "unchecked topic Skill must show 不展示 after save readback");
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑描述性分析"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('[data-skill-intelligent-analysis-visible="topic-descriptive"]')?.checked === false`);
  await cdp.evaluate(`document.querySelector('[data-skill-intelligent-analysis-visible="topic-descriptive"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll('[role="dialog"] button')].find((button) => button.textContent.trim() === "保存")?.click()`);
  await waitForEval(cdp, `!document.querySelector('[role="dialog"]')`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "场景")?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[aria-label="编辑智能分析主查询"]'))`);
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑智能分析主查询"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('[data-skill-intelligent-analysis-visible="scene-self-analysis"]')?.checked === true`);
  await cdp.evaluate(`document.querySelector('[data-skill-intelligent-analysis-visible="scene-self-analysis"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll('[role="dialog"] button')].find((button) => button.textContent.trim() === "保存")?.click()`);
  await waitForEval(cdp, `!document.querySelector('[role="dialog"]')`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await cdp.evaluate(`document.querySelector('button[aria-label="添加分析上下文"]')?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.trim().startsWith("描述性分析"))`);
  await assertEval(cdp, `![...document.querySelectorAll("button")].some((button) => button.textContent.trim().startsWith("智能分析主查询"))`, "hidden scene Skill must leave the 智能分析 + menu without disabling topic Skills");
  await navigate(cdp, `${appUrl}/agent/skills`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[aria-label="编辑智能分析主查询"]'))`);
  await assertEval(cdp, `document.querySelector('[data-skill-display-status="scene-self-analysis"]')?.textContent.trim() === "不展示"`, "unchecked scene Skill must show 不展示 after save readback");
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑智能分析主查询"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('[data-skill-intelligent-analysis-visible="scene-self-analysis"]')?.checked === false`);
  await cdp.evaluate(`document.querySelector('[data-skill-intelligent-analysis-visible="scene-self-analysis"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll('[role="dialog"] button')].find((button) => button.textContent.trim() === "保存")?.click()`);
  await waitForEval(cdp, `!document.querySelector('[role="dialog"]')`);

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
  await assertEval(cdp, `(() => { const text = document.body.innerText; return text.includes("当前机构 Data Crawler 已下载的 CSV") && !text.includes("Origin_Data") && !text.includes("/app/data/"); })()`, "data management must describe the selected-institution Data Crawler delivery boundary without exposing retired or internal filesystem paths");

  await navigate(cdp, `${appUrl}/agent/tasks`);
  await waitForEval(cdp, `document.body.innerText.includes("自动化任务") && [...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增自动化任务"))`);
  await assertEval(cdp, `!document.body.innerText.includes("任务触发洞察")`, "task-triggered insight submodule must be removed");
  await assertEval(cdp, `(() => {
    const row = document.querySelector("[data-agent-task-card]");
    if (!row) return true;
    const labels = [...row.querySelectorAll("button")].map((button) => button.getAttribute("aria-label") || "");
    const compact = row.getBoundingClientRect().height <= 88;
    return compact && labels.some((label) => label.includes("查看任务")) && labels.some((label) => label.includes("编辑任务") || label.includes("不可编辑")) && labels.some((label) => label.includes("删除任务") || label.includes("不可删除"));
  })()`, "automation task rows must be compact list bars with view/edit/delete actions");
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
  await waitForEval(cdp, `document.body.innerText.includes("工具调用") && [...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增工具"))`);
  await assertEval(cdp, `(() => { const text = document.body.innerText; return ["Confluence知识检索","Outlook邮箱调用","Teams-云文档工具","Teams-T5T工具","财务分析师"].every((name) => text.includes(name)) && !text.includes("华兴银行经营沙盘数据获取"); })()`, "an operating institution must receive the governed platform tool catalog without inheriting another institution's tool entries");
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增工具"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增工具"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label="新增工具"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label="新增工具"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new tool must open as a centered system modal");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭工具弹窗"]')?.click()`);

  await navigate(cdp, `${appUrl}/agent/skills`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "主题")`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "主题")?.click()`);
  await waitForEval(cdp, `["描述性分析","归因分析","预测分析"].every((name) => document.body.innerText.includes(name))`);
  await assertEval(cdp, `!["华兴银行","广州银行","兰州银行","汉口银行","石嘴山银行","郑州银行","临商银行","瑞丰银行","南京银行","三峡银行","兴业消金"].some((institution) => ["描述性分析","归因分析","预测分析"].some((method) => document.body.innerText.includes(institution + method)))`, "institution context must live in Memory instead of duplicate topic Skills");

  await navigate(cdp, `${appUrl}/self-analysis/config`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增分析配置"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增分析配置"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label="新增分析配置"]'))`);
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label="新增分析配置"]'); const rect = dialog.getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20 && Boolean(dialog.querySelector('summary[aria-label="选择分析记忆"]')) && dialog.innerText.includes("只保存记忆 ID") && !dialog.innerText.includes("华兴银行描述性分析") && Boolean(dialog.querySelector('button[aria-label="关闭编辑分析配置"]')); })()`, "analysis configuration must use the centered modal and exclude institution Skills before review approval");
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
  await cdp.evaluate(`document.querySelector('[data-model-edit-row="model_global_analysis_relay"]')?.click()`);
  await waitForEval(cdp, `document.querySelectorAll('[data-model-option]').length >= 40`);
  await cdp.evaluate(`performance.clearResourceTimings()`);
  await cdp.evaluate(`(() => {
    const scroll = document.querySelector('[data-model-integrations-scroll="true"]');
    const labels = [...document.querySelectorAll('[data-model-option]')];
    scroll.scrollTop = Math.max(0, scroll.scrollHeight - scroll.clientHeight - 80);
    window.__modelOptionBefore = {
      order: labels.map((label) => label.getAttribute('data-model-option')),
      scrollTop: scroll.scrollTop,
      target: labels.find((label) => label.getAttribute('data-model-option') === 'perf-model-40')?.getAttribute('data-model-option'),
    };
    labels.find((label) => label.getAttribute('data-model-option') === 'perf-model-40')?.querySelector('input')?.click();
  })()`);
  await waitForEval(cdp, `document.querySelector('[data-model-option="perf-model-40"]')?.getAttribute('data-model-option-selected') === "true" && document.querySelector('[role="status"]')?.textContent.includes("模型接入已更新")`);
  await assertEval(cdp, `(() => {
    const scroll = document.querySelector('[data-model-integrations-scroll="true"]');
    const order = [...document.querySelectorAll('[data-model-option]')].map((label) => label.getAttribute('data-model-option'));
    const base = window.__modelOptionBefore;
    const configReads = performance.getEntriesByType('resource').filter((entry) => new URL(entry.name).pathname === '/api/system-config').length;
    return base?.target === 'perf-model-40' && JSON.stringify(order) === JSON.stringify(base.order) && Math.abs(scroll.scrollTop - base.scrollTop) <= 2 && configReads === 0;
  })()`, "model checkbox save must keep option order and scroll position without a redundant full configuration read");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭弹窗"]')?.click()`);
  await waitForEval(cdp, `!document.body.innerText.includes("模型接入管理")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑模型接入"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("模型接入管理")`);
  await cdp.evaluate(`document.querySelector('[data-model-edit-row="model_global_analysis_relay"]')?.click()`);
  await waitForEval(cdp, `document.querySelectorAll('[data-model-option]').length >= 40`);
  await assertEval(cdp, `(() => {
    const selectedStates = [...document.querySelectorAll('[data-model-option]')].map((label) => label.getAttribute('data-model-option-selected') === 'true');
    const firstUnselected = selectedStates.indexOf(false);
    return firstUnselected === -1 || !selectedStates.slice(firstUnselected).includes(true);
  })()`, "reopening model access must place all selected child models before unselected child models");
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "语音转文字")?.click()`);
  await waitForEval(cdp, `["新增语音转文字接入","更新系统语音接入"].some((label) => document.body.innerText.includes(label))`);
  await assertEval(cdp, `!document.body.innerText.includes("须含 .aliyuncs.com") && !document.body.innerText.includes("此配置用于系统内全部语音应用")`, "speech access modal must omit the removed endpoint and shared-usage explanations");
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
  await waitForEval(cdp, `document.body.innerText.includes("经营周报") && !document.body.innerText.includes("核心指标表现")`);
  await waitForEval(cdp, `document.querySelector('[data-report-meta-key="reporters"] input')?.value === "胥京波"`);
  await assertEval(cdp, `document.querySelector('[data-report-meta-key="reporters"] input')?.value === "胥京波"`, "weekly report reporter must default to the authenticated user's display name");
  await waitForEval(cdp, `(() => { const tabs = [...document.querySelectorAll("button")].filter((button) => ["可视化分析","分析结论"].includes(button.textContent.trim())); const ready = tabs[0]?.textContent.trim() === "可视化分析" && tabs[1]?.textContent.trim() === "分析结论" && !document.body.innerText.includes("待载入"); const explicitEmpty = document.body.innerText.includes("当前未显示周报数据，可通过右上角“周报数据”按钮重新启用。"); return ready || explicitEmpty; })()`);
  const weeklyVisualCard = await cdp.evaluate(`Boolean(document.querySelector('[data-visual-card]'))`);
  if (weeklyVisualCard) {
    await cdp.evaluate(`(() => { const card = document.querySelector('[data-visual-card]'); const rect = card.getBoundingClientRect(); card.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, clientX: rect.left + Math.min(80, rect.width / 2), clientY: rect.top + Math.min(120, rect.height / 2) })); })()`);
    await waitForEval(cdp, `Boolean(document.querySelector('[data-visual-comment-action="true"]'))`);
    await cdp.evaluate(`document.querySelector('[data-visual-comment-action="true"]')?.click()`);
    await waitForEval(cdp, `Boolean(document.querySelector('aside[data-context-page="weekly-report"][data-context-rail="expanded"]'))`);
    await assertEval(cdp, `Boolean(document.querySelector('aside[data-context-page="weekly-report"] button[aria-label*="评论"], aside[data-context-page="weekly-report"] [data-comments-panel]')) || document.body.innerText.includes("新增评论")`, "visual comment bubble must open the weekly report comments rail");
    await cdp.evaluate(`document.querySelector('aside[data-context-page="weekly-report"] [data-context-rail-collapse="true"]')?.click()`);
  }
  const weeklyDimensionHeader = await cdp.evaluate(`Boolean(document.querySelector('th[data-visual-table-dimension-header]'))`);
  if (weeklyDimensionHeader) {
    await cdp.evaluate(`(() => { const header = document.querySelector('th[data-visual-table-dimension-header]'); const field = header.dataset.visualTableDimensionHeader; const table = header.closest("table"); const index = [...header.parentElement.children].indexOf(header); const values = [...table.querySelectorAll("tbody tr")].map((row) => row.children[index]?.textContent.trim()).filter(Boolean); window.__weeklyMergeExpected = new Set(values).size < values.length; const rect = header.getBoundingClientRect(); header.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: rect.left + 12, clientY: rect.bottom - 4 })); window.__weeklyMergeField = field; })()`);
    await waitForEval(cdp, `Boolean(document.querySelector('[data-visual-table-header-menu] [data-visual-merge-dimension]'))`);
    await assertEval(cdp, `document.querySelector('[data-visual-table-header-menu]')?.querySelector('[data-visual-table-header-comment="true"]') && document.querySelector('[data-visual-table-header-menu]')?.textContent.includes("合并重复单元格")`, "dimension header menu must provide both comment and merge actions");
    await cdp.evaluate(`document.querySelector('[data-visual-table-header-menu] [data-visual-merge-dimension]')?.click()`);
    await waitForEval(cdp, `!document.querySelector('[data-visual-table-header-menu]')`);
    await assertEval(cdp, `!window.__weeklyMergeExpected || Boolean(document.querySelector('td[data-table-merged-dimension][rowspan]'))`, "duplicate dimension values must render as row-spanning cells when present");
    await cdp.evaluate(`(() => { const field = window.__weeklyMergeField; const header = document.querySelector('th[data-visual-table-dimension-header="' + CSS.escape(field) + '"]'); const rect = header.getBoundingClientRect(); header.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: rect.left + 12, clientY: rect.bottom - 4 })); })()`);
    await waitForEval(cdp, `document.querySelector('[data-visual-table-header-menu] [data-visual-merge-dimension]')?.getAttribute("aria-pressed") === "true"`);
    await cdp.evaluate(`document.querySelector('[data-visual-table-header-menu] [data-visual-merge-dimension]')?.click()`);
  }
  const weeklyCommentTarget = await cdp.evaluate(`Boolean(document.querySelector('[data-comment-target]'))`);
  if (weeklyCommentTarget) {
    await cdp.evaluate(`document.querySelector('[data-comment-target]')?.click()`);
    await waitForEval(cdp, `Boolean(document.querySelector('[data-comment-selection-action="true"]'))`);
    await dispatchRealDrag(cdp, '[data-weekly-selection-action="true"]', 28, 14);
    await dispatchRealClick(cdp, '[data-comment-selection-action="true"]');
    await waitForEval(cdp, `Boolean(document.querySelector('aside[data-context-page="weekly-report"][data-context-rail="expanded"] [data-draft-id] textarea'))`);
    await cdp.evaluate(`document.querySelector('aside[data-context-page="weekly-report"] [data-context-rail-collapse="true"]')?.click()`);
    await waitForEval(cdp, `document.querySelector('aside[data-context-page="weekly-report"]')?.dataset.contextRail === "collapsed"`);
    await cdp.evaluate(`document.querySelector('[data-comment-target]')?.click()`);
    await waitForEval(cdp, `Boolean(document.querySelector('[data-analysis-selection-action="true"]'))`);
    await dispatchRealClick(cdp, '[data-analysis-selection-action="true"]');
    await waitForEval(cdp, `Boolean(document.querySelector('aside[data-context-page="weekly-report"][data-context-rail="expanded"] [data-analysis-workspace-panel="true"]'))`);
    await cdp.evaluate(`document.querySelector('aside[data-context-page="weekly-report"] [data-context-rail-collapse="true"]')?.click()`);
  }
  if (process.env.SDA_SMOKE_STOP_AFTER_WEEKLY_FLOATING_ACTIONS === "true") return;
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析数据模块"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("拖动排序 · 点击显隐") && Boolean(document.querySelector('[data-weekly-unified-data-menu="true"]'))`);
  await assertEval(cdp, `(() => { const menu = document.querySelector('[data-weekly-unified-data-menu="true"]'); const rows = [...(menu?.querySelectorAll('[data-weekly-data-item]') || [])]; return rows.every((row) => row.draggable && !row.querySelector('button[aria-label^="隐藏"], button[aria-label^="显示"]')?.disabled && !row.querySelector('button[aria-label^="删除"]')); })()`, "weekly data browse mode must allow reorder and visibility while hiding delete");
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析数据模块"]')?.click()`);
  await cdp.evaluate(`document.querySelector('button[data-weekly-page-data-mode-toggle="true"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('button[data-weekly-page-data-mode-toggle="true"]')?.textContent.includes("保存")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析数据模块"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("拖动排序 · 点击显隐") && document.body.innerText.includes("周报数据") && Boolean(document.querySelector('[data-weekly-unified-data-menu="true"]'))`);
  await assertEval(cdp, `(() => { const menu = document.querySelector('[data-weekly-unified-data-menu="true"]'); const rows = [...(menu?.querySelectorAll('[data-weekly-data-item]') || [])]; const pageRows = rows.filter((row) => row.dataset.weeklyDataKind === "page-data"); const pageRowsLead = !pageRows.length || rows.slice(0, pageRows.length).every((row) => row.dataset.weeklyDataKind === "page-data"); return pageRowsLead && !rows.some((row) => row.dataset.weeklyDataKind === "core") && rows.every((row) => row.draggable && row.querySelector('button[aria-label^="隐藏"], button[aria-label^="显示"]') && row.querySelector('button[aria-label^="删除"]')) && ![...menu.querySelectorAll("span")].some((node) => ["分析模块", "页面数据", "核心指标表现"].includes(node.textContent.trim())); })()`, "weekly data edit mode must retain reorder, visibility and permission-scoped delete for the super administrator");
  await cdp.evaluate(`(() => { const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((node) => node.textContent.trim() === "二、重点事项及进展"); const editor = heading?.closest("section")?.querySelector('[role="textbox"][data-comment-editor-id]'); if (!editor) throw new Error("weekly static editor not found"); editor.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true })); })()`);
  await waitForEval(cdp, `(() => { const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((node) => node.textContent.trim() === "二、重点事项及进展"); return Boolean(heading?.closest("section")?.querySelector('[contenteditable="true"][data-comment-editor-id]')); })()`);
  await cdp.evaluate(`(() => {
    const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((node) => node.textContent.trim() === "二、重点事项及进展");
    const section = heading?.closest("section");
    const textarea = section?.querySelector('[contenteditable="true"][data-comment-editor-id]');
    if (!textarea) throw new Error("weekly rich editor not found");
    const bytes = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/6nV5WQAAAABJRU5ErkJggg=="), (char) => char.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], "weekly-paste.png", { type: "image/png" }));
    textarea.focus();
    const range = document.createRange();
    range.selectNodeContents(textarea);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    textarea.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: transfer }));
  })()`);
  await waitForEval(cdp, `(() => { const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((node) => node.textContent.trim() === "二、重点事项及进展"); const section = heading?.closest("section"); return Boolean(section?.querySelector('[data-rich-image-id]') && section?.querySelector('button[aria-label="拖动右上角同时调整图片宽高"]') && section?.querySelector('button[aria-label="拖动右下角同时调整图片宽高"]')); })()`, 10000);
  await assertEval(cdp, `(() => { const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((node) => node.textContent.trim() === "二、重点事项及进展"); const section = heading?.closest("section"); return section?.querySelector('[data-rich-image-id] img')?.classList.contains("rounded-[10px]"); })()`, "pasted weekly report images must use light rounded corners");
  await cdp.evaluate(`(() => { const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((node) => node.textContent.trim() === "二、重点事项及进展"); const section = heading?.closest("section"); const frame = section.querySelector('[data-rich-image-id]'); const handle = section.querySelector('button[aria-label="拖动右下角同时调整图片宽高"]'); const rect = frame.getBoundingClientRect(); window.__weeklyImageBefore = { width: rect.width, height: rect.height }; handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 7, clientX: rect.right, clientY: rect.bottom })); document.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 7, clientX: rect.right + 36, clientY: rect.bottom + 28 })); document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 7 })); })()`);
  await waitForEval(cdp, `(() => { const frame = document.querySelector('[data-rich-image-id]'); const rect = frame?.getBoundingClientRect(); return rect && rect.width > window.__weeklyImageBefore.width + 10 && rect.height > window.__weeklyImageBefore.height + 10; })()`);
  await cdp.evaluate(`(() => { const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((node) => node.textContent.trim() === "二、重点事项及进展"); heading?.closest("section")?.querySelector('button[aria-label="在图片下方插入空白行"]')?.click(); })()`);

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
  await waitForEval(cdp, `document.querySelectorAll("[data-model-group]").length === 4`);
  await assertEval(cdp, `[...document.querySelectorAll("[data-model-group]")].map((node) => node.dataset.modelGroup).join("|") === "经营分析中转站A|经营分析中转站B|通用分析中转站|其他"`, "user-configured relay integrations must each form a category and non-relay models must be grouped last under 其他");
  await assertEval(cdp, `(() => { const enabled = ["gpt-5.5","deepseek-v4-flash","qwen-plus","claude-sonnet-4","perf-model-40"]; const disabled = ["360/deepseek-v4-flash","360/deepseek-v4-pro","deepbank/glm-5.2","glm-5.2-codex"]; return enabled.every((id) => Boolean(document.querySelector('button[data-model-option="' + id + '"]'))) && disabled.every((id) => !document.querySelector('button[data-model-option="' + id + '"]')); })()`, "only enabled child models must be listed under their integration groups");
  await cdp.evaluate(`document.querySelector('button[data-model-option="qwen-plus"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('button[aria-label="选择分析模型"]')?.innerText.toLowerCase().includes("qwen-plus")`);
  await navigate(cdp, `${appUrl}/weekly-report`);
  await waitForEval(cdp, `document.body.innerText.includes("经营周报")`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await waitForEval(cdp, `document.querySelector('button[aria-label="选择分析模型"]')?.innerText.toLowerCase().includes("qwen-plus")`);
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await waitForEval(cdp, `document.querySelector('button[aria-label="选择分析模型"]')?.innerText.toLowerCase().includes("qwen-plus")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="添加分析上下文"]')?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.trim().startsWith("智能分析主查询"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim().startsWith("智能分析主查询"))?.click()`);
  await cdp.evaluate(`document.querySelector('button[aria-label="添加分析上下文"]')?.click()`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.trim().startsWith("描述性分析"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim().startsWith("描述性分析"))?.click()`);
  await assertEval(cdp, `(() => { const labels = [...document.querySelectorAll("button")].map((button) => button.textContent.trim()); return labels.includes("智能分析主查询") && labels.includes("描述性分析"); })()`, "one scene and one topic Skill must remain selected together");
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
    ["/weekly-report", "/weekly-report", "经营周报"],
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
    ["/agent/skills", "/agent/skills", "skill/插件"],
    ["/data-assets", "/data-assets/metrics", "指标字典"],
    ["/data-assets/metrics", "/data-assets/metrics", "指标字典"],
    ["/data-assets/knowledge", "/data-assets/knowledge", "知识记忆"],
    ["/data-assets/behavior", "/data-assets/knowledge", "知识记忆"],
    ["/data-assets/data-management", "/data-assets/data-management", "站内数据"],
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
    await assertEval(cdp, `document.querySelectorAll('[data-global-message-board-trigger="true"]').length === 1`, `route ${requestedPath} must expose exactly one global message-board shortcut`);
    await assertEval(cdp, `(() => {
      const wrapper = document.querySelector('[data-global-message-board-host]');
      return wrapper?.getAttribute('data-global-message-board-host') === 'fallback' || wrapper === wrapper?.parentElement?.lastElementChild;
    })()`, `route ${requestedPath} must keep the global message-board shortcut after all page-header actions`);
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
  await waitForEval(cdp, `document.querySelectorAll('input[type="radio"][name="analysis-data-table"]').length > 0`);
  await cdp.evaluate(`(() => { const radio = document.querySelector('input[type="radio"][name="analysis-data-table"]'); radio?.click(); [...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "完成")?.click(); })()`);
  await waitForEval(cdp, `![...document.querySelectorAll("button")].some((button) => button.textContent.trim() === "完成")`);
}

async function installSession(cdp, apiUrl, email, institution) {
  const expression = `
    (async () => {
      const response = await fetch(${JSON.stringify(`${apiUrl}/api/auth/login`)}, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: ${JSON.stringify(email)}, password: ${JSON.stringify(testDevelopmentLoginPassword)}, institution: ${JSON.stringify(institution)} })
      });
      if (!response.ok) throw new Error(await response.text());
      const session = await response.json();
      if (!session.tenant_id || !session.tenant_directory?.some((item) => item.id === session.tenant_id)) {
        throw new Error("login response is missing the canonical tenant directory");
      }
      localStorage.setItem(${JSON.stringify(authStorageKey)}, JSON.stringify(session));
      localStorage.setItem(${JSON.stringify(selectedInstitutionStorageKey)}, session.institution || ${JSON.stringify(institution)});
      return session.user.id;
    })()
  `;
  const userId = await cdp.evaluate(expression, true);
  if (!userId) throw new Error(`failed to install session for ${email}`);
}

async function configureApplicationModel(cdp, apiUrl, applicationModule, name, source = "中转站", models = ["frontend-smoke-model"], id = `model_${applicationModule}`, enabledModels = models) {
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
          enabledModels: ${JSON.stringify(enabledModels)},
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

async function verifyShellEdgeSpacing(cdp) {
  await waitForEval(cdp, `[...document.querySelectorAll("main h2")].some((heading) => heading.textContent.trim() === "智能分析")`);
  const measure = () => cdp.evaluate(`(() => {
    const html = document.documentElement;
    const main = document.querySelector('[data-agent-main-shell="true"]');
    const page = main?.firstElementChild;
    const sidebarHeader = document.querySelector('[data-agent-sidebar-header="true"]');
    const heading = [...document.querySelectorAll("main h2")].find((node) => node.textContent.trim() === "智能分析");
    const htmlRect = html.getBoundingClientRect();
    const mainRect = main?.getBoundingClientRect();
    const mainStyle = main ? getComputedStyle(main) : null;
    const pageStyle = page ? getComputedStyle(page) : null;
    return {
      viewport: { width: innerWidth, height: innerHeight },
      htmlRightGap: innerWidth - htmlRect.right,
      htmlOverflow: html.scrollWidth > html.clientWidth,
      main: mainRect && mainStyle ? {
        top: mainRect.top,
        rightGap: htmlRect.right - mainRect.right,
        paddingTop: parseFloat(mainStyle.paddingTop),
        paddingRight: parseFloat(mainStyle.paddingRight),
        overflow: main.scrollWidth > main.clientWidth,
      } : null,
      page: pageStyle ? {
        paddingTop: parseFloat(pageStyle.paddingTop),
        paddingRight: parseFloat(pageStyle.paddingRight),
        paddingBottom: parseFloat(pageStyle.paddingBottom),
        paddingLeft: parseFloat(pageStyle.paddingLeft),
      } : null,
      headingTop: heading && mainRect ? heading.getBoundingClientRect().top - mainRect.top : null,
      sidebarPaddingTop: sidebarHeader ? parseFloat(getComputedStyle(sidebarHeader).paddingTop) : null,
    };
  })()`);
  const desktop = await measure();
  assertShellEdgeMetrics(desktop, true);
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 900,
    height: 700,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await delay(200);
  const narrow = await measure();
  assertShellEdgeMetrics(narrow, false);
  console.log(JSON.stringify({ shellEdgeSpacing: { desktop, narrow } }));
}

function assertShellEdgeMetrics(metrics, expectSidebar) {
  const nearEdgeGap = (value) => typeof value === "number" && value >= 14 && value <= 17;
  if ((metrics?.main?.paddingTop || 0) > 0.5 || (metrics?.main?.paddingRight || 0) > 0.5) {
    throw new Error(`main shell must not pad itself, so the scrollbar stays flush: ${JSON.stringify(metrics)}`);
  }
  if (metrics.htmlRightGap > 0.5 || metrics.htmlOverflow || metrics.main?.overflow) {
    throw new Error(`shell must not reserve a document scrollbar gutter or overflow horizontally: ${JSON.stringify(metrics)}`);
  }
  if (!nearEdgeGap(metrics.page?.paddingTop) || !nearEdgeGap(metrics.page?.paddingRight) || metrics.page?.paddingLeft < 15 || metrics.page?.paddingBottom < 15) {
    throw new Error(`page top and right inset must be 0.4cm while keeping left and bottom padding: ${JSON.stringify(metrics)}`);
  }
  if (!nearEdgeGap(metrics.headingTop)) {
    throw new Error(`page heading must begin approximately 0.4cm below the viewport edge: ${JSON.stringify(metrics)}`);
  }
  if (expectSidebar && !nearEdgeGap(metrics.sidebarPaddingTop)) {
    throw new Error(`desktop sidebar header must begin approximately 0.4cm below the viewport edge: ${JSON.stringify(metrics)}`);
  }
}

async function verifyMenuRoutePerformance(cdp, appUrl) {
  await waitForEval(cdp, `[...document.querySelectorAll("main h2")].some((heading) => heading.textContent.trim() === "智能分析")`);
  await cdp.evaluate(`[...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "系统管理")?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('nav a[href="/settings/config"]'))`);
  await cdp.evaluate(`
    (() => {
      const startedAt = performance.now();
      const startPath = location.pathname;
      const probe = window.__menuRoutePerformanceProbe = {
        active: true,
        startedAt,
        startPath,
        samples: 0,
        pendingSamples: 0,
        fallbackSamples: 0,
        overflowSamples: 0,
        oldPageStable: true,
      };
      const sample = () => {
        if (!probe.active) return;
        const stillWaiting = location.pathname === startPath;
        probe.samples += 1;
        if (document.querySelector('[data-menu-route-pending="true"]')) probe.pendingSamples += 1;
        if (document.querySelector('[aria-label="页面内容加载中"]')) probe.fallbackSamples += 1;
        if (document.documentElement.scrollWidth > document.documentElement.clientWidth || document.body.scrollWidth > document.body.clientWidth) probe.overflowSamples += 1;
        if (stillWaiting && ![...document.querySelectorAll("main h2")].some((heading) => heading.textContent.trim() === "智能分析")) probe.oldPageStable = false;
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    })()
  `);
  await dispatchRealClick(cdp, 'nav a[href="/settings/config"]');
  await waitForEval(cdp, `location.pathname === "/settings/config" && Boolean(document.querySelector('[data-settings-upper-module="model-access"]'))`);
  await delay(100);
  const result = await cdp.evaluate(`(() => {
    const probe = window.__menuRoutePerformanceProbe;
    probe.active = false;
    return { ...probe, elapsedMs: performance.now() - probe.startedAt, finalPath: location.pathname };
  })()`);
  if (!result.oldPageStable) throw new Error(`menu route must retain the current page while its target module prepares: ${JSON.stringify(result)}`);
  if (result.fallbackSamples) throw new Error(`prepared menu navigation must not flash the page fallback: ${JSON.stringify(result)}`);
  if (result.overflowSamples) throw new Error(`menu navigation must not create horizontal overflow: ${JSON.stringify(result)}`);
  console.log(JSON.stringify({ menuRoutePerformance: result }));

  await cdp.send("Network.setBlockedURLs", { urls: ["*CustomerSegmentAnalysis*"] });
  await navigate(cdp, `${appUrl}/self-analysis/query`);
  await waitForEval(cdp, `location.pathname === "/self-analysis/query" && document.body.innerText.includes("智能分析")`);
  await cdp.evaluate(`[...document.querySelectorAll("nav button")].find((button) => button.textContent.trim() === "经营分析")?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('nav a[href="/customer-segment-analysis"]'))`);
  await dispatchRealClick(cdp, 'nav a[href="/customer-segment-analysis"]');
  await waitForEval(cdp, `location.pathname === "/customer-segment-analysis" && Boolean(document.querySelector('[data-route-error="true"]'))`, 30_000);
  await assertEval(cdp, `!document.querySelector('[data-menu-route-pending="true"]') && !document.querySelector('[aria-label="页面内容加载中"]')`, "failed target module preparation must release menu pending and reach the existing route error boundary");
  await cdp.send("Network.setBlockedURLs", { urls: [] });
}

async function verifyModelSelectionPerformance(cdp, appUrl) {
  await navigate(cdp, `${appUrl}/settings/config`, 30_000);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-settings-upper-module="model-access"]'))`);
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑模型接入"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("模型接入管理")`);
  await cdp.evaluate(`document.querySelector('[data-model-edit-row="model_global_analysis_relay"]')?.click()`);
  await waitForEval(cdp, `document.querySelectorAll('[data-model-option]').length >= 40`);
  await cdp.evaluate(`performance.clearResourceTimings()`);
  await cdp.evaluate(`(() => {
    const scroll = document.querySelector('[data-model-integrations-scroll="true"]');
    const labels = [...document.querySelectorAll('[data-model-option]')];
    scroll.scrollTop = Math.max(0, scroll.scrollHeight - scroll.clientHeight - 80);
    window.__modelPerformanceBefore = {
      order: labels.map((label) => label.getAttribute('data-model-option')),
      scrollTop: scroll.scrollTop,
    };
    labels.find((label) => label.getAttribute('data-model-option') === 'perf-model-40')?.querySelector('input')?.click();
  })()`);
  await waitForEval(cdp, `document.querySelector('[data-model-option="perf-model-40"]')?.getAttribute('data-model-option-selected') === "true" && document.querySelector('[role="status"]')?.textContent.includes("模型接入已更新")`);
  await assertEval(cdp, `(() => {
    const scroll = document.querySelector('[data-model-integrations-scroll="true"]');
    const currentOrder = [...document.querySelectorAll('[data-model-option]')].map((label) => label.getAttribute('data-model-option'));
    const configReads = performance.getEntriesByType('resource').filter((entry) => new URL(entry.name).pathname === '/api/system-config').length;
    return JSON.stringify(currentOrder) === JSON.stringify(window.__modelPerformanceBefore.order)
      && Math.abs(scroll.scrollTop - window.__modelPerformanceBefore.scrollTop) <= 2
      && configReads === 0;
  })()`, "model checkbox save must keep scroll and order without a redundant system-config read");
  await assertEval(cdp, `fetch('/api/system-config', { credentials: 'include' }).then(async (response) => {
    if (!response.ok) return false;
    const payload = await response.json();
    return payload.models?.find((model) => model.id === 'model_global_analysis_relay')?.enabledModels?.includes('perf-model-40') === true;
  })`, "selected child model must be persisted by the existing system-config API");
  await cdp.evaluate(`(() => {
    const originalFetch = window.fetch;
    window.fetch = (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (new URL(url, location.origin).pathname === '/api/system-config/model' && (init?.method || 'GET').toUpperCase() === 'POST') {
        window.fetch = originalFetch;
        return Promise.resolve(new Response(JSON.stringify({ detail: 'isolated save failure' }), { status: 500, headers: { 'Content-Type': 'application/json' } }));
      }
      return originalFetch(input, init);
    };
    const scroll = document.querySelector('[data-model-integrations-scroll="true"]');
    window.__modelFailureBefore = {
      order: [...document.querySelectorAll('[data-model-option]')].map((label) => label.getAttribute('data-model-option')),
      scrollTop: scroll.scrollTop,
    };
    document.querySelector('[data-model-option="perf-model-39"] input')?.click();
  })()`);
  await waitForEval(cdp, `document.querySelector('[role="status"]')?.textContent.includes("失败") && document.querySelector('[data-model-option="perf-model-39"]')?.getAttribute('data-model-option-selected') === "false"`);
  await assertEval(cdp, `(() => {
    const scroll = document.querySelector('[data-model-integrations-scroll="true"]');
    const order = [...document.querySelectorAll('[data-model-option]')].map((label) => label.getAttribute('data-model-option'));
    return JSON.stringify(order) === JSON.stringify(window.__modelFailureBefore.order) && Math.abs(scroll.scrollTop - window.__modelFailureBefore.scrollTop) <= 2;
  })()`, "failed child-model save must roll back selection without moving the list");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭弹窗"]')?.click()`);
  await waitForEval(cdp, `!document.body.innerText.includes("模型接入管理")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑模型接入"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("模型接入管理")`);
  await cdp.evaluate(`document.querySelector('[data-model-edit-row="model_global_analysis_relay"]')?.click()`);
  await waitForEval(cdp, `document.querySelectorAll('[data-model-option]').length >= 40`);
  await assertEval(cdp, `(() => {
    const states = [...document.querySelectorAll('[data-model-option]')].map((label) => label.getAttribute('data-model-option-selected') === 'true');
    const firstUnselected = states.indexOf(false);
    return firstUnselected === -1 || !states.slice(firstUnselected).includes(true);
  })()`, "reopened model dialog must place selected child models first");
}

async function verifyGlobalMessageBoardShortcut(cdp, appUrl) {
  const representativeRoutes = [
    ["/dashboard", "多机构分析"],
    ["/self-analysis/query", "智能分析"],
    ["/data-assets/data-management", "站内数据"],
    ["/settings/config", "系统配置"],
  ];
  for (const [path, marker] of representativeRoutes) {
    await navigate(cdp, `${appUrl}${path}`, 30_000);
    await waitForEval(cdp, `location.pathname === ${JSON.stringify(path)} && document.body.innerText.includes(${JSON.stringify(marker)}) && Boolean(document.querySelector('[data-global-message-board-trigger="true"]'))`, 30_000);
    const shortcutPosition = await cdp.evaluate(`(() => {
      const trigger = document.querySelector('[data-global-message-board-trigger="true"]');
      const wrapper = trigger?.parentElement;
      const host = wrapper?.parentElement;
      if (!trigger || !wrapper || !host) return { valid: false, reason: "missing" };
      const right = trigger.getBoundingClientRect().right;
      const childRects = [...host.children].filter((child) => child instanceof HTMLElement && child.getBoundingClientRect().width > 0)
        .map((child) => ({ tag: child.tagName, text: child.textContent?.trim().slice(0, 30), right: child.getBoundingClientRect().right, isWrapper: child === wrapper }));
      return {
        valid: wrapper === host.lastElementChild && childRects.filter((child) => !child.isWrapper).every((child) => child.right <= right + 1),
        host: host.getAttribute("data-page-header-actions") || host.getAttribute("data-standard-analysis-page-actions") || wrapper.getAttribute("data-global-message-board-host"),
        hostClass: host.className,
        right,
        childRects,
      };
    })()`);
    if (!shortcutPosition?.valid) throw new Error(`global message-board shortcut must be the rightmost page-header action on ${path}: ${JSON.stringify(shortcutPosition)}`);
  }

  await navigate(cdp, `${appUrl}/dashboard`, 30_000);
  await waitForEval(cdp, `document.body.innerText.includes("多机构分析") && Boolean(document.querySelector('[data-global-message-board-trigger="true"]'))`);
  await cdp.evaluate(`document.querySelector('[data-global-message-board-trigger="true"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[data-global-message-board-popover="true"]'))`);
  await assertEval(cdp, `(() => {
    const popover = document.querySelector('[data-global-message-board-popover="true"]');
    const rect = popover?.getBoundingClientRect();
    const scroll = document.querySelector('[data-global-message-board-scroll="true"]');
    return Boolean(rect && scroll && rect.width >= 450 && rect.width <= 458 && rect.height >= 375 && rect.height <= 760 && getComputedStyle(scroll).overflowY === "auto");
  })()`, "message-board popover must use the requested 12cm width, 10cm minimum height and 20cm scroll ceiling");

  const draftText = `全局留言板草稿与管理员回显 ${Date.now()}`;
  await cdp.evaluate(`(() => {
    const input = document.querySelector('[data-global-message-board-input="true"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(input, ${JSON.stringify(draftText)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
  await delay(700);
  await waitForEval(cdp, `document.querySelector('[data-message-board-draft-status="saved"]')`);
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭留言气泡"]')?.click()`);
  await waitForEval(cdp, `getComputedStyle(document.querySelector('[data-global-message-board-popover="true"]')).display === "none"`);
  await cdp.evaluate(`document.querySelector('[data-global-message-board-trigger="true"]')?.click()`);
  await waitForEval(cdp, `document.querySelector('[data-global-message-board-input="true"]')?.value === ${JSON.stringify(draftText)}`);

  await cdp.evaluate(`(() => {
    const input = document.querySelector('[data-global-message-board-input="true"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(input, Array.from({ length: 80 }, (_, index) => "页面问题明细 " + (index + 1)).join("\\n"));
    input.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
  await waitForEval(cdp, `(() => {
    const popover = document.querySelector('[data-global-message-board-popover="true"]');
    const scroll = document.querySelector('[data-global-message-board-scroll="true"]');
    return Boolean(popover && scroll && popover.getBoundingClientRect().height <= 380 && scroll.scrollHeight > scroll.clientHeight);
  })()`);
  await cdp.evaluate(`(() => {
    const input = document.querySelector('[data-global-message-board-input="true"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(input, ${JSON.stringify(draftText)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);

  await cdp.evaluate(`(() => {
    const input = document.querySelector('[data-global-message-board-input="true"]');
    const bytes = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="), (char) => char.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], "page-problem.png", { type: "image/png" }));
    input.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: transfer }));
  })()`);
  await waitForEval(cdp, `document.querySelectorAll('[data-global-message-board-images="true"] img').length === 1`);
  await delay(700);

  await cdp.evaluate(`(() => {
    window.__messageBoardVoiceSockets = [];
    class FakeWebSocket {
      static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
      constructor(url) { this.url = url; this.readyState = 0; window.__messageBoardVoiceSockets.push(this); setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 20); }
      send(data) { if (typeof data !== "string") return; try { const payload = JSON.parse(data); if (payload.type === "start") { this.startPayload = payload; setTimeout(() => { this.onmessage?.({ data: JSON.stringify({ type: "config", provider: "aliyun_fun_asr" }) }); this.onmessage?.({ data: JSON.stringify({ type: "ready" }) }); }, 20); } } catch {} }
      close() { if (this.readyState >= 2) return; this.readyState = 3; setTimeout(() => this.onclose?.({}), 10); }
      emit(text) { this.onmessage?.({ data: JSON.stringify({ type: "transcript", text, final: true }) }); }
    }
    Object.defineProperty(window, "WebSocket", { value: FakeWebSocket, configurable: true });
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) }, configurable: true });
    class FakeAudioContext {
      constructor() { this.sampleRate = 16000; this.destination = {}; }
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
      createScriptProcessor() { return { onaudioprocess: null, connect() {}, disconnect() {} }; }
      close() { return Promise.resolve(); }
    }
    Object.defineProperty(window, "AudioContext", { value: FakeAudioContext, configurable: true });
  })()`);
  await cdp.evaluate(`document.querySelector('[data-global-message-board-voice="true"]')?.click()`);
  await waitForEval(cdp, `window.__messageBoardVoiceSockets.at(-1)?.startPayload?.applicationModule === "realtime_voice_input"`);
  await cdp.evaluate(`window.__messageBoardVoiceSockets.at(-1).emit("语音补充页面操作卡顿")`);
  await waitForEval(cdp, `document.querySelector('[data-global-message-board-input="true"]')?.value.includes("语音补充页面操作卡顿")`);
  await cdp.evaluate(`document.querySelector('[data-global-message-board-voice="true"]')?.click()`);

  await cdp.evaluate(`(() => {
    const originalFetch = window.fetch;
    window.fetch = (input, init = {}) => {
      const url = new URL(typeof input === "string" ? input : input.url, location.origin);
      if (url.pathname === "/api/message-board/image" && (init.method || "GET").toUpperCase() === "POST") {
        window.fetch = originalFetch;
        return Promise.resolve(new Response(JSON.stringify({ detail: "isolated image upload failure" }), { status: 503, headers: { "Content-Type": "application/json" } }));
      }
      return originalFetch(input, init);
    };
    [...document.querySelectorAll('[data-global-message-board-popover="true"] button')].find((button) => button.textContent.trim() === "提交")?.click();
  })()`);
  await waitForEval(cdp, `document.querySelector('[data-global-message-board-popover="true"] [role="status"]')?.textContent.includes("Data Agent API 请求失败")`);
  await assertEval(cdp, `document.querySelector('[data-global-message-board-input="true"]')?.value.includes(${JSON.stringify(draftText)}) && document.querySelectorAll('[data-global-message-board-images="true"] img').length === 1`, "failed submission must keep the text and image draft in place");

  await cdp.evaluate(`[...document.querySelectorAll('[data-global-message-board-popover="true"] button')].find((button) => button.textContent.trim() === "提交")?.click()`);
  await waitForEval(cdp, `document.querySelector('[data-global-message-board-trigger="true"]')?.textContent.includes("已提交")`, 30_000);
  await assertEval(cdp, `fetch('/api/message-board?page_key=dashboard', { credentials: 'include' }).then(async (response) => {
    if (!response.ok) return false;
    const payload = await response.json();
    const message = payload.messages?.find((item) => item.content.includes(${JSON.stringify(draftText)}));
    return Boolean(message && message.page_title === '多机构分析' && message.attachment_ids?.length === 1);
  })`, "submitted text and screenshot must be readable from the existing message-board API");

  await navigate(cdp, `${appUrl}/agent/message-board`, 30_000);
  await waitForEval(cdp, `document.body.innerText.includes("留言板管理") && [...document.querySelectorAll('[data-message-board-admin-row]')].some((row) => row.textContent.includes(${JSON.stringify(draftText)}))`, 30_000);
  await cdp.evaluate(`(() => {
    const row = [...document.querySelectorAll('[data-message-board-admin-row]')].find((item) => item.textContent.includes(${JSON.stringify(draftText)}));
    row?.querySelector('button[aria-label="展开留言详情"]')?.click();
  })()`);
  await waitForEval(cdp, `(() => { const row = [...document.querySelectorAll('[data-message-board-admin-row]')].find((item) => item.textContent.includes(${JSON.stringify(draftText)})); return Boolean(row?.querySelector('[data-message-board-attachment-gallery="true"] img')); })()`, 30_000);
  await runFullRouteSmoke(cdp, appUrl);
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

async function setFileInput(cdp, selector, filePath) {
  const document = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
  const result = await cdp.send("DOM.querySelector", { nodeId: document.root.nodeId, selector });
  if (!result.nodeId) throw new Error(`cannot find file input: ${selector}`);
  await cdp.send("DOM.setFileInputFiles", { nodeId: result.nodeId, files: [filePath] });
}

async function createCustomerListWorkbook(filePath) {
  const script = [
    "from openpyxl import Workbook",
    "import sys",
    "wb = Workbook()",
    "ws = wb.active",
    "ws.append(('C001', 'ignored'))",
    "ws.append(('C002', None))",
    "ws.append(('C001', None))",
    "ws.append((None, 'ignored'))",
    "wb.save(sys.argv[1])",
    "wb.close()",
  ].join("; ");
  const child = spawn("uv", ["run", "python", "-c", script, filePath], { cwd: root, stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
  const exitCode = await new Promise((resolve) => child.once("exit", resolve));
  if (exitCode !== 0) throw new Error(`failed to create customer-list workbook: ${stderr}`);
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
    return Boolean(rect && Math.hypot(rect.left - ${before.left}, rect.top - ${before.top}) >= Math.max(4, Math.hypot(${deltaX}, ${deltaY}) * 0.35));
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
  const pageState = await cdp.evaluate(`({
    path: location.pathname,
    body: document.body.innerText.slice(0, 1200),
    dialogs: [...document.querySelectorAll('[role="dialog"]')].map((dialog) => ({
      label: dialog.getAttribute('aria-label'),
      text: dialog.innerText.slice(0, 600),
    })),
    inputs: [...document.querySelectorAll('input')].slice(0, 12).map((input) => ({
      placeholder: input.getAttribute('placeholder'),
      value: input.value,
      meta: input.closest('[data-report-meta-key]')?.getAttribute('data-report-meta-key') || null,
    })),
  })`).catch(() => null);
  const recentResponses = cdp.events
    .filter((event) => event.method === "Network.responseReceived" && String(event.params?.response?.url || "").includes("/api/"))
    .slice(-8)
    .map((event) => ({ status: event.params?.response?.status, url: event.params?.response?.url }));
  throw new Error(`timed out waiting for expression: ${expression}; page=${JSON.stringify(pageState)}; recentResponses=${JSON.stringify(recentResponses)}`);
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
