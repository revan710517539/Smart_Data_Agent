import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile("src/app/components/self-analysis/topicTablePrecipitation.ts", "utf8");
const hook = await readFile("src/app/components/self-analysis/useTopicTablePrecipitation.ts", "utf8");
const selfAnalysis = await readFile("src/app/components/SelfAnalysis.tsx", "utf8");
const platformContext = await readFile("src/app/platform/PlatformContext.tsx", "utf8");

const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

assert.equal(module.classifyTopicTableSource({
  executionMode: "uploaded_file",
  selectedDataTables: [{ id: "raw_1", kind: "raw", name: "机构表", code: "loan_daily", relativePath: "raw://loan_daily" }],
}), "upload");
assert.equal(module.classifyTopicTableSource({
  executionMode: "selected_raw_csv",
  selectedDataTables: [{ id: "raw_1", kind: "raw", name: "机构表", code: "loan_daily", relativePath: "raw://loan_daily" }],
}), "data_management");
assert.equal(module.classifyTopicTableSource({
  executionMode: "selected_raw_csv",
  selectedDataTables: [{ id: "raw_1", kind: "raw", name: "指标表", code: "metric_loan", metricCodes: ["loan_amount"], relativePath: "raw://metric_loan" }],
  resolvedViaMetricPreset: true,
}), "metric_dictionary");
assert.equal(module.extractPersistableSelectSql(
  '-- Selected tenant CSV; executed by the bounded read-only CSV adapter.\nSELECT "a" FROM "loan_daily"\n\n-- Parameters\n{}',
), 'SELECT "a" FROM "loan_daily"');
assert.equal(module.canPersistTopicTable({ sourceKind: "upload", sql: "SELECT 1", taskId: "t1" }), false);
assert.equal(module.canPersistTopicTable({ sourceKind: "data_management", sql: "SELECT 1 FROM loan_daily", taskId: "t1" }), true);

assert.match(hook, /registerBeforeLogout/);
assert.match(hook, /pagehide/);
assert.match(hook, /prepareQuestionSwitch/);
assert.ok(!selfAnalysis.includes("await saveAsTopicTable(false)"));
assert.match(selfAnalysis, /prepareQuestionSwitch\(nextQuery\)/);
assert.match(platformContext, /runBeforeLogout/);

console.log("智能分析主题表沉淀合同通过（数据源分流、换问题/退出时机、三个保存按钮不再顺带存主题）");
