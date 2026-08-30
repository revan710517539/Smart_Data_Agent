import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const sourcePath = new URL("../src/app/components/visualization/visualizationCommand.ts", import.meta.url);
const source = await readFile(sourcePath, "utf8");
const visualCardSource = await readFile(new URL("../src/app/components/self-analysis/ResultViews.tsx", import.meta.url), "utf8");
const visualDataModelSource = await readFile(new URL("../src/app/components/visualization/visualizationDataModel.ts", import.meta.url), "utf8");
const tableProgressDialogSource = await readFile(new URL("../src/app/components/visualization/TableProgressDialog.tsx", import.meta.url), "utf8");
const calculatedColumnDialogSource = await readFile(new URL("../src/app/components/visualization/TableCalculatedColumnDialog.tsx", import.meta.url), "utf8");
const tableTemplateGallerySource = await readFile(new URL("../src/app/components/visualization/TableTemplateGallery.tsx", import.meta.url), "utf8");
const tableStyleTemplatesSource = await readFile(new URL("../src/app/components/visualization/tableStyleTemplates.ts", import.meta.url), "utf8");
const chartTemplateGallerySource = await readFile(new URL("../src/app/components/visualization/ChartTemplateGallery.tsx", import.meta.url), "utf8");
const chartStyleTemplatesSource = await readFile(new URL("../src/app/components/visualization/chartStyleTemplates.ts", import.meta.url), "utf8");
const tableTemplatesCssSource = await readFile(new URL("../src/styles/table-templates.css", import.meta.url), "utf8");
const visualGridSource = await readFile(new URL("../src/app/components/self-analysis/ResizableVisualizationGrid.tsx", import.meta.url), "utf8");
const visualGridLayoutSource = await readFile(new URL("../src/app/components/self-analysis/visualGridLayout.ts", import.meta.url), "utf8");
const analysisWorkspaceSource = await readFile(new URL("../src/app/components/analysis-workspace/AnalysisWorkspaceRail.tsx", import.meta.url), "utf8");
const voiceSource = await readFile(new URL("../src/app/components/visualization/useVisualizationVoiceCommand.ts", import.meta.url), "utf8");
const tableSortSource = await readFile(new URL("../src/app/components/visualization/tableSort.ts", import.meta.url), "utf8");
const messageBoardSource = await readFile(new URL("../src/app/components/message-board/MessageBoardPanel.tsx", import.meta.url), "utf8");
const workbenchPersistenceSource = await readFile(new URL("../src/app/components/self-analysis/useSelfAnalysisWorkbenchPersistence.ts", import.meta.url), "utf8");
const selfAnalysisSource = await readFile(new URL("../src/app/components/SelfAnalysis.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { classifyVisualVoiceIntent, moveVisualizationField, resolveVisualizationVoiceCommand } = await import(moduleUrl);
const visualDataModelCompiled = ts.transpileModule(visualDataModelSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const visualDataModelModuleUrl = `data:text/javascript;base64,${Buffer.from(visualDataModelCompiled).toString("base64")}`;
const { associationRuleMatches, compileVisualizationFormula, normalizeCalculatedColumns, normalizeMetricFormats, normalizeMetricProgress, normalizeVisualizationChartStyle, normalizeVisualizationTableStyle, ordinalRanks, progressPercentage, resolveProgressDenominator, visualizationRoleFields } = await import(visualDataModelModuleUrl);
const visualGridLayoutCompiled = ts.transpileModule(visualGridLayoutSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const visualGridLayoutModuleUrl = `data:text/javascript;base64,${Buffer.from(visualGridLayoutCompiled).toString("base64")}`;
const { defaultVisualGridSpan, packVisualGridItems } = await import(visualGridLayoutModuleUrl);
const tableSortCompiled = ts.transpileModule(tableSortSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const tableSortModuleUrl = `data:text/javascript;base64,${Buffer.from(tableSortCompiled).toString("base64")}`;
const { nextTableSortState, sortTableRows } = await import(tableSortModuleUrl);

assert.deepEqual(
  resolveVisualizationVoiceCommand(
    "请改成折线图，用放款金额作为指标，按日期作为维度并显示数据",
    ["field_2", "field_3"],
    ["field_1"],
    { field_1: "日期", field_2: "总完件", field_3: "放款金额" },
  ),
  { visualizationType: "line", metricField: "field_3", dimensionField: "field_1", dataVisibility: "shown" },
);
assert.equal(resolveVisualizationVoiceCommand("隐藏数值", [], [], {}).dataVisibility, "hidden");
assert.equal(resolveVisualizationVoiceCommand("按照放款金额展示趋势图", ["field_3"], ["field_1"], { field_1: "日期", field_3: "放款金额" }).metricField, "field_3", "直接说指标中文名时必须命中字段");
assert.equal(resolveVisualizationVoiceCommand("按照放款金额展示趋势图", ["field_3"], ["field_1"], { field_1: "日期", field_3: "放款金额" }).visualizationType, "line", "趋势图必须映射为折线图");
assert.equal(resolveVisualizationVoiceCommand("先改成表格，随后按照放款金额展示趋势图", ["field_3"], ["field_1"], { field_1: "日期", field_3: "放款金额" }).visualizationType, "line", "累计语音文本必须以最后一次样式要求为准");
assert.deepEqual(moveVisualizationField(["field_2", "field_3", "field_4"], "field_2", "field_4"), ["field_3", "field_4", "field_2"]);
assert.equal(classifyVisualVoiceIntent("改成折线图", "chart").mode, "chart_control", "非文本可视化实时语音必须走图表形态控制");
assert.equal(classifyVisualVoiceIntent("记下这段口径", "text").mode, "textbox_record", "文本框实时语音在记录意图下不得触发分析");
assert.deepEqual(classifyVisualVoiceIntent("分析一下放款为什么下降", "text"), { mode: "textbox_record", analysisKinds: [] }, "文本框口述内容即使含分析词也只能转写，不能静默启动模型");
assert.ok(visualCardSource.includes('data-visual-text-voice="true"') && visualCardSource.includes("正在将语音转写到文本框") && !visualCardSource.includes("textbox_analyze") && !visualCardSource.includes("runTextCardVoiceAnalysis") && !visualCardSource.includes("waitForSelfAnalysis"), "文本框必须提供独立实时语音转写入口，且不得保留第二条分析链");
assert.deepEqual(moveVisualizationField(["field_2", "field_3"], "missing", "field_3"), ["field_2", "field_3"]);
const sortRows = [{ raw: { amount: 20 } }, { raw: { amount: 5 } }, { raw: { amount: 20 } }];
const ascending = nextTableSortState(null, "amount");
const descending = nextTableSortState(ascending, "amount");
assert.deepEqual(sortTableRows(sortRows, ascending).map((row) => row.raw.amount), [5, 20, 20], "首次点击表头必须正排且同值稳定");
assert.deepEqual(sortTableRows(sortRows, descending).map((row) => row.raw.amount), [20, 20, 5], "第二次点击表头必须倒排");
assert.equal(nextTableSortState(descending, "amount"), null, "第三次点击表头必须恢复原始顺序");
assert.strictEqual(sortTableRows(sortRows, null), sortRows, "复原状态不得复制或修改源数据行");
const rankedRows = [{ id: "a", value: 20 }, { id: "b", value: 5 }, { id: "c", value: 20 }];
assert.deepEqual(rankedRows.map((row) => ordinalRanks(rankedRows, (item) => item.value, "desc").get(row)), [1, 3, 2], "从大到小必须按稳定的一位序号从 1 排列");
assert.deepEqual(rankedRows.map((row) => ordinalRanks(rankedRows, (item) => item.value, "asc").get(row)), [2, 1, 3], "从小到大必须以最小值为 1 并保持同值稳定");
const progressRows = [
  { branch: "华东", raw: { branch: "华东", month: "2026-08", amount: 80 } },
  { branch: "华北", raw: { branch: "华北", month: "2026-08", amount: 100 } },
];
const progressConfig = normalizeMetricProgress([{ metricField: "amount", denominatorRules: [{ id: "d1", field: "branch", operator: "in", values: ["华北"] }], color: "#C3D8F4", colorEnd: "#6F9ED8", colorMode: "gradient", associationRules: [{ id: "a1", source: "progress", operator: "gte", threshold: 80, targetField: "amount", style: "value", color: "#FFF1B8", replacementValue: "达标" }] }], ["amount"])[0];
const denominator = resolveProgressDenominator(progressRows, progressConfig);
assert.equal(denominator.status, "ready", "分母维度组合必须唯一命中一行");
assert.equal(progressPercentage(80, denominator.value), 80, "进度必须使用当前指标值除以唯一分母行同指标值");
assert.equal(associationRuleMatches(progressConfig.associationRules[0], 80, 80), true, "关联规则必须独立按进度条件计算");
assert.equal(progressConfig.colorEnd, "#6f9ed8", "进度渐变终点颜色必须归一化保存");
assert.equal(progressConfig.colorMode, "gradient", "进度填充模式必须归一化保存");
assert.equal(normalizeMetricProgress([{ ...progressConfig, colorMode: "reverse_gradient" }], ["amount"])[0].colorMode, "reverse_gradient", "反向渐变模式必须跨配置归一化保留");
assert.equal(progressConfig.associationRules[0].replacementValue, "达标", "关联规则枚举显示值必须保存");
assert.equal(resolveProgressDenominator(progressRows, { ...progressConfig, denominatorRules: [] }).status, "incomplete", "未指定分母必须失败关闭");
assert.equal(resolveProgressDenominator(progressRows, { ...progressConfig, denominatorRules: [{ id: "d2", field: "month", operator: "in", values: ["2026-08"] }] }).status, "multiple", "分母组合命中多行时必须失败关闭");
const columnMaxProgress = normalizeMetricProgress([{ metricField: "amount", denominatorMode: "column_max", denominatorRules: [], color: "#5A9BD5", colorEnd: "#D7E8F6", associationRules: [] }], ["amount"])[0];
assert.equal(columnMaxProgress.denominatorMode, "column_max", "精选模板的按列最大值模式必须被规范化保留");
assert.deepEqual(resolveProgressDenominator(progressRows, columnMaxProgress, [80, 100, 120]), { status: "ready", matches: [], value: 120 }, "按列最大值数据条必须从当前表格值确定 100% 基准");
assert.equal(resolveProgressDenominator(progressRows, columnMaxProgress, [-10, -5]).status, "non_positive", "仅含负值的列不得伪造正向数据条基准");
const caseFormula = compileVisualizationFormula("CASE WHEN [amount] > 0 THEN SUM([amount], [fee]) / 2 ELSE 0 END", ["amount", "fee"]);
assert.equal(caseFormula.error, null, "CASE WHEN 与 SUM 组合公式必须通过安全解析");
assert.deepEqual(caseFormula.evaluate({ amount: 80, fee: 20 }), { value: 50, error: null }, "计算列必须逐行使用当前指标值求值");
assert.equal(compileVisualizationFormula("[放款金额] / 2", ["amount"], { amount: "放款金额" }).evaluate({ amount: 80 }).value, 40, "计算公式必须支持表格中显示的指标名并映射到权威字段");
assert.equal(compileVisualizationFormula("AVERAGE([amount], [fee])", ["amount", "fee"]).evaluate({ amount: 80, fee: 20 }).value, 50, "AVERAGE 必须返回有效平均值");
assert.equal(compileVisualizationFormula("COUNT([amount], [fee])", ["amount", "fee"]).evaluate({ amount: 80, fee: null }).value, 1, "COUNT 必须只统计非空指标");
assert.match(compileVisualizationFormula("[unknown] + 1", ["amount"]).error || "", /不在当前表格中/, "公式不得引用当前表格之外的指标");
assert.match(compileVisualizationFormula("[amount] / 0", ["amount"]).evaluate({ amount: 80 }).error || "", /除数不能为 0/, "除零必须失败关闭");
assert.deepEqual(normalizeCalculatedColumns([{ id: "column-1", name: "收益率", position: 3, expression: "[amount] / [fee]" }, { id: "column-1", name: "重复", position: 4, expression: "0" }]), [{ id: "column-1", name: "收益率", position: 3, expression: "[amount] / [fee]" }], "计算列配置必须去重并有界保存");
const normalizedTableStyle = normalizeVisualizationTableStyle({ templateId: "custom", headerBackground: "bad", headerTextColor: "#ffffff", fontFamily: "unknown", density: "compact", bandedRows: false, emphasizeFirstColumn: true });
assert.equal(normalizedTableStyle.headerBackground, "#F5FAF7", "非法表头颜色必须回退到系统样式");
assert.equal(normalizedTableStyle.headerTextColor, "#ffffff", "合法表格颜色必须归一化");
assert.equal(normalizedTableStyle.fontFamily, "system", "非法字体枚举不得进入渲染层");
assert.equal(normalizedTableStyle.density, "compact", "紧凑密度必须被保留");
assert.equal(normalizedTableStyle.bandedRows, false, "模板必须能关闭隔行底色");
const normalizedChartStyle = normalizeVisualizationChartStyle({ templateId: "chart-test", palette: ["#123456", "#abcdef"], fontFamily: "unknown", chartHeight: "expanded", lineWidth: 99, areaOpacity: -1 });
assert.deepEqual(normalizedChartStyle.palette, ["#123456", "#abcdef"], "图表模板必须保留至少两个合法主题色");
assert.equal(normalizedChartStyle.fontFamily, "system", "非法图表字体枚举不得进入渲染层");
assert.equal(normalizedChartStyle.chartHeight, "expanded", "图表模板必须支持紧凑、标准和扩展高度");
assert.equal(normalizedChartStyle.lineWidth, 4, "图表线宽必须在共享配置中有界保存");
assert.equal(normalizedChartStyle.areaOpacity, 0, "图表面积透明度必须在共享配置中有界保存");
assert.deepEqual(normalizeMetricFormats([{ metricField: "amount", percent: true, decimalPlaces: 12 }, { metricField: "missing", percent: true }], ["amount"]), [{ metricField: "amount", percent: true, decimalPlaces: 8 }], "指标百分比和小数位必须限于当前指标且位数限定为 0 到 8");

const followUpIndex = visualCardSource.indexOf(">追问</button>");
const operationTrayIndex = visualCardSource.indexOf("data-visual-operation-tray=");
const operationButtonIndex = visualCardSource.indexOf("><SlidersHorizontal");
assert.ok(followUpIndex >= 0 && followUpIndex < operationTrayIndex && operationTrayIndex < operationButtonIndex, "操作子按钮必须位于追问和操作之间");
assert.equal((visualCardSource.match(/tabIndex=\{operationsOpen \? 0 : -1\}/g) || []).length, 4, "操作托盘必须只保留样式、指标、维度和语音四个子按钮");
assert.ok(!visualCardSource.includes('data-visual-panel-trigger="template"'), "表格样式模板不得继续占用顶部工具栏");
const styleTemplateIndex = visualCardSource.indexOf('label="样式模板"');
const saveTemplateIndex = visualCardSource.indexOf('label="保存模板"');
assert.ok(styleTemplateIndex >= 0 && saveTemplateIndex > styleTemplateIndex && visualCardSource.includes('isTableCard ? "data-table-style-template" : "data-chart-style-template"') && visualCardSource.includes('dataAttr="data-save-table-template"'), "样式模板必须在所有非文本图表的更多菜单中显示，表格保存模板仍紧邻其下");
assert.equal((chartStyleTemplatesSource.match(/chart\("chart-/g) || []).length, 10, "非表格图表必须固定提供十个独立样式模板");
assert.ok(chartTemplateGallerySource.includes('data-chart-template-gallery="true"') && chartTemplateGallerySource.includes('data-chart-template-built-in=') && chartTemplateGallerySource.includes("只调整图形、配色、字体、留白与尺寸，保留当前数据和交互"), "图表模板必须使用独立浮层缩略图并明确只复制样式");
assert.ok(visualCardSource.includes("chartStyle={chartStyle}") && visualCardSource.includes("normalizeVisualizationChartStyle(chartStyle)") && visualCardSource.includes("normalizedChartStyle.palette"), "全部非表格图形必须从同一图表样式配置读取主题色和几何参数");
assert.equal((tableStyleTemplatesSource.match(/id: "(?:excel|tabulator|handsontable|datatables)-/g) || []).length, 10, "经典模板库必须固定提供十个独立样式");
assert.ok(tableTemplateGallerySource.includes('data-table-template-gallery="true"') && tableTemplateGallerySource.includes("经典样式") && tableTemplateGallerySource.includes("自定义表格样式") && tableTemplateGallerySource.includes("仅复制样式与规则，保留当前表格数据"), "模板下拉必须用缩略图分开展示经典和自定义样式，并说明不复制数据");
assert.ok(tableTemplateGallerySource.includes('className="fixed z-[180]') && tableTemplateGallerySource.includes('h-2.5') && tableTemplateGallerySource.includes('h-1.5'), "样式模板必须使用页面级浮层和半高紧凑缩略图");
assert.ok(tableTemplateGallerySource.includes('max-h-[min(900px,calc(100vh-80px))]') && tableTemplateGallerySource.includes('data-table-template-scroll="true"') && tableTemplateGallerySource.includes("overflow-y-auto"), "模板弹层必须以参考图高度为上限并只在内容区滚动");
assert.ok(tableStyleTemplatesSource.includes('bankPerformanceTemplateId = "featured-bank-performance-ranking"') && tableStyleTemplatesSource.includes('name: "银行经营排名"') && tableStyleTemplatesSource.includes('denominatorMode: "column_max"') && tableTemplateGallerySource.includes('data-table-template-featured='), "自定义区必须内置可应用到当前字段的银行经营排名模板及按列最大值数据条规则");
assert.ok(visualCardSource.includes("createBankPerformanceTableTemplate(metricFields, dimensionFields, fieldLabels)") && visualCardSource.includes("featuredTemplates={featuredTableTemplates}"), "多维表和交叉表必须通过同一模板映射入口生成精选模板");
assert.ok(!visualCardSource.includes("已应用自定义模板：") && !visualCardSource.includes("已应用模板：") && !visualCardSource.includes("已应用图表模板：") && !visualCardSource.includes("已随页面皮肤应用图表模板："), "应用表格、图表或页面皮肤模板后不得在图表内显示成功提示横条");
assert.ok(tableStyleTemplatesSource.includes("sourceMetricFields") && tableStyleTemplatesSource.includes("sourceDimensionFields") && tableStyleTemplatesSource.includes("fieldLabels") && tableStyleTemplatesSource.includes("compileVisualizationFormula") && !/\brows\s*:/.test(tableStyleTemplatesSource), "自定义模板必须通过字段映射复制规则且不得保存数据行");
assert.ok(tableStyleTemplatesSource.includes("sda:table-templates:v1") && tableStyleTemplatesSource.includes("tenantId") && tableStyleTemplatesSource.includes("userId") && tableStyleTemplatesSource.includes("slice(0, 20)"), "自定义模板必须按租户和用户隔离并限制数量");
assert.ok(visualCardSource.includes('data-progress-data-bar="true"') && visualCardSource.includes('data-progress-data-bar-track="true"') && tableTemplatesCssSource.includes('[data-progress-data-bar-track="true"]'), "进度必须使用单元格内嵌数据条，不得再整格铺色");
assert.ok(visualCardSource.includes('data-visual-table-theme="true"') && visualCardSource.includes("tableThemeVariables") && tableTemplatesCssSource.includes("--sda-table-header-bg") && tableTemplatesCssSource.includes('data-table-total-row="true"'), "普通表与交叉表必须使用同一组主题令牌渲染表头、正文和总计");
assert.ok(visualCardSource.includes('rounded-full bg-[#f0f6f2]') && visualCardSource.includes('rounded-full px-2 text-[11px]'), "操作子按钮必须使用同字号的无边框椭圆分组");
assert.ok(visualCardSource.includes("flex-nowrap") && visualCardSource.includes('aria-label={operationsOpen ? "收起可视化操作" : "展开可视化操作"}') && !visualCardSource.includes('<SlidersHorizontal className="h-3.5 w-3.5" />操作'), "工具栏必须保持单行，操作入口只显示图标");
assert.ok(visualCardSource.includes("{fieldLabels[field] || field}") && visualCardSource.includes("{labels[field] || field}"), "表头、指标和维度必须优先显示字段中文名");
assert.ok(visualCardSource.includes('window.setTimeout(() => setVoiceNoticeVisible(false), 1_000)'), "语音提示必须在 1 秒后自动收起");
assert.ok(voiceSource.includes('scheduleCommand()') && voiceSource.includes("const silenceMs = Math.max(250, Number(options.silenceMs || 1_000))") && voiceSource.includes("}, silenceMs)") && voiceSource.includes("if (stopAfterCommand) stop()"), "共享语音入口必须默认静默一秒触发，并允许 AI 右栏单次提交后停止");
assert.ok(voiceSource.includes("speechApplicationModule: applicationModule") && voiceSource.includes("buildFunAsrRealtimeUrl(tenantId, userId, applicationModule)"), "语音入口必须从模型应用模块读取同一套接入配置");
assert.ok(analysisWorkspaceSource.includes('data-analysis-popup-voice="true"') && analysisWorkspaceSource.includes('data-analysis-realtime-voice="true"') && analysisWorkspaceSource.includes('applicationModule: "popup_voice_input"') && analysisWorkspaceSource.includes('applicationModule: "realtime_voice_input"') && analysisWorkspaceSource.includes("silenceMs: 1_000") && analysisWorkspaceSource.includes('resultDelivery: "planned_analysis"'), "AI 右栏两种语音必须转写后在一秒静默时进入唯一文本分析运行时");
assert.deepEqual(
  visualizationRoleFields(
    ["loan_amount", "branch", "report_date"],
    {
      loan_amount: { type: "decimal", semanticRole: "metric", isMetric: true },
      branch: { type: "string", semanticRole: "dimension" },
      report_date: { type: "date", semanticRole: "date", isTime: true },
    },
    ["loan_amount", "branch"],
  ),
  { metrics: ["loan_amount"], dimensions: ["branch", "report_date"] },
  "已定义指标不得进入维度下拉，已定义维度不得进入指标下拉",
);
assert.ok(visualCardSource.includes("visualizationRoleFields") && visualCardSource.includes("roleFields.metrics") && visualCardSource.includes("roleFields.dimensions"), "可视化指标和维度候选必须按数据表字段角色拆分");
assert.ok(visualCardSource.includes('document.addEventListener("pointerdown", dismissTransientControls, true)') && visualCardSource.includes('[data-table-template-gallery="true"]'), "操作浮层必须支持点击页面其他区域收起且真实模板点击不得被提前卸载");
assert.ok(visualCardSource.includes("moreButtonRef.current?.contains(target)") && visualCardSource.includes('[data-visual-more-menu="true"]') && visualCardSource.includes("if (!inMoreMenu && !inMoreButton) setMoreOpen(false)"), "更多菜单必须在点击按钮和菜单之外时关闭，不得被卡片内其他交互区挡住");
assert.match(visualCardSource, /applyType\(option\.type\);[\s\S]{0,300}setActivePanel\(null\);(?!\s*setOperationsOpen\(false\);)/, "选择样式后操作托盘不得自动折叠");
assert.ok(visualCardSource.includes('长按 2 秒后拖动排序') && visualCardSource.includes('}, 2_000)') && visualCardSource.includes('data-table-long-press-reorder="true"'), "指标、维度、表头和首列必须使用两秒长按排序");
assert.match(visualCardSource, /data-visual-table-scroll="true"/, "超高表格必须在组件内滚动");
assert.match(visualCardSource, /thead className="sticky top-0 z-20/, "表格滚动时表头必须吸顶");
assert.match(visualCardSource, /data-visual-table-frozen-header="true"/, "超高表格表头必须标记为冻结");
assert.match(visualCardSource, /data-visual-table-sort=\{field\}/, "每列表头必须提供统一排序入口");
assert.match(visualCardSource, /data-visual-table-sort-direction=\{direction \|\| "original"\}/, "表头必须暴露原始、正排和倒排三态");
assert.ok(visualCardSource.includes("rowByKey") && visualCardSource.includes("originalIndexByRow") && !visualCardSource.includes("rows.indexOf(row)"), "表格重排必须使用预建索引，不能对每一行重复线性扫描");
assert.ok(visualCardSource.includes("useClientPagination(rowLabels, 20)") && visualCardSource.includes("useClientPagination(columnLabels, pivotColumnPageSize)"), "交叉表必须同时限制行与列的单页渲染规模");
assert.ok(visualCardSource.includes("data-pivot-row-pagination") && visualCardSource.includes("data-pivot-column-pagination"), "交叉表必须暴露行列分页状态供浏览器验收");
assert.match(visualCardSource, /addEventListener\("wheel", onWheel, \{ passive: false, capture: true \}\)/, "表格滚轮必须用捕获阶段非被动监听");
assert.match(visualCardSource, /node.scrollTop \+= deltaY/, "表格内滚轮必须先滚动表格内容");
assert.match(visualCardSource, /if \(!used\) return false/, "表格滚到尽头后必须把滚轮交给页面");
assert.match(visualCardSource, /!scroller.contains\(event.target\)/, "表格外滚轮必须直接滚动页面，不得锁进卡片空白区");
assert.match(visualCardSource, /overscroll-contain/, "表格内部滚动不得把中间溢出传递给页面");
assert.match(visualCardSource, /data-visual-table-region=\{isTableCard \? "true" : undefined\}/, "表格卡片必须标记图表区以便区分表内表外滚轮");
assert.match(visualCardSource, /useVisualTableRegionWheelLock\(chartAreaRef, isTableCard\)/, "表格卡片必须在表内接管滚轮");
assert.match(visualGridSource, /setPointerCapture\(event.pointerId\)/, "可视化缩放必须捕获指针，避免拖到右下角丢失");
assert.match(visualGridSource, /Math.min\(hintMaxWidth, edgeMaxWidth, effectiveWidth\)/, "可视化拖拽宽度不得超过底层页面/网格容器");
assert.match(visualGridSource, /overflow-x-hidden/, "可视化网格不得把卡片画到页面宽度之外");
assert.ok(visualCardSource.includes('onClick={(event) =>') && visualCardSource.includes('onContextMenu={(event) =>') && visualCardSource.includes('data-visual-comment-action="true"') && visualCardSource.includes('<MessageSquareText'), "单击或右键可视化必须显示统一评论气泡");
assert.ok(visualCardSource.includes('eventInsideVisualTable') && visualCardSource.includes('closest("[data-visual-table-scroll]")'), "表格区域内单击或右键不得弹出评论浮圈");
assert.ok(visualCardSource.includes('data-visual-table-header-comment="true"') && visualCardSource.includes("data-visual-merge-dimension=") && visualCardSource.includes("冻结到首列") && visualCardSource.includes("data-visual-freeze-column"), "表格列头右键必须提供评论、合并重复单元格和冻结到首列");
assert.ok(visualCardSource.includes('data-visual-metric-ranking=') && visualCardSource.includes('data-visual-metric-progress=') && visualCardSource.includes('data-visual-table-metric-header=') && visualCardSource.includes('data-visual-table-rank-header='), "表格与交叉表指标表头必须接入排名和显示进度，排名列必须使用独立表头类型");
assert.ok(visualCardSource.includes('data-visual-metric-percent=') && visualCardSource.includes('data-visual-metric-decimals=') && visualCardSource.includes('data-visual-metric-decimal-input=') && visualCardSource.includes('headerMetricFormat?.percent ? "隐藏百分号" : "显示百分号"'), "指标表头必须提供可逆百分号和 0 到 8 位小数配置");
assert.ok(visualCardSource.includes('data-visual-rank-direction="desc"') && visualCardSource.includes('data-visual-rank-direction="asc"') && visualCardSource.includes('tableHeaderMenu.kind === "rank"'), "从大到小和从小到大只能出现在排名表头菜单中");
assert.ok(visualCardSource.includes('metricRankings={metricRankings}') && visualCardSource.includes('metricFormats={metricFormats}') && visualCardSource.includes('metricProgress={metricProgress}') && visualCardSource.includes('type === "pivot"') && visualCardSource.includes('onMetricHeaderContextMenu'), "排名、格式和进度必须通过共享渲染器同时进入普通表与交叉表");
assert.ok(visualCardSource.includes('data-visual-rank-cell=') && visualCardSource.includes('data-visual-progress-cell=') && visualCardSource.includes('data-progress-width='), "派生排名列与进度色块必须暴露可验收的单元格状态");
assert.ok(tableProgressDialogSource.includes('data-progress-formula="true"') && tableProgressDialogSource.includes('data-progress-denominator="true"') && tableProgressDialogSource.includes('data-progress-color="true"'), "进度弹窗必须包含公式、分母指定和进度条颜色三个子模块");
assert.ok(tableProgressDialogSource.includes('data-progress-association="true"') && tableProgressDialogSource.includes("associationOpen") && tableProgressDialogSource.includes("添加关联规则"), "关联规则必须默认折叠并可展开添加规则");
assert.ok(tableProgressDialogSource.includes("所有条件同时成立") && tableProgressDialogSource.includes("添加筛选") && !tableProgressDialogSource.includes("添加“或”条件组"), "进度分母条件组只能使用且逻辑");
assert.ok(tableProgressDialogSource.includes('data-progress-classic-palettes="true"') && tableProgressDialogSource.includes('data-progress-palette-more="true"') && tableProgressDialogSource.includes('data-progress-palette-more-panel="true"') && tableProgressDialogSource.includes("primaryPalettes") && tableProgressDialogSource.includes("additionalPalettes") && tableProgressDialogSource.includes("正向渐变色") && tableProgressDialogSource.includes("反向渐变色") && tableProgressDialogSource.includes("完全色") && !tableProgressDialogSource.includes('>经典配色<') && !tableProgressDialogSource.includes('>填充模式<'), "进度颜色模块必须默认展示四组配色、下拉补充六组，并提供正反渐变和完全色");
assert.ok(tableProgressDialogSource.includes('max-w-[1044px]') && tableProgressDialogSource.includes('max-h-[min(744px,calc(100vh-108px))]'), "进度弹窗的最大宽高必须各收紧约 2 厘米");
assert.ok(tableProgressDialogSource.includes('grid-cols-[92px_108px_90px_minmax(150px,1fr)_92px_170px_36px]') && tableProgressDialogSource.includes('data-association-rule-row={rule.id}') && tableProgressDialogSource.includes('<option value="value">枚举值</option>') && tableProgressDialogSource.includes('aria-label="关联规则枚举值"'), "关联规则必须以一致尺寸单行排布并支持枚举值替换");
assert.ok(visualCardSource.includes('data-visual-insert-column="left"') && visualCardSource.includes('data-visual-insert-column="right"') && visualCardSource.includes('data-visual-calculation-rule="true"') && visualCardSource.includes("向左新增一列") && visualCardSource.includes("向右新增一列"), "表格表头右键必须提供左右新增列和计算规则");
assert.ok(visualCardSource.includes('{tableHeaderMenu.kind === "calculated" && <button') && visualCardSource.includes('if (!tableHeaderMenu || tableHeaderMenu.kind !== "calculated") return;') && !visualCardSource.includes('insertCalculatedColumn("right", true)'), "计算规则只能在新增列菜单中显示且只能编辑当前列");
assert.ok(visualCardSource.includes('data-visual-table-calculated-header=') && visualCardSource.includes('data-calculated-column-name-input=') && visualCardSource.includes('data-visual-calculated-cell='), "普通表与交叉表必须渲染可双击改名的计算列及其单元格");
assert.ok(calculatedColumnDialogSource.includes('data-calculation-expression="true"') && calculatedColumnDialogSource.includes('draggable') && calculatedColumnDialogSource.includes("SUM") && calculatedColumnDialogSource.includes("AVERAGE") && calculatedColumnDialogSource.includes("COUNT") && calculatedColumnDialogSource.includes("CASE WHEN"), "计算规则弹窗必须支持拖入指标以及受控的 SQL 风格函数与算子");
assert.ok(visualCardSource.includes("冻结到首行") && visualCardSource.includes("data-visual-freeze-row") && visualCardSource.includes("data-visual-table-row-menu"), "表格行右键必须提供冻结到首行");
assert.ok(visualCardSource.includes("有合并单元格的情况下，无法冻结，如需冻结请取消合并单元格") && visualCardSource.includes("data-visual-table-freeze-notice"), "有合并单元格时冻结必须提示且不可冻结");
assert.ok(visualCardSource.includes("frozenColumnFields") && visualCardSource.includes("frozenRowKeys") && visualCardSource.includes("source.frozenColumnFields"), "列与行冻结顺序必须进入统一图表配置并按点击时间保留");
assert.ok(visualCardSource.includes("mergedDimensionFields") && visualCardSource.includes("setMergedDimensionFields") && visualCardSource.includes("source.mergedDimensionFields"), "合并维度选择必须进入统一图表配置并支持恢复");
assert.ok(!visualCardSource.includes("右键可评论；操作中可配置样式、指标、维度与语音"), "可视化卡片不得保留冗余操作说明");
assert.ok(analysisWorkspaceSource.includes("const analysisTitle = selectedDataPoint?.label || definition.title"), "AI 分析栏标题必须使用所点可视化名称");
assert.ok(!analysisWorkspaceSource.includes("当前锚点："), "AI 分析栏不得保留重复锚点文本条");
assert.ok(analysisWorkspaceSource.includes("const visibleThreads = openThreads.filter") && analysisWorkspaceSource.includes('data-analysis-thread-tabs="true"') && analysisWorkspaceSource.indexOf('data-global-analysis-wide-toggle="true"') > analysisWorkspaceSource.indexOf('data-analysis-thread-tabs="true"'), "重复线程标签必须去重且宽度按钮固定在滚动标签外");
assert.ok(messageBoardSource.includes('引用 · {target.label || "页面内容"}') && !messageBoardSource.includes('>{target.selectedText}</div>'), "留言引用只能显示可视化名称");
assert.ok(workbenchPersistenceSource.includes("sessionStorage.setItem") && workbenchPersistenceSource.includes("analysisRows.slice(0, 200)") && selfAnalysisSource.includes("useSelfAnalysisWorkbenchPersistence"), "智能分析离开页面后必须恢复租户用户范围内的有界数据与可视化状态");

assert.equal(defaultVisualGridSpan(1), 12, "单个可视化必须默认全宽");
assert.equal(defaultVisualGridSpan(2), 6, "多个可视化必须默认每行两个等宽卡片");
const defaultPacked = packVisualGridItems([{ id: "a", span: 6, height: 380 }, { id: "b", span: 6, height: 380 }], 1200, 16);
assert.deepEqual(defaultPacked.positions.map(({ x, y, width }) => ({ x, y, width })), [{ x: 0, y: 0, width: 592 }, { x: 608, y: 0, width: 592 }], "默认双卡必须顶端对齐并平分可用宽度");
const densePacked = packVisualGridItems([{ id: "a", span: 8, height: 380 }, { id: "b", span: 6, height: 300 }, { id: "c", span: 4, height: 280 }], 1200, 16);
assert.equal(densePacked.positions[2].y, 0, "后续窄卡必须自动向上补入前方剩余空间");
for (const direction of ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]) assert.ok(visualGridSource.includes(`data-visual-resize-handle="${direction}"`), `缺少 ${direction} 缩放边界`);
assert.ok(visualGridSource.includes("requestAnimationFrame") && visualGridSource.includes("item.style.width") && visualGridSource.includes("item.style.height"), "缩放预览必须由 rAF 直接更新像素尺寸");
assert.ok(visualGridSource.includes('data-visual-grid-default={entries.length === 1 ? "full-width" : "two-per-row"}'), "可视化网格必须声明单图全宽和多图双列默认形态");
assert.ok(visualCardSource.includes('data-visual-filter-value-trigger={rule.id}') && visualCardSource.includes('className="fixed z-[120]') && visualCardSource.includes('data-visual-filter-value-menu="true"'), "条件值下拉必须通过视口浮层呈现，不能被条件滚动区裁剪");
assert.ok(visualCardSource.includes("当前维度暂无可选值"), "条件值为空时必须给出明确反馈，不能显示空白下拉");
assert.ok(visualCardSource.includes('data-combo-series-control={field}') && visualCardSource.includes('data-combo-series-menu={field}') && visualCardSource.includes('absolute left-0 top-full'), "组合图转换菜单必须锚定在右键指标正下方");
assert.ok(!visualCardSource.includes('className="absolute right-2 top-7 z-30'), "组合图不得继续使用图表右上角固定菜单位置");

console.log("可视化语音、工具栏、筛选浮层、指标右键锚点与可缩放补位合同通过");
