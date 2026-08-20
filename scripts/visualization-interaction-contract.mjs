import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const sourcePath = new URL("../src/app/components/visualization/visualizationCommand.ts", import.meta.url);
const source = await readFile(sourcePath, "utf8");
const visualCardSource = await readFile(new URL("../src/app/components/self-analysis/ResultViews.tsx", import.meta.url), "utf8");
const visualGridSource = await readFile(new URL("../src/app/components/self-analysis/ResizableVisualizationGrid.tsx", import.meta.url), "utf8");
const visualGridLayoutSource = await readFile(new URL("../src/app/components/self-analysis/visualGridLayout.ts", import.meta.url), "utf8");
const analysisWorkspaceSource = await readFile(new URL("../src/app/components/analysis-workspace/AnalysisWorkspaceRail.tsx", import.meta.url), "utf8");
const voiceSource = await readFile(new URL("../src/app/components/visualization/useVisualizationVoiceCommand.ts", import.meta.url), "utf8");
const messageBoardSource = await readFile(new URL("../src/app/components/message-board/MessageBoardPanel.tsx", import.meta.url), "utf8");
const workbenchPersistenceSource = await readFile(new URL("../src/app/components/self-analysis/useSelfAnalysisWorkbenchPersistence.ts", import.meta.url), "utf8");
const selfAnalysisSource = await readFile(new URL("../src/app/components/SelfAnalysis.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { moveVisualizationField, resolveVisualizationVoiceCommand } = await import(moduleUrl);
const visualGridLayoutCompiled = ts.transpileModule(visualGridLayoutSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const visualGridLayoutModuleUrl = `data:text/javascript;base64,${Buffer.from(visualGridLayoutCompiled).toString("base64")}`;
const { defaultVisualGridSpan, packVisualGridItems } = await import(visualGridLayoutModuleUrl);

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
assert.deepEqual(moveVisualizationField(["field_2", "field_3"], "missing", "field_3"), ["field_2", "field_3"]);

const followUpIndex = visualCardSource.indexOf(">追问</button>");
const operationTrayIndex = visualCardSource.indexOf("data-visual-operation-tray=");
const operationButtonIndex = visualCardSource.indexOf("><SlidersHorizontal");
assert.ok(followUpIndex >= 0 && followUpIndex < operationTrayIndex && operationTrayIndex < operationButtonIndex, "操作子按钮必须位于追问和操作之间");
assert.equal((visualCardSource.match(/tabIndex=\{operationsOpen \? 0 : -1\}/g) || []).length, 4, "操作必须包含样式、指标、维度和语音四个子按钮");
assert.ok(visualCardSource.includes('rounded-full bg-[#f0f6f2]') && visualCardSource.includes('rounded-full px-2 text-[11px]'), "操作子按钮必须使用同字号的无边框椭圆分组");
assert.ok(visualCardSource.includes("flex-nowrap") && visualCardSource.includes('aria-label={operationsOpen ? "收起可视化操作" : "展开可视化操作"}') && !visualCardSource.includes('<SlidersHorizontal className="h-3.5 w-3.5" />操作'), "工具栏必须保持单行，操作入口只显示图标");
assert.ok(visualCardSource.includes("{fieldLabels[field] || field}") && visualCardSource.includes("{labels[field] || field}"), "表头、指标和维度必须优先显示字段中文名");
assert.ok(visualCardSource.includes('window.setTimeout(() => setVoiceNoticeVisible(false), 1_000)'), "语音提示必须在 1 秒后自动收起");
assert.ok(voiceSource.includes('scheduleCommand()') && voiceSource.includes('}, 1_000)') && !voiceSource.includes('onCommand(next);\n            stop();'), "可视化语音必须在静默 1 秒后执行且不自动停止");
assert.ok(visualCardSource.includes('document.addEventListener("pointerdown", dismissTransientControls, true)'), "操作浮层必须支持点击页面其他区域收起");
assert.ok(visualCardSource.includes('applyType(option.type); setActivePanel(null);') && !visualCardSource.includes('applyType(option.type); setActivePanel(null); setOperationsOpen(false);'), "选择样式后操作托盘不得自动折叠");
assert.ok(visualCardSource.includes('长按 2 秒后拖动排序') && visualCardSource.includes('}, 2_000)') && visualCardSource.includes('data-table-long-press-reorder="true"'), "指标、维度、表头和首列必须使用两秒长按排序");
assert.ok(visualCardSource.includes('onDoubleClick=') && visualCardSource.includes('data-visual-comment-action="true"') && visualCardSource.includes('<MessageSquareText'), "双击可视化必须显示周报同款评论图标");
assert.ok(!visualCardSource.includes("右键可评论；操作中可配置样式、指标、维度与语音"), "可视化卡片不得保留冗余操作说明");
assert.ok(analysisWorkspaceSource.includes("const analysisTitle = selectedDataPoint?.label || definition.title"), "AI 分析栏标题必须使用所点可视化名称");
assert.ok(!analysisWorkspaceSource.includes("当前锚点："), "AI 分析栏不得保留重复锚点文本条");
assert.ok(analysisWorkspaceSource.includes("const visibleThreads = threads.filter") && analysisWorkspaceSource.includes('data-analysis-thread-tabs="true"') && analysisWorkspaceSource.indexOf('data-global-analysis-wide-toggle="true"') > analysisWorkspaceSource.indexOf('data-analysis-thread-tabs="true"'), "重复线程标签必须去重且宽度按钮固定在滚动标签外");
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
