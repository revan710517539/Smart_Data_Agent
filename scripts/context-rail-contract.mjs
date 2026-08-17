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
const dataAssets = read("src/app/components/DataAssets.tsx");
const systemSettings = read("src/app/components/SystemSettings.tsx");
const defaultModels = read("backend/platform/settings/default_models.py");
const analysisApi = read("src/app/services/analysisApi.ts");
const metricRoutes = read("backend/platform/api/routes/metrics.py");
const csvFolder = read("backend/platform/ingestion/csv_folder.py");
const pendingAnalysis = read("src/app/components/self-analysis/pendingAnalysisRun.ts");

const checks = [
  [rail.includes('data-context-rail-collapse="true"'), "右栏必须保留整体收起入口"],
  [rail.includes("useState(true)") && !rail.includes("smart_data_agent_context_rail_collapsed"), "右栏每次进入页面必须默认折叠，不得被旧本地状态强制展开"],
  [rail.includes('data-context-rail-edge-zone="true"'), "收起后必须保留右边缘悬浮感应区"],
  [rail.includes('style={{ top: "50%" }}') && !rail.includes("setEdgeY") && !rail.includes("clientY"), "右侧边缘展开按钮必须固定在垂直中线，不得随鼠标移动"],
  [rail.includes("contextRailRevealEvent") && rail.includes("setCollapsed(false)") && rail.includes("onTabChange(detail.tab)"), "点击页面标注时必须自动展开右栏并切换到对应评论或 AI 页签"],
  [rail.includes('data-context-rail-scroll="true"') && rail.includes("overflow-y-auto"), "右栏必须使用独立纵向滚动容器"],
  [rail.includes('activeTab === "comments" ? "" : "hidden"') && rail.includes('activeTab === "analysis" ? "" : "hidden"'), "评论和 AI 标签切换不得卸载内部状态"],
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
  [comments.includes("readableContextText") && domain.includes("JSON.parse(normalized)") && domain.includes("summarizeContextValue"), "评论引用内容必须把历史 JSON 转换为可读中文摘要，不得直接显示序列化数据"],
  [comments.includes("let nextTop = startTop") && comments.includes("const displayTop = nextTop") && !comments.includes(".sort((a, b) => a.anchorTop - b.anchorTop)"), "评论卡必须从顶部开始按列表顺序自上而下排列，不得按正文锚点制造大段空白"],
  [comments.includes("activeDraftId || activeCommentId") && comments.includes("scroller.scrollTo") && comments.includes("CSS.escape(entryId)"), "点击评论标注后右栏必须自动滚动定位到对应评论或草稿"],
  [comments.includes("formatCommentTimestamp(comment.time)") && comments.includes("formatCommentTimestamp(reply.time)") && comments.includes('return `${year}-${month}-${day} ${hour}:${minute}:${second}`'), "评论和追评时间必须只显示年月日与时分秒，不得暴露毫秒或时区信息"],
  [layout.includes('data-agent-sidebar-expand-zone="true"') && layout.includes('style={{ top: "50%" }}') && !layout.includes("setSidebarEdgeY") && !layout.includes("clientY") && layout.includes("sidebarEdgeVisible"), "左侧菜单折叠后必须在整条左边缘显示居中稳定的展开按钮"],
  [dashboard.includes("summarizeContextValue(p.kpis)") && dashboard.includes("summarizeContextValue(dualTrend)") && dashboard.includes("summarizeContextValue(bankProductData)") && !dashboard.includes("JSON.stringify(p.kpis)"), "多机构分析的指标、图表和表格评论目标必须使用可读摘要，不得生成 JSON 乱码"],
  [routes.includes("canSafelyReloadRouteImport") && routes.includes("routeImportRetryKey") && routes.includes("errorElement: createElement(RouteErrorPage)"), "动态页面模块失效时必须限制自动重载次数并提供路由错误边界"],
  [routeError.includes('data-route-error="true"') && routeError.includes("重新加载页面") && routeError.includes("返回智能分析"), "路由异常不得显示默认英文白屏，必须提供系统风格恢复操作"],
  [layout.includes("<AgentSupervisor />") && layout.includes("<GlobalContextRail />") && globalRail.includes("<AnalysisWorkspacePanel revealedDataPoint={selectedDataPoint}"), "页面必须保留总管对话入口，并把分析线程迁入统一右栏"],
  [!supervisor.includes("分析线程") && !supervisor.includes("AnalysisWorkspacePanel") && !supervisor.includes("analysisWorkspaceRevealEvent"), "小机器人不得继续承载重复的分析线程入口"],
  [globalRail.includes("analysisWorkspaceRevealEvent") && globalRail.includes('setActiveTab("analysis")') && globalRail.includes("contextRailRevealEvent"), "图表或数据点追问必须携带锚点展开统一右栏并进入 AI 分析"],
  [workspacePanel.includes('data-global-analysis-wide-toggle="true"') && !workspacePanel.includes("服务端持久化 · 分支历史不覆盖") && !workspacePanel.includes("输入问题后，本轮问题、规划、结论和证据会写入当前线程"), "AI 分析必须只保留一个线程 Tab 头并移除重复标题说明"],
  [workspacePanel.includes("createAnalysisBranch") && workspacePanel.includes("mergeAnalysisThreads") && workspacePanel.includes("TrustedArtifactPanel") && workspacePanel.includes("runWorkspaceAnalysis"), "融合后必须保留追问、分支、合并和可信证据能力"],
  [workspacePanel.includes('model_application_module: "intelligent_analysis_reasoning"') && workspacePanel.includes("datasetSnapshot: objectValue") && workspacePanel.includes("evidenceRefs: evidenceRefArray"), "可视化页追问必须使用系统配置的分析模型，并把当前快照和证据绑定到服务端工作区"],
  [[funnel, sandbox, supervision, customers, competition, emailDaily].every((source) => source.includes("updateAnalysisWorkspacePageContext")), "所有工作台可视化页面必须向多轮分析线程发布当前筛选、快照和证据上下文"],
  [selfAnalysis.includes("syncSelfAnalysisWorkspaceContext") && selfAnalysisWorkspace.includes('updateAnalysisWorkspacePageContext("my-reports"') && selfAnalysisWorkspace.includes('updateAnalysisWorkspacePageContext("self-analysis"'), "智能分析与我的报告必须分别发布上下文，不能把报告追问误绑定到查询页"],
  [resultViews.includes('data-visual-follow-up="true"') && resultViews.includes('data-visual-data-toggle="true"') && resultViews.includes('data-visual-operation-tray=') && (selfAnalysis.match(/onFollowUp=/g) || []).length === 2 && (selfAnalysis.match(/onComment=/g) || []).length === 2 && visualFollowUp.includes('railPageKey || (reportId ? "my-reports" : "self-analysis")') && visualFollowUp.includes("selected_data_table_ids"), "智能分析当前结果和我的报告的每张可视化都必须提供显示数据、追问、操作和右栏评论入口"],
  [(resultViews.match(/showData && <LabelList/g) || []).length >= 7 && resultViews.includes('data-visual-values={showData ? "shown" : "hidden"}') && !resultViews.includes('absolute inset-x-5 bottom-5 z-10 flex flex-wrap'), "显示数据必须把指标值绑定到图形元素，不得只在绘图区底部附加一排独立标签"],
  [resultViews.includes('aria-hidden={!operationsOpen}') && resultViews.includes('{ inert: "" } as Record<string, string>') && resultViews.includes('tabIndex={operationsOpen ? 0 : -1}') && resultViews.includes('motion-reduce:transition-none'), "操作滑轨折叠后必须从键盘和读屏顺序中隐藏，并尊重减少动画偏好"],
  [resultViews.includes("长按 2 秒后拖动排序") && resultViews.includes("useRightPressReorder") && resultViews.includes("orderedCandidates") && resultViews.includes("data-reorder-index") && resultViews.includes("data-table-long-press-reorder") && resultViews.includes("moveVisualizationField") && resultViews.includes("resolveVisualizationVoiceCommand") && visualCommand.includes("resolveVisualizationVoiceCommand") && visualVoice.includes("realtime_voice_input"), "统一可视化必须让指标维度长按两秒排序真实反映到呈现顺序，并支持持续实时语音配置"],
  [!messageBoard.includes("当前页面还没有留言") && messageBoard.includes('data-message-board-new="true"'), "留言板空态只能保留新增留言入口，不得显示第二个灰色空模块"],
  [!messageBoard.includes("onEditorKeyDown") && messageBoard.includes("回车换行") && messageBoard.includes("仅点击保存后提交") && messageBoard.includes(">取消</button>"), "留言编辑器必须允许回车换行，仅点击保存提交，并提供显式取消"],
  [messageBoard.includes("deleteMessageBoardEntry") && messageBoard.includes('aria-label="删除留言"') && !messageBoard.includes("留言已存档并标记为已完成") && messageBoardAdmin.includes('data-message-board-inline-summary="true"') && !messageBoardAdmin.includes("grid grid-cols-4 gap-4"), "关闭留言必须真正删除，管理页四项指标只能内联展示"],
  [messageBoard.includes("AudioLines") && !messageBoard.includes("ImagePlus") && !messageBoard.includes("<Mic"), "留言板实时语音图标必须与智能分析统一，且不得保留照片浮标"],
  [rail.includes('wide ? "w-[640px]" : "w-[320px]"') && workspacePanel.includes('data-global-analysis-wide-toggle="true"') && layout.includes("sidebarCollapsedBeforeWideRef") && layout.includes("setSidebarCollapsed(sidebarCollapsedBeforeWideRef.current)"), "AI 卡片放大必须把右栏扩为两倍宽，并按放大前状态恢复左侧菜单"],
  [dashboard.includes('if (!dashboardModel.hasData)') && dashboard.includes("<PageDataVisualizationModules controller={pageData}") && dashboard.includes("pageData.visibleAssets.length === 0") && !dashboard.includes('embedded />\n      {dashboardSideRail}') && weeklyRail.includes("if (!visible) return null"), "页面主数据为空时必须优先呈现已配置页面数据，且不得单独渲染页面右侧栏"],
  [selfAnalysis.includes("未找到可执行的数据表映射，可查看相关指标：") && selfAnalysis.includes("text-[11px] font-semibold leading-5 text-[#d93025]") && selfAnalysis.includes("queryInputRef.current?.focus()") && selfAnalysis.includes("选择对应数据表"), "数据表映射提示必须使用与外层一致的 11px 字号，指标可点击加粗并回填输入框，选择数据表保持原入口"],
  [!dashboard.includes("setSelectedBank") && !dashboard.includes("全部分行</option>") && !dashboard.includes('runDashboardAction("select_bank"'), "多机构分析右上角不得保留分支机构下拉选项"],
  [!comments.includes("border-t-[4px]") && !comments.includes("ring-2 ring-[#fbbc04]") && !analysis.includes("ring-2 ring-[#0a66c2]") && !messageBoard.includes("shadow-sm shadow-black/[0.03]"), "评论、AI 分析和留言板子模块必须统一为飞书式浅灰单边框，不得各用粗顶边或双重光环"],
  [pendingAnalysis.includes("smart-data-agent:pending-analysis") && selfAnalysis.includes("resumeRunId: pending.runId") && selfAnalysis.includes("analysisWaitAbortRef.current?.abort()") && analysisApi.includes("waitForAnalysisPoll") && analysisApi.includes("signal?: AbortSignal"), "智能分析运行必须持久保存运行句柄，离开页面停止旧轮询，返回后从同一任务继续"],
  [dataAssets.includes("完全相同的重复行只导入一次") && dataAssets.includes("相同重复行自动合并") && dataAssets.includes("冲突名称整批失败") && metricRoutes.includes("_prepare_metric_import") && metricRoutes.includes("metric_dictionary_duplicate_names"), "批量指标导入只能合并完全相同的文件内重复行；定义冲突或指标库已有名称仍须整批失败"],
  [systemSettings.includes('model.requiresCredential ? "待配置"') && systemSettings.includes("model.requiresCredential && !modelEditDraft.value.trim()") && defaultModels.includes("DEFAULT_RELAY_SHARED_MODELS") && defaultModels.includes('"gpt-5.5"'), "未配置默认模型密钥时必须显示安全预置目录和待配置状态，不得伪装为已连接或把密钥写入源码"],
  [weekly.includes('{ id: afterParagraphId, type: "paragraph" as const, text: afterText }') && weekly.includes('data-comment-editor-id="${afterParagraphId}"'), "周报文字模块粘贴图片后必须始终创建并聚焦图片下方文本行"],
  [csvFolder.includes("_crawler_source_roots") && csvFolder.includes('self.root / "csv" / source_id') && csvFolder.includes("institutionId") && !csvFolder.includes("self.root / \"csv\"\n"), "SDA 必须按 Crawler 机构绑定读取 source-id 输出目录，不得无边界扫描公共 csv 根目录"],
];

const failures = checks.filter(([passed]) => !passed).map(([, message]) => message);
if (failures.length) {
  console.error(`右侧栏契约检查失败：\n- ${failures.join("\n- ")}`);
  process.exit(1);
}

console.log(`右侧栏契约检查通过（${checks.length} 项）`);
