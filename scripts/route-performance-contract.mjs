import fs from "node:fs";

const preload = fs.readFileSync("src/app/routePreload.ts", "utf8");
const dataPreload = fs.readFileSync("src/app/routeDataPreload.ts", "utf8");
const layout = fs.readFileSync("src/app/components/Layout.tsx", "utf8");
const apiClient = fs.readFileSync("src/app/services/apiClient.ts", "utf8");
const visualCards = fs.readFileSync("src/app/components/visual-report/VisualReportCards.tsx", "utf8");
const visualBuilder = fs.readFileSync("src/app/components/VisualReportBuilder.tsx", "utf8");
const analysisConfig = fs.readFileSync("src/app/components/AnalysisConfigManager.tsx", "utf8");
const workspace = fs.readFileSync("src/app/components/DataAgentWorkspace.tsx", "utf8");
const settings = fs.readFileSync("src/app/components/SystemSettings.tsx", "utf8");
const automationApi = fs.readFileSync("src/app/services/automationApi.ts", "utf8");
const capabilitiesApi = fs.readFileSync("src/app/services/capabilitiesApi.ts", "utf8");
const accessApi = fs.readFileSync("src/app/services/accessControlApi.ts", "utf8");

const checks = [
  [preload.includes("warmVisibleRoutePaths"), "可见页面必须支持空闲预热"],
  [preload.includes("requestIdleCallback") && preload.includes("setTimeout(runNext, 180)"), "预热必须优先使用空闲调度并提供兼容回退"],
  [preload.includes("pendingLoaders.shift()") && preload.includes("finally(scheduleNext)"), "页面模块必须逐个预热，避免并发抢占主线程"],
  [preload.includes("routeLoaderPromises"), "悬停、聚焦和空闲预热必须复用同一个模块请求"],
  [preload.includes("cancelIdleCallback") && preload.includes("clearTimeout"), "页面卸载或路由变化必须取消未开始的预热"],
  [preload.includes('path !== currentPath'), "当前已加载页面不得重复进入预热队列"],
  [preload.includes("routeWarmGroup") && preload.includes('return "self-analysis"'), "空闲预热必须优先当前菜单分组并保持全站回退"],
  [preload.includes('path === "/dashboard"'), "多机构分析一级入口必须纳入统一预热映射"],
  [preload.includes('path.startsWith("/agent/message-board")'), "留言板页面必须纳入统一预热映射"],
  [layout.includes('navigationStatus !== "ready"'), "权限导航未就绪时不得启动页面预热"],
  [layout.includes("visibleMenuItems.flatMap"), "只能预热当前用户可见的页面"],
  [layout.includes("return warmVisibleRoutePaths(visiblePaths, location.pathname)"), "路由变化必须清理并重建剩余预热队列"],
  [(layout.match(/preloadRoutePath\(/g) || []).length >= 4, "一级和二级页面入口都必须保留悬停和聚焦即时预热"],
  [(layout.match(/preloadRouteDataPath\(/g) || []).length >= 4, "一级和二级页面入口必须按目标页预取业务数据"],
  [(layout.match(/onPointerDown=/g) || []).length >= 2, "鼠标与触屏点击必须在路由提交前启动代码和数据预取"],
  [!preload.includes("fetch("), "路由预热不得触发业务 API"],
  [dataPreload.includes("Promise.allSettled") && dataPreload.includes("routeDataTasks"), "数据预取必须失败隔离且按页面收敛依赖"],
  [dataPreload.match(/path\.startsWith\("\/self-analysis\/config"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.match(/fetchDataAssets/g)?.length === 2 && dataPreload.includes('scope: "knowledge"'), "分析配置必须预取目录与知识投影并复用服务缓存"],
  [dataPreload.match(/path\.startsWith\("\/agent\/skills"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes('scope: "knowledge"') === true, "Skill 插件必须只预取知识投影"],
  [dataPreload.match(/path\.startsWith\("\/data-assets\/tools"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchMetricDictionary") === false, "工具调用不得预取未使用的指标字典"],
  [dataPreload.match(/path\.startsWith\("\/agent\/tasks"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchPlatformCapabilities") === true && dataPreload.includes("fetchAutomationWorkspace"), "自动化任务必须预取真实任务与能力依赖"],
  [automationApi.includes('tags: ["automation-workspace"]') && capabilitiesApi.includes('tags: ["platform-capabilities"]'), "任务与能力读取必须短缓存并合并预取和挂载请求"],
  [workspace.includes('if (activeTab !== "tasks") return;'), "待办页面不得加载自动化任务专属目录"],
  [dataPreload.includes('/settings/config') && dataPreload.includes('/settings/users') && dataPreload.includes('/settings/audit'), "系统管理必须按子页预取精确依赖"],
  [settings.includes('if (activeTab !== "config") return;') && settings.includes('activeTab !== "users" && activeTab !== "roles"'), "系统管理挂载不得读取其他 Tab 数据"],
  [accessApi.match(/readCache:/g)?.length === 2, "用户与角色读取必须短缓存并在写入后统一失效"],
  [dataPreload.includes('/self-analysis/reports') && dataPreload.includes("fetchVisualReports") && dataPreload.includes("fetchSavedAnalysisResults"), "我的报表必须预取两类首屏报表配置"],
  [dataPreload.match(/path\.startsWith\("\/self-analysis\/reports"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchDataAssets") === false, "我的报表悬停预取不得用大目录抢占首屏列表"],
  [apiClient.includes("apiReadInflight") && apiClient.includes("apiReadCacheKey"), "共享读取层必须合并并发请求并按上下文生成缓存键"],
  [apiClient.includes("context?.tenantId") && apiClient.includes("context?.userId"), "缓存键必须隔离租户和用户"],
  [apiClient.includes("method !== \"GET\"") && apiClient.includes("clearApiReadCache"), "成功写操作必须让读取缓存失效"],
  [apiClient.includes("apiReadCacheGeneration") && apiClient.includes("apiReadInflight.clear()"), "写操作后旧并发读取不得重新写回缓存"],
  [visualCards.includes('data-visual-report-data-loading="true"') && visualCards.indexOf("if (loading)") < visualCards.indexOf("<AnalysisVisualCard"), "真实数据投影完成前不得把标准图表挂载为空态"],
  [visualBuilder.includes("reportLoading") && visualBuilder.includes("catalogLoading"), "报表框架与数据目录必须渐进加载"],
  [visualBuilder.includes('if (view !== "editor" || catalogLoadedRef.current) return;') && visualBuilder.indexOf("fetchVisualReports({ tenantId, userId })") < visualBuilder.indexOf('fetchDataAssets({ tenantId, userId, scope: "visualization" })'), "可视化报表落地页必须仅读取报表骨架，进入编辑器后再准备专用目录"],
  [visualCards.includes('scope: "visualization"') && !visualCards.includes('scope: "runtime"'), "可视化报表回读必须使用单一瘦目录请求"],
  [visualBuilder.includes("h-[min(88vh,900px)]") && visualBuilder.includes("shrink-0") && visualBuilder.includes("overflow-hidden"), "图表弹窗必须固定可视高度并隔离内容滚动与操作栏"],
  [analysisConfig.includes('aria-label="正在读取分析配置"') && analysisConfig.includes("!loading && !shortcuts.length"), "分析配置冷启动必须显示局部骨架且不得闪现假空态"],
];

const failed = checks.filter(([passed]) => !passed);
for (const [passed, label] of checks) console.log(`${passed ? "PASS" : "FAIL"} ${label}`);
if (failed.length) process.exit(1);
