import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = process.cwd();
const modelPath = path.join(root, "src/app/components/visualization/visualizationDataModel.ts");
const viewsPath = path.join(root, "src/app/components/self-analysis/ResultViews.tsx");
const selfAnalysisPath = path.join(root, "src/app/components/SelfAnalysis.tsx");
const pageDataPath = path.join(root, "src/app/components/page-data/PageDataComposer.tsx");
const dashboardPath = path.join(root, "src/app/components/Dashboard.tsx");
const supervisionPath = path.join(root, "src/app/components/InstitutionSupervision.tsx");

const modelSource = fs.readFileSync(modelPath, "utf8");
const modelJs = ts.transpileModule(modelSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const model = await import(`data:text/javascript;base64,${Buffer.from(modelJs).toString("base64")}`);

assert.deepEqual(model.selectedTableFields(["date", "branch"], ["amount", "count"]), ["date", "branch", "amount", "count"], "table fields keep dimensions before metrics");
assert.equal(model.visualizationFieldPolicy("scatter").maximumMetrics, 2, "scatter caps metrics at two");
assert.equal(model.visualizationFieldPolicy("kpi").maximumDimensions, 1, "KPI caps dimensions at one");
assert.equal(model.visualizationFieldPolicy("treemap").maximumMetrics, 1, "treemap caps metrics at one");
assert.deepEqual(model.moveVisualizationFieldWithinGroup(["a", "b", "c"], "c", "a"), ["c", "a", "b"], "reorder commits inside one field group");

const rows = [
  { raw: { branch: "A", date: "2026-01", amount: 10, count: 2 } },
  { raw: { branch: "A", date: "2026-02", amount: 20, count: 3 } },
  { raw: { branch: "B", date: "2026-01", amount: 30, count: 4 } },
];
assert.deepEqual(model.defaultVisualizationSelections("line", ["amount", "count"], ["branch", "date"], { date: "日期" }).dimensions, ["date"], "trend defaults to a time dimension");
assert.equal(model.buildVisualDataPoints(rows, ["amount"], ["branch"], { branch: ["A"] }, false).length, 2, "unaggregated filters retain raw rows");
const summed = model.buildVisualDataPoints(rows, ["amount", "count"], ["branch"], {}, true);
assert.deepEqual(summed.map((point) => [point.label, point.values.amount, point.values.count]), [["A", 30, 5], ["B", 30, 4]], "sum option aggregates every selected metric by dimension combination");
const filterGroups = [
  { id: "g1", rules: [{ id: "r1", field: "branch", operator: "in", values: ["A"] }, { id: "r2", field: "date", operator: "contains", values: ["01"] }] },
  { id: "g2", rules: [{ id: "r3", field: "branch", operator: "in", values: ["B"] }, { id: "r4", field: "date", operator: "not_in", values: ["2026-02"] }] },
];
assert.deepEqual(model.filterVisualizationRows(rows, {}, filterGroups).map((row) => `${row.raw.branch}-${row.raw.date}`), ["A-2026-01", "B-2026-01"], "filter groups evaluate AND inside a group and OR between groups");
assert.equal(model.filterVisualizationRows(rows, {}, [{ id: "missing", rules: [{ id: "bad", field: "unknown", operator: "in", values: ["未分类"] }] }]).length, 0, "missing dimensions fail closed instead of matching fallback values");
assert.deepEqual(model.legacyFiltersToFilterGroups({ branch: ["A"] })[0].rules[0], { id: "legacy-rule-0", field: "branch", operator: "in", values: ["A"] }, "legacy simple filters remain readable");
assert.deepEqual(model.visualizationFilterGroupsToLegacyFilters([{ id: "g", rules: [{ id: "r", field: "branch", operator: "in", values: ["A", "B"] }] }]), { branch: ["A", "B"] }, "one simple group retains legacy projection");
assert.equal(model.visualizationChartColor(0), "#287557", "global chart palette starts with the restrained system green");
assert.equal(new Set(Array.from({ length: 8 }, (_, index) => model.visualizationChartColor(index))).size, 8, "muted palette remains distinguishable across series");

const views = fs.readFileSync(viewsPath, "utf8");
assert.match(views, /requestAnimationFrame\(\(\) =>/, "drag preview is frame scheduled");
assert.match(views, /if \(commit && source && destination[^\n]+setFields/, "field order commits once on release");
assert.doesNotMatch(views, /pointermove[\s\S]{0,500}setFields\(/i, "pointer move does not mutate field order");
for (const marker of ["data-visual-more", "条件", "复制", "删除", "求和", "data-visual-title-input", "双击修改标题", "转为", "柱状图", "趋势图", "data-filter-rule-relation=\"and\"", "data-filter-group-relation=\"or\"", "添加筛选", "添加“或”条件组"]) assert.ok(views.includes(marker), `shared card contains ${marker}`);
for (const saturatedColor of ["#2f6fed", "#f0a23a", "#7c63d6", "#d15f7a"]) assert.ok(!views.includes(saturatedColor), `shared renderer no longer uses saturated series color ${saturatedColor}`);

const selfAnalysis = fs.readFileSync(selfAnalysisPath, "utf8");
assert.ok(selfAnalysis.includes('handleSaveTarget("mine")'), "toolbar exposes save mine");
assert.ok(selfAnalysis.includes("visualizations: visualCards.map"), "save mine persists the ordered visualization list and config");
assert.ok(selfAnalysis.includes("visualCards.map((card) => <AnalysisVisualCard"), "current analysis renders a dynamic visualization list");
assert.ok(selfAnalysis.includes("reportVisualizationsFor(result).map"), "my reports renders every saved visualization");

const pageData = fs.readFileSync(pageDataPath, "utf8");
assert.ok(pageData.includes("export function PageDataModeToggle"), "browse/edit toggle is shared for future page-data screens");
assert.ok(pageData.includes("onDuplicate={showEditorControls && mode === \"edit\"") && pageData.includes("onDelete={showEditorControls && mode === \"edit\""), "page-data visualizations inherit duplicate/delete behavior only for authorized editors in edit mode");
for (const file of [dashboardPath, supervisionPath]) {
  const source = fs.readFileSync(file, "utf8");
  assert.ok(source.includes("<PageDataModeToggle controller={"), `${path.basename(file)} places the shared toggle beside the title`);
  assert.ok(!source.includes("<PageDataComposer "), `${path.basename(file)} removes the legacy composer toolbar`);
}

console.log("共享可视化工作台合同通过（指标维度、拖动、图表操作、存我的、页面标题栏）");
