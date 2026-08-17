import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router";
import { usePlatformContext } from "../../platform/PlatformContext";
import type { SelectedDataPoint } from "../../services/analysisWorkspaceApi";
import { AnalysisWorkspacePanel, analysisWorkspaceRevealEvent } from "../analysis-workspace/AnalysisWorkspaceRail";
import { MessageBoardPanel } from "../message-board/MessageBoardPanel";
import { CommentsPanel } from "../weekly-report/CommentsPanel";
import type { CommentTarget } from "../weekly-report/domain";
import { useInstitutionCommentThread } from "./useInstitutionCommentThread";
import {
  ContextSideRail,
  contextRailRevealEvent,
  type ContextRailRevealTarget,
  type ContextRailTab,
} from "./ContextSideRail";

const pageDefinitions: Record<string, { pageKey: string; pageTitle: string }> = {
  "/funnel": { pageKey: "funnel", pageTitle: "业务漏斗" },
  "/sandbox": { pageKey: "sandbox", pageTitle: "经营沙盘" },
  "/supervision": { pageKey: "supervision", pageTitle: "机构督导" },
  "/email-daily": { pageKey: "email-daily", pageTitle: "邮件日报" },
  "/customers": { pageKey: "customers", pageTitle: "客群分析" },
  "/competition": { pageKey: "competition", pageTitle: "竞品分析" },
  "/self-analysis/visual-reports": { pageKey: "visual-reports", pageTitle: "可视化报表" },
  "/self-analysis/query": { pageKey: "self-analysis", pageTitle: "智能分析" },
  "/self-analysis/reports": { pageKey: "my-reports", pageTitle: "我的报表" },
  "/data-assets/metrics": { pageKey: "metric-management", pageTitle: "指标管理" },
  "/data-assets/data-management": { pageKey: "data-management", pageTitle: "数据管理" },
};

export function GlobalContextRail() {
  const location = useLocation();
  const definition = pageDefinitions[location.pathname];
  const { tenantId, userId, userName } = usePlatformContext();
  const [activeTab, setActiveTab] = useState<ContextRailTab>("analysis");
  const [wide, setWide] = useState(false);
  const [selectedDataPoint, setSelectedDataPoint] = useState<SelectedDataPoint>();
  const [selectedTarget, setSelectedTarget] = useState<CommentTarget | null>(null);
  const [draftTargets, setDraftTargets] = useState<CommentTarget[]>([]);
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [expandedReplyInputs, setExpandedReplyInputs] = useState<Record<string, boolean>>({});
  const [expandedCommentReplies, setExpandedCommentReplies] = useState<Record<string, boolean>>({});
  const [activeCommentId, setActiveCommentId] = useState<string | null>(null);
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const reportId = `context_page:${definition?.pageKey || "unavailable"}`;
  const { comments, createComment, replyToComment, resolveComment } = useInstitutionCommentThread({
    tenantId,
    userId,
    userName,
    reportId,
  });

  useEffect(() => {
    setWide(false);
    setSelectedDataPoint(undefined);
    setSelectedTarget(null);
    setDraftTargets([]);
    setCommentDrafts({});
    setReplyDrafts({});
    setExpandedReplyInputs({});
    setExpandedCommentReplies({});
    setActiveCommentId(null);
    setActiveDraftId(null);
  }, [definition?.pageKey, tenantId, userId]);

  useEffect(() => {
    const reveal = (event: Event) => {
      const detail = (event as CustomEvent<{ pageKey?: string; tab?: ContextRailTab; target?: ContextRailRevealTarget }>).detail;
      if (!definition || detail?.pageKey !== definition.pageKey) return;
      if (detail.tab) setActiveTab(detail.tab);
      if (!detail.target) return;
      const dataPoint: SelectedDataPoint = {
        targetType: detail.target.targetType,
        targetId: detail.target.targetId,
        label: detail.target.label,
        values: detail.target.values,
      };
      setSelectedDataPoint(dataPoint);
      const commentTarget = toCommentTarget(dataPoint);
      setSelectedTarget(commentTarget);
      if (detail.tab === "comments") {
        setDraftTargets((current) => current.some((item) => item.id === commentTarget.id) ? current : [commentTarget, ...current]);
        setCommentDrafts((current) => ({ ...current, [commentTarget.id]: current[commentTarget.id] || "" }));
        setActiveDraftId(commentTarget.id);
        setActiveCommentId(null);
      }
    };
    window.addEventListener(contextRailRevealEvent, reveal);
    return () => window.removeEventListener(contextRailRevealEvent, reveal);
  }, [definition]);

  useEffect(() => {
    const revealWorkspace = (event: Event) => {
      const detail = (event as CustomEvent<{ selectedDataPoint?: SelectedDataPoint; surface?: string }>).detail;
      if (detail?.surface && detail.surface !== "context-rail") return;
      setSelectedDataPoint(detail?.selectedDataPoint);
      if (detail?.selectedDataPoint) setSelectedTarget(toCommentTarget(detail.selectedDataPoint));
      setActiveTab("analysis");
    };
    window.addEventListener(analysisWorkspaceRevealEvent, revealWorkspace);
    return () => window.removeEventListener(analysisWorkspaceRevealEvent, revealWorkspace);
  }, []);

  const openComments = useMemo(() => comments.filter((comment) => comment.status === "open"), [comments]);
  if (!definition) return null;

  const saveComment = (targetId: string) => {
    const target = draftTargets.find((item) => item.id === targetId);
    const text = commentDrafts[targetId]?.trim();
    if (!target || !text) return;
    const pendingId = createComment(target, text);
    setDraftTargets((current) => current.filter((item) => item.id !== targetId));
    setCommentDrafts((current) => ({ ...current, [targetId]: "" }));
    setActiveDraftId(null);
    setActiveCommentId(pendingId || null);
  };

  const saveReply = (commentId: string) => {
    const text = replyDrafts[commentId]?.trim();
    if (!text) return;
    replyToComment(commentId, text);
    setReplyDrafts((current) => ({ ...current, [commentId]: "" }));
    setExpandedReplyInputs((current) => ({ ...current, [commentId]: false }));
  };

  return (
    <div className="hidden shrink-0 bg-[#f8f8fa] py-4 pr-4 lg:block" data-global-context-rail="true">
      <ContextSideRail
        pageKey={definition.pageKey}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        commentCount={openComments.length}
        wide={wide}
        onWideChange={setWide}
        comments={(
          <CommentsPanel
            showHeader={false}
            selectedTarget={selectedTarget}
            draftTargets={draftTargets}
            commentDrafts={commentDrafts}
            onDraftChange={(targetId, value) => setCommentDrafts((current) => ({ ...current, [targetId]: value }))}
            comments={openComments}
            replyDrafts={replyDrafts}
            expandedReplyInputs={expandedReplyInputs}
            expandedCommentReplies={expandedCommentReplies}
            highlightedCommentId={activeCommentId}
            activeCommentId={activeCommentId}
            activeDraftId={activeDraftId}
            railHeight={720}
            onSave={saveComment}
            onCommentActivate={(commentId) => { setActiveCommentId(commentId); setActiveDraftId(null); }}
            onResolveComment={resolveComment}
            onReplyDraftChange={(commentId, value) => setReplyDrafts((current) => ({ ...current, [commentId]: value }))}
            onReplyToggle={(commentId, expanded) => setExpandedReplyInputs((current) => ({ ...current, [commentId]: expanded }))}
            onReplySave={saveReply}
            onCommentRepliesToggle={(commentId, expanded) => setExpandedCommentReplies((current) => ({ ...current, [commentId]: expanded }))}
          />
        )}
        analysis={<div className="h-[calc(100vh-98px)]"><AnalysisWorkspacePanel revealedDataPoint={selectedDataPoint} wide={wide} onWideChange={setWide} /></div>}
        messageBoard={<MessageBoardPanel tenantId={tenantId} userId={userId} pageKey={definition.pageKey} pageTitle={definition.pageTitle} target={selectedTarget} />}
      />
    </div>
  );
}

function toCommentTarget(target: SelectedDataPoint): CommentTarget {
  const selectedText = valuePreview(target.values);
  return {
    id: target.targetId,
    contextTargetId: target.targetId,
    label: target.label || target.targetId,
    type: target.targetType === "chart" ? "图表" : target.targetType === "text" ? "文本" : "数据",
    targetKind: target.targetType === "chart" ? "chart" : target.targetType === "text" ? "paragraph" : "table",
    selectedText,
    anchorTop: 12,
  };
}

function valuePreview(values?: Record<string, unknown>) {
  if (!values) return "当前页面整体";
  const preferred = values.analysis_summary || values.question || values.metric_name || values.visualization_type;
  if (preferred) return String(preferred).slice(0, 500);
  try { return JSON.stringify(values).slice(0, 500); } catch { return "当前可视化"; }
}
