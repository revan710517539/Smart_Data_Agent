import { replaceVisualAnalysisSourceGroup, updateAnalysisWorkspacePageContext } from "../analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "../analysis-workspace/visualAnalysisScope";
import type {
  AnalysisDataTableSelection,
  SavedAnalysisResult,
  SelfAnalysisSection,
} from "./domain";
import { resolveVisualAnalysisTables } from "./visualFollowUp";

export function syncSelfAnalysisWorkspaceContext({
  activeView,
  expandedReportId,
  reportSourceFilter,
  savedAnalysisResults,
  selectedDataTables,
  selectedInstitution,
  analysisTaskId,
}: {
  activeView: SelfAnalysisSection;
  expandedReportId: string;
  reportSourceFilter: string;
  savedAnalysisResults: SavedAnalysisResult[];
  selectedDataTables: AnalysisDataTableSelection[];
  selectedInstitution: string;
  analysisTaskId?: string;
}) {
  if (activeView === "reports") {
    const report = savedAnalysisResults.find((item) => item.id === expandedReportId);
    const reports = report ? [report] : savedAnalysisResults.slice(0, 12);
    const sources = reports.flatMap((item) => {
      const tables = resolveVisualAnalysisTables(item.selectedDataTables, selectedDataTables);
      if (!tables.length && !item.analysisTaskId && !item.rows?.length) return [];
      return [{
        id: item.id,
        label: item.title || item.query || "报表",
        tables,
        analysis_task_id: item.analysisTaskId || "",
        question: item.query || "",
        summary: item.summary || "",
        rows: boundedVisualRows(item.rows),
      }];
    });
    updateAnalysisWorkspacePageContext("my-reports", {
      route: "self-analysis/reports",
      selected_institution: selectedInstitution,
      artifact_id: report?.id || "my-reports",
      dataset_snapshot: report?.topicData ? {
        id: report.topicData.reference_id,
        version: report.topicData.updated_at,
        generatedAt: report.topicData.updated_at,
      } : {},
      filters: { institution: selectedInstitution, source_channel: report?.source?.channel || reportSourceFilter },
      visualization: report ? {
        title: report.title,
        query: report.query,
        summary: report.summary,
        row_count: report.topicData?.row_count || report.rows.length,
        visual_types: report.visualTypes,
      } : { report_count: savedAnalysisResults.length },
      selected_data_tables: resolveVisualAnalysisTables(report?.selectedDataTables, selectedDataTables),
      analysis_task_id: report?.analysisTaskId || analysisTaskId || "",
      analysis_policy: { engine: "IntelligentAnalysisEngine", resultDelivery: "data_first" },
    });
    replaceVisualAnalysisSourceGroup("my-reports", "my-reports", sources);
    return;
  }
  const queryTables = resolveVisualAnalysisTables(selectedDataTables);
  updateAnalysisWorkspacePageContext("self-analysis", {
    route: "self-analysis/query",
    selected_institution: selectedInstitution,
    selected_data_tables: queryTables,
    analysis_task_id: analysisTaskId || "",
    filters: { institution: selectedInstitution },
    analysis_policy: { engine: "IntelligentAnalysisEngine", resultDelivery: "data_first" },
  });
  replaceVisualAnalysisSourceGroup("self-analysis", "self-analysis", queryTables.length || analysisTaskId ? [{
    id: analysisTaskId || "current-analysis",
    label: "当前分析结果",
    tables: queryTables,
    analysis_task_id: analysisTaskId || "",
  }] : []);
}
