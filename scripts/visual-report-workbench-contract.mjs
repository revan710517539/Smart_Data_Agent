import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [layout, routes, builder, library, cards, reportData, visualCard, visualNote, contextRail, selfAnalysis, dataTablePicker, analysisRoute, reportsRoute, application, applicationRoute, productionAssetStore, featuredReports, domain, dashboard, supervision, weekly, richNote, noteModel, stickyNote, stickyHook, pageDataComposer, standardAnalysisPage] = await Promise.all([
  readFile("src/app/components/Layout.tsx", "utf8"),
  readFile("src/app/routes.ts", "utf8"),
  readFile("src/app/components/VisualReportBuilder.tsx", "utf8"),
  readFile("src/app/components/visual-report/VisualReportLibrary.tsx", "utf8"),
  readFile("src/app/components/visual-report/VisualReportCards.tsx", "utf8"),
  readFile("src/app/components/visual-report/reportData.ts", "utf8"),
  readFile("src/app/components/self-analysis/ResultViews.tsx", "utf8"),
  readFile("src/app/components/visualization/VisualNoteFields.tsx", "utf8"),
  readFile("src/app/components/context-rail/ContextSideRail.tsx", "utf8"),
  readFile("src/app/components/SelfAnalysis.tsx", "utf8"),
  readFile("src/app/components/self-analysis/DataTablePickerModal.tsx", "utf8"),
  readFile("backend/platform/api/routes/analysis.py", "utf8"),
  readFile("backend/platform/api/routes/reports.py", "utf8"),
  readFile("backend/platform/application/store.py", "utf8"),
  readFile("backend/platform/api/routes/application.py", "utf8"),
  readFile("backend/platform/assets/postgresql_store.py", "utf8"),
  readFile("src/app/components/self-analysis/featuredReports.ts", "utf8"),
  readFile("src/app/components/self-analysis/domain.ts", "utf8"),
  readFile("src/app/components/Dashboard.tsx", "utf8"),
  readFile("src/app/components/InstitutionSupervision.tsx", "utf8"),
  readFile("src/app/components/WeeklyReport.tsx", "utf8"),
  readFile("src/app/components/notes/RichNoteEditor.tsx", "utf8"),
  readFile("src/app/components/notes/richNote.ts", "utf8"),
  readFile("src/app/components/notes/StickyNote.tsx", "utf8"),
  readFile("src/app/components/notes/useStickyNote.ts", "utf8"),
  readFile("src/app/components/page-data/PageDataComposer.tsx", "utf8"),
  readFile("src/app/components/page-data/StandardAnalysisPage.tsx", "utf8"),
]);
const [reportPublicFilters, apiSupport, weeklyAnalysisModules] = await Promise.all([
  readFile("src/app/components/report-filters/ReportPublicFilters.tsx", "utf8"),
  readFile("backend/platform/api/support.py", "utf8"),
  readFile("src/app/components/weekly-report/AnalysisModules.tsx", "utf8"),
]);
const [reportPageStyles, reportPageStyleCss, dataAssetApi, postgresqlApplicationStore, assetsRoute] = await Promise.all([
  readFile("src/app/components/report-style/reportPageStyles.tsx", "utf8"),
  readFile("src/styles/report-page-styles.css", "utf8"),
  readFile("src/app/services/dataAssetApi.ts", "utf8"),
  readFile("backend/platform/application/postgresql_store.py", "utf8"),
  readFile("backend/platform/api/routes/assets.py", "utf8"),
]);
const [visualReportApi, customerInsight, competitionAnalysis] = await Promise.all([
  readFile("src/app/services/visualReportApi.ts", "utf8"),
  readFile("src/app/components/CustomerInsight.tsx", "utf8"),
  readFile("src/app/components/CompetitionAnalysis.tsx", "utf8"),
]);

assert.ok(layout.indexOf('label: "可视化报表"') < layout.indexOf('label: "智能分析"'), "可视化报表必须位于智能分析上方");
assert.match(layout, /path: "\/self-analysis\/reports", label: "我的报表"/);
assert.ok(layout.indexOf('label: "经营分析"') < layout.indexOf('label: "我的报表"') && layout.indexOf('label: "我的报表"') < layout.indexOf('label: "自助分析"'), "我的报表必须作为一级菜单位于经营分析与自助分析之间");
assert.equal((layout.match(/label: "我的报表"/g) || []).length, 1, "我的报表菜单只能保留一个入口");
assert.match(routes, /path: "self-analysis\/visual-reports"/);

assert.match(builder, /useState<"browse" \| "edit">\("browse"\)/, "报表必须默认浏览态");
assert.match(builder, /useState<"landing" \| "editor">\("landing"\)/, "可视化报表路由必须先进入落地页");
assert.match(builder, /placeholder="搜索曾经创建过的报表"/);
assert.match(builder, /data-new-visual-report="true"/);
assert.match(builder, /data-visual-report-list-loading="true"/, "已有报表慢请求必须降级为局部加载提示");
assert.match(builder, /data-report-list-loading=\{reportLoading \? "true" : "false"\}/, "新建报表画布不得被已有报表列表请求阻塞");
assert.match(builder, /title="最近创建"/);
assert.match(builder, /title="推荐使用"/);
assert.match(builder, /openReport\(newVisualReport\(\), "edit"\)/, "新建报表必须直接进入可编辑的空白画布");
assert.match(selfAnalysis, /navigate\("\/self-analysis\/visual-reports", \{ state: \{ createVisualReport: true \} \}\)/, "我的报表中的新建可视化报表必须携带一次性新建意图");
assert.match(builder, /consumedCreateIntentRef\.current === location\.key/, "同一次新建路由意图只能消费一次");
assert.ok(builder.includes("navigate(location.pathname, { replace: true, state: null });"), "消费新建路由意图后必须替换历史记录并清除状态");
assert.match(builder, /savedSignatureRef\.current = reportSignature\(selected\)/, "二次编辑必须沿用原报表 ID 与保存签名");
assert.match(builder, /editController=\{reportEditController\}/, "可视化报表必须把浏览和编辑状态交给统一页头控制");
assert.match(standardAnalysisPage, /<PageDataModeToggle controller=\{editController\}/, "统一页头必须复用编辑保存按钮组件");
assert.match(builder, /saveLayout: async \(\) => Boolean\(await persistReport\(report\)\)/, "退出编辑态前必须通过统一控制器保存当前报表");
assert.match(pageDataComposer, /const saved = await controller\.saveLayout\(\);[\s\S]*?if \(!saved\) return;[\s\S]*?controller\.setMode\("browse"\)/, "保存失败必须停留在编辑态，只有保存成功才能进入非编辑态");
assert.match(builder, /navigate\("\/self-analysis\/reports"\)/, "存我的后必须进入我的报表");
assert.match(builder, /WHERE :tenant_id IS NOT NULL/, "存主题必须保留显式租户绑定 SQL 契约");
assert.match(builder, /onDoubleClick=\{\(\) => setEditingTitle\(true\)\}/);
assert.match(builder, /onBlur=\{commitTitle\}/);
assert.match(builder, /data-add-visual-report-chart="true"/);
assert.match(builder, /<FormDialogCancelButton onClick=\{onCancel\}>取消<\/FormDialogCancelButton>/);
assert.match(builder, /data-visual-report-restore="true"/);
assert.match(builder, /<FormDialogPrimaryButton[\s\S]*?>保存<\/FormDialogPrimaryButton>/);
assert.ok(builder.indexOf(">取消</FormDialogCancelButton>") < builder.indexOf("data-visual-report-restore") && builder.indexOf("data-visual-report-restore") < builder.indexOf(">保存</FormDialogPrimaryButton>"), "新增图表底部按钮必须按取消、恢复、保存排列");
assert.match(builder, /Record<string, VisualChartDraft>/, "未保存图表配置必须按数据集隔离保留");
assert.match(builder, /visualDatasetDraftKey\(dataset\)/, "原始表和主题表切换后必须按数据集恢复草稿");
assert.match(builder, /setVisualChartDrafts\(\{\}\)/, "恢复必须清空本次新增流程的图表草稿");
const draftType = builder.match(/type VisualChartDraft = \{([\s\S]*?)\};/)?.[1] || "";
assert.ok(draftType && !draftType.includes("rows"), "图表草稿不能缓存授权数据行");
for (const label of ["存我的", "存经验", "存周报"]) assert.ok(builder.includes(`label="${label}"`));
assert.ok(!builder.includes('label="存主题"'), "可视化报表不得保留存主题按钮");
assert.match(builder, /if \(destination !== "topic"\) await saveAsTopic\(/, "三个保存入口必须自动沉淀对应 SQL 到主题表");

assert.match(cards, /AnalysisVisualCard/);
assert.match(cards, /initialConfig=\{card\.config\}[\s\S]{0,120}configAuthority="server"/, "已保存可视化报表必须以服务端配置为权威，不能被会话缓存覆盖");
assert.match(standardAnalysisPage, /data-visual-card=\{visualGridId\(moduleKey, item\.id\)\}[\s\S]*?rememberVisualStickyNoteAnchor\(visualGridId\(moduleKey, item\.id\)/, "标准报表网格必须把点击的自定义图表登记为便签锚点");
assert.match(cards, /onLayoutChange=\{\(cardId, size\) => \{[\s\S]{0,300}updateCard\(cardId, \{ config: \{ \.\.\.card\.config, layoutSpan: size\.span, layoutHeight: size\.height \} \}\)/, "可视化报表缩放结果必须回写卡片配置，不能只停留在网格组件内部");
assert.match(builder, /data-visual-report-dataset-toolbar="true"[\s\S]{0,500}<ReportPublicFilterButton/, "可视化报表编辑态必须在首个数据集旁提供公共筛选入口");
assert.match(builder, /<ReportPublicFilterButton[\s\S]{0,420}<ReportPageStyleButton/, "可视化报表样式入口必须紧邻公共筛选右侧");
assert.match(weekly, /<WeeklyAnalysisModuleMenu[\s\S]{0,900}<PageDataPublicFilterButton controller=\{weeklyPageData\}/, "经营周报公共筛选入口必须位于首个可选数据模块右侧");
assert.match(weekly, /<PageDataPublicFilterButton controller=\{weeklyPageData\} \/><ReportPageStyleButton/, "经营周报样式入口必须紧邻公共筛选右侧");
assert.match(pageDataComposer, /<PageDataPublicFilterButton controller=\{controller\} \/><ReportPageStyleButton/, "页面数据报表样式入口必须紧邻公共筛选右侧");
assert.match(pageDataComposer, /const selectedAssets = controller\.visibleAssets\.filter[\s\S]*controller\.visibleAssets\.map/, "页面数据公共筛选只能选择当前报表已经显示并由后端布局授权的数据集");
assert.match(pageDataComposer, /new Map\(layoutIds\.flatMap/, "同一数据集的多个图表不得在公共筛选数据集列表中重复出现");
assert.match(pageDataComposer, /const nextPublicFilters = normalizeReportPublicFilterPositions[\s\S]*group\.datasetIds\.filter\(\(datasetId\) => nextIdSet\.has\(datasetId\)\)/, "移除报表数据集时必须同步清理公共筛选映射，避免后端拒绝整页保存");
assert.equal((reportPageStyles.match(/\{ id: "(?:executive-overview|trend-story|variance-benchmark|risk-watch|operations-dense|segment-lens|funnel-journey|board-brief|evidence-ledger|balanced-canvas)"/g) || []).length, 10, "整页样式下拉必须提供十套受控模板");
for (const method of ["关键指标优先", "时间趋势展开", "同类比较", "异常优先", "明细驱动", "分群比较", "漏斗拆解", "结论先行", "证据追溯", "总分均衡"]) assert.ok(reportPageStyles.includes(method), `整页模板必须包含分析方法：${method}`);
assert.match(reportPageStyles, /applyReportPageStyleToCards[\s\S]*layoutSpan:[\s\S]*layoutHeight:[\s\S]*tableStyle:[\s\S]*chartStyle:/, "选择整页模板必须同时改动排列、尺寸、表格与图表样式");
assert.match(reportPageStyleCss, /--sda-report-canvas[\s\S]*--sda-report-border[\s\S]*--sda-report-font/, "整页模板必须统一画布、线框和字体令牌");
assert.match(reportPageStyles, /--sda-report-chart-1[\s\S]*--sda-report-chart-grid[\s\S]*--sda-report-chart-line-width/, "整页模板必须把对应图表模板转换为原生图表主题令牌");
assert.match(standardAnalysisPage, /data-report-native-chart-theme="true"/, "标准分析页的原生图表必须接入整页图表主题");
assert.match(reportPageStyleCss, /data-report-native-chart-theme[\s\S]*recharts-cartesian-grid[\s\S]*--sda-report-table-header-bg/, "整页样式必须实际覆盖原生图表网格和表格主题");
assert.match(customerInsight, /--sda-report-chart-1[\s\S]*--sda-report-chart-grid/, "客群分析原生图形必须直接消费所选整页模板的图表令牌");
assert.match(competitionAnalysis, /reportChartColors[\s\S]*--sda-report-chart-grid/, "竞品分析原生多序列图形必须消费所选整页模板的调色板和网格令牌");
assert.match(application, /_REPORT_PAGE_STYLE_IDS/, "服务端必须用白名单校验整页样式");
assert.match(application, /next_state\["pageReportStyleId"\][\s\S]*next_state\["pageVisualStyleId"\]/, "服务端必须保存两类报表页样式");
assert.match(postgresqlApplicationStore, /shared_state\["pageReportStyleId"\][\s\S]*shared_state\["pageVisualStyleId"\]/, "生产状态投影必须持久化报表整页样式");
assert.match(assetsRoute, /"page_style_id": str\(state\.get\("pageReportStyleId"\)/, "页面数据工作区必须回读服务端保存的整页样式");
assert.match(dataAssetApi, /page_style_id\?: string/, "前端页面数据缓存必须携带服务端整页样式");
assert.match(cards, /<ReportPublicFilterControls[\s\S]{0,300}onChange=\{\(publicFilters\) => onChange\?\.\(\{ \.\.\.report, publicFilters \}\)\}/, "可视化报表的公共筛选选择与拖动顺序必须进入报表持久状态");
assert.match(cards, /applyReportPublicFilters\([\s\S]{0,220}visualReportDatasetKey\(card\)/, "公共筛选必须按图表绑定的数据集精确过滤行数据");
assert.match(cards, /return `\$\{card\.dataset\.kind\}:\$\{card\.dataset\.id\}`/, "筛选数据集键必须包含类型，避免不同来源同 ID 串数据");
assert.match(reportPublicFilters, /data-page-public-filter-common-fields="true"[\s\S]*data-page-public-filter-datasets="true"/, "公共筛选弹窗必须上方展示公共字段、下方展示可用数据集");
assert.match(reportPublicFilters, /data-page-public-filter-field-menu="true"/, "公共字段必须支持右键打开操作菜单");
assert.match(reportPublicFilters, /data-page-public-filter-remove-field=\{field\}/, "公共字段右键菜单必须提供删除字段动作");
assert.match(reportPublicFilters, /data-page-public-filter-save-group="true">保存/, "保存分组后必须留在弹窗内继续配置");
assert.match(reportPublicFilters, /data-page-public-filter-confirm="true">确认/, "公共筛选弹窗必须提供确认关闭入口");
assert.match(reportPublicFilters, /draggable=\{editable\}/, "公共筛选控件必须支持在编辑态拖动排序");
assert.match(reportPublicFilters, /moveReportPublicFilterControl/, "公共筛选控件必须支持跨分组拖动并持久化全局位置");
assert.match(reportPublicFilters, /const source = draggingRef\.current \|\| dragging[\s\S]*moveReportPublicFilterControl\(groups, source, target\)/, "公共筛选 drop 必须优先读取同步拖拽身份");
assert.match(reportPublicFilters, /onDragStart=\{\(\) => \{ const source = [^;]+; draggingRef\.current = source; setDragging\(source\); \}\}/, "公共筛选快拖时必须同步登记源控件");
assert.match(pageDataComposer, /const source = draggingRef\.current \|\| dragging[\s\S]*moveReportPublicFilterControl\(controller\.publicFilters, source, target\)/, "页面数据公共筛选 drop 必须优先读取同步拖拽身份");
assert.match(weekly, /useWeeklyDataPreferences/, "经营周报必须使用统一的服务端模块偏好控制器");
assert.match(weeklyAnalysisModules, /set_weekly_data_preferences[\s\S]*keepalive: true/, "周报模块顺序与显示状态必须自动保存到服务端并支持离页续传");
assert.match(application, /set_weekly_data_preferences[\s\S]*_normalize_weekly_data_preferences/, "服务端必须归一化并持久化周报模块顺序与显示状态");
assert.match(library, /upsertVisualReport\(\{ tenantId, userId, report, keepalive: destination === "weekly" \}\)/, "周报内可视化报表变更必须使用离页可续传的保存请求");
assert.match(library, /pendingKeepaliveRef[\s\S]*addEventListener\("pagehide", flush\)[\s\S]*visibilitychange/, "周报内可视化报表必须在离页时立即发送最新快照，不能只等待保存队列");
assert.match(visualReportApi, /keepalive = false[\s\S]*keepalive,/, "可视化报表保存 API 必须透传 keepalive");
assert.match(application, /def _normalize_visual_report_public_filters[\s\S]*visual_report_public_filter_field_unavailable/, "服务端必须重新验证公共字段确实属于所选数据集交集");
assert.match(applicationRoute, /dataset_id_aliases[\s\S]*publicFilters/, "数据文件轮换后公共筛选绑定必须跟随权威数据集身份重绑");
assert.match(apiSupport, /visual_report_public_filter_field_unavailable/, "公共筛选字段失效必须返回可理解的产品错误");
assert.match(cards, /revealVisualFollowUp/);
assert.match(cards, /replaceVisualAnalysisSourceGroup/, "可视化报表必须把当前页全部图表登记为页面 AI 分析数据源");
assert.match(cards, /revealVisualComment/);
assert.match(builder, /showFollowUp=\{false\}/, "新增图表弹窗预览必须隐藏追问");
assert.match(visualCard, /showFollowUp = true/, "落地后的标准图表默认必须显示追问");
assert.match(visualCard, /label="文本框"[\s\S]*data-visual-more-text[\s\S]*data-visual-filter-toggle/, "更多菜单必须在条件前提供文本框");
assert.match(visualCard, /onCreateText/, "文本框必须从复制权限中拆出独立入口");
assert.match(visualCard, /disabled=\{!onCreateText && !onDuplicate\}/, "能看见图表的用户只要有文本框入口即可点击，不得只绑在复制权限上");
assert.match(cards, /onCreateText=\{\(config\) => createTextCard\(card, config\)\}/, "可视化报表浏览态也必须能创建文本框");
assert.doesNotMatch(visualCard, /data-visual-toolbar[\s\S]{0,800}data-visual-filter-toggle/, "工具栏不得再单独放置条件按钮");
assert.match(visualNote, /data-visual-note="true"/, "文本框图表必须复用统一可视化卡片并渲染标题与正文");
assert.match(noteModel, /data-visual-note-term/, "命中数据源字段的文本必须加粗下划线标注");
assert.match(visualNote, /data-visual-note-title-delete="true"/, "文本框标题右侧必须提供延迟显示的删除按钮");
assert.match(visualCard, /data-visual-text-ops-above/, "文本框操作展开必须出现在填写名称上方");
assert.match(visualCard, /VisualNoteTitle/, "填写名称必须与操作按钮同一行");
assert.match(richNote, /contentEditable="true"/, "便签和文本框必须用可见的可编辑正文，不得再用透明 textarea");
assert.doesNotMatch(richNote, /text-transparent/, "便签正文不得使用透明文字");
assert.doesNotMatch(weekly, /WebkitTextFillColor: "transparent"/, "周报文本框不得把填入文字设为透明");
assert.match(richNote, /data-note-bold-action="true"/, "选中文字工具条必须在评论和 AI 分析之间提供加粗");
assert.doesNotMatch(richNote, /data-note-bold-menu/, "不得再用右键加粗下拉框");
assert.match(stickyHook, /function hiddenOnLoad/, "各页面便签必须在进入页面时默认隐藏，点击后才显示");
assert.match(stickyHook, /pendingSave[\s\S]*saveStickyNote\(\{ tenantId, userId, moduleKey, surface, pending, keepalive: true \}\)/, "便签最后一次编辑必须使用离页续传请求");
assert.match(stickyHook, /addEventListener\("pagehide", flush\)[\s\S]*visibilitychange/, "便签最后一次编辑必须在离页时立即冲刷");
assert.match(visualCard, /createPortal\(<div className="fixed z-\[120\] w-32/, "更多菜单必须浮到卡片外，并为保存模板保留足够宽度");
assert.match(noteModel, /text-\[16px\] leading-\[26px\] tracking-\[-0.31px\]/, "正文必须使用 16px / 26px / -0.31px 字距");
assert.match(noteModel, /gap-\[10px\]/, "段落间距必须为 10px");
assert.match(noteModel, /p-5/, "文本框内边距必须为 20px");
assert.match(stickyNote, /data-sticky-note-delete="true"/, "便签右键必须提供删除");
assert.match(stickyHook, /const hide = /, "便签删除必须把面板从页面上收起");
assert.match(standardAnalysisPage, /onHide=\{stickyNote.hide\}/, "标准分析页面便签必须支持右键删除收起");
assert.match(dashboard, /StandardAnalysisPageStickyNote stickyNote=\{stickyNote\}/, "多机构分析必须复用标准便签删除收起能力");
assert.match(supervision, /StandardAnalysisPageStickyNote stickyNote=\{stickyNote\}/, "机构督导必须复用标准便签删除收起能力");
assert.match(weekly, /onHide=\{stickyNote.hide\}/, "经营周报便签必须支持右键删除收起");
assert.match(builder, /<StandardAnalysisPageStickyNote stickyNote=\{stickyNote\}/, "可视化报表便签必须复用支持右键删除收起的标准组件");
assert.match(selfAnalysis, /onHide=\{analysisSticky.hide\}/, "智能分析便签必须支持右键删除收起");
assert.match(cards, /analysisSource=\{\[selectedTable\]\}/, "可视化报表追问必须绑定当前图表数据集");
assert.match(application, /_sanitize_note_html/, "便签加粗 HTML 必须在保存时清洗");
assert.match(domain, /type: "text", label: "文本框"/, "文本框必须作为标准可视化样式出现在样式菜单中");
assert.match(visualCard, /disabled=\{isTextCard\}/, "文本框样式下条件必须灰显");
assert.match(visualCard, /data-visual-operation-toggle="true"/, "文本框可视化必须提供可展开收起的操作按钮");
assert.doesNotMatch(pageDataComposer, /canDeleteOwnVisualCopy\([^\n]+&& <div className="mb-1 flex h-7 shrink-0 items-center justify-end/, "文本框上方不得保留重复的移除按钮");
assert.match(pageDataComposer, /onDelete=\{canDeleteOwnVisualCopy\([^\n]+\? \(\) => removeNote\(note\.id\) : undefined\}/, "文本框必须保留更多菜单中的所有者范围删除能力");
assert.match(standardAnalysisPage, /StickyNoteButton onClick=\{stickyNote.show\}[\s\S]*PageDataModeToggle/, "标准分析页必须在编辑按钮左侧提供便签");
assert.match(dashboard, /StandardAnalysisPageHeader[\s\S]*stickyNote=\{stickyNote\}/, "多机构分析必须复用标准标题栏便签");
assert.match(supervision, /StandardAnalysisPageHeader[\s\S]*stickyNote=\{stickyNote\}/, "机构督导必须复用标准标题栏便签");
assert.match(weekly, /StickyNoteButton onClick=\{stickyNote.show\}/, "经营周报必须在编辑按钮左侧提供便签");
assert.match(weekly, /一、业绩与业务波动[\s\S]*StickyNotePanel/, "经营周报便签必须出现在业绩与业务波动标题下、可视化图表上方");
assert.match(builder, /<StandardAnalysisPageHeader[\s\S]*?stickyNote=\{stickyNote\}[\s\S]*?editController=\{reportEditController\}/, "可视化报表必须在统一页头中按便签、编辑顺序提供操作");
assert.match(builder, /const destinationActions =[\s\S]*data-visual-report-destinations="true"/, "报表沉淀操作必须收敛为统一页头操作组");
assert.match(builder, /<StandardAnalysisPageHeader[\s\S]*?leadingActions=\{destinationActions\}/, "存我的、存经验、存周报必须显示在页面右上角统一页头中");
assert.match(builder, /aria-label="返回报表首页"[\s\S]*?data-visual-report-back="true"[\s\S]*?data-visual-report-title="true"/, "返回报表首页必须显示在可视化报表标题左侧的小型图标按钮中");
assert.doesNotMatch(builder, /<ArrowLeft[^>]*\/>返回报表首页/, "可视化报表统一页头上方不得再显示独立返回文字行");
assert.ok(!builder.includes('description="从空白画布开始编辑当前机构的可视化报表"') && !builder.includes("双击名称编辑，点击其他位置自动保存"), "可视化报表标题下方不得再显示说明与机构元信息");
assert.ok(!builder.includes('const [notice, setNotice]') && !builder.includes("可视化报表已保存。") && !builder.includes("destinationMessage("), "可视化报表保存成功后不得再渲染占位提示条");
assert.match(selfAnalysis, /StickyNoteButton size="compact" onClick=\{analysisSticky.show\}/, "智能分析必须在存周报和导出之间提供便签");
assert.ok(selfAnalysis.includes('label: "源数据"') && selfAnalysis.includes('label: "图表"') && selfAnalysis.includes('label: "AI总结"'), "智能分析结果页签必须使用源数据、图表和 AI 总结");
assert.ok(selfAnalysis.includes('label: "存报表"') && !selfAnalysis.includes(' /> 存我的'), "智能分析保存入口必须把存我的改成存报表");
assert.ok(selfAnalysis.indexOf('label: "存报表"') < selfAnalysis.indexOf('label: "存经验"') && selfAnalysis.indexOf('label: "存经验"') < selfAnalysis.indexOf('label: "存周报"') && selfAnalysis.indexOf('label: "存周报"') < selfAnalysis.indexOf('StickyNoteButton size="compact"') && selfAnalysis.indexOf('StickyNoteButton size="compact"') < selfAnalysis.indexOf("导出"), "智能分析便签必须位于存周报右侧、导出左侧");
assert.ok(selfAnalysis.includes("justify-between") && selfAnalysis.includes("whitespace-nowrap rounded px-2 py-1"), "结果工具栏保存入口必须右对齐，并用紧凑滑块避免变形");
assert.ok(!selfAnalysis.includes('demoFallbackDisabledMessage("分析结果保存")'), "存报表/存周报失败不得再套 demo fallback 文案");
assert.match(selfAnalysis, /isSelfAnalysisNoticeFailure\(saveMessage\)/, "保存失败提示不得再用成功绿色");
assert.match(selfAnalysis, /onLayoutChange=\{\(cardId, size\) => \{[\s\S]{0,280}updateVisualCard\(cardId, \{ config: \{ \.\.\.card\.config, layoutSpan: size\.span, layoutHeight: size\.height \} \}\)/, "当前智能分析图表缩放后必须进入待保存卡片状态");
assert.equal((selfAnalysis.match(/onConfigChange=\{\(config\) => void persistSavedReportVisualizations/g) || []).length, 2, "我的报表中的普通与精选分析结果都必须把样式修改立即保存到服务端");
assert.equal((selfAnalysis.match(/onLayoutChange=\{\(cardId, size\) => \{[\s\S]{0,260}persistSavedReportVisualizations/g) || []).length, 2, "我的报表中的普通与精选分析结果都必须持久化缩放结果");
assert.match(application, /set_page_sticky_note/, "应用模块必须提供统一便签保存动作");
assert.match(visualCard, /\{showFollowUp && <button[\s\S]*data-visual-follow-up="true"/, "追问按钮显示应由标准图表契约控制");
for (const label of ["评论", "AI 分析", "留言板"]) assert.ok(contextRail.includes(label), `追问右侧栏必须保留${label}`);
assert.match(library, /destination: Extract<VisualReportDestination, "mine" \| "weekly">/);
assert.ok(!library.includes("window.confirm"), "可视化报表删除不得使用浏览器原生确认框");
assert.match(library, /data-visual-report-delete-dialog="true"/, "可视化报表删除必须使用系统风格确认弹窗");
assert.match(selfAnalysis, />精选<\/button>/);
assert.match(selfAnalysis, />智能分析<\/button>/);
assert.match(selfAnalysis, />可视化报表<\/button>/);
assert.match(selfAnalysis, /data-featured-report-star="analysis"/);
assert.match(selfAnalysis, /defaultMyReportsTab\(live\.length > 0\)/);
assert.match(library, /data-featured-report-star="visual"/);
assert.match(library, /featuredReports\.toggle\("visual", report\.id\)/);
assert.match(featuredReports, /export function defaultMyReportsTab/);
assert.match(featuredReports, /hasFeatured \? "featured" : "analysis"/);
assert.match(featuredReports, /smart_data_agent_featured_reports_v1/);
assert.ok(!featuredReports.includes("sample_report"), "精选列表不得写入样例报表");
assert.match(dataTablePicker, /type="radio"/, "智能分析数据表必须使用单选控件");
assert.match(dataTablePicker, /onChange\(\[table\]\)/, "选择新表必须替换而不是追加已有数据源");
assert.doesNotMatch(dataTablePicker, /多机构页面|pageDataTables|pageDataToSelection/, "智能分析数据表弹窗不得显示多机构页面");
assert.match(domain, /singleAnalysisDataTableSelection[\s\S]*tables\.at\(-1\)/, "历史或外部多选状态必须收敛到最新一张数据表");
assert.match(domain, /export function rematchAnalysisDataTableSelection/, "已选数据表必须能按 sourceKey 对齐当前交付");
assert.doesNotMatch(domain, /if \(!matched && table\.contentHash\) \{[\s\S]*?item\.contentHash === table\.contentHash/, "站内数据表不得仅凭内容 Hash 跨相对路径重绑定");
assert.match(domain, /if \(!matched && table\.kind !== "raw" && table\.code\)/, "原始表不得按代码或标题跨路径替换，主题与页面数据仍保留稳定代码兼容");
assert.match(domain, /analysisTableLogicalTitle/, "已选数据表必须能按交付题目对齐当前文件，找不到时不得继续使用下线表");
assert.match(selfAnalysis, /singleAnalysisDataTableSelection\(forcedDataTables \?\? selectedDataTables\)/, "每次分析提交前必须再次收敛单表契约");
const handleQuerySource = selfAnalysis.match(/const handleQuery = async \([\s\S]*?\n  realtimeVoiceAutoAnalyzeRef\.current/)?.[0] || "";
assert.ok(handleQuerySource, "必须能定位智能分析提交函数");
assert.doesNotMatch(handleQuerySource, /forceRefresh: true/, "点击提交的关键路径不得等待数据目录强制刷新");
assert.match(handleQuerySource, /if \(isAnalyzingRef\.current\) return;/, "同步双击和程序化重复提交必须被执行态引用拦截");
assert.ok(
  handleQuerySource.indexOf('setAnalysisSubmissionPhase("submitting")') < handleQuerySource.indexOf("waitForSelfAnalysis({"),
  "点击反馈与重复提交锁必须先于分析入队请求",
);
assert.match(selfAnalysis, /data-analysis-submit-feedback=\{activeSubmissionPhase\}/, "提交按钮必须提供可见且可访问的即时状态反馈");
assert.match(selfAnalysis, /data-analysis-submit-phase=\{activeSubmissionPhase\}/, "提交按钮必须暴露提交、排队和执行状态");
assert.match(analysisRoute, /page_context = _preflight_analysis_page_context\([\s\S]*?automation_runtime\.trigger\(/, "服务端必须在分析入队前权威解析租户、权限和数据表引用");
assert.match(selfAnalysis, /rematchAnalysisDataTableSelection\(snapshot.selectedDataTables, analysisCatalogRef.current\)/, "恢复工作台时必须把缓存数据表对齐到当前目录");
assert.match(selfAnalysis, /runtimeAssetResponse\.topic_tables/, "智能分析主题表必须使用已发布 runtime 目录");
assert.match(selfAnalysis, /rematchAnalysisDataTableSelection\(current/, "恢复或刷新目录后必须把已选表对齐到当前交付");
assert.match(analysisRoute, /consumer="self_analysis"/, "智能分析必须通过受治理的多机构页面读取接口取数");
assert.match(builder, />原始表 \{rawTables.length\}<\/button>/, "可视化报表弹窗必须提供原始表");
assert.match(builder, />主题表 \{topicTables.length\}<\/button>/, "可视化报表弹窗必须提供主题表");
assert.doesNotMatch(builder, /多机构页面 \{pageDataTables\.length\}|单机构页面|switchTab\("page_data"\)/, "可视化报表新增图表弹窗不得显示多机构页面或单机构页面");
assert.match(builder, /pageCode: "visual_report"/, "可视化报表编辑器必须按自身消费者身份读取多机构页面");
assert.match(cards, /railPageKey === "my-reports" \? "my_reports" : "visual_report"/, "我的报表回读可视化报表时必须重新校验多机构页面授权");
assert.match(cards, /resolveVisualReportRawTable\(card\.dataset, rawTables\)/, "我的报表必须按稳定来源重绑原始表，而不是死盯一次交付文件 ID");
assert.match(cards, /catalog\.status === "loading"/, "可视化目录尚未就绪时必须等待，不得把空目录当成表已消失");
assert.match(cards, /visualReportCardHasData/, "浏览态必须按是否有数据决定是否渲染图表");
assert.match(cards, /visibleCards.filter\(\(card\) => visualReportCardHasData/, "浏览态没有数据的图表必须整卡不渲染");
assert.doesNotMatch(cards, /数据集不存在、无权限或 Schema 已变化/, "不得把轮转后的交付文件 ID 直接判成数据集不存在");
assert.match(library, /empty:hidden/, "我的报表展开后若无图表不得留下空白底栏");
assert.match(selfAnalysis, /analysisRows.length \? \(\s*<ResizableVisualizationGrid(?:\s[^>]*)?>/, "智能分析浏览态没有数据时不得挂载空白图表");
assert.match(visualCard, /if \(!rows.length \|\| !metricFields.length\) return null/, "没有数据时图表区域必须整块不渲染，不得保留空态占位");
assert.match(reportData, /export function resolveVisualReportRawTable/, "原始表回读必须有独立的重绑入口");
assert.match(reportData, /uniqueRawTablesByLogicalTitle/, "历史报表必须能按去掉交付日期后的题目重绑当前 CSV");
assert.match(reportData, /visualReportLogicalTitleCandidate/, "csv_hash 不得当作业务题目参与重绑");
assert.match(applicationRoute, /def _resolve_visual_report_raw_source/, "保存可视化报表时必须按 sourceKey / 文件 ID / 题目重绑当前交付");
assert.match(selfAnalysis, /已保存到我的报表「智能分析」/, "智能分析存报表必须明确落到我的报表智能分析页签");
function analysisTableLogicalTitle(value) {
  const stem = String(value || "").trim().replace(/\.csv$/i, "");
  const withoutPrefix = stem.replace(/^\d{8}(?:_\d{6})?_/, "");
  const withoutSuffix = withoutPrefix.replace(/_\d{4}-\d{2}-\d{2}(?:_历史数据)?$/, "");
  const title = withoutSuffix.split("/").pop() || withoutSuffix;
  return title.replace(/[\s_\-./]+/g, "").toLocaleLowerCase();
}
assert.equal(analysisTableLogicalTitle("标品双周会周度sql_2026-08-14"), analysisTableLogicalTitle("标品双周会周度sql_2026-05-06"));
assert.equal(analysisTableLogicalTitle("标品双周会周度sql_2026-08-14"), "标品双周会周度sql");
assert.equal(analysisTableLogicalTitle("标品双周会周度sql_2026-05-06_历史数据"), "标品双周会周度sql");
assert.match(domain, /export function analysisTableLogicalTitle\(value: string\)/, "题目归一化实现必须与报表重绑契约一致");
assert.match(reportsRoute, /topic_data_store\.read_reference/, "我的报表智能分析 Tab 必须从分析执行的受治理快照回读数据");

assert.match(application, /"upsert_visual_report", "delete_visual_report"/);
assert.match(application, /"visualReports": \[\]/);
assert.doesNotMatch(application, /next_state\["visualReports"\].*rows/s, "可视化报表状态不能持久化原始数据行");
assert.match(applicationRoute, /visual_report_dataset_unavailable/);
assert.match(applicationRoute, /"schemaFingerprint"/);
assert.match(productionAssetStore, /UPDATE platform_data_asset_items[\s\S]*?RETURNING asset_item_id, payload/, "主题候选删除必须返回归档所需的 payload");

console.log("visual report workbench contract passed");
