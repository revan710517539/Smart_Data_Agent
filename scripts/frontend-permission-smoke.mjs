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

  try {
  const api = spawn(
    "python3",
    ["-m", "backend.platform.api.server", "--host", "127.0.0.1", "--port", String(apiPort), "--db", join(workDir, "api.sqlite")],
    { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
  );
  processes.push(api);
  await waitForHttp(`${apiUrl}/api/health`);

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
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 960,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await waitForEval(cdp, `location.pathname === "/login" && document.readyState !== "loading"`);

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
  await cdp.evaluate(`
    localStorage.removeItem(${JSON.stringify(authStorageKey)});
    localStorage.removeItem(${JSON.stringify(selectedInstitutionStorageKey)});
  `);
  // Cached shell rendering is intentionally immediate.  First allow the
  // HttpOnly-session reconciliation to populate local state, then navigate to
  // the privileged route; otherwise the unauthenticated first render quite
  // correctly redirects the browser to the landing page.
  await navigate(cdp, `${appUrl}/`);
  await waitForEval(cdp, `JSON.parse(localStorage.getItem(${JSON.stringify(authStorageKey)}))?.user?.id === "u_super_admin"`);
  await navigate(cdp, `${appUrl}/settings/config`, 30_000);
  await waitForEval(cdp, `location.pathname === "/settings/config" && document.body.innerText.includes("模型接入") && document.body.innerText.includes("用户与角色概览")`);
  await assertEval(
    cdp,
    `JSON.parse(localStorage.getItem(${JSON.stringify(authStorageKey)}))?.user?.id === "u_super_admin"`,
    "an HttpOnly session must restore even when this frontend port has no local auth cache",
  );
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
  await navigate(cdp, `${appUrl}/`);
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
  await waitForEval(cdp, `location.pathname !== "/settings/config"`);
  await assertEval(
    cdp,
    `!document.body.innerText.includes("系统接入配置加载失败") && !document.body.innerText.includes("The requested operation is not permitted")`,
    "a cookie identity change must reconcile and leave an unauthorized config route before it loads",
  );
  await installSession(cdp, appUrl, "xujingbo-jk@qifu.com", "华兴银行");
  await navigate(cdp, `${appUrl}/settings/roles`);
  await waitForEval(cdp, `document.body.innerText.includes("角色权限")`);

  await navigate(cdp, `${appUrl}/agent/skills`);
  await waitForEval(cdp, `document.body.innerText.includes("周报分析") && document.body.innerText.includes("运营日常分析") && document.body.innerText.includes("风险策略分析")`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增场景"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增场景"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label*="新增场景"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label*="新增场景"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new scene must open as a centered system modal");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭场景弹窗"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "主题")?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("描述性分析") && document.body.innerText.includes("可疑交易分析") && document.body.innerText.includes("逾期风险分析")`);
  await waitForEval(cdp, `[...document.querySelectorAll("button")].some((button) => button.textContent.includes("新增主题"))`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("新增主题"))?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('[role="dialog"][aria-label*="新增主题"]'))`);
  await assertEval(cdp, `(() => { const rect = document.querySelector('[role="dialog"][aria-label*="新增主题"]').getBoundingClientRect(); return Math.abs(rect.left + rect.width / 2 - innerWidth / 2) < 12 && rect.top > 20 && rect.bottom < innerHeight - 20; })()`, "new topic must open as a centered system modal");
  await assertEval(cdp, `(() => { const dialog = document.querySelector('[role="dialog"][aria-label*="新增主题"]'); return dialog && !dialog.innerText.includes("格式要求") && dialog.innerText.includes("主题 Skill 不设置固定格式"); })()`, "topic Skill must not expose a fixed output-format field and must explain adaptive visualization");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭主题弹窗"]')?.click()`);

  await navigate(cdp, `${appUrl}/data-assets/knowledge`);
  await waitForEval(cdp, `document.body.innerText.includes("知识记忆") && document.body.innerText.includes("知识文件仅用于提炼意图")`);
  await assertEval(cdp, `!document.body.innerText.includes("知识文件提炼任务") && !document.body.innerText.includes("新建提炼任务")`, "knowledge memory page must no longer own automation-task management");
  await assertEval(cdp, `(() => { const selects = [...document.querySelectorAll("select")]; return selects.some((node) => [...node.options].some((option) => option.textContent.includes("按时间倒排"))) && selects.some((node) => [...node.options].some((option) => option.textContent.includes("全部状态"))); })()`, "knowledge memory must expose the same sort and status controls as behavior habits");

  await navigate(cdp, `${appUrl}/data-assets/data-management`);
  await waitForEval(cdp, `document.body.innerText.includes("原始表读取 Origin_Data") && document.body.innerText.includes("每页 10 条") && document.body.innerText.includes("原始表") && document.body.innerText.includes("主题表")`);
  await assertEval(cdp, `!document.body.innerText.includes("新增原始表") && !document.body.innerText.includes("数据接入") && !document.body.innerText.includes("爬虫")`, "CSV-only data management must not expose retired raw-upload, data-access, or crawler controls");
  await assertEval(cdp, `(() => { const text = document.body.innerText; return text.includes("原始表 27") && text.includes("1 / 3") && Boolean(document.querySelector('button[aria-label^="展开"]')); })()`, "data management must paginate the latest Origin_Data CSV catalog and expose expandable file records");

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

  await navigate(cdp, `${appUrl}/self-analysis/config`);
  await waitForEval(cdp, `["分行放款排名分析","M1逾期率归因分析","渠道获客成本与ROI分析","客群转化与活跃分析","机构经营规模与目标分析","客户画像与风险分层分析","贷款申请授信动支漏斗分析"].every((title) => document.body.innerText.includes(title))`);
  await cdp.evaluate(`document.querySelector('button[aria-label^="编辑"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('summary[aria-label="选择分析记忆"]')) && document.body.innerText.includes("这里只保存记忆 ID")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭编辑分析配置"]')?.click()`);

  await navigate(cdp, `${appUrl}/settings/config`);
  await waitForEval(cdp, `location.pathname === "/settings/config" && document.body.innerText.includes("模型接入") && document.body.innerText.includes("用户与角色概览")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="编辑模型接入"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("模型接入管理") && document.body.innerText.includes("应用模块")`);
  await assertEval(cdp, `["智能分析推理分析","周报结论重新生成","自动分析任务","记忆模块","Skill自学习与演化"].every((label) => [...document.querySelectorAll("option")].some((option) => option.textContent.trim() === label)) && ![...document.querySelectorAll("option")].some((option) => option.textContent.trim() === "爬虫异常优化")`, "large-model application dropdown must expose the current governed LLM application modules");
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "语音转文字")?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("实时语音录入") && document.body.innerText.includes("弹窗语音录入")`);
  await assertEval(cdp, `(() => { const select = [...document.querySelectorAll("select")].find((node) => [...node.options].some((option) => option.value === "weekly_report_conclusion_regeneration")); const values = ["realtime_voice_input","popup_voice_input","intelligent_analysis_reasoning","weekly_report_conclusion_regeneration","automatic_analysis","memory_extraction","skill_evolution_learning"]; return Boolean(select) && !select.multiple && values.every((value) => [...select.options].some((option) => option.value === value)) && ![...select.options].some((option) => option.value === "crawler_exception_optimization"); })()`, "speech application module must be single-select and expose the current shared function list");
  await cdp.evaluate(`document.querySelector('button[aria-label="关闭弹窗"]')?.click()`);
  await assertEval(cdp, `!document.body.innerText.includes("数据接入") && !document.body.innerText.includes("爬虫")`, "system configuration must not expose the retired crawler or data-access module");

  await navigate(cdp, `${appUrl}/weekly-report`);
  await waitForEval(cdp, `document.body.innerText.includes("核心指标表现") && ["在贷余额","放款金额","新增余额"].every((label) => document.body.innerText.includes(label))`);
  await assertEval(cdp, `(() => { const tabs = [...document.querySelectorAll("button")].filter((button) => ["可视化分析","分析结论"].includes(button.textContent.trim())); return tabs[0]?.textContent.trim() === "可视化分析" && tabs[1]?.textContent.trim() === "分析结论" && !document.body.innerText.includes("待载入"); })()`, "weekly report must default to visualization before conclusion and render direct metric data without LLM placeholders");
  await waitForEval(cdp, `document.body.innerText.includes("核心指标周度趋势") && document.body.innerText.includes("按日期从早到晚 · 单位：亿元")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析数据模块"]')?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("拖动排序 · 点击显隐") && document.body.innerText.includes("分析时间：") && document.body.innerText.includes("显示中")`);
  await assertEval(cdp, `(() => { const menu = document.querySelector('button[aria-label="选择分析数据模块"]')?.parentElement; const rows = [...(menu?.querySelectorAll('div[draggable="true"]') || [])].filter((row) => row.innerText.includes("分析时间：")); const titles = rows.map((row) => row.querySelector('button span.min-w-0 span')?.textContent.trim()); const core = rows.find((row) => row.innerText.includes("核心指标表现")); const saved = rows.filter((row) => !row.innerText.includes("核心指标表现")); return rows.length > 0 && titles[0] === "核心指标表现" && rows.every((row) => row.draggable) && new Set(titles).size === titles.length && !rows.some((row) => row.innerText.includes("核心 ·")) && !core?.querySelector('button[aria-label^="删除分析模块"]') && saved.every((row) => row.querySelector('button[aria-label^="删除分析模块"]')); })()`, "weekly modules must default core first, remain draggable and deduplicated, and expose delete only for saved analysis");
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
  await waitForEval(cdp, `document.body.innerText.includes("智能分析") && document.body.innerText.includes("执行记录") && document.body.innerText.includes("分行放款排名分析")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析模型"]')?.click()`);
  await waitForEval(cdp, `document.querySelectorAll("[data-model-group]").length === 3`);
  await assertEval(cdp, `[...document.querySelectorAll("[data-model-group]")].map((node) => node.dataset.modelGroup).join("|") === "经营分析中转站A|经营分析中转站B|其他"`, "relay integrations must each form a category and non-relay models must be grouped last under 其他");
  await assertEval(cdp, `[...document.querySelectorAll("[data-model-option]")].map((node) => node.dataset.modelOption).join("|") === "gpt-5.5|deepseek-v4-flash|qwen-plus|claude-sonnet-4"`, "all configured child models must be listed in stable integration order");
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析模型"]')?.click()`);
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
  await waitForEval(cdp, `document.body.innerText.includes("分析配置")`);
  await assertEval(cdp, `!document.body.innerText.includes("用户管理")`, "operator should not see user management");
  await assertEval(cdp, `!document.body.innerText.includes("角色权限")`, "operator should not see role permissions");

    await cdp.close();
    console.log("frontend permission smoke passed");
  } finally {
    for (const child of processes.reverse()) {
      child.kill("SIGTERM");
    }
    await rmWithRetry(workDir);
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
  await waitForEval(cdp, `document.body.innerText.includes("智能分析") && document.body.innerText.includes("贷款申请授信动支漏斗分析")`);
  await cdp.evaluate(`document.querySelector('button[aria-label="选择分析模型"]')?.click()`);
  await waitForEval(cdp, `Boolean(document.querySelector('button[data-model-option="qwen-plus"]'))`);
  await cdp.evaluate(`document.querySelector('button[data-model-option="qwen-plus"]')?.click()`);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.trim() === "贷款申请授信动支漏斗分析")?.click()`);
  await waitForEval(cdp, `window.__analysisRuns === 1`, 5000);
  await assertEval(cdp, `window.__analysisBodies[0]?.page_context?.model_application_module === "intelligent_analysis_reasoning"`, "shortcut analysis must route through the intelligent-analysis application-module placeholder");
  await assertEval(cdp, `window.__analysisBodies[0]?.page_context?.model_application_selection?.integrationId === "model_analysis_mock_b" && window.__analysisBodies[0]?.page_context?.model_application_selection?.selectedModelName === "qwen-plus"`, "selected dropdown model must be sent as a module-scoped selection");
  await cdp.evaluate(`window.__releaseAnalysis(1)`);
  await waitForEval(cdp, `document.body.innerText.includes("测试分行") && Boolean(document.querySelector('button[aria-label="开始分析"]'))`, 5000);
  await cdp.evaluate(`[...document.querySelectorAll("button")].find((button) => button.textContent.includes("执行记录"))?.click()`);
  await waitForEval(cdp, `document.body.innerText.includes("查看历史问题、分析结果、思考阶段和执行链路") && Boolean(document.querySelector('button[title="删除执行记录"]'))`);
  await assertEval(cdp, `(() => { const buttons = [...document.querySelectorAll('button[title="删除执行记录"],button[title="查看分析结果"],button[title="展开执行详情"]')]; return buttons.length >= 3 && buttons.every((button) => button.textContent.trim() === ""); })()`, "history delete, view and detail actions must be icon-only");

  await navigate(cdp, `${appUrl}/self-analysis/query?popup-voice-smoke=1`);
  await waitForEval(cdp, `document.body.innerText.includes("智能分析")`);
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
  }

  open() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
      this.ws.addEventListener("message", (event) => {
        const message = JSON.parse(event.data);
        if (!message.id) return;
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
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "Runtime.evaluate failed");
    }
    return result.result?.value;
  }

  close() {
    this.ws?.close();
  }
}

async function waitForHttp(url, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.status < 500) return;
    } catch {
      // Retry.
    }
    await delay(250);
  }
  throw new Error(`timed out waiting for ${url}`);
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
