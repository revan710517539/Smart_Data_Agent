import type { AnalysisDataTableSelection, AnalysisRow, KnowledgeFileAttachment } from "./domain";

export type TopicTableSourceKind = "upload" | "data_management" | "metric_dictionary" | "none";

export type CompletedAnalysisRound = {
  tenantId: string;
  userId: string;
  taskId: string;
  question: string;
  sql: string;
  summary: string;
  tables: AnalysisDataTableSelection[];
  rows: AnalysisRow[];
  sourceKind: TopicTableSourceKind;
  executionMode: string;
};

const UPLOADED_EXECUTION_MODES = new Set(["uploaded_file", "uploaded_document_summary"]);
export const TOPIC_TABLE_SKIP_PERSIST_ERRORS = new Set([
  "topic_table_uploaded_source_not_persisted",
  "executed_analysis_evidence_required_for_asset_candidate",
]);

export function isUploadedAnalysisTable(table: AnalysisDataTableSelection) {
  const path = String(table.relativePath || "").trim();
  const kind = String(table.kind || "").trim().toLowerCase();
  return path.startsWith("upload://") || kind === "uploaded_file" || String(table.id || "").startsWith("upload_");
}
export function classifyTopicTableSource(input: {
  executionMode?: string;
  selectedDataTables: AnalysisDataTableSelection[];
  knowledgeFiles?: KnowledgeFileAttachment[];
  resolvedViaMetricPreset?: boolean;
}): TopicTableSourceKind {
  const mode = String(input.executionMode || "").trim().toLowerCase();
  if (UPLOADED_EXECUTION_MODES.has(mode)) return "upload";
  const catalogTables = input.selectedDataTables.filter((table) => !isUploadedAnalysisTable(table));
  const hasUploadFiles = (input.knowledgeFiles || []).some((file) => file.classification === "data_source");
  if (!catalogTables.length) {
    if (hasUploadFiles || input.selectedDataTables.some(isUploadedAnalysisTable)) return "upload";
    return "none";
  }
  if (input.resolvedViaMetricPreset || catalogTables.some((table) => (table.metricCodes || []).length > 0)) {
    return "metric_dictionary";
  }
  return "data_management";
}

export function canPersistTopicTable(round: Pick<CompletedAnalysisRound, "sourceKind" | "sql" | "taskId">) {
  return Boolean(
    round.taskId
    && (round.sourceKind === "data_management" || round.sourceKind === "metric_dictionary")
    && extractPersistableSelectSql(round.sql),
  );
}

export function extractPersistableSelectSql(sqlScript: string) {
  const lines = String(sqlScript || "").split("\n");
  while (lines.length && (!lines[0].trim() || lines[0].trimStart().startsWith("--"))) lines.shift();
  const text = lines.join("\n").trim();
  const cut = text.search(/\n-- Parameters\b/);
  const statement = (cut >= 0 ? text.slice(0, cut) : text).replace(/;+\s*$/, "").trim();
  const normalized = statement.replace(/^\/\*[\s\S]*?\*\//, "").trim();
  if (!/^(select|with)\b/i.test(normalized)) return "";
  return statement;
}

export function executedSelectSqlFromAnalysis(response: {
  skill_results?: Array<{
    sql?: string;
    evidence?: { executed_sql?: string; execution_statement?: string; [key: string]: unknown };
  }>;
  intelligent_analysis?: { executed_sql?: string; suggested_sql?: string };
}, fallbackScript = "") {
  const result = response.skill_results?.[0];
  const raw = String(
    result?.evidence?.executed_sql
    || result?.evidence?.execution_statement
    || result?.sql
    || response.intelligent_analysis?.executed_sql
    || fallbackScript
    || "",
  ).trim();
  return extractPersistableSelectSql(raw);
}

export function topicTableFieldsFromRows(rows: AnalysisRow[]) {
  if (!rows.length) return [];
  return Object.keys(rows[0].raw).map((fieldName, index) => ({
    fieldNameEn: fieldName || `field_${index + 1}`,
    fieldNameCn: rows[0].fieldLabels?.[fieldName] || fieldName || `字段${index + 1}`,
    type: typeof rows[0].raw[fieldName] === "number" ? "decimal" : "string",
    explanation: "来自已执行分析结果；业务语义需在数据资产复核时确认。",
    exampleUsage: "智能分析、经营周报、主题表复用",
  }));
}

export function buildTopicTableItem(round: CompletedAnalysisRound) {
  const table = round.tables.find((item) => !isUploadedAnalysisTable(item)) || round.tables[0];
  const sourceLabel = round.sourceKind === "metric_dictionary"
    ? `指标字典数据表${table ? ` ${table.name}（${table.code}）` : ""}`
    : `站内数据表${table ? ` ${table.name}（${table.code}）` : ""}`;
  const rawCode = `topic_analysis_${round.taskId}`.toLowerCase().replace(/[^a-z0-9_]+/g, "_").slice(0, 118);
  const code = /^[A-Za-z_]/.test(rawCode) ? rawCode : `t_${rawCode}`;
  return {
    id: `topic_analysis_${round.taskId}`,
    name: (round.question || "智能分析主题").slice(0, 120),
    code,
    description: `来自智能分析最新一轮。数据来源：${sourceLabel}。${(round.summary || "").split("\n")[0] || ""}`.slice(0, 2000),
    sql: extractPersistableSelectSql(round.sql),
    fields: topicTableFieldsFromRows(round.rows),
    fieldExplanations: "字段来自服务端已执行结果，需在数据资产审核中补充业务语义。",
    applicableScene: "智能分析, 经营周报",
    relatedIntent: "智能分析沉淀",
    relatedExperience: "",
    quickDisplay: false,
    reportReference: "经营周报",
    source: round.sourceKind === "metric_dictionary" ? "智能分析/指标字典" : "智能分析/站内数据",
    analysisTaskId: round.taskId,
    updatedAt: new Date().toLocaleString("zh-CN", { hour12: false }),
  };
}

export function completedRoundFromAnalysis(input: {
  tenantId: string;
  userId: string;
  question: string;
  response: {
    task_id?: string;
    skill_results?: Array<{
      sql?: string;
      semantic_info?: Record<string, unknown>;
      evidence?: { executed_sql?: string; execution_statement?: string; [key: string]: unknown };
    }>;
    intelligent_analysis?: { executed_sql?: string; analysis_summary?: string };
    conclusions?: string[];
  };
  tables: AnalysisDataTableSelection[];
  rows: AnalysisRow[];
  knowledgeFiles?: KnowledgeFileAttachment[];
  resolvedViaMetricPreset?: boolean;
  fallbackScript?: string;
}): CompletedAnalysisRound | null {
  const taskId = String(input.response.task_id || "").trim();
  if (!taskId) return null;
  const executionMode = String(input.response.skill_results?.[0]?.semantic_info?.execution_mode || "").trim();
  const sourceKind = classifyTopicTableSource({
    executionMode,
    selectedDataTables: input.tables,
    knowledgeFiles: input.knowledgeFiles,
    resolvedViaMetricPreset: input.resolvedViaMetricPreset,
  });
  const sql = executedSelectSqlFromAnalysis(input.response, input.fallbackScript);
  const summary = String(
    input.response.intelligent_analysis?.analysis_summary
    || (input.response.conclusions || []).filter((item) => item.trim()).join("\n")
    || "",
  );
  return {
    tenantId: input.tenantId,
    userId: input.userId,
    taskId,
    question: input.question,
    sql,
    summary,
    tables: input.tables,
    rows: input.rows,
    sourceKind,
    executionMode,
  };
}
