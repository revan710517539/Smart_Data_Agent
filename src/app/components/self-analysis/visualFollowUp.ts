import { revealAnalysisWorkspace } from "../analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "../analysis-workspace/visualAnalysisScope";
import { revealContextRail } from "../context-rail/ContextSideRail";
import { backendTableToSelection, type AnalysisDataTableSelection, type AnalysisRow, type ResultVisualKey, type VisualizationType } from "./domain";

export function resolveVisualAnalysisTables(
  ...candidates: Array<AnalysisDataTableSelection[] | unknown[] | unknown | undefined | null>
): AnalysisDataTableSelection[] {
  for (const candidate of candidates) {
    const tables = (Array.isArray(candidate) ? candidate : []).flatMap((item: unknown) => {
      if (!item || typeof item !== "object") return [];
      const record = item as AnalysisDataTableSelection;
      if (record.id && record.kind && record.name && record.code) return [record];
      const converted = backendTableToSelection(item);
      return converted ? [converted] : [];
    });
    if (tables.length) return tables;
  }
  return [];
}

export function revealVisualFollowUp({
  key,
  title,
  type,
  rows,
  taskId,
  reportId,
  question,
  summary,
  plan,
  selectedDataTables,
  railPageKey,
  selectedText,
}: {
  key: ResultVisualKey;
  title: string;
  type: VisualizationType;
  rows: AnalysisRow[];
  taskId?: string;
  reportId?: string;
  question: string;
  summary: string;
  plan: string;
  selectedDataTables?: AnalysisDataTableSelection[] | unknown[] | null;
  railPageKey?: string;
  selectedText?: string;
}) {
  const selectedDataPoint = buildVisualDataPoint({ key, title, type, rows, taskId, reportId, question, summary, plan, selectedDataTables, selectedText });
  revealContextRail(railPageKey || (reportId ? "my-reports" : "self-analysis"), "analysis", selectedDataPoint);
  revealAnalysisWorkspace(selectedDataPoint, "context-rail");
}

export function revealVisualComment(input: Parameters<typeof revealVisualFollowUp>[0]) {
  const selectedDataPoint = buildVisualDataPoint(input);
  revealContextRail(input.railPageKey || (input.reportId ? "my-reports" : "self-analysis"), "comments", selectedDataPoint);
}

function buildVisualDataPoint({ key, title, type, rows, taskId, reportId, question, summary, plan, selectedDataTables, selectedText }: Parameters<typeof revealVisualFollowUp>[0]) {
  const firstRow = rows[0];
  const artifactId = reportId || taskId || "current-analysis";
  const boundTables = resolveVisualAnalysisTables(selectedDataTables);
  const sourceTable = boundTables[0];
  return {
    targetType: type === "table" || type === "pivot" ? "table" : type === "text" ? "text" : "chart",
    targetId: `${artifactId}:${key}`,
    label: title,
    values: {
      visual_key: key,
      visualization_type: type,
      analysis_task_id: taskId || "",
      report_id: reportId || "",
      question,
      analysis_summary: summary,
      analysis_plan: plan,
      row_count: rows.length,
      metric_name: firstRow?.metricName || "",
      metric_unit: firstRow?.metricUnit || "",
      chart_bound_source: true,
      follow_up_source_question: question,
      visual_rows: boundedVisualRows(rows),
      selected_data_table_ids: boundTables.map((table) => table.id),
      selected_data_tables: boundTables.map((table) => {
        const metricCodes = table.metricCodes || table.defaultMetrics || [];
        const dimensionCodes = table.dimensionCodes || table.defaultDimensions || [];
        return {
          id: table.id,
          kind: table.kind,
          name: table.name,
          code: table.code,
          datasetId: table.datasetId,
          fields: table.fields,
          field_labels: table.fieldLabels || {},
          fieldLabels: table.fieldLabels || {},
          metric_codes: metricCodes,
          metricCodes,
          defaultMetrics: table.defaultMetrics || metricCodes,
          dimension_codes: dimensionCodes,
          dimensionCodes,
          defaultDimensions: table.defaultDimensions || dimensionCodes,
          contentHash: table.contentHash,
          schemaFingerprint: table.schemaFingerprint,
          assetVersion: table.assetVersion,
          relativePath: table.relativePath,
          sourceKey: table.sourceKey,
        };
      }),
      dataset_snapshot: sourceTable ? {
        id: sourceTable.datasetId || sourceTable.id,
        version: sourceTable.assetVersion || sourceTable.contentHash,
        content_hash: sourceTable.contentHash,
        schema_fingerprint: sourceTable.schemaFingerprint,
        generatedAt: new Date().toISOString(),
      } : {},
      field_labels: firstRow?.fieldLabels || sourceTable?.fieldLabels || {},
      selected_content: selectedText || "",
    },
  } as const;
}
