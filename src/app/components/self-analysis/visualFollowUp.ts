import { revealAnalysisWorkspace } from "../analysis-workspace/AnalysisWorkspaceRail";
import { revealContextRail } from "../context-rail/ContextSideRail";
import type { AnalysisDataTableSelection, AnalysisRow, ResultVisualKey, VisualizationType } from "./domain";

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
  selectedDataTables: AnalysisDataTableSelection[];
  railPageKey?: string;
}) {
  const selectedDataPoint = buildVisualDataPoint({ key, title, type, rows, taskId, reportId, question, summary, plan, selectedDataTables });
  revealContextRail(railPageKey || (reportId ? "my-reports" : "self-analysis"), "analysis", selectedDataPoint);
  revealAnalysisWorkspace(selectedDataPoint, "context-rail");
}

export function revealVisualComment(input: Parameters<typeof revealVisualFollowUp>[0]) {
  const selectedDataPoint = buildVisualDataPoint(input);
  revealContextRail(input.railPageKey || (input.reportId ? "my-reports" : "self-analysis"), "comments", selectedDataPoint);
}

function buildVisualDataPoint({ key, title, type, rows, taskId, reportId, question, summary, plan, selectedDataTables }: Parameters<typeof revealVisualFollowUp>[0]) {
  const firstRow = rows[0];
  const artifactId = reportId || taskId || "current-analysis";
  return {
    targetType: type === "table" || type === "pivot" ? "table" : "chart",
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
      selected_data_table_ids: selectedDataTables.map((table) => table.id),
      selected_data_tables: selectedDataTables.map((table) => ({
        id: table.id,
        kind: table.kind,
        name: table.name,
        code: table.code,
        datasetId: table.datasetId,
        field_labels: table.fieldLabels || {},
        metric_codes: table.metricCodes || table.defaultMetrics || [],
        dimension_codes: table.dimensionCodes || table.defaultDimensions || [],
      })),
      field_labels: firstRow?.fieldLabels || selectedDataTables[0]?.fieldLabels || {},
    },
  } as const;
}
