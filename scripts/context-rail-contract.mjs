import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), "utf8");
const rail = read("src/app/components/context-rail/ContextSideRail.tsx");
const weeklyRail = read("src/app/components/weekly-report/WeeklyReportSideRail.tsx");
const analysis = read("src/app/components/weekly-report/ContextAnalysisPanel.tsx");
const progress = read("src/app/components/self-analysis/AnalysisProgressPanel.tsx");
const weekly = read("src/app/components/WeeklyReport.tsx");
const dashboard = read("src/app/components/Dashboard.tsx");
const layout = read("src/app/components/Layout.tsx");
const comments = read("src/app/components/weekly-report/CommentsPanel.tsx");
const commentDomain = read("src/app/components/weekly-report/domain.ts");
const selectable = read("src/app/components/weekly-report/SelectableRegion.tsx");
const annotationText = read("src/app/components/weekly-report/AnnotationText.tsx");
const institutionComments = read("src/app/components/context-rail/useInstitutionCommentThread.ts");
const domain = read("src/app/components/weekly-report/domain.ts");
const routes = read("src/app/routes.ts");
const routeError = read("src/app/components/RouteErrorPage.tsx");
const supervisor = read("src/app/components/agent-supervisor/AgentSupervisor.tsx");
const workspacePanel = read("src/app/components/analysis-workspace/AnalysisWorkspaceRail.tsx");
const funnel = read("src/app/components/BusinessFunnel.tsx");
const sandbox = read("src/app/components/BusinessSandbox.tsx");
const supervision = read("src/app/components/InstitutionSupervision.tsx");
const customers = read("src/app/components/CustomerInsight.tsx");
const competition = read("src/app/components/CompetitionAnalysis.tsx");
const emailDaily = read("src/app/components/EmailDailyReport.tsx");
const selfAnalysis = read("src/app/components/SelfAnalysis.tsx");
const selfAnalysisWorkspace = read("src/app/components/self-analysis/workspaceContext.ts");
const resultViews = read("src/app/components/self-analysis/ResultViews.tsx");
const visualFollowUp = read("src/app/components/self-analysis/visualFollowUp.ts");
const globalRail = read("src/app/components/context-rail/GlobalContextRail.tsx");
const visualVoice = read("src/app/components/visualization/useVisualizationVoiceCommand.ts");
const visualCommand = read("src/app/components/visualization/visualizationCommand.ts");
const messageBoard = read("src/app/components/message-board/MessageBoardPanel.tsx");
const messageBoardAdmin = read("src/app/components/MessageBoardManagement.tsx");
const messageBoardApi = read("src/app/services/messageBoardApi.ts");
const messageBoardService = read("backend/platform/message_board/service.py");
const dataAgentWorkspace = read("src/app/components/DataAgentWorkspace.tsx");
const globalMessageBoard = read("src/app/components/message-board/GlobalMessageBoardShortcut.tsx");
const messageBoardDraftStore = read("src/app/components/message-board/messageBoardDraftStore.ts");
const messageBoardGallery = read("src/app/components/message-board/MessageBoardAttachmentGallery.tsx");
const dataAssets = read("src/app/components/DataAssets.tsx");
const systemSettings = read("src/app/components/SystemSettings.tsx");
const settingsRoutes = read("backend/platform/api/routes/settings.py");
const asrRoutes = read("backend/platform/api/routes/asr.py");
const analysisApi = read("src/app/services/analysisApi.ts");
const metricRoutes = read("backend/platform/api/routes/metrics.py");
const csvFolder = read("backend/platform/ingestion/csv_folder.py");
const pendingAnalysis = read("src/app/components/self-analysis/pendingAnalysisRun.ts");
const pageData = read("src/app/components/page-data/PageDataComposer.tsx");
const analysisRoute = read("backend/platform/api/routes/analysis.py");
const workflow = read("backend/platform/orchestration/workflow.py");
const theme = read("src/styles/theme.css");

const checks = [
  [rail.includes('data-context-rail-collapse="true"'), "右栏必须保留整体收起入口"],
  [rail.includes("useState(true)") && !rail.includes("smart_data_agent_context_rail_collapsed"), "右栏每次进入页面必须默认折叠，不得被旧本地状态强制展开"],
  [rail.includes('data-context-rail-edge-zone="true"') && rail.includes("pointer-events-none fixed bottom-0 right-0 top-0"), "收起后必须保留右边缘悬浮感应区，且感应区不得挡住页面滚动条拖动"],
  [rail.includes('style={{ top: "50%" }}') && !rail.includes("setEdgeY") && !rail.includes("clientY"), "右侧边缘展开按钮必须固定在垂直中线，不得随鼠标移动"],
  [rail.includes("pointermove") && rail.includes("fromRight") && rail.includes("innerWidth - event.clientX"), "右栏展开按钮仍须在靠近右边缘时出现，但不能靠全高热区截获滚动条指针"],
  [rail.includes("contextRailRevealEvent") && rail.includes("setCollapsed(false)") && rail.includes("onTabChange(detail.tab)"), "点击页面标注时必须自动展开右栏并切换到对应评论或 AI 页签"],
  [rail.includes('data-context-rail-scroll="true"') && rail.includes("flex min-h-0 flex-1 flex-col overflow-hidden") && comments.includes("overflow-y-auto") && messageBoard.includes("overflow-y-auto") && workspacePanel.includes("overflow-y-auto"), "右栏必须用独立纵向滚动区，页签和输入框不得进入滚动层"],
  [rail.includes('activeTab === "comments" ? "flex h-full min-h-0 flex-1 flex-col overflow-hidden" : "hidden"') && rail.includes('activeTab === "analysis" ? "flex h-full min-h-0 flex-1 flex-col overflow-hidden" : "hidden"') && rail.includes('activeTab === "message-board" ? "flex h-full min-h-0 flex-1 flex-col overflow-hidden" : "hidden"'), "评论和 AI 标签切换不得卸载内部状态"],
  [rail.includes('data-context-rail-tabs="true"') && rail.includes("shrink-0") && !rail.includes("top-[57px]") && rail.includes("visualViewport"), "右栏页签必须固定在顶栏，高度跟随 visualViewport，不得被绝对定位内容盖住"],
  [comments.includes('data-comments-composer="true"') && messageBoard.includes('data-message-board-composer="true"') && workspacePanel.includes('data-analysis-workspace-composer="true"'), "评论、留言板和 AI 分析输入区必须钉在右栏底部"],
  [weekly.includes('data-weekly-report-toolbar="true"') && weekly.indexOf('data-weekly-report-toolbar="true"') > weekly.indexOf('data-context-page-body="weekly-report"'), "周报工具栏必须留在正文列，不得盖住右栏页签"],
  [analysis.includes("本页面没有找到这一数据，请检查要分析的内容"), "缺少请求数据时必须使用产品指定提示"],
  [analysis.includes("实时语音交互") && !analysis.includes('disabled={!target}'), "无选区总体分析也必须允许实时语音"],
  [analysis.includes("voiceStartupErrorMessage") && analysis.includes("Data Agent API 暂时不可用") && analysis.includes("重新连接"), "语音启动失败必须使用场景化提示并提供重新连接入口"],
  [analysis.includes('data-context-analysis-collapsed={collapsed ? "true" : "false"}') && analysis.includes('aria-label="已完成"') && analysis.includes("onClick={onComplete}") && !analysis.includes("setCompleted"), "AI 卡片必须支持折叠，点击已完成后直接关闭且不得切换为恢复状态"],
  [analysis.includes("<AnalysisProgressPanel embedded") && !analysis.includes('overflow-x-auto rounded-lg border border-[#ececf0]') && !analysis.includes('h-[260px] w-full rounded-lg border border-[#ececf0]'), "AI 结果四个页签内部不得重复嵌套边框"],
  [analysis.includes('data-context-analysis-input="true"') && analysis.includes('className="bg-transparent px-0.5"') && analysis.includes('className="-mx-3 -mb-3 overflow-hidden border-t') && !analysis.includes('rounded-xl border border-[#e5e5ea] bg-[#fafbfc] p-2.5'), "AI 输入与分析结果必须共用分析卡最外层边框，不得各自嵌套卡片边框"],
  [progress.includes("{!embedded && (") && progress.includes('embedded ? "overflow-hidden bg-transparent"') && !analysis.includes("{chart.title}") && !analysis.includes("whitespace-pre-wrap rounded-lg bg") && !analysis.includes("items-center justify-center rounded-lg bg"), "AI 结果四个页签必须直接呈现内容，不得保留内部标题栏或卡片层"],
  [selectable.includes("captureTextSelection") && selectable.includes("selection:bg-[#dce9ff]") && selectable.includes("onOpenAnalysis(actionTarget)"), "多机构分析选中文字后必须把真实选区传给 AI 分析"],
  [selectable.includes('event.target.closest("[data-comment-selection-action], [data-analysis-selection-action]")') && selectable.indexOf('event.target.closest("[data-comment-selection-action], [data-analysis-selection-action]")') < selectable.indexOf("action.setPointerCapture(event.pointerId)"), "评论和 AI 悬浮按钮必须在拖动指针捕获前退出，保证真实点击回调可达"],
  [selectable.includes("AnalysisUnderlineProvider") && selectable.includes("data-analysis-annotation") && selectable.includes("border-[#ff3b30]"), "AI 选区必须持久渲染为红色可点击下划线"],
  [annotationText.includes('annotationKind === "analysis"') && annotationText.includes("border-[#ff3b30]") && annotationText.includes("border-[#1a73e8]"), "经营周报 AI 与评论文字标注必须分别使用红色和蓝色下划线"],
  [selectable.includes('data-comment-annotation') && selectable.includes('data-annotation-kind') && selectable.includes("border-[#1a73e8] bg-[#eef4ff]") && selectable.includes("border-[#ff3b30] bg-[#fff1f0]"), "多机构分析评论与 AI 文字标注必须使用不同的下划线和阴影底色"],
  [![selectable, annotationText].some((source) => ["#6d28d9", "#8b5cf6", "#ede9fe", "#f5f3ff", "#7c3aed"].some((color) => source.includes(color))), "AI 文字标注不得残留旧紫色样式"],
  [weekly.includes("analysisSelectionTargets") && weekly.includes('annotationKind: "analysis"') && weekly.includes("activateTextAnnotation"), "经营周报必须持久保存 AI 文字选区并支持点击反向激活"],
  [weeklyRail.includes("<AnalysisWorkspacePanel revealedDataPoint={selectedDataPoint}") && weeklyRail.includes("selected_content") && !weeklyRail.includes("页面分析") && !weeklyRail.includes("分析线程"), "周报与多机构分析必须复用唯一 AI 分析工作区，并只注入当前选中内容"],
  [dashboard.includes("AnalysisUnderlineProvider") && dashboard.includes("analysisSelectionTargets") && dashboard.includes("activateDashboardAnalysis"), "多机构分析必须持久保存 AI 文字选区并支持点击反向激活"],
  [dashboard.includes("dashboardCommentAnnotations") && dashboard.includes("activateDashboardAnnotation") && dashboard.includes('revealContextRail("multi-institution-analysis", "comments")'), "多机构分析评论标注必须支持点击后展开右栏、激活对应评论并双向高亮"],
  [weekly.includes('revealContextRail("weekly-report", "comments")') && weekly.includes('revealContextRail("weekly-report", "analysis")') && weekly.includes("draftAnnotations"), "经营周报评论和 AI 标注必须支持折叠态反向展开，评论草稿也必须保留蓝色标注"],
  [dashboard.includes("useInstitutionCommentThread") && institutionComments.includes("fetchReportComments({ tenantId, userId, reportId })") && institutionComments.includes("createReportComment") && institutionComments.includes('action: "reply"'), "多机构分析评论必须使用机构共享的后端评论线程并允许同机构用户追评"],
  [institutionComments.includes("scopeKey = `${tenantId}:${userId}:${reportId}`") && institutionComments.includes("scopeKeyRef.current !== mutationScope"), "评论异步回写必须防止用户或机构切换后污染新权限域"],
  [analysis.includes("if (!target?.selectedText?.trim()) window.setTimeout") && domain.includes("makeAnalysisSelectionTarget"), "选中文字打开 AI 分析时不得由输入框抢走焦点，且不同文字选区必须生成独立分析目标"],
  [analysis.includes('data-context-analysis-body="true"') && analysis.includes("setCollapsed((value) => !value)"), "AI 分析卡折叠按钮必须控制输入框和结果主体"],
  [progress.includes('data-analysis-progress-scroll="manual"') && !progress.includes("scrollTo({ top: element.scrollHeight"), "思考链必须由用户手动滚动，不得在运行时强制滚到底部"],
  [weekly.includes('pageKey="weekly-report"') && weekly.includes("xl:grid-cols-[minmax(0,1fr)_auto]"), "经营周报必须接入共享右栏并允许整体收起"],
  [dashboard.includes('pageKey="multi-institution-analysis"') && dashboard.includes("SelectableRegion"), "多机构分析必须接入共享右栏和选区操作"],
  [dashboard.includes(">多机构分析</h2>") && layout.includes('label: "多机构分析"'), "页面标题和导航必须统一为多机构分析"],
  [comments.includes('data-comments-empty-state="true"') && !comments.includes('xl:top-[96px]'), "暂无评论提示必须直接衔接在评论页签下方"],
  [comments.includes('data-comments-new="true"') && comments.includes("新增评论") && comments.includes('data-comments-new-editor="true"') && comments.includes('data-comments-new-input="true"') && comments.includes('data-comments-new-save="true"') && comments.includes("[composerScopeKey]"), "评论页签必须提供同留言板风格的新增评论入口和紧凑编辑器，切换权限域时清空草稿"],
  [commentDomain.includes("makePageCommentTarget") && dashboard.includes('onCreateComment: createDashboardPageComment') && weekly.includes("onCreateComment: addPageComment") && globalRail.includes("onCreateComment={createPageComment}"), "新增评论必须复用现有机构评论线程并绑定当前页面目标"],
  [comments.includes("readableContextText") && domain.includes("JSON.parse(normalized)") && domain.includes("summarizeContextValue"), "评论引用内容必须把历史 JSON 转换为可读中文摘要，不得直接显示序列化数据"],
  [comments.includes("let nextTop = startTop") && comments.includes("const displayTop = nextTop") && !comments.includes(".sort((a, b) => a.anchorTop - b.anchorTop)"), "评论卡必须从顶部开始按列表顺序自上而下排列，不得按正文锚点制造大段空白"],
  [comments.includes("activeDraftId || activeCommentId") && comments.includes("scroller.scrollTo") && comments.includes("CSS.escape(entryId)"), "点击评论标注后右栏必须自动滚动定位到对应评论或草稿"],
  [comments.includes("formatCommentTimestamp(comment.time)") && comments.includes("formatCommentTimestamp(reply.time)") && comments.includes('return `${year}-${month}-${day} ${hour}:${minute}:${second}`'), "评论和追评时间必须只显示年月日与时分秒，不得暴露毫秒或时区信息"],
  [layout.includes('data-agent-sidebar-expand-zone="true"') && layout.includes('style={{ top: "50%" }}') && !layout.includes("setSidebarEdgeY") && !layout.includes("clientY") && layout.includes("sidebarEdgeVisible"), "左侧菜单折叠后必须在整条左边缘显示居中稳定的展开按钮"],
  [theme.includes("--sda-shell-edge-gap: 0.4cm") && theme.includes('[data-agent-main-shell="true"] > *') && theme.includes("padding-top: var(--sda-shell-edge-gap) !important") && theme.includes("padding-right: var(--sda-shell-edge-gap) !important"), "全局页面顶部和右侧外边距必须统一为 0.4cm"],
  [theme.includes('[data-agent-main-shell="true"]') && theme.includes("padding-top: 0") && theme.includes("padding-right: 0") && layout.includes('data-agent-sidebar-header="true"'), "主滚动容器不得自带顶部或右侧内边距，避免滚动条右侧出现空隙"],
  [theme.includes("scrollbar-gutter: auto") && !theme.includes("scrollbar-gutter: stable"), "文档不得为主工作区已经独立拥有的滚动条重复预留右侧空槽"],
  [dashboard.includes("pageData.visibleAssets.map") && dashboard.includes("rowCount: pageData.rowsById[asset.id]?.row_count") && !dashboard.includes("JSON.stringify(p.kpis)"), "多机构分析的指标、图表和表格评论目标必须使用页面数据摘要，不得生成旧快照 JSON 乱码"],
  [routes.includes("canSafelyReloadRouteImport") && routes.includes("routeImportRetryKey") && routes.includes("errorElement: createElement(RouteErrorPage)"), "动态页面模块失效时必须限制自动重载次数并提供路由错误边界"],
  [routeError.includes('data-route-error="true"') && routeError.includes("重新加载页面") && routeError.includes("返回智能分析"), "路由异常不得显示默认英文白屏，必须提供系统风格恢复操作"],
  [layout.includes("<AgentSupervisor />") && layout.includes("<GlobalContextRail />") && globalRail.includes("<AnalysisWorkspacePanel revealedDataPoint={selectedDataPoint}"), "页面必须保留总管对话入口，并把分析线程迁入统一右栏"],
  [!supervisor.includes("分析线程") && !supervisor.includes("AnalysisWorkspacePanel") && !supervisor.includes("analysisWorkspaceRevealEvent"), "小机器人不得继续承载重复的分析线程入口"],
  [supervisor.includes("chatWithAgentSupervisor") && supervisor.includes("readPersistedTextModelSelection") && supervisor.includes("isExplicitAnalysisQuestion") && supervisor.includes("data-supervisor-pending"), "Agent 总管闲聊必须走当前所选文本模型，并显示等待状态，不得把寒暄丢进默认 loan_amount 分析流水线"],
  [resultViews.includes('data-visual-filter-value-menu], [data-visual-filter-value-trigger]') && resultViews.includes('data-visual-filter-value-menu="true" data-visual-filter-panel="true"'), "可视化条件值菜单必须排除在图表外点击关闭之外，避免选值时整个条件弹窗闪退"],
  [resultViews.includes('data-visual-filter-toggle') && !resultViews.includes(">条件{activeFilterCount") && resultViews.includes("applyFilterState") && resultViews.includes("filterSnapshotRef"), "条件只能出现在更多菜单中，选值后即时筛选，取消时恢复原条件"],
  [supervisor.includes("data-supervisor-model") && supervisor.includes("textModelSelectionEvent") && !supervisor.includes("AGENT WORKSPACE") && !supervisor.includes("左下角切换后") && !supervisor.includes("未选择文本模型"), "Agent 总管跟随左下角当前文本模型，且不得展示工作区标签、路径副标题和模型说明文案"],
  [globalRail.includes("analysisWorkspaceRevealEvent") && globalRail.includes('setActiveTab("analysis")') && globalRail.includes("contextRailRevealEvent"), "图表或数据点追问必须携带锚点展开统一右栏并进入 AI 分析"],
  [globalRail.includes('"/dashboard": { pageKey: "multi-institution-analysis"') && globalRail.includes("commentTargetFromRailReveal") && globalRail.includes('detail.tab === "comments"'), "多机构分析必须接入全局右栏，追问和图表评论都要展开并生成评论草稿"],
  [globalRail.includes('"/customer-segment-analysis": { pageKey: "customer-segment-analysis"') && workspacePanel.includes('"/customer-segment-analysis": { pageKey: "customer-segment-analysis"'), "分客群分析必须接入统一评论与 AI 分析右栏"],
  [!globalRail.includes('"/data-assets/metrics"') && !workspacePanel.includes('"/data-assets/metrics"') && !globalRail.includes("metric-management") && !workspacePanel.includes("metric-management"), "指标管理不得接入评论、留言板或 AI 分析右栏"],
  [workspacePanel.includes('"/dashboard": { pageKey: "multi-institution-analysis"') && dashboard.includes('updateAnalysisWorkspacePageContext("multi-institution-analysis"'), "多机构分析追问必须登记分析工作区并发布当前页面数据上下文"],
  [weekly.includes("contextRailRevealEvent") && weekly.includes("commentTargetFromRailReveal") && weekly.includes('detail.tab === "comments"') && weekly.includes("setDraftTargets"), "经营周报图表评论必须根据右栏展开事件创建可提交草稿，不得只打开空评论页"],
  [workspacePanel.includes('data-global-analysis-wide-toggle="true"') && !workspacePanel.includes("服务端持久化 · 分支历史不覆盖") && !workspacePanel.includes("输入问题后，本轮问题、规划、结论和证据会写入当前线程"), "AI 分析必须只保留一个线程 Tab 头并移除重复标题说明"],
  [workspacePanel.includes('data-analysis-workspace-composer="true"') && workspacePanel.includes('data-workspace-transcript="true"') && workspacePanel.includes("min-h-0 flex-1 overflow-y-auto") && weeklyRail.includes('className="flex h-full min-h-0 flex-col overflow-hidden"') && globalRail.includes('className="flex h-full min-h-0 flex-col overflow-hidden"') && rail.includes("data-context-rail-flush") && rail.includes("flushToViewport") && rail.includes("fixed top-4 right-0 bottom-0") && globalRail.includes("flushToViewport") && !rail.includes("orbClearancePx") && !rail.includes("mr-20") && !globalRail.includes("pb-24") && !globalRail.includes("pr-4") && rail.includes("border-b-0 border-r-0") && workspacePanel.includes('data-analysis-branch-create="true"') && workspacePanel.includes("visibleThreads.filter((thread) => thread.parent_thread_id") && !workspacePanel.includes(">新建分支</button>"), "右栏必须贴齐浏览器右边缘和下边缘，输入框贴在右栏底部，且合并选项不得列出被去重的重复线程"],
  [supervisor.includes("clampOrbOffset") && supervisor.includes("orbSectorRadiusCm") && supervisor.includes("setPointerCapture") && supervisor.includes('data-agent-supervisor-orb="true"') && !supervisor.includes("absolute bottom-6 right-6"), "小机器人必须可拖动，且移动范围限制在系统右下角 5cm 扇形内"],
  [workspacePanel.includes("createAnalysisBranch") && workspacePanel.includes("mergeAnalysisThreads") && workspacePanel.includes("TrustedArtifactPanel") && workspacePanel.includes("waitForSelfAnalysis") && workspacePanel.includes('resultDelivery: "planned_analysis"') && workspacePanel.includes('resultFormat: "concise_visual"') && workspacePanel.includes("WorkspaceFollowUpChart") && workspacePanel.includes("data-workspace-follow-up-thinking"), "融合后必须保留追问、分支、合并和可信证据能力，右栏追问要走唯一规划运行时并展示思考链、聚焦图和短结论"],
  [workspacePanel.indexOf('...objectValue(effectivePageContext.analysis_policy)') < workspacePanel.indexOf('resultDelivery: "planned_analysis"') && workspacePanel.includes('engine: "IntelligentAnalysisEngine"'), "页面遗留策略不得覆盖右栏唯一 IntelligentAnalysisEngine 规划主链"],
  [workspacePanel.includes('data-analysis-popup-voice="true"') && workspacePanel.includes('data-analysis-realtime-voice="true"') && workspacePanel.includes('applicationModule: "popup_voice_input"') && workspacePanel.includes('applicationModule: "realtime_voice_input"') && workspacePanel.includes("silenceMs: 1_000"), "AI 分析右栏的语音录入与实时语音必须复用模型应用配置，并在静默一秒后提交文本分析主链"],
  [workspacePanel.includes("parseNewChatCommand") && workspacePanel.includes("nextRootThreadTitle") && workspacePanel.includes("/new") && workspacePanel.includes("parent_thread_id") && workspacePanel.includes("已保存当前分析记录，并打开新对话。") && workspacePanel.includes("[definition, tenantId, userId, workspaceKey]") && !workspacePanel.includes("[definition, tenantId, userId, pageContext]"), "AI 分析必须把完成轮次持久化到工作区，输入 /new 保存历史并打开新对话，且不得因页面上下文刷新清空线程"],
  [workspacePanel.includes("onContextMenu") && workspacePanel.includes("archiveAnalysisThread") && workspacePanel.includes("data-analysis-thread-menu") && workspacePanel.includes(">关闭</button>") && workspacePanel.includes("至少保留一个分析对话。"), "AI 分析分支 Tab 必须支持右键气泡关闭，且不能关掉最后一个对话"],
  [workspacePanel.includes('model_application_module: "intelligent_analysis_reasoning"') && workspacePanel.includes("datasetSnapshot: objectValue") && workspacePanel.includes("evidenceRefs: evidenceRefArray"), "可视化页追问必须使用系统配置的分析模型，并把当前快照和证据绑定到服务端工作区"],
  [workspacePanel.includes("boundVisualAnalysisTables") && workspacePanel.includes("chartFollowUp") && !workspacePanel.includes('definition.pageKey === "self-analysis" && selectedTables.length === 0'), "图表追问必须使用图表绑定的数据表，不得再要求回到智能分析主输入区选表"],
  [pageData.includes("pageDataToSelection") && pageData.includes("selected_data_tables") && pageData.includes("chart_bound_source") && pageData.includes("replaceVisualAnalysisSourceGroup") && pageData.includes("revealAnalysisWorkspace"), "多机构页面数据图表追问必须把当前页面数据集作为分析数据源，并把整页图表登记为页面分析范围"],
  [visualFollowUp.includes("chart_bound_source") && visualFollowUp.includes("resolveVisualAnalysisTables") && visualFollowUp.includes("dataset_snapshot") && visualFollowUp.includes("metricCodes") && visualFollowUp.includes("visual_rows"), "统一可视化追问必须携带图表绑定的数据表、数据集快照和当前图数据行"],
  [workspacePanel.includes("parent_task_id: parentTaskId") && workspacePanel.includes("chart_bound_source: chartFollowUp") && workspacePanel.includes('visual_analysis_scope: chartFollowUp ? "chart" : "page"') && workspacePanel.includes('analysis_scene_hint: chartFollowUp ? "chart_followup" : "page_rail"') && workspacePanel.includes("follow_up_source_question") && analysisRoute.includes("_inherit_chart_follow_up_context") && analysisRoute.includes("_parent_visual_query_result") && analysisRoute.includes("_take_reused_visual") && analysisRoute.includes("_visual_follow_up_planning_question") && workflow.includes("analysis_planning_question"), "所有可视化追问必须继承图表数据表或复用图表已查询结果，不得把寒暄丢进默认 loan_amount"],
  [workspacePanel.includes('data-visual-analysis-scope={chartFollowUp ? "chart" : "page"}') && workspacePanel.includes("replaceVisualAnalysisSourceGroup") && rail.includes('data-context-rail-analysis-tab="true"') && rail.includes("revealAnalysisWorkspace(undefined)") && selfAnalysisWorkspace.includes('replaceVisualAnalysisSourceGroup("self-analysis"') && selfAnalysisWorkspace.includes('replaceVisualAnalysisSourceGroup("my-reports"') && !selfAnalysisWorkspace.includes("chart_bound_source:") && analysisRoute.includes("visual_analysis_scope") && analysisRoute.includes("_page_visual_query_result"), "直接点击 AI 分析必须进入页面范围并汇总当前页全部可视化，图表追问不得把 chart_bound_source 泄漏进页面上下文"],
  [[funnel, sandbox, supervision, customers, competition, emailDaily].every((source) => source.includes("updateAnalysisWorkspacePageContext")), "所有工作台可视化页面必须向多轮分析线程发布当前筛选、快照和证据上下文"],
  [selfAnalysis.includes("syncSelfAnalysisWorkspaceContext") && selfAnalysisWorkspace.includes('updateAnalysisWorkspacePageContext("my-reports"') && selfAnalysisWorkspace.includes('updateAnalysisWorkspacePageContext("self-analysis"'), "智能分析与我的报告必须分别发布上下文，不能把报告追问误绑定到查询页"],
  [resultViews.includes('data-visual-follow-up="true"') && !resultViews.includes("disabled={!rows.length} className=\"h-7 whitespace-nowrap rounded-full px-2 text-[11px] text-[#178a53]") && resultViews.includes('data-visual-data-toggle="true"') && resultViews.includes('data-visual-operation-tray=') && (selfAnalysis.match(/onFollowUp=/g) || []).length >= 2 && (selfAnalysis.match(/onComment=/g) || []).length >= 2 && visualFollowUp.includes('railPageKey || (reportId ? "my-reports" : "self-analysis")') && visualFollowUp.includes("selected_data_table_ids"), "智能分析当前结果和我的报告的每张可视化都必须提供显示数据、追问、操作和右栏评论入口，且追问不得因暂无行数据被禁用"],
  [(resultViews.match(/showData && <LabelList/g) || []).length >= 7 && resultViews.includes('data-visual-values={showData ? "shown" : "hidden"}') && !resultViews.includes('absolute inset-x-5 bottom-5 z-10 flex flex-wrap'), "显示数据必须把指标值绑定到图形元素，不得只在绘图区底部附加一排独立标签"],
  [resultViews.includes('aria-hidden={!operationsOpen}') && resultViews.includes('{ inert: "" } as Record<string, string>') && resultViews.includes('tabIndex={operationsOpen ? 0 : -1}') && resultViews.includes('motion-reduce:transition-none'), "操作滑轨折叠后必须从键盘和读屏顺序中隐藏，并尊重减少动画偏好"],
  [resultViews.includes("长按 2 秒后拖动排序") && resultViews.includes("useRightPressReorder") && resultViews.includes("orderedCandidates") && resultViews.includes("data-reorder-index") && resultViews.includes("data-table-long-press-reorder") && resultViews.includes("moveVisualizationField") && resultViews.includes("resolveVisualizationVoiceCommand") && visualCommand.includes("resolveVisualizationVoiceCommand") && visualVoice.includes("realtime_voice_input"), "统一可视化必须让指标维度长按两秒排序真实反映到呈现顺序，并支持持续实时语音配置"],
  [!messageBoard.includes("当前页面还没有留言") && messageBoard.includes('data-message-board-new="true"'), "留言板空态只能保留新增留言入口，不得显示第二个灰色空模块"],
  [!messageBoard.includes("onEditorKeyDown") && messageBoard.includes("回车换行") && messageBoard.includes("仅点击保存后提交") && messageBoard.includes(">取消</button>"), "留言编辑器必须允许回车换行，仅点击保存提交，并提供显式取消"],
  [messageBoard.includes("deleteMessageBoardEntry") && messageBoard.includes('aria-label="删除留言"') && !messageBoard.includes("留言已存档并标记为已完成") && messageBoardAdmin.includes('data-message-board-inline-summary="true"') && !messageBoardAdmin.includes("grid grid-cols-4 gap-4"), "关闭留言必须真正删除，管理页四项指标只能内联展示"],
  [messageBoard.includes("AudioLines") && !messageBoard.includes("ImagePlus") && !messageBoard.includes("<Mic"), "留言板实时语音图标必须与智能分析统一，且不得保留照片浮标"],
  [layout.includes("<GlobalMessageBoardShortcut />") && globalMessageBoard.includes("createPortal") && globalMessageBoard.includes('data-global-message-board-trigger="true"') && globalMessageBoard.includes("findPageHeaderHost") && globalMessageBoard.includes('data-page-header-actions="true"') && globalMessageBoard.includes("flex h-9 items-center gap-1.5") && !globalMessageBoard.includes("shadow-sm shadow-black/[0.03]"), "所有登录后页面必须把留言板入口注入页头操作行，并与同排按钮保持 h-9"],
  [[dataAssets, weekly, selfAnalysis, emailDaily, funnel, sandbox, systemSettings, messageBoardAdmin, dataAgentWorkspace].every((source) => source.includes('data-page-header-actions="true"')), "指标、周报、智能分析、邮件日报、漏斗、沙盘、系统管理、任务工作台和留言板管理页头必须提供操作行给留言板对齐"],
  [globalMessageBoard.includes("w-[12cm] min-h-[10cm] max-h-[20cm]") && globalMessageBoard.includes("max-h-[calc(20cm-40px)]") && globalMessageBoard.includes("overflow-y-auto") && !globalMessageBoard.includes("草稿已自动保存"), "全局留言气泡必须为 12cm 宽、默认至少 10cm，高度最多 20cm 后独立滚动，且不得展示草稿已自动保存"],
  [globalMessageBoard.includes("onPaste={onPaste}") && globalMessageBoard.includes("uploadMessageBoardImage") && globalMessageBoard.includes("useMessageBoardVoice") && globalMessageBoard.includes(">取消</button>") && globalMessageBoard.includes("提交"), "全局留言必须支持粘贴图片、实时语音、提交和显式取消"],
  [globalMessageBoard.includes("messageBoardDraftKey(tenantId, userId, pageKey)") && globalMessageBoard.includes("saveMessageBoardDraft") && messageBoardDraftStore.includes('const databaseName = "smart-data-agent-message-board"') && messageBoardDraftStore.includes("indexedDB.open") && messageBoardDraftStore.includes("localStorage"), "留言草稿必须按机构、用户和页面自动隔离保存，并在 IndexedDB 不可用时保留文字兜底"],
  [globalMessageBoard.includes("clearMessageBoardDraft(draftKey)") && globalMessageBoard.includes("createMessageBoardEntry") && messageBoardAdmin.includes("globalMessageBoardSubmittedEvent") && messageBoardAdmin.includes("<MessageBoardAttachmentGallery") && messageBoardGallery.includes("fetchMessageBoardAttachment"), "提交成功必须清除对应草稿、通知管理页刷新，并让超级管理员读取文字和截图"],
  [messageBoardAdmin.includes('data-message-board-append-content="true"') && messageBoardAdmin.includes('aria-label="追加内容"') && !messageBoardAdmin.includes(">追加内容") && !messageBoardAdmin.includes("追加内容</") && messageBoardAdmin.includes("scheduleAppendSave") && messageBoardAdmin.includes("persistAppendContent") && messageBoardAdmin.includes("keepalive") && messageBoardApi.includes("/api/message-board/admin/append-content"), "超级管理员追加内容必须自动保存到服务端，切换页面或重新登录后仍保留"],
  [messageBoardAdmin.includes('data-message-board-export="true"') && messageBoardAdmin.includes("Excel 文档") && messageBoardAdmin.includes("飞书表格") && messageBoardAdmin.includes("downloadAdoptedMessageBoardExport"), "留言板必须提供已采纳留言的 Excel 文档和飞书表格下载"],
  [messageBoardAdmin.includes('data-message-board-status-filter="true"') && messageBoardAdmin.includes('value: "new"') && messageBoardAdmin.includes('value: "adopted"') && messageBoardAdmin.includes('value: "completed"') && messageBoardApi.includes("status, sort"), "留言板管理必须在搜索框左侧提供按状态筛选"],
  [messageBoardAdmin.includes('data-message-board-time-sort="true"') && messageBoardAdmin.includes('current === "" ? "asc"') && messageBoardAdmin.includes('current === "asc" ? "desc"') && messageBoardService.includes('safe_sort not in {"", "asc", "desc"}'), "留言时间必须支持正排、倒排和恢复默认顺序"],
  [!dataAgentWorkspace.includes("w-9 h-9 rounded-lg bg-[#f2f2f7] flex items-center justify-center") && !messageBoardAdmin.includes("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#f2f2f7]"), "任务工作台三个页面标题前不得放置小图标"],
  [rail.includes('wide ? "w-[640px]" : "w-[320px]"') && rail.includes('w-[0.2cm]') && globalRail.includes("min-w-[0.2cm]") && workspacePanel.includes('data-global-analysis-wide-toggle="true"') && layout.includes("sidebarCollapsedBeforeWideRef") && layout.includes("setSidebarCollapsed(sidebarCollapsedBeforeWideRef.current)"), "收起右栏后只保留 0.2cm 占位，AI 卡片放大必须把右栏扩为两倍宽，并按放大前状态恢复左侧菜单"],
  [dashboard.includes("if (pageData.loading && !pageData.assets.length)") && dashboard.includes("<PageDataVisualizationModules controller={pageData}") && dashboard.includes("pageData.visibleAssets.length === 0") && !dashboard.includes('embedded />\n      {dashboardSideRail}') && weeklyRail.includes("if (!visible) return null"), "页面主数据为空时必须优先呈现已配置页面数据，且不得单独渲染页面右侧栏"],
  [selfAnalysis.includes("未找到可执行的数据表映射，可查看相关指标：") && selfAnalysis.includes("text-[11px] font-semibold leading-5 text-[#d93025]") && selfAnalysis.includes("queryInputRef.current?.focus()") && selfAnalysis.includes("选择对应数据表"), "数据表映射提示必须使用与外层一致的 11px 字号，指标可点击加粗并回填输入框，选择数据表保持原入口"],
  [!dashboard.includes("setSelectedBank") && !dashboard.includes("全部分行</option>") && !dashboard.includes('runDashboardAction("select_bank"'), "多机构分析右上角不得保留分支机构下拉选项"],
  [!comments.includes("border-t-[4px]") && !comments.includes("ring-2 ring-[#fbbc04]") && !analysis.includes("ring-2 ring-[#0a66c2]") && !messageBoard.includes("shadow-sm shadow-black/[0.03]"), "评论、AI 分析和留言板子模块必须统一为飞书式浅灰单边框，不得各用粗顶边或双重光环"],
  [pendingAnalysis.includes("smart-data-agent:pending-analysis") && selfAnalysis.includes("resumeRunId: pending.runId") && selfAnalysis.includes("analysisWaitAbortRef.current?.abort()") && analysisApi.includes("waitForAnalysisPoll") && analysisApi.includes("signal?: AbortSignal"), "智能分析运行必须持久保存运行句柄，离开页面停止旧轮询，返回后从同一任务继续"],
  [dataAssets.includes("完全相同的重复行只导入一次") && dataAssets.includes("相同重复行自动合并") && dataAssets.includes("冲突名称整批失败") && dataAssets.includes("批量导入失败：") && metricRoutes.includes("_prepare_metric_import") && metricRoutes.includes("metric_dictionary_duplicate_names"), "批量指标导入只能合并完全相同的文件内重复行；定义冲突或指标库已有名称仍须整批失败并显示明确原因"],
  [!systemSettings.includes("model_default_intelligent_analysis_relay") && !settingsRoutes.includes("default_relay_model_preset") && !settingsRoutes.includes("ensure_default_models_for_account") && !asrRoutes.includes("default_relay_model_preset") && !asrRoutes.includes("ensure_default_models_for_account"), "模型接入不得再注入或保护默认模型条目"],
  [weekly.includes('{ id: afterParagraphId, type: "paragraph" as const, text: afterText') && weekly.includes('data-comment-editor-id="${afterParagraphId}"'), "周报文字模块粘贴图片后必须始终创建并聚焦图片下方文本行"],
  [csvFolder.includes("_crawler_source_roots") && csvFolder.includes('self.root / "csv" / source_id') && csvFolder.includes("institutionId") && !csvFolder.includes("self.root / \"csv\"\n"), "SDA 必须按 Crawler 机构绑定读取 source-id 输出目录，不得无边界扫描公共 csv 根目录"],
];

const failures = checks.filter(([passed]) => !passed).map(([, message]) => message);
if (failures.length) {
  console.error(`右侧栏契约检查失败：\n- ${failures.join("\n- ")}`);
  process.exit(1);
}

console.log(`右侧栏契约检查通过（${checks.length} 项）`);
