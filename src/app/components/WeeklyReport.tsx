import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Download,
  FileText,
  GripVertical,
  Image as ImageIcon,
  MessageSquareText,
  MoreHorizontal,
  RefreshCcw,
  Send,
  ThumbsUp,
} from "lucide-react";
import { createClientUuid } from "../utils/clientUuid";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePlatformContext } from "../platform/PlatformContext";
import {
  cancelAsyncAnalysisRun,
  fetchAnalysisTask,
  waitForSelfAnalysis,
  type AnalysisProgressStep,
  type BackendAnalysisResponse,
} from "../services/analysisApi";
import { runApplicationAction } from "../services/applicationApi";
import { fetchDataAssets, type AnalysisSkillAsset, type TopicTableAsset } from "../services/dataAssetApi";
import { fetchOperatingSnapshot } from "../services/operatingSnapshotApi";
import {
  analyzeWeeklyReportVersion,
  createReportComment,
  deleteSavedAnalysisResult,
  fetchReportComments,
  fetchSavedAnalysisResults,
  fetchWeeklyReportVersions,
  mutateReportComment,
  saveWeeklyReportVersion,
  type ReportComment,
  type SavedAnalysisResult as BackendSavedAnalysisResult,
  type WeeklyLearningTask,
} from "../services/reportApi";
import { isDemoFallbackEnabled } from "../services/apiContext";
import { fetchReportImageObjectUrl, uploadReportImage } from "../services/reportAttachmentApi";
import { buildWeeklyAnalysisModules, CoreMetricChart, SavedAnalysisEmbed, WeeklyAnalysisModuleMenu, loadWeeklyAnalysisModulePreferences, weeklyAnalysisModuleStorageKey, type WeeklyAnalysisModule, type WeeklyAnalysisModuleSettings, type WeeklyDataModule } from "./weekly-report/AnalysisModules";
import {
  type AnalysisStatus,
  type ReportStatus,
  type CommentStatus,
  type CommentResolvedReason,
  type CommentTargetKind,
  type TableBlock,
  type TextBlock,
  type ReportBlock,
  type RichContentItem,
  type ReportSection,
  type ImageUploadContext,
  type WeeklyInstitutionReport,
  type CommentItem,
  type CommentTarget,
  type PendingTextSelection,
  type SavedAnalysisResult,
  type WeeklyReportVersion,
  type PublishableAnalysisMaterial,
  savedAnalysisStorageKey,
  reportCommentsStoragePrefix,
  weeklyReportVersionsStoragePrefix,
  reportPeriod,
  makeId,
  makeAnalysisSelectionTarget,
  makeStableIdSegment,
  tableHeaderItemId,
  tableCellItemId,
  chartAxisItemId,
  chartLegendItemId,
  createTextItems,
  createAnalysisContentItems,
  hasMeaningfulRichContent,
  clampImageWidth,
  clampImageHeight,
  makeTextBlock,
  serializeContentItems,
  createWeeklyReports,
  formatNow,
  formatDate,
  getCurrentWorkweekPeriod,
  statusClass,
  loadSavedAnalysisResults,
  reportCommentsStorageKey,
  loadLocalReportComments,
  saveLocalReportComments,
  weeklyReportVersionsStorageKey,
  cloneWeeklyReport,
  buildWeeklyReportVersionName,
  loadLocalWeeklyReportVersions,
  saveLocalWeeklyReportVersions,
  normalizeWeeklyReportVersions,
  weeklyLearningTaskMap,
  normalizeWeeklyReport,
  normalizeReportBlock,
  normalizeContentItems,
  normalizeComments,
  normalizeCommentStatus,
  normalizeResolvedReason,
  normalizeTargetKind,
  inferCommentTargetKind,
  inferCommentItemTargetKind,
  normalizeReplies,
  normalizeSavedAnalysisResult,
  sortSavedAnalysisResultsNewestFirst,
  normalizeStoredVisualizationType,
  normalizeSavedAnalysisRows,
  extractPublishableAnalysisMaterial,
  extractCoreWeeklyAnalysisMaterial,
} from "./weekly-report/domain";
import { AnalysisUnderlineProvider, FloatingSelectionActions, SelectableRegion } from "./weekly-report/SelectableRegion";
import { renderAnnotatedSvgText, renderAnnotatedText } from "./weekly-report/AnnotationText";
import { WeeklyReportSideRail } from "./weekly-report/WeeklyReportSideRail";
import { revealContextRail } from "./context-rail/ContextSideRail";
import { AnalysisProgressPanel } from "./self-analysis/AnalysisProgressPanel";
import { applyWeeklyCoreMetricSnapshot, buildWeeklyCoreMetricRows } from "./weekly-report/CoreMetrics";
import { downloadWeeklyExport, downloadWeeklyExportPdf, prepareWeeklyExportDocument, weeklyExportFilename, weeklyExportHtml, type WeeklyExportFormat } from "./weekly-report/exportReport";
import { PageDataModeToggle, PageDataVisualizationModules, usePageDataComposer } from "./page-data/PageDataComposer";
import { useVisualReportCollection } from "./visual-report/VisualReportLibrary";
import { VisualReportCards } from "./visual-report/VisualReportCards";

const WEEKLY_CORE_ANALYSIS_PROMPT = "结合在贷余额、放款金额、新增余额三个指标在不同机构、日期甚至客户经理下的数据表现，融合调用的指标记忆、skill进行分析，最终形成分析结论";

export function WeeklyReport() {
  const reportBodyRef = useRef<HTMLDivElement>(null);
  const analysisRevisionRef = useRef<Record<string, number>>({});
  const analysisRunRef = useRef<Record<string, string>>({});
  const autoAnalysisStartedRef = useRef<Set<string>>(new Set());
  const { selectedInstitution, tenantId, userId, userName } = usePlatformContext();
  const weeklyPageData = usePageDataComposer({ pageCode: "weekly_report", moduleKey: "weekly_report", railPageKey: "weekly-report" });
  const weeklyVisualReports = useVisualReportCollection("weekly");
  const [reports, setReports] = useState(() => createWeeklyReports(selectedInstitution, userName, userId));
  const [, setSavedAt] = useState(
    isDemoFallbackEnabled() ? "当前为显式演示模板" : "尚未绑定真实分析证据，当前草稿不可发布",
  );
  const [reportVersions, setReportVersions] = useState<WeeklyReportVersion[]>([]);
  const [weeklyLearningTasks, setWeeklyLearningTasks] = useState<Record<string, WeeklyLearningTask>>({});
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [viewingHistoryVersionId, setViewingHistoryVersionId] = useState<string | null>(null);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<WeeklyExportFormat>("html");
  const [includeExportComments, setIncludeExportComments] = useState(false);
  const [includeExportAnalysis, setIncludeExportAnalysis] = useState(true);
  const [isExporting, setIsExporting] = useState(false);
  const [isLoadingReportEvidence, setIsLoadingReportEvidence] = useState(false);
  const [savedAnalysisResults, setSavedAnalysisResults] = useState<SavedAnalysisResult[]>([]);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState("");
  const [analysisModuleSettings, setAnalysisModuleSettings] = useState<WeeklyAnalysisModuleSettings>(() =>
    loadWeeklyAnalysisModulePreferences(tenantId, userId),
  );
  const [weeklyBehaviorMemoryIds, setWeeklyBehaviorMemoryIds] = useState<string[] | null>(null);
  const [weeklyCoreContext, setWeeklyCoreContext] = useState<{ table: TopicTableAsset | null; skill: AnalysisSkillAsset | null }>({ table: null, skill: null });
  const [weeklyCoreDataReady, setWeeklyCoreDataReady] = useState(false);
  const [analysisProgressByBlock, setAnalysisProgressByBlock] = useState<Record<string, AnalysisProgressStep[]>>({});
  const [analysisErrorByBlock, setAnalysisErrorByBlock] = useState<Record<string, string>>({});
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [draftTargets, setDraftTargets] = useState<CommentTarget[]>([]);
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [selectedCommentTarget, setSelectedCommentTarget] = useState<CommentTarget | null>(null);
  const [analysisTarget, setAnalysisTarget] = useState<CommentTarget | null>(null);
  const [analysisSelectionTargets, setAnalysisSelectionTargets] = useState<CommentTarget[]>([]);
  const [rightRailTab, setRightRailTab] = useState<"comments" | "analysis" | "message-board">("comments");
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [expandedReplyInputs, setExpandedReplyInputs] = useState<Record<string, boolean>>({});
  const [expandedCommentReplies, setExpandedCommentReplies] = useState<Record<string, boolean>>({});
  const [highlightedCommentId, setHighlightedCommentId] = useState<string | null>(null);
  const [activeCommentId, setActiveCommentId] = useState<string | null>(null);
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const [pendingTextSelection, setPendingTextSelection] = useState<PendingTextSelection | null>(null);
  const [commentRailHeight, setCommentRailHeight] = useState(720);
  const commentRevisionRef = useRef(0);
  const commentPersistQueueRef = useRef<Promise<void>>(Promise.resolve());

  const activeReport = reports[0];
  const mainSections = activeReport.sections.slice(0, 2);
  const remainingSections = activeReport.sections.slice(2);
  const selectedAnalysis = savedAnalysisResults.find((item) => item.id === selectedAnalysisId);
  const visibleComments = comments.filter((comment) => comment.status !== "resolved");
  const analysisAnnotations = useMemo<CommentItem[]>(() => analysisSelectionTargets.map((target) => ({
    id: target.id,
    targetId: target.id,
    targetLabel: target.label,
    selectedText: target.selectedText,
    blockId: target.blockId,
    itemId: target.itemId,
    rangeStart: target.rangeStart,
    rangeEnd: target.rangeEnd,
    anchorTop: target.anchorTop,
    annotationKind: "analysis",
    status: "open",
    targetKind: target.targetKind,
    author: "AI分析",
    time: "",
    text: "",
    replies: [],
  })), [analysisSelectionTargets]);
  const draftAnnotations = useMemo<CommentItem[]>(() => draftTargets
    .filter((target) => target.selectedText?.trim() && typeof target.rangeStart === "number" && typeof target.rangeEnd === "number")
    .map((target) => ({
      id: target.id,
      targetId: target.id,
      targetLabel: target.label,
      selectedText: target.selectedText,
      blockId: target.blockId,
      itemId: target.itemId,
      rangeStart: target.rangeStart,
      rangeEnd: target.rangeEnd,
      anchorTop: target.anchorTop,
      annotationKind: "comment" as const,
      status: "open" as const,
      targetKind: target.targetKind,
      author: userName,
      time: "",
      text: "",
      replies: [],
    })), [draftTargets, userName]);
  const visibleAnnotations = rightRailTab === "analysis"
    ? [...analysisAnnotations, ...draftAnnotations, ...visibleComments]
    : [...draftAnnotations, ...visibleComments, ...analysisAnnotations];
  const highlightedAnnotationId = rightRailTab === "analysis"
    ? selectedCommentTarget?.id || null
    : activeDraftId || activeCommentId || highlightedCommentId;
  const activeHistoryVersion = reportVersions.find((version) => version.id === viewingHistoryVersionId);
  const coreMetricBlock = activeReport.sections
    .flatMap((section) => section.blocks)
    .find((block): block is TableBlock => block.type === "table" && block.id.endsWith("_core_metrics"));
  const analysisModules = useMemo<WeeklyAnalysisModule[]>(() => buildWeeklyAnalysisModules({
    coreMetricBlock,
    savedAnalysisResults,
    preferences: analysisModuleSettings.preferences,
    orderCustomized: analysisModuleSettings.orderCustomized,
  }), [analysisModuleSettings, coreMetricBlock, savedAnalysisResults]);
  const weeklyDataItems = useMemo<WeeklyDataModule[]>(() => {
    const preferenceById = new Map(analysisModuleSettings.preferences.map((item) => [item.id, item]));
    const defaults: WeeklyDataModule[] = [
      ...weeklyPageData.assets.map((asset) => ({
        id: `page-data:${asset.id}`,
        kind: "page-data" as const,
        title: asset.name,
        subtitle: `页面数据 · 原始表：${asset.sourceTableName}`,
        visible: weeklyPageData.layoutIds.includes(asset.id),
        deletable: false,
        sourceId: asset.id,
      })),
      ...analysisModules.filter((module) => module.kind === "core").map((module) => ({
        id: module.id,
        kind: "core" as const,
        title: module.title,
        subtitle: `页面数据 · 分析时间：${module.analysisTime}`,
        visible: module.visible,
        deletable: false,
        sourceId: module.id,
      })),
      ...weeklyVisualReports.reports.map((report) => ({
        id: `visual-report:${report.id}`,
        kind: "visual-report" as const,
        title: report.title,
        subtitle: `可视化报表 · ${report.cards.length} 个图表`,
        visible: preferenceById.get(`visual-report:${report.id}`)?.visible ?? true,
        deletable: true,
        sourceId: report.id,
      })),
      ...analysisModules.filter((module) => module.kind === "saved").map((module) => ({
        id: module.id,
        kind: "saved-analysis" as const,
        title: module.title,
        subtitle: `智能分析 · 分析时间：${module.analysisTime}`,
        visible: module.visible,
        deletable: true,
        sourceId: module.savedAnalysisId || module.id,
      })),
    ];
    if (!analysisModuleSettings.orderCustomized) return defaults;
    const itemById = new Map(defaults.map((item) => [item.id, item]));
    return [
      ...analysisModuleSettings.preferences.map((item) => itemById.get(item.id)).filter((item): item is WeeklyDataModule => Boolean(item)),
      ...defaults.filter((item) => !preferenceById.has(item.id)),
    ];
  }, [analysisModuleSettings.orderCustomized, analysisModuleSettings.preferences, analysisModules, weeklyPageData.assets, weeklyPageData.layoutIds, weeklyVisualReports.reports]);

  useEffect(() => {
    setReports(createWeeklyReports(selectedInstitution, userName, userId));
    setViewingHistoryVersionId(null);
    setSelectedAnalysisId("");
    setAnalysisTarget(null);
    setAnalysisSelectionTargets([]);
    setRightRailTab("comments");
    setSavedAt(isDemoFallbackEnabled() ? "当前为显式演示模板" : "尚未绑定真实分析证据，当前草稿不可发布");
  }, [selectedInstitution, tenantId, userId, userName]);

  useEffect(() => {
    setAnalysisModuleSettings(loadWeeklyAnalysisModulePreferences(tenantId, userId));
    setWeeklyBehaviorMemoryIds(null);
    setWeeklyCoreContext({ table: null, skill: null });
    setWeeklyCoreDataReady(false);
  }, [tenantId, userId]);

  useEffect(() => {
    window.localStorage.setItem(
      weeklyAnalysisModuleStorageKey(tenantId, userId),
      JSON.stringify({ version: 4, orderCustomized: analysisModuleSettings.orderCustomized, preferences: weeklyDataItems.map(({ id, visible }) => ({ id, visible })) }),
    );
  }, [analysisModuleSettings.orderCustomized, tenantId, userId, weeklyDataItems]);

  useEffect(() => {
    let cancelled = false;
    void fetchDataAssets({ tenantId, userId })
      .then((bundle) => {
        if (cancelled) return;
        setWeeklyBehaviorMemoryIds(
          (bundle.behavior_habits || [])
            .filter((habit) => habit.lifecycleStatus === "active" && habit.status !== "历史归档")
            .map((habit) => habit.id),
        );
        setWeeklyCoreContext({
          table: (bundle.topic_tables || []).find((table) => table.id === "topic_core_weekly_metrics") || null,
          skill: (bundle.analysis_skills || []).find((skill) => skill.id === "topic-descriptive" && skill.enabled !== false) || null,
        });
      })
      .catch(() => {
        if (!cancelled) setWeeklyBehaviorMemoryIds([]);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);


  useEffect(() => {
    if (viewingHistoryVersionId) return;
    let cancelled = false;
    setWeeklyCoreDataReady(false);
    void fetchOperatingSnapshot({ tenantId, userId, view: "weekly_report" })
      .then((snapshot) => {
        if (cancelled) return;
        const dataset = snapshot.datasets.weekly_core_metrics;
        if (!dataset || dataset.status !== "ready" || !dataset.rows.length) {
          setSavedAt("经营周报三指标数据源暂不可用，未启动结论分析");
          return;
        }
        const rows = buildWeeklyCoreMetricRows(dataset);
        setReports((current) => applyWeeklyCoreMetricSnapshot(current, dataset, rows, formatNow()));
        setWeeklyCoreDataReady(true);
        setSavedAt(`经营周报三指标已直接载入 ${rows.length} 个周期；AI 结论正在异步加工`);
      })
      .catch((error) => {
        if (!cancelled) setSavedAt(error instanceof Error ? `经营周报指标载入失败：${error.message}` : "经营周报指标载入失败");
      });
    return () => {
      cancelled = true;
    };
  }, [activeReport.id, tenantId, userId, viewingHistoryVersionId]);


  useEffect(() => {
    if (!coreMetricBlock || !weeklyCoreDataReady || weeklyBehaviorMemoryIds === null || !weeklyCoreContext.table || !weeklyCoreContext.skill || viewingHistoryVersionId) return;
    const key = `${tenantId}:${activeReport.id}`;
    if (autoAnalysisStartedRef.current.has(key)) return;
    autoAnalysisStartedRef.current.add(key);
    void generateAnalysis(coreMetricBlock, { automatic: true });
  }, [activeReport.id, coreMetricBlock?.id, tenantId, viewingHistoryVersionId, weeklyBehaviorMemoryIds, weeklyCoreContext, weeklyCoreDataReady]);

  useEffect(() => {
    const refreshSavedAnalysis = async () => {
      try {
        const response = await fetchSavedAnalysisResults({ tenantId });
        setSavedAnalysisResults(sortSavedAnalysisResultsNewestFirst(
          response.results
            .filter((result) => result.weeklyReportEligible === true)
            .map(normalizeSavedAnalysisResult),
        ));
      } catch {
        setSavedAnalysisResults(isDemoFallbackEnabled() ? loadSavedAnalysisResults() : []);
      }
    };

    void refreshSavedAnalysis();
    const refresh = () => void refreshSavedAnalysis();
    window.addEventListener("storage", refresh);
    window.addEventListener("smart-data-agent-analysis-saved", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("smart-data-agent-analysis-saved", refresh);
    };
  }, [tenantId]);

  useEffect(() => {
    let cancelled = false;
    const refreshVersions = async () => {
      try {
        const response = await fetchWeeklyReportVersions({ tenantId, userId });
        if (cancelled) return;
        const versions = normalizeWeeklyReportVersions(response.versions);
        setReportVersions(versions);
        setWeeklyLearningTasks(weeklyLearningTaskMap(response.analysis_tasks || []));
        if (versions.length) saveLocalWeeklyReportVersions(tenantId, versions);
      } catch {
        if (!cancelled) {
          setReportVersions(isDemoFallbackEnabled() ? loadLocalWeeklyReportVersions(tenantId) : []);
          setWeeklyLearningTasks({});
        }
      }
    };
    void refreshVersions();
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  useEffect(() => {
    setReportVersions(isDemoFallbackEnabled() ? loadLocalWeeklyReportVersions(tenantId) : []);
    setViewingHistoryVersionId(null);
    setIsHistoryOpen(false);
  }, [tenantId]);

  useEffect(() => {
    if (!isHistoryOpen) return;
    const handleDocumentMouseDown = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest("[data-weekly-history-menu]")) return;
      setIsHistoryOpen(false);
    };
    document.addEventListener("mousedown", handleDocumentMouseDown);
    return () => document.removeEventListener("mousedown", handleDocumentMouseDown);
  }, [isHistoryOpen]);

  useEffect(() => {
    const updateRailHeight = () => {
      setCommentRailHeight(Math.max(720, reportBodyRef.current?.scrollHeight ?? 0));
    };

    updateRailHeight();
    window.addEventListener("resize", updateRailHeight);
    return () => window.removeEventListener("resize", updateRailHeight);
  }, [reports, comments.length, draftTargets.length]);

  useEffect(() => {
    let cancelled = false;

    const loadComments = async () => {
      try {
        const response = await fetchReportComments({ tenantId, userId, reportId: activeReport.id });
        if (!cancelled) {
          setComments(normalizeComments(response.comments, userId, userName));
          commentRevisionRef.current = Number(response.revision || 0);
        }
      } catch {
        if (!cancelled) setComments(isDemoFallbackEnabled() ? loadLocalReportComments(tenantId, activeReport.id, userId, userName) : []);
      }
    };

    void loadComments();
    return () => {
      cancelled = true;
    };
  }, [activeReport.id, tenantId, userId, userName]);

  function enqueueCommentMutation(
    execute: (expectedRevision: number) => Promise<{ comments: ReportComment[]; revision: number }>,
    localFallback: CommentItem[],
  ) {
    const reportId = activeReport.id;
    commentPersistQueueRef.current = commentPersistQueueRef.current.then(async () => {
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const response = await execute(commentRevisionRef.current);
          commentRevisionRef.current = Number(response.revision || commentRevisionRef.current + 1);
          setComments(normalizeComments(response.comments, userId, userName));
          return;
        } catch {
          try {
            const latest = await fetchReportComments({ tenantId, userId, reportId });
            commentRevisionRef.current = Number(latest.revision || 0);
            setComments(normalizeComments(latest.comments, userId, userName));
          } catch {
            break;
          }
        }
      }
      if (isDemoFallbackEnabled()) {
        saveLocalReportComments(tenantId, reportId, localFallback);
      }
    });
  }

  function getAnchorTop(rect?: DOMRect) {
    const bodyRect = reportBodyRef.current?.getBoundingClientRect();
    if (!bodyRect || !rect) return 84;
    return Math.max(84, rect.top - bodyRect.top);
  }

  function getRegionAnchorTop(targetId: string) {
    const element = document.querySelector(`[data-comment-target="${targetId}"]`);
    return getAnchorTop(element?.getBoundingClientRect());
  }

  function getSelectionButtonPosition(rect: DOMRect) {
    const bodyRect = reportBodyRef.current?.getBoundingClientRect();
    if (!bodyRect) return { top: 84, left: 16 };
    return {
      top: Math.max(12, rect.top - bodyRect.top - 42),
      left: Math.min(Math.max(12, rect.left - bodyRect.left), Math.max(12, bodyRect.width - 72)),
    };
  }

  function getDirtyDraft() {
    return draftTargets.find((target) => Boolean(commentDrafts[target.id]?.trim()));
  }

  useEffect(() => {
    const hasEmptyDraft = draftTargets.some((target) => !commentDrafts[target.id]?.trim());
    if (!pendingTextSelection && !hasEmptyDraft) return;

    const handleDocumentMouseDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest("[data-draft-id]") || target.closest("[data-weekly-selection-action]")) return;

      if (pendingTextSelection) {
        setPendingTextSelection(null);
      }

      if (!draftTargets.some((draftTarget) => !commentDrafts[draftTarget.id]?.trim())) return;
      setDraftTargets((current) => current.filter((draftTarget) => commentDrafts[draftTarget.id]?.trim()));
      setCommentDrafts((current) => {
        const next = { ...current };
        draftTargets.forEach((draftTarget) => {
          if (!next[draftTarget.id]?.trim()) {
            delete next[draftTarget.id];
          }
        });
        return next;
      });
      setActiveDraftId((current) => {
        if (!current) return current;
        return commentDrafts[current]?.trim() ? current : null;
      });
    };

    document.addEventListener("mousedown", handleDocumentMouseDown);
    return () => document.removeEventListener("mousedown", handleDocumentMouseDown);
  }, [commentDrafts, draftTargets, pendingTextSelection]);

  function focusDraft(targetId: string) {
    setActiveDraftId(targetId);
    setActiveCommentId(null);
    window.setTimeout(() => {
      const draftElement = document.querySelector(`[data-draft-id="${targetId}"]`);
      draftElement?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      draftElement?.querySelector("textarea")?.focus();
    }, 0);
  }

  function prepareTextComment(target: CommentTarget, rect: DOMRect) {
    const dirtyDraft = getDirtyDraft();
    if (dirtyDraft) {
      setPendingTextSelection(null);
      focusDraft(dirtyDraft.id);
      return;
    }

    const nextTarget = {
      ...target,
      anchorTop: getAnchorTop(rect),
      anchorViewportTop: rect.top,
    };
    setDraftTargets([]);
    setCommentDrafts({});
    setActiveDraftId(null);
    setActiveCommentId(null);
    setSelectedCommentTarget(null);
    setPendingTextSelection({
      target: nextTarget,
      ...getSelectionButtonPosition(rect),
    });
  }

  function resolveComment(commentId: string, reason: CommentResolvedReason = "manual") {
    setPendingTextSelection(null);
    setActiveDraftId(null);
    setActiveCommentId(null);
    setHighlightedCommentId(null);
    window.setTimeout(() => {
      try {
        window.getSelection()?.removeAllRanges();
      } catch {
        // Selection can already be detached after a comment menu unmounts.
      }
      setComments((current) => {
        const next = current.map((comment) =>
          comment.id === commentId
            ? {
                ...comment,
                status: "resolved" as const,
                resolvedAt: formatNow(),
                resolvedBy: userId,
                resolvedReason: reason,
                targetKind: comment.targetKind ?? inferCommentItemTargetKind(comment),
              }
            : comment,
        );
        enqueueCommentMutation(
          (expectedRevision) =>
            mutateReportComment({
              tenantId,
              userId,
              reportId: activeReport.id,
              commentId,
              action: "resolve",
              payload: { reason },
              expectedRevision,
            }),
          next,
        );
        return next;
      });
    }, 0);
  }

  function resolveAnalysisComments(blockId: string, reason: CommentResolvedReason) {
    setComments((current) => {
      const next = current.map((comment) =>
        comment.status !== "resolved" && comment.blockId === blockId && comment.targetKind === "analysis"
          ? {
              ...comment,
              status: "resolved" as const,
              resolvedAt: formatNow(),
              resolvedBy: userId,
              resolvedReason: reason,
              targetKind: comment.targetKind ?? inferCommentItemTargetKind(comment),
            }
          : comment,
      );
      if (next === current || next.every((comment, index) => comment === current[index])) return current;
      current
        .filter(
          (comment) =>
            comment.status !== "resolved" && comment.blockId === blockId && comment.targetKind === "analysis",
        )
        .forEach((comment) =>
          enqueueCommentMutation(
            (expectedRevision) =>
              mutateReportComment({
                tenantId,
                userId,
                reportId: activeReport.id,
                commentId: comment.id,
                action: "resolve",
                payload: { reason },
                expectedRevision,
              }),
            next,
          ),
        );
      return next;
    });
  }

  function resolveBlockComments(blockIds: string[], reason: CommentResolvedReason) {
    const replacedIds = new Set(blockIds);
    if (!replacedIds.size) return;
    setComments((current) => {
      const next = current.map((comment) =>
        comment.status !== "resolved" && comment.blockId && replacedIds.has(comment.blockId)
          ? {
              ...comment,
              status: "resolved" as const,
              resolvedAt: formatNow(),
              resolvedBy: userId,
              resolvedReason: reason,
              targetKind: comment.targetKind ?? inferCommentItemTargetKind(comment),
            }
          : comment,
      );
      if (next.every((comment, index) => comment === current[index])) return current;
      current
        .filter(
          (comment) => comment.status !== "resolved" && Boolean(comment.blockId && replacedIds.has(comment.blockId)),
        )
        .forEach((comment) =>
          enqueueCommentMutation(
            (expectedRevision) =>
              mutateReportComment({
                tenantId,
                userId,
                reportId: activeReport.id,
                commentId: comment.id,
                action: "resolve",
                payload: { reason },
                expectedRevision,
              }),
            next,
          ),
        );
      return next;
    });
  }

  function updateBlock(blockId: string, updater: (block: ReportBlock) => ReportBlock) {
    setReports((current) =>
      current.map((report) => {
        if (report.id !== activeReport.id) return report;
        return {
          ...report,
          status: report.status === "已完成" ? "已编辑" : report.status,
          sections: report.sections.map((section) => ({
            ...section,
            blocks: section.blocks.map((block) => (block.id === blockId ? updater(block) : block)),
          })),
        };
      }),
    );
  }

  function updateReportMeta(key: "meetingTime" | "reporters" | "period", value: string) {
    setReports((current) =>
      current.map((report) =>
        report.id === activeReport.id
          ? { ...report, [key]: value, status: report.status === "已完成" ? "已编辑" : report.status }
          : report,
      ),
    );
  }

  function toggleAnalysisModule(module: WeeklyAnalysisModule) {
    const nextVisible = !module.visible;
    setAnalysisModuleSettings((current) => ({ ...current, preferences: weeklyDataItems.map((item) => ({ id: item.id, visible: item.id === module.id ? nextVisible : item.visible })) }));
    if (module.kind === "saved" && module.savedAnalysisId) {
      setSelectedAnalysisId(nextVisible ? module.savedAnalysisId : selectedAnalysisId === module.savedAnalysisId ? "" : selectedAnalysisId);
    }
  }

  function toggleWeeklyDataItem(item: WeeklyDataModule) {
    if (weeklyPageData.mode !== "edit") return;
    if (item.kind === "page-data") {
      weeklyPageData.toggleAsset(item.sourceId);
      return;
    }
    if (item.kind === "visual-report") {
      setAnalysisModuleSettings((current) => ({ ...current, preferences: weeklyDataItems.map((currentItem) => ({ id: currentItem.id, visible: currentItem.id === item.id ? !item.visible : currentItem.visible })) }));
      return;
    }
    const analysisModule = analysisModules.find((module) => module.id === item.id);
    if (analysisModule) toggleAnalysisModule(analysisModule);
  }

  function moveWeeklyDataItem(sourceId: string, targetId: string) {
    if (weeklyPageData.mode !== "edit") return;
    if (!sourceId || sourceId === targetId) return;
    const next = weeklyDataItems.map(({ id, visible }) => ({ id, visible }));
    const sourceIndex = next.findIndex((item) => item.id === sourceId);
    const targetIndex = next.findIndex((item) => item.id === targetId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    const [source] = next.splice(sourceIndex, 1);
    next.splice(targetIndex, 0, source);
    setAnalysisModuleSettings({ preferences: next, orderCustomized: true });
  }

  async function deleteWeeklyDataItem(item: WeeklyDataModule) {
    if (weeklyPageData.mode !== "edit" || !item.deletable) return;
    if (item.kind === "visual-report") {
      const report = weeklyVisualReports.reports.find((candidate) => candidate.id === item.sourceId);
      if (!report) return;
      const removed = await weeklyVisualReports.remove(report);
      if (removed) setAnalysisModuleSettings((current) => ({ ...current, preferences: current.preferences.filter((preference) => preference.id !== item.id) }));
      return;
    }
    if (item.kind === "saved-analysis") {
      const module = analysisModules.find((candidate) => candidate.id === item.id);
      if (module) await deleteAnalysisModule(module);
    }
  }
  async function deleteAnalysisModule(module: WeeklyAnalysisModule) {
    if (module.kind !== "saved" || !module.savedAnalysisId || !window.confirm(`确认删除“${module.title}”吗？`)) return;
    const resultIds = module.savedAnalysisIds?.length ? module.savedAnalysisIds : [module.savedAnalysisId];
    try {
      await Promise.all(resultIds.map((resultId) => deleteSavedAnalysisResult({ tenantId, userId, resultId })));
      setSavedAnalysisResults((current) => current.filter((item) => !resultIds.includes(item.id)));
      setAnalysisModuleSettings((current) => ({ ...current, preferences: current.preferences.filter((item) => item.id !== module.id) }));
      if (resultIds.includes(selectedAnalysisId)) setSelectedAnalysisId("");
      setSavedAt(`已删除分析模块“${module.title}”`);
    } catch (error) { setSavedAt(error instanceof Error ? `删除分析模块失败：${error.message}` : "删除分析模块失败"); }
  }
  function stopBlockAnalysis(blockId: string) {
    const block = activeReport.sections.flatMap((section) => section.blocks).find((item) => item.id === blockId);
    if (block?.type !== "table" || block.analysis.status !== "分析中") return;
    analysisRevisionRef.current[blockId] = (analysisRevisionRef.current[blockId] || 0) + 1;
    const runId = analysisRunRef.current[blockId];
    delete analysisRunRef.current[blockId];
    if (runId) {
      void cancelAsyncAnalysisRun({ runId, tenantId, userId }).catch(() => undefined);
    }
    updateBlock(blockId, (current) => current.type === "table"
      ? { ...current, analysis: { ...current.analysis, status: "已停止" } }
      : current);
    setSavedAt("已停止本次自动分析；尚未返回的内容不会写入周报。继续编辑不会触发模型。 ");
  }

  async function generateAnalysis(block: TableBlock, options: { automatic?: boolean } = {}) {
    const isCoreMetricBlock = block.id.endsWith("_core_metrics");
    const taskId = block.analysisTaskId || block.evidenceRef?.analysis_task_id;
    if (!isCoreMetricBlock && !taskId) {
      setSavedAt("重新生成已阻止：请先选择并载入一条已复核的真实分析结果");
      return;
    }
    const revision = (analysisRevisionRef.current[block.id] || 0) + 1;
    analysisRevisionRef.current[block.id] = revision;
    setAnalysisProgressByBlock((current) => ({ ...current, [block.id]: [] }));
    setAnalysisErrorByBlock((current) => ({ ...current, [block.id]: "" }));
    updateBlock(block.id, (current) => current.type === "table"
      ? {
          ...current,
          analysis: {
            ...current.analysis,
            status: "分析中",
            conclusion: options.automatic ? "" : current.analysis.conclusion,
            contentItems: options.automatic ? createAnalysisContentItems(current.id, "") : current.analysis.contentItems,
          },
        }
      : current);
    setIsLoadingReportEvidence(true);
    try {
      const sourceTask = taskId ? await fetchAnalysisTask({ taskId, tenantId, userId }) : null;
      const task = await waitForSelfAnalysis({
        question: isCoreMetricBlock
          ? WEEKLY_CORE_ANALYSIS_PROMPT
          : sourceTask?.question || block.title,
        tenantId,
        userId,
        requestId: createClientUuid(),
        onRun: (run) => {
          if (analysisRevisionRef.current[block.id] === revision) {
            analysisRunRef.current[block.id] = run.automation_run_id;
            setAnalysisProgressByBlock((current) => ({ ...current, [block.id]: run.progress_steps || [] }));
            setAnalysisErrorByBlock((current) => ({ ...current, [block.id]: run.error_summary || "" }));
          }
        },
        pageContext: {
          route: "weekly-report",
          selected_institution: selectedInstitution,
          analysis_trigger: "weekly_report_conclusion_regeneration",
          model_application_module: "weekly_report_conclusion_regeneration",
          parent_task_id: taskId || null,
          analysis_skill: isCoreMetricBlock ? {
            id: weeklyCoreContext.skill?.id || "topic-descriptive",
            category: weeklyCoreContext.skill?.category || "主题",
          } : null,
          analysis_context_skills: isCoreMetricBlock ? [{
            id: weeklyCoreContext.skill?.id || "topic-descriptive",
            category: weeklyCoreContext.skill?.category || "主题",
          }] : [],
          analysis_memory_ids: isCoreMetricBlock ? weeklyBehaviorMemoryIds || [] : [],
          selected_data_tables: isCoreMetricBlock
            ? [{ id: "topic_core_weekly_metrics", code: "core_weekly_metrics", name: "经营周报三指标" }]
            : [],
          conversation_session: isCoreMetricBlock ? {
            turn_count: 1,
            turns: [{
              role: "user",
              content: `经营周报三指标已由语义数据快照直出，不允许模型改写表格和图表。当前数据：${JSON.stringify(block.rows)}`,
            }],
          } : undefined,
          analysis_policy: isCoreMetricBlock ? { resultDelivery: "data_first" } : undefined,
          weekly_report_contract: isCoreMetricBlock
            ? {
                metrics: ["在贷余额", "放款金额", "新增余额"],
                skill: "描述性分析",
                format: "核心表现 / 周度趋势 / 异常与边界 / 经营建议",
                visualization: ["柱状图", "趋势图", "多维表格"],
              }
            : null,
        },
      });
      if (analysisRevisionRef.current[block.id] !== revision) return;
      const material = isCoreMetricBlock
        ? extractCoreWeeklyAnalysisMaterial(task)
        : extractPublishableAnalysisMaterial(task);
      resolveAnalysisComments(block.id, "source_text_replaced");
      updateBlock(block.id, (current) => {
        if (current.type !== "table") return current;
        if (isCoreMetricBlock) {
          return {
            ...current,
            analysisTaskId: task.task_id,
            evidenceRef: {
              ...(current.evidenceRef || { verified: false, reason: "" }),
              analysis_task_id: task.task_id,
              reason: `${current.evidenceRef?.reason || "语义数据快照已加载"}；AI 结论任务 ${task.task_id}`,
            },
            analysis: {
              status: material.conclusion ? "待确认" : "未生成",
              conclusion: material.conclusion,
              contentItems: createAnalysisContentItems(current.id, material.conclusion),
            },
          };
        }
        return {
          ...current,
          fields: material.fields,
          rows: material.rows,
          dataSource: material.dataSource,
          analysisTaskId: task.task_id,
          updatedAt: material.updatedAt || formatNow(),
          evidenceRef: {
            verified: task.status === "completed",
            reason: task.status === "completed" ? "服务端复核通过" : "开发数据已完成服务端语义校验",
            analysis_task_id: task.task_id,
            evidence_id: String(material.evidence?.evidence_id || ""),
            source_snapshot: material.evidence?.source_snapshot,
            data_source: material.dataSource,
          },
          analysis: {
            status: material.conclusion ? "待确认" : "未生成",
            conclusion: material.conclusion,
            contentItems: createAnalysisContentItems(current.id, material.conclusion),
          },
        };
      });
      setSavedAt(`${options.automatic ? "已自动" : "已重新"}通过“周报结论重新生成”应用模块生成任务 ${task.task_id}；表格与图表保持语义数据快照，仅更新分析结论`);
    } catch (error) {
      if (analysisRevisionRef.current[block.id] !== revision) return;
      setAnalysisErrorByBlock((current) => ({ ...current, [block.id]: error instanceof Error ? error.message : "复核结论刷新失败" }));
      updateBlock(block.id, (current) => current.type === "table"
        ? { ...current, analysis: { ...current.analysis, status: current.analysis.conclusion.trim() ? "待确认" : "未生成" } }
        : current);
      setSavedAt(error instanceof Error ? error.message : "复核结论刷新失败");
    } finally {
      if (analysisRevisionRef.current[block.id] === revision) {
        delete analysisRunRef.current[block.id];
        setIsLoadingReportEvidence(false);
      }
    }
  }

  function confirmAnalysis(blockId: string) {
    updateBlock(blockId, (current) => {
      if (current.type !== "table") return current;
      return {
        ...current,
        analysis: {
          ...current.analysis,
          status: "已确认",
        },
      };
    });
  }

  function openCommentDraft(target: CommentTarget, rect?: DOMRect) {
    revealContextRail("weekly-report", "comments");
    setRightRailTab("comments");
    const dirtyDraft = getDirtyDraft();
    if (dirtyDraft && dirtyDraft.id !== target.id) {
      focusDraft(dirtyDraft.id);
      setPendingTextSelection(null);
      return;
    }
    const nextTarget = {
      ...target,
      anchorTop: target.anchorTop ?? (rect ? getAnchorTop(rect) : getRegionAnchorTop(target.id)),
    };
    setDraftTargets([nextTarget]);
    setCommentDrafts((current) => ({ ...current, [nextTarget.id]: current[nextTarget.id] ?? "" }));
    setSelectedCommentTarget(null);
    setPendingTextSelection(null);
    setActiveDraftId(nextTarget.id);
    setActiveCommentId(null);
    focusDraft(nextTarget.id);
  }

  function openContextAnalysis(target: CommentTarget, rect?: DOMRect) {
    revealContextRail("weekly-report", "analysis");
    const analysisSelectionTarget = makeAnalysisSelectionTarget(target);
    const nextTarget = {
      ...analysisSelectionTarget,
      anchorTop: target.anchorTop ?? (rect ? getAnchorTop(rect) : getRegionAnchorTop(target.id)),
      anchorViewportTop: target.anchorViewportTop ?? rect?.top,
    };
    if (nextTarget.selectedText?.trim() && typeof nextTarget.rangeStart === "number" && typeof nextTarget.rangeEnd === "number") {
      setAnalysisSelectionTargets((current) => [nextTarget, ...current.filter((item) => item.id !== nextTarget.id)]);
    }
    setPendingTextSelection(null);
    setSelectedCommentTarget(nextTarget);
    setAnalysisTarget(nextTarget);
    setRightRailTab("analysis");
    setActiveCommentId(null);
    setActiveDraftId(null);
  }

  function addComment(targetId: string) {
    const text = commentDrafts[targetId]?.trim();
    const target = draftTargets.find((item) => item.id === targetId);
    if (!text || !target) return;
    const clientRequestId = makeId("comment_request");
    const nextComment: CommentItem = {
        id: `pending_${clientRequestId}`,
        targetId: target.id,
        targetLabel: target.label,
        selectedText: target.selectedText,
        blockId: target.blockId,
        itemId: target.itemId,
        rangeStart: target.rangeStart,
        rangeEnd: target.rangeEnd,
        anchorTop: target.anchorTop,
        status: "open",
        targetKind: target.targetKind,
        author: userName,
        time: formatNow(),
        text,
        replies: [],
      };
    setComments((current) => {
      const next = [nextComment, ...current];
      enqueueCommentMutation(
        (expectedRevision) =>
          createReportComment({
            tenantId,
            userId,
            reportId: activeReport.id,
            comment: {
              targetId: target.id,
              targetLabel: target.label,
              selectedText: target.selectedText,
              blockId: target.blockId,
              itemId: target.itemId,
              rangeStart: target.rangeStart,
              rangeEnd: target.rangeEnd,
              anchorTop: target.anchorTop,
              targetKind: target.targetKind,
              text,
            },
            expectedRevision,
            clientRequestId,
          }),
        next,
      );
      return next;
    });
    setActiveCommentId(nextComment.id);
    setHighlightedCommentId(nextComment.id);
    window.setTimeout(() => {
      setHighlightedCommentId((current) => (current === nextComment.id ? null : current));
    }, 1400);
    setCommentDrafts((current) => {
      const next = { ...current };
      delete next[targetId];
      return next;
    });
    setDraftTargets((current) => current.filter((item) => item.id !== targetId));
    setSelectedCommentTarget(null);
    setActiveDraftId(null);
  }

  function addReply(commentId: string) {
    const text = replyDrafts[commentId]?.trim();
    if (!text) return;
    const clientRequestId = makeId("reply_request");
    setComments((current) => {
      const next = current.map((comment) =>
        comment.id === commentId
          ? {
              ...comment,
              replies: [
                ...comment.replies,
                {
                  id: `pending_${clientRequestId}`,
                  author: userName,
                  time: formatNow(),
                  text,
                },
              ],
            }
          : comment,
      );
      enqueueCommentMutation(
        (expectedRevision) =>
          mutateReportComment({
            tenantId,
            userId,
            reportId: activeReport.id,
            commentId,
            action: "reply",
            payload: { text },
            expectedRevision,
            clientRequestId,
          }),
        next,
      );
      return next;
    });
    setReplyDrafts((current) => ({ ...current, [commentId]: "" }));
    setExpandedReplyInputs((current) => ({ ...current, [commentId]: false }));
    setExpandedCommentReplies((current) => ({ ...current, [commentId]: true }));
  }

  function highlightComment(commentId: string, rect?: DOMRect) {
    revealContextRail("weekly-report", "comments");
    setRightRailTab("comments");
    if (rect) {
      const nextTop = getAnchorTop(rect);
      setComments((current) => {
        const next = current.map((comment) => (comment.id === commentId ? { ...comment, anchorTop: nextTop } : comment));
        return next;
      });
    }
    setPendingTextSelection(null);
    setActiveDraftId(null);
    setActiveCommentId(commentId);
    setHighlightedCommentId(commentId);
    window.setTimeout(() => {
      setHighlightedCommentId((current) => (current === commentId ? null : current));
    }, 1400);
  }

  function activateTextAnnotation(annotationId: string, rect?: DOMRect) {
    const analysisSelection = analysisSelectionTargets.find((target) => target.id === annotationId);
    if (!analysisSelection) {
      highlightComment(annotationId, rect);
      return;
    }
    const nextTarget = {
      ...analysisSelection,
      anchorTop: rect ? getAnchorTop(rect) : analysisSelection.anchorTop,
      anchorViewportTop: rect?.top ?? analysisSelection.anchorViewportTop,
    };
    revealContextRail("weekly-report", "analysis");
    setAnalysisSelectionTargets((current) => current.map((target) => target.id === annotationId ? nextTarget : target));
    setRightRailTab("analysis");
    setPendingTextSelection(null);
    setActiveCommentId(null);
    setActiveDraftId(null);
    setSelectedCommentTarget(nextTarget);
    setAnalysisTarget(nextTarget);
  }

  async function saveReportVersion() {
    const savedAt = formatNow();
    const nextVersion: WeeklyReportVersion = {
      id: makeId("weekly_version"),
      name: buildWeeklyReportVersionName(activeReport),
      savedAt,
      tenantId,
      reportId: activeReport.id,
      report: cloneWeeklyReport(activeReport),
    };
    const analysisTaskRefs = Array.from(
      new Set(
        activeReport.sections.flatMap((section) =>
          section.blocks.flatMap((block) =>
            block.type === "table" && block.analysisTaskId ? [block.analysisTaskId] : [],
          ),
        ),
      ),
    );
    const versionPayload = {
      ...nextVersion,
      comments,
      analysisTaskRefs,
    };
    try {
      const response = await saveWeeklyReportVersion({
        tenantId,
        userId,
        version: versionPayload,
        analyze: true,
      });
      const savedVersion = normalizeWeeklyReportVersions([response.version])[0];
      if (savedVersion) {
        const mergedVersions = [savedVersion, ...reportVersions.filter((version) => version.id !== savedVersion.id)].slice(0, 30);
        setReportVersions(mergedVersions);
        if (isDemoFallbackEnabled()) saveLocalWeeklyReportVersions(tenantId, mergedVersions);
        setReports((current) => [cloneWeeklyReport(savedVersion.report), ...current.filter((report) => report.id !== savedVersion.report.id)]);
      }
      if (response.analysis_task?.version_id) {
        setWeeklyLearningTasks((current) => ({ ...current, [response.analysis_task!.version_id]: response.analysis_task! }));
      }
      const publicationStatus = String(response.version?.publicationStatus || "review_required");
      setSavedAt(
        publicationStatus === "ready"
          ? `版本已由服务端保存并通过证据校验 · ${savedAt}`
          : `版本已由服务端保存，但仍有未验证数据块，暂不可发布 · ${savedAt}`,
      );
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        const nextVersions = [nextVersion, ...reportVersions].slice(0, 30);
        setReportVersions(nextVersions);
        saveLocalWeeklyReportVersions(tenantId, nextVersions);
        setSavedAt(`服务端保存失败；显式演示模式下仅保存到本地 · ${savedAt}`);
      } else {
        setSavedAt(error instanceof Error ? `保存失败：${error.message}` : "保存失败：服务端未确认写入");
      }
    }
    await runApplicationAction({
      tenantId,
      userId,
      moduleKey: "weekly_report",
      action: "save_version",
      payload: { reportId: activeReport.id, report: activeReport, selectedInstitution, version: versionPayload },
    }).catch(() => undefined);
  }

  async function openReportHistory() {
    setIsHistoryOpen((current) => !current);
    if (!isHistoryOpen) {
      try {
        const response = await fetchWeeklyReportVersions({ tenantId, userId });
        const versions = normalizeWeeklyReportVersions(response.versions);
        setReportVersions(versions);
        setWeeklyLearningTasks(weeklyLearningTaskMap(response.analysis_tasks || []));
        if (versions.length) saveLocalWeeklyReportVersions(tenantId, versions);
      } catch {
        setReportVersions(isDemoFallbackEnabled() ? loadLocalWeeklyReportVersions(tenantId) : []);
      }
      setSavedAt(`历史版本已打开 · ${formatNow()}`);
      await runApplicationAction({
        tenantId,
        userId,
        moduleKey: "weekly_report",
        action: "open_history",
        payload: { reportId: activeReport.id, selectedInstitution },
      }).catch(() => undefined);
    }
  }

  function restoreReportVersion(version: WeeklyReportVersion) {
    const restoredReport = cloneWeeklyReport(version.report);
    setReports((current) => [restoredReport, ...current.filter((report) => report.id !== restoredReport.id)]);
    setViewingHistoryVersionId(version.id);
    setIsHistoryOpen(false);
    setSelectedAnalysisId("");
    setPendingTextSelection(null);
    setSelectedCommentTarget(null);
    setAnalysisTarget(null);
    setRightRailTab("comments");
    setDraftTargets([]);
    setCommentDrafts({});
    setActiveDraftId(null);
    setActiveCommentId(null);
    analysisRevisionRef.current = {};
  }

  async function reanalyzeReportVersion(version: WeeklyReportVersion) {
    setWeeklyLearningTasks((current) => ({
      ...current,
      [version.id]: {
        id: current[version.id]?.id || version.id,
        version_id: version.id,
        status: "分析中",
      },
    }));
    try {
      const response = await analyzeWeeklyReportVersion({ tenantId, userId, versionId: version.id, force: true });
      setWeeklyLearningTasks((current) => ({ ...current, [version.id]: response.analysis_task }));
      setSavedAt(`历史版本已重新分析 · ${formatNow()}`);
    } catch {
      setWeeklyLearningTasks((current) => ({
        ...current,
        [version.id]: {
          id: current[version.id]?.id || version.id,
          version_id: version.id,
          status: "分析失败",
          error_message: "后端重新分析失败",
        },
      }));
    }
  }

  async function loadLatestReportData() {
    if (!selectedAnalysis?.analysisTaskId) {
      setSavedAt("请先在“分析数据”中选择一条已保存、已复核的分析结果");
      return;
    }
    setIsLoadingReportEvidence(true);
    try {
      const task = await fetchAnalysisTask({ taskId: selectedAnalysis.analysisTaskId, tenantId, userId });
      const material = extractPublishableAnalysisMaterial(task);
      const previousTableBlockIds = activeReport.sections
        .slice(0, 2)
        .flatMap((section) => section.blocks)
        .filter((block): block is TableBlock => block.type === "table")
        .map((block) => block.id);
      const blockId = `${activeReport.id}_analysis_${makeStableIdSegment(task.task_id)}`;
      const verifiedTable: TableBlock = {
        id: blockId,
        type: "table",
        title: selectedAnalysis.title || selectedAnalysis.query || "智能分析结果",
        dataSource: material.dataSource,
        updatedAt: material.updatedAt,
        fields: material.fields,
        rows: material.rows,
        analysisTaskId: task.task_id,
        evidenceRef: {
          verified: false,
          reason: "pending_server_binding",
          analysis_task_id: task.task_id,
          execution_id: task.execution_id,
          evidence_id: material.evidence?.evidence_id,
          source_snapshot: material.evidence?.source_snapshot,
          data_source: material.dataSource,
        },
        analysis: {
          status: material.conclusion ? "待确认" : "未生成",
          conclusion: material.conclusion,
          contentItems: createAnalysisContentItems(blockId, material.conclusion),
        },
      };
      resolveBlockComments(previousTableBlockIds, "source_text_replaced");
      setReports((current) =>
        current.map((report, index) => {
          if (index !== 0) return report;
          return {
            ...report,
            period: getCurrentWorkweekPeriod(),
            status: "已编辑",
            sections: report.sections.map((section, sectionIndex) =>
              sectionIndex === 0
                ? { ...section, blocks: [verifiedTable] }
                : sectionIndex === 1
                  ? { ...section, blocks: [] }
                  : section,
            ),
          };
        }),
      );
      setViewingHistoryVersionId(null);
      setPendingTextSelection(null);
      setSelectedCommentTarget(null);
      setAnalysisTarget(null);
      setSavedAt(
        `已载入分析任务 ${task.task_id} 的 ${material.rows.length} 行真实数据；保存版本后由服务端再次校验行哈希`,
      );
    } catch (error) {
      setSavedAt(error instanceof Error ? error.message : "真实分析数据载入失败");
    } finally {
      setIsLoadingReportEvidence(false);
    }
  }

  async function exportReport() {
    await runApplicationAction({
      tenantId,
      userId,
      moduleKey: "weekly_report",
      action: "open_export_dialog",
      payload: { reportId: activeReport.id, filename: `${activeReport.institutionName}经营周报.pdf` },
    }).catch(() => undefined);
    setIsExportDialogOpen(true);
  }

  async function confirmExportReport() {
    const reportNode = reportBodyRef.current?.querySelector<HTMLElement>(".weekly-report-print-root");
    if (!reportNode || isExporting) return;
    setIsExporting(true);
    const filename = weeklyExportFilename(activeReport, exportFormat);
    try {
      await runApplicationAction({
        tenantId,
        userId,
        moduleKey: "weekly_report",
        action: "export_weekly_report",
        payload: {
          reportId: activeReport.id,
          filename,
          format: exportFormat,
          includeComments: includeExportComments,
          includeAiAnalysis: includeExportAnalysis,
        },
      }).catch(() => undefined);
      const documentNode = await prepareWeeklyExportDocument(reportNode, {
        includeComments: includeExportComments,
        includeAnalysis: includeExportAnalysis,
        report: activeReport,
        comments: visibleComments,
      });
      if (exportFormat === "html") {
        downloadWeeklyExport(new Blob([weeklyExportHtml(documentNode, activeReport)], { type: "text/html;charset=utf-8" }), filename);
      } else {
        await downloadWeeklyExportPdf(documentNode, filename);
      }
      setIsExportDialogOpen(false);
      setSavedAt(`经营周报已导出为 ${exportFormat.toUpperCase()} · ${formatNow()}`);
    } catch (error) {
      setSavedAt(error instanceof Error ? `周报导出失败：${error.message}` : "周报导出失败，请稍后重试。");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className="p-4 md:p-7">
      <div className="weekly-report-print-hidden flex flex-col gap-4 mb-6 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">银行经营分析周报工作台</h2>
            <span className={`text-[11px] px-2 py-0.5 rounded-full border ${statusClass(activeReport.status)}`}>
              {activeReport.status}
            </span>
          </div>
          <p className="text-[13px] text-[#aeaeb2] mt-1">
            机构周报生成与分析工作台 · {activeReport.institutionName}经营周报 · {activeReport.period}
          </p>
          {activeHistoryVersion && (
            <p className="mt-1 text-[12px] text-[#8a8a8e]">
              当前查看历史版本：{activeHistoryVersion.name} · 保存于 {activeHistoryVersion.savedAt}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PageDataModeToggle controller={weeklyPageData} onSave={saveReportVersion} className="weekly-report-page-data-mode-toggle" />
          <div className="relative" data-weekly-history-menu="true">
            <button
              onClick={() => void openReportHistory()}
              className="flex h-8 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#636366] transition-colors hover:bg-[#f2f2f7]"
            >
              <FileText className="w-3.5 h-3.5" />
              历史版本
            </button>
            {isHistoryOpen && (
              <div className="absolute right-0 top-[34px] z-[90] w-[280px] overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-xl shadow-black/10">
                <div className="border-b border-[#f0f0f2] px-3 py-2 text-[11px] text-[#8a8a8e]">已保存版本</div>
                <div className="max-h-[280px] overflow-y-auto py-1">
                  {reportVersions.length ? (
                    reportVersions.map((version) => {
                      const task = weeklyLearningTasks[version.id];
                      return (
                        <div
                          key={version.id}
                          className={`flex items-center gap-2 px-3 py-2 transition-colors hover:bg-[#f5f7fb] ${
                            version.id === viewingHistoryVersionId ? "bg-[#f0f6ff]" : "bg-white"
                          }`}
                        >
                          <button type="button" onClick={() => restoreReportVersion(version)} className="min-w-0 flex-1 text-left">
                            <span className="block truncate text-[12px] text-[#1d1d1f]">{version.name}</span>
                            <span className="mt-0.5 block text-[10px] text-[#aeaeb2]">
                              {version.savedAt} · 自学习 {task?.status || "待分析"}
                            </span>
                          </button>
                          <button
                            type="button"
                            onClick={() => void reanalyzeReportVersion(version)}
                            className="shrink-0 rounded-md bg-[#f2f2f7] px-2 py-1 text-[10px] text-[#636366] hover:bg-[#e5e5ea]"
                          >
                            重新分析
                          </button>
                        </div>
                      );
                    })
                  ) : (
                    <div className="px-3 py-5 text-center text-[12px] text-[#aeaeb2]">暂无历史版本</div>
                  )}
                </div>
              </div>
            )}
          </div>
          <button
            onClick={() => void exportReport()}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white transition-colors hover:bg-[#2c2c2e]"
          >
            <Download className="w-3.5 h-3.5" />
            导出
          </button>
        </div>
      </div>

      <div ref={reportBodyRef} className="relative grid gap-5 xl:grid-cols-[minmax(0,1fr)_auto]" data-context-page-body="weekly-report">
        <AnalysisUnderlineProvider
          targets={analysisSelectionTargets.filter((target) => !target.itemId)}
          activeTargetId={rightRailTab === "analysis" ? selectedCommentTarget?.id : undefined}
          onActivate={(target, rect) => activateTextAnnotation(target.id, rect)}
        >
        {pendingTextSelection && (
          <FloatingSelectionActions selection={pendingTextSelection} onOpenComment={openCommentDraft} onOpenAnalysis={openContextAnalysis} />
        )}
        <section className="weekly-report-print-root bg-white rounded-xl border border-[#f0f0f2] overflow-hidden">
          <div className="px-4 py-4 md:px-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-[180px]">
                <div className="weekly-report-print-hidden flex items-center gap-2 text-[12px] text-[#8a8a8e] mb-2">
                  <FileText className="w-3.5 h-3.5" />
                  <span>报告状态：{activeReport.status}</span>
                </div>
                <h3 className="whitespace-nowrap text-[20px] text-[#1d1d1f] tracking-tight">{activeReport.institutionName}经营周报</h3>
              </div>
              <div
                className="grid w-full grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)_minmax(190px,1.35fr)] lg:mr-[19px] lg:min-w-[540px] lg:max-w-[620px]"
                data-weekly-report-meta-grid="true"
              >
                {[
                  { label: "会议时间", key: "meetingTime" as const, value: activeReport.meetingTime },
                  { label: "汇报人", key: "reporters" as const, value: activeReport.reporters },
                  { label: "报告周期", key: "period" as const, value: activeReport.period },
                ].map((item) => (
                  <div key={item.label} className="rounded-lg px-2.5 py-1.5" data-report-meta-key={item.key}>
                    <div className="text-[10px] text-[#aeaeb2] mb-1">{item.label}</div>
                    <input
                      value={item.value}
                      onChange={(event) => updateReportMeta(item.key, event.target.value)}
                      className="w-full rounded-md border border-transparent bg-transparent px-0 py-0.5 text-[11px] leading-relaxed text-[#3a3a3c] outline-none transition-colors focus:border-[#d1d1d6] focus:bg-white focus:px-1"
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="px-4 pb-5 pt-2 md:px-6">
            <section className="mb-6 border-t border-[#f0f0f2] pt-2">
              <div className="flex flex-col gap-2 mb-3 md:flex-row md:items-center md:justify-between">
                <h4 className="text-[14px] text-[#1d1d1f]">一、业绩与业务波动</h4>
                <div className="weekly-report-print-hidden flex items-center gap-2">
                  {selectedAnalysis?.analysisTaskId && (
                    <button
                      type="button"
                      onClick={() => void loadLatestReportData()}
                      disabled={isLoadingReportEvidence}
                      className="h-[24px] rounded-md border border-[#d7e7ff] bg-[#f5f9ff] px-2.5 text-[11px] text-[#0a66c2] outline-none hover:bg-[#eaf3ff]"
                    >
                      {isLoadingReportEvidence ? "校验中" : viewingHistoryVersionId ? "载入最新" : "载入报告"}
                    </button>
                  )}
                  <WeeklyAnalysisModuleMenu
                    items={weeklyDataItems}
                    editable={weeklyPageData.mode === "edit"}
                    loading={weeklyPageData.loading || weeklyVisualReports.loading}
                    notice={weeklyPageData.notice || weeklyVisualReports.error}
                    onToggle={toggleWeeklyDataItem}
                    onMove={moveWeeklyDataItem}
                    onDelete={(item) => void deleteWeeklyDataItem(item)}
                  />
                </div>
              </div>
              <div className="space-y-4">
                {weeklyDataItems.filter((item) => item.visible).map((item) => {
                  let content: ReactNode;
                  if (item.kind === "page-data") {
                    content = weeklyPageData.loading ? null : <PageDataVisualizationModules controller={weeklyPageData} className="" assetIds={[item.sourceId]} showEditorControls={false} layoutEditable={weeklyPageData.mode === "edit"} />;
                  } else if (item.kind === "visual-report") {
                    const report = weeklyVisualReports.reports.find((candidate) => candidate.id === item.sourceId);
                    content = report ? <section className="rounded-xl border border-[#eef1ef] bg-white p-4" data-weekly-visual-report={report.id}>
                      <div className="mb-3"><h5 className="text-[12px] text-[#1d1d1f]">{report.title}</h5><p className="mt-1 text-[10px] text-[#9ba19e]">来自可视化报表 · {report.cards.length} 个图表</p></div>
                      <VisualReportCards report={report} railPageKey="weekly-report" layoutEditable={weeklyPageData.mode === "edit"} />
                    </section> : null;
                  } else if (item.kind === "saved-analysis") {
                    const module = analysisModules.find((candidate) => candidate.id === item.id);
                    const result = module?.savedAnalysisId ? savedAnalysisResults.find((candidate) => candidate.id === module.savedAnalysisId) : undefined;
                    content = result ? <SavedAnalysisEmbed result={result} /> : null;
                  } else {
                    content = mainSections.flatMap((section) => section.blocks).map((block) =>
                      block.type === "table" ? (
                        <ReportTable
                          key={block.id}
                          block={block}
                          selectedTargetId={selectedCommentTarget?.id}
                          onSelectTarget={setSelectedCommentTarget}
                          onOpenComment={openCommentDraft}
                          onOpenAnalysis={openContextAnalysis}
                          onAnalyze={() => generateAnalysis(block)}
                          onConfirm={() => confirmAnalysis(block.id)}
                          onAnalysisChange={(items) => {
                            const wasAnalyzing = block.analysis.status === "分析中";
                            stopBlockAnalysis(block.id);
                            updateBlock(block.id, (current) =>
                              current.type === "table"
                                ? {
                                    ...current,
                                    analysis: {
                                      status: wasAnalyzing ? "已停止" : hasMeaningfulRichContent(items) ? "待确认" : "未生成",
                                      conclusion: serializeContentItems(items),
                                      contentItems: items,
                                    },
                                  }
                                : current,
                            );
                          }}
                          comments={visibleAnnotations}
                          highlightedCommentId={highlightedAnnotationId}
                          onCreateTextComment={prepareTextComment}
                          onAnnotationClick={activateTextAnnotation}
                          imageUploadContext={{ tenantId, userId, reportId: activeReport.id }}
                          analysisProgress={analysisProgressByBlock[block.id] || []}
                          analysisError={analysisErrorByBlock[block.id] || ""}
                        />
                      ) : null,
                    );
                  }
                  if (!content) return null;
                  return <div key={item.id} className="relative" onDragOver={(event) => { if (weeklyPageData.mode === "edit") event.preventDefault(); }} onDrop={(event) => { event.preventDefault(); moveWeeklyDataItem(event.dataTransfer.getData("text/x-weekly-data-item"), item.id); }} data-weekly-visual-order-item={item.id}>
                    {weeklyPageData.mode === "edit" && <div className="weekly-report-print-hidden mb-1 flex h-7 items-center rounded-lg border border-dashed border-[#d8e5dd] bg-[#f8fbf9] px-2 text-[10px] text-[#718078]" draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/x-weekly-data-item", item.id); }} data-weekly-visual-order-handle={item.id}><span className="inline-flex cursor-grab items-center gap-1.5 active:cursor-grabbing"><GripVertical className="h-3.5 w-3.5" />拖动调整呈现顺序</span></div>}
                    {content}
                  </div>;
                })}
                {!weeklyDataItems.some((item) => item.visible) ? <div className="rounded-lg border border-dashed border-[#e5e5ea] px-4 py-10 text-center text-[12px] text-[#aeaeb2]">当前未显示周报数据，可切换到编辑后通过右上角按钮重新启用。</div> : null}
              </div>
            </section>

            <div className="space-y-4">
              {remainingSections.map((section) => (
                <section key={section.id} className="border-t border-[#f0f0f2] pt-4">
                  <h4 className="text-[14px] text-[#1d1d1f] mb-3">{section.name}</h4>
                  <div className="space-y-4">
                    {section.blocks.map((block) =>
                      block.type === "table" ? (
                        <ReportTable
                          key={block.id}
                          block={block}
                          selectedTargetId={selectedCommentTarget?.id}
                          onSelectTarget={setSelectedCommentTarget}
                          onOpenComment={openCommentDraft}
                          onOpenAnalysis={openContextAnalysis}
                          onAnalyze={() => generateAnalysis(block)}
                          onConfirm={() => confirmAnalysis(block.id)}
                          onAnalysisChange={(items) =>
                            updateBlock(block.id, (current) =>
                              current.type === "table"
                                ? {
                                    ...current,
                                    analysis: {
                                      status: hasMeaningfulRichContent(items) ? "待确认" : "未生成",
                                      conclusion: serializeContentItems(items),
                                      contentItems: items,
                                    },
                                  }
                                : current,
                              )
                          }
                          comments={visibleAnnotations}
                          highlightedCommentId={highlightedAnnotationId}
                          onCreateTextComment={prepareTextComment}
                          onAnnotationClick={activateTextAnnotation}
                          imageUploadContext={{ tenantId, userId, reportId: activeReport.id }}
                          analysisProgress={analysisProgressByBlock[block.id] || []}
                          analysisError={analysisErrorByBlock[block.id] || ""}
                        />
                      ) : (
                        <TextSection
                          key={block.id}
                          block={block}
                          selectedTargetId={selectedCommentTarget?.id}
                          onSelectTarget={setSelectedCommentTarget}
                          onOpenComment={openCommentDraft}
                          onOpenAnalysis={openContextAnalysis}
                          onChange={(items) =>
                            updateBlock(block.id, (current) =>
                              current.type === "text"
                                ? { ...current, content: serializeContentItems(items), contentItems: items }
                                : current,
                            )
                          }
                          comments={visibleAnnotations}
                          highlightedCommentId={highlightedAnnotationId}
                          onCreateTextComment={prepareTextComment}
                          onAnnotationClick={activateTextAnnotation}
                          imageUploadContext={{ tenantId, userId, reportId: activeReport.id }}
                        />
                      ),
                    )}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </section>

        <WeeklyReportSideRail
          activeTab={rightRailTab}
          onTabChange={setRightRailTab}
          commentCount={visibleComments.length}
          railHeight={commentRailHeight}
          pageKey="weekly-report"
          pageTitle="经营周报"
          overallPrompt="结合当前经营周报页面及其关联指标数据，对本周业绩变化、机构差异、风险信号和下一步行动进行总体分析。"
          focusTargetId={selectedCommentTarget?.id}
          focusTarget={rightRailTab === "analysis" || rightRailTab === "message-board" ? selectedCommentTarget : null}
          onAnalysisTargetActivate={(target) => setSelectedCommentTarget(target)}
          onAnalysisTargetDismiss={(target) => {
            setAnalysisTarget((current) => current?.id === target.id ? null : current);
            setSelectedCommentTarget((current) => current?.id === target.id ? null : current);
            setAnalysisSelectionTargets((current) => current.filter((item) => item.id !== target.id));
          }}
          commentsProps={{
            selectedTarget: selectedCommentTarget,
            draftTargets,
            commentDrafts,
            onDraftChange: (targetId, value) => setCommentDrafts((current) => ({ ...current, [targetId]: value })),
            comments: visibleComments,
            replyDrafts,
            expandedReplyInputs,
            expandedCommentReplies,
            highlightedCommentId,
            activeCommentId,
            activeDraftId,
            railHeight: commentRailHeight,
            onSave: addComment,
            onCommentActivate: (commentId) => { setActiveDraftId(null); setActiveCommentId(commentId); },
            onResolveComment: resolveComment,
            onReplyDraftChange: (commentId, value) => setReplyDrafts((current) => ({ ...current, [commentId]: value })),
            onReplyToggle: (commentId, expanded) => setExpandedReplyInputs((current) => ({ ...current, [commentId]: expanded })),
            onReplySave: addReply,
            onCommentRepliesToggle: (commentId, expanded) => setExpandedCommentReplies((current) => ({ ...current, [commentId]: expanded })),
          }}
          analysisProps={{
            report: activeReport,
            target: analysisTarget,
            tenantId,
            userId,
            selectedInstitution,
            topicTable: weeklyCoreContext.table,
            analysisSkill: weeklyCoreContext.skill,
            memoryIds: weeklyBehaviorMemoryIds || [],
            railHeight: commentRailHeight,
          }}
        />
        </AnalysisUnderlineProvider>
      </div>
      {isExportDialogOpen && (
        <div
          className="weekly-report-print-hidden fixed inset-0 z-[120] flex items-center justify-center bg-black/20 px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="weekly-report-export-title"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setIsExportDialogOpen(false);
          }}
        >
          <div className="w-full max-w-[360px] rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/15">
            <div className="border-b border-[#f0f0f2] px-4 py-3">
              <h3 id="weekly-report-export-title" className="text-[15px] text-[#1d1d1f]">
                导出经营周报
              </h3>
              <p className="mt-1 text-[12px] leading-relaxed text-[#8a8a8e]">
                导出文件只包含周报正文，不含左侧菜单、右侧工作台栏和页面右上角操作按钮。
              </p>
            </div>
            <div className="space-y-4 px-4 py-4">
              <fieldset>
                <legend className="mb-2 text-[12px] font-medium text-[#3a3a3c]">导出格式</legend>
                <div className="grid grid-cols-2 gap-2">
                  {([
                    ["html", "导出为 HTML", "独立可打开的周报网页"],
                    ["pdf", "导出为 PDF", "A4 版式的周报文件"],
                  ] as Array<[WeeklyExportFormat, string, string]>).map(([format, label, description]) => (
                    <label key={format} className={`cursor-pointer rounded-lg border px-3 py-2.5 ${exportFormat === format ? "border-[#1d1d1f] bg-[#f7f7f8]" : "border-[#e5e5ea] bg-white"}`}>
                      <span className="flex items-center gap-2"><input type="radio" name="weekly-export-format" checked={exportFormat === format} onChange={() => setExportFormat(format)} className="accent-[#1d1d1f]" /><span className="text-[12px] text-[#1d1d1f]">{label}</span></span>
                      <span className="mt-1 block pl-5 text-[10px] text-[#8a8a8e]">{description}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend className="mb-2 text-[12px] font-medium text-[#3a3a3c]">导出内容</legend>
                <div className="space-y-2">
                  <label className="flex cursor-pointer items-center justify-between rounded-lg border border-[#e5e5ea] px-3 py-2"><span><span className="block text-[12px] text-[#1d1d1f]">带评论</span><span className="mt-0.5 block text-[10px] text-[#8a8a8e]">附上已公开的周报评论与回复</span></span><input type="checkbox" checked={includeExportComments} onChange={(event) => setIncludeExportComments(event.target.checked)} className="h-4 w-4 accent-[#1d1d1f]" /></label>
                  <label className="flex cursor-pointer items-center justify-between rounded-lg border border-[#e5e5ea] px-3 py-2"><span><span className="block text-[12px] text-[#1d1d1f]">带 AI 分析</span><span className="mt-0.5 block text-[10px] text-[#8a8a8e]">附上已在周报中确认的 AI 分析结论</span></span><input type="checkbox" checked={includeExportAnalysis} onChange={(event) => setIncludeExportAnalysis(event.target.checked)} className="h-4 w-4 accent-[#1d1d1f]" /></label>
                </div>
              </fieldset>
            </div>
            <div className="flex items-center justify-end gap-2 px-4 py-3">
              <button
                type="button"
                onClick={() => setIsExportDialogOpen(false)}
                className="rounded-lg border border-[#e5e5ea] px-3 py-1.5 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void confirmExportReport()}
                disabled={isExporting}
                className="rounded-lg bg-[#1d1d1f] px-3 py-1.5 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-50"
              >
                {isExporting ? "导出中…" : "导出"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function ReportTable({
  block,
  selectedTargetId,
  onSelectTarget,
  onOpenComment,
  onOpenAnalysis,
  onAnalyze,
  onConfirm,
  onAnalysisChange,
  comments,
  highlightedCommentId,
  onCreateTextComment,
  onAnnotationClick,
  imageUploadContext,
  analysisProgress,
  analysisError,
}: {
  block: TableBlock;
  selectedTargetId?: string;
  onSelectTarget: (target: CommentTarget) => void;
  onOpenComment: (target: CommentTarget) => void;
  onOpenAnalysis: (target: CommentTarget) => void;
  onAnalyze: () => void;
  onConfirm: () => void;
  onAnalysisChange: (items: RichContentItem[]) => void;
  comments: CommentItem[];
  highlightedCommentId: string | null;
  onCreateTextComment: (target: CommentTarget, rect: DOMRect) => void;
  onAnnotationClick: (commentId: string, rect?: DOMRect) => void;
  imageUploadContext: ImageUploadContext;
  analysisProgress: AnalysisProgressStep[];
  analysisError: string;
}) {
  const [activeTab, setActiveTab] = useState<"analysis" | "trend">("trend");
  const trend = useMemo(() => createTrendData(block), [block]);
  const analysisItems = block.analysis.contentItems?.length
    ? block.analysis.contentItems
    : createAnalysisContentItems(block.id, block.analysis.conclusion);
  const analysisTextBlock: TextBlock = {
    id: `${block.id}_analysis`,
    type: "text",
    title: `${block.title} / 分析结论`,
    content: block.analysis.conclusion,
    contentItems: analysisItems,
  };
  const tableTarget: CommentTarget = {
    id: `${block.id}_data`,
    label: `${block.title} / 表格数据`,
    type: "数据",
    targetKind: "table",
    blockId: block.id,
  };
  const chartTarget: CommentTarget = {
    id: `${block.id}_trend`,
    label: `${block.title} / 可视化分析`,
    type: "图表",
    targetKind: "chart",
    blockId: block.id,
    itemId: `${block.id}_trend_region`,
  };
  return (
    <article className="rounded-lg border border-[#f0f0f2] overflow-hidden">
      <div className="px-4 py-3 bg-[#fafbfc] border-b border-[#f0f0f2] flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h5 className="text-[13px] text-[#1d1d1f]">{block.title}</h5>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[#aeaeb2] mt-1">
            <span>数据源：{block.dataSource}</span>
            <span>更新时间：{block.updatedAt}</span>
          </div>
        </div>
        <button
          onClick={onAnalyze}
          disabled={block.analysis.status === "分析中"}
          className="inline-flex h-[30px] w-[104px] items-center justify-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white text-[12px] text-[#636366] hover:bg-[#f2f2f7] transition-colors"
        >
          <RefreshCcw className={`w-3.5 h-3.5 ${block.analysis.status === "分析中" ? "animate-spin" : ""}`} />
          {block.analysis.status === "分析中" ? "正在分析" : "重新生成"}
        </button>
      </div>

      <SelectableRegion
        target={tableTarget}
        selectedTargetId={selectedTargetId}
        onSelect={onSelectTarget}
        onOpenComment={onOpenComment}
        onOpenAnalysis={onOpenAnalysis}
      >
        <div className="overflow-x-auto">
          <table className="min-w-[720px] w-full table-fixed text-[12px]">
            <thead className="bg-white">
              <tr className="border-b border-[#f0f0f2] text-[11px] text-[#8a8a8e]">
                {block.fields.map((field, fieldIndex) => {
                  const itemId = tableHeaderItemId(block.id, fieldIndex);
                  return (
                  <th key={field} className="text-left py-2.5 px-3 font-normal whitespace-nowrap">
                    <CommentableStaticText
                      value={field}
                      target={{
                        id: `${itemId}_selection`,
                        label: `${block.title} / 表头 / ${field}`,
                        type: "数据",
                        targetKind: "table",
                        blockId: block.id,
                        itemId,
                      }}
                      annotations={comments.filter((comment) => comment.targetKind === "table" && comment.itemId === itemId)}
                      highlightedCommentId={highlightedCommentId}
                      onCreateTextComment={onCreateTextComment}
                      onAnnotationClick={onAnnotationClick}
                      className="block truncate"
                    />
                  </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {!block.rows.length && (
                <tr className="border-b border-[#f8f8f8] bg-white last:border-b-0">
                  <td colSpan={Math.max(1, block.fields.length)} className="px-3 py-6 text-center text-[12px] text-[#aeaeb2]">
                    尚未绑定已复核的真实分析数据
                  </td>
                </tr>
              )}
              {block.rows.map((row, rowIndex) => (
                <tr key={`${block.id}_${rowIndex}`} className="border-b border-[#f8f8f8] bg-white last:border-b-0">
                  {block.fields.map((field, fieldIndex) => {
                    const value = String(row[field] ?? "");
                    const itemId = tableCellItemId(block.id, rowIndex, fieldIndex);
                    const rowLabel = String(row[block.fields[0]] ?? `第${rowIndex + 1}行`);
                    return (
                    <td key={field} className="py-2.5 px-3 text-[#3a3a3c]">
                      <CommentableStaticText
                        value={value}
                        target={{
                          id: `${itemId}_selection`,
                          label: `${block.title} / ${rowLabel} / ${field}`,
                          type: "数据",
                          targetKind: "table",
                          blockId: block.id,
                          itemId,
                        }}
                        annotations={comments.filter((comment) => comment.targetKind === "table" && comment.itemId === itemId)}
                        highlightedCommentId={highlightedCommentId}
                        onCreateTextComment={onCreateTextComment}
                        onAnnotationClick={onAnnotationClick}
                        className="block truncate"
                      />
                    </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SelectableRegion>

      <div className="border-t border-[#f0f0f2] p-4 bg-white">
        <div className="flex flex-col gap-2 mb-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex gap-px bg-[#f2f2f7] rounded-lg p-0.5 w-fit">
            {[
              { key: "trend", label: "可视化分析" },
              { key: "analysis", label: "分析结论" },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key as "analysis" | "trend")}
                className={`px-3 py-1.5 rounded-md text-[12px] transition-all ${
                  activeTab === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {activeTab === "analysis" ? (
            <div className="flex items-center gap-2">
              <span className={`text-[11px] px-2 py-0.5 rounded-full border ${statusClass(block.analysis.status)}`}>
                {block.analysis.status}
              </span>
              <button
                onClick={onConfirm}
                disabled={!block.analysis.conclusion.trim()}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-[#f2f2f7] text-[12px] text-[#636366] hover:bg-[#e5e5ea] transition-colors disabled:opacity-40"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                保存为正式结论
              </button>
            </div>
          ) : (
            <div className="text-[11px] text-[#aeaeb2]">
              分析口径：{trend.metricField}
            </div>
          )}
        </div>

        {activeTab === "analysis" ? (
          <div className="space-y-3" data-weekly-report-ai="true">
            {block.analysis.status === "分析中" && (
              <AnalysisProgressPanel
                steps={analysisProgress}
                running
                error={analysisError}
                hasResult={Boolean(block.analysis.conclusion.trim())}
              />
            )}
            <TextSection
              block={analysisTextBlock}
              selectedTargetId={selectedTargetId}
              onSelectTarget={onSelectTarget}
              onOpenComment={onOpenComment}
              onOpenAnalysis={onOpenAnalysis}
              onChange={onAnalysisChange}
              comments={comments.filter((comment) => comment.targetKind === "analysis" && comment.blockId === block.id)}
              highlightedCommentId={highlightedCommentId}
              onCreateTextComment={onCreateTextComment}
              onAnnotationClick={onAnnotationClick}
              placeholder={block.analysis.status === "分析中" ? "正在分析中…上方展示可审计的执行阶段；你可以直接输入，开始编辑后会立即停止本次模型分析。" : "点击重新生成，或直接在这里输入/修改分析结论。"}
              showHeader={false}
              articleClassName="rounded-lg bg-[#fafbfc] border border-[#f0f0f2]"
              editorClassName="min-h-[92px] rounded-lg px-3 py-2 focus-within:border-[#c7c7cc]"
              targetKind="analysis"
              commentBlockId={block.id}
              imageUploadContext={imageUploadContext}
            />
          </div>
        ) : (
          <SelectableRegion
            target={chartTarget}
            selectedTargetId={selectedTargetId}
            onSelect={onSelectTarget}
            onOpenComment={onOpenComment}
            onOpenAnalysis={onOpenAnalysis}
          >
            {block.id.endsWith("_core_metrics") ? <CoreMetricChart block={block} /> : (
              <TrendChart
                blockId={block.id}
                blockTitle={block.title}
                trend={trend}
                comments={comments.filter((comment) => comment.targetKind === "chart" && comment.blockId === block.id)}
                highlightedCommentId={highlightedCommentId}
                onCreateTextComment={onCreateTextComment}
                onAnnotationClick={onAnnotationClick}
              />
            )}
          </SelectableRegion>
        )}
      </div>
    </article>
  );
}

function createTrendData(block: TableBlock) {
  const dimensionField = block.fields[0];
  const metricField =
    ["当前余额", "本周余额", "达成率", "本周净增", "变化值"]
      .find((field) => block.fields.includes(field)) ??
    block.fields.find((field) => field !== dimensionField && block.rows.some((row) => parseMetricValue(row[field]) !== null)) ??
    block.fields[1];
  const periods = ["第24周", "第25周", "第26周", "第27周"];
  const factors = [0.86, 0.91, 0.96, 1];
  const series = block.rows.map((row, index) => String(row[dimensionField] ?? `序列${index + 1}`));
  const data = periods.map((period, index) => {
    const point: Record<string, string | number> = { period };
    block.rows.forEach((row, rowIndex) => {
      const label = series[rowIndex];
      const currentValue = parseMetricValue(row[metricField]) ?? 0;
      point[label] = Number((currentValue * factors[index]).toFixed(2));
    });
    return point;
  });

  return {
    data,
    series,
    metricField,
    unit: getMetricUnit(metricField),
  };
}

function parseMetricValue(value: string | number | undefined) {
  if (typeof value === "number") return value;
  if (!value) return null;
  const match = String(value).replace(/,/g, "").match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function getMetricUnit(metricField: string) {
  if (metricField.includes("率") || metricField.includes("进度")) return "%";
  if (metricField.includes("余额") || metricField.includes("净增") || metricField.includes("变化值")) return "亿";
  return "";
}

function TrendChart({
  blockId,
  blockTitle,
  trend,
  comments,
  highlightedCommentId,
  onCreateTextComment,
  onAnnotationClick,
}: {
  blockId: string;
  blockTitle: string;
  trend: {
    data: Record<string, string | number>[];
    series: string[];
    metricField: string;
    unit: string;
  };
  comments: CommentItem[];
  highlightedCommentId: string | null;
  onCreateTextComment: (target: CommentTarget, rect: DOMRect) => void;
  onAnnotationClick: (commentId: string, rect?: DOMRect) => void;
}) {
  const colors = ["#1d1d1f", "#8a8a8e", "#34a853", "#c7c7cc", "#636366"];

  return (
    <div className="rounded-lg bg-[#fafbfc] border border-[#f0f0f2] p-3">
      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={trend.data} margin={{ top: 12, right: 16, bottom: 4, left: -12 }}>
            <CartesianGrid stroke="#f0f0f2" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="period"
              tick={(props) => {
                const value = String(props.payload?.value ?? "");
                const itemId = chartAxisItemId(blockId, "x", value);
                return (
                  <CommentableSvgText
                    value={value}
                    x={Number(props.x ?? 0)}
                    y={Number(props.y ?? 0) + 10}
                    textAnchor="middle"
                    target={{
                      id: `${itemId}_selection`,
                      label: `${blockTitle} / 可视化分析 / 横轴 ${value}`,
                      type: "图表",
                      targetKind: "chart",
                      blockId,
                      itemId,
                    }}
                    annotations={comments.filter((comment) => comment.itemId === itemId)}
                    highlightedCommentId={highlightedCommentId}
                    onCreateTextComment={onCreateTextComment}
                    onAnnotationClick={onAnnotationClick}
                    className="text-[11px]"
                    fill="#8a8a8e"
                  />
                );
              }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tick={(props) => {
                const rawValue = String(props.payload?.value ?? "");
                const value = `${rawValue}${trend.unit}`;
                const itemId = chartAxisItemId(blockId, "y", value);
                return (
                  <CommentableSvgText
                    value={value}
                    x={Number(props.x ?? 0)}
                    y={Number(props.y ?? 0) + 4}
                    textAnchor="end"
                    target={{
                      id: `${itemId}_selection`,
                      label: `${blockTitle} / 可视化分析 / 纵轴 ${value}`,
                      type: "图表",
                      targetKind: "chart",
                      blockId,
                      itemId,
                    }}
                    annotations={comments.filter((comment) => comment.itemId === itemId)}
                    highlightedCommentId={highlightedCommentId}
                    onCreateTextComment={onCreateTextComment}
                    onAnnotationClick={onAnnotationClick}
                    className="text-[10px]"
                    fill="#aeaeb2"
                  />
                );
              }}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip
              contentStyle={{ borderRadius: 8, border: "1px solid #e5e5ea", fontSize: 12 }}
              formatter={(value, name) => [`${Number(value).toFixed(2)}${trend.unit}`, name]}
              labelStyle={{ color: "#636366" }}
            />
            {trend.series.map((name, index) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={colors[index % colors.length]}
                strokeWidth={index === 0 ? 2 : 1.6}
                dot={{ r: 2.5, strokeWidth: 1 }}
                activeDot={{ r: 4 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-3 mt-2 text-[11px] text-[#8a8a8e]">
        {trend.series.map((name, index) => (
          <span key={name} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colors[index % colors.length] }} />
            <CommentableStaticText
              value={name}
              target={{
                id: `${chartLegendItemId(blockId, name)}_selection`,
                label: `${blockTitle} / 可视化分析 / 图例 ${name}`,
                type: "图表",
                targetKind: "chart",
                blockId,
                itemId: chartLegendItemId(blockId, name),
              }}
              annotations={comments.filter((comment) => comment.itemId === chartLegendItemId(blockId, name))}
              highlightedCommentId={highlightedCommentId}
              onCreateTextComment={onCreateTextComment}
              onAnnotationClick={onAnnotationClick}
              className="inline-block"
            />
          </span>
        ))}
      </div>
    </div>
  );
}

function measureImageSize(src: string) {
  return new Promise<{ width: number; height: number }>((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve({ width: image.naturalWidth || 520, height: image.naturalHeight || 220 });
    image.onerror = () => reject(new Error("image_measure_failed"));
    image.src = src;
  });
}

function fitImageSize(width: number, height: number, maxWidth: number, maxHeight = 420) {
  const safeWidth = width > 0 ? width : 520;
  const safeHeight = height > 0 ? height : 220;
  const ratio = Math.min(1, maxWidth / safeWidth, maxHeight / safeHeight);
  return {
    width: clampImageWidth(safeWidth * ratio, maxWidth),
    height: clampImageHeight(safeHeight * ratio, maxHeight),
  };
}

async function createRichImageItem(
  prefix: string,
  file: File,
  maxWidth: number,
  uploadContext: ImageUploadContext,
): Promise<Extract<RichContentItem, { type: "image" }>> {
  const localObjectUrl = URL.createObjectURL(file);
  const measuredSize = await measureImageSize(localObjectUrl).catch(() => ({ width: 520, height: 220 }));
  URL.revokeObjectURL(localObjectUrl);
  const uploaded = await uploadReportImage({
    file,
    reportId: uploadContext.reportId,
    blockId: prefix,
    tenantId: uploadContext.tenantId,
    userId: uploadContext.userId,
  });
  const fittedSize = fitImageSize(measuredSize.width, measuredSize.height, maxWidth);
  return {
    id: makeId(prefix),
    type: "image",
    src: uploaded.absoluteContentUrl,
    name: file.name || "粘贴图片",
    attachmentId: uploaded.attachment.attachment_id,
    artifactId: uploaded.artifact.artifact_id,
    contentHash: uploaded.artifact.content_hash,
    ...fittedSize,
  };
}

function AutoResizeTextarea({
  value,
  onChange,
  onPaste,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={textareaRef}
      rows={1}
      value={value}
      placeholder={placeholder}
      onPaste={onPaste}
      onChange={(event) => onChange(event.target.value)}
      className="block w-full overflow-hidden resize-none bg-transparent px-0 py-1 text-[13px] text-[#3a3a3c] leading-[1.7] outline-none placeholder:text-[#c7c7cc]"
    />
  );
}

function getSelectionPayloadWithin(container: Element) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount || !container) return null;
  const range = selection.getRangeAt(0);
  if (!container.contains(range.commonAncestorContainer)) return null;

  const selectedText = selection.toString();
  if (!selectedText.trim()) return null;

  const beforeSelection = range.cloneRange();
  beforeSelection.selectNodeContents(container);
  beforeSelection.setEnd(range.startContainer, range.startOffset);
  const start = beforeSelection.toString().length;
  const end = start + selectedText.length;
  if (end <= start) return null;

  const rangeRect = range.getBoundingClientRect();
  const fallbackRect = container.getBoundingClientRect();
  const rect = rangeRect.width || rangeRect.height ? rangeRect : fallbackRect;
  return {
    selectedText,
    start,
    end,
    rect,
  };
}

function CommentableStaticText({
  value,
  target,
  annotations,
  highlightedCommentId,
  className = "",
  onCreateTextComment,
  onAnnotationClick,
}: {
  value: string;
  target: CommentTarget;
  annotations: CommentItem[];
  highlightedCommentId: string | null;
  className?: string;
  onCreateTextComment: (target: CommentTarget, rect: DOMRect) => void;
  onAnnotationClick: (commentId: string, rect?: DOMRect) => void;
}) {
  const textRef = useRef<HTMLSpanElement>(null);

  function handleTextSelection() {
    const textElement = textRef.current;
    if (!textElement) return;
    const payload = getSelectionPayloadWithin(textElement);
    if (!payload) return;

    onCreateTextComment(
      {
        ...target,
        selectedText: payload.selectedText.trim(),
        rangeStart: payload.start,
        rangeEnd: payload.end,
      },
      payload.rect,
    );
  }

  return (
    <span
      ref={textRef}
      data-commentable-text="true"
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      onMouseUp={() => window.setTimeout(handleTextSelection)}
      className={className}
    >
      {renderAnnotatedText(value, annotations, highlightedCommentId, onAnnotationClick)}
    </span>
  );
}

function CommentableSvgText({
  value,
  x,
  y,
  textAnchor,
  target,
  annotations,
  highlightedCommentId,
  onCreateTextComment,
  onAnnotationClick,
  className = "",
  fill = "#8a8a8e",
}: {
  value: string;
  x: number;
  y: number;
  textAnchor: "start" | "middle" | "end";
  target: CommentTarget;
  annotations: CommentItem[];
  highlightedCommentId: string | null;
  onCreateTextComment: (target: CommentTarget, rect: DOMRect) => void;
  onAnnotationClick: (commentId: string, rect?: DOMRect) => void;
  className?: string;
  fill?: string;
}) {
  const textRef = useRef<SVGTextElement>(null);

  function handleTextSelection() {
    const textElement = textRef.current;
    if (!textElement) return;
    const payload = getSelectionPayloadWithin(textElement);
    if (!payload) return;

    onCreateTextComment(
      {
        ...target,
        selectedText: payload.selectedText.trim(),
        rangeStart: payload.start,
        rangeEnd: payload.end,
      },
      payload.rect,
    );
  }

  return (
    <text
      ref={textRef}
      data-commentable-text="true"
      x={x}
      y={y}
      textAnchor={textAnchor}
      fill={fill}
      pointerEvents="all"
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      onMouseUp={() => window.setTimeout(handleTextSelection)}
      className={className}
      style={{ userSelect: "text", WebkitUserSelect: "text" }}
    >
      {renderAnnotatedSvgText(value, annotations, highlightedCommentId, onAnnotationClick)}
    </text>
  );
}

function getCaretOffsetFromPoint(container: Element, x: number, y: number) {
  const documentWithCaret = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  };
  const range = documentWithCaret.caretRangeFromPoint?.(x, y);
  const position = !range ? documentWithCaret.caretPositionFromPoint?.(x, y) : null;
  const node = range?.startContainer ?? position?.offsetNode;
  const offset = range?.startOffset ?? position?.offset;
  if (!node || typeof offset !== "number" || !container.contains(node)) return null;

  const beforeSelection = document.createRange();
  beforeSelection.selectNodeContents(container);
  beforeSelection.setEnd(node, offset);
  return beforeSelection.toString().length;
}

function estimateTextareaSelectionRect(textarea: HTMLTextAreaElement, start: number) {
  const rect = textarea.getBoundingClientRect();
  const style = window.getComputedStyle(textarea);
  const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.7 || 20;
  const paddingTop = Number.parseFloat(style.paddingTop) || 0;
  const paddingLeft = Number.parseFloat(style.paddingLeft) || 0;
  const fontSize = Number.parseFloat(style.fontSize) || 13;
  const beforeSelection = textarea.value.slice(0, start);
  const lines = beforeSelection.split("\n");
  const lineIndex = Math.max(0, lines.length - 1);
  const column = lines[lines.length - 1]?.length ?? 0;
  const left = Math.min(rect.left + paddingLeft + column * fontSize * 0.55, rect.right - 16);
  const top = rect.top + paddingTop + lineIndex * lineHeight;
  return new DOMRect(left, top, 1, lineHeight);
}

function CommentableText({
  value,
  target,
  annotations,
  highlightedCommentId,
  placeholder,
  className = "",
  editableClassName = "",
  onChange,
  onPaste,
  onRemoveEmpty,
  onCreateTextComment,
  onAnnotationClick,
}: {
  value: string;
  target: CommentTarget;
  annotations: CommentItem[];
  highlightedCommentId: string | null;
  placeholder?: string;
  className?: string;
  editableClassName?: string;
  onChange: (value: string) => void;
  onPaste?: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
  onRemoveEmpty?: () => void;
  onCreateTextComment: (target: CommentTarget, rect: DOMRect) => void;
  onAnnotationClick: (commentId: string, rect?: DOMRect) => void;
}) {
  const staticRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [value, editing]);

  function openEditor(caretOffset?: number | null) {
    setEditing(true);
    window.setTimeout(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      const offset = Math.min(Math.max(caretOffset ?? value.length, 0), value.length);
      textarea.focus();
      textarea.setSelectionRange(offset, offset);
    }, 0);
  }

  function handleTextSelection() {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    if (end <= start) return;
    const selectedText = value.slice(start, end);
    if (!selectedText.trim()) return;

    onCreateTextComment(
      {
        ...target,
        selectedText: selectedText.trim(),
        rangeStart: start,
        rangeEnd: end,
      },
      estimateTextareaSelectionRect(textarea, start),
    );
  }

  function handleStaticMouseUp(event: ReactMouseEvent<HTMLDivElement>) {
    const staticElement = staticRef.current;
    if (!staticElement) return;
    const payload = getSelectionPayloadWithin(staticElement);
    if (payload) {
      onCreateTextComment(
        {
          ...target,
          selectedText: payload.selectedText.trim(),
          rangeStart: payload.start,
          rangeEnd: payload.end,
        },
        payload.rect,
      );
      return;
    }
    openEditor(getCaretOffsetFromPoint(staticElement, event.clientX, event.clientY));
  }

  function handleStaticKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openEditor();
  }

  function handleTextareaBlur() {
    window.setTimeout(() => {
      const active = document.activeElement;
      if (active && active.closest("[data-weekly-selection-action]")) return;
      setEditing(false);
    }, 120);
  }

  function handleTextareaKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (!onRemoveEmpty || value) return;
    if (event.key !== "Backspace" && event.key !== "Delete") return;
    event.preventDefault();
    onRemoveEmpty();
  }

  return (
    <div className={`relative ${className}`}>
      {!value && placeholder && (
        <span className="pointer-events-none absolute left-3 top-2 text-[12px] text-[#c7c7cc]">
          {placeholder}
        </span>
      )}
      <div
        aria-hidden
        className={`pointer-events-none absolute inset-0 whitespace-pre-wrap break-words ${editableClassName}`}
      >
        {value ? renderAnnotatedText(value, annotations, highlightedCommentId, onAnnotationClick) : ""}
      </div>
      {!editing && (
        <div
          ref={staticRef}
          role="textbox"
          tabIndex={0}
          data-commentable-text="true"
          data-comment-editor-id={target.itemId}
          onMouseUp={handleStaticMouseUp}
          onKeyDown={handleStaticKeyDown}
          className={`absolute inset-0 z-20 cursor-text whitespace-pre-wrap break-words ${editableClassName}`}
        >
          {value ? renderAnnotatedText(value, annotations, highlightedCommentId, onAnnotationClick) : ""}
        </div>
      )}
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        placeholder={placeholder}
        data-comment-editor-id={target.itemId}
        onFocus={() => setEditing(true)}
        onBlur={handleTextareaBlur}
        onPaste={onPaste}
        onKeyDown={handleTextareaKeyDown}
        onChange={(event) => onChange(event.currentTarget.value)}
        onMouseUp={() => window.setTimeout(handleTextSelection)}
        onKeyUp={() => window.setTimeout(handleTextSelection)}
        className={`relative z-10 block resize-none overflow-hidden bg-transparent text-transparent caret-[#3a3a3c] outline-none selection:bg-[#dce9ff] ${editableClassName}`}
        style={{ WebkitTextFillColor: "transparent" }}
      />
    </div>
  );
}

function EditableParagraph({
  block,
  item,
  annotations,
  highlightedCommentId,
  placeholder,
  targetKind = "paragraph",
  commentBlockId,
  targetType = "文本",
  targetLabel,
  onChange,
  onPaste,
  onRemoveEmpty,
  onCreateTextComment,
  onAnnotationClick,
}: {
  block: TextBlock;
  item: Extract<RichContentItem, { type: "paragraph" }>;
  annotations: CommentItem[];
  highlightedCommentId: string | null;
  placeholder?: string;
  targetKind?: CommentTargetKind;
  commentBlockId?: string;
  targetType?: CommentTarget["type"];
  targetLabel?: string;
  onChange: (value: string) => void;
  onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
  onRemoveEmpty?: () => void;
  onCreateTextComment: (target: CommentTarget, rect: DOMRect) => void;
  onAnnotationClick: (commentId: string, rect?: DOMRect) => void;
}) {
  return (
    <CommentableText
      value={item.text}
      target={{
        id: `${block.id}_${item.id}_selection`,
        label: targetLabel || `${block.title} / 选中文本`,
        type: targetType,
        targetKind,
        blockId: commentBlockId || block.id,
        itemId: item.id,
      }}
      annotations={annotations}
      highlightedCommentId={highlightedCommentId}
      placeholder={placeholder}
      onPaste={onPaste}
      onChange={onChange}
      onRemoveEmpty={onRemoveEmpty}
      onCreateTextComment={onCreateTextComment}
      onAnnotationClick={onAnnotationClick}
      className=""
      editableClassName="min-h-[28px] w-full whitespace-pre-wrap break-words bg-transparent px-0 py-1 text-[13px] text-[#3a3a3c] leading-[1.7] outline-none"
    />
  );
}

function ResizableRichImage({
  item,
  index,
  total,
  onMove,
  onResize,
  onDelete,
  onInsertBlank,
}: {
  item: Extract<RichContentItem, { type: "image" }>;
  index: number;
  total: number;
  onMove: (fromIndex: number, toIndex: number) => void;
  onResize: (size: { width?: number; height?: number }) => void;
  onDelete: () => void;
  onInsertBlank: (position: "before" | "after") => void;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [deleteMenu, setDeleteMenu] = useState<{ x: number; y: number } | null>(null);
  const [authorizedImageSrc, setAuthorizedImageSrc] = useState("");

  useEffect(() => {
    if (!item.attachmentId) {
      setAuthorizedImageSrc("");
      return;
    }
    let disposed = false;
    let objectUrl = "";
    void fetchReportImageObjectUrl({ attachmentId: item.attachmentId })
      .then((url) => {
        objectUrl = url;
        if (!disposed) setAuthorizedImageSrc(url);
      })
      .catch(() => {
        if (!disposed) setAuthorizedImageSrc("");
      });
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [item.attachmentId]);

  useEffect(() => {
    if (!deleteMenu) return;
    const close = () => setDeleteMenu(null);
    document.addEventListener("pointerdown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
    };
  }, [deleteMenu]);

  function startResize(edge: "top-right" | "bottom-right", event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // Synthetic pointer events used in UI tests do not always own a browser pointer id.
    }
    const frame = frameRef.current;
    if (!frame) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const frameRect = frame.getBoundingClientRect();
    const startWidth = frameRect.width;
    const startHeight = imageRef.current?.getBoundingClientRect().height || item.height || 220;
    const maxWidth = frame.parentElement?.clientWidth || 760;
    const maxHeight = Math.max(180, window.innerHeight - 180);
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = edge === "top-right" ? "nesw-resize" : "nwse-resize";
    document.body.style.userSelect = "none";
    const handlePointerMove = (pointerEvent: PointerEvent) => {
      onResize({
        width: clampImageWidth(startWidth + pointerEvent.clientX - startX, maxWidth),
        height: clampImageHeight(
          edge === "top-right"
            ? startHeight + startY - pointerEvent.clientY
            : startHeight + pointerEvent.clientY - startY,
          maxHeight,
        ),
      });
    };
    const handlePointerUp = () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", handlePointerUp);
      document.removeEventListener("pointercancel", handlePointerUp);
    };
    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", handlePointerUp);
    document.addEventListener("pointercancel", handlePointerUp);
  }

  function openDeleteMenu(event: ReactMouseEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    setDeleteMenu({
      x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 84)),
      y: Math.max(8, event.clientY - rect.top),
    });
  }

  return (
    <div className="group/image-gap relative py-2">
      <button type="button" aria-label="在图片上方插入空白行" onClick={() => onInsertBlank("before")} className="absolute inset-x-0 top-0 z-20 h-2 cursor-text rounded-full bg-transparent transition-colors hover:bg-[#dce9ff] focus-visible:bg-[#dce9ff]" />
      <div
        ref={frameRef}
        onContextMenu={openDeleteMenu}
        className="group/image relative max-w-full rounded-xl border border-[#e5e5ea] bg-white p-1"
        style={{ width: item.width ? `${item.width}px` : "100%" }}
        data-rich-image-id={item.id}
      >
      <div className="absolute right-2 top-2 z-40 flex items-center gap-1 opacity-0 transition-opacity group-hover/image:opacity-100 group-focus-within/image:opacity-100">
        <button
          type="button"
          onClick={() => onMove(index, index - 1)}
          className="h-7 w-7 rounded-md border border-[#e5e5ea] bg-white/95 text-[#636366] shadow-sm shadow-black/10 flex items-center justify-center disabled:opacity-30"
          disabled={index === 0}
          aria-label="上移图片"
        >
          <ArrowUp className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() => onMove(index, index + 1)}
          className="h-7 w-7 rounded-md border border-[#e5e5ea] bg-white/95 text-[#636366] shadow-sm shadow-black/10 flex items-center justify-center disabled:opacity-30"
          disabled={index === total - 1}
          aria-label="下移图片"
        >
          <ArrowDown className="w-3.5 h-3.5" />
        </button>
      </div>
      <img
        ref={imageRef}
        src={authorizedImageSrc || item.src}
        alt={item.name}
        className="block w-full select-none rounded-[10px] bg-white object-contain"
        style={{ height: item.height ? `${item.height}px` : "auto", maxHeight: item.height ? undefined : "260px" }}
        draggable={false}
      />
      <button type="button" onPointerDown={(event) => startResize("top-right", event)} className="absolute right-0 top-0 z-30 h-4 w-4 cursor-nesw-resize rounded-bl-lg rounded-tr-xl border-b border-l border-transparent bg-white/70 opacity-0 transition-opacity hover:border-[#8eb8ee] hover:bg-[#dce9ff] group-hover/image:opacity-100 focus-visible:opacity-100" aria-label="拖动右上角同时调整图片宽高" title="拖动右上角同时调整宽高" />
      <button type="button" onPointerDown={(event) => startResize("bottom-right", event)} className="absolute bottom-0 right-0 z-30 h-4 w-4 cursor-nwse-resize rounded-br-xl rounded-tl-lg border-l border-t border-transparent bg-white/70 opacity-0 transition-opacity hover:border-[#8eb8ee] hover:bg-[#dce9ff] group-hover/image:opacity-100 focus-visible:opacity-100" aria-label="拖动右下角同时调整图片宽高" title="拖动右下角同时调整宽高" />
      {deleteMenu && (
        <div
          className="absolute z-30 w-20 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg shadow-black/10"
          style={{ left: deleteMenu.x, top: deleteMenu.y }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => {
              setDeleteMenu(null);
              onDelete();
            }}
            className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#d92d20] hover:bg-[#fff1f0]"
          >
            删除
          </button>
        </div>
      )}
      </div>
      <button type="button" aria-label="在图片下方插入空白行" onClick={() => onInsertBlank("after")} className="absolute inset-x-0 bottom-0 z-20 h-2 cursor-text rounded-full bg-transparent transition-colors hover:bg-[#dce9ff] focus-visible:bg-[#dce9ff]" />
    </div>
  );
}

function TextSection({
  block,
  selectedTargetId,
  onSelectTarget,
  onOpenComment,
  onOpenAnalysis,
  onChange,
  comments,
  highlightedCommentId,
  onCreateTextComment,
  onAnnotationClick,
  showHeader = true,
  articleClassName = "rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4",
  editorClassName = "bg-white rounded-lg border border-[#f0f0f2] px-3 py-2 focus-within:border-[#c7c7cc]",
  targetKind = "paragraph",
  commentBlockId,
  placeholder = "输入正文，或直接粘贴图片...",
  imageUploadContext,
}: {
  block: TextBlock;
  selectedTargetId?: string;
  onSelectTarget: (target: CommentTarget) => void;
  onOpenComment: (target: CommentTarget) => void;
  onOpenAnalysis: (target: CommentTarget) => void;
  onChange: (items: RichContentItem[]) => void;
  comments: CommentItem[];
  highlightedCommentId: string | null;
  onCreateTextComment: (target: CommentTarget, rect?: DOMRect) => void;
  onAnnotationClick: (commentId: string, rect?: DOMRect) => void;
  showHeader?: boolean;
  articleClassName?: string;
  editorClassName?: string;
  targetKind?: CommentTargetKind;
  commentBlockId?: string;
  placeholder?: string;
  imageUploadContext: ImageUploadContext;
}) {
  const items = block.contentItems?.length ? block.contentItems : createTextItems(block.id, block.content);
  const resolvedCommentBlockId = commentBlockId || block.id;
  const textTarget: CommentTarget = {
    id: `${block.id}_text`,
    label: `${block.title} / 正文`,
    type: "文本",
    targetKind,
    blockId: resolvedCommentBlockId,
  };

  function commit(nextItems: RichContentItem[]) {
    onChange(nextItems.length ? nextItems : [{ id: makeId(`${block.id}_line`), type: "paragraph", text: "" }]);
  }

  function updateParagraph(index: number, value: string) {
    const nextItems = [...items];
    nextItems[index] = { ...nextItems[index], type: "paragraph", text: value } as RichContentItem;
    commit(nextItems);
  }

  async function pasteImagesAtCursor(
    event: ClipboardEvent<HTMLTextAreaElement>,
    index: number,
    item: Extract<RichContentItem, { type: "paragraph" }>,
  ) {
    const files = Array.from(event.clipboardData.items)
      .filter((item) => item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file));

    if (!files.length) return;
    event.preventDefault();
    const textarea = event.currentTarget;
    const selectionStart = textarea.selectionStart ?? item.text.length;
    const selectionEnd = textarea.selectionEnd ?? selectionStart;
    const beforeText = item.text.slice(0, selectionStart);
    const afterText = item.text.slice(selectionEnd);
    const afterParagraphId = makeId(`${block.id}_line`);
    const editorWidth = textarea.closest<HTMLElement>("[data-rich-text-editor]")?.clientWidth || textarea.clientWidth || 560;
    const maxImageWidth = Math.max(220, Math.min(editorWidth - 12, 680));
    const imageItems: RichContentItem[] = await Promise.all(
      files.map((file) => createRichImageItem(`${block.id}_image`, file, maxImageWidth, imageUploadContext)),
    );
    const replacementItems: RichContentItem[] = [
      ...(beforeText.length ? [{ ...item, text: beforeText }] : []),
      ...imageItems,
      { id: afterParagraphId, type: "paragraph" as const, text: afterText },
    ];
    const nextItems = [...items];
    nextItems.splice(index, 1, ...replacementItems);
    commit(nextItems);
    window.setTimeout(() => {
      const nextEditor = document.querySelector(`textarea[data-comment-editor-id="${afterParagraphId}"]`) as HTMLTextAreaElement | null;
      if (!nextEditor) return;
      const offset = 0;
      nextEditor.focus();
      nextEditor.setSelectionRange(offset, offset);
    }, 0);
  }

  function moveItem(fromIndex: number, toIndex: number) {
    if (toIndex < 0 || toIndex >= items.length || fromIndex === toIndex) return;
    const nextItems = [...items];
    const [item] = nextItems.splice(fromIndex, 1);
    nextItems.splice(toIndex, 0, item);
    commit(nextItems);
  }

  function resizeImage(index: number, size: { width?: number; height?: number }) {
    const nextItems = [...items];
    const item = nextItems[index];
    if (!item || item.type !== "image") return;
    nextItems[index] = { ...item, ...size };
    commit(nextItems);
  }

  function deleteItem(index: number) {
    const nextItems = items.filter((_, itemIndex) => itemIndex !== index);
    commit(nextItems.length ? nextItems : [{ id: makeId(`${block.id}_line`), type: "paragraph", text: "" }]);
  }

  function removeParagraph(index: number) {
    const nextItems = items.filter((_, itemIndex) => itemIndex !== index);
    commit(nextItems);
  }

  function insertBlankAroundImage(index: number, position: "before" | "after") {
    const insertionIndex = position === "before" ? index : index + 1;
    const existing = items[insertionIndex];
    const paragraphId = existing?.type === "paragraph" && !existing.text.trim()
      ? existing.id
      : makeId(`${block.id}_line`);
    if (!(existing?.type === "paragraph" && !existing.text.trim())) {
      const nextItems = [...items];
      nextItems.splice(insertionIndex, 0, { id: paragraphId, type: "paragraph", text: "" });
      commit(nextItems);
    }
    window.setTimeout(() => {
      const editor = document.querySelector(`textarea[data-comment-editor-id="${paragraphId}"]`) as HTMLTextAreaElement | null;
      editor?.focus();
      editor?.setSelectionRange(0, 0);
    }, 0);
  }

  return (
    <article className={articleClassName}>
      {showHeader && (
        <div className="flex items-center gap-2 mb-3">
          <MessageSquareText className="w-4 h-4 text-[#8a8a8e]" />
          <h5 className="text-[13px] text-[#1d1d1f]">{block.title}</h5>
        </div>
      )}
      <SelectableRegion
        target={textTarget}
        selectedTargetId={selectedTargetId}
        onSelect={onSelectTarget}
        onOpenComment={onOpenComment}
        onOpenAnalysis={onOpenAnalysis}
      >
        <div className={editorClassName} data-rich-text-editor="true">
          {items.map((item, index) => (
            <div
              key={item.id}
              className="group relative rounded-md"
            >
              {item.type === "paragraph" ? (
                <EditableParagraph
                  block={block}
                  item={item}
                  annotations={comments.filter((comment) => comment.itemId === item.id)}
                  highlightedCommentId={highlightedCommentId}
                  placeholder={index === 0 ? placeholder : ""}
                  targetKind={targetKind}
                  commentBlockId={resolvedCommentBlockId}
                  targetType="文本"
                  targetLabel={`${block.title} / 选中文本`}
                  onPaste={(event) => pasteImagesAtCursor(event, index, item)}
                  onChange={(value) => updateParagraph(index, value)}
                  onRemoveEmpty={() => removeParagraph(index)}
                  onCreateTextComment={onCreateTextComment}
                  onAnnotationClick={onAnnotationClick}
                />
              ) : (
                <ResizableRichImage
                  item={item}
                  index={index}
                  total={items.length}
                  onMove={moveItem}
                  onResize={(size) => resizeImage(index, size)}
                  onDelete={() => deleteItem(index)}
                  onInsertBlank={(position) => insertBlankAroundImage(index, position)}
                />
              )}
            </div>
          ))}
        </div>
      </SelectableRegion>
    </article>
  );
}
