import { updateAnalysisWorkspacePageContext } from "../analysis-workspace/AnalysisWorkspaceRail";
import type {
  AnalysisDataTableSelection,
  SavedAnalysisResult,
  SelfAnalysisSection,
} from "./domain";

export function syncSelfAnalysisWorkspaceContext({
  activeView,
  expandedReportId,
  reportSourceFilter,
  savedAnalysisResults,
  selectedDataTables,
  selectedInstitution,
}: {
  activeView: SelfAnalysisSection;
  expandedReportId: string;
  reportSourceFilter: string;
  savedAnalysisResults: SavedAnalysisResult[];
  selectedDataTables: AnalysisDataTableSelection[];
  selectedInstitution: string;
}) {
  if (activeView === "reports") {
    const report = savedAnalysisResults.find((item) => item.id === expandedReportId);
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
      selected_data_tables: selectedDataTables,
      analysis_policy: { engine: "IntelligentAnalysisEngine", resultDelivery: "data_first" },
    });
    return;
  }
  updateAnalysisWorkspacePageContext("self-analysis", {
    route: "self-analysis/query",
    selected_institution: selectedInstitution,
    selected_data_tables: selectedDataTables,
    filters: { institution: selectedInstitution },
    analysis_policy: { engine: "IntelligentAnalysisEngine", resultDelivery: "data_first" },
  });
}
