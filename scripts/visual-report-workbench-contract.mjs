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
assert.match(builder, /openReport\(newVisualReport\(\), "edit"\)/, "新建报表必须直接进入编辑态");
assert.match(builder, /savedSignatureRef\.current = reportSignature\(selected\)/, "二次编辑必须沿用原报表 ID 与保存签名");
assert.match(builder, /mode === "browse" \? "编辑" : "保存"/, "编辑态按钮必须显示保存");
assert.match(builder, /const saved = await persistReport\(report\)/, "退出编辑态前必须保存当前报表");
assert.match(builder, /navigate\("\/self-analysis\/reports"\)/, "存我的后必须进入我的报表");
assert.match(builder, /WHERE :tenant_id IS NOT NULL/, "存主题必须保留显式租户绑定 SQL 契约");
assert.match(builder, /onDoubleClick=\{\(\) => setEditingTitle\(true\)\}/);
assert.match(builder, /onBlur=\{commitTitle\}/);
assert.match(builder, /data-add-visual-report-chart="true"/);
assert.match(builder, />取消<\/button>/);
assert.match(builder, /data-visual-report-restore="true"/);
assert.match(builder, />保存<\/button>/);
assert.ok(builder.indexOf(">取消</button>") < builder.indexOf("data-visual-report-restore") && builder.indexOf("data-visual-report-restore") < builder.indexOf(">保存</button>"), "新增图表底部按钮必须按取消、恢复、保存排列");
assert.match(builder, /Record<string, VisualChartDraft>/, "未保存图表配置必须按数据集隔离保留");
assert.match(builder, /visualDatasetDraftKey\(dataset\)/, "原始表和主题表切换后必须按数据集恢复草稿");
assert.match(builder, /setVisualChartDrafts\(\{\}\)/, "恢复必须清空本次新增流程的图表草稿");
const draftType = builder.match(/type VisualChartDraft = \{([\s\S]*?)\};/)?.[1] || "";
assert.ok(draftType && !draftType.includes("rows"), "图表草稿不能缓存授权数据行");
for (const label of ["存我的", "存经验", "存周报"]) assert.ok(builder.includes(`label="${label}"`));
assert.ok(!builder.includes('label="存主题"'), "可视化报表不得保留存主题按钮");
assert.match(builder, /if \(destination !== "topic"\) await saveAsTopic\(/, "三个保存入口必须自动沉淀对应 SQL 到主题表");

assert.match(cards, /AnalysisVisualCard/);
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
assert.match(visualCard, /createPortal\(<div className="fixed z-\[120\] w-28/, "更多菜单必须浮到卡片外，避免被工具条裁切");
assert.match(noteModel, /text-\[16px\] leading-\[26px\] tracking-\[-0.31px\]/, "正文必须使用 16px / 26px / -0.31px 字距");
assert.match(noteModel, /gap-\[10px\]/, "段落间距必须为 10px");
assert.match(noteModel, /p-5/, "文本框内边距必须为 20px");
assert.match(stickyNote, /data-sticky-note-delete="true"/, "便签右键必须提供删除");
assert.match(stickyHook, /const hide = /, "便签删除必须把面板从页面上收起");
assert.match(standardAnalysisPage, /onHide=\{stickyNote.hide\}/, "标准分析页面便签必须支持右键删除收起");
assert.match(dashboard, /StandardAnalysisPageStickyNote stickyNote=\{stickyNote\}/, "多机构分析必须复用标准便签删除收起能力");
assert.match(supervision, /StandardAnalysisPageStickyNote stickyNote=\{stickyNote\}/, "机构督导必须复用标准便签删除收起能力");
assert.match(weekly, /onHide=\{stickyNote.hide\}/, "经营周报便签必须支持右键删除收起");
assert.match(builder, /onHide=\{stickyNote.hide\}/, "可视化报表便签必须支持右键删除收起");
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
assert.match(builder, /StickyNoteButton onClick=\{stickyNote.show\}/, "可视化报表必须在存周报和保存之间提供便签");
assert.ok(builder.indexOf('<DestinationButton label="存周报"') < builder.indexOf("<StickyNoteButton onClick={stickyNote.show}") && builder.indexOf("<StickyNoteButton onClick={stickyNote.show}") < builder.indexOf("data-visual-report-mode-toggle"), "可视化报表便签必须位于存周报右侧、保存左侧");
assert.match(selfAnalysis, /StickyNoteButton size="compact" onClick=\{analysisSticky.show\}/, "智能分析必须在存周报和导出之间提供便签");
assert.ok(selfAnalysis.includes('label: "源数据"') && selfAnalysis.includes('label: "图表"') && selfAnalysis.includes('label: "AI总结"'), "智能分析结果页签必须使用源数据、图表和 AI 总结");
assert.ok(selfAnalysis.includes('label: "存报表"') && !selfAnalysis.includes(' /> 存我的'), "智能分析保存入口必须把存我的改成存报表");
assert.ok(selfAnalysis.indexOf('label: "存报表"') < selfAnalysis.indexOf('label: "存经验"') && selfAnalysis.indexOf('label: "存经验"') < selfAnalysis.indexOf('label: "存周报"') && selfAnalysis.indexOf('label: "存周报"') < selfAnalysis.indexOf('StickyNoteButton size="compact"') && selfAnalysis.indexOf('StickyNoteButton size="compact"') < selfAnalysis.indexOf("导出"), "智能分析便签必须位于存周报右侧、导出左侧");
assert.ok(selfAnalysis.includes("justify-between") && selfAnalysis.includes("whitespace-nowrap rounded px-2 py-1"), "结果工具栏保存入口必须右对齐，并用紧凑滑块避免变形");
assert.ok(!selfAnalysis.includes('demoFallbackDisabledMessage("分析结果保存")'), "存报表/存周报失败不得再套 demo fallback 文案");
assert.match(selfAnalysis, /isSelfAnalysisNoticeFailure\(saveMessage\)/, "保存失败提示不得再用成功绿色");
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
assert.match(selfAnalysis, /analysisRows.length \? \(\s*<ResizableVisualizationGrid>/, "智能分析浏览态没有数据时不得挂载空白图表");
assert.match(visualCard, /if \(!rows.length \|\| !metricFields.length\) return null/, "没有数据时图表区域必须整块不渲染，不得保留空态占位");
assert.match(reportData, /export function resolveVisualReportRawTable/, "原始表回读必须有独立的重绑入口");
assert.match(reportData, /uniqueRawTablesByLogicalTitle/, "历史报表必须能按去掉交付日期后的题目重绑当前 CSV");
assert.match(reportData, /visualReportLogicalTitleCandidate/, "csv_hash 不得当作业务题目参与重绑");
assert.match(applicationRoute, /def _resolve_visual_report_raw_source/, "保存可视化报表时必须按 sourceKey / 文件 ID / 题目重绑当前交付");
assert.match(selfAnalysis, /已保存到我的报表「智能分析」/, "智能分析存报表必须明确落到我的报表智能分析页签");
function analysisTableLogicalTitle(value) {
  const stem = String(value || "").trim().replace(/\.csv$/i, "");
  const withoutPrefix = stem.replace(/^\d{8}(?:_\d{6})?_/, "");
  const withoutSuffix = withoutPrefix.replace(/_\d{4}-\d{2}-\d{2}$/, "");
  const title = withoutSuffix.split("/").pop() || withoutSuffix;
  return title.replace(/[\s_\-./]+/g, "").toLocaleLowerCase();
}
assert.equal(analysisTableLogicalTitle("标品双周会周度sql_2026-08-14"), analysisTableLogicalTitle("标品双周会周度sql_2026-05-06"));
assert.equal(analysisTableLogicalTitle("标品双周会周度sql_2026-08-14"), "标品双周会周度sql");
assert.match(domain, /export function analysisTableLogicalTitle\(value: string\)/, "题目归一化实现必须与报表重绑契约一致");
assert.match(reportsRoute, /topic_data_store\.read_reference/, "我的报表智能分析 Tab 必须从分析执行的受治理快照回读数据");

assert.match(application, /"upsert_visual_report", "delete_visual_report"/);
assert.match(application, /"visualReports": \[\]/);
assert.doesNotMatch(application, /next_state\["visualReports"\].*rows/s, "可视化报表状态不能持久化原始数据行");
assert.match(applicationRoute, /visual_report_dataset_unavailable/);
assert.match(applicationRoute, /"schemaFingerprint"/);
assert.match(productionAssetStore, /UPDATE platform_data_asset_items[\s\S]*?RETURNING asset_item_id, payload/, "主题候选删除必须返回归档所需的 payload");

console.log("visual report workbench contract passed");
