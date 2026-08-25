import fs from "node:fs";

const preload = fs.readFileSync("src/app/routePreload.ts", "utf8");
const routes = fs.readFileSync("src/app/routes.ts", "utf8");
const dataPreload = fs.readFileSync("src/app/routeDataPreload.ts", "utf8");
const layout = fs.readFileSync("src/app/components/Layout.tsx", "utf8");
const apiClient = fs.readFileSync("src/app/services/apiClient.ts", "utf8");
const metricApi = fs.readFileSync("src/app/services/metricDictionaryApi.ts", "utf8");
const visualCards = fs.readFileSync("src/app/components/visual-report/VisualReportCards.tsx", "utf8");
const visualBuilder = fs.readFileSync("src/app/components/VisualReportBuilder.tsx", "utf8");
const analysisConfig = fs.readFileSync("src/app/components/AnalysisConfigManager.tsx", "utf8");
const workspace = fs.readFileSync("src/app/components/DataAgentWorkspace.tsx", "utf8");
const settings = fs.readFileSync("src/app/components/SystemSettings.tsx", "utf8");
const automationApi = fs.readFileSync("src/app/services/automationApi.ts", "utf8");
const capabilitiesApi = fs.readFileSync("src/app/services/capabilitiesApi.ts", "utf8");
const accessApi = fs.readFileSync("src/app/services/accessControlApi.ts", "utf8");
const dataAssetApi = fs.readFileSync("src/app/services/dataAssetApi.ts", "utf8");
const dashboard = fs.readFileSync("src/app/components/Dashboard.tsx", "utf8");
const dataPageSelector = fs.readFileSync("src/app/components/ui/DataPageSelector.tsx", "utf8");

const checks = [
  [preload.includes("warmVisibleRoutePaths"), "可见页面必须支持空闲预热"],
  [preload.includes("requestIdleCallback") && preload.includes("setTimeout(runNext, 180)"), "预热必须优先使用空闲调度并提供兼容回退"],
  [preload.includes("pendingLoaders.shift()") && preload.includes("finally(scheduleNext)"), "页面模块必须逐个预热，避免并发抢占主线程"],
  [preload.includes("routeLoaderPromises"), "悬停、聚焦和空闲预热必须复用同一个模块请求"],
  [preload.includes("prepareRoutePath") && preload.includes("prepareRouteLoader(loader)") && preload.includes("options.navigationIntent"), "菜单点击必须能够等待目标模块准备完成后再提交路由"],
  [routes.includes("preparedNamed(routeLoaders.") && routes.includes("readPreparedRouteModule(loader)"), "菜单预加载与路由渲染必须共享同一模块缓存，避免提交路由后再次闪现全页骨架"],
  [routes.includes('preparedNamed(routeLoaders.layout, "Layout", false)') && routes.includes("if (clearRetryOnSuccess) clearRouteImportRetry()"), "外层布局成功不得提前清除叶子页面的动态导入重试保护，避免失败模块反复整页刷新"],
  [preload.includes("preparedNavigationFailures") && routes.includes("consumePreparedNavigationFailure(loader)"), "菜单目标模块准备失败必须直接进入既有路由错误边界，不得触发整页刷新循环"],
  [routes.includes("let terminalError: unknown = null") && routes.includes("if (terminalError) throw terminalError"), "动态模块最终失败必须同步交给路由错误边界，不得以重复拒绝的 Promise 永久停留在骨架态"],
  [routes.includes('data-route-fallback-indicator": "compact"') && !routes.includes('className: "h-5 w-36 rounded bg-[#e9e9ed]"'), "直接加载的兜底状态必须使用紧凑指示器，不得再显示易被误认为顶部滚动条的横向脉冲条"],
  [["/funnel", "/sandbox", "/email-daily", "/customer-segment-analysis", "/bridge-authorize"].every((path) => preload.includes(path)), "全部直接页面入口必须纳入目标模块准备映射"],
  [preload.includes("nearbyLoaders") && preload.includes("crossGroupDelayComplete") && preload.includes("window.setTimeout(scheduleNext, 1_200)"), "空闲预热必须先处理当前菜单组并延后跨组模块，避免与即时点击争抢资源"],
  [preload.includes("cancelIdleCallback") && preload.includes("clearTimeout"), "页面卸载或路由变化必须取消未开始的预热"],
  [preload.includes('path !== currentPath'), "当前已加载页面不得重复进入预热队列"],
  [preload.includes("routeWarmGroup") && preload.includes('return "self-analysis"'), "空闲预热必须优先当前菜单分组并保持全站回退"],
  [preload.includes('path === "/dashboard"'), "多机构分析一级入口必须纳入统一预热映射"],
  [preload.includes('path.startsWith("/agent/message-board")'), "留言板页面必须纳入统一预热映射"],
  [layout.includes('navigationStatus !== "ready"'), "权限导航未就绪时不得启动页面预热"],
  [layout.includes("sda-navigation-keys-v1") && layout.includes("isSuperAdmin") && layout.includes("optimisticKeys"), "登录后必须用超级管理员全菜单或会话缓存立刻渲染，不得清空菜单再白屏等待导航"],
  [layout.includes('data-navigation-loading="true"'), "无缓存时权限加载必须显示局部加载态而不是空白主栏"],
  [dataAssetApi.includes("timeoutMs: 30_000") && dataAssetApi.includes("/api/data-assets/table-relationships/catalog"), "表关系目录必须使用长于默认读请求的超时"],
  [layout.includes("visibleMenuItems.flatMap"), "只能预热当前用户可见的页面"],
  [layout.includes("cancelCodeWarmup = warmVisibleRoutePaths(visiblePaths, location.pathname)") && layout.includes("cancelCodeWarmup();"), "路由变化必须清理并重建剩余预热队列"],
  [(layout.match(/preloadRoutePath\(/g) || []).length >= 4, "一级和二级页面入口都必须保留悬停和聚焦即时预热"],
  [(layout.match(/preloadRouteDataPath\(/g) || []).length >= 4, "一级和二级页面入口必须按目标页预取业务数据"],
  [(layout.match(/onPointerDown=/g) || []).length >= 2, "鼠标与触屏点击必须在路由提交前启动代码和数据预取"],
  [layout.includes("routeWarmupCancelRef") && layout.includes("prepareMenuRoute") && layout.includes("routeWarmupCancelRef.current()"), "真实菜单意图必须取消未开始的后台预热，仅保留目标模块和数据准备"],
  [layout.includes("navigatePreparedMenuRoute") && layout.includes("await prepareRoutePath(path, { navigationIntent: true })") && layout.includes("event.preventDefault()") && layout.includes("startTransition(() => { void navigate(path); })"), "菜单必须保持当前页面直到目标代码就绪，再用非阻塞过渡提交原路由"],
  [layout.includes('data-menu-route-pending="true"') && layout.includes("pendingRoutePath === child.path") && layout.includes("pendingRoutePath === item.path"), "等待目标模块时必须在被点击菜单内提供紧凑即时反馈，不得用页面顶部骨架替代"],
  [layout.includes("event.metaKey") && layout.includes("event.ctrlKey") && layout.includes("event.shiftKey") && layout.includes("event.altKey"), "新标签页和组合键点击必须保留浏览器原生导航语义"],
  [!preload.includes("fetch("), "路由预热不得触发业务 API"],
  [dataPreload.includes("Promise.allSettled") && dataPreload.includes("routeDataTasks"), "数据预取必须失败隔离且按页面收敛依赖"],
  [dataPreload.match(/path\.startsWith\("\/self-analysis\/config"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.match(/fetchDataAssets/g)?.length === 2 && dataPreload.includes('scope: "knowledge"'), "分析配置必须预取目录与知识投影并复用服务缓存"],
  [dataPreload.match(/path\.startsWith\("\/agent\/skills"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes('scope: "knowledge"') === true, "Skill 插件必须只预取知识投影"],
  [dataPreload.match(/path\.startsWith\("\/data-assets\/tools"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchMetricDictionary") === false, "工具调用不得预取未使用的指标字典"],
  [dataPreload.match(/path\.startsWith\("\/data-assets\/metrics"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchMetricDictionary") === true && dataPreload.match(/path\.startsWith\("\/data-assets\/metrics"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchDataAssets") === false, "指标字典只预取指标，不得拖入完整资产目录"],
  [dataPreload.match(/path\.startsWith\("\/data-assets\/knowledge"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes('scope: "knowledge"') === true && dataPreload.match(/path\.startsWith\("\/data-assets\/knowledge"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchMetricDictionary") === false, "知识记忆必须只预取知识投影"],
  [dataPreload.match(/path\.startsWith\("\/data-assets\/quality"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchDataAssets") === false && dataPreload.includes('path.startsWith("/data-assets/quality")'), "质量监测不得预取资产目录和指标字典"],
  [dataPreload.match(/path\.startsWith\("\/data-assets\/"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchMetricDictionary") === false, "数据管理悬停不得预取未使用的指标字典"],
  [dataPreload.match(/path\.startsWith\("\/agent\/tasks"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchPlatformCapabilities") === true && dataPreload.includes("fetchAutomationWorkspace"), "自动化任务必须预取真实任务与能力依赖"],
  [dataPreload.match(/path\.startsWith\("\/agent\/tasks"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchDataAssets") === false && dataPreload.match(/path\.startsWith\("\/agent\/tasks"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchMetricDictionary") === false, "自动化任务悬停不得用资产目录和指标字典抢占任务列表"],
  [dataPreload.includes('path.startsWith("/agent/message-board")') && dataPreload.includes("fetchMessageBoardAdmin"), "留言板管理必须预取当前机构首屏列表"],
  [dataPreload.match(/path\.startsWith\("\/self-analysis\/query"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchAnalysisRuntimeConfig") === true, "智能分析必须预取账号分析模型运行时配置"],
  [automationApi.includes('tags: ["automation-workspace"]') && capabilitiesApi.includes('tags: ["platform-capabilities"]'), "任务与能力读取必须短缓存并合并预取和挂载请求"],
  [workspace.includes('if (activeTab !== "tasks") return;'), "待办页面不得加载自动化任务专属目录"],
  [workspace.includes('data-agent-task-card={task.id}') && workspace.includes('className="overflow-hidden rounded-lg bg-[#fafbfc]"') && workspace.includes('<Eye className="h-3.5 w-3.5" />') && workspace.includes('<Pencil className="h-3.5 w-3.5" />') && workspace.includes('<Trash2 className="h-3.5 w-3.5" />') && !workspace.includes("rounded-xl border border-[#f0f0f2] bg-white p-5 transition-colors hover:border-[#d1d1d6]"), "自动化任务必须使用与其他页面一致的窄条列表，并在右侧提供查改删图标"],
  [dataPreload.includes('/settings/config') && dataPreload.includes('/settings/users') && dataPreload.includes('/settings/audit'), "系统管理必须按子页预取精确依赖"],
  [settings.includes('if (activeTab !== "config") return;') && settings.includes('activeTab !== "users" && activeTab !== "roles"'), "系统管理挂载不得读取其他 Tab 数据"],
  [settings.includes('data-user-role-summary="true"') && settings.includes('data-user-role-tooltip="true"') && settings.includes("truncate whitespace-nowrap"), "用户管理角色列必须单行省略并在多角色悬停时展示全部"],
  [settings.includes("useDeferredValue") && settings.includes("useClientPagination(filteredUsers, 20)") && settings.includes('ariaLabel="用户列表分页"'), "用户列表必须延迟过滤并限制单页节点数，避免大数据输入和删除阻塞主线程"],
  [settings.includes("stableOpenModelOptions") && settings.includes('data-model-option-order="stable-open"') && settings.includes('overflowAnchor: "none"'), "模型勾选在本次弹窗打开期间必须保持原位置并关闭滚动锚定"],
  [settings.includes('className={`flex h-9 shrink-0 items-center overflow-hidden') && settings.includes('aria-live="polite"'), "模型操作状态栏必须预留固定高度，避免保存提示引起文字跳动"],
  [!settings.includes("forceRefresh: true"), "模型新增和勾选保存后不得冗余全量回读系统配置"],
  [dataPageSelector.includes("const safePage = Math.max(1, Math.min(page, totalPages))") && dataPageSelector.includes("items.slice((safePage - 1) * pageSize"), "删除分页末项时必须同步使用有效页，不能短暂闪现空列表再跳页"],
  [accessApi.match(/readCache:/g)?.length === 2, "用户与角色读取必须短缓存并在写入后统一失效"],
  [dataPreload.includes('/self-analysis/reports') && dataPreload.includes("fetchVisualReports") && dataPreload.includes("fetchSavedAnalysisResults"), "我的报表必须预取两类首屏报表配置"],
  [dataPreload.match(/path\.startsWith\("\/self-analysis\/reports"\)[\s\S]*?return \[([\s\S]*?)\];/)?.[1]?.includes("fetchDataAssets") === false, "我的报表悬停预取不得用大目录抢占首屏列表"],
  [apiClient.includes("apiReadInflight") && apiClient.includes("apiReadCacheKey"), "共享读取层必须合并并发请求并按上下文生成缓存键"],
  [apiClient.includes("context?.tenantId") && apiClient.includes("context?.userId"), "缓存键必须隔离租户和用户"],
  [apiClient.includes("method !== \"GET\"") && apiClient.includes("clearApiReadCache"), "成功写操作必须让读取缓存失效"],
  [apiClient.includes("apiReadCacheGeneration") && apiClient.includes("apiReadInflight.clear()"), "写操作后旧并发读取不得重新写回缓存"],
  [apiClient.includes("sessionRefreshRequest") && apiClient.includes("refreshSessionOnce"), "并发 401 必须合并为一次会话刷新，避免旋转 refresh token 互相失效"],
  [visualCards.includes('data-visual-report-data-loading="true"') && visualCards.includes("!rows.length && !errorsByDataset[card.dataset.id]"), "真实数据投影完成前不得把标准图表挂载为空态"],
  [dataPreload.includes('fetchPageDataWorkspace({ tenantId, userId, pageCode: "dashboard" })') && dataPreload.includes('pageCode: "weekly_report"') && dataPreload.includes('pageCode: "institution_supervision"'), "经营页必须预取页面数据工作区而不是整包资产目录"],
  [layout.includes('preloadRouteDataPath("/dashboard", { tenantId, userId })') && layout.includes('visiblePaths.includes("/dashboard")') && layout.includes("requestIdleCallback(warmDashboardData"), "多机构分析工作区必须在授权导航空闲时提前准备"],
  [dataAssetApi.includes('return `${tenantId}:${userId}:${pageCode}`') && dataAssetApi.includes("pageDataWorkspaceMemoryKey(tenantId, userId, pageCode)"), "页面工作区内存必须同时隔离租户、用户与页面"],
  [!dataAssetApi.match(/page-data-workspace:\$\{pageCode\}`\][^\n]*forceRefresh/), "工作区预取与页面挂载不得被强制刷新拆成重复请求"],
  [!dashboard.includes("fetchOperatingSnapshot") && !dashboard.includes("buildDashboardModel"), "多机构页面不得并行加载已退出展示主链的旧经营快照"],
  [visualCards.includes("speculative") || visualCards.includes("Promise.all(report.cards.map"), "可视化报表必须与目录并行拉取已知数据集，不得等目录完成后再串行读数"],
  [visualBuilder.includes("reportLoading") && visualBuilder.includes("catalogLoading"), "报表框架与数据目录必须渐进加载"],
  [visualBuilder.includes('if (view !== "editor" || catalogLoadedRef.current) return;') && visualBuilder.indexOf("fetchVisualReports({ tenantId, userId })") < visualBuilder.indexOf('fetchDataAssets({ tenantId, userId, scope: "visualization" })'), "可视化报表落地页必须仅读取报表骨架，进入编辑器后再准备专用目录"],
  [visualCards.includes('scope: "visualization"') && !visualCards.includes('scope: "runtime"'), "可视化报表回读必须使用单一瘦目录请求"],
  [visualBuilder.includes("h-[min(88vh,900px)]") && visualBuilder.includes("shrink-0") && visualBuilder.includes("overflow-hidden"), "图表弹窗必须固定可视高度并隔离内容滚动与操作栏"],
  [analysisConfig.includes('aria-label="正在读取分析配置"') && analysisConfig.includes("!loading && !shortcuts.length"), "分析配置冷启动必须显示局部骨架且不得闪现假空态"],
  [metricApi.includes("importMetricDictionaryWorkbook") && metricApi.includes("timeoutMs: 60_000"), "指标批量导入必须使用长于默认读请求的超时"],
];

const failed = checks.filter(([passed]) => !passed);
for (const [passed, label] of checks) console.log(`${passed ? "PASS" : "FAIL"} ${label}`);
if (failed.length) process.exit(1);
