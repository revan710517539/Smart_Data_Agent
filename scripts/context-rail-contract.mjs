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

const checks = [
  [rail.includes('data-context-rail-collapse="true"'), "右栏必须保留整体收起入口"],
  [rail.includes('data-context-rail-edge-zone="true"'), "收起后必须保留右边缘悬浮感应区"],
  [rail.includes('style={{ top: "50%" }}') && !rail.includes("setEdgeY") && !rail.includes("clientY"), "右侧边缘展开按钮必须固定在垂直中线，不得随鼠标移动"],
  [rail.includes("contextRailRevealEvent") && rail.includes("setCollapsed(false)") && rail.includes("onTabChange(detail.tab)"), "点击页面标注时必须自动展开右栏并切换到对应评论或 AI 页签"],
  [rail.includes('data-context-rail-scroll="true"') && rail.includes("overflow-y-auto"), "右栏必须使用独立纵向滚动容器"],
  [rail.includes('activeTab === "comments" ? "" : "hidden"') && rail.includes('activeTab === "analysis" ? "" : "hidden"'), "评论和 AI 标签切换不得卸载内部状态"],
  [weeklyRail.includes("Array<CommentTarget | null>>([null])"), "无选区时必须保留全页总体分析卡片"],
  [weeklyRail.includes("positionedTargets.map") && weeklyRail.includes("activateTarget"), "AI 分析必须支持多卡片和卡片置顶"],
  [weeklyRail.includes("onAnalysisTargetActivate?.(target)"), "点击 AI 卡片必须反向选中页面对应内容"],
  [analysis.includes("本页面没有找到这一数据，请检查要分析的内容"), "缺少请求数据时必须使用产品指定提示"],
  [analysis.includes("实时语音交互") && !analysis.includes('disabled={!target}'), "无选区总体分析也必须允许实时语音"],
  [analysis.includes("voiceStartupErrorMessage") && analysis.includes("Data Agent API 暂时不可用") && analysis.includes("重新连接"), "语音启动失败必须使用场景化提示并提供重新连接入口"],
  [analysis.includes('data-context-analysis-collapsed={collapsed ? "true" : "false"}') && analysis.includes('aria-label="已完成"') && analysis.includes("onClick={onComplete}") && !analysis.includes("setCompleted"), "AI 卡片必须支持折叠，点击已完成后直接关闭且不得切换为恢复状态"],
  [analysis.includes("<AnalysisProgressPanel embedded") && !analysis.includes('overflow-x-auto rounded-lg border border-[#ececf0]') && !analysis.includes('h-[260px] w-full rounded-lg border border-[#ececf0]'), "AI 结果四个页签内部不得重复嵌套边框"],
  [analysis.includes('data-context-analysis-input="true"') && analysis.includes('className="bg-transparent px-0.5"') && analysis.includes('className="-mx-3 -mb-3 overflow-hidden border-t') && !analysis.includes('rounded-xl border border-[#e5e5ea] bg-[#fafbfc] p-2.5'), "AI 输入与分析结果必须共用分析卡最外层边框，不得各自嵌套卡片边框"],
  [progress.includes("{!embedded && (") && progress.includes('embedded ? "overflow-hidden bg-transparent"') && !analysis.includes("{chart.title}") && !analysis.includes("whitespace-pre-wrap rounded-lg bg") && !analysis.includes("items-center justify-center rounded-lg bg"), "AI 结果四个页签必须直接呈现内容，不得保留内部标题栏或卡片层"],
  [weeklyRail.includes("activeTargetKey") && weeklyRail.includes("setActiveTargetKey(null)") && !weeklyRail.includes("const activateTarget = (target: CommentTarget | null) => {\n    setAnalysisTargets"), "AI 分析卡高亮必须由独立单选状态控制，点击空白处后取消"],
  [weeklyRail.includes("startedTargetKeys") && weeklyRail.includes("onAnalysisTargetDismiss?.(activeTarget)") && weeklyRail.includes('addEventListener("mousedown", handleDocumentMouseDown, true)'), "未执行的临时 AI 分析卡必须在点击其他位置时自动清理"],
  [weeklyRail.includes("const completeTarget") && weeklyRail.includes("current.filter((item) => targetKey(item) !== key)") && weeklyRail.includes("onComplete={() => completeTarget(target)}"), "点击已完成必须从右栏移除当前 AI 分析卡"],
  [selectable.includes("captureTextSelection") && selectable.includes("selection:bg-[#dce9ff]") && selectable.includes("onOpenAnalysis(actionTarget)"), "多机构分析选中文字后必须把真实选区传给 AI 分析"],
  [selectable.includes("AnalysisUnderlineProvider") && selectable.includes("data-analysis-annotation") && selectable.includes("border-[#ff3b30]"), "AI 选区必须持久渲染为红色可点击下划线"],
  [annotationText.includes('annotationKind === "analysis"') && annotationText.includes("border-[#ff3b30]") && annotationText.includes("border-[#1a73e8]"), "经营周报 AI 与评论文字标注必须分别使用红色和蓝色下划线"],
  [selectable.includes('data-comment-annotation') && selectable.includes('data-annotation-kind') && selectable.includes("border-[#1a73e8] bg-[#eef4ff]") && selectable.includes("border-[#ff3b30] bg-[#fff1f0]"), "多机构分析评论与 AI 文字标注必须使用不同的下划线和阴影底色"],
  [![selectable, annotationText].some((source) => ["#6d28d9", "#8b5cf6", "#ede9fe", "#f5f3ff", "#7c3aed"].some((color) => source.includes(color))), "AI 文字标注不得残留旧紫色样式"],
  [weekly.includes("analysisSelectionTargets") && weekly.includes('annotationKind: "analysis"') && weekly.includes("activateTextAnnotation"), "经营周报必须持久保存 AI 文字选区并支持点击反向激活"],
  [weeklyRail.includes("positionAnalysisTargets") && weeklyRail.includes("alignAnalysisCard") && weeklyRail.includes("anchorViewportTop"), "AI 选区激活后必须按文字锚点定位并对齐对应分析卡片"],
  [weeklyRail.includes("analysisScopeKey") && weeklyRail.includes("analysisProps.tenantId") && weeklyRail.includes("analysisProps.userId") && weeklyRail.includes('key={`${analysisScopeKey}:'), "共享右栏 AI 卡片必须按机构、用户、页面和报告强制隔离"],
  [weeklyRail.includes("analysisStateScopeKey === analysisScopeKey") && weeklyRail.includes("scopeMatches ? analysisTargets : [null]") && weeklyRail.includes("if (!scopeMatches || !analysisProps.target) return"), "切换机构或用户后的首帧必须同步隐藏旧 AI 卡片，不得等待异步清理"],
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
  [routeError.includes('data-route-error="true"') && routeError.includes("重新加载页面") && routeError.includes("返回多机构分析"), "路由异常不得显示默认英文白屏，必须提供系统风格恢复操作"],
];

const failures = checks.filter(([passed]) => !passed).map(([, message]) => message);
if (failures.length) {
  console.error(`右侧栏契约检查失败：\n- ${failures.join("\n- ")}`);
  process.exit(1);
}

console.log(`右侧栏契约检查通过（${checks.length} 项）`);
