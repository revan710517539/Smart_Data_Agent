import { useEffect, useMemo, useState, type ComponentProps } from "react";
import { ContextSideRail } from "../context-rail/ContextSideRail";
import { CommentsPanel } from "./CommentsPanel";
import { WeeklyContextAnalysisPanel } from "./ContextAnalysisPanel";
import { MessageBoardPanel } from "../message-board/MessageBoardPanel";
import { AnalysisWorkspacePanel, replaceVisualAnalysisSourceGroup, updateAnalysisWorkspacePageContext } from "../analysis-workspace/AnalysisWorkspaceRail";
import type { SelectedDataPoint } from "../../services/analysisWorkspaceApi";
import type { CommentTarget } from "./domain";

type CommentsProps = ComponentProps<typeof CommentsPanel>;
type AnalysisProps = ComponentProps<typeof WeeklyContextAnalysisPanel>;

export function WeeklyReportSideRail({
  activeTab,
  onTabChange,
  commentCount,
  commentsProps,
  analysisProps,
  pageKey = "weekly-report",
  pageTitle = "经营周报",
  focusTargetId,
  focusTarget,
  visible = true,
}: {
  activeTab: "comments" | "analysis" | "message-board";
  onTabChange: (tab: "comments" | "analysis" | "message-board") => void;
  commentCount: number;
  railHeight: number;
  commentsProps: Omit<CommentsProps, "showHeader" | "composerScopeKey">;
  analysisProps: AnalysisProps;
  pageKey?: string;
  pageTitle?: string;
  overallPrompt?: string;
  focusTargetId?: string;
  focusTarget?: CommentTarget | null;
  onAnalysisTargetActivate?: (target: CommentTarget | null) => void;
  onAnalysisTargetDismiss?: (target: CommentTarget) => void;
  visible?: boolean;
}) {
  const [railWide, setRailWide] = useState(false);
  const selectedTarget = focusTarget || analysisProps.target || commentsProps.selectedTarget || null;
  const selectedDataPoint = useMemo(() => toSelectedDataPoint(selectedTarget), [selectedTarget]);

  useEffect(() => {
    const topicTable = analysisProps.topicTable;
    const topicSourceTable = topicTable ? [{
      id: topicTable.id,
      kind: "topic",
      name: topicTable.name,
      code: topicTable.code,
      datasetId: topicTable.datasetId,
      fields: topicTable.fields,
    }] : [];
    updateAnalysisWorkspacePageContext(pageKey, {
      workspace_key: `${pageKey}:${analysisProps.report.id}`,
      artifact_id: analysisProps.report.id,
      filters: { institution: analysisProps.selectedInstitution },
      selected_data_tables: topicSourceTable,
      selected_content: selectedDataPoint,
      analysis_skill: analysisProps.analysisSkill || {},
      analysis_policy: { engine: "IntelligentAnalysisEngine", resultDelivery: "data_first" },
    });
    replaceVisualAnalysisSourceGroup(pageKey, "weekly-topic", topicTable ? [{
      id: topicTable.id,
      label: topicTable.name,
      tables: topicSourceTable,
      question: topicTable.name,
    }] : []);
  }, [analysisProps.analysisSkill, analysisProps.report.id, analysisProps.selectedInstitution, analysisProps.topicTable, pageKey, selectedDataPoint]);

  if (!visible) return null;
  return (
    <ContextSideRail
      pageKey={pageKey}
      activeTab={activeTab}
      onTabChange={onTabChange}
      commentCount={commentCount}
      wide={railWide}
      onWideChange={setRailWide}
      comments={<CommentsPanel {...commentsProps} showHeader={false} composerScopeKey={`${analysisProps.tenantId}:${analysisProps.userId}:${analysisProps.report.id}`} />}
      analysis={<div className="flex h-full min-h-0 flex-col overflow-hidden"><AnalysisWorkspacePanel revealedDataPoint={selectedDataPoint} wide={railWide} onWideChange={setRailWide} /></div>}
      messageBoard={<MessageBoardPanel tenantId={analysisProps.tenantId} userId={analysisProps.userId} pageKey={pageKey} pageTitle={pageTitle} target={selectedTarget} />}
    />
  );
}

function toSelectedDataPoint(target: CommentTarget | null): SelectedDataPoint | undefined {
  if (!target) return undefined;
  const targetType = target.targetKind === "chart" ? "chart" : target.targetKind === "table" ? "table" : "text";
  return {
    targetType,
    targetId: target.id,
    label: target.label,
    values: {
      selected_content: target.selectedText || "",
      context_target_id: target.contextTargetId || target.id,
      context_target_kind: target.targetKind,
      focus_target_id: target.id,
    },
  };
}
