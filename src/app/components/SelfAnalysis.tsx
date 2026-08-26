import { useEffect, useRef, useState, type ClipboardEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { usePlatformContext } from "../platform/PlatformContext";
import { createClientUuid } from "../utils/clientUuid";
import type { MetricDictionaryItem } from "../data/metricDictionary";
import { cancelAsyncAnalysisRun, deleteAnalysisHistoryTask, fetchAnalysisTask, fetchAnalysisHistory, fetchAnalysisHistoryDetail, waitForSelfAnalysis, type AnalysisProgressStep, type AnalysisTraceSpan, type BackendAnalysisPlan, type BackendAnalysisResponse } from "../services/analysisApi";
import { ExecutionHistoryDrawer } from "./self-analysis/ExecutionHistoryDrawer";
import { VoiceInputPopover } from "./self-analysis/VoiceInputPopover";
import { AnalysisProgressPanel } from "./self-analysis/AnalysisProgressPanel";
import { completedProgressSteps, configuredModelForModule, modelApplicationModuleForTrigger, modelApplicationSelection, modelInvocationIssue, modelsForModule, speechApplicationModuleForTarget } from "./self-analysis/analysisRuntime";
import { createRealtimeSpeakerGateState, extractRealtimeVoiceAnalysisCommand, gateRealtimeSpeakerFrame, isRealtimeVoiceTrigger, type RealtimeSpeakerGateState, type RealtimeVoiceTrigger } from "./self-analysis/realtimeVoice";
import { fetchMetricDictionary } from "../services/metricDictionaryApi";
import {
  deleteSavedAnalysisResult,
  fetchSavedAnalysisResults,
  saveAnalysisResultAsExperience,
  saveAnalysisResultToWeeklyReport,
  saveSavedAnalysisResult,
} from "../services/reportApi";
import {
  fetchDataAssets,
  fetchTopicData,
  saveDataAssetItem,
  type PageDataAsset,
  type RawTableAsset,
  type TopicDataReference,
  type TopicTableAsset,
} from "../services/dataAssetApi";
import { intelligentAnalysisMenuSkills as selectAvailableAnalysisSkills } from "../services/analysisSkillCatalog";
import { resolveMetricPreset, type MetricPreset } from "./self-analysis/metricPreset";
import { apiErrorMessage, getApiBaseUrl } from "../services/apiClient";
import { isDemoFallbackEnabled } from "../services/apiContext";
import { modelApplicationModuleLabel } from "../data/modelApplicationModules";
import { runApplicationAction } from "../services/applicationApi";
import { fetchAnalysisRuntimeConfig, fetchSystemConfig, type FunAsrRuntimeIntegration, type ModelIntegration } from "../services/systemConfigApi";
import { findConfiguredTextModel, persistTextModelSelection, readPersistedTextModelSelection, textModelSelectionEvent } from "../services/modelSelectionStore";
import { ArrowUp, AudioLines, Sparkles, Clock, Star, ArrowUpRight, Table2, Download, BookmarkPlus, History, Lightbulb, Code2, Mic, Plus, Upload, X, ChevronsDown, ChevronsUp, Eye, Pencil, Trash2, Check, RotateCcw } from "lucide-react";
import { AnalysisVisualCard, RawDataTable, type VisualizationCardConfig } from "./self-analysis/ResultViews";
import { AnalysisModelSelector } from "./self-analysis/AnalysisModelSelector";
import { AnalysisTopicShortcuts } from "./self-analysis/AnalysisTopicShortcuts";
import { AnalysisScriptEditor } from "./self-analysis/AnalysisScriptEditor";
import { defaultVisualizationCards, documentSummaryCards, type VisualCardInstance } from "./self-analysis/visualCards";
import { ingestAnalysisUploads, uploadedAnalysisGate, UPLOADED_MEDIA_UNSUPPORTED_MESSAGE } from "./self-analysis/uploadedSource";
import { completedRoundFromAnalysis } from "./self-analysis/topicTablePrecipitation";
import { useTopicTablePrecipitation } from "./self-analysis/useTopicTablePrecipitation";
import { ResizableVisualizationGrid } from "./self-analysis/ResizableVisualizationGrid";
import { visualDuplicateLayout } from "./self-analysis/visualGridLayout";
import { StickyNoteButton, StickyNotePanel } from "./notes/StickyNote";
import { useStickyNote } from "./notes/useStickyNote";
import { TrustedArtifactPanel } from "./analysis-workspace/TrustedArtifactPanel";
import { syncSelfAnalysisWorkspaceContext } from "./self-analysis/workspaceContext";
import { resolveVisualAnalysisTables, revealVisualComment, revealVisualFollowUp } from "./self-analysis/visualFollowUp";
import { AnalysisSkillMenu } from "./self-analysis/AnalysisSkillMenu";
import { DataPageSelector, useClientPagination } from "./ui/DataPageSelector";
import { askConfirm } from "./ui/ConfirmDialog";
import {
  type VisualizationType,
  type ResultVisualKey,
  type ResultMode,
  type SaveTarget,
  type SelfAnalysisSection,
  type ScriptTab,
  type AnalysisSkillOption,
  type QuerySkillReference,
  type AnalysisConversationTurn,
  type AnalysisConversationState,
  type FunAsrInputTarget,
  type AnalysisRunTrigger,
  type AnalysisTopicShortcut,
  type TopicShortcutMenuState,
  type KnowledgeFileAttachment,
  detectAttachmentInstitutions,
  type AnalysisDataTableSelection,
  singleAnalysisDataTableSelection,
  rematchAnalysisDataTableSelection,
  type AnalysisRow,
  type AudioContextConstructorLike,
  type FunAsrContextMessage,
  type FunAsrProxyEvent,
  type SavedAnalysisResult,
  realtimeVoiceSilenceAnalysisMs,
  savedAnalysisStorageKey,
  analysisConversationSessionStoragePrefix,
  analysisConversationStoragePrefix,
  analysisTopicShortcutStoragePrefix,
  funAsrSampleRate,
  scopedStorageKey,
  createConversationSessionId,
  ensureAnalysisConversationSessionId,
  conversationStorageKey,
  topicShortcutStorageKey,
  loadConversationState,
  saveConversationState,
  isConversationTurn,
  loadAnalysisTopicShortcuts,
  saveAnalysisTopicShortcuts,
  isAnalysisTopicShortcut,
  normalizeStoredAnalysisTopicShortcut,
  getSelfAnalysisSection,
  formatTopicFields,
  pageDataToSelection,
  rawTableToSelection,
  topicTableToSelection,
  backendTableToSelection,
  formatSelectedDataTables,
  isAutoReferenceSkill,
  skillReferenceAliases,
  buildQuerySkillReferences,
  uniqueSkills,
  sameStringSet,
  getAudioContextConstructor,
  normalizeVoiceSegment,
  appendRealtimeVoiceText,
  buildFunAsrRealtimeUrl,
  buildFunAsrContext,
  downsampleToPcm16,
  floatToPcm16,
  funAsrErrorMessage,
  formatConversationContext,
  makeConversationTurn,
  extractPlanLine,
  cleanAnalysisTopicCandidate,
  buildAnalysisTopicTitle,
  buildAnalysisTopicShortcut,
  suggestedQuestions,
  analysisSkillOptions,
  fallbackAnalysisModels,
  firstSelectableAnalysisModel,
  hasSelectableAnalysisModel,
  autoReferenceSkillCategories,
  inferVisualTypes,
  visualizationPreferencesFromQuestion,
  visualizationLabel,
  isSelfAnalysisNoticeFailure,
  createAnalysisPlan,
  backendDisplayValue,
  appendMetricReferences,
  formatBackendPlan,
  mapBackendRows,
  visualTypeFromBackend,
  visualTypesFromBackend,
  sqlScriptFromBackend,
  pythonScriptFromBackend,
  formatMetricScenarios,
  loadSavedAnalysisResults,
  downloadCsv,
  csvCell,
  detectedAnalysisInstitution,
} from "./self-analysis/domain";
import { DataTablePickerModal } from "./self-analysis/DataTablePickerModal";
import {
  defaultMyReportsTab,
  featuredReportKey,
  loadFeaturedReports,
  pruneFeaturedReports,
  useFeaturedReports,
  type ReportKindTab,
} from "./self-analysis/featuredReports";
import { useVisualReportCollection, VisualReportLibrary, VisualReportRow } from "./visual-report/VisualReportLibrary";
import type { VisualReport } from "../services/visualReportApi";

import { clearPendingAnalysisRun, isAnalysisNavigationAbort, loadPendingAnalysisRun, savePendingAnalysisRun } from "./self-analysis/pendingAnalysisRun";
import { clearSelfAnalysisWorkbenchPersistence, useSelfAnalysisWorkbenchPersistence } from "./self-analysis/useSelfAnalysisWorkbenchPersistence";

type AnalysisSubmissionPhase = "idle" | "submitting" | "queued" | "running";

export function SelfAnalysis() {
  const location = useLocation();
  const navigate = useNavigate();
  const { selectedInstitution, tenantId, userId } = usePlatformContext();
  const activeView = getSelfAnalysisSection(location.pathname);
  const funAsrSocketRef = useRef<WebSocket | null>(null);
  const funAsrInputTargetRef = useRef<FunAsrInputTarget>("query");
  const realtimeVoiceStreamRef = useRef<MediaStream | null>(null);
  const realtimeVoiceAudioContextRef = useRef<AudioContext | null>(null);
  const realtimeVoiceSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const realtimeVoiceProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const realtimeVoiceActiveRef = useRef(false);
  const realtimeVoiceBaseRef = useRef("");
  const realtimeVoiceFinalRef = useRef("");
  const realtimeVoiceDraftRef = useRef("");
  const realtimeVoiceRenderedRef = useRef("");
  const realtimeVoiceSilenceTimerRef = useRef<number | null>(null);
  const realtimeVoiceReconnectTimerRef = useRef<number | null>(null);
  const realtimeVoiceReconnectAttemptsRef = useRef(0);
  const realtimeVoiceExpectedCloseRef = useRef<"session_end" | "">("");
  const realtimeVoiceLastAutoAnalysisTextRef = useRef("");
  const realtimeVoiceAutoAnalyzeRef = useRef<(text: string, trigger: RealtimeVoiceTrigger) => void>(() => undefined);
  const realtimeVoiceDrainQueueRef = useRef<() => void>(() => undefined);
  const realtimeVoiceQueueRef = useRef<Array<{ text: string; trigger: RealtimeVoiceTrigger }>>([]);
  const metricPresetFlashTimerRef = useRef<number | null>(null);
  const realtimeVoiceSpeakerGateRef = useRef<RealtimeSpeakerGateState>(createRealtimeSpeakerGateState());
  const realtimeVoiceIgnoredSpeakerSegmentsRef = useRef(0);
  const queryLatestRef = useRef("");
  const isAnalyzingRef = useRef(false);
  const analysisWaitAbortRef = useRef<AbortController | null>(null);
  const activeAnalysisRunIdRef = useRef("");
  const analysisGenerationRef = useRef(0);
  const partialAnalysisTaskIdRef = useRef("");
  const partialAnalysisResponseRef = useRef<BackendAnalysisResponse | null>(null);
  const funAsrIntegrationByModuleRef = useRef<Record<string, FunAsrRuntimeIntegration | null>>({});
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const queryInputRef = useRef<HTMLTextAreaElement | null>(null);
  const analysisMenuRef = useRef<HTMLDivElement | null>(null);
  const [query, setQuery] = useState("");
  const [analysisMenuOpen, setAnalysisMenuOpen] = useState(false);
  const [availableModels, setAvailableModels] = useState<ModelIntegration[]>([]);
  const [selectedModel, setSelectedModel] = useState<ModelIntegration | null>(null);
  const [, setFunAsrIntegration] = useState<FunAsrRuntimeIntegration | null>(null);
  const [selectedModeSkill, setSelectedModeSkill] = useState<AnalysisSkillOption | null>(null);
  const [selectedSceneSkill, setSelectedSceneSkill] = useState<AnalysisSkillOption | null>(null);
  const [selectedTopicSkill, setSelectedTopicSkill] = useState<AnalysisSkillOption | null>(null);
  const [availableAnalysisSkills, setAvailableAnalysisSkills] = useState<AnalysisSkillOption[]>(() =>
    analysisSkillOptions.filter((skill) => skill.category === "模式"),
  );
  const [dismissedAutoSkillIds, setDismissedAutoSkillIds] = useState<Set<string>>(() => new Set());
  const [knowledgeFiles, setKnowledgeFiles] = useState<KnowledgeFileAttachment[]>([]);
  const [showResult, setShowResult] = useState(false);
  const [analysisPlan, setAnalysisPlan] = useState("");
  const [analysisRows, setAnalysisRows] = useState<AnalysisRow[]>([]);
  const [analysisSummary, setAnalysisSummary] = useState("");
  const [analysisScenarios, setAnalysisScenarios] = useState("本次第一阶段规划尚未生成指标表现情景。");
  const [analysisError, setAnalysisError] = useState("");
  const [analysisProgressSteps, setAnalysisProgressSteps] = useState<AnalysisProgressStep[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisSubmissionPhase, setAnalysisSubmissionPhase] = useState<AnalysisSubmissionPhase>("idle");
  const [analysisTaskId, setAnalysisTaskId] = useState("");
  const analysisSticky = useStickyNote("self_analysis", `self_analysis:${analysisTaskId || "current"}`);
  const [resultMode, setResultMode] = useState<ResultMode>("visual");
  const [saveMessage, setSaveMessage] = useState("");
  const [visualTypes, setVisualTypes] = useState<Record<ResultVisualKey, VisualizationType>>({
    primary: "column",
    secondary: "table",
  });
  const [visualCards, setVisualCards] = useState<VisualCardInstance[]>(() => defaultVisualizationCards({ primary: "column", secondary: "table" }));
  const visualCardsTaskRef = useRef("");
  const [reportVisualTypeOverrides, setReportVisualTypeOverrides] = useState<Record<string, Record<ResultVisualKey, VisualizationType>>>({});
  const [scriptEditorOpen, setScriptEditorOpen] = useState(false);
  const [activeScriptTab, setActiveScriptTab] = useState<ScriptTab>("sql");
  const [scriptPlanName, setScriptPlanName] = useState("经营分析思路");
  const [sqlScript, setSqlScript] = useState("-- 尚未执行分析，暂无已执行 SQL。");
  const [pythonScript, setPythonScript] = useState("# 尚未执行分析，暂无已执行 Python 脚本。");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [voiceListening, setVoiceListening] = useState(false);
  const [voiceTranscript, setVoiceTranscript] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const [realtimeVoiceListening, setRealtimeVoiceListening] = useState(false);
  const [realtimeVoiceError, setRealtimeVoiceError] = useState("");
  const [realtimeVoiceQueueLength, setRealtimeVoiceQueueLength] = useState(0);
  const [realtimeVoiceIgnoredSpeakerSegments, setRealtimeVoiceIgnoredSpeakerSegments] = useState(0);
  const [voiceprintStatus, setVoiceprintStatus] = useState<"idle" | "calibrating" | "locked">("idle");
  const [analysisInputCollapsed, setAnalysisInputCollapsed] = useState(false);
  const [activeMetricPreset, setActiveMetricPreset] = useState<MetricPreset | null>(null);
  const [metricPresetFlashing, setMetricPresetFlashing] = useState(false);
  const [availableMetrics, setAvailableMetrics] = useState<MetricDictionaryItem[]>([]);
  const [availableRawTables, setAvailableRawTables] = useState<RawTableAsset[]>([]);
  const [availableTopicTables, setAvailableTopicTables] = useState<TopicTableAsset[]>([]);
  const [availablePageDataTables, setAvailablePageDataTables] = useState<PageDataAsset[]>([]);
  const analysisCatalogRef = useRef<AnalysisDataTableSelection[]>([]);
  const [selectedDataTables, setSelectedDataTablesState] = useState<AnalysisDataTableSelection[]>([]);
  const setSelectedDataTables = (
    next: AnalysisDataTableSelection[] | ((current: AnalysisDataTableSelection[]) => AnalysisDataTableSelection[]),
  ) => setSelectedDataTablesState((current) => singleAnalysisDataTableSelection(
    typeof next === "function" ? next(current) : next,
  ));
  const [dataTablePickerOpen, setDataTablePickerOpen] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<TopicTableAsset | null>(null);
  const [conversationSessionId, setConversationSessionId] = useState("");
  const [conversationTurns, setConversationTurns] = useState<AnalysisConversationTurn[]>([]);
  const [analysisTopicShortcuts, setAnalysisTopicShortcuts] = useState<AnalysisTopicShortcut[]>([]);
  const [savedAnalysisResults, setSavedAnalysisResults] = useState<SavedAnalysisResult[]>([]);
  const [reportKindTab, setReportKindTab] = useState<ReportKindTab>(() => defaultMyReportsTab(loadFeaturedReports(tenantId, userId).length > 0));
  const reportSourceFilter = "all";
  const [savedAnalysisLoadError, setSavedAnalysisLoadError] = useState("");
  const [savedAnalysisLoaded, setSavedAnalysisLoaded] = useState(false);
  const featuredReports = useFeaturedReports(tenantId, userId);
  const visualMine = useVisualReportCollection("mine", activeView === "reports");
  const userPickedReportTabRef = useRef(false);
  const defaultReportTabAppliedRef = useRef(false);
  const [expandedFeaturedVisualId, setExpandedFeaturedVisualId] = useState("");
  const [expandedReportId, setExpandedReportId] = useState("");
  const [editingReportId, setEditingReportId] = useState<string | null>(null);
  const [reportTitleDraft, setReportTitleDraft] = useState("");
  const [reportActionError, setReportActionError] = useState("");
  const [reportActionNotice, setReportActionNotice] = useState("");
  const [reportActionLoadingId, setReportActionLoadingId] = useState("");
  const [reportLoadingId, setReportLoadingId] = useState("");
  useEffect(() => {
    syncSelfAnalysisWorkspaceContext({ activeView, expandedReportId, reportSourceFilter, savedAnalysisResults, selectedDataTables, selectedInstitution, analysisTaskId });
  }, [activeView, expandedReportId, reportSourceFilter, savedAnalysisResults, selectedDataTables, selectedInstitution, analysisTaskId]);
  const [analysisTopicsLoaded, setAnalysisTopicsLoaded] = useState(false);
  const [analysisTopicsExpanded, setAnalysisTopicsExpanded] = useState(false);
  const [topicShortcutMenu, setTopicShortcutMenu] = useState<TopicShortcutMenuState>(null);
  const [editingTopicId, setEditingTopicId] = useState<string | null>(null);
  const [executionHistoryOpen, setExecutionHistoryOpen] = useState(false);
  const [executionHistoryLoading, setExecutionHistoryLoading] = useState(false);
  const [executionHistoryTasks, setExecutionHistoryTasks] = useState<BackendAnalysisResponse[]>([]);
  const [expandedExecutionTaskId, setExpandedExecutionTaskId] = useState("");
  const [executionTraceSpans, setExecutionTraceSpans] = useState<AnalysisTraceSpan[]>([]);
  useSelfAnalysisWorkbenchPersistence({ tenantId, userId, enabled: activeView === "query", state: { selectedDataTables, selectedTopic, showResult, analysisPlan, analysisRows, analysisSummary, analysisScenarios, analysisTaskId, resultMode, visualTypes, scriptPlanName, sqlScript, pythonScript, analysisInputCollapsed }, restore: (snapshot) => { setSelectedDataTables(rematchAnalysisDataTableSelection(snapshot.selectedDataTables, analysisCatalogRef.current)); setSelectedTopic(snapshot.selectedTopic); setShowResult(snapshot.showResult); setAnalysisPlan(snapshot.analysisPlan); setAnalysisRows(snapshot.analysisRows); setAnalysisSummary(snapshot.analysisSummary); setAnalysisScenarios(snapshot.analysisScenarios); setAnalysisTaskId(snapshot.analysisTaskId); setResultMode(snapshot.resultMode); setVisualTypes(snapshot.visualTypes); setScriptPlanName(snapshot.scriptPlanName); setSqlScript(snapshot.sqlScript); setPythonScript(snapshot.pythonScript); setAnalysisInputCollapsed(snapshot.analysisInputCollapsed); } });
  useEffect(() => {
    if (!analysisTaskId || visualCardsTaskRef.current === analysisTaskId) return;
    visualCardsTaskRef.current = analysisTaskId;
    setVisualCards(defaultVisualizationCards(visualTypes));
  }, [analysisTaskId, visualTypes.primary, visualTypes.secondary]);
  const selectedManualSkills = [selectedModeSkill, selectedSceneSkill, selectedTopicSkill].filter(
    (skill): skill is AnalysisSkillOption => Boolean(skill),
  );
  const availableAnalysisTables = [
    ...availableRawTables.map(rawTableToSelection),
    ...availableTopicTables.map(topicTableToSelection),
    ...availablePageDataTables.map(pageDataToSelection),
  ];
  const topicPrecipitation = useTopicTablePrecipitation();
  const rememberTopicRound = (
    question: string,
    response: BackendAnalysisResponse,
    tables: AnalysisDataTableSelection[],
    rows: AnalysisRow[],
    resolvedViaMetricPreset = false,
  ) => {
    topicPrecipitation.rememberCompletedRound(completedRoundFromAnalysis({
      tenantId,
      userId,
      question,
      response,
      tables,
      rows,
      knowledgeFiles,
      resolvedViaMetricPreset,
      fallbackScript: sqlScriptFromBackend(response),
    }));
  };
  const uploadedGate = uploadedAnalysisGate(knowledgeFiles);
  const metricPresetNotice = uploadedGate.hasDataSource || uploadedGate.hasTextDocument
    ? ""
    : activeMetricPreset?.message
    ? activeMetricPreset.status === "none"
      ? "目前没有与问题匹配的已登记指标，请明确说明需要分析的具体指标，或添加需要分析的数据表。"
      : activeMetricPreset.status === "suggestions"
        ? "未找到可执行的数据表映射，可查看相关指标："
      : activeMetricPreset.message
    : "";
  const primaryAnalysisSkill = selectedSceneSkill || selectedTopicSkill || selectedModeSkill;
  const querySkillReferences = buildQuerySkillReferences(query, dismissedAutoSkillIds, availableAnalysisSkills);
  const visibleAnalysisTopicShortcuts = analysisTopicShortcuts.filter((topic) => !topic.hidden);
  const boundChartTables = resolveVisualAnalysisTables(
    selectedDataTables,
    selectedTopic ? [topicTableToSelection(selectedTopic)] : [],
  );
  const recentSavedQueries = savedAnalysisResults
    .filter(
      (item, index, items) =>
        Boolean(item.query?.trim()) && items.findIndex((candidate) => candidate.query === item.query) === index,
    )
    .slice(0, 6);
  useEffect(() => {
    queryLatestRef.current = query;
  }, [query]);
  useEffect(() => {
    isAnalyzingRef.current = isAnalyzing;
  }, [isAnalyzing]);
  const clearRealtimeVoiceSilenceTimer = () => {
    if (realtimeVoiceSilenceTimerRef.current === null) return;
    window.clearTimeout(realtimeVoiceSilenceTimerRef.current);
    realtimeVoiceSilenceTimerRef.current = null;
  };
  const flashMetricPresetNotice = () => {
    if (metricPresetFlashTimerRef.current !== null) {
      window.clearTimeout(metricPresetFlashTimerRef.current);
    }
    setMetricPresetFlashing(false);
    metricPresetFlashTimerRef.current = window.setTimeout(() => {
      setMetricPresetFlashing(true);
      metricPresetFlashTimerRef.current = window.setTimeout(() => {
        setMetricPresetFlashing(false);
        metricPresetFlashTimerRef.current = null;
      }, 700);
    }, 20);
  };
  useEffect(() => () => {
    if (metricPresetFlashTimerRef.current !== null) {
      window.clearTimeout(metricPresetFlashTimerRef.current);
    }
  }, []);
  const clearRealtimeVoiceReconnectTimer = () => {
    if (realtimeVoiceReconnectTimerRef.current === null) return;
    window.clearTimeout(realtimeVoiceReconnectTimerRef.current);
    realtimeVoiceReconnectTimerRef.current = null;
  };
  const scheduleRealtimeVoiceSilenceAnalysis = (candidateText?: string) => {
    clearRealtimeVoiceSilenceTimer();
    if (!realtimeVoiceActiveRef.current) return;
    const seedText = normalizeVoiceSegment(candidateText || realtimeVoiceRenderedRef.current || queryLatestRef.current);
    if (!seedText) return;
    realtimeVoiceSilenceTimerRef.current = window.setTimeout(() => {
      realtimeVoiceSilenceTimerRef.current = null;
      if (!realtimeVoiceActiveRef.current) return;
      const nextQuery = normalizeVoiceSegment(realtimeVoiceRenderedRef.current || queryLatestRef.current);
      if (!nextQuery || nextQuery === realtimeVoiceLastAutoAnalysisTextRef.current) return;
      realtimeVoiceLastAutoAnalysisTextRef.current = nextQuery;
      realtimeVoiceAutoAnalyzeRef.current(nextQuery, "realtime_voice_silence");
    }, realtimeVoiceSilenceAnalysisMs);
  };
  const cleanupRealtimeAudio = () => {
    try {
      realtimeVoiceProcessorRef.current?.disconnect();
    } catch {
      // ignore cleanup failures from already-disconnected audio nodes
    }
    try {
      realtimeVoiceSourceRef.current?.disconnect();
    } catch {
      // ignore cleanup failures from already-disconnected audio nodes
    }
    realtimeVoiceProcessorRef.current = null;
    realtimeVoiceSourceRef.current = null;
    realtimeVoiceStreamRef.current?.getTracks().forEach((track) => track.stop());
    realtimeVoiceStreamRef.current = null;
    void realtimeVoiceAudioContextRef.current?.close().catch(() => undefined);
    realtimeVoiceAudioContextRef.current = null;
  };
  const cleanupRealtimeVoiceConnection = (sendFinish: boolean) => {
    clearRealtimeVoiceSilenceTimer();
    clearRealtimeVoiceReconnectTimer();
    realtimeVoiceActiveRef.current = false;
    const socket = funAsrSocketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN && sendFinish) {
      socket.send(JSON.stringify({ type: "finish" }));
    }
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close();
    }
    funAsrSocketRef.current = null;
    cleanupRealtimeAudio();
  };
  const applyFunAsrTranscript = (text: string, isFinal: boolean) => {
    const normalized = normalizeVoiceSegment(text);
    if (!normalized) return;
    if (isFinal) {
      realtimeVoiceFinalRef.current = normalizeVoiceSegment(`${realtimeVoiceFinalRef.current} ${normalized}`);
      realtimeVoiceDraftRef.current = "";
    } else {
      realtimeVoiceDraftRef.current = normalized;
    }
    const recognizedText = normalizeVoiceSegment(`${realtimeVoiceFinalRef.current} ${realtimeVoiceDraftRef.current}`);
    const nextQuery = appendRealtimeVoiceText(realtimeVoiceBaseRef.current, recognizedText);
    realtimeVoiceRenderedRef.current = nextQuery;
    if (funAsrInputTargetRef.current === "voice") {
      setVoiceTranscript(nextQuery);
    }
    setQuery(nextQuery);
    if (isFinal && funAsrInputTargetRef.current === "query") {
      const command = extractRealtimeVoiceAnalysisCommand(nextQuery);
      if (command.triggered) {
        clearRealtimeVoiceSilenceTimer();
        if (!command.query || command.query === realtimeVoiceLastAutoAnalysisTextRef.current) return;
        realtimeVoiceRenderedRef.current = command.query;
        setQuery(command.query);
        realtimeVoiceLastAutoAnalysisTextRef.current = command.query;
        realtimeVoiceAutoAnalyzeRef.current(command.query, "realtime_voice_keyword");
        return;
      }
    }
    scheduleRealtimeVoiceSilenceAnalysis(nextQuery);
    queryInputRef.current?.focus();
  };
  const startRealtimeAudioStream = async (socket: WebSocket, stream: MediaStream) => {
    const AudioContextConstructor = getAudioContextConstructor();
    if (!AudioContextConstructor) {
      throw new Error("当前浏览器不支持实时音频采集，可继续直接输入。");
    }
    const audioContext = new AudioContextConstructor({ sampleRate: funAsrSampleRate });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (event) => {
      event.outputBuffer.getChannelData(0).fill(0);
      if (!realtimeVoiceActiveRef.current || socket.readyState !== WebSocket.OPEN) return;
      const channel = event.inputBuffer.getChannelData(0);
      const gated = gateRealtimeSpeakerFrame(realtimeVoiceSpeakerGateRef.current, channel, audioContext.sampleRate);
      realtimeVoiceSpeakerGateRef.current = gated.state;
      if (gated.justLocked) setVoiceprintStatus("locked");
      if (gated.rejectedSpeakerStarted) {
        realtimeVoiceIgnoredSpeakerSegmentsRef.current += 1;
        setRealtimeVoiceIgnoredSpeakerSegments(realtimeVoiceIgnoredSpeakerSegmentsRef.current);
      }
      const pcm = downsampleToPcm16(
        gated.accepted ? channel : new Float32Array(channel.length),
        audioContext.sampleRate,
        funAsrSampleRate,
      );
      socket.send(pcm.buffer.slice(0));
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    realtimeVoiceAudioContextRef.current = audioContext;
    realtimeVoiceSourceRef.current = source;
    realtimeVoiceProcessorRef.current = processor;
  };
  useEffect(() => {
    return () => {
      analysisWaitAbortRef.current?.abort();
      cleanupRealtimeVoiceConnection(false);
    };
  }, []);
  useEffect(() => {
    if (activeView !== "query") return;
    const sessionId = ensureAnalysisConversationSessionId(tenantId, userId);
    const state = loadConversationState(tenantId, userId, sessionId);
    setConversationSessionId(sessionId);
    setConversationTurns(state.turns);
    setQuery(state.draft);
    setAnalysisTopicsLoaded(false);
    setAnalysisTopicShortcuts([]);
  }, [activeView, tenantId, userId]);
  const visibleSavedAnalysisResults = savedAnalysisResults;
  const savedReportPagination = useClientPagination(visibleSavedAnalysisResults);
  const featuredEntries: Array<
    | { key: string; kind: "analysis"; result: SavedAnalysisResult }
    | { key: string; kind: "visual"; report: VisualReport }
  > = [];
  for (const ref of featuredReports.refs) {
    if (ref.kind === "analysis") {
      const result = savedAnalysisResults.find((item) => item.id === ref.id);
      if (result) featuredEntries.push({ key: featuredReportKey(ref), kind: "analysis", result });
      continue;
    }
    const report = visualMine.reports.find((item) => item.id === ref.id);
    if (report) featuredEntries.push({ key: featuredReportKey(ref), kind: "visual", report });
  }
  const featuredReportPagination = useClientPagination(featuredEntries);
  const selectReportKindTab = (tab: ReportKindTab) => {
    userPickedReportTabRef.current = true;
    setReportKindTab(tab);
  };
  useEffect(() => {
    userPickedReportTabRef.current = false;
    defaultReportTabAppliedRef.current = false;
    setReportKindTab(defaultMyReportsTab(loadFeaturedReports(tenantId, userId).length > 0));
  }, [tenantId, userId]);
  useEffect(() => {
    if (activeView !== "reports") return;
    if (!savedAnalysisLoaded || visualMine.loading) return;
    const live = pruneFeaturedReports(loadFeaturedReports(tenantId, userId), {
      analysisIds: savedAnalysisResults.map((item) => item.id),
      visualIds: visualMine.reports.map((item) => item.id),
    });
    featuredReports.replace(live);
    if (userPickedReportTabRef.current || defaultReportTabAppliedRef.current) return;
    defaultReportTabAppliedRef.current = true;
    setReportKindTab(defaultMyReportsTab(live.length > 0));
  }, [activeView, featuredReports.replace, savedAnalysisLoaded, savedAnalysisResults, tenantId, userId, visualMine.loading, visualMine.reports]);
  useEffect(() => {
    if (activeView !== "query" || !conversationSessionId) return;
    saveConversationState(tenantId, userId, {
      sessionId: conversationSessionId,
      draft: query,
      turns: conversationTurns,
      updatedAt: new Date().toISOString(),
    });
  }, [activeView, conversationSessionId, conversationTurns, query, tenantId, userId]);
  useEffect(() => {
    const input = queryInputRef.current;
    if (!input) return;
    if (analysisInputCollapsed) {
      input.style.height = "24px";
      return;
    }
    input.style.height = "0px";
    input.style.height = `${Math.min(Math.max(input.scrollHeight, 32), 140)}px`;
  }, [analysisInputCollapsed, query, selectedModeSkill, selectedSceneSkill, selectedTopicSkill, knowledgeFiles.length]);
  useEffect(() => {
    if (!analysisMenuOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (analysisMenuRef.current?.contains(target)) return;
      setAnalysisMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
    };
  }, [analysisMenuOpen]);
  useEffect(() => {
    if (!topicShortcutMenu) return;
    const closeOnOutsidePointer = () => setTopicShortcutMenu(null);
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
    };
  }, [topicShortcutMenu]);
  useEffect(() => {
    setDismissedAutoSkillIds((current) => {
      if (!current.size) return current;
      const mentionedIds = new Set(buildQuerySkillReferences(query, new Set(), availableAnalysisSkills).map((reference) => reference.skill.id));
      const next = new Set(Array.from(current).filter((skillId) => mentionedIds.has(skillId)));
      return sameStringSet(current, next) ? current : next;
    });
  }, [query]);
  useEffect(() => {
    if (activeView !== "query") return;
    let cancelled = false;
    const syncModels = async () => {
      try {
        const runtime = await fetchAnalysisRuntimeConfig({ tenantId, userId, speechApplicationModule: "realtime_voice_input" });
        if (cancelled) return;
        setFunAsrIntegration(runtime.speechIntegration);
        funAsrIntegrationByModuleRef.current.realtime_voice_input = runtime.speechIntegration;
        let models = runtime.models.filter((model) => model.name);
        if (!modelsForModule(models, "intelligent_analysis_reasoning").length) {
          const config = await fetchSystemConfig({ tenantId, userId });
          if (cancelled) return;
          models = (config.models || []).filter((model) => model.name);
        }
        const nextModels = models.length ? models : isDemoFallbackEnabled() ? fallbackAnalysisModels : [];
        setAvailableModels(nextModels);
        const analysisModels = modelsForModule(nextModels, "intelligent_analysis_reasoning");
        const preferredModel = findConfiguredTextModel(
          analysisModels,
          readPersistedTextModelSelection(tenantId, userId),
        );
        setSelectedModel(preferredModel && hasSelectableAnalysisModel(analysisModels, preferredModel)
          ? preferredModel
          : firstSelectableAnalysisModel(analysisModels));
      } catch {
        if (cancelled) return;
        try {
          const config = await fetchSystemConfig({ tenantId, userId });
          if (cancelled) return;
          const configModels = (config.models || []).filter((model) => model.name);
          setFunAsrIntegration(null);
          funAsrIntegrationByModuleRef.current.realtime_voice_input = null;
          const nextModels = configModels.length ? configModels : isDemoFallbackEnabled() ? fallbackAnalysisModels : [];
          setAvailableModels(nextModels);
          const analysisModels = modelsForModule(nextModels, "intelligent_analysis_reasoning");
          const preferredModel = findConfiguredTextModel(
            analysisModels,
            readPersistedTextModelSelection(tenantId, userId),
          );
          setSelectedModel(preferredModel && hasSelectableAnalysisModel(analysisModels, preferredModel)
            ? preferredModel
            : firstSelectableAnalysisModel(analysisModels));
        } catch {
          if (cancelled) return;
          setFunAsrIntegration(null);
          funAsrIntegrationByModuleRef.current.realtime_voice_input = null;
          const demoModels = isDemoFallbackEnabled() ? fallbackAnalysisModels : [];
          setAvailableModels(demoModels);
          const analysisModels = modelsForModule(demoModels, "intelligent_analysis_reasoning");
          const preferredModel = findConfiguredTextModel(
            analysisModels,
            readPersistedTextModelSelection(tenantId, userId),
          );
          setSelectedModel(preferredModel && hasSelectableAnalysisModel(analysisModels, preferredModel)
            ? preferredModel
            : firstSelectableAnalysisModel(analysisModels));
        }
      }
    };
    void syncModels();
    return () => {
      cancelled = true;
    };
  }, [activeView, tenantId, userId]);
  useEffect(() => {
    const applySharedSelection = () => {
      const analysisModels = modelsForModule(availableModels, "intelligent_analysis_reasoning");
      const preferredModel = findConfiguredTextModel(
        analysisModels,
        readPersistedTextModelSelection(tenantId, userId),
      );
      setSelectedModel(preferredModel && hasSelectableAnalysisModel(analysisModels, preferredModel)
        ? preferredModel
        : firstSelectableAnalysisModel(analysisModels));
    };
    window.addEventListener(textModelSelectionEvent, applySharedSelection);
    return () => window.removeEventListener(textModelSelectionEvent, applySharedSelection);
  }, [availableModels, tenantId, userId]);
  useEffect(() => {
    if (activeView !== "query") return;
    let cancelled = false;
    const syncMetrics = async () => {
      try {
        const [metricResponse, assetResponse, runtimeAssetResponse] = await Promise.all([
          fetchMetricDictionary({ tenantId, userId }),
          fetchDataAssets({ tenantId, userId }),
          fetchDataAssets({ tenantId, userId, scope: "runtime" }),
        ]);
        if (!cancelled) {
          const allConfiguredShortcuts = (assetResponse.analysis_shortcuts || [])
            .filter((item) => item.lifecycleStatus === "active" && item.visible);
          const ownedConfiguredShortcuts = allConfiguredShortcuts.filter((item) => item.ownerUserId === userId);
          const visibleConfiguredShortcuts = (ownedConfiguredShortcuts.length
            ? ownedConfiguredShortcuts
            : allConfiguredShortcuts.filter((item) => !item.ownerUserId))
            .sort((a, b) => a.sortOrder - b.sortOrder);
          setAvailableMetrics(metricResponse.metrics);
          // raw_tables is the same CSV catalog rendered in 数据管理 → 原始表.
          // It is intentionally not a separately stored configuration list.
          const nextRawTables = assetResponse.raw_tables.filter((table) => table.lifecycleStatus === "active");
          const nextTopicTables = (runtimeAssetResponse.topic_tables || []).filter(
            (item) => item.lifecycleStatus === "active",
          );
          const nextPageDataTables = (assetResponse.page_data || []).filter(
            (item) => item.lifecycleStatus === "active" && item.institutionScope === "multi_institution",
          );
          setAvailableRawTables(nextRawTables);
          setAvailableTopicTables(nextTopicTables);
          setAvailablePageDataTables(nextPageDataTables);
          const nextCatalog = [
            ...nextRawTables.map(rawTableToSelection),
            ...nextTopicTables.map(topicTableToSelection),
            ...nextPageDataTables.map(pageDataToSelection),
          ];
          analysisCatalogRef.current = nextCatalog;
          setSelectedDataTables((current) => rematchAnalysisDataTableSelection(current, nextCatalog));
          const configuredSkills = selectAvailableAnalysisSkills(runtimeAssetResponse.analysis_skills || [])
            .map((skill) => ({
              id: skill.id,
              name: skill.name,
              category: skill.category,
              description: skill.description,
              memoryRefs: skill.memoryRefs,
              toolRefs: skill.toolRefs,
              analysisMethod: skill.analysisMethod,
              documentAbstraction: skill.documentAbstraction,
              outputFormat: skill.outputFormat,
              viewpointStrategy: skill.viewpointStrategy,
              recommendedSkillIds: skill.recommendedSkillIds,
            } satisfies AnalysisSkillOption));
          const modeSkills = analysisSkillOptions.filter((skill) => skill.category === "模式");
          setAvailableAnalysisSkills([...modeSkills, ...configuredSkills]);
          setAnalysisTopicShortcuts(
            visibleConfiguredShortcuts
              .map((item) => ({
                id: item.id,
                title: item.title,
                query: item.query,
                method: "配置中心维护",
                sql: "",
                conclusionMode: "绑定Skill解决方案",
                summary: item.query,
                createdAt: item.publishedAt || "",
                updatedAt: item.reviewedAt || "",
                hidden: !item.visible,
                skillIds: item.skillIds,
                tableIds: item.tableIds,
                memoryIds: item.memoryIds,
              })),
          );
          setAnalysisTopicsLoaded(true);
        }
      } catch {
        if (!cancelled) {
          setAvailableMetrics([]);
          setAvailableRawTables([]);
          setAvailableTopicTables([]);
          setAvailablePageDataTables([]);
          // A stale local scene/subject must never replace the governed Skill
          // catalog after a read failure. Modes are local UI controls only.
          setAvailableAnalysisSkills(analysisSkillOptions.filter((skill) => skill.category === "模式"));
          setAnalysisTopicShortcuts([]);
          setAnalysisTopicsLoaded(true);
        }
      }
    };
    void syncMetrics();
    return () => {
      cancelled = true;
    };
  }, [activeView, tenantId, userId]);
  useEffect(() => {
    if (activeView !== "query" && activeView !== "reports") return;
    let cancelled = false;
    setSavedAnalysisLoaded(false);
    const syncSavedResults = async () => {
      try {
        const response = await fetchSavedAnalysisResults({ tenantId, userId });
        if (!cancelled) {
          setSavedAnalysisResults(response.results as SavedAnalysisResult[]);
          setSavedAnalysisLoadError("");
        }
      } catch (error) {
        if (cancelled) return;
        if (isDemoFallbackEnabled()) {
          setSavedAnalysisResults(loadSavedAnalysisResults());
          setSavedAnalysisLoadError(`当前展示 demo 本地缓存：${apiErrorMessage(error, "服务端历史加载失败")}`);
        } else {
          setSavedAnalysisResults([]);
          setSavedAnalysisLoadError(apiErrorMessage(error, "已保存分析加载失败"));
        }
      } finally {
        if (!cancelled) setSavedAnalysisLoaded(true);
      }
    };
    void syncSavedResults();
    return () => {
      cancelled = true;
    };
  }, [activeView, tenantId, userId]);
  useEffect(() => {
    if (!realtimeVoiceError || realtimeVoiceListening) return;
    const timer = window.setTimeout(() => setRealtimeVoiceError(""), 8000);
    return () => window.clearTimeout(timer);
  }, [realtimeVoiceError, realtimeVoiceListening]);
  const handleQueryChange = (value: string) => {
    setQuery(value);
    if (realtimeVoiceError) setRealtimeVoiceError("");
    if (realtimeVoiceListening) {
      syncFunAsrManualEdit("query", value);
      scheduleRealtimeVoiceSilenceAnalysis(value);
    }
  };
  const handleVoiceTranscriptChange = (value: string) => {
    setVoiceTranscript(value);
    if (voiceListening) syncFunAsrManualEdit("voice", value);
  };
  const ensureActiveConversationSessionId = () => {
    if (conversationSessionId) return conversationSessionId;
    const sessionId = ensureAnalysisConversationSessionId(tenantId, userId);
    setConversationSessionId(sessionId);
    return sessionId;
  };
  const addConversationTurn = (turn: AnalysisConversationTurn) => {
    setConversationTurns((current) => [...current, turn].slice(-30));
  };
  const addAnalysisTopicShortcut = (shortcut: AnalysisTopicShortcut) => {
    setAnalysisTopicShortcuts((current) => [shortcut, ...current].slice(0, 40));
  };
  const hideAnalysisTopicShortcut = async (topicId: string) => {
    const topic = analysisTopicShortcuts.find((item) => item.id === topicId);
    if (!(await askConfirm({ title: "删除快捷键", description: `确定删除快捷键「${topic?.title || "该项"}」？`, hint: "此操作不可撤销。" }))) return;
    setAnalysisTopicShortcuts((current) => current.map((item) => item.id === topicId ? { ...item, hidden: true, updatedAt: new Date().toISOString() } : item));
    setTopicShortcutMenu(null);
  };
  const renameAnalysisTopicShortcut = (topicId: string, title: string) => {
    setAnalysisTopicShortcuts((current) => current.map((topic) => topic.id === topicId ? { ...topic, title, updatedAt: new Date().toISOString() } : topic));
  };
  const finishAnalysisTopicEditing = (topicId: string) => {
    setAnalysisTopicShortcuts((current) =>
      current.map((topic) => {
        if (topic.id !== topicId) return topic;
        const trimmed = topic.title.trim();
        return {
          ...topic,
          title: trimmed || "未命名分析主题",
          updatedAt: new Date().toISOString(),
        };
      }),
    );
    setEditingTopicId(null);
  };
  const startAnalysisTopicEditing = (topicId: string) => { setTopicShortcutMenu(null); setEditingTopicId(topicId); };
  const uploadKnowledgeFiles = async (files: File[]) => {
    if (!files.length) return;
    const { accepted, rejectedMessage } = await ingestAnalysisUploads(files, { tenantId, userId });
    if (rejectedMessage) setAnalysisError(rejectedMessage);
    else if (accepted.length) setAnalysisError("");
    if (accepted.length) {
      setKnowledgeFiles((current) => [...current, ...accepted]);
      setActiveMetricPreset(null);
      await Promise.all(
        accepted.map((file) =>
          runApplicationAction({
            tenantId,
            userId,
            moduleKey: "self_analysis",
            action: "upload_knowledge_file",
            payload: {
              id: file.id,
              name: file.name,
              type: file.type,
              size: file.size,
              lastModified: file.lastModified,
              classification: file.classification,
            },
          }).catch(() => undefined),
        ),
      );
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };
  const chooseFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    await uploadKnowledgeFiles(Array.from(files));
  };
  const handleQueryPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.files);
    const itemFiles = Array.from(event.clipboardData.items)
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file));
    const pastedFiles = [...files, ...itemFiles].filter(
      (file, index, values) =>
        values.findIndex((item) => item.name === file.name && item.size === file.size && item.type === file.type) === index,
    );
    if (!pastedFiles.length) return;
    event.preventDefault();
    void uploadKnowledgeFiles(pastedFiles);
  };
  const selectAnalysisSkill = (skill: AnalysisSkillOption) => {
    if (skill.category === "场景") setSelectedSceneSkill(skill);
    else if (skill.category === "主题") setSelectedTopicSkill(skill);
    else setSelectedModeSkill(skill);
    setAnalysisMenuOpen(false);
    void runApplicationAction({
      tenantId,
      userId,
      moduleKey: "self_analysis",
      action: "select_analysis_skill",
      payload: { skill },
    }).catch(() => undefined);
    queryInputRef.current?.focus();
  };
  const clearAnalysisSkill = (skill: AnalysisSkillOption) => {
    if (skill.category === "场景") setSelectedSceneSkill(null);
    else if (skill.category === "主题") setSelectedTopicSkill(null);
    else setSelectedModeSkill(null);
    void runApplicationAction({
      tenantId,
      userId,
      moduleKey: "self_analysis",
      action: "clear_analysis_skill",
      payload: { skill },
    }).catch(() => undefined);
    queryInputRef.current?.focus();
  };
  const selectAnalysisModel = (model: ModelIntegration) => {
    setSelectedModel(model);
    const selectedModelName = model.selectedModelName || model.enabledModels?.[0] || model.availableModels?.[0] || "";
    if (!model.id || !selectedModelName) return;
    persistTextModelSelection(tenantId, userId, {
      integrationId: model.id,
      selectedModelName,
    });
  };
  const removeKnowledgeFile = (fileId: string) => {
    setKnowledgeFiles((current) => current.filter((file) => file.id !== fileId));
    void runApplicationAction({
      tenantId,
      userId,
      moduleKey: "self_analysis",
      action: "remove_knowledge_file",
      payload: { fileId },
    }).catch(() => undefined);
  };
  const removeSelectedDataTable = (tableId: string) => {
    setSelectedDataTables((current) => current.filter((table) => table.id !== tableId));
  };
  const handleAnalysisRunProgress = (run: { automation_run_id: string; status?: string; progress_steps?: AnalysisProgressStep[] }, generation = analysisGenerationRef.current) => {
    if (generation !== analysisGenerationRef.current) return;
    activeAnalysisRunIdRef.current = run.automation_run_id;
    setAnalysisSubmissionPhase(run.status === "queued" ? "queued" : "running");
    const steps = (run.progress_steps || []).filter((step) => step.step_code !== "execute_handler");
    if (steps.length) setAnalysisProgressSteps(steps);
    const partialTaskId = [...steps]
      .reverse()
      .flatMap((step) => step.output_refs || [])
      .map((ref) => String(ref.partial_task_id || ""))
      .find(Boolean);
    if (!partialTaskId || partialAnalysisTaskIdRef.current === partialTaskId) return;
    partialAnalysisTaskIdRef.current = partialTaskId;
    void fetchAnalysisTask({ taskId: partialTaskId, tenantId, userId })
      .then((partial) => {
        if (generation !== analysisGenerationRef.current) return;
        partialAnalysisResponseRef.current = partial;
        const currentQuestion = partial.question || queryLatestRef.current;
        const partialRows = mapBackendRows(partial, currentQuestion, selectedDataTables);
        if (!partialRows.length) return;
        setAnalysisTaskId(partial.task_id);
        setAnalysisRows(partialRows);
        const fallbackVisualTypes = inferVisualTypes(currentQuestion, selectedDataTables);
        setAnalysisPlan(formatBackendPlan(currentQuestion, partial.analysis_plan) || createAnalysisPlan(currentQuestion, fallbackVisualTypes));
        setVisualTypes(visualTypesFromBackend(partial, fallbackVisualTypes, currentQuestion));
        setSqlScript(sqlScriptFromBackend(partial));
        setPythonScript(pythonScriptFromBackend(partial));
        setResultMode("visual");
      })
      .catch(() => {
        if (generation !== analysisGenerationRef.current) return;
        partialAnalysisTaskIdRef.current = "";
      });
  };
  useEffect(() => {
    if (activeView !== "query") return;
    const pending = loadPendingAnalysisRun(tenantId, userId);
    if (!pending || isAnalyzingRef.current) return;
    const analysisGeneration = ++analysisGenerationRef.current;
    const controller = new AbortController();
    analysisWaitAbortRef.current = controller;
    activeAnalysisRunIdRef.current = pending.runId;
    isAnalyzingRef.current = true;
    setIsAnalyzing(true);
    setAnalysisSubmissionPhase("running");
    setQuery(pending.question);
    const pendingTables = singleAnalysisDataTableSelection(pending.selectedDataTables);
    setSelectedDataTables(pendingTables);
    setShowResult(true);
    setResultMode("thinking");
    setAnalysisError("");
    setAnalysisProgressSteps([{
      step_code: "resume_pending_run",
      sequence_no: 0,
      status: "running",
      output_refs: [{ label: "恢复分析任务", detail: "正在继续读取离开页面前的分析进度。" }],
    }]);
    void waitForSelfAnalysis({
      question: pending.question,
      tenantId,
      userId,
      resumeRunId: pending.runId,
      signal: controller.signal,
      onRun: (run) => {
        if (analysisGeneration !== analysisGenerationRef.current || controller.signal.aborted) return;
        handleAnalysisRunProgress(run, analysisGeneration);
        savePendingAnalysisRun(tenantId, userId, { ...pending, selectedDataTables: pendingTables, runId: run.automation_run_id });
      },
    }).then((response) => {
      if (analysisGeneration !== analysisGenerationRef.current || controller.signal.aborted) return;
      const restoredQuery = response.question || pending.question;
      const fallbackVisualTypes = inferVisualTypes(restoredQuery, pendingTables);
      setAnalysisTaskId(response.task_id);
      setAnalysisPlan(formatBackendPlan(restoredQuery, response.analysis_plan) || createAnalysisPlan(restoredQuery, fallbackVisualTypes));
      setAnalysisRows(mapBackendRows(response, restoredQuery, pendingTables));
      setAnalysisSummary(
        response.intelligent_analysis?.analysis_summary?.trim()
        || response.conclusions?.filter((item) => item.trim()).join("\n")
        || "后端未返回经复核的分析结论；不会由前端模板补写。",
      );
      setAnalysisScenarios(formatMetricScenarios(response));
      setVisualTypes(visualTypesFromBackend(response, fallbackVisualTypes, restoredQuery));
      setSqlScript(sqlScriptFromBackend(response));
      setPythonScript(pythonScriptFromBackend(response));
      setAnalysisProgressSteps(completedProgressSteps(response));
      setResultMode("visual");
      rememberTopicRound(
        restoredQuery,
        response,
        pendingTables,
        mapBackendRows(response, restoredQuery, pendingTables),
      );
    }).catch((error) => {
      if (analysisGeneration !== analysisGenerationRef.current) return;
      if (isAnalysisNavigationAbort(error)) return;
      setAnalysisError(apiErrorMessage(error, "分析任务恢复失败"));
      setResultMode("visual");
    }).finally(() => {
      if (analysisGeneration !== analysisGenerationRef.current || controller.signal.aborted) return;
      clearPendingAnalysisRun(tenantId, userId, pending.runId);
      if (analysisWaitAbortRef.current === controller) analysisWaitAbortRef.current = null;
      activeAnalysisRunIdRef.current = "";
      isAnalyzingRef.current = false;
      setIsAnalyzing(false);
      setAnalysisSubmissionPhase("idle");
    });
    return () => controller.abort();
  }, [activeView, tenantId, userId]);
  const handleQuery = async (
    q?: string,
    topic?: TopicTableAsset,
    trigger: AnalysisRunTrigger = "manual",
    forcedSkills: AnalysisSkillOption[] = [],
    forcedDataTables?: AnalysisDataTableSelection[],
    forcedMemoryIds: string[] = [],
    topicDataSource?: { type: "shortcut"; id: string },
  ) => {
    const nextQuery = (q || query).trim();
    if (isAnalyzingRef.current) return;
    if (!nextQuery) {
      setAnalysisError("请输入明确的分析问题后再执行");
      return;
    }
    void topicPrecipitation.prepareQuestionSwitch(nextQuery);
    const realtimeVoiceTrigger = isRealtimeVoiceTrigger(trigger);
    const preserveRealtimeQueryInput = funAsrInputTargetRef.current === "query" && (
      realtimeVoiceActiveRef.current || realtimeVoiceReconnectTimerRef.current !== null
    );
    if (!realtimeVoiceTrigger && !preserveRealtimeQueryInput) {
      cleanupRealtimeVoiceConnection(true);
      setRealtimeVoiceListening(false);
      setVoiceListening(false);
      setRealtimeVoiceError("");
    } else if (!realtimeVoiceTrigger && preserveRealtimeQueryInput) {
      // Manual submit while continuous listening must consume the current
      // speech segment exactly once, without stopping ASR or letting the old
      // five-second timer enqueue the same question again.
      clearRealtimeVoiceSilenceTimer();
      resetFunAsrTranscriptState("");
    }
    const nextQuerySkillReferences = buildQuerySkillReferences(nextQuery, dismissedAutoSkillIds, availableAnalysisSkills);
    const analysisContextSkills = uniqueSkills([
      ...forcedSkills,
      ...selectedManualSkills,
      ...nextQuerySkillReferences.map((reference) => reference.skill),
    ]);
    let effectiveDataTables = singleAnalysisDataTableSelection(forcedDataTables ?? selectedDataTables);
    const submissionCatalog = availableAnalysisTables;
    let resolvedViaMetricPreset = false;
    const uploadGate = uploadedAnalysisGate(knowledgeFiles);
    if (uploadGate.mediaOnly) {
      setAnalysisError(UPLOADED_MEDIA_UNSUPPORTED_MESSAGE);
      return;
    }
    if (!effectiveDataTables.length && !topic && !uploadGate.hasDataSource && !uploadGate.hasTextDocument) {
      const preset = resolveMetricPreset(nextQuery, availableMetrics, submissionCatalog);
      if (preset.table) {
        effectiveDataTables = [preset.table];
        resolvedViaMetricPreset = true;
        setSelectedDataTables(effectiveDataTables);
      } else {
        setActiveMetricPreset(preset);
        setAnalysisError("");
        flashMetricPresetNotice();
        return;
      }
    }
    setActiveMetricPreset(null);
    if (effectiveDataTables !== selectedDataTables) setSelectedDataTables(effectiveDataTables);
    const modelApplicationModule = modelApplicationModuleForTrigger();
    const analysisModels = modelsForModule(availableModels, modelApplicationModule);
    const routedModel = modelApplicationModule === "intelligent_analysis_reasoning"
      ? selectedModel && hasSelectableAnalysisModel(analysisModels, selectedModel)
        ? selectedModel
        : firstSelectableAnalysisModel(analysisModels)
      : configuredModelForModule(availableModels, modelApplicationModule);
    if (modelApplicationModule === "intelligent_analysis_reasoning" && routedModel !== selectedModel) setSelectedModel(routedModel);
    const activeConversationSessionId = ensureActiveConversationSessionId();
    const userTurn = makeConversationTurn("user", nextQuery, { query: nextQuery });
    const requestConversationTurns = [...conversationTurns, userTurn].slice(-30);
    setConversationTurns(requestConversationTurns);
    const conversationContext = formatConversationContext(
      activeConversationSessionId,
      requestConversationTurns,
      nextQuery,
      analysisContextSkills.some((skill) => skill.id === "context-compression"),
    );
    const fallbackVisualTypes = inferVisualTypes(nextQuery, effectiveDataTables);
    const topicPlan = topic
      ? `${createAnalysisPlan(nextQuery, fallbackVisualTypes)}
主题表：${topic.name}（${topic.code}）
主题SQL：${topic.sql}
字段解释：${topic.fieldExplanations}
适用场景：${topic.applicableScene}`
      : createAnalysisPlan(nextQuery, fallbackVisualTypes);
    const fallbackPlan = appendMetricReferences(topicPlan, nextQuery, availableMetrics);
    const skillPlan = analysisContextSkills.length
      ? `${fallbackPlan}\n分析上下文：${analysisContextSkills
          .map((skill) => `${skill.name}（${skill.category}） - ${skill.description}`)
          .join("；")}`
      : fallbackPlan;
    const filePlan = knowledgeFiles.length
      ? `${skillPlan}\n知识文件：${knowledgeFiles.map((file) => file.name).join("、")}`
      : skillPlan;
    const tableContextText = formatSelectedDataTables(effectiveDataTables);
    const dataTablePlan = tableContextText
      ? `${filePlan}\n已选择数据表：${effectiveDataTables.map((table) => `${table.name}(${table.code})`).join("、")}\n${tableContextText}`
      : filePlan;
    const modelPlan = routedModel
      ? `${dataTablePlan}\n应用模块：${modelApplicationModuleLabel(modelApplicationModule)}\n调用引擎：${routedModel.name}`
      : `${dataTablePlan}\n应用模块：${modelApplicationModuleLabel(modelApplicationModule)}（未配置可用模型）`;
    const realtimeVoiceAutoAnalysis =
      realtimeVoiceTrigger
        ? {
            enabled: true,
            trigger,
            silenceMs: realtimeVoiceSilenceAnalysisMs,
            commandKeyword: trigger === "realtime_voice_keyword" ? "开始分析" : null,
            contextInputs: ["input_text", "uploaded_files", "referenced_skills", "selected_data_tables"],
            expectedOutputs: ["sql", "python_script", "metric_scenarios", "visualization_suggestions", "analysis_summary"],
          }
        : null;
    const analysisPolicy = {
      engine: "IntelligentAnalysisEngine",
      resultDelivery: "data_first",
      multiRoleDebate: "reuse_weekly_learning_memory_chain_when_writing_back_experience",
      timeDecay: "preserve_knowledge_memory_weighting_and_do_not_override_current_fact_data",
      conflictStrategy: "selected_input_context_has_priority_for_current_run",
    };
    const analysisGeneration = ++analysisGenerationRef.current;
    setQuery(nextQuery);
    setSelectedTopic(topic ?? null);
    setScriptPlanName(topic?.name || nextQuery);
    setVisualTypes(fallbackVisualTypes);
    setAnalysisPlan(modelPlan);
    setAnalysisRows([]);
    setAnalysisSummary("");
    setAnalysisScenarios("正在等待第一阶段模型生成指标表现情景……");
    setSqlScript("-- 等待服务端执行；不会展示前端生成的候选 SQL。");
    setPythonScript("# 等待服务端执行；不会展示前端生成的候选 Python 脚本。");
    partialAnalysisTaskIdRef.current = "";
    partialAnalysisResponseRef.current = null;
    setAnalysisProgressSteps([
      {
        step_code: "request_queued",
        sequence_no: 0,
        status: "queued",
        output_refs: [{ label: "创建分析任务", detail: "正在提交问题并分配分析执行资源。" }],
      },
    ]);
    setResultMode("thinking");
    setSaveMessage("");
    setShowResult(true);
    setAnalysisSubmissionPhase("submitting");
    setIsAnalyzing(true);
    isAnalyzingRef.current = true;
    setAnalysisError("");
    analysisWaitAbortRef.current?.abort();
    const waitController = new AbortController();
    analysisWaitAbortRef.current = waitController;
    let trackedRunId = "";
    const pendingStartedAt = new Date().toISOString();
    try {
      const response = await waitForSelfAnalysis({
        question: nextQuery,
        tenantId,
        userId,
        requestId: createClientUuid(),
        signal: waitController.signal,
        onRun: (run) => {
          if (analysisGeneration !== analysisGenerationRef.current || waitController.signal.aborted) return;
          trackedRunId = run.automation_run_id;
          savePendingAnalysisRun(tenantId, userId, {
            runId: run.automation_run_id,
            question: nextQuery,
            selectedDataTables: effectiveDataTables,
            startedAt: pendingStartedAt,
          });
          if (!waitController.signal.aborted) handleAnalysisRunProgress(run, analysisGeneration);
        },
        pageContext: {
          route: "self-analysis/query",
          analysis_scene_hint: "self_analysis",
          selected_institution: selectedInstitution,
          analysis_trigger: trigger,
          model_application_module: modelApplicationModule,
          model_application_selection: modelApplicationSelection(modelApplicationModule, routedModel),
          realtime_voice_auto_analysis: realtimeVoiceAutoAnalysis,
          analysis_policy: analysisPolicy,
          visualization_preferences: visualizationPreferencesFromQuestion(nextQuery, effectiveDataTables),
          analysis_skill: primaryAnalysisSkill,
          analysis_context_skills: analysisContextSkills,
          conversation_session: conversationContext,
          auto_referenced_skills: nextQuerySkillReferences.map((reference) => ({
            id: reference.skill.id,
            name: reference.skill.name,
            category: reference.skill.category,
            description: reference.skill.description,
            matchedText: reference.text,
            rangeStart: reference.start,
            rangeEnd: reference.end,
          })),
          selected_data_tables: effectiveDataTables,
          analysis_memory_ids: forcedMemoryIds,
          topic_data_source: topicDataSource || null,
          files: knowledgeFiles,
          plugins: [],
          selected_topic: topic
            ? {
                id: topic.id,
                code: topic.code,
                name: topic.name,
                sql: topic.sql,
                fields: formatTopicFields(topic.fields),
              }
            : null,
        },
      });
      if (analysisGeneration !== analysisGenerationRef.current || waitController.signal.aborted) return;
      const backendPlan = appendMetricReferences(formatBackendPlan(nextQuery, response.analysis_plan) || modelPlan, nextQuery, availableMetrics);
      const backendRows = mapBackendRows(response, nextQuery, effectiveDataTables);
      const backendVisualTypes = visualTypesFromBackend(response, fallbackVisualTypes, nextQuery);
      const backendSummary =
        response.intelligent_analysis?.analysis_summary?.trim() ||
        response.conclusions?.filter((item) => item.trim()).join("\n") ||
        "后端未返回经复核的分析结论；不会由前端模板补写。";
      const backendSql = sqlScriptFromBackend(response);
      const backendPython = pythonScriptFromBackend(response);
      setAnalysisError(modelInvocationIssue(response, routedModel));
      setAnalysisTaskId(response.task_id);
      const documentMode = String(response.skill_results?.[0]?.semantic_info?.execution_mode || "") === "uploaded_document_summary";
      if (documentMode) {
        visualCardsTaskRef.current = response.task_id;
        setVisualTypes({ primary: "text", secondary: "text" });
        setVisualCards(documentSummaryCards(backendSummary));
      } else {
        setVisualTypes(backendVisualTypes);
      }
      setAnalysisPlan(backendPlan);
      setAnalysisRows(backendRows);
      setAnalysisSummary(backendSummary);
      setAnalysisScenarios(formatMetricScenarios(response));
      setSqlScript(backendSql);
      setPythonScript(backendPython);
      setResultMode("visual");
      partialAnalysisResponseRef.current = response;
      const resolvedTables = resolveVisualAnalysisTables(response.asset_context?.selected_data_tables, effectiveDataTables);
      const catalogTables = resolvedTables.filter((table) => !String(table.relativePath || "").startsWith("upload://"));
      if (catalogTables.length) setSelectedDataTables(catalogTables);
      rememberTopicRound(nextQuery, response, catalogTables.length ? catalogTables : effectiveDataTables, backendRows, resolvedViaMetricPreset);
      addConversationTurn(
        makeConversationTurn("assistant", backendSummary, {
          query: nextQuery,
          summary: backendSummary,
          sql: backendSql,
          analysisPlan: backendPlan,
        }),
      );
    } catch (error) {
      if (analysisGeneration !== analysisGenerationRef.current) return;
      if (isAnalysisNavigationAbort(error)) return;
      let partial = partialAnalysisResponseRef.current;
      if (!partial && partialAnalysisTaskIdRef.current) {
        try { partial = await fetchAnalysisTask({ taskId: partialAnalysisTaskIdRef.current, tenantId, userId }); } catch { partial = null; }
        if (analysisGeneration !== analysisGenerationRef.current) return;
      }
      const partialRows = partial ? mapBackendRows(partial, nextQuery, effectiveDataTables) : [];
      if (partial && partialRows.length) {
        setAnalysisTaskId(partial.task_id);
        setAnalysisRows(partialRows);
        setAnalysisPlan(formatBackendPlan(nextQuery, partial.analysis_plan) || modelPlan);
        setVisualTypes(visualTypesFromBackend(partial, fallbackVisualTypes, nextQuery));
        setSqlScript(sqlScriptFromBackend(partial));
        setPythonScript(pythonScriptFromBackend(partial));
        setAnalysisSummary(`数据查询已完成并保留 ${partialRows.length} 行结果；智能结论阶段暂未完成，请先查看数据或稍后重试。`);
        setAnalysisScenarios("数据查询已完成；模型结论阶段未完成，不影响查看已返回的数据与可视化。");
        setAnalysisError(`数据与可视化已保留；智能结论阶段在自动重试后仍未完成。${error instanceof Error ? error.message : ""}`);
        setResultMode("visual");
      } else {
        setAnalysisTaskId("");
        setAnalysisRows([]);
        setAnalysisSummary("分析服务未返回可用数据，请检查 API 服务、数据源连接或当前角色的数据权限。");
        setAnalysisScenarios("数据查询阶段未返回结果。");
        setAnalysisError(error instanceof Error ? error.message : "后端分析服务暂不可用。");
      }
    } finally {
      if (analysisGeneration !== analysisGenerationRef.current || waitController.signal.aborted) return;
      clearPendingAnalysisRun(tenantId, userId, trackedRunId || undefined);
      if (analysisWaitAbortRef.current === waitController) analysisWaitAbortRef.current = null;
      activeAnalysisRunIdRef.current = "";
      setIsAnalyzing(false);
      setAnalysisSubmissionPhase("idle");
      isAnalyzingRef.current = false;
      window.setTimeout(() => realtimeVoiceDrainQueueRef.current(), 0);
    }
  };
  realtimeVoiceAutoAnalyzeRef.current = (nextQuery: string, trigger: RealtimeVoiceTrigger) => {
    const target = funAsrInputTargetRef.current;
    if (target === "voice") {
      setVoiceTranscript(nextQuery);
      setVoiceOpen(false);
    }
    resetFunAsrTranscriptState("");
    setQuery("");
    if (isAnalyzingRef.current) {
      const queue = realtimeVoiceQueueRef.current;
      if (queue[queue.length - 1]?.text !== nextQuery) queue.push({ text: nextQuery, trigger });
      setRealtimeVoiceQueueLength(queue.length);
      return;
    }
    void handleQuery(nextQuery, undefined, trigger);
  };
  realtimeVoiceDrainQueueRef.current = () => {
    if (isAnalyzingRef.current) return;
    const nextQuery = realtimeVoiceQueueRef.current.shift();
    setRealtimeVoiceQueueLength(realtimeVoiceQueueRef.current.length);
    if (!nextQuery) return;
    void handleQuery(nextQuery.text, undefined, nextQuery.trigger);
  };
  const updateVisualType = (key: ResultVisualKey, type: VisualizationType) => {
    setVisualTypes((current) => ({ ...current, [key]: type }));
    setVisualCards((current) => current.map((card) => card.key === key ? { ...card, type, title: card.title.includes("·") ? `${card.title.split("·")[0].trim()} · ${visualizationLabel(type)}` : card.title } : card));
  };
  const updateVisualCard = (id: string, patch: Partial<VisualCardInstance>) => {
    setVisualCards((current) => current.map((card) => card.id === id ? { ...card, ...patch } : card));
  };
  const duplicateVisualCard = (id: string, config: VisualizationCardConfig, options?: { asText?: boolean }) => {
    setVisualCards((current) => {
      const index = current.findIndex((card) => card.id === id);
      if (index < 0) return current;
      const source = current[index];
      const duplicate: VisualCardInstance = {
        ...source,
        id: `visual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        key: undefined,
        type: options?.asText ? "text" : source.type,
        title: options?.asText ? `${source.title} · 结论` : `${source.title} · 副本`,
        config: options?.asText ? { ...config, noteTitle: "", noteBody: "", noteItems: [], noteTitleHidden: false, ...visualDuplicateLayout(source.id) } : config,
      };
      return [...current.slice(0, index + 1), duplicate, ...current.slice(index + 1)];
    });
  };
  const deleteVisualCard = async (id: string) => {
    const card = visualCards.find((item) => item.id === id);
    if (!(await askConfirm({ title: "删除图表", description: `确定删除图表「${card?.title || "该图表"}」？`, hint: "此操作不可撤销。" }))) return;
    setVisualCards((current) => current.filter((item) => item.id !== id));
  };
  const reportVisualTypesFor = (result: SavedAnalysisResult): Record<ResultVisualKey, VisualizationType> => (
    reportVisualTypeOverrides[result.id] || {
      primary: result.visualTypes.primary as VisualizationType,
      secondary: result.visualTypes.secondary as VisualizationType,
    }
  );
  const reportVisualizationsFor = (result: SavedAnalysisResult): VisualCardInstance[] => (
    result.visualizations?.length
      ? result.visualizations.map((card) => ({ ...card, type: card.type as VisualizationType, config: card.config as VisualizationCardConfig | undefined }))
      : defaultVisualizationCards(reportVisualTypesFor(result))
  );
  const persistSavedReportVisualizations = async (result: SavedAnalysisResult, visualizations: VisualCardInstance[]) => {
    const nextResult: SavedAnalysisResult = {
      ...result,
      visualTypes: {
        primary: (visualizations.find((card) => card.key === "primary")?.type || result.visualTypes.primary) as VisualizationType,
        secondary: (visualizations.find((card) => card.key === "secondary")?.type || result.visualTypes.secondary) as VisualizationType,
      },
      visualizations: visualizations.map((card) => ({ id: card.id, key: card.key, title: card.title, type: card.type, config: card.config })),
    };
    setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? nextResult : item));
    try {
      const response = await saveSavedAnalysisResult({ tenantId, userId, result: nextResult });
      const saved = response.result as SavedAnalysisResult;
      setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? saved : item));
    } catch (error) {
      setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? result : item));
      setReportActionError(apiErrorMessage(error, "可视化配置保存失败"));
    }
  };
  const updateSavedReportVisualType = async (
    result: SavedAnalysisResult,
    key: ResultVisualKey,
    type: VisualizationType,
  ) => {
    const previousTypes = reportVisualTypesFor(result);
    const nextTypes = { ...previousTypes, [key]: type };
    setReportVisualTypeOverrides((current) => ({ ...current, [result.id]: nextTypes }));
    setReportActionError("");
    setReportActionLoadingId(`${result.id}:visual:${key}`);
    try {
      const response = await saveSavedAnalysisResult({ tenantId, userId, result: { ...result, visualTypes: nextTypes } });
      const saved = response.result as SavedAnalysisResult;
      setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? saved : item));
      setReportVisualTypeOverrides((current) => {
        const { [result.id]: _savedOverride, ...remaining } = current;
        return remaining;
      });
    } catch (error) {
      setReportVisualTypeOverrides((current) => ({ ...current, [result.id]: previousTypes }));
      setReportActionError(apiErrorMessage(error, "可视化样式保存失败"));
    } finally {
      setReportActionLoadingId("");
    }
  };
  const rerunAnalysis = async () => {
    const nextQuery = query.trim();
    if (!nextQuery) {
      setAnalysisError("当前没有可重新执行的分析问题");
      return;
    }
    const nextQuerySkillReferences = buildQuerySkillReferences(nextQuery, dismissedAutoSkillIds, availableAnalysisSkills);
    const analysisContextSkills = uniqueSkills([
      ...selectedManualSkills,
      ...nextQuerySkillReferences.map((reference) => reference.skill),
    ]);
    const modelApplicationModule = "intelligent_analysis_reasoning";
    const analysisModels = modelsForModule(availableModels, modelApplicationModule);
    const routedModel = selectedModel && hasSelectableAnalysisModel(analysisModels, selectedModel)
      ? selectedModel
      : firstSelectableAnalysisModel(analysisModels);
    if (routedModel !== selectedModel) setSelectedModel(routedModel);
    const activeConversationSessionId = ensureActiveConversationSessionId();
    const userTurn = makeConversationTurn("user", `重新分析：${nextQuery}`, { query: nextQuery, analysisPlan });
    const requestConversationTurns = [...conversationTurns, userTurn].slice(-30);
    setConversationTurns(requestConversationTurns);
    const conversationContext = formatConversationContext(
      activeConversationSessionId,
      requestConversationTurns,
      nextQuery,
      analysisContextSkills.some((skill) => skill.id === "context-compression"),
    );
    setAnalysisSubmissionPhase("submitting");
    setIsAnalyzing(true);
    isAnalyzingRef.current = true;
    setAnalysisError("");
    setSaveMessage("");
    partialAnalysisTaskIdRef.current = "";
    partialAnalysisResponseRef.current = null;
    setAnalysisProgressSteps([
      {
        step_code: "request_queued",
        sequence_no: 0,
        status: "queued",
        output_refs: [{ label: "创建重跑任务", detail: "正在提交修改后的分析方案并创建新版本。" }],
      },
    ]);
    setResultMode("thinking");
    analysisWaitAbortRef.current?.abort();
    const waitController = new AbortController();
    analysisWaitAbortRef.current = waitController;
    let trackedRunId = "";
    const pendingStartedAt = new Date().toISOString();
    const analysisGeneration = ++analysisGenerationRef.current;
    try {
      const response = await waitForSelfAnalysis({
        question: nextQuery,
        tenantId,
        userId,
        requestId: createClientUuid(),
        signal: waitController.signal,
        onRun: (run) => {
          if (analysisGeneration !== analysisGenerationRef.current || waitController.signal.aborted) return;
          trackedRunId = run.automation_run_id;
          savePendingAnalysisRun(tenantId, userId, {
            runId: run.automation_run_id,
            question: nextQuery,
            selectedDataTables,
            startedAt: pendingStartedAt,
          });
          if (!waitController.signal.aborted) handleAnalysisRunProgress(run, analysisGeneration);
        },
        pageContext: {
          route: "self-analysis/query",
          analysis_scene_hint: "self_analysis",
          selected_institution: selectedInstitution,
          analysis_trigger: "manual",
          model_application_module: modelApplicationModule,
          model_application_selection: modelApplicationSelection(modelApplicationModule, routedModel),
          parent_task_id: analysisTaskId || null,
          realtime_voice_auto_analysis: null,
          analysis_policy: {
            engine: "IntelligentAnalysisEngine",
            resultDelivery: "data_first",
            multiRoleDebate: "reuse_weekly_learning_memory_chain_when_writing_back_experience",
            timeDecay: "preserve_knowledge_memory_weighting_and_do_not_override_current_fact_data",
            conflictStrategy: "selected_input_context_has_priority_for_current_run",
          },
          edited_analysis_plan: analysisPlan,
          edited_sql_script: sqlScript,
          edited_python_script: pythonScript,
          edited_ai_summary: analysisSummary,
          visualization_preferences: visualizationPreferencesFromQuestion(nextQuery, selectedDataTables),
          analysis_skill: primaryAnalysisSkill,
          analysis_context_skills: analysisContextSkills,
          conversation_session: conversationContext,
          auto_referenced_skills: nextQuerySkillReferences.map((reference) => ({
            id: reference.skill.id,
            name: reference.skill.name,
            category: reference.skill.category,
            description: reference.skill.description,
            matchedText: reference.text,
            rangeStart: reference.start,
            rangeEnd: reference.end,
          })),
          selected_data_tables: selectedDataTables,
          files: knowledgeFiles,
          plugins: [],
          selected_topic: selectedTopic
            ? {
                id: selectedTopic.id,
                code: selectedTopic.code,
                name: selectedTopic.name,
                sql: selectedTopic.sql,
                fields: formatTopicFields(selectedTopic.fields),
              }
            : null,
        },
      });
      if (analysisGeneration !== analysisGenerationRef.current || waitController.signal.aborted) return;
      const editStatuses = Object.entries(response.manual_edits ?? {})
        .map(([name, detail]) => `${name}=${detail.status ?? "unknown"}`)
        .join("，");
      const backendPlan = `${appendMetricReferences(formatBackendPlan(nextQuery, response.analysis_plan) || analysisPlan, nextQuery, availableMetrics)}
重跑说明：已创建第${response.revision ?? 1}次受治理执行${editStatuses ? `；人工修改状态：${editStatuses}` : ""}。`;
      const backendRows = mapBackendRows(response, nextQuery, selectedDataTables);
      const backendVisualTypes = visualTypesFromBackend(response, inferVisualTypes(`${nextQuery} ${analysisPlan}`, selectedDataTables), `${nextQuery} ${analysisPlan}`);
      const backendSummary =
        response.intelligent_analysis?.analysis_summary?.trim() ||
        response.conclusions?.filter((item) => item.trim()).join("\n") ||
        "后端未返回经复核的分析结论；不会由前端模板补写。";
      const backendSql = sqlScriptFromBackend(response);
      const backendPython = pythonScriptFromBackend(response);
      setAnalysisError(modelInvocationIssue(response, routedModel));
      setAnalysisTaskId(response.task_id);
      setVisualTypes(backendVisualTypes);
      setAnalysisPlan(backendPlan);
      setAnalysisRows(backendRows);
      setAnalysisSummary(backendSummary);
      setAnalysisScenarios(formatMetricScenarios(response));
      setSqlScript(backendSql);
      setPythonScript(backendPython);
      setResultMode("visual");
      partialAnalysisResponseRef.current = response;
      const resolvedTables = resolveVisualAnalysisTables(response.asset_context?.selected_data_tables, selectedDataTables);
      if (resolvedTables.length) setSelectedDataTables(resolvedTables);
      rememberTopicRound(nextQuery, response, resolvedTables.length ? resolvedTables : selectedDataTables, backendRows);
      setSaveMessage("已重跑");
      addConversationTurn(
        makeConversationTurn("assistant", backendSummary, {
          query: nextQuery,
          summary: backendSummary,
          sql: backendSql,
          analysisPlan: backendPlan,
        }),
      );
    } catch (error) {
      if (analysisGeneration !== analysisGenerationRef.current) return;
      if (isAnalysisNavigationAbort(error)) return;
      let partial = partialAnalysisResponseRef.current;
      if (!partial && partialAnalysisTaskIdRef.current) {
        try { partial = await fetchAnalysisTask({ taskId: partialAnalysisTaskIdRef.current, tenantId, userId }); } catch { partial = null; }
        if (analysisGeneration !== analysisGenerationRef.current) return;
      }
      const partialRows = partial ? mapBackendRows(partial, nextQuery, selectedDataTables) : [];
      if (partial && partialRows.length) {
        setAnalysisTaskId(partial.task_id);
        setAnalysisRows(partialRows);
        setAnalysisSummary(`重跑已完成数据查询并保留 ${partialRows.length} 行结果；智能结论阶段暂未完成。`);
        setAnalysisScenarios("重跑数据已返回；模型结论阶段未完成，不影响查看数据与可视化。");
        setAnalysisError(`重跑数据与可视化已保留；智能结论阶段在自动重试后仍未完成。${error instanceof Error ? error.message : ""}`);
        setResultMode("visual");
      } else {
        setAnalysisRows([]);
        setAnalysisSummary("重跑未返回可用数据，请检查 API 服务、数据源连接或当前角色的数据权限。");
        setAnalysisScenarios("重跑的数据查询阶段未返回结果。");
        setAnalysisError(error instanceof Error ? error.message : "后端分析服务暂不可用。");
      }
    } finally {
      if (analysisGeneration !== analysisGenerationRef.current || waitController.signal.aborted) return;
      clearPendingAnalysisRun(tenantId, userId, trackedRunId || undefined);
      if (analysisWaitAbortRef.current === waitController) analysisWaitAbortRef.current = null;
      activeAnalysisRunIdRef.current = "";
      setIsAnalyzing(false);
      setAnalysisSubmissionPhase("idle");
      isAnalyzingRef.current = false;
      window.setTimeout(() => realtimeVoiceDrainQueueRef.current(), 0);
    }
  };
  const cancelActiveAnalysis = async () => {
    const runId = activeAnalysisRunIdRef.current;
    if (!runId) return;
    setAnalysisError("正在取消分析执行...");
    try {
      await cancelAsyncAnalysisRun({ runId, tenantId, userId });
      setAnalysisError("分析执行已取消；未产生可发布结果。")
    } catch (error) {
      setAnalysisError(apiErrorMessage(error, "分析取消失败"));
    }
  };
  const restoreInitialAnalysisWorkspace = () => {
    void topicPrecipitation.flush();
    const runId = activeAnalysisRunIdRef.current || loadPendingAnalysisRun(tenantId, userId)?.runId || "";
    analysisGenerationRef.current += 1;
    analysisWaitAbortRef.current?.abort();
    analysisWaitAbortRef.current = null;
    activeAnalysisRunIdRef.current = "";
    partialAnalysisTaskIdRef.current = "";
    partialAnalysisResponseRef.current = null;
    isAnalyzingRef.current = false;
    setAnalysisSubmissionPhase("idle");
    clearPendingAnalysisRun(tenantId, userId);
    clearSelfAnalysisWorkbenchPersistence(tenantId, userId);
    if (runId) void cancelAsyncAnalysisRun({ runId, tenantId, userId }).catch(() => undefined);

    if (typeof window !== "undefined") {
      const currentStateKey = analysisTaskId || query;
      for (const card of visualCards) {
        sessionStorage.removeItem(`sda:visual-card:v2:${window.location.pathname}:current:${currentStateKey}:${card.id}`);
      }
    }

    cleanupRealtimeVoiceConnection(true);
    resetFunAsrTranscriptState("");
    queryLatestRef.current = "";
    visualCardsTaskRef.current = "";
    setQuery("");
    setAnalysisMenuOpen(false);
    setSelectedModeSkill(null);
    setSelectedSceneSkill(null);
    setSelectedTopicSkill(null);
    setDismissedAutoSkillIds(new Set());
    setKnowledgeFiles([]);
    setSelectedDataTables([]);
    setDataTablePickerOpen(false);
    setSelectedTopic(null);
    setConversationTurns([]);
    setShowResult(false);
    setAnalysisPlan("");
    setAnalysisRows([]);
    setAnalysisSummary("");
    setAnalysisScenarios("本次第一阶段规划尚未生成指标表现情景。");
    setAnalysisError("");
    setAnalysisProgressSteps([]);
    setIsAnalyzing(false);
    setAnalysisTaskId("");
    setResultMode("visual");
    setSaveMessage("");
    setVisualTypes({ primary: "column", secondary: "table" });
    setVisualCards(defaultVisualizationCards({ primary: "column", secondary: "table" }));
    setScriptEditorOpen(false);
    setActiveScriptTab("sql");
    setScriptPlanName("经营分析思路");
    setSqlScript("-- 尚未执行分析，暂无已执行 SQL。");
    setPythonScript("# 尚未执行分析，暂无已执行 Python 脚本。");
    setVoiceOpen(false);
    setVoiceListening(false);
    setVoiceTranscript("");
    setVoiceError("");
    setRealtimeVoiceListening(false);
    setRealtimeVoiceError("");
    setRealtimeVoiceQueueLength(0);
    setRealtimeVoiceIgnoredSpeakerSegments(0);
    setVoiceprintStatus("idle");
    setAnalysisInputCollapsed(false);
    setActiveMetricPreset(null);
    setMetricPresetFlashing(false);
    setExecutionHistoryOpen(false);
    setExpandedExecutionTaskId("");
    setExecutionTraceSpans([]);
    window.setTimeout(() => queryInputRef.current?.focus(), 0);
  };
  const runConfiguredAnalysisShortcut = (topic: AnalysisTopicShortcut) => {
    const boundSkills = (topic.skillIds || [])
      .map((skillId) => availableAnalysisSkills.find((skill) => skill.id === skillId))
      .filter((skill): skill is AnalysisSkillOption => Boolean(skill));
    const scene = boundSkills.find((skill) => skill.category === "场景") || null;
    const analysisTopic = boundSkills.find((skill) => skill.category === "主题") || null;
    if (scene) setSelectedSceneSkill(scene);
    if (analysisTopic) setSelectedTopicSkill(analysisTopic);
    const shortcutTables = (topic.tableIds || [])
      .map((tableId) => availableTopicTables.find((table) => table.id === tableId))
      .filter((table): table is TopicTableAsset => Boolean(table));
    const tableSelections = shortcutTables.map(topicTableToSelection);
    if (tableSelections.length) setSelectedDataTables(tableSelections);
    void restoreTopicDataReference(
      { reference_type: "shortcut", reference_id: topic.id },
      { fallbackQuery: topic.query, fallbackVisualTypes: inferVisualTypes(topic.query, tableSelections) },
    ).catch(() => {
      void handleQuery(
        topic.query,
        shortcutTables[0],
        "manual",
        boundSkills,
        tableSelections.length ? tableSelections : undefined,
        topic.memoryIds || [],
        { type: "shortcut", id: topic.id },
      );
    });
  };
  const rowsFromTopicSnapshot = (rows: Array<Record<string, string>>, manifest: Record<string, unknown>): AnalysisRow[] => {
    if (!rows.length) return [];
    const first = rows[0];
    const metricField = Object.keys(first).find((field) => Number.isFinite(Number(first[field]))) || Object.keys(first)[0] || "value";
    const dimensionField = Object.keys(first).find((field) => field !== metricField) || metricField;
    const schemaMapping = manifest.schema_mapping && typeof manifest.schema_mapping === "object" ? manifest.schema_mapping as Record<string, unknown> : {};
    const fieldLabels = schemaMapping.field_labels && typeof schemaMapping.field_labels === "object"
      ? Object.fromEntries(Object.entries(schemaMapping.field_labels as Record<string, unknown>).map(([field, label]) => [field, String(label || field)]))
      : Object.assign({}, ...selectedDataTables.map((table) => table.fieldLabels || {}));
    const fieldMetadata = Object.assign({}, ...selectedDataTables.map((table) => table.fieldMetadata || {}));
    return rows.slice(0, 200).map((raw, index) => ({
      branch: String(raw[dimensionField] || `第${index + 1}行`),
      productLine: String(raw.product_line || "—"),
      customerSegment: String(raw.customer_segment || "—"),
      amount: Number(raw[metricField]) || 0,
      metricName: metricField,
      metricUnit: "",
      fieldLabels,
      fieldMetadata,
      raw,
      completion: String(raw.completion_rate || raw.balance_completion_rate || "—"),
      conversion: String(raw.conversion_rate || "—"),
      overdueRate: String(raw.m1_overdue_rate || "—"),
      weekChange: String(raw.week_change || raw.weekly_net_increase || "—"),
    }));
  };
  const restoreTopicDataReference = async (
    reference: Pick<TopicDataReference, "reference_type" | "reference_id">,
    options: { fallbackQuery: string; fallbackVisualTypes?: Record<ResultVisualKey, VisualizationType> },
  ) => {
    const snapshot = await fetchTopicData({
      tenantId,
      userId,
      referenceType: reference.reference_type,
      referenceId: reference.reference_id,
      dataType: "data",
    });
    const manifest = snapshot.manifest as Record<string, unknown>;
    const restoredQuery = String(manifest.question || options.fallbackQuery || "历史分析");
    let restoredRows = rowsFromTopicSnapshot(snapshot.rows, manifest);
    const snapshotTaskId = String(manifest.task_id || "");
    let restoredTables = selectedDataTables;
    if (snapshotTaskId) {
      try {
        const task = await fetchAnalysisTask({ taskId: snapshotTaskId, tenantId, userId });
        const taskTables = Array.isArray(task.asset_context?.selected_data_tables)
          ? task.asset_context.selected_data_tables.map(backendTableToSelection).filter((table): table is AnalysisDataTableSelection => Boolean(table))
          : [];
        if (taskTables.length) {
          restoredTables = taskTables;
          setSelectedDataTables(taskTables);
        }
        const taskRows = mapBackendRows(task, restoredQuery, restoredTables);
        if (taskRows.length) restoredRows = taskRows;
      } catch {
        // Topic_Data remains the authoritative fallback for retained reports.
      }
    }
    setQuery(restoredQuery);
    setScriptPlanName(restoredQuery);
    setAnalysisTaskId(snapshotTaskId || (reference.reference_type === "history" ? reference.reference_id : ""));
    setAnalysisPlan(
      typeof manifest.analysis_plan === "string"
        ? manifest.analysis_plan
        : manifest.analysis_plan && typeof manifest.analysis_plan === "object"
          ? JSON.stringify(manifest.analysis_plan, null, 2)
          : `已复用 Topic_Data 最新快照 · ${snapshot.row_count} 行数据。`,
    );
    setAnalysisRows(restoredRows);
    setAnalysisSummary(String(manifest.summary || "该结果已从 Topic_Data 最新快照恢复。"));
    setSqlScript(String(manifest.sql || "-- 当前 Topic_Data 快照未保存 SQL。"));
    setPythonScript(String(manifest.python_script || "# 当前 Topic_Data 快照未保存 Python 脚本。"));
    setVisualTypes(options.fallbackVisualTypes || inferVisualTypes(restoredQuery, restoredTables));
    setAnalysisError("");
    setResultMode("visual");
    setShowResult(true);
  };
  const openSavedReport = async (result: SavedAnalysisResult) => {
    const reference = result.topicData || (result.analysisTaskId ? { reference_type: "history" as const, reference_id: result.analysisTaskId } : null);
    if (!reference) {
      setReportActionError("该报告缺少可读取的数据快照。");
      return;
    }
    if (expandedReportId === result.id) {
      setExpandedReportId("");
      return;
    }
    setReportActionError("");
    setReportActionNotice("");
    setExpandedReportId(result.id);
    setReportLoadingId(result.id);
    try {
      visualCardsTaskRef.current = result.analysisTaskId;
      setVisualCards(reportVisualizationsFor(result));
      const savedTables = (result.selectedDataTables || []).filter((table): table is AnalysisDataTableSelection => (
        Boolean(table) && typeof table === "object" &&
        typeof (table as AnalysisDataTableSelection).id === "string" &&
        typeof (table as AnalysisDataTableSelection).code === "string"
      ));
      if (savedTables.length) setSelectedDataTables(savedTables);
      await restoreTopicDataReference(reference, { fallbackQuery: result.query, fallbackVisualTypes: result.visualTypes as Record<ResultVisualKey, VisualizationType> });
    } catch (error) {
      setReportActionError(apiErrorMessage(error, "报告数据读取失败"));
    } finally {
      setReportLoadingId("");
    }
  };
  const saveReportTitle = async (result: SavedAnalysisResult) => {
    const title = reportTitleDraft.trim();
    if (!title) {
      setReportActionError("报告名称不能为空。");
      return;
    }
    try {
      const response = await saveSavedAnalysisResult({ tenantId, userId, result: { ...result, title } });
      const saved = response.result as SavedAnalysisResult;
      setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? saved : item));
      setEditingReportId(null);
      setReportActionError("");
    } catch (error) {
      setReportActionError(apiErrorMessage(error, "报告名称保存失败"));
    }
  };
  const deleteSavedReport = async (result: SavedAnalysisResult) => {
    if (!(await askConfirm({ title: "删除报告", description: `确定删除报告「${result.title || result.query}」？`, hint: "此操作不可撤销。" }))) return;
    try {
      await deleteSavedAnalysisResult({ tenantId, userId, resultId: result.id });
      setSavedAnalysisResults((current) => current.filter((item) => item.id !== result.id));
      featuredReports.remove("analysis", result.id);
      if (expandedReportId === result.id) setExpandedReportId("");
      setReportActionError("");
    } catch (error) {
      setReportActionError(apiErrorMessage(error, "报告删除失败"));
    }
  };
  const saveSavedReportToWeekly = async (result: SavedAnalysisResult) => {
    setReportActionLoadingId(`${result.id}:weekly`);
    setReportActionError("");
    setReportActionNotice("");
    try {
      const response = await saveAnalysisResultToWeeklyReport({ tenantId, userId, resultId: result.id });
      const saved = response.result as SavedAnalysisResult;
      setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? saved : item));
      window.dispatchEvent(new CustomEvent("smart-data-agent-analysis-saved", { detail: saved }));
      setReportActionNotice("已存入经营周报的分析模块下拉框；在周报页面勾选后即可展示。");
    } catch (error) {
      setReportActionError(apiErrorMessage(error, "存周报失败"));
    } finally {
      setReportActionLoadingId("");
    }
  };
  const saveSavedReportAsExperience = async (result: SavedAnalysisResult) => {
    setReportActionLoadingId(`${result.id}:experience`);
    setReportActionError("");
    setReportActionNotice("");
    try {
      const response = await saveAnalysisResultAsExperience({ tenantId, userId, resultId: result.id });
      setReportActionNotice(response.message || "已固化为当前账号的经验记忆候选；复核通过后可用于后续提炼与召回。");
    } catch (error) {
      setReportActionError(apiErrorMessage(error, "存经验失败"));
    } finally {
      setReportActionLoadingId("");
    }
  };
  const saveAnalysisResult = async (saveToWeekly = false) => {
    if (!analysisTaskId) {
      setSaveMessage("请先完成一次分析后再保存。");
      return;
    }
    const title = query || "未命名分析结果";
    const result: SavedAnalysisResult = {
      id: `analysis_${Date.now()}`,
      title,
      query: title,
      plan: analysisPlan,
      summary: analysisSummary || "服务端未返回经复核的结论",
      visualTypes,
      visualizations: visualCards.map((card) => ({ id: card.id, key: card.key, title: card.title, type: card.type, config: card.config })),
      savedAt: new Date().toLocaleString("zh-CN", { hour12: false }),
      rows: [],
      analysisTaskId,
      sql: sqlScript,
      pythonScript,
      analysisScenarios,
      selectedDataTables,
      visibility: "private",
      analysisInstitution: detectedAnalysisInstitution(knowledgeFiles, selectedInstitution),
      currentInstitution: selectedInstitution,
      uploadedDataInstitutions: Array.from(new Set(knowledgeFiles.flatMap((file) => file.detectedInstitutions || detectAttachmentInstitutions(file.name, file.contentPreview || "")))),
    };
    setSaveMessage("保存中...");
    try {
      const response = await saveSavedAnalysisResult({ tenantId, userId, result });
      const saved = saveToWeekly
        ? (await saveAnalysisResultToWeeklyReport({ tenantId, userId, resultId: response.result.id })).result as SavedAnalysisResult
        : response.result as SavedAnalysisResult;
      setSavedAnalysisResults((current) => [saved, ...current.filter((item) => item.id !== saved.id)].slice(0, 50));
      window.dispatchEvent(new CustomEvent("smart-data-agent-analysis-saved", { detail: saved }));
      setSaveMessage(saveToWeekly ? "已保存到我的报表「智能分析」和经营周报，数据、结论、图表配置与脚本已关联 Topic_Data 最新快照。" : "已保存到我的报表「智能分析」。问题、分析结果和当前图表配置已完整保留，请到该页签查看，而不是可视化报表。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        const nextResults = [result, ...loadSavedAnalysisResults()].slice(0, 12);
        window.localStorage.setItem(savedAnalysisStorageKey, JSON.stringify(nextResults));
        setSavedAnalysisResults(nextResults);
        window.dispatchEvent(new CustomEvent("smart-data-agent-analysis-saved", { detail: result }));
        setSaveMessage(`已保存到 demo 本地缓存，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setSaveMessage(apiErrorMessage(error, "分析结果保存失败，请稍后重试。"));
    }
  };
  const downloadAnalysisRows = async () => {
    downloadCsv("自助分析原始数据.csv", analysisRows);
  };
  const saveAsAnalysisExperience = async () => {
    const title = scriptPlanName || query || "智能分析经验";
    const experience = {
      id: `exp_${Date.now()}`,
      name: title,
      memoryTopic: selectedTopic?.code || query || title,
      relatedTopic: selectedTopic?.code || "",
      relatedIntent: selectedTopic?.relatedIntent || "智能分析沉淀",
      steps: analysisPlan,
      metrics: availableMetrics.slice(0, 5).map((metric) => metric.metricName).join(", "),
      rules: "先按主题 SQL 返回数据，再用 Python 可视化核验，最后基于真实数据形成总结。",
      commonConclusions: analysisSummary,
      riskTips: "结论必须以返回数据为依据，样本量不足时只输出风险提示。",
      summaryTemplate: "核心结论 / 主要异常 / 关键原因 / 数据证据 / 经营建议 / 风险提示 / 后续跟进动作",
      institutionScope: selectedInstitution,
      enabled: true,
      sourceVersionId: analysisTaskId,
      evidence: `analysis_task:${analysisTaskId}`,
      updatedAt: new Date().toLocaleString("zh-CN", { hour12: false }),
    };
    setSaveMessage("保存分析经验中...");
    try {
      await saveDataAssetItem({ tenantId, itemType: "analysis_experience", item: experience });
      setSaveMessage("分析经验已提交复核。");
    } catch (error) {
      setSaveMessage(apiErrorMessage(error, "分析经验保存失败，请稍后重试。"));
    }
  };
  const handleSaveTarget = (target: SaveTarget) => {
    if (target === "experience") {
      void saveAsAnalysisExperience();
      return;
    }
    void saveAnalysisResult(target === "report");
  };
  const setFunAsrListening = (target: FunAsrInputTarget, listening: boolean) => {
    if (target === "voice") {
      setVoiceListening(listening);
      return;
    }
    setRealtimeVoiceListening(listening);
  };
  const setFunAsrError = (target: FunAsrInputTarget, message: string) => {
    if (target === "voice") {
      setVoiceError(message);
      return;
    }
    setRealtimeVoiceError(message);
  };
  const resetFunAsrTranscriptState = (baseText: string) => {
    realtimeVoiceBaseRef.current = baseText;
    realtimeVoiceFinalRef.current = "";
    realtimeVoiceDraftRef.current = "";
    realtimeVoiceRenderedRef.current = baseText;
  };
  const syncFunAsrManualEdit = (target: FunAsrInputTarget, value: string) => {
    if (funAsrInputTargetRef.current !== target || value === realtimeVoiceRenderedRef.current) return;
    resetFunAsrTranscriptState(value);
    const socket = funAsrSocketRef.current;
    if (socket?.readyState !== WebSocket.OPEN) return;
    const nextReferences = buildQuerySkillReferences(value, dismissedAutoSkillIds, availableAnalysisSkills);
    socket.send(
      JSON.stringify({
        type: "context",
        context: buildFunAsrContext(
          [...conversationTurns, makeConversationTurn("user", value, { query: value })],
          uniqueSkills([...selectedManualSkills, ...nextReferences.map((reference) => reference.skill)]),
        ),
      }),
    );
  };
  const startFunAsrInput = async (
    target: FunAsrInputTarget,
    baseText: string,
    options: { preserveSpeakerProfile?: boolean } = {},
  ) => {
    setFunAsrError(target, "");
    const speechApplicationModule = speechApplicationModuleForTarget(target);
    let activeFunAsrIntegration = funAsrIntegrationByModuleRef.current[speechApplicationModule] || null;
    try {
      const runtime = await fetchAnalysisRuntimeConfig({ tenantId, userId, speechApplicationModule });
      activeFunAsrIntegration = runtime.speechIntegration;
      funAsrIntegrationByModuleRef.current[speechApplicationModule] = runtime.speechIntegration;
      setFunAsrIntegration(runtime.speechIntegration);
      if (runtime.models.length) {
        setAvailableModels(runtime.models);
        const analysisModels = modelsForModule(runtime.models, "intelligent_analysis_reasoning");
        setSelectedModel((current) => current && hasSelectableAnalysisModel(analysisModels, current) ? current : firstSelectableAnalysisModel(analysisModels));
      }
    } catch (error) {
      activeFunAsrIntegration = funAsrIntegrationByModuleRef.current[speechApplicationModule] || null;
      if (!activeFunAsrIntegration) {
        setFunAsrError(target, apiErrorMessage(error, "语音模型运行配置加载失败，请稍后重试。"));
      }
    }
    if (!activeFunAsrIntegration) {
      setFunAsrListening(target, false);
      setFunAsrError(target, "当前机构没有已启用的阿里云 Fun-ASR 接入。请在系统配置 → 模型接入管理 → 语音转文字中保存配置；无需连通性测试。");
      if (target === "query") queryInputRef.current?.focus();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setFunAsrListening(target, false);
      setFunAsrError(target, "当前浏览器不支持实时麦克风采集，可继续直接输入。");
      if (target === "query") queryInputRef.current?.focus();
      return;
    }
    cleanupRealtimeVoiceConnection(false);
    funAsrInputTargetRef.current = target;
    setRealtimeVoiceListening(target === "query");
    setVoiceListening(target === "voice");
    if (target === "query") setVoiceOpen(false);
    resetFunAsrTranscriptState(baseText);
    if (!options.preserveSpeakerProfile) {
      realtimeVoiceSpeakerGateRef.current = createRealtimeSpeakerGateState();
      realtimeVoiceIgnoredSpeakerSegmentsRef.current = 0;
      setRealtimeVoiceIgnoredSpeakerSegments(0);
      setVoiceprintStatus("calibrating");
      realtimeVoiceReconnectAttemptsRef.current = 0;
    }
    realtimeVoiceActiveRef.current = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (!realtimeVoiceActiveRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      realtimeVoiceStreamRef.current = stream;
      const socket = new WebSocket(buildFunAsrRealtimeUrl(tenantId, userId, speechApplicationModule));
      funAsrSocketRef.current = socket;
      socket.onopen = () => {
        if (!realtimeVoiceActiveRef.current) return;
        const targetReferences = buildQuerySkillReferences(baseText, dismissedAutoSkillIds, availableAnalysisSkills);
        const activeSkills = uniqueSkills([
          ...selectedManualSkills,
          ...targetReferences.map((reference) => reference.skill),
        ]);
        socket.send(
          JSON.stringify({
            type: "start",
            provider: "aliyun_fun_asr",
            speechIntegrationId: activeFunAsrIntegration.id,
            applicationModule: speechApplicationModule,
            sampleRate: funAsrSampleRate,
            context: buildFunAsrContext(
              baseText.trim()
                ? [...conversationTurns, makeConversationTurn("user", baseText, { query: baseText })]
                : conversationTurns,
              activeSkills,
            ),
          }),
        );
      };
      socket.onmessage = (event) => {
        if (!realtimeVoiceActiveRef.current) return;
        let payload: FunAsrProxyEvent;
        try {
          payload = JSON.parse(String(event.data)) as FunAsrProxyEvent;
        } catch {
          return;
        }
        if (payload.type === "ready") {
          realtimeVoiceReconnectAttemptsRef.current = 0;
          setFunAsrError(target, "");
          void startRealtimeAudioStream(socket, stream).catch((error) => {
            setFunAsrError(target, apiErrorMessage(error, "实时音频采集失败，可继续直接输入。"));
            stopRealtimeVoiceInput();
          });
          return;
        }
        if (payload.type === "config") {
          if (payload.provider !== "aliyun_fun_asr") {
            setFunAsrError(target, "语音入口未连接阿里云 Fun-ASR，已停止本次录音。");
            stopRealtimeVoiceInput();
          }
          return;
        }
        if (payload.type === "transcript") {
          applyFunAsrTranscript(payload.text || "", Boolean(payload.final));
          return;
        }
        if (payload.type === "error") {
          setFunAsrError(target, funAsrErrorMessage(payload.message || ""));
          stopRealtimeVoiceInput();
          return;
        }
        if (payload.type === "finished") {
          if (target === "query" && realtimeVoiceActiveRef.current) {
            // Aliyun ends a recognition task; keep listening by opening a new
            // task instead of treating this as a transport failure.
            realtimeVoiceExpectedCloseRef.current = "session_end";
            socket.close();
          } else {
            stopRealtimeVoiceInput();
          }
        }
      };
      socket.onerror = () => {
        if (!realtimeVoiceActiveRef.current) return;
        setFunAsrError(target, target === "query" ? "实时语音连接中断，正在自动重连…" : "实时语音连接失败，可继续直接输入。");
        socket.close();
      };
      socket.onclose = () => {
        if (!realtimeVoiceActiveRef.current) return;
        const expectedClose = realtimeVoiceExpectedCloseRef.current;
        realtimeVoiceExpectedCloseRef.current = "";
        // renderedRef is the current unsubmitted speech segment. It may be
        // intentionally empty after a 5-second auto-submit, so do not fall back
        // to the already executing query and accidentally enqueue it again.
        const continuationText = realtimeVoiceRenderedRef.current;
        realtimeVoiceDraftRef.current = "";
        cleanupRealtimeVoiceConnection(false);
        if (target !== "query") {
          setFunAsrListening(target, false);
          return;
        }
        setRealtimeVoiceListening(true);
        if (expectedClose !== "session_end") {
          setRealtimeVoiceError("实时语音连接中断，正在自动重连…");
        }
        const attempt = realtimeVoiceReconnectAttemptsRef.current + 1;
        realtimeVoiceReconnectAttemptsRef.current = attempt;
        const delay = expectedClose === "session_end" ? 0 : Math.min(10_000, 800 * 2 ** Math.min(attempt - 1, 4));
        realtimeVoiceReconnectTimerRef.current = window.setTimeout(() => {
          realtimeVoiceReconnectTimerRef.current = null;
          void startFunAsrInput("query", continuationText, { preserveSpeakerProfile: true });
        }, delay);
      };
      if (target === "query") queryInputRef.current?.focus();
      void runApplicationAction({
        tenantId,
        userId,
        moduleKey: "self_analysis",
        action: target === "voice" ? "start_voice_input_fun_asr" : "start_realtime_voice",
        payload: {
          sessionId: conversationSessionId || null,
          target,
          speechIntegrationId: activeFunAsrIntegration.id,
          speechIntegrationName: activeFunAsrIntegration.name,
          applicationModule: speechApplicationModule,
        },
      }).catch(() => undefined);
    } catch (error) {
      cleanupRealtimeVoiceConnection(false);
      setFunAsrListening(target, false);
      setFunAsrError(target, funAsrErrorMessage(apiErrorMessage(error, "实时语音未启动，可继续直接输入。")));
    }
  };
  const openVoiceInput = () => {
    const baseText = query;
    setVoiceOpen(true);
    setVoiceTranscript(baseText);
    setVoiceError("");
    void startFunAsrInput("voice", baseText);
  };
  const cancelVoiceInput = () => {
    if (funAsrInputTargetRef.current === "voice") stopRealtimeVoiceInput();
    setVoiceListening(false);
    setVoiceOpen(false);
    setVoiceError("");
  };
  const analyzeVoiceInput = () => {
    const nextQuery = voiceTranscript.trim();
    if (funAsrInputTargetRef.current === "voice") stopRealtimeVoiceInput();
    setVoiceListening(false);
    setVoiceOpen(false);
    setQuery(nextQuery);
    void handleQuery(nextQuery, undefined, "popup_voice");
  };
  const stopRealtimeVoiceInput = (options?: { runAfterStop?: boolean }) => {
    const target = funAsrInputTargetRef.current;
    const latestText = target === "voice" ? voiceTranscript : query;
    cleanupRealtimeVoiceConnection(true);
    setRealtimeVoiceListening(false);
    setVoiceListening(false);
    setVoiceprintStatus("idle");
    realtimeVoiceReconnectAttemptsRef.current = 0;
    realtimeVoiceExpectedCloseRef.current = "";
    realtimeVoiceSpeakerGateRef.current = createRealtimeSpeakerGateState();
    realtimeVoiceIgnoredSpeakerSegmentsRef.current = 0;
    setRealtimeVoiceIgnoredSpeakerSegments(0);
    realtimeVoiceQueueRef.current = [];
    setRealtimeVoiceQueueLength(0);
    realtimeVoiceDraftRef.current = "";
    realtimeVoiceBaseRef.current = latestText;
    realtimeVoiceRenderedRef.current = latestText;
    if (options?.runAfterStop && target === "query") {
      window.setTimeout(() => void rerunAnalysis(), 0);
    }
  };
  const toggleRealtimeVoiceInput = () => {
    if (realtimeVoiceListening && funAsrInputTargetRef.current === "query") {
      stopRealtimeVoiceInput({ runAfterStop: analysisInputCollapsed && showResult });
      return;
    }
    void startFunAsrInput("query", query);
  };
  const toggleExecutionHistory = async () => {
    if (executionHistoryOpen) {
      setExecutionHistoryOpen(false);
      return;
    }
    setExecutionHistoryOpen(true);
    setExecutionHistoryLoading(true);
    try {
      const response = await fetchAnalysisHistory({ tenantId, userId, limit: 50 });
      setExecutionHistoryTasks(response.tasks);
    } catch (error) {
      setAnalysisError(apiErrorMessage(error, "执行记录加载失败"));
    } finally {
      setExecutionHistoryLoading(false);
    }
  };
  const viewExecution = (task: BackendAnalysisResponse) => {
    const restoredQuery = task.question || "历史分析";
    void topicPrecipitation.prepareQuestionSwitch(restoredQuery);
    setQuery(restoredQuery);
    setAnalysisTaskId(task.task_id);
    setAnalysisPlan(formatBackendPlan(restoredQuery, task.analysis_plan) || "历史执行未保存分析计划。");
    const historyTables = resolveVisualAnalysisTables(task.asset_context?.selected_data_tables, selectedDataTables);
    if (historyTables.length) setSelectedDataTables(historyTables);
    setAnalysisRows(mapBackendRows(task, restoredQuery, historyTables.length ? historyTables : selectedDataTables));
    setAnalysisSummary(
      task.intelligent_analysis?.analysis_summary?.trim()
        || task.conclusions?.filter(Boolean).join("\n")
        || "历史执行未返回分析总结。",
    );
    setSqlScript(sqlScriptFromBackend(task));
    setPythonScript(pythonScriptFromBackend(task));
    setAnalysisScenarios(formatMetricScenarios(task));
    setAnalysisProgressSteps(completedProgressSteps(task));
    setShowResult(true);
    setResultMode("visual");
    setExecutionHistoryOpen(false);
    rememberTopicRound(restoredQuery, task, historyTables.length ? historyTables : selectedDataTables, mapBackendRows(task, restoredQuery, historyTables.length ? historyTables : selectedDataTables));
  };
  const toggleExecutionDetails = async (task: BackendAnalysisResponse) => {
    if (expandedExecutionTaskId === task.task_id) {
      setExpandedExecutionTaskId("");
      setExecutionTraceSpans([]);
      return;
    }
    setExpandedExecutionTaskId(task.task_id);
    setExecutionTraceSpans([]);
    try {
      const response = await fetchAnalysisHistoryDetail({ tenantId, userId, taskId: task.task_id });
      setExecutionTraceSpans(response.spans);
    } catch (error) {
      setAnalysisError(apiErrorMessage(error, "执行详情加载失败"));
    }
  };
  const deleteExecution = async (task: BackendAnalysisResponse) => {
    if (!(await askConfirm({ title: "删除执行记录", description: `确定删除「${task.question || "未命名分析问题"}」这条执行记录？`, hint: "此操作不可撤销。" }))) return;
    try {
      await deleteAnalysisHistoryTask({ tenantId, userId, taskId: task.task_id });
      setExecutionHistoryTasks((current) => current.filter((item) => item.task_id !== task.task_id));
      if (expandedExecutionTaskId === task.task_id) {
        setExpandedExecutionTaskId("");
        setExecutionTraceSpans([]);
      }
      if (analysisTaskId === task.task_id) {
        setAnalysisTaskId("");
        setSaveMessage("当前展示结果的执行记录已删除；如需继续修改，请重新发起分析。");
      }
    } catch (error) {
      setAnalysisError(apiErrorMessage(error, "执行记录删除失败"));
    }
  };
  const activeSubmissionPhase: AnalysisSubmissionPhase = isAnalyzing
    ? analysisSubmissionPhase === "idle" ? "running" : analysisSubmissionPhase
    : "idle";
  const analysisSubmissionStatus = activeSubmissionPhase === "submitting"
    ? "已提交，正在启动"
    : activeSubmissionPhase === "queued"
      ? "已进入分析队列"
      : activeSubmissionPhase === "running"
        ? "大模型正在执行"
        : "";
  return (
    <div className="p-7">
      <div className="mb-7 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">{activeView === "reports" ? "我的报表" : "智能分析"}</h2>
          <p className="text-[13px] text-[#aeaeb2] mt-1">{activeView === "reports" ? "精选报表 · 智能分析报表 · 可视化报表" : "自然语言查询 · AI自动生成图表 · 智能归因分析"}</p>
        </div>
        <div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true">{activeView === "query" ? <><button type="button" onClick={restoreInitialAnalysisWorkspace} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] transition hover:bg-[#f2f2f7]" data-self-analysis-restore="true"><RotateCcw className="h-3.5 w-3.5" />恢复</button><button type="button" onClick={() => void toggleExecutionHistory()} className={`inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-[12px] transition ${executionHistoryOpen ? "border-[#d1d1d6] bg-[#f2f2f7] text-[#1d1d1f]" : "border-[#e5e5ea] bg-white text-[#3a3a3c] hover:bg-[#f2f2f7]"}`}><History className="h-3.5 w-3.5" />执行记录</button></> : null}</div>
      </div>
      {activeView === "query" && (
        <>
          {/* Search Bar */}
          <div className={`rounded-xl border border-[#f0f0f2] bg-white transition-all ${analysisInputCollapsed ? "mb-3 p-2.5" : "mb-6 p-5"}`}>
            <div className="flex">
              <div className="flex-1">
                {!analysisInputCollapsed && (knowledgeFiles.length > 0 || selectedDataTables.length > 0) && (
                  <div className="mb-2 flex flex-wrap gap-2">
                    {knowledgeFiles.map((file) => (
                      <span key={file.id} className="inline-flex max-w-[220px] items-center gap-1.5 rounded-md border border-[#e5e5ea] bg-[#fafbfc] px-2 py-1 text-[11px] text-[#636366]">
                        <Upload className="h-3 w-3 shrink-0 text-[#8a8a8e]" />
                        <span className="truncate">{file.name}</span>
                        {file.classification === "data_source" && <span className="shrink-0 text-[10px] text-[#258a3f]">数据源</span>}
                        {file.classification === "text_document" && <span className="shrink-0 text-[10px] text-[#636366]">文档</span>}
                        {file.detectedInstitutions?.length === 1 && (
                          <span className="shrink-0 rounded bg-[#eef4ff] px-1 py-0.5 text-[10px] text-[#2466b0]" title="仅用于提示，不会切换当前机构或扩大数据权限">
                            识别：{file.detectedInstitutions[0]}
                          </span>
                        )}
                        <button type="button" onClick={() => removeKnowledgeFile(file.id)} className="shrink-0 text-[#aeaeb2] hover:text-[#1d1d1f]">
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    {selectedDataTables.map((table) => (
                      <span key={table.id} className="inline-flex max-w-[260px] items-center gap-1.5 rounded-md border border-[#d7efd9] bg-[#eef8f1] px-2 py-1 text-[11px] text-[#258a3f]">
                        <Table2 className="h-3 w-3 shrink-0" />
                        <span className="shrink-0">{table.kind === "raw" ? "原始表" : "主题表"}</span>
                        <span className="truncate">{table.name}</span>
                        <button type="button" onClick={() => removeSelectedDataTable(table.id)} className="shrink-0 text-[#8a8a8e] hover:text-[#1d1d1f]">
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <div
                  className={`relative border border-[#d1d1d6] bg-white transition-colors focus-within:border-[#d1d1d6] ${
                    analysisInputCollapsed ? "rounded-2xl px-3 py-1.5 pr-[78px]" : "rounded-[22px] px-4 py-2"
                  }`}
                >
                  <div className={`relative ${analysisInputCollapsed ? "min-h-[24px]" : "min-h-[32px]"}`}>
                    <textarea
                      data-plain-query-input="true"
                      ref={queryInputRef}
                      value={query}
                      onChange={(e) => handleQueryChange(e.target.value)}
                      onPaste={handleQueryPaste}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          if (!isAnalyzing) void handleQuery();
                        }
                      }}
                      placeholder="用自然语言描述你想分析的问题，如：本月各分行放款金额排名..."
                      rows={1}
                      className={`w-full resize-none bg-transparent px-0 py-0 text-[13px] leading-[1.5] text-[#3a3a3c] outline-none placeholder:text-[#aeaeb2] focus:!outline-none focus:!shadow-none focus-visible:!outline-none focus-visible:!shadow-none ${
                        analysisInputCollapsed ? "h-6 min-h-[24px] overflow-hidden text-[#3a3a3c]" : "min-h-[32px]"
                      }`}
                    />
                  </div>
                  {analysisInputCollapsed ? (
                    <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setAnalysisInputCollapsed(false)}
                        className="flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                        aria-label="展开输入框"
                        title="展开输入框"
                      >
                        <ChevronsDown className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={toggleRealtimeVoiceInput}
                        className={`relative flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                          realtimeVoiceListening
                            ? "text-[#0a84ff]"
                            : "text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                        }`}
                        aria-label={realtimeVoiceListening ? "停止实时语音交互" : "实时语音交互"}
                        title={realtimeVoiceListening ? "停止实时语音交互" : "实时语音交互"}
                      >
                        {realtimeVoiceListening && (
                          <span className="absolute -inset-1 rounded-full bg-gradient-to-r from-[#34c759]/45 via-[#0a84ff]/45 to-[#af52de]/45 blur-sm animate-pulse" />
                        )}
                        <AudioLines className="relative z-10 h-4 w-4" />
                      </button>
                    </div>
                  ) : (
                    <div className="mt-1 flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <div ref={analysisMenuRef} className="relative shrink-0">
                          <button
                            type="button"
                            onClick={() => setAnalysisMenuOpen((open) => !open)}
                            className="flex h-7 w-7 items-center justify-center rounded-full text-[#636366] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                            aria-label="添加分析上下文"
                          >
                            <Plus className="h-4 w-4" />
                          </button>
                          {analysisMenuOpen && (
                            <AnalysisSkillMenu
                              skills={availableAnalysisSkills}
                              onUpload={() => {
                                setAnalysisMenuOpen(false);
                                fileInputRef.current?.click();
                              }}
                              onSelectDataTable={() => {
                                setAnalysisMenuOpen(false);
                                setDataTablePickerOpen(true);
                              }}
                              onSelectSkill={selectAnalysisSkill}
                            />
                          )}
                        </div>
                        <AnalysisModelSelector
                          models={modelsForModule(availableModels, "intelligent_analysis_reasoning")}
                          selectedModel={selectedModel}
                          onSelect={selectAnalysisModel}
                        />
                        {selectedManualSkills.map((skill) => (
                          <button
                            key={skill.category}
                            type="button"
                            onClick={() => clearAnalysisSkill(skill)}
                            className="inline-flex h-6 min-w-0 max-w-[190px] shrink items-center gap-1 rounded-full bg-[#f2f2f7] px-2.5 text-[12px] text-[#3a3a3c] hover:bg-[#e5e5ea]"
                            title={`${skill.category}：${skill.name}`}
                          >
                            <span className="truncate">{skill.name}</span>
                            <X className="h-3 w-3 shrink-0 text-[#aeaeb2]" />
                          </button>
                        ))}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setScriptEditorOpen(true)}
                          className="flex h-7 w-7 items-center justify-center rounded-full text-[#636366] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                          aria-label="脚本编辑"
                        >
                          <Code2 className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={openVoiceInput}
                          className="flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                          aria-label="语音录入"
                          title="语音录入"
                        >
                          <Mic className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => setAnalysisInputCollapsed(true)}
                          className="flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                          aria-label="折叠输入框"
                          title="折叠输入框"
                        >
                          <ChevronsUp className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={toggleRealtimeVoiceInput}
                          className={`relative flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                            realtimeVoiceListening
                              ? "text-[#0a84ff]"
                              : "text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                          }`}
                          aria-label={realtimeVoiceListening ? "停止实时语音交互" : "实时语音交互"}
                          title={realtimeVoiceListening ? "停止实时语音交互" : "实时语音交互"}
                        >
                          {realtimeVoiceListening && (
                            <span className="absolute -inset-1 rounded-full bg-gradient-to-r from-[#34c759]/45 via-[#0a84ff]/45 to-[#af52de]/45 blur-sm animate-pulse" />
                          )}
                          <AudioLines className="relative z-10 h-4 w-4" />
                        </button>
                        {analysisSubmissionStatus && (
                          <span
                            role="status"
                            aria-live="polite"
                            className="whitespace-nowrap text-[11px] font-medium leading-5 text-[#258a3f]"
                            data-analysis-submit-feedback={activeSubmissionPhase}
                          >
                            {analysisSubmissionStatus}
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => activeSubmissionPhase === "submitting" ? undefined : isAnalyzing ? void cancelActiveAnalysis() : void handleQuery()}
                          disabled={activeSubmissionPhase === "submitting"}
                          className={`flex h-8 w-8 items-center justify-center rounded-full text-white transition-all duration-150 ${
                            isAnalyzing
                              ? "bg-[#258a3f] shadow-[0_0_0_4px_rgba(37,138,63,0.14)] hover:bg-[#1f7a36]"
                              : "bg-[#8e8e93] hover:bg-[#636366]"
                          }`}
                          aria-label={activeSubmissionPhase === "submitting" ? "分析请求已提交" : isAnalyzing ? "取消分析" : "开始分析"}
                          data-analysis-submit-phase={activeSubmissionPhase}
                        >
                          {activeSubmissionPhase === "submitting" ? <Check className="h-4 w-4" /> : isAnalyzing ? <X className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                  )}
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(event) => void chooseFiles(event.target.files)}
                  />
                  {!analysisInputCollapsed && realtimeVoiceError && <div role="status" className="mt-1 text-[11px] text-[#9a6a00]">语音转文字提示：{realtimeVoiceError}</div>}
                  {!analysisInputCollapsed && !showResult && analysisError && (
                    <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 text-[11px] leading-5 text-[#d93025]">
                      <span>{analysisError}</span>
                      <button type="button" onClick={() => setDataTablePickerOpen(true)} className="text-[11px] font-normal leading-5 text-[#0a84ff] underline decoration-[#0a84ff]/45 underline-offset-2 hover:text-[#0071e3]">选择数据表</button>
                    </div>
                  )}
                  {!analysisInputCollapsed && realtimeVoiceListening && (
                    <div className="mt-1 text-[11px] text-[#0a84ff]">
                      实时语音持续在线 · {voiceprintStatus === "locked" ? "已锁定首位说话人音色" : "正在识别首位说话人音色"}
                      {realtimeVoiceIgnoredSpeakerSegments ? ` · 已过滤 ${realtimeVoiceIgnoredSpeakerSegments} 段其他说话人语音` : ""}
                      {realtimeVoiceQueueLength ? ` · 已排队 ${realtimeVoiceQueueLength} 条指令` : ""}
                    </div>
                  )}
                </div>
              </div>
            </div>
            {!analysisInputCollapsed && visibleAnalysisTopicShortcuts.length > 0 && (
              <div className="relative mt-3 min-h-7 lg:pr-[156px]">
                <AnalysisTopicShortcuts
                  topics={visibleAnalysisTopicShortcuts}
                  expanded={analysisTopicsExpanded}
                  editingId={editingTopicId}
                  menu={topicShortcutMenu}
                  onToggleExpanded={() => setAnalysisTopicsExpanded((expanded) => !expanded)}
                  onRunTopic={runConfiguredAnalysisShortcut}
                  onOpenMenu={setTopicShortcutMenu}
                  onRenameTopic={renameAnalysisTopicShortcut}
                  onFinishEditing={finishAnalysisTopicEditing}
                  onStartEditing={startAnalysisTopicEditing}
                  onDeleteTopic={hideAnalysisTopicShortcut}
                />
              </div>
            )}
            {!analysisInputCollapsed && metricPresetNotice && (
              <div role="status" className={`mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-5 ${metricPresetFlashing ? "animate-pulse" : ""}`}>
                <span className="text-[#d93025]">{metricPresetNotice}</span>
                {activeMetricPreset?.status === "suggestions" && activeMetricPreset.metrics.map((metric, index) => (
                  <span key={metric.metricId} className="inline-flex items-center">
                    <button
                      type="button"
                      onClick={() => {
                        setQuery((current) => current.includes(metric.metricName) ? current : `${current}${current ? "，" : ""}${metric.metricName}`);
                        window.setTimeout(() => queryInputRef.current?.focus(), 0);
                      }}
                      className="text-[11px] font-semibold leading-5 text-[#d93025] underline decoration-[#d93025]/45 underline-offset-2 hover:text-[#a61b13]"
                      title={metric.definition || metric.valueLogic || "指标字典未登记完整口径"}
                    >
                      {metric.metricName}
                    </button>
                    {index < activeMetricPreset.metrics.length - 1 ? "、" : ""}
                  </span>
                ))}
                {activeMetricPreset?.status === "suggestions" && <span className="text-[#d93025]">；或</span>}
                {activeMetricPreset?.status === "incomplete" && (
                  <Link
                    to="/data-assets/metrics"
                    className="text-[11px] font-normal leading-5 text-[#0a84ff] underline decoration-[#0a84ff]/45 underline-offset-2 hover:text-[#0071e3]"
                  >
                    查看指标配置
                  </Link>
                )}
                {!activeMetricPreset?.table && (
                  <button
                    type="button"
                    onClick={() => setDataTablePickerOpen(true)}
                    className="text-[11px] font-normal leading-5 text-[#0a84ff] underline decoration-[#0a84ff]/45 underline-offset-2 hover:text-[#0071e3]"
                  >
                    {activeMetricPreset?.status === "suggestions" ? "选择对应数据表" : "选择数据表"}
                  </button>
                )}
                {activeMetricPreset?.status === "suggestions" && <span className="text-[#d93025]">。</span>}
              </div>
            )}
          </div>
          {!showResult ? (
            <div className="grid grid-cols-3 gap-5">
              <div className="col-span-2 bg-white rounded-xl border border-[#f0f0f2] p-5">
                <div className="flex items-center gap-2 mb-4">
                  <History className="w-4 h-4 text-[#aeaeb2]" />
                  <h3 className="text-[13px] text-[#1d1d1f]">最近查询</h3>
                </div>
                <div className="space-y-1.5">
                  {recentSavedQueries.map((item) => (
                    <div key={item.id} onClick={() => void openSavedReport(item)}
                      className="flex items-center gap-3 p-3 bg-[#fafbfc] rounded-lg cursor-pointer hover:bg-[#f2f2f7] transition-colors">
                      <Clock className="w-3.5 h-3.5 text-[#c7c7cc] shrink-0" />
                      <span className="text-[12px] text-[#636366] flex-1">{item.query}</span>
                      <span className="text-[11px] text-[#c7c7cc]">{item.savedAt || "时间未记录"}</span>
                      <ArrowUpRight className="w-3.5 h-3.5 text-[#d1d1d6]" />
                    </div>
                  ))}
                  {!recentSavedQueries.length && (
                    <div className="rounded-lg bg-[#fafbfc] p-3 text-[11px] text-[#aeaeb2]">
                      {savedAnalysisLoadError || "暂无服务端已保存的分析查询"}
                    </div>
                  )}
                </div>
              </div>
              <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Lightbulb className="w-4 h-4 text-[#aeaeb2]" />
                  <h3 className="text-[13px] text-[#1d1d1f]">AI 推荐分析</h3>
                </div>
                <div className="space-y-2">
                  {visibleAnalysisTopicShortcuts.slice(0, 3).map((topic) => (
                    <div key={topic.id} onClick={() => runConfiguredAnalysisShortcut(topic)}
                      className="p-3 bg-[#fafbfc] rounded-lg cursor-pointer hover:bg-[#f2f2f7] transition-colors">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#aeaeb2]" />
                        <span className="text-[12px] text-[#1d1d1f]">{topic.title}</span>
                      </div>
                      <p className="text-[11px] text-[#aeaeb2] pl-3.5">{topic.query}</p>
                    </div>
                  ))}
                  {!visibleAnalysisTopicShortcuts.length && (
                    <div className="rounded-lg bg-[#fafbfc] p-3 text-[11px] text-[#aeaeb2]">
                      暂无分析配置，请先在“分析配置”中新增快捷入口
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
                <div className="mb-4 flex min-w-0 items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5 overflow-x-auto">
                    <div className="flex shrink-0 items-center gap-2">
                      <Sparkles className="h-4 w-4 shrink-0 text-[#aeaeb2]" />
                      <h3 className="whitespace-nowrap text-[13px] text-[#1d1d1f]">分析结果</h3>
                    </div>
                    <div className="flex shrink-0 gap-px rounded-md bg-[#f2f2f7] p-0.5">
                      {[
                        { key: "thinking", label: "思考链" },
                        { key: "data", label: "源数据" },
                        { key: "visual", label: "图表" },
                        { key: "summary", label: "AI总结" },
                      ].map((tab) => (
                        <button
                          key={tab.key}
                          type="button"
                          onClick={() => setResultMode(tab.key as ResultMode)}
                          className={`whitespace-nowrap rounded px-2 py-1 text-[11px] transition-all ${
                            resultMode === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#636366]"
                          }`}
                        >
                          {tab.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <div className="flex shrink-0 gap-px rounded-md bg-[#f2f2f7] p-0.5">
                      {[
                        { key: "mine" as const, label: "存报表" },
                        { key: "experience" as const, label: "存经验" },
                        { key: "report" as const, label: "存周报" },
                      ].map((action) => (
                        <button
                          key={action.key}
                          type="button"
                          onClick={() => handleSaveTarget(action.key)}
                          className="whitespace-nowrap rounded px-2 py-1 text-[11px] text-[#8a8a8e] transition-all hover:bg-white hover:text-[#1d1d1f] hover:shadow-sm"
                        >
                          {action.label}
                        </button>
                      ))}
                    </div>
                    <StickyNoteButton size="compact" onClick={analysisSticky.show} />
                    <button
                      onClick={() => void downloadAnalysisRows()}
                      className="flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-[11px] text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#636366]"
                    >
                      <Download className="w-3 h-3" /> 导出
                    </button>
                  </div>
                </div>
                {saveMessage && (
                  <div className={`mb-4 rounded-lg border px-3 py-2 text-[12px] ${isSelfAnalysisNoticeFailure(saveMessage) ? "border-[#f4d0d0] bg-[#fdeeee] text-[#c83a3a]" : "border-[#d7efd9] bg-[#eef8f1] text-[#258a3f]"}`}>
                    {saveMessage}
                  </div>
                )}
                {resultMode === "thinking" ? (
                  <AnalysisProgressPanel steps={analysisProgressSteps} running={isAnalyzing} error={analysisError} hasResult={analysisRows.length > 0} />
                ) : resultMode === "summary" ? (
                  <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
                    <div className="mb-2 flex items-center gap-2 text-[12px] text-[#1d1d1f]">
                      <Lightbulb className="w-3.5 h-3.5 text-[#aeaeb2]" />
                      AI总结
                      {isAnalyzing && <span className="text-[11px] text-[#aeaeb2]">后端分析中...</span>}
                      {analysisTaskId && <span className="text-[11px] text-[#aeaeb2]">任务 {analysisTaskId}</span>}
                    </div>
                    <textarea
                      value={analysisSummary}
                      onChange={(event) => setAnalysisSummary(event.target.value)}
                      placeholder="核心结论：&#10;主要异常：&#10;关键原因：&#10;数据证据：&#10;经营建议：&#10;风险提示：&#10;后续跟进动作："
                      className="min-h-[260px] w-full resize-y rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[12px] leading-[1.7] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
                    />
                    {analysisError && (
                      <p className={`mt-2 text-[11px] ${analysisRows.length ? "text-[#9a6a00]" : "text-[#d93025]"}`}>
                        {analysisRows.length ? "模型阶段提示：" : "后端服务未返回可用结果，未启用前端本地降级："}{analysisError}
                      </p>
                    )}
                  </div>
                ) : resultMode === "visual" && isAnalyzing && !analysisRows.length ? (
                  <AnalysisProgressPanel steps={analysisProgressSteps} running={isAnalyzing} error={analysisError} hasResult={analysisRows.length > 0} />
                ) : resultMode === "visual" ? (
                  <div className="space-y-3">
                    <StickyNotePanel
                      note={analysisSticky.note}
                      editing={analysisSticky.editing}
                      onChange={analysisSticky.updateItems}
                      onFinishEdit={analysisSticky.finishEdit}
                      onStartEdit={() => analysisSticky.setEditing(true)}
                      onHide={analysisSticky.hide}
                      uploadContext={analysisSticky.uploadContext}
                    />
                  {analysisRows.length ? (
                  <ResizableVisualizationGrid>
                    {visualCards.map((card) => <AnalysisVisualCard
                      key={card.id} id={card.id} stateKey={`current:${analysisTaskId || query}:${card.id}`} fillHeight visualGridSpan={card.config?.layoutSpan} visualGridHeight={card.config?.layoutHeight} visualGridMaxSpan={card.config?.maxLayoutSpan} visualGridMaxHeight={card.config?.maxLayoutHeight}
                      title={card.title}
                      type={card.type}
                      rows={analysisRows}
                      initialConfig={card.config}
                      analysisSource={boundChartTables}
                      onFollowUp={(detail) => revealVisualFollowUp({ key: card.key || "primary", title: card.title, type: card.type, rows: analysisRows, taskId: analysisTaskId, question: query, summary: analysisSummary, plan: analysisPlan, selectedDataTables: resolveVisualAnalysisTables(detail?.dataTables, boundChartTables), selectedText: detail?.selectedText })}
                      onComment={(detail) => revealVisualComment({ key: card.key || "primary", title: card.title, type: card.type, rows: analysisRows, taskId: analysisTaskId, question: query, summary: analysisSummary, plan: analysisPlan, selectedDataTables: resolveVisualAnalysisTables(detail?.dataTables, boundChartTables), selectedText: detail?.selectedText })}
                      onTypeChange={(nextType) => card.key ? updateVisualType(card.key, nextType) : updateVisualCard(card.id, { type: nextType })}
                      onTitleChange={(nextTitle) => updateVisualCard(card.id, { title: nextTitle })}
                      onConfigChange={(config) => updateVisualCard(card.id, { config })}
                      onDuplicate={(config, options) => duplicateVisualCard(card.id, config, options)}
                      onDelete={() => deleteVisualCard(card.id)}
                    />)}
                  </ResizableVisualizationGrid>
                  ) : null}
                  </div>
                ) : (
                  <RawDataTable rows={analysisRows} onDownload={() => void downloadAnalysisRows()} />
                )}
                <TrustedArtifactPanel taskId={analysisTaskId} />
              </div>
              <button onClick={() => setShowResult(false)} className="text-[12px] text-[#aeaeb2] hover:text-[#636366] transition-colors">
                ← 返回查询
              </button>
            </div>
          )}
        </>
      )}
      {activeView === "reports" && (
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-[13px] text-[#1d1d1f]">我的报表</h3>
              <p className="mt-1 text-[11px] text-[#aeaeb2]">精选常用报表，也可分别查看智能分析保存的数据报表与可视化报表工作台配置的报表。</p>
            </div>
            {reportKindTab === "featured" && <span className="rounded-md bg-[#f2f2f7] px-2 py-1 text-[11px] text-[#636366]">{featuredEntries.length} 份</span>}
            {reportKindTab === "analysis" && <span className="rounded-md bg-[#f2f2f7] px-2 py-1 text-[11px] text-[#636366]">{visibleSavedAnalysisResults.length} 份</span>}
          </div>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="inline-flex rounded-lg bg-[#f2f2f7] p-0.5" role="tablist" aria-label="我的报表分类">
              <button type="button" role="tab" aria-selected={reportKindTab === "featured"} onClick={() => selectReportKindTab("featured")} className={`h-8 rounded-md px-4 text-[11px] ${reportKindTab === "featured" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#7b7b80]"}`}>精选</button>
              <button type="button" role="tab" aria-selected={reportKindTab === "analysis"} onClick={() => selectReportKindTab("analysis")} className={`h-8 rounded-md px-4 text-[11px] ${reportKindTab === "analysis" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#7b7b80]"}`}>智能分析</button>
              <button type="button" role="tab" aria-selected={reportKindTab === "visual"} onClick={() => selectReportKindTab("visual")} className={`h-8 rounded-md px-4 text-[11px] ${reportKindTab === "visual" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#7b7b80]"}`}>可视化报表</button>
            </div>
            {reportKindTab !== "featured" && (
              <button type="button" onClick={() => navigate(reportKindTab === "analysis" ? "/self-analysis/query" : "/self-analysis/visual-reports")} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#0f8f58] px-3 text-[11px] text-white hover:bg-[#0b7d4c]">
                <Plus className="h-3.5 w-3.5" />{reportKindTab === "analysis" ? "新建智能分析" : "新建可视化报表"}
              </button>
            )}
          </div>
          {reportKindTab === "featured" && featuredReportPagination.paginated && <div className="mb-3 flex justify-end"><DataPageSelector page={featuredReportPagination.page} totalPages={featuredReportPagination.totalPages} shownCount={featuredReportPagination.items.length} totalCount={featuredReportPagination.total} onChange={featuredReportPagination.setPage} ariaLabel="我的精选报表分页" /></div>}
          {reportKindTab === "analysis" && savedReportPagination.paginated && <div className="mb-3 flex justify-end"><DataPageSelector page={savedReportPagination.page} totalPages={savedReportPagination.totalPages} shownCount={savedReportPagination.items.length} totalCount={savedReportPagination.total} onChange={savedReportPagination.setPage} ariaLabel="我的智能分析报表分页" /></div>}
          <div className={reportKindTab === "featured" ? "" : "hidden"} data-my-reports-featured-tab="true">
            {reportActionError && <div className="mb-3 rounded-lg border border-[#ffd0d0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#d93025]">{reportActionError}</div>}
            <div className="space-y-1.5">
              {featuredReportPagination.items.map((entry) => entry.kind === "analysis" ? (
                <div key={entry.key} className="overflow-hidden rounded-lg bg-[#fafbfc]" data-featured-report="analysis">
                  <div
                    className="flex cursor-pointer items-center gap-3 p-3 transition-colors hover:bg-[#f2f2f7]"
                    role="button"
                    tabIndex={0}
                    onClick={() => { void openSavedReport(entry.result); }}
                    onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void openSavedReport(entry.result); } }}
                  >
                    <div className="min-w-0 flex-1">
                      <span className="block max-w-full truncate text-left text-[12px] text-[#1d1d1f]">{entry.result.title || entry.result.query}</span>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-[#c7c7cc]">
                        <span className="inline-flex items-center rounded bg-[#f2f2f7] px-1.5 py-0.5 text-[10px] text-[#636366]">智能分析</span>
                        <span>{entry.result.savedAt || "时间未记录"}</span>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        data-featured-report-star="analysis"
                        aria-pressed="true"
                        aria-label={`取消精选${entry.result.title || entry.result.query}`}
                        title="取消精选"
                        onClick={(event) => { event.stopPropagation(); featuredReports.toggle("analysis", entry.result.id); }}
                        className="rounded-md p-1.5 text-[#c7c7cc] hover:bg-white"
                      >
                        <Star className="h-3.5 w-3.5 fill-[#f5a524] text-[#f5a524]" />
                      </button>
                      <button type="button" aria-label="查看报告" title="查看" onClick={(event) => { event.stopPropagation(); void openSavedReport(entry.result); }} className="rounded-md p-1.5 text-[#636366] hover:bg-white"><Eye className="h-3.5 w-3.5" /></button>
                    </div>
                  </div>
                  {expandedReportId === entry.result.id && (
                    <div className="border-t border-[#ececf0] bg-white p-4">
                      {reportLoadingId === entry.result.id ? (
                        <div className="rounded-lg bg-[#fafbfc] px-3 py-8 text-center text-[12px] text-[#8a8a8e]">正在从 Topic_Data 读取该报告的最新数据…</div>
                      ) : (
                        <>
                          {analysisRows.length ? (
                  <ResizableVisualizationGrid>
                            {reportVisualizationsFor(entry.result).map((card, cardIndex, cards) => <AnalysisVisualCard
                              key={card.id} id={card.id} stateKey={`featured:${entry.result.id}:${card.id}`} fillHeight
                              title={card.title}
                              type={card.type}
                              rows={analysisRows}
                              initialConfig={card.config}
                              analysisSource={resolveVisualAnalysisTables(entry.result.selectedDataTables, selectedDataTables)}
                              onFollowUp={(detail) => revealVisualFollowUp({ key: card.key || "primary", title: card.title, type: card.type, rows: analysisRows, taskId: entry.result.analysisTaskId, reportId: entry.result.id, question: entry.result.query, summary: analysisSummary || entry.result.summary, plan: entry.result.plan, selectedDataTables: resolveVisualAnalysisTables(detail?.dataTables, entry.result.selectedDataTables, selectedDataTables) })}
                              onComment={(detail) => revealVisualComment({ key: card.key || "primary", title: card.title, type: card.type, rows: analysisRows, taskId: entry.result.analysisTaskId, reportId: entry.result.id, question: entry.result.query, summary: analysisSummary || entry.result.summary, plan: entry.result.plan, selectedDataTables: resolveVisualAnalysisTables(detail?.dataTables, entry.result.selectedDataTables, selectedDataTables) })}
                              onTypeChange={(nextType) => void persistSavedReportVisualizations(entry.result, cards.map((item) => item.id === card.id ? { ...item, type: nextType } : item))}
                              onTitleChange={(nextTitle) => void persistSavedReportVisualizations(entry.result, cards.map((item) => item.id === card.id ? { ...item, title: nextTitle } : item))}
                              onConfigChange={(config) => setSavedAnalysisResults((current) => current.map((item) => item.id === entry.result.id ? { ...item, visualizations: cards.map((visual) => visual.id === card.id ? { ...visual, config } : visual) } : item))}
                              onDuplicate={(config, options) => { const duplicate = { ...card, id: `visual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, key: undefined, type: options?.asText ? "text" as const : card.type, title: options?.asText ? `${card.title} · 结论` : `${card.title} · 副本`, config: options?.asText ? { ...config, noteTitle: "", noteBody: "", noteItems: [], noteTitleHidden: false, ...visualDuplicateLayout(card.id) } : config }; void persistSavedReportVisualizations(entry.result, [...cards.slice(0, cardIndex + 1), duplicate, ...cards.slice(cardIndex + 1)]); }}
                              onDelete={() => { void askConfirm({ title: "删除图表", description: `确定删除图表「${card.title}」？`, hint: "此操作不可撤销。" }).then((ok) => { if (ok) void persistSavedReportVisualizations(entry.result, cards.filter((item) => item.id !== card.id)); }); }}
                            />)}
                          </ResizableVisualizationGrid>
                  ) : null}
                          <div className="mt-4 rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-3 text-[12px] leading-[1.7] whitespace-pre-wrap text-[#3a3a3c]">{analysisSummary || entry.result.summary || "当前报告尚无可展示结论。"}</div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <VisualReportRow
                  key={entry.key}
                  report={entry.report}
                  expanded={expandedFeaturedVisualId === entry.report.id}
                  onToggleExpanded={() => setExpandedFeaturedVisualId((current) => current === entry.report.id ? "" : entry.report.id)}
                  railPageKey="my-reports"
                  featured
                  onToggleFeatured={() => featuredReports.toggle("visual", entry.report.id)}
                  kindBadge="可视化报表"
                />
              ))}
              {!featuredEntries.length && (
                <div className="rounded-lg bg-[#fafbfc] p-3 text-[11px] text-[#aeaeb2]">
                  {visualMine.loading || !savedAnalysisLoaded ? "正在核对精选报表…" : "尚未精选报表，可在智能分析或可视化报表列表右侧点击星标加入。"}
                </div>
              )}
            </div>
          </div>
          <div className={reportKindTab === "analysis" ? "" : "hidden"} data-my-reports-analysis-tab="true">
          {reportActionError && <div className="mb-3 rounded-lg border border-[#ffd0d0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#d93025]">{reportActionError}</div>}
          {reportActionNotice && <div className="mb-3 rounded-lg border border-[#d7efd9] bg-[#eef8f1] px-3 py-2 text-[11px] text-[#258a3f]">{reportActionNotice}</div>}
          <div className="space-y-1.5">
            {savedReportPagination.items.map((result) => (
              <div key={result.id} className="overflow-hidden rounded-lg bg-[#fafbfc]">
                <div
                  className="flex cursor-pointer items-center gap-3 p-3 transition-colors hover:bg-[#f2f2f7]"
                  role="button"
                  tabIndex={0}
                  onClick={() => { if (editingReportId !== result.id) void openSavedReport(result); }}
                  onKeyDown={(event) => { if (editingReportId !== result.id && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); void openSavedReport(result); } }}
                >
                  <div className="min-w-0 flex-1">
                    {editingReportId === result.id ? (
                      <input
                        autoFocus
                        value={reportTitleDraft}
                        onChange={(event) => setReportTitleDraft(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") void saveReportTitle(result);
                          if (event.key === "Escape") setEditingReportId(null);
                        }}
                        className="h-7 w-full rounded-md border border-[#c7c7cc] bg-white px-2 text-[12px] text-[#1d1d1f] outline-none"
                      />
                    ) : (
                      <span onDoubleClick={(event) => { event.stopPropagation(); setEditingReportId(result.id); setReportTitleDraft(result.title || result.query); }} className="block max-w-full truncate text-left text-[12px] text-[#1d1d1f]" title="双击修改报告名称">
                        {result.title || result.query}
                      </span>
                    )}
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-[#c7c7cc]">
                      {result.source?.channel && <span className="inline-flex items-center gap-1 rounded bg-[#eef3ff] px-1.5 py-0.5 text-[#4169a8]"><Sparkles className="h-3 w-3" />{result.source.label || result.source.channel}</span>}
                      <span>{result.savedAt || "时间未记录"}{result.topicData?.updated_at ? ` · 数据更新 ${new Date(result.topicData.updated_at).toLocaleString("zh-CN", { hour12: false })}` : ""}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      data-featured-report-star="analysis"
                      aria-pressed={featuredReports.isFeatured("analysis", result.id)}
                      aria-label={featuredReports.isFeatured("analysis", result.id) ? `取消精选${result.title || result.query}` : `精选${result.title || result.query}`}
                      title={featuredReports.isFeatured("analysis", result.id) ? "取消精选" : "精选"}
                      onClick={(event) => { event.stopPropagation(); featuredReports.toggle("analysis", result.id); }}
                      className="rounded-md p-1.5 text-[#c7c7cc] hover:bg-white"
                    >
                      <Star className={`h-3.5 w-3.5 ${featuredReports.isFeatured("analysis", result.id) ? "fill-[#f5a524] text-[#f5a524]" : "text-[#c7c7cc]"}`} />
                    </button>
                    {editingReportId === result.id ? (
                      <button type="button" aria-label="保存报告名称" title="保存" onClick={(event) => { event.stopPropagation(); void saveReportTitle(result); }} className="rounded-md p-1.5 text-[#636366] hover:bg-white"><Check className="h-3.5 w-3.5" /></button>
                    ) : (
                      <button type="button" aria-label="编辑报告名称" title="编辑" onClick={(event) => { event.stopPropagation(); setEditingReportId(result.id); setReportTitleDraft(result.title || result.query); }} className="rounded-md p-1.5 text-[#636366] hover:bg-white"><Pencil className="h-3.5 w-3.5" /></button>
                    )}
                    <button type="button" aria-label="查看报告" title="查看" onClick={(event) => { event.stopPropagation(); void openSavedReport(result); }} className="rounded-md p-1.5 text-[#636366] hover:bg-white"><Eye className="h-3.5 w-3.5" /></button>
                    <button type="button" aria-label="删除报告" title="删除" onClick={(event) => { event.stopPropagation(); void deleteSavedReport(result); }} className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025]"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
                {expandedReportId === result.id && (
                  <div className="border-t border-[#ececf0] bg-white p-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <div className="text-[12px] font-medium text-[#1d1d1f]">可视化图形与结论</div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => void saveSavedReportToWeekly(result)}
                          disabled={reportActionLoadingId === `${result.id}:weekly`}
                          className="inline-flex h-7 items-center gap-1 rounded-md border border-[#e5e5ea] bg-white px-2.5 text-[11px] text-[#3a3a3c] transition-colors hover:bg-[#f2f2f7] disabled:cursor-wait disabled:opacity-60"
                        >
                          <BookmarkPlus className="h-3.5 w-3.5" />
                          {reportActionLoadingId === `${result.id}:weekly` ? "保存中" : result.weeklyReportEligible ? "已存周报" : "存周报"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void saveSavedReportAsExperience(result)}
                          disabled={reportActionLoadingId === `${result.id}:experience`}
                          className="inline-flex h-7 items-center gap-1 rounded-md border border-[#e5e5ea] bg-white px-2.5 text-[11px] text-[#3a3a3c] transition-colors hover:bg-[#f2f2f7] disabled:cursor-wait disabled:opacity-60"
                        >
                          <Lightbulb className="h-3.5 w-3.5" />
                          {reportActionLoadingId === `${result.id}:experience` ? "固化中" : "存经验"}
                        </button>
                      </div>
                    </div>
                    {reportLoadingId === result.id ? (
                      <div className="rounded-lg bg-[#fafbfc] px-3 py-8 text-center text-[12px] text-[#8a8a8e]">正在从 Topic_Data 读取该报告的最新数据…</div>
                    ) : <>
                    {analysisRows.length ? (
                  <ResizableVisualizationGrid>
                      {reportVisualizationsFor(result).map((card, cardIndex, cards) => <AnalysisVisualCard
                        key={card.id} id={card.id} stateKey={`report:${result.id}:${card.id}`} fillHeight
                        title={card.title}
                        type={card.type}
                        rows={analysisRows}
                        initialConfig={card.config}
                        analysisSource={resolveVisualAnalysisTables(result.selectedDataTables, selectedDataTables)}
                        onFollowUp={(detail) => revealVisualFollowUp({ key: card.key || "primary", title: card.title, type: card.type, rows: analysisRows, taskId: result.analysisTaskId, reportId: result.id, question: result.query, summary: analysisSummary || result.summary, plan: result.plan, selectedDataTables: resolveVisualAnalysisTables(detail?.dataTables, result.selectedDataTables, selectedDataTables) })}
                        onComment={(detail) => revealVisualComment({ key: card.key || "primary", title: card.title, type: card.type, rows: analysisRows, taskId: result.analysisTaskId, reportId: result.id, question: result.query, summary: analysisSummary || result.summary, plan: result.plan, selectedDataTables: resolveVisualAnalysisTables(detail?.dataTables, result.selectedDataTables, selectedDataTables) })}
                        onTypeChange={(nextType) => void persistSavedReportVisualizations(result, cards.map((item) => item.id === card.id ? { ...item, type: nextType } : item))}
                        onTitleChange={(nextTitle) => void persistSavedReportVisualizations(result, cards.map((item) => item.id === card.id ? { ...item, title: nextTitle } : item))}
                        onConfigChange={(config) => setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? { ...item, visualizations: cards.map((visual) => visual.id === card.id ? { ...visual, config } : visual) } : item))}
                        onDuplicate={(config, options) => { const duplicate = { ...card, id: `visual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, key: undefined, type: options?.asText ? "text" as const : card.type, title: options?.asText ? `${card.title} · 结论` : `${card.title} · 副本`, config: options?.asText ? { ...config, noteTitle: "", noteBody: "", noteItems: [], noteTitleHidden: false, ...visualDuplicateLayout(card.id) } : config }; void persistSavedReportVisualizations(result, [...cards.slice(0, cardIndex + 1), duplicate, ...cards.slice(cardIndex + 1)]); }}
                        onDelete={() => { void askConfirm({ title: "删除图表", description: `确定删除图表「${card.title}」？`, hint: "此操作不可撤销。" }).then((ok) => { if (ok) void persistSavedReportVisualizations(result, cards.filter((item) => item.id !== card.id)); }); }}
                      />)}
                    </ResizableVisualizationGrid>
                  ) : null}
                    <div className="mt-4 rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-3 text-[12px] leading-[1.7] whitespace-pre-wrap text-[#3a3a3c]">{analysisSummary || result.summary || "当前报告尚无可展示结论。"}</div>
                    </>}
                  </div>
                )}
              </div>
            ))}
            {!visibleSavedAnalysisResults.length && (
              <div className="rounded-lg bg-[#fafbfc] p-3 text-[11px] text-[#aeaeb2]">
                {savedAnalysisLoadError || (reportSourceFilter === "all" ? "暂无服务端已保存的报告" : "该来源暂无报告")}
              </div>
            )}
          </div>
          </div>
          {reportKindTab === "visual" && <VisualReportLibrary destination="mine" railPageKey="my-reports" />}
        </div>
      )}
      {dataTablePickerOpen && (
        <DataTablePickerModal
          rawTables={availableRawTables}
          topicTables={availableTopicTables}
          selectedTables={selectedDataTables}
          onChange={setSelectedDataTables}
          onClose={() => setDataTablePickerOpen(false)}
        />
      )}
      {voiceOpen && (
        <VoiceInputPopover
          transcript={voiceTranscript}
          listening={voiceListening}
          error={voiceError}
          onTranscriptChange={handleVoiceTranscriptChange}
          onAnalyze={analyzeVoiceInput}
          onCancel={cancelVoiceInput}
        />
      )}
      <AnalysisScriptEditor
        open={scriptEditorOpen}
        sqlScript={sqlScript}
        pythonScript={pythonScript}
        analysisScenarios={analysisScenarios}
        analysisSummary={analysisSummary}
        analysisPlan={analysisPlan}
        scriptPlanName={scriptPlanName}
        activeScriptTab={activeScriptTab}
        onSqlScriptChange={setSqlScript}
        onPythonScriptChange={setPythonScript}
        onAnalysisScenariosChange={setAnalysisScenarios}
        onAnalysisSummaryChange={setAnalysisSummary}
        onAnalysisPlanChange={setAnalysisPlan}
        onScriptPlanNameChange={setScriptPlanName}
        onActiveScriptTabChange={setActiveScriptTab}
        onClose={() => setScriptEditorOpen(false)}
        onSave={() => {
          setSaveMessage("修改已保留在当前编辑会话；点击“执行”后才会生成受治理的新 revision");
          setScriptEditorOpen(false);
        }}
        onExecute={() => {
          setScriptEditorOpen(false);
          void rerunAnalysis();
        }}
      />
      <ExecutionHistoryDrawer
        open={executionHistoryOpen}
        tasks={executionHistoryTasks}
        expandedTaskId={expandedExecutionTaskId}
        spans={executionTraceSpans}
        loading={executionHistoryLoading}
        onClose={() => setExecutionHistoryOpen(false)}
        onView={viewExecution}
        onDelete={(task) => void deleteExecution(task)}
        onToggleDetails={(task) => void toggleExecutionDetails(task)}
      />
    </div>
  );
}
