import { useEffect, useMemo, useState } from "react";
import { usePlatformContext } from "../platform/PlatformContext";
import { AnalysisUnderlineProvider, SelectableRegion } from "./weekly-report/SelectableRegion";
import { WeeklyReportSideRail } from "./weekly-report/WeeklyReportSideRail";
import { useInstitutionCommentThread } from "./context-rail/useInstitutionCommentThread";
import { revealContextRail } from "./context-rail/ContextSideRail";
import { replaceVisualAnalysisSourceGroup, updateAnalysisWorkspacePageContext } from "./analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "./analysis-workspace/visualAnalysisScope";
import { pageDataToSelection } from "./self-analysis/domain";
import { makeAnalysisSelectionTarget, makePageCommentTarget, makeTextBlock, type CommentTarget, type WeeklyInstitutionReport } from "./weekly-report/domain";
import { PAGE_DATA_PAGE_GUTTER_CLASS, PageDataVisualizationModules, usePageDataComposer, type PageDataComposerController } from "./page-data/PageDataComposer";
import { StandardAnalysisPageHeader, StandardAnalysisPageStickyNote } from "./page-data/StandardAnalysisPage";
import { useStickyNote } from "./notes/useStickyNote";

export function Dashboard() {
  const { tenantId, userId, userName, selectedInstitution, isSuperAdmin } = usePlatformContext();
  const [rightRailTab, setRightRailTab] = useState<"comments" | "analysis" | "message-board">("analysis");
  const [selectedContextTarget, setSelectedContextTarget] = useState<CommentTarget | null>(null);
  const [analysisTarget, setAnalysisTarget] = useState<CommentTarget | null>(null);
  const [analysisSelectionTargets, setAnalysisSelectionTargets] = useState<CommentTarget[]>([]);
  const [draftTargets, setDraftTargets] = useState<CommentTarget[]>([]);
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [expandedReplyInputs, setExpandedReplyInputs] = useState<Record<string, boolean>>({});
  const [expandedCommentReplies, setExpandedCommentReplies] = useState<Record<string, boolean>>({});
  const [activeCommentId, setActiveCommentId] = useState<string | null>(null);
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const pageData = usePageDataComposer({ pageCode: "dashboard", moduleKey: "dashboard", railPageKey: "multi-institution-analysis" });
  const stickyNote = useStickyNote("dashboard", "dashboard");

  useEffect(() => {
    if (!isSuperAdmin) pageData.setMode("browse");
  }, [isSuperAdmin, pageData.setMode]);
  const dashboardReportId = `multi_institution_${tenantId}`;
  const { comments, createComment, replyToComment, resolveComment } = useInstitutionCommentThread({
    tenantId,
    userId,
    userName,
    reportId: dashboardReportId,
  });

  useEffect(() => {
    updateAnalysisWorkspacePageContext("multi-institution-analysis", {
      artifact_id: dashboardReportId,
      filters: { institution: selectedInstitution },
      selected_content: pageData.visibleAssets.map((asset) => asset.name).join("、"),
      visualization: {
        asset_ids: pageData.visibleAssets.map((asset) => asset.id),
        visualization_types: pageData.visualTypes,
      },
    });
    replaceVisualAnalysisSourceGroup("multi-institution-analysis", "page-data", pageData.visibleAssets.map((asset) => ({
      id: asset.id,
      label: asset.name,
      tables: [pageDataToSelection(asset) as unknown as Record<string, unknown>],
      question: asset.name,
      summary: asset.sourceTableName || asset.name,
      rows: boundedVisualRows(pageData.rowsById[asset.id]?.rows),
    })));
  }, [dashboardReportId, pageData.rowsById, pageData.visibleAssets, pageData.visualTypes, selectedInstitution, tenantId]);

  useEffect(() => {
    setAnalysisTarget(null);
    setAnalysisSelectionTargets([]);
    setSelectedContextTarget(null);
    setDraftTargets([]);
    setCommentDrafts({});
    setReplyDrafts({});
    setExpandedReplyInputs({});
    setExpandedCommentReplies({});
    setActiveCommentId(null);
    setActiveDraftId(null);
  }, [tenantId, userId]);

  const dashboardReport = useMemo<WeeklyInstitutionReport>(() => ({
    id: dashboardReportId,
    institutionName: selectedInstitution,
    projectNo: "multi-institution-analysis",
    meetingTime: "",
    reporters: userName,
    period: "当前页面",
    status: "已编辑",
    owner: userId,
    sections: [{
      id: "dashboard_page",
      name: "多机构分析",
      blocks: [makeTextBlock("dashboard_snapshot", "多机构分析页面及关联指标数据", JSON.stringify({
        datasets: pageData.visibleAssets.map((asset) => ({
          id: asset.id,
          name: asset.name,
          sourceTableName: asset.sourceTableName,
          rowCount: pageData.rowsById[asset.id]?.row_count || 0,
        })),
      }))],
    }],
  }), [dashboardReportId, pageData.rowsById, pageData.visibleAssets, selectedInstitution, userId, userName]);

  const contextTarget = (id: string, label: string, type: CommentTarget["type"], selectedText: string): CommentTarget => ({
    id: `dashboard:${id}`,
    label,
    type,
    targetKind: type === "文本" ? "paragraph" : type === "图表" ? "chart" : "table",
    selectedText,
    blockId: "dashboard_snapshot",
  });

  const openDashboardComment = (target: CommentTarget) => {
    revealContextRail("multi-institution-analysis", "comments");
    setRightRailTab("comments");
    setSelectedContextTarget(target);
    setDraftTargets((current) => current.some((item) => item.id === target.id) ? current : [target, ...current]);
    setCommentDrafts((current) => ({ ...current, [target.id]: current[target.id] || "" }));
    setActiveDraftId(target.id);
    setActiveCommentId(null);
  };
  const openDashboardAnalysis = (target: CommentTarget) => {
    revealContextRail("multi-institution-analysis", "analysis");
    const analysisSelectionTarget = makeAnalysisSelectionTarget(target);
    if (analysisSelectionTarget.selectedText?.trim() && typeof analysisSelectionTarget.rangeStart === "number" && typeof analysisSelectionTarget.rangeEnd === "number") {
      setAnalysisSelectionTargets((current) => [analysisSelectionTarget, ...current.filter((item) => item.id !== analysisSelectionTarget.id)]);
    }
    setSelectedContextTarget(analysisSelectionTarget);
    setAnalysisTarget(analysisSelectionTarget);
    setRightRailTab("analysis");
  };
  const activateDashboardAnalysis = (target: CommentTarget, rect: DOMRect) => {
    revealContextRail("multi-institution-analysis", "analysis");
    const pageBody = document.querySelector<HTMLElement>("[data-context-page-body=\"multi-institution-analysis\"]");
    const bodyRect = pageBody?.getBoundingClientRect();
    const nextTarget = {
      ...target,
      anchorTop: bodyRect ? Math.max(12, rect.top - bodyRect.top) : target.anchorTop,
      anchorViewportTop: rect.top,
    };
    setAnalysisSelectionTargets((current) => [nextTarget, ...current.filter((item) => item.id !== nextTarget.id)]);
    setSelectedContextTarget(nextTarget);
    setAnalysisTarget(nextTarget);
    setRightRailTab("analysis");
    setActiveCommentId(null);
    setActiveDraftId(null);
  };
  const dashboardCommentAnnotations = useMemo<CommentTarget[]>(() => [
    ...draftTargets
      .filter((target) => target.selectedText?.trim() && typeof target.rangeStart === "number" && typeof target.rangeEnd === "number")
      .map((target) => ({ ...target, contextTargetId: target.contextTargetId || target.id, annotationKind: "comment" as const })),
    ...comments
      .filter((comment) => comment.status === "open" && comment.selectedText?.trim() && typeof comment.rangeStart === "number" && typeof comment.rangeEnd === "number")
      .map((comment) => ({
        id: comment.id,
        contextTargetId: comment.targetId,
        label: comment.targetLabel,
        type: comment.targetKind === "chart" ? "图表" as const : comment.targetKind === "paragraph" ? "文本" as const : "数据" as const,
        targetKind: comment.targetKind || "paragraph",
        selectedText: comment.selectedText,
        blockId: comment.blockId,
        itemId: comment.itemId,
        rangeStart: comment.rangeStart,
        rangeEnd: comment.rangeEnd,
        anchorTop: comment.anchorTop,
        annotationKind: "comment" as const,
      })),
  ], [comments, draftTargets]);
  const activateDashboardAnnotation = (target: CommentTarget, rect: DOMRect) => {
    if (target.annotationKind !== "comment") {
      activateDashboardAnalysis(target, rect);
      return;
    }
    revealContextRail("multi-institution-analysis", "comments");
    setRightRailTab("comments");
    setSelectedContextTarget(target);
    const isDraft = draftTargets.some((draft) => draft.id === target.id);
    setActiveDraftId(isDraft ? target.id : null);
    setActiveCommentId(isDraft ? null : target.id);
  };
  const saveDashboardComment = (targetId: string) => {
    const target = draftTargets.find((item) => item.id === targetId);
    const text = commentDrafts[targetId]?.trim();
    if (!target || !text) return;
    const pendingId = createComment(target, text);
    setDraftTargets((current) => current.filter((item) => item.id !== targetId));
    setCommentDrafts((current) => ({ ...current, [targetId]: "" }));
    setActiveDraftId(null);
    setActiveCommentId(pendingId || null);
  };
  const saveDashboardReply = (commentId: string) => {
    const text = replyDrafts[commentId]?.trim();
    if (!text) return;
    replyToComment(commentId, text);
    setReplyDrafts((current) => ({ ...current, [commentId]: "" }));
    setExpandedReplyInputs((current) => ({ ...current, [commentId]: false }));
  };
  const createDashboardPageComment = (text: string) => {
    const pendingId = createComment(makePageCommentTarget("multi-institution-analysis", "多机构分析"), text);
    setActiveDraftId(null);
    setActiveCommentId(pendingId || null);
  };

  const dashboardSideRail = (
    <WeeklyReportSideRail
      pageKey="multi-institution-analysis"
      pageTitle="多机构分析"
      overallPrompt="结合当前多机构分析页面和关联指标数据，比较各机构消费贷与经营贷的规模、趋势、效率和风险，给出关键差异与行动建议。"
      activeTab={rightRailTab}
      onTabChange={setRightRailTab}
      commentCount={comments.filter((comment) => comment.status === "open").length}
      railHeight={720}
      focusTargetId={selectedContextTarget?.id}
      focusTarget={rightRailTab === "analysis" || rightRailTab === "message-board" ? selectedContextTarget : null}
      onAnalysisTargetActivate={setSelectedContextTarget}
      onAnalysisTargetDismiss={(target) => {
        setAnalysisTarget((current) => current?.id === target.id ? null : current);
        setSelectedContextTarget((current) => current?.id === target.id ? null : current);
        setAnalysisSelectionTargets((current) => current.filter((item) => item.id !== target.id));
      }}
      commentsProps={{
        selectedTarget: selectedContextTarget,
        draftTargets,
        commentDrafts,
        onDraftChange: (targetId, value) => setCommentDrafts((current) => ({ ...current, [targetId]: value })),
        comments: comments.filter((comment) => comment.status === "open"),
        replyDrafts,
        expandedReplyInputs,
        expandedCommentReplies,
        highlightedCommentId: activeCommentId,
        activeCommentId,
        activeDraftId,
        railHeight: 720,
        onCreateComment: createDashboardPageComment,
        onSave: saveDashboardComment,
        onCommentActivate: (commentId) => { setActiveCommentId(commentId); setActiveDraftId(null); },
        onResolveComment: (commentId) => resolveComment(commentId),
        onReplyDraftChange: (commentId, value) => setReplyDrafts((current) => ({ ...current, [commentId]: value })),
        onReplyToggle: (commentId, expanded) => setExpandedReplyInputs((current) => ({ ...current, [commentId]: expanded })),
        onReplySave: saveDashboardReply,
        onCommentRepliesToggle: (commentId, expanded) => setExpandedCommentReplies((current) => ({ ...current, [commentId]: expanded })),
      }}
      analysisProps={{
        report: dashboardReport,
        target: analysisTarget,
        tenantId,
        userId,
        selectedInstitution,
        topicTable: null,
        analysisSkill: null,
        memoryIds: [],
        railHeight: 720,
        noDataMessage: "本页面没有找到这一数据，请检查要分析的内容",
      }}
    />
  );

  if (pageData.loading && !pageData.assets.length) {
    return <div className={PAGE_DATA_PAGE_GUTTER_CLASS}><DashboardPageHeader controller={pageData} canEditLayout={isSuperAdmin} stickyNote={stickyNote} /><DashboardState message="正在读取多机构页面数据…" embedded /></div>;
  }

  return <div className={PAGE_DATA_PAGE_GUTTER_CLASS}>
    <DashboardPageHeader controller={pageData} canEditLayout={isSuperAdmin} stickyNote={stickyNote} />
    <StandardAnalysisPageStickyNote stickyNote={stickyNote} />
    {(pageData.hasSelectedPageData || pageData.mode === "edit") && <PageDataVisualizationModules controller={pageData} showEditorControls={isSuperAdmin} layoutEditable={isSuperAdmin} showAssetPicker />}
    {pageData.waitingForPageDataRows && !pageData.hasSelectedPageData ? <DashboardState message="正在读取多机构页面数据…" embedded /> : null}
    {!pageData.loading && !pageData.waitingForPageDataRows && !pageData.hasSelectedPageData && <DashboardState message={pageData.notice || "请先在站内数据的「多机构页面」中配置要展示的数据。"} embedded />}
  </div>;
}

function DashboardPageHeader({ controller, canEditLayout, stickyNote }: { controller: PageDataComposerController; canEditLayout: boolean; stickyNote: ReturnType<typeof useStickyNote> }) {
  return <StandardAnalysisPageHeader title="多机构分析" description="展示站内数据「多机构页面」中配置的数据集" stickyNote={stickyNote} editController={controller} canEditLayout={canEditLayout} headerDataAttribute="multi-institution-analysis" />;
}

function DashboardState({ message, embedded = false }: { message: string; embedded?: boolean }) {
  return (
    <div className={embedded ? "min-w-0" : "p-7"}>
      {!embedded && <><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">多机构分析</h2><p className="text-[13px] text-[#aeaeb2] mt-1">消费贷 + 经营贷 双产品经营全景</p></>}
      <div className={`${embedded ? "mt-0" : "mt-6"} w-full rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]`}>{message}</div>
    </div>
  );
}
