import { useEffect, useRef, useState, type ClipboardEvent, type ReactNode } from "react";
import { useLocation } from "react-router";
import { usePlatformContext } from "../platform/PlatformContext";
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
  type RawTableAsset,
  type TopicDataReference,
  type TopicTableAsset,
} from "../services/dataAssetApi";
import { apiErrorMessage, getApiBaseUrl } from "../services/apiClient";
import { demoFallbackDisabledMessage, isDemoFallbackEnabled } from "../services/apiContext";
import { modelApplicationModuleLabel } from "../data/modelApplicationModules";
import { runApplicationAction } from "../services/applicationApi";
import { fetchAnalysisRuntimeConfig, type FunAsrRuntimeIntegration, type ModelIntegration } from "../services/systemConfigApi";
import { findConfiguredTextModel, readPersistedTextModelSelection } from "../services/modelSelectionStore";
import { ArrowUp, AudioLines, Sparkles, Clock, Star, ArrowUpRight, BarChart3, PieChartIcon, TrendingUp, Table2, Download, BookmarkPlus, History, Lightbulb, ChevronDown, Code2, Mic, Plus, Upload, X, ChevronsDown, ChevronsUp, Eye, Pencil, Trash2, Check } from "lucide-react";
import { AnalysisVisualCard, RawDataTable } from "./self-analysis/ResultViews";
import {
  type VisualizationType,
  type ResultVisualKey,
  type ResultMode,
  type SaveTarget,
  type SelfAnalysisSection,
  type ScriptTab,
  type AnalysisSkillOption,
  type QuerySkillReference,
  type QueryReferenceMenuState,
  type AnalysisConversationTurn,
  type AnalysisConversationState,
  type FunAsrInputTarget,
  type AnalysisRunTrigger,
  type AnalysisTopicShortcut,
  type TopicShortcutMenuState,
  type KnowledgeFileAttachment,
  detectAttachmentInstitutions,
  type AnalysisDataTableSelection,
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
  rawTableToSelection,
  topicTableToSelection,
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
  createSelectedAnalysisModel,
  firstSelectableAnalysisModel,
  groupAnalysisModelOptions,
  hasSelectableAnalysisModel,
  autoReferenceSkillCategories,
  inferVisualTypes,
  visualizationLabel,
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
  readKnowledgeAttachment,
} from "./self-analysis/domain";

function AnalysisSkillMenu({
  skills,
  onUpload,
  onSelectDataTable,
  onSelectSkill,
}: {
  skills: AnalysisSkillOption[];
  onUpload: () => void;
  onSelectDataTable: () => void;
  onSelectSkill: (skill: AnalysisSkillOption) => void;
}) {
  const sceneSkills = skills.filter((skill) => skill.category === "场景");
  const topicSkills = skills.filter((skill) => skill.category === "主题");
  const modeSkills = skills.filter((skill) => skill.category === "模式");
  return (
    <div className="absolute left-0 top-10 z-50 max-h-[420px] w-[520px] max-w-[calc(100vw-48px)] overflow-y-auto rounded-xl border border-[#e5e5ea] bg-white p-1.5 shadow-xl shadow-black/[0.08]">
      <MenuGroup title="添加">
        <button
          type="button"
          onClick={onUpload}
          className="flex h-8 w-full items-center gap-2 rounded-lg px-3 text-left text-[13px] text-[#3a3a3c] hover:bg-[#f2f2f7]"
        >
          <Upload className="h-4 w-4 text-[#636366]" />
          <span className="shrink-0">文件上传</span>
          <span className="ml-auto truncate text-[11px] text-[#aeaeb2]">支持多文件</span>
        </button>
        <button
          type="button"
          onClick={onSelectDataTable}
          className="flex h-8 w-full items-center gap-2 rounded-lg px-3 text-left text-[13px] text-[#3a3a3c] hover:bg-[#f2f2f7]"
        >
          <Table2 className="h-4 w-4 text-[#636366]" />
          <span className="shrink-0">数据表</span>
          <span className="ml-auto truncate text-[11px] text-[#aeaeb2]">原始表/主题表</span>
        </button>
      </MenuGroup>
      <MenuGroup title="模式">
        {modeSkills.map((skill) => (
          <SkillMenuButton key={skill.id} skill={skill} onSelect={onSelectSkill} />
        ))}
      </MenuGroup>
      <MenuGroup title="场景">
        {sceneSkills.map((skill) => (
          <SkillMenuButton key={skill.id} skill={skill} onSelect={onSelectSkill} />
        ))}
      </MenuGroup>
      <MenuGroup title="主题">
        {topicSkills.map((skill) => (
          <SkillMenuButton key={skill.id} skill={skill} onSelect={onSelectSkill} />
        ))}
      </MenuGroup>
    </div>
  );
}

function MenuGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="py-0.5">
      <div className="px-3 pb-0.5 text-[12px] leading-5 text-[#aeaeb2]">{title}</div>
      <div className="space-y-px">{children}</div>
    </div>
  );
}

function SkillMenuButton({
  skill,
  onSelect,
}: {
  skill: AnalysisSkillOption;
  onSelect: (skill: AnalysisSkillOption) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(skill)}
      className="flex h-7 w-full items-center gap-2 rounded-lg px-3 text-left hover:bg-[#f2f2f7]"
    >
      <Sparkles className="h-4 w-4 shrink-0 text-[#636366]" />
      <span className="flex min-w-0 flex-1 items-baseline gap-2">
        <span className="shrink-0 text-[13px] font-normal text-[#4b4b50]">{skill.name}</span>
        <span className="min-w-0 truncate whitespace-nowrap text-[11px] text-[#aeaeb2]">{skill.description}</span>
      </span>
    </button>
  );
}

function DataTablePickerModal({
  rawTables,
  topicTables,
  selectedTables,
  onChange,
  onClose,
}: {
  rawTables: RawTableAsset[];
  topicTables: TopicTableAsset[];
  selectedTables: AnalysisDataTableSelection[];
  onChange: (tables: AnalysisDataTableSelection[]) => void;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<"raw" | "topic">("raw");
  const selectedIds = new Set(selectedTables.map((table) => table.id));
  const toggleTable = (table: AnalysisDataTableSelection) => {
    onChange(selectedIds.has(table.id)
      ? selectedTables.filter((item) => item.id !== table.id)
      : [...selectedTables, table]);
  };
  const rows = activeTab === "raw"
    ? rawTables.map(rawTableToSelection)
    : topicTables.map(topicTableToSelection);
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/20 px-4">
      <div className="w-full max-w-[820px] rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">选择数据表</h3>
            <p className="mt-1 text-[11px] text-[#8a8a8e]">与数据管理同源，选中后会将对应 SQL 和字段信息注入智能分析上下文。</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7]">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="border-b border-[#f0f0f2] px-5 pt-3">
          <div className="inline-flex rounded-lg bg-[#f2f2f7] p-1">
            {[
              { key: "raw", label: `原始表 ${rawTables.length}` },
              { key: "topic", label: `主题表 ${topicTables.length}` },
            ].map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key as "raw" | "topic")}
                className={`rounded-md px-3 py-1.5 text-[12px] transition-colors ${
                  activeTab === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="max-h-[460px] overflow-y-auto p-5">
          <div className="overflow-hidden rounded-lg border border-[#f0f0f2]">
            <div className="grid grid-cols-[1.1fr_0.8fr_1.7fr_70px] gap-3 bg-[#fafbfc] px-3 py-2 text-[11px] text-[#8a8a8e]">
              <span>表名称</span>
              <span>编码</span>
              <span>描述</span>
              <span className="text-right">选择</span>
            </div>
            {rows.map((table) => (
              <label key={table.id} className="grid cursor-pointer grid-cols-[1.1fr_0.8fr_1.7fr_70px] items-center gap-3 border-t border-[#f8f8f8] px-3 py-2.5 hover:bg-[#fafbfc]">
                <span className="text-[12px] text-[#1d1d1f]">{table.name}</span>
                <span className="truncate font-mono text-[11px] text-[#8a8a8e]">{table.code}</span>
                <span className="truncate text-[11px] text-[#636366]">{table.description}</span>
                <span className="flex justify-end">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(table.id)}
                    onChange={() => toggleTable(table)}
                    className="h-4 w-4 accent-[#1d1d1f]"
                  />
                </span>
              </label>
            ))}
            {!rows.length && <div className="px-3 py-8 text-center text-[12px] text-[#aeaeb2]">暂无可选数据表</div>}
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-[#f0f0f2] px-5 py-3">
          <span className="text-[11px] text-[#8a8a8e]">已选择 {selectedTables.length} 张表</span>
          <button type="button" onClick={onClose} className="rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e]">
            完成
          </button>
        </div>
      </div>
    </div>
  );
}

function AnalysisModelSelector({
  models,
  selectedModel,
  onSelect,
}: {
  models: ModelIntegration[];
  selectedModel: ModelIntegration | null;
  onSelect: (model: ModelIntegration) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const groups = groupAnalysisModelOptions(models);
  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  return (
    <div ref={menuRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        disabled={!groups.length}
        aria-label="选择分析模型"
        aria-expanded={open}
        className="flex h-7 max-w-[220px] items-center gap-1 rounded-md px-1.5 text-[11px] text-[#636366] transition-colors hover:bg-[#f2f2f7] disabled:cursor-not-allowed disabled:text-[#aeaeb2]"
        title={groups.length ? "选择智能分析推理模型" : "智能分析推理分析模块暂无已鉴权模型"}
      >
        <span className="truncate">{selectedModel?.name || "未配置分析模型"}</span>
        <ChevronDown className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && groups.length > 0 && (
        <div className="absolute left-0 top-full z-50 mt-2 max-h-[420px] w-[300px] overflow-y-auto rounded-xl border border-[#e5e5ea] bg-white py-2 shadow-xl shadow-black/10">
          {groups.map((group) => (
            <div key={group.id} data-model-group={group.category} className="border-b border-[#f2f2f7] pb-1.5 last:border-b-0 last:pb-0">
              <div className="px-3 pb-1 pt-1.5 text-[10px] font-semibold text-[#8a8a8e]">{group.category}</div>
              {group.options.map((option) => {
                const selected = option.model.id === selectedModel?.id && option.value === selectedModel.selectedModelName;
                return (
                  <button
                    key={option.id}
                    data-model-option={option.value}
                    type="button"
                    onClick={() => {
                      onSelect(createSelectedAnalysisModel(option));
                      setOpen(false);
                    }}
                    className={`flex w-full items-center justify-between px-3 py-2 text-left text-[12px] transition-colors ${selected ? "bg-[#f2f2f7] font-medium text-[#1d1d1f]" : "text-[#3a3a3c] hover:bg-[#f7f7f9]"}`}
                  >
                    <span className="truncate">{option.label}</span>
                    {selected && <span className="ml-3 h-1.5 w-1.5 shrink-0 rounded-full bg-[#1d1d1f]" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function QueryReferenceOverlay({
  skills,
  query,
  references,
  openMenu,
  onOpenMenu,
  onCancelReference,
}: {
  skills: AnalysisSkillOption[];
  query: string;
  references: QuerySkillReference[];
  openMenu: QueryReferenceMenuState;
  onOpenMenu: (state: Exclude<QueryReferenceMenuState, null>) => void;
  onCancelReference: (skill: AnalysisSkillOption) => void;
}) {
  if (!query) return null;
  const parts: ReactNode[] = [];
  let cursor = 0;
  references.forEach((reference) => {
    if (reference.start > cursor) {
      parts.push(
        <span key={`text_${cursor}_${reference.start}`}>
          {query.slice(cursor, reference.start)}
        </span>,
      );
    }
    parts.push(
      <span
        key={`${reference.skill.id}_${reference.start}`}
        role="button"
        tabIndex={-1}
        data-query-skill-reference={reference.skill.id}
        onContextMenu={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onOpenMenu({ skillId: reference.skill.id, x: event.clientX, y: event.clientY });
        }}
        className="pointer-events-auto mx-0.5 inline-flex max-w-full cursor-context-menu items-center rounded-md border border-[#d1d1d6] bg-[#f7f7f9] px-1.5 py-[1px] align-baseline text-[12px] font-semibold leading-[1.4] text-[#0b63ce]"
        title="右键取消引用"
      >
        {reference.text}
      </span>,
    );
    cursor = reference.end;
  });
  if (cursor < query.length) {
    parts.push(<span key={`text_${cursor}_end`}>{query.slice(cursor)}</span>);
  }
  const openSkill = openMenu
    ? skills.find((skill) => skill.id === openMenu.skillId)
    : null;

  return (
    <>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 z-20 min-h-[32px] whitespace-pre-wrap break-words px-0 py-0 text-[13px] leading-[1.5] text-[#3a3a3c]"
      >
        {parts}
      </div>
      {openMenu && openSkill && (
        <div
          className="fixed z-[100] w-24 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg shadow-black/10"
          style={{ left: openMenu.x, top: openMenu.y + 6 }}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => onCancelReference(openSkill)}
            className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7]"
          >
            取消{openSkill.category}
          </button>
        </div>
      )}
    </>
  );
}

function AnalysisTopicShortcuts({
  topics,
  expanded,
  editingId,
  menu,
  onToggleExpanded,
  onRunTopic,
  onOpenMenu,
  onRenameTopic,
  onFinishEditing,
  onStartEditing,
  onDeleteTopic,
}: {
  topics: AnalysisTopicShortcut[];
  expanded: boolean;
  editingId: string | null;
  menu: TopicShortcutMenuState;
  onToggleExpanded: () => void;
  onRunTopic: (topic: AnalysisTopicShortcut) => void;
  onOpenMenu: (state: Exclude<TopicShortcutMenuState, null>) => void;
  onRenameTopic: (topicId: string, title: string) => void;
  onFinishEditing: (topicId: string) => void;
  onStartEditing: (topicId: string) => void;
  onDeleteTopic: (topicId: string) => void;
}) {
  const openTopic = menu ? topics.find((topic) => topic.id === menu.id) : null;
  const canToggleExpanded = topics.length > 4;
  if (!topics.length) return null;

  return (
    <div className="relative">
      <div className={`flex flex-wrap gap-2 ${canToggleExpanded ? "pr-9" : ""} ${canToggleExpanded && !expanded ? "max-h-[62px] overflow-hidden" : ""}`}>
        {topics.map((topic) => (
          <div key={topic.id} className="relative">
            {editingId === topic.id ? (
              <input
                autoFocus
                value={topic.title}
                onChange={(event) => onRenameTopic(topic.id, event.target.value)}
                onBlur={() => onFinishEditing(topic.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onFinishEditing(topic.id);
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    onFinishEditing(topic.id);
                  }
                }}
                className="h-7 w-[220px] rounded-md border border-[#d1d1d6] bg-white px-2 text-[11px] font-semibold text-[#1d1d1f] outline-none focus:border-[#8e8e93]"
              />
            ) : (
              <button
                type="button"
                onClick={() => onRunTopic(topic)}
                onContextMenu={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onOpenMenu({ id: topic.id, x: event.clientX, y: event.clientY });
                }}
                title={`分析方法：${topic.method}\nSQL：${topic.sql}\n结论生成方式：${topic.conclusionMode}`}
                className="inline-flex h-7 max-w-[280px] items-center gap-1.5 rounded-md border border-[#d7efd9] bg-[#eef8f1] px-2.5 text-[11px] font-semibold text-[#258a3f] transition-colors hover:bg-[#e1f3e6]"
              >
                <Sparkles className="h-3 w-3 shrink-0" />
                <span className="truncate">{topic.title}</span>
              </button>
            )}
          </div>
        ))}
      </div>
      {canToggleExpanded && (
        <button
          type="button"
          onClick={onToggleExpanded}
          className="absolute bottom-0 right-0 flex h-7 w-7 items-center justify-center rounded-full border border-[#e5e5ea] bg-white text-[#8a8a8e] shadow-sm hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
          aria-label={expanded ? "折叠分析主题" : "展开历史分析主题"}
        >
          {expanded ? <ChevronsUp className="h-3.5 w-3.5" /> : <ChevronsDown className="h-3.5 w-3.5" />}
        </button>
      )}
      {menu && openTopic && (
        <div
          className="fixed z-[100] w-24 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg shadow-black/10"
          style={{ left: menu.x, top: menu.y + 6 }}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => onStartEditing(openTopic.id)}
            className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7]"
          >
            编辑
          </button>
          <button
            type="button"
            onClick={() => onDeleteTopic(openTopic.id)}
            className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#d93025] hover:bg-[#f2f2f7]"
          >
            删除
          </button>
        </div>
      )}
    </div>
  );
}

export function SelfAnalysis() {
  const location = useLocation();
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
  const realtimeVoiceLastAutoAnalysisTextRef = useRef("");
  const realtimeVoiceAutoAnalyzeRef = useRef<(text: string, trigger: RealtimeVoiceTrigger) => void>(() => undefined);
  const realtimeVoiceDrainQueueRef = useRef<() => void>(() => undefined);
  const realtimeVoiceQueueRef = useRef<Array<{ text: string; trigger: RealtimeVoiceTrigger }>>([]);
  const realtimeVoiceSpeakerGateRef = useRef<RealtimeSpeakerGateState>(createRealtimeSpeakerGateState());
  const realtimeVoiceIgnoredSpeakerSegmentsRef = useRef(0);
  const queryLatestRef = useRef("");
  const isAnalyzingRef = useRef(false);
  const activeAnalysisRunIdRef = useRef("");
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
  const [availableAnalysisSkills, setAvailableAnalysisSkills] = useState<AnalysisSkillOption[]>(analysisSkillOptions);
  const [dismissedAutoSkillIds, setDismissedAutoSkillIds] = useState<Set<string>>(() => new Set());
  const [referenceMenu, setReferenceMenu] = useState<QueryReferenceMenuState>(null);
  const [knowledgeFiles, setKnowledgeFiles] = useState<KnowledgeFileAttachment[]>([]);
  const [showResult, setShowResult] = useState(false);
  const [analysisPlan, setAnalysisPlan] = useState("");
  const [analysisRows, setAnalysisRows] = useState<AnalysisRow[]>([]);
  const [analysisSummary, setAnalysisSummary] = useState("");
  const [analysisScenarios, setAnalysisScenarios] = useState("本次第一阶段规划尚未生成指标表现情景。");
  const [analysisError, setAnalysisError] = useState("");
  const [analysisProgressSteps, setAnalysisProgressSteps] = useState<AnalysisProgressStep[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisTaskId, setAnalysisTaskId] = useState("");
  const [resultMode, setResultMode] = useState<ResultMode>("visual");
  const [saveMessage, setSaveMessage] = useState("");
  const [visualTypes, setVisualTypes] = useState<Record<ResultVisualKey, VisualizationType>>({
    primary: "column",
    secondary: "table",
  });
  const [openVisualMenu, setOpenVisualMenu] = useState<ResultVisualKey | null>(null);
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
  const [availableMetrics, setAvailableMetrics] = useState<MetricDictionaryItem[]>([]);
  const [availableRawTables, setAvailableRawTables] = useState<RawTableAsset[]>([]);
  const [availableTopicTables, setAvailableTopicTables] = useState<TopicTableAsset[]>([]);
  const [selectedDataTables, setSelectedDataTables] = useState<AnalysisDataTableSelection[]>([]);
  const [dataTablePickerOpen, setDataTablePickerOpen] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<TopicTableAsset | null>(null);
  const [conversationSessionId, setConversationSessionId] = useState("");
  const [conversationTurns, setConversationTurns] = useState<AnalysisConversationTurn[]>([]);
  const [analysisTopicShortcuts, setAnalysisTopicShortcuts] = useState<AnalysisTopicShortcut[]>([]);
  const [savedAnalysisResults, setSavedAnalysisResults] = useState<SavedAnalysisResult[]>([]);
  const [reportSourceFilter, setReportSourceFilter] = useState("all");
  const [savedAnalysisLoadError, setSavedAnalysisLoadError] = useState("");
  const [expandedReportId, setExpandedReportId] = useState("");
  const [editingReportId, setEditingReportId] = useState<string | null>(null);
  const [reportTitleDraft, setReportTitleDraft] = useState("");
  const [reportActionError, setReportActionError] = useState("");
  const [reportActionNotice, setReportActionNotice] = useState("");
  const [reportActionLoadingId, setReportActionLoadingId] = useState("");
  const [reportLoadingId, setReportLoadingId] = useState("");
  const [analysisTopicsLoaded, setAnalysisTopicsLoaded] = useState(false);
  const [analysisTopicsExpanded, setAnalysisTopicsExpanded] = useState(false);
  const [topicShortcutMenu, setTopicShortcutMenu] = useState<TopicShortcutMenuState>(null);
  const [editingTopicId, setEditingTopicId] = useState<string | null>(null);
  const [executionHistoryOpen, setExecutionHistoryOpen] = useState(false);
  const [executionHistoryLoading, setExecutionHistoryLoading] = useState(false);
  const [executionHistoryTasks, setExecutionHistoryTasks] = useState<BackendAnalysisResponse[]>([]);
  const [expandedExecutionTaskId, setExpandedExecutionTaskId] = useState("");
  const [executionTraceSpans, setExecutionTraceSpans] = useState<AnalysisTraceSpan[]>([]);
  const selectedManualSkills = [selectedModeSkill, selectedSceneSkill, selectedTopicSkill].filter(
    (skill): skill is AnalysisSkillOption => Boolean(skill),
  );
  const primaryAnalysisSkill = selectedSceneSkill || selectedTopicSkill || selectedModeSkill;
  const querySkillReferences = buildQuerySkillReferences(query, dismissedAutoSkillIds, availableAnalysisSkills);
  const visibleAnalysisTopicShortcuts = analysisTopicShortcuts.filter((topic) => !topic.hidden);
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

  const reportSourceOptions = Array.from(
    new Map(
      savedAnalysisResults
        .map((result) => result.source?.channel ? [result.source.channel, result.source.label || result.source.channel] as const : null)
        .filter((item): item is readonly [string, string] => Boolean(item)),
    ).entries(),
  );
  const visibleSavedAnalysisResults = reportSourceFilter === "all"
    ? savedAnalysisResults
    : savedAnalysisResults.filter((result) => result.source?.channel === reportSourceFilter);

  useEffect(() => {
    if (reportSourceFilter !== "all" && !reportSourceOptions.some(([channel]) => channel === reportSourceFilter)) {
      setReportSourceFilter("all");
    }
  }, [reportSourceFilter, reportSourceOptions]);

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
    if (!referenceMenu) return;
    const closeOnOutsidePointer = () => setReferenceMenu(null);
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
    };
  }, [referenceMenu]);

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
        const models = runtime.models.filter((model) => model.name && model.modelName);
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
    };
    void syncModels();
    return () => {
      cancelled = true;
    };
  }, [activeView, tenantId, userId]);

  useEffect(() => {
    if (activeView !== "query") return;
    let cancelled = false;
    const syncMetrics = async () => {
      try {
        const [metricResponse, assetResponse] = await Promise.all([
          fetchMetricDictionary({ tenantId, userId }),
          fetchDataAssets({ tenantId, userId }),
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
          setAvailableRawTables(assetResponse.raw_tables.filter((table) => table.lifecycleStatus === "active"));
          setAvailableTopicTables(assetResponse.topic_tables);
          const configuredSkills = (assetResponse.analysis_skills || [])
            .filter((skill) => skill.enabled && skill.lifecycleStatus === "active")
            .sort((a, b) => a.sortOrder - b.sortOrder)
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
          setAvailableAnalysisSkills(analysisSkillOptions);
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

  const hideAnalysisTopicShortcut = (topicId: string) => {
    setAnalysisTopicShortcuts((current) =>
      current.map((topic) =>
        topic.id === topicId
          ? { ...topic, hidden: true, updatedAt: new Date().toISOString() }
          : topic,
      ),
    );
    setTopicShortcutMenu(null);
  };

  const renameAnalysisTopicShortcut = (topicId: string, title: string) => {
    setAnalysisTopicShortcuts((current) =>
      current.map((topic) =>
        topic.id === topicId
          ? { ...topic, title, updatedAt: new Date().toISOString() }
          : topic,
      ),
    );
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

  const startAnalysisTopicEditing = (topicId: string) => {
    setTopicShortcutMenu(null);
    setEditingTopicId(topicId);
  };

  const uploadKnowledgeFiles = async (files: File[]) => {
    if (!files.length) return;
    const nextFiles = await Promise.all(files.map(readKnowledgeAttachment));
    setKnowledgeFiles((current) => [...current, ...nextFiles]);
    await Promise.all(
      nextFiles.map((file) =>
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
          },
        }).catch(() => undefined),
      ),
    );
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

  const cancelAutoReference = (skill: AnalysisSkillOption) => {
    setDismissedAutoSkillIds((current) => new Set(current).add(skill.id));
    setReferenceMenu(null);
    void runApplicationAction({
      tenantId,
      userId,
      moduleKey: "self_analysis",
      action: "cancel_auto_reference",
      payload: { skill },
    }).catch(() => undefined);
    queryInputRef.current?.focus();
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

  const handleAnalysisRunProgress = (run: { automation_run_id: string; progress_steps?: AnalysisProgressStep[] }) => {
    activeAnalysisRunIdRef.current = run.automation_run_id;
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
        partialAnalysisResponseRef.current = partial;
        const currentQuestion = partial.question || queryLatestRef.current;
        const partialRows = mapBackendRows(partial, currentQuestion);
        if (!partialRows.length) return;
        setAnalysisTaskId(partial.task_id);
        setAnalysisRows(partialRows);
        const fallbackVisualTypes = inferVisualTypes(currentQuestion, selectedDataTables);
        setAnalysisPlan(formatBackendPlan(currentQuestion, partial.analysis_plan) || createAnalysisPlan(currentQuestion, fallbackVisualTypes));
        setVisualTypes(visualTypesFromBackend(partial, fallbackVisualTypes));
        setSqlScript(sqlScriptFromBackend(partial));
        setPythonScript(pythonScriptFromBackend(partial));
        setResultMode("visual");
      })
      .catch(() => {
        partialAnalysisTaskIdRef.current = "";
      });
  };

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
    if (!nextQuery) {
      setAnalysisError("请输入明确的分析问题后再执行");
      return;
    }
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
    const effectiveDataTables = forcedDataTables ?? selectedDataTables;
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
    setOpenVisualMenu(null);
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
    setIsAnalyzing(true);
    isAnalyzingRef.current = true;
    setAnalysisError("");

    try {
      const response = await waitForSelfAnalysis({
        question: nextQuery,
        tenantId,
        userId,
        requestId: crypto.randomUUID(),
        onRun: handleAnalysisRunProgress,
        pageContext: {
          route: "self-analysis/query",
          selected_institution: selectedInstitution,
          analysis_trigger: trigger,
          model_application_module: modelApplicationModule,
          model_application_selection: modelApplicationSelection(modelApplicationModule, routedModel),
          realtime_voice_auto_analysis: realtimeVoiceAutoAnalysis,
          analysis_policy: analysisPolicy,
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
      const backendPlan = appendMetricReferences(formatBackendPlan(nextQuery, response.analysis_plan) || modelPlan, nextQuery, availableMetrics);
      const backendRows = mapBackendRows(response, nextQuery);
      const backendVisualTypes = visualTypesFromBackend(response, fallbackVisualTypes);
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
      addConversationTurn(
        makeConversationTurn("assistant", backendSummary, {
          query: nextQuery,
          summary: backendSummary,
          sql: backendSql,
          analysisPlan: backendPlan,
        }),
      );
    } catch (error) {
      let partial = partialAnalysisResponseRef.current;
      if (!partial && partialAnalysisTaskIdRef.current) {
        try { partial = await fetchAnalysisTask({ taskId: partialAnalysisTaskIdRef.current, tenantId, userId }); } catch { partial = null; }
      }
      const partialRows = partial ? mapBackendRows(partial, nextQuery) : [];
      if (partial && partialRows.length) {
        setAnalysisTaskId(partial.task_id);
        setAnalysisRows(partialRows);
        setAnalysisPlan(formatBackendPlan(nextQuery, partial.analysis_plan) || modelPlan);
        setVisualTypes(visualTypesFromBackend(partial, fallbackVisualTypes));
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
      activeAnalysisRunIdRef.current = "";
      setIsAnalyzing(false);
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
    setOpenVisualMenu(null);
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
    try {
      const response = await waitForSelfAnalysis({
        question: nextQuery,
        tenantId,
        userId,
        requestId: crypto.randomUUID(),
        onRun: handleAnalysisRunProgress,
        pageContext: {
          route: "self-analysis/query",
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
      const editStatuses = Object.entries(response.manual_edits ?? {})
        .map(([name, detail]) => `${name}=${detail.status ?? "unknown"}`)
        .join("，");
      const backendPlan = `${appendMetricReferences(formatBackendPlan(nextQuery, response.analysis_plan) || analysisPlan, nextQuery, availableMetrics)}
重跑说明：已创建第${response.revision ?? 1}次受治理执行${editStatuses ? `；人工修改状态：${editStatuses}` : ""}。`;
      const backendRows = mapBackendRows(response, nextQuery);
      const backendVisualTypes = visualTypesFromBackend(response, inferVisualTypes(`${nextQuery} ${analysisPlan}`, selectedDataTables));
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
      let partial = partialAnalysisResponseRef.current;
      if (!partial && partialAnalysisTaskIdRef.current) {
        try { partial = await fetchAnalysisTask({ taskId: partialAnalysisTaskIdRef.current, tenantId, userId }); } catch { partial = null; }
      }
      const partialRows = partial ? mapBackendRows(partial, nextQuery) : [];
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
      activeAnalysisRunIdRef.current = "";
      setIsAnalyzing(false);
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

  const rowsFromTopicSnapshot = (rows: Array<Record<string, string>>): AnalysisRow[] => {
    if (!rows.length) return [];
    const first = rows[0];
    const metricField = Object.keys(first).find((field) => Number.isFinite(Number(first[field]))) || Object.keys(first)[0] || "value";
    const dimensionField = Object.keys(first).find((field) => field !== metricField) || metricField;
    return rows.slice(0, 200).map((raw, index) => ({
      branch: String(raw[dimensionField] || `第${index + 1}行`),
      productLine: String(raw.product_line || "—"),
      customerSegment: String(raw.customer_segment || "—"),
      amount: Number(raw[metricField]) || 0,
      metricName: metricField,
      metricUnit: "",
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
    const restoredRows = rowsFromTopicSnapshot(snapshot.rows);
    setQuery(restoredQuery);
    setScriptPlanName(restoredQuery);
    setAnalysisTaskId(String(manifest.task_id || (reference.reference_type === "history" ? reference.reference_id : "")));
    setAnalysisPlan(String(manifest.analysis_plan?.toString?.() || `已复用 Topic_Data 最新快照 · ${snapshot.row_count} 行数据。`));
    setAnalysisRows(restoredRows);
    setAnalysisSummary(String(manifest.summary || "该结果已从 Topic_Data 最新快照恢复。"));
    setSqlScript(String(manifest.sql || "-- 当前 Topic_Data 快照未保存 SQL。"));
    setPythonScript(String(manifest.python_script || "# 当前 Topic_Data 快照未保存 Python 脚本。"));
    setVisualTypes(options.fallbackVisualTypes || inferVisualTypes(restoredQuery, selectedDataTables));
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
      const saved = {
        ...response.result,
        visualTypes: {
          primary: response.result.visualTypes.primary as VisualizationType,
          secondary: response.result.visualTypes.secondary as VisualizationType,
        },
      } satisfies SavedAnalysisResult;
      setSavedAnalysisResults((current) => current.map((item) => item.id === result.id ? saved : item));
      setEditingReportId(null);
      setReportActionError("");
    } catch (error) {
      setReportActionError(apiErrorMessage(error, "报告名称保存失败"));
    }
  };

  const deleteSavedReport = async (result: SavedAnalysisResult) => {
    if (!window.confirm(`确认删除报告“${result.title || result.query}”吗？`)) return;
    try {
      await deleteSavedAnalysisResult({ tenantId, userId, resultId: result.id });
      setSavedAnalysisResults((current) => current.filter((item) => item.id !== result.id));
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

  const saveAnalysisResult = async () => {
    const title = query || "未命名分析结果";
    const result: SavedAnalysisResult = {
      id: `analysis_${Date.now()}`,
      title,
      query: title,
      plan: analysisPlan,
      summary: analysisSummary || "服务端未返回经复核的结论",
      visualTypes,
      savedAt: new Date().toLocaleString("zh-CN", { hour12: false }),
      rows: analysisRows,
      analysisTaskId,
      visibility: "private",
      analysisInstitution: detectedAnalysisInstitution(knowledgeFiles, selectedInstitution),
      currentInstitution: selectedInstitution,
      uploadedDataInstitutions: Array.from(new Set(knowledgeFiles.flatMap((file) => file.detectedInstitutions || detectAttachmentInstitutions(file.name, file.contentPreview || "")))),
    };
    setSaveMessage("保存中...");
    try {
      const response = await saveSavedAnalysisResult({ tenantId, userId, result });
      setSavedAnalysisResults((current) => [response.result as SavedAnalysisResult, ...current.filter((item) => item.id !== response.result.id)].slice(0, 50));
      window.dispatchEvent(new CustomEvent("smart-data-agent-analysis-saved", { detail: response.result }));
      setSaveMessage("已保存到我的报告，数据已关联 Topic_Data 最新快照。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        const nextResults = [result, ...loadSavedAnalysisResults()].slice(0, 12);
        window.localStorage.setItem(savedAnalysisStorageKey, JSON.stringify(nextResults));
        setSavedAnalysisResults(nextResults);
        window.dispatchEvent(new CustomEvent("smart-data-agent-analysis-saved", { detail: result }));
        setSaveMessage(`已保存到 demo 本地缓存，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setSaveMessage(`${demoFallbackDisabledMessage("分析结果保存")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const downloadAnalysisRows = async () => {
    downloadCsv("自助分析原始数据.csv", analysisRows);
  };

  const saveAsTopicTable = async () => {
    const title = scriptPlanName || query || "智能分析主题";
    const topic = {
      id: `topic_${Date.now()}`,
      name: title,
      code: title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || `topic_${Date.now()}`,
      description: analysisSummary.split("\n")[0]?.replace("核心结论：", "") || "由智能分析结果沉淀的主题表。",
      sql: sqlScript,
      fields: analysisRows.length
        ? Object.keys(analysisRows[0].raw).map((fieldName) => ({
            fieldNameEn: fieldName,
            fieldNameCn: fieldName,
            type: typeof analysisRows[0].raw[fieldName] === "number" ? "decimal" : "string",
            explanation: "来自已执行分析结果；业务语义需在数据资产复核时确认。",
            exampleUsage: "智能分析、经营周报、主题表复用",
          }))
        : [],
      fieldExplanations: "字段来自服务端已执行结果，需在数据资产审核中补充业务语义。",
      applicableScene: "智能分析, 经营周报",
      relatedIntent: selectedTopic?.relatedIntent || "智能分析沉淀",
      relatedExperience: "",
      quickDisplay: false,
      reportReference: "经营周报",
      source: "智能分析页面",
      analysisTaskId,
      updatedAt: new Date().toLocaleString("zh-CN", { hour12: false }),
    };
    setSaveMessage("保存主题表中...");
    try {
      await saveDataAssetItem({ tenantId, itemType: "topic_table", item: topic });
      setSaveMessage("主题表版本已提交数据资产复核；批准发布后才会进入智能分析复用");
    } catch (error) {
      setSaveMessage(`${demoFallbackDisabledMessage("主题表保存")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const saveAsAnalysisExperience = async () => {
    const title = scriptPlanName || query || "智能分析经验";
    const experience = {
      id: `exp_${Date.now()}`,
      name: title,
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
      setSaveMessage("分析经验版本已提交复核；批准发布后才会进入知识记忆召回");
    } catch (error) {
      setSaveMessage(`${demoFallbackDisabledMessage("分析经验保存")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const handleSaveTarget = (target: SaveTarget) => {
    if (target === "topic") {
      void saveAsTopicTable();
      return;
    }
    if (target === "experience") {
      void saveAsAnalysisExperience();
      return;
    }
    void saveAnalysisResult();
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
        setRealtimeVoiceError("实时语音连接中断，正在自动重连…");
        const attempt = realtimeVoiceReconnectAttemptsRef.current + 1;
        realtimeVoiceReconnectAttemptsRef.current = attempt;
        const delay = Math.min(10_000, 800 * 2 ** Math.min(attempt - 1, 4));
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
    setQuery(restoredQuery);
    setAnalysisTaskId(task.task_id);
    setAnalysisPlan(formatBackendPlan(restoredQuery, task.analysis_plan) || "历史执行未保存分析计划。");
    setAnalysisRows(mapBackendRows(task, restoredQuery));
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
    if (!window.confirm(`确认删除“${task.question || "未命名分析问题"}”这条执行记录吗？`)) return;
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

  return (
    <div className="p-7">
      <div className="mb-7 flex items-start justify-between gap-4">
        <div><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">智能分析</h2><p className="text-[13px] text-[#aeaeb2] mt-1">自然语言查询 · AI自动生成图表 · 智能归因分析</p></div>
        {activeView === "query" ? <button type="button" onClick={() => void toggleExecutionHistory()} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[12px] transition ${executionHistoryOpen ? "border-[#d1d1d6] bg-[#f2f2f7] text-[#1d1d1f]" : "border-[#e5e5ea] bg-white text-[#636366] hover:bg-[#f2f2f7]"}`}><History className="h-3.5 w-3.5" />执行记录</button> : null}
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
                    {!analysisInputCollapsed && (
                      <QueryReferenceOverlay
                        skills={availableAnalysisSkills}
                        query={query}
                        references={querySkillReferences}
                        openMenu={referenceMenu}
                        onOpenMenu={setReferenceMenu}
                        onCancelReference={cancelAutoReference}
                      />
                    )}
                    <textarea
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
                      className={`relative z-10 w-full resize-none bg-transparent px-0 py-0 text-[13px] leading-[1.5] outline-none placeholder:text-[#aeaeb2] focus:!outline-none focus:!shadow-none focus-visible:!outline-none focus-visible:!shadow-none ${
                        analysisInputCollapsed ? "h-6 min-h-[24px] overflow-hidden text-[#3a3a3c]" : "min-h-[32px]"
                      } ${
                        query && !analysisInputCollapsed ? "text-transparent caret-[#3a3a3c] selection:bg-[#dce9ff]" : "text-[#3a3a3c]"
                      }`}
                      style={query && !analysisInputCollapsed ? { WebkitTextFillColor: "transparent" } : undefined}
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
                          onSelect={setSelectedModel}
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
                        <button
                          type="button"
                          onClick={() => isAnalyzing ? void cancelActiveAnalysis() : void handleQuery()}
                          className="flex h-8 w-8 items-center justify-center rounded-full bg-[#8e8e93] text-white transition-colors hover:bg-[#636366]"
                          aria-label={isAnalyzing ? "取消分析" : "开始分析"}
                        >
                          {isAnalyzing ? <X className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
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
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-[#aeaeb2]" />
                    <h3 className="text-[13px] text-[#1d1d1f]">分析结果</h3>
                    <div className="flex gap-px bg-[#f2f2f7] rounded-md p-0.5 ml-1">
                      {[
                        { key: "thinking", label: "思考链" },
                        { key: "data", label: "查看数据" },
                        { key: "visual", label: "可视化分析" },
                        { key: "summary", label: "AI分析总结" },
                      ].map((tab) => (
                        <button
                          key={tab.key}
                          type="button"
                          onClick={() => setResultMode(tab.key as ResultMode)}
                          className={`px-2.5 py-1 rounded text-[11px] transition-all ${
                            resultMode === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#636366]"
                          }`}
                        >
                          {tab.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleSaveTarget("topic")}
                      className="flex items-center gap-1 px-3 py-1.5 border border-[#e5e5ea] rounded-lg text-[11px] text-[#636366] hover:bg-[#f2f2f7]"
                    >
                      <BookmarkPlus className="w-3 h-3" /> 存主题
                    </button>
                    <button
                      onClick={() => handleSaveTarget("experience")}
                      className="flex items-center gap-1 px-3 py-1.5 border border-[#e5e5ea] rounded-lg text-[11px] text-[#636366] hover:bg-[#f2f2f7]"
                    >
                      <Lightbulb className="w-3 h-3" /> 存经验
                    </button>
                    <button
                      onClick={() => handleSaveTarget("report")}
                      className="flex items-center gap-1 px-3 py-1.5 border border-[#e5e5ea] rounded-lg text-[11px] text-[#636366] hover:bg-[#f2f2f7]"
                    >
                      <BookmarkPlus className="w-3 h-3" /> 存周报
                    </button>
                    <button
                      onClick={() => void downloadAnalysisRows()}
                      className="flex items-center gap-1 px-3 py-1.5 border border-[#e5e5ea] rounded-lg text-[11px] text-[#636366] hover:bg-[#f2f2f7]"
                    >
                      <Download className="w-3 h-3" /> 导出
                    </button>
                  </div>
                </div>

                {saveMessage && (
                  <div className="mb-4 rounded-lg border border-[#d7efd9] bg-[#eef8f1] px-3 py-2 text-[12px] text-[#258a3f]">
                    {saveMessage}
                  </div>
                )}

                {resultMode === "thinking" ? (
                  <AnalysisProgressPanel steps={analysisProgressSteps} running={isAnalyzing} error={analysisError} hasResult={analysisRows.length > 0} />
                ) : resultMode === "summary" ? (
                  <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
                    <div className="mb-2 flex items-center gap-2 text-[12px] text-[#1d1d1f]">
                      <Lightbulb className="w-3.5 h-3.5 text-[#aeaeb2]" />
                      AI分析总结
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
                  <div className="grid gap-5 xl:grid-cols-2">
                    <AnalysisVisualCard
                      id="primary"
                      title={`主分析视图 · ${visualizationLabel(visualTypes.primary)}`}
                      type={visualTypes.primary}
                      rows={analysisRows}
                      open={openVisualMenu === "primary"}
                      onMenuToggle={() => setOpenVisualMenu((current) => (current === "primary" ? null : "primary"))}
                      onTypeChange={(type) => updateVisualType("primary", type)}
                    />
                    <AnalysisVisualCard
                      id="secondary"
                      title={`补充分析视图 · ${visualizationLabel(visualTypes.secondary)}`}
                      type={visualTypes.secondary}
                      rows={analysisRows}
                      open={openVisualMenu === "secondary"}
                      onMenuToggle={() => setOpenVisualMenu((current) => (current === "secondary" ? null : "secondary"))}
                      onTypeChange={(type) => updateVisualType("secondary", type)}
                    />
                  </div>
                ) : (
                  <RawDataTable rows={analysisRows} onDownload={() => void downloadAnalysisRows()} />
                )}

                <div className="mt-4 p-3 bg-[#fafbfc] rounded-lg border border-[#f0f0f2]">
                  <p className="text-[11px] text-[#8a8a8e] leading-[1.6]">
                    可视化图形用于解答上方分析问题；点击“查看数据”可查看这些图形对应的原始表格数据并下载。
                  </p>
                </div>
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
              <h3 className="text-[13px] text-[#1d1d1f]">我的报告</h3>
              <p className="mt-1 text-[11px] text-[#aeaeb2]">报告、最近查询和快捷键统一读取 Topic_Data 中保留的最新数据。</p>
            </div>
            <span className="rounded-md bg-[#f2f2f7] px-2 py-1 text-[11px] text-[#636366]">{visibleSavedAnalysisResults.length} 份</span>
          </div>
          <div className="mb-4 flex flex-wrap gap-1.5" aria-label="报告来源筛选">
            <button type="button" onClick={() => setReportSourceFilter("all")} className={`rounded-md px-2.5 py-1 text-[11px] transition-colors ${reportSourceFilter === "all" ? "bg-[#1d1d1f] text-white" : "bg-[#f2f2f7] text-[#636366] hover:bg-[#e5e5ea]"}`}>全部</button>
            {reportSourceOptions.map(([channel, label]) => (
              <button key={channel} type="button" onClick={() => setReportSourceFilter(channel)} className={`rounded-md px-2.5 py-1 text-[11px] transition-colors ${reportSourceFilter === channel ? "bg-[#1d1d1f] text-white" : "bg-[#f2f2f7] text-[#636366] hover:bg-[#e5e5ea]"}`}>{label}</button>
            ))}
          </div>
          {reportActionError && <div className="mb-3 rounded-lg border border-[#ffd0d0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#d93025]">{reportActionError}</div>}
          {reportActionNotice && <div className="mb-3 rounded-lg border border-[#d7efd9] bg-[#eef8f1] px-3 py-2 text-[11px] text-[#258a3f]">{reportActionNotice}</div>}
          <div className="space-y-1.5">
            {visibleSavedAnalysisResults.map((result) => (
              <div key={result.id} className="overflow-hidden rounded-lg bg-[#fafbfc]">
                <div
                  className="flex cursor-pointer items-center gap-3 p-3 transition-colors hover:bg-[#f2f2f7]"
                  role="button"
                  tabIndex={0}
                  onClick={() => { if (editingReportId !== result.id) void openSavedReport(result); }}
                  onKeyDown={(event) => { if (editingReportId !== result.id && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); void openSavedReport(result); } }}
                >
                  <Star className="w-4 h-4 shrink-0 text-[#c7c7cc]" />
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
                    <div className="grid gap-4 xl:grid-cols-2">
                      <AnalysisVisualCard id="primary" title={`主分析视图 · ${visualizationLabel(result.visualTypes.primary as VisualizationType)}`} type={result.visualTypes.primary as VisualizationType} rows={analysisRows} open={false} onMenuToggle={() => undefined} onTypeChange={() => undefined} />
                      <AnalysisVisualCard id="secondary" title={`补充分析视图 · ${visualizationLabel(result.visualTypes.secondary as VisualizationType)}`} type={result.visualTypes.secondary as VisualizationType} rows={analysisRows} open={false} onMenuToggle={() => undefined} onTypeChange={() => undefined} />
                    </div>
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

      {scriptEditorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4">
          <div className="w-full max-w-[1040px] rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
            <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
              <div>
                <h3 className="text-[14px] text-[#1d1d1f]">脚本编辑</h3>
                <p className="text-[11px] text-[#aeaeb2] mt-0.5">编辑分析思路、SQL、Python 可视化和 AI 总结后可保存或执行重跑</p>
              </div>
            </div>
            <div className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1.16fr)_minmax(300px,0.84fr)]">
              <div className="flex h-[470px] min-h-0 flex-col overflow-hidden rounded-lg border border-[#24252a] bg-[#101114]">
                <div className="flex gap-1 border-b border-white/10 bg-[#15161a] px-2 py-2">
                  {[
                    { key: "sql", label: "SQL" },
                    { key: "python", label: "Python" },
                    { key: "scenarios", label: "指标情景" },
                    { key: "summary", label: "AI总结" },
                  ].map((tab) => (
                    <button
                      key={tab.key}
                      type="button"
                      onClick={() => setActiveScriptTab(tab.key as ScriptTab)}
                      className={`rounded-md px-3 py-1.5 text-[12px] transition-colors ${
                        activeScriptTab === tab.key
                          ? "bg-white text-[#1d1d1f]"
                          : "text-[#c7c7cc] hover:bg-white/10 hover:text-white"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <textarea
                  value={
                    activeScriptTab === "sql"
                      ? sqlScript
                      : activeScriptTab === "python"
                        ? pythonScript
                        : activeScriptTab === "scenarios"
                          ? analysisScenarios
                          : analysisSummary
                  }
                  onChange={(event) => {
                    if (activeScriptTab === "sql") setSqlScript(event.target.value);
                    else if (activeScriptTab === "python") setPythonScript(event.target.value);
                    else if (activeScriptTab === "scenarios") setAnalysisScenarios(event.target.value);
                    else setAnalysisSummary(event.target.value);
                  }}
                  className="min-h-0 flex-1 resize-none bg-[#101114] px-4 py-3 font-mono text-[12px] leading-[1.7] text-[#f5f5f7] outline-none"
                />
              </div>
              <div className="flex min-h-[470px] flex-col rounded-lg border border-[#e5e5ea] bg-[#fafbfc] p-4">
                <label className="mb-3 block">
                  <span className="mb-1 block text-[12px] text-[#1d1d1f]">分析思路名称</span>
                  <input
                    value={scriptPlanName}
                    onChange={(event) => setScriptPlanName(event.target.value)}
                    className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
                  />
                </label>
                <div className="mb-2 text-[12px] text-[#1d1d1f]">分析思路</div>
                <textarea
                  value={analysisPlan}
                  onChange={(event) => setAnalysisPlan(event.target.value)}
                  placeholder="写清楚分析目的、指标、维度、筛选条件、校验规则和输出口径。"
                  className="min-h-[330px] flex-1 rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[13px] text-[#3a3a3c] leading-[1.7] outline-none focus:border-[#c7c7cc] resize-none"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-[#f0f0f2] px-5 py-4">
              <button
                type="button"
                onClick={() => setScriptEditorOpen(false)}
                className="rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[13px] text-[#636366] hover:bg-[#f2f2f7]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => {
                  setSaveMessage("修改已保留在当前编辑会话；点击“执行”后才会生成受治理的新 revision");
                  setScriptEditorOpen(false);
                }}
                className="rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[13px] text-[#1d1d1f] hover:bg-[#f2f2f7]"
              >
                保存
              </button>
              <button
                type="button"
                onClick={() => {
                  setScriptEditorOpen(false);
                  void rerunAnalysis();
                }}
                className="rounded-lg bg-[#1d1d1f] px-4 py-2 text-[13px] text-white hover:bg-[#2c2c2e]"
              >
                执行
              </button>
            </div>
          </div>
        </div>
      )}
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

function detectedAnalysisInstitution(files: KnowledgeFileAttachment[], currentInstitution: string) {
  const detected = Array.from(new Set(files.flatMap((file) => file.detectedInstitutions || detectAttachmentInstitutions(file.name, file.contentPreview || ""))));
  return detected.length === 1 ? detected[0] : currentInstitution;
}
