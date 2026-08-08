import { useEffect, useRef, useState, type ClipboardEvent, type ReactNode } from "react";
import { useLocation } from "react-router";
import { usePlatformContext } from "../../platform/PlatformContext";
import { operatingTenantNames } from "../../data/operatingTenants";
import type { MetricDictionaryItem } from "../../data/metricDictionary";
import {
  cancelAsyncAnalysisRun,
  waitForSelfAnalysis,
  type BackendAnalysisPlan,
  type BackendAnalysisResponse,
} from "../../services/analysisApi";
import { fetchMetricDictionary } from "../../services/metricDictionaryApi";
import { fetchSavedAnalysisResults, saveSavedAnalysisResult } from "../../services/reportApi";
import {
  fetchDataAssets,
  saveDataAssetItem,
  type RawTableAsset,
  type TopicTableAsset,
} from "../../services/dataAssetApi";
import { apiErrorMessage, getApiBaseUrl } from "../../services/apiClient";
import { demoFallbackDisabledMessage } from "../../services/apiContext";
import { runApplicationAction } from "../../services/applicationApi";
import { fetchSystemConfig, type ModelIntegration } from "../../services/systemConfigApi";
import {
  ArrowUp,
  AudioLines,
  Sparkles,
  Clock,
  Star,
  ArrowUpRight,
  BarChart3,
  PieChartIcon,
  TrendingUp,
  Table2,
  Download,
  BookmarkPlus,
  History,
  Lightbulb,
  ChevronDown,
  Code2,
  Mic,
  Plus,
  Upload,
  X,
  ChevronsDown,
  ChevronsUp,
} from "lucide-react";

export type VisualizationType = "table" | "column" | "bar" | "line" | "radar";
export type ResultVisualKey = "primary" | "secondary";
export type ResultMode = "thinking" | "visual" | "data" | "summary";
export type SaveTarget = "report" | "topic" | "experience";
export type SelfAnalysisSection = "query" | "reports";
export type ScriptTab = "sql" | "python" | "scenarios" | "summary";
export type AnalysisSkillOption = {
  id: string;
  name: string;
  category: "场景" | "主题" | "模式";
  description: string;
  memoryRefs?: string[];
  toolRefs?: string[];
  analysisMethod?: string;
  documentAbstraction?: string;
  outputFormat?: string;
  viewpointStrategy?: string;
  recommendedSkillIds?: string[];
};
export type QuerySkillReference = {
  skill: AnalysisSkillOption;
  start: number;
  end: number;
  text: string;
};
export type QueryReferenceMenuState = {
  skillId: string;
  x: number;
  y: number;
} | null;
export type AnalysisConversationTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  query?: string;
  summary?: string;
  sql?: string;
  analysisPlan?: string;
};
export type AnalysisConversationState = {
  sessionId: string;
  draft: string;
  turns: AnalysisConversationTurn[];
  updatedAt: string;
};
export type FunAsrInputTarget = "query" | "voice";
export type AnalysisRunTrigger = "manual" | "realtime_voice_silence" | "realtime_voice_keyword" | "popup_voice";
export type AnalysisTopicShortcut = {
  id: string;
  title: string;
  query: string;
  method: string;
  sql: string;
  conclusionMode: string;
  summary: string;
  createdAt: string;
  updatedAt: string;
  hidden?: boolean;
  skillIds?: string[];
  tableIds?: string[];
  memoryIds?: string[];
};
export type TopicShortcutMenuState = {
  id: string;
  x: number;
  y: number;
} | null;
export type KnowledgeFileAttachment = {
  id: string;
  name: string;
  size: number;
  type: string;
  lastModified: number;
  contentPreview?: string;
  detectedInstitutions?: string[];
};
export type AnalysisDataTableSelection = {
  id: string;
  kind: "raw" | "topic";
  name: string;
  code: string;
  description: string;
  sql: string;
  fields: string;
  datasetId?: string;
  metricCodes?: string[];
  defaultMetrics?: string[];
  dimensionCodes?: string[];
  defaultDimensions?: string[];
  chartTypes?: string[];
};
export type AnalysisRow = {
  branch: string;
  productLine: string;
  customerSegment: string;
  amount: number;
  metricName: string;
  metricUnit: string;
  raw: Record<string, unknown>;
  completion: string;
  conversion: string;
  overdueRate: string;
  weekChange: string;
};

export type AudioContextConstructorLike = new (options?: AudioContextOptions) => AudioContext;

export type FunAsrContextMessage = {
  role: "user" | "assistant";
  content: Array<{
    type: "input_text" | "text";
    text: string;
  }>;
};

export type FunAsrProxyEvent = {
  type?: "connected" | "config" | "ready" | "transcript" | "finished" | "error" | "pong";
  text?: string;
  final?: boolean;
  message?: string;
  provider?: string;
  integrationId?: string;
  integrationName?: string;
  model?: string;
};

export const realtimeVoiceSilenceAnalysisMs = 5_000;

export type SavedAnalysisResult = {
  id: string;
  title: string;
  query: string;
  plan: string;
  summary: string;
  visualTypes: Record<ResultVisualKey, VisualizationType>;
  savedAt: string;
  rows: unknown[];
  analysisTaskId: string;
  analysisInstitution?: string;
  currentInstitution?: string;
  uploadedDataInstitutions?: string[];
  weeklyReportEligible?: boolean;
  weeklyReportSavedAt?: string;
  visibility?: "private" | "tenant";
  ownerUserId?: string;
  updatedBy?: string;
  source?: {
    channel: string;
    label: string;
    bindingId?: string;
    runId?: string;
    reportId?: string;
    url?: string;
  } | null;
  topicData?: {
    reference_type: "history" | "shortcut" | "topic" | "report";
    reference_id: string;
    folder: string;
    updated_at: string;
    row_count: number;
    has_data: boolean;
    version_count: 1;
  };
};

export const savedAnalysisStorageKey = "smart_data_agent_saved_analysis_results";
export const analysisConversationSessionStoragePrefix = "smart_data_agent_self_analysis_session_v1";
export const analysisConversationStoragePrefix = "smart_data_agent_self_analysis_conversation_v1";
export const analysisTopicShortcutStoragePrefix = "smart_data_agent_self_analysis_topics_v1";
export const funAsrSampleRate = 16000;

export function scopedStorageKey(prefix: string, tenantId: string, userId: string, suffix = "") {
  const safeTenant = tenantId || "tenant_unknown";
  const safeUser = userId || "user_unknown";
  return [prefix, safeTenant, safeUser, suffix].filter(Boolean).join(":");
}

export function createConversationSessionId() {
  return `analysis_session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function ensureAnalysisConversationSessionId(tenantId: string, userId: string) {
  const key = scopedStorageKey(analysisConversationSessionStoragePrefix, tenantId, userId);
  const existing = window.sessionStorage.getItem(key);
  if (existing) return existing;
  const next = createConversationSessionId();
  window.sessionStorage.setItem(key, next);
  return next;
}

export function conversationStorageKey(tenantId: string, userId: string, sessionId: string) {
  return scopedStorageKey(analysisConversationStoragePrefix, tenantId, userId, sessionId);
}

export function topicShortcutStorageKey(tenantId: string, userId: string) {
  return scopedStorageKey(analysisTopicShortcutStoragePrefix, tenantId, userId);
}

export function loadConversationState(tenantId: string, userId: string, sessionId: string): AnalysisConversationState {
  try {
    const raw = window.localStorage.getItem(conversationStorageKey(tenantId, userId, sessionId));
    if (!raw) {
      return { sessionId, draft: "", turns: [], updatedAt: new Date().toISOString() };
    }
    const parsed = JSON.parse(raw) as Partial<AnalysisConversationState>;
    return {
      sessionId,
      draft: typeof parsed.draft === "string" ? parsed.draft : "",
      turns: Array.isArray(parsed.turns) ? parsed.turns.filter(isConversationTurn).slice(-30) : [],
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : new Date().toISOString(),
    };
  } catch {
    return { sessionId, draft: "", turns: [], updatedAt: new Date().toISOString() };
  }
}

export function saveConversationState(tenantId: string, userId: string, state: AnalysisConversationState) {
  window.localStorage.setItem(
    conversationStorageKey(tenantId, userId, state.sessionId),
    JSON.stringify({
      ...state,
      turns: state.turns.slice(-30),
      updatedAt: new Date().toISOString(),
    }),
  );
}

export function isConversationTurn(value: unknown): value is AnalysisConversationTurn {
  if (!value || typeof value !== "object") return false;
  const turn = value as Partial<AnalysisConversationTurn>;
  return (turn.role === "user" || turn.role === "assistant") && typeof turn.content === "string";
}

export function loadAnalysisTopicShortcuts(tenantId: string, userId: string): AnalysisTopicShortcut[] {
  try {
    const raw = window.localStorage.getItem(topicShortcutStorageKey(tenantId, userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter(isAnalysisTopicShortcut).map(normalizeStoredAnalysisTopicShortcut).slice(0, 40)
      : [];
  } catch {
    return [];
  }
}

export function saveAnalysisTopicShortcuts(tenantId: string, userId: string, shortcuts: AnalysisTopicShortcut[]) {
  window.localStorage.setItem(topicShortcutStorageKey(tenantId, userId), JSON.stringify(shortcuts.slice(0, 40)));
}

export function isAnalysisTopicShortcut(value: unknown): value is AnalysisTopicShortcut {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<AnalysisTopicShortcut>;
  return typeof item.id === "string" && typeof item.title === "string" && typeof item.query === "string";
}

export function normalizeStoredAnalysisTopicShortcut(shortcut: AnalysisTopicShortcut): AnalysisTopicShortcut {
  const normalizedTitle = shortcut.title.replace(/\s+/g, " ").trim();
  const normalizedQuery = shortcut.query.replace(/\s+/g, " ").trim();
  if (!normalizedQuery || normalizedTitle !== normalizedQuery) return shortcut;
  const summary = typeof shortcut.summary === "string" ? shortcut.summary : "";
  const method = typeof shortcut.method === "string" ? shortcut.method : "";
  const abstractTitle =
    cleanAnalysisTopicCandidate(summary.split(/[。；\n]/)[0] || "") ||
    cleanAnalysisTopicCandidate(method.split(/[。；\n]/)[0] || "") ||
    "历史分析主题";
  return {
    ...shortcut,
    title: abstractTitle.slice(0, 36),
  };
}

export function getSelfAnalysisSection(pathname: string): SelfAnalysisSection {
  return pathname.endsWith("/reports") ? "reports" : "query";
}

export function formatTopicFields(fields: TopicTableAsset["fields"]) {
  if (Array.isArray(fields)) {
    return fields.map((field) => `${field.fieldNameEn}(${field.fieldNameCn})`).join(", ");
  }
  return String(fields || "");
}

export function rawTableToSelection(table: RawTableAsset): AnalysisDataTableSelection {
  const fields = table.fields.map((field) => `${field.fieldNameEn}(${field.fieldNameCn}:${field.type})`).join(", ");
  const sql = table.exampleSql?.trim() || `SELECT *\nFROM ${table.tableNameEn}\nLIMIT 100;`;
  return {
    id: table.id,
    kind: "raw",
    name: table.tableNameCn,
    code: table.tableNameEn,
    description: table.description,
    sql,
    fields,
  };
}

export function topicTableToSelection(topic: TopicTableAsset): AnalysisDataTableSelection {
  return {
    id: topic.id,
    kind: "topic",
    name: topic.name,
    code: topic.code,
    description: topic.description,
    sql: topic.sql,
    fields: formatTopicFields(topic.fields),
    datasetId: topic.datasetId,
    metricCodes: topic.metricCodes,
    defaultMetrics: topic.defaultMetrics,
    dimensionCodes: topic.dimensionCodes,
    defaultDimensions: topic.defaultDimensions,
    chartTypes: topic.chartTypes,
  };
}

export function formatSelectedDataTables(tables: AnalysisDataTableSelection[]) {
  if (!tables.length) return "";
  return tables
    .map((table, index) => {
      return `数据表${index + 1}：${table.name}（${table.kind === "raw" ? "原始表" : "主题表"} / ${table.code}）
说明：${table.description}
字段：${table.fields}
SQL：
${table.sql}`;
    })
    .join("\n---\n");
}

export function isAutoReferenceSkill(skill: AnalysisSkillOption) {
  return autoReferenceSkillCategories.includes(skill.category);
}

export function skillReferenceAliases(skill: AnalysisSkillOption) {
  const aliases = [skill.name];
  const withoutAnalysis = skill.name.replace(/分析$/, "");
  if (withoutAnalysis && withoutAnalysis !== skill.name && withoutAnalysis.length >= 2) {
    aliases.push(withoutAnalysis);
  }
  return Array.from(new Set(aliases)).sort((a, b) => b.length - a.length);
}

export function buildQuerySkillReferences(
  query: string,
  dismissedIds: Set<string>,
  skillOptions: AnalysisSkillOption[] = analysisSkillOptions,
) {
  if (!query.trim()) return [];
  const candidates: QuerySkillReference[] = [];
  skillOptions.filter(isAutoReferenceSkill).forEach((skill) => {
    if (dismissedIds.has(skill.id)) return;
    skillReferenceAliases(skill).forEach((alias) => {
      let offset = 0;
      while (offset < query.length) {
        const index = query.indexOf(alias, offset);
        if (index < 0) break;
        candidates.push({
          skill,
          start: index,
          end: index + alias.length,
          text: query.slice(index, index + alias.length),
        });
        offset = index + Math.max(alias.length, 1);
      }
    });
  });

  const selected: QuerySkillReference[] = [];
  candidates
    .sort((a, b) => b.end - b.start - (a.end - a.start) || a.start - b.start)
    .forEach((candidate) => {
      const overlaps = selected.some((item) => candidate.start < item.end && candidate.end > item.start);
      if (!overlaps) selected.push(candidate);
    });
  return selected.sort((a, b) => a.start - b.start || a.end - b.end);
}

export function uniqueSkills(skills: Array<AnalysisSkillOption | null | undefined>) {
  const seen = new Set<string>();
  return skills.filter((skill): skill is AnalysisSkillOption => {
    if (!skill || seen.has(skill.id)) return false;
    seen.add(skill.id);
    return true;
  });
}

export function sameStringSet(a: Set<string>, b: Set<string>) {
  if (a.size !== b.size) return false;
  for (const value of a) {
    if (!b.has(value)) return false;
  }
  return true;
}

export function getAudioContextConstructor() {
  const audioWindow = window as Window & {
    webkitAudioContext?: AudioContextConstructorLike;
  };
  return window.AudioContext ?? audioWindow.webkitAudioContext;
}

export function normalizeVoiceSegment(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

export function appendRealtimeVoiceText(baseText: string, recognizedText: string) {
  const cleanRecognized = normalizeVoiceSegment(recognizedText);
  if (!cleanRecognized) return baseText;
  const cleanBase = baseText.trimEnd();
  if (!cleanBase) return cleanRecognized;
  const separator = /[\s，。！？；、：,.!?;:]$/.test(cleanBase) ? "" : " ";
  return `${cleanBase}${separator}${cleanRecognized}`;
}

export function buildFunAsrRealtimeUrl(tenantId: string, userId: string, applicationModule: string) {
  const apiBase = getApiBaseUrl();
  const baseUrl = apiBase
    ? new URL(apiBase)
    : new URL(window.location.origin);
  baseUrl.protocol = baseUrl.protocol === "https:" ? "wss:" : "ws:";
  baseUrl.pathname = "/api/asr/fun-asr/realtime";
  baseUrl.search = "";
  baseUrl.searchParams.set("tenant_id", tenantId);
  baseUrl.searchParams.set("user_id", userId);
  baseUrl.searchParams.set("application_module", applicationModule);
  return baseUrl.toString();
}

export function buildFunAsrContext(
  turns: AnalysisConversationTurn[],
  skills: AnalysisSkillOption[],
): FunAsrContextMessage[] {
  const messages: FunAsrContextMessage[] = [];
  turns.slice(-8).forEach((turn) => {
    const text = normalizeVoiceSegment(turn.content).slice(0, 400);
    if (!text) return;
    messages.push({
      role: turn.role,
      content: [
        {
          type: turn.role === "user" ? "input_text" : "text",
          text,
        },
      ],
    });
  });
  const skillText = uniqueSkills(skills)
    .map((skill) => `${skill.name}:${skill.description}`)
    .join("；")
    .slice(0, 400);
  if (skillText) {
    messages.push({
      role: "user",
      content: [{ type: "input_text", text: `银行经营分析词表：${skillText}` }],
    });
  }
  return messages.slice(-10);
}

export function downsampleToPcm16(input: Float32Array, inputSampleRate: number, outputSampleRate: number) {
  if (outputSampleRate >= inputSampleRate) {
    return floatToPcm16(input);
  }
  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.max(1, Math.floor(input.length / ratio));
  const output = new Float32Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) {
      sum += input[inputIndex];
      count += 1;
    }
    output[index] = count ? sum / count : input[start] || 0;
  }
  return floatToPcm16(output);
}

export function floatToPcm16(input: Float32Array) {
  const output = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index] || 0));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

export function audioSignature(channel: Float32Array) {
  if (!channel.length) return { rms: 0, zeroCrossingRate: 0 };
  let energy = 0;
  let zeroCrossings = 0;
  let previous = channel[0] || 0;
  for (let index = 0; index < channel.length; index += 1) {
    const value = channel[index] || 0;
    energy += value * value;
    if ((value >= 0) !== (previous >= 0)) zeroCrossings += 1;
    previous = value;
  }
  return {
    rms: Math.sqrt(energy / channel.length),
    zeroCrossingRate: zeroCrossings / channel.length,
  };
}

export function funAsrErrorMessage(message: string) {
  const normalized = message.toLowerCase();
  if (normalized.includes("permission denied") || normalized.includes("notallowederror")) {
    return "浏览器未获得麦克风权限，但不影响文字分析；可授权麦克风后重试。";
  }
  if (
    message.includes("dashscope_api_key_missing")
    || message.includes("fun_asr_api_key_missing")
    || message.includes("fun_asr_configuration_missing")
  ) {
    return "当前机构未配置阿里云 Fun-ASR。请保存并启用 API 地址和密钥；不影响文字分析。";
  }
  if (message.includes("fun_asr_configuration_not_verified") || message.includes("fun_asr_configuration_invalid")) {
    return "阿里云 Fun-ASR 当前仍是演示配置，请换成真实 API 密钥；保存后可直接使用，无需连通性测试。";
  }
  if (message.includes("fun_asr_authentication_failed")) {
    return "阿里云 Fun-ASR 鉴权失败，请检查“语音转文字”Tab 中的 API 密钥是否有效。";
  }
  if (message.includes("fun_asr_egress_rejected")) {
    return "阿里云 Fun-ASR 地址未通过服务端出站安全校验，请检查语音模型 API 地址。";
  }
  if (message.includes("fun_asr_connection_timeout") || message.includes("fun_asr_dns_failed")) {
    return "服务端无法连接阿里云 Fun-ASR，请检查网络、DNS 和语音模型 API 地址。";
  }
  if (
    message.includes("fun_asr_proxy_failed") ||
    message.includes("fun_asr_connection_error") ||
    message.includes("fun_asr_task_failed")
  ) {
    return `阿里云 Fun-ASR 本次连接失败（${message || "fun_asr_proxy_failed"}）；不影响文字分析，可检查地址、密钥或服务端网络后重试。`;
  }
  return message || "实时语音已中断，可继续编辑文字。";
}

export function formatConversationContext(
  sessionId: string,
  turns: AnalysisConversationTurn[],
  currentQuestion: string,
  compressionEnabled: boolean,
) {
  return {
    session_id: sessionId,
    current_question: currentQuestion,
    turn_count: turns.length,
    compression_enabled: compressionEnabled,
    turns: turns.slice(-12),
  };
}

export function makeConversationTurn(
  role: AnalysisConversationTurn["role"],
  content: string,
  extra: Partial<AnalysisConversationTurn> = {},
): AnalysisConversationTurn {
  return {
    id: `turn_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    role,
    content,
    createdAt: new Date().toISOString(),
    ...extra,
  };
}

export function extractPlanLine(plan: string, label: string) {
  return plan
    .split("\n")
    .find((line) => line.startsWith(label))
    ?.replace(label, "")
    .trim() || "";
}

export function cleanAnalysisTopicCandidate(value: string) {
  return value
    .replace(/^(核心结论|分析主题|主题表|分析目标|业务焦点|核心指标|分析思路)[:：]/, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildAnalysisTopicTitle({
  plan,
  summary,
  skills,
  topicName,
}: {
  plan: string;
  summary: string;
  skills: AnalysisSkillOption[];
  topicName?: string;
}) {
  const focusSkill = skills.find((skill) => skill.category === "场景") ?? skills.find((skill) => skill.category === "主题");
  const planLead =
    ["分析主题：", "主题表：", "分析目标：", "业务焦点：", "核心指标：", "分析思路："]
      .map((label) => cleanAnalysisTopicCandidate(extractPlanLine(plan, label)))
      .find(Boolean) || "";
  const summaryLead = cleanAnalysisTopicCandidate(summary.split(/[。；\n]/)[0] || "");
  const base = cleanAnalysisTopicCandidate(topicName || planLead || summaryLead || focusSkill?.name || "智能分析主题");
  const prefix = focusSkill && base !== focusSkill.name ? `${focusSkill.name} · ` : "";
  return `${prefix}${base}`.slice(0, 36);
}

export function buildAnalysisTopicShortcut({
  question,
  plan,
  sql,
  summary,
  skills,
  response,
  topicName,
}: {
  question: string;
  plan: string;
  sql: string;
  summary: string;
  skills: AnalysisSkillOption[];
  response?: BackendAnalysisResponse;
  topicName?: string;
}): AnalysisTopicShortcut {
  const approach = response?.intelligent_analysis?.analysis_approach?.join("；") || extractPlanLine(plan, "分析思路：") || "按指标、维度、SQL结果和可视化证据生成分析结论。";
  const conclusionMode =
    response?.intelligent_analysis?.possible_conclusions?.length
      ? "基于智能分析引擎的可能结论、SQL结果和Python可视化结果生成。"
      : "基于SQL聚合结果、图表趋势和分析思路生成。";
  const now = new Date().toISOString();
  return {
    id: `analysis_topic_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    title: buildAnalysisTopicTitle({ plan, summary, skills, topicName }),
    query: question,
    method: approach,
    sql,
    conclusionMode,
    summary,
    createdAt: now,
    updatedAt: now,
  };
}

export const suggestedQuestions = [
  { q: "本月各分行放款金额排名TOP10", category: "机构分析", icon: BarChart3 },
  { q: "消费贷和经营贷的逾期率对比趋势", category: "风险分析", icon: TrendingUp },
  { q: "25-35岁客群的转化漏斗分析", category: "客群分析", icon: PieChartIcon },
  { q: "线上渠道获客成本和ROI月度变化", category: "渠道分析", icon: BarChart3 },
  { q: "各产品动支率影响因素归因分析", category: "归因分析", icon: Lightbulb },
  { q: "本季度经营指标完成情况汇总", category: "经营分析", icon: Table2 },
];

export const analysisSkillOptions: AnalysisSkillOption[] = [
  { id: "weekly-report", name: "周报分析", category: "场景", description: "按周报结构输出业绩、波动、风险与行动项。" },
  { id: "daily-operation", name: "运营日常分析", category: "场景", description: "围绕日常经营指标监控、异常解释和跟进动作。" },
  { id: "risk-strategy", name: "风险策略分析", category: "场景", description: "结合准入、逾期、迁徙和策略命中进行分析。" },
  { id: "descriptive", name: "描述性分析", category: "主题", description: "描述数据分布、规模、结构和变化。" },
  { id: "attribution", name: "归因分析", category: "主题", description: "拆解指标变化贡献和可能原因。" },
  { id: "forecast", name: "预测分析", category: "主题", description: "结合历史趋势预测后续走势。" },
  { id: "exploratory", name: "探索性分析", category: "主题", description: "自动探索相关维度、异常点和潜在线索。" },
  { id: "budget", name: "财务预算分析", category: "主题", description: "测算预算达成、缺口和资源配置效率。" },
  { id: "credit-risk", name: "信用风险分析", category: "主题", description: "围绕信用风险、违约概率和授信质量交叉验证。" },
  { id: "suspicious-transaction", name: "可疑交易分析", category: "主题", description: "识别可疑交易模式和异常资金行为。" },
  { id: "liquidity-risk", name: "流动性风险分析", category: "主题", description: "评估资金流动性、集中度和压力信号。" },
  { id: "overdue-risk", name: "逾期风险分析", category: "主题", description: "拆解逾期指标、迁徙趋势和重点客群风险。" },
  { id: "goal-mode", name: "目标模式", category: "模式", description: "围绕目标拆解差距、路径和达成条件。" },
  { id: "plan-mode", name: "计划模式", category: "模式", description: "将分析结果转成计划、节奏和任务安排。" },
  { id: "loop-mode", name: "LOOP模式", category: "模式", description: "按观察、判断、行动、复盘循环推进分析。" },
  { id: "context-compression", name: "上下文压缩", category: "模式", description: "将长会话压缩为关键问题、SQL、结论和后续动作。" },
];

export const fallbackAnalysisModels: ModelIntegration[] = [];

export type AnalysisModelOption = {
  id: string;
  label: string;
  value: string;
  model: ModelIntegration;
};

export type AnalysisModelGroup = {
  id: string;
  category: string;
  options: AnalysisModelOption[];
};

export function displayAnalysisModelName(value: string) {
  const normalized = value.trim().replace(/_/g, "-").replace(/\s+/g, "-");
  if (!normalized) return "未命名";
  return normalized
    .split("-")
    .filter(Boolean)
    .map((part) => {
      if (/^gpt$/i.test(part)) return "GPT";
      if (/^glm$/i.test(part)) return "GLM";
      if (/^qwen$/i.test(part)) return "Qwen";
      if (/^deepseek$/i.test(part)) return "Deepseek";
      return part;
    })
    .join("-");
}

export function analysisModelValues(model: ModelIntegration) {
  const enabled = (model.enabledModels || [])
    .map((value) => value.trim())
    .filter(Boolean);
  const available = (model.availableModels || [])
    .map((value) => value.trim())
    .filter(Boolean);
  const values = enabled.length ? enabled : available;
  return Array.from(new Set(values));
}

export function groupAnalysisModelOptions(models: ModelIntegration[]): AnalysisModelGroup[] {
  const relayGroups: AnalysisModelGroup[] = [];
  const otherOptions: AnalysisModelOption[] = [];
  models.forEach((model) => {
    const isRelay = model.modelName.trim() === "中转站";
    const options = analysisModelValues(model).map((value) => ({
      id: `${model.id}::${value}`,
      label: isRelay ? displayAnalysisModelName(value) : `${model.name} · ${displayAnalysisModelName(value)}`,
      value,
      model,
    }));
    if (!options.length) return;
    if (isRelay) {
      relayGroups.push({ id: model.id, category: model.name, options });
      return;
    }
    otherOptions.push(...options);
  });
  if (otherOptions.length) {
    relayGroups.push({ id: "other", category: "其他", options: otherOptions });
  }
  return relayGroups;
}

export function createSelectedAnalysisModel(option: AnalysisModelOption): ModelIntegration {
  return {
    ...option.model,
    id: option.model.id,
    name: option.label,
    selectedModelName: option.value,
    availableModels: option.model.availableModels?.length ? option.model.availableModels : [option.value],
    enabledModels: [option.value],
  };
}

export function firstSelectableAnalysisModel(models: ModelIntegration[]) {
  const firstOption = groupAnalysisModelOptions(models)[0]?.options[0];
  return firstOption ? createSelectedAnalysisModel(firstOption) : null;
}

export function hasSelectableAnalysisModel(models: ModelIntegration[], selected: ModelIntegration) {
  return groupAnalysisModelOptions(models).some((group) =>
    group.options.some(
      (option) =>
        (option.model.id === selected.id && option.value === (selected.selectedModelName || selected.enabledModels?.[0])) ||
        option.id === selected.id,
    ),
  );
}

export const autoReferenceSkillCategories: AnalysisSkillOption["category"][] = ["场景", "主题"];

export const visualizationOptions: { type: VisualizationType; label: string; icon: typeof Table2 }[] = [
  { type: "line", label: "趋势图", icon: TrendingUp },
  { type: "column", label: "柱状图", icon: BarChart3 },
  { type: "table", label: "多维表格", icon: Table2 },
];

function normalizedVisualizationType(type?: string): "line" | "column" | "table" | null {
  const normalized = String(type || "").trim().toLowerCase();
  if (normalized === "line") return "line";
  if (normalized === "column" || normalized === "bar") return "column";
  if (normalized === "table" || normalized === "radar" || normalized === "pie") return "table";
  return null;
}

export function inferVisualTypes(
  question: string,
  tables: AnalysisDataTableSelection[] = [],
): Record<ResultVisualKey, VisualizationType> {
  const tableContext = tables.flatMap((table) => [table.name, table.code, table.description, table.fields]).join(" ");
  const configuredTypes = Array.from(new Set(
    tables.flatMap((table) => table.chartTypes || []).map(normalizedVisualizationType).filter(
      (type): type is "line" | "column" | "table" => Boolean(type),
    ),
  ));
  const hasQuestionTime = /趋势|走势|变化|波动|连续|环比|同比|月度|季度|年度|每日|每周|每月|日期|时间|上升|下降/i.test(question);
  const isQuestionDetail = /多维|交叉|明细|清单|台账|列表|汇总|完成情况|数据核对/i.test(question);
  const isQuestionComparison = /排名|排行|TOP|分行|机构|客群|画像|结构|漏斗|归因|因素|对比|比较|成本|ROI|动支率|逾期率|产品|渠道/i.test(question);
  const tableHasTimeDimension = /月度|季度|年度|日期|时间|month|week|date|year/i.test(tableContext);
  const tableSuggestsComparison = /机构|分行|客群|产品|渠道|行业|风险|漏斗|对比|排名/i.test(tableContext);

  let primary: "line" | "column" | "table";
  if (hasQuestionTime) primary = "line";
  else if (isQuestionDetail && !isQuestionComparison) primary = "table";
  else if (isQuestionComparison) primary = "column";
  else if (configuredTypes[0]) primary = configuredTypes[0];
  else if (tableHasTimeDimension) primary = "line";
  else primary = tableSuggestsComparison ? "column" : "table";

  const secondary = configuredTypes.find((type) => type !== primary)
    || (primary === "table" ? (hasQuestionTime || tableHasTimeDimension ? "line" : "column") : "table");
  return { primary, secondary };
}

export function visualizationLabel(type: VisualizationType) {
  if (type === "bar") return "柱状图";
  if (type === "radar") return "多维表格";
  return visualizationOptions.find((option) => option.type === type)?.label ?? "图表";
}

export function createAnalysisPlan(question: string, visualTypes: Record<ResultVisualKey, VisualizationType>) {
  const normalized = question.trim();
  const dimension = /客群|年龄|画像/.test(normalized)
    ? "客群、年龄段、产品偏好、授信阶段"
    : /渠道|ROI|成本/.test(normalized)
      ? "渠道、月份、获客来源、产品线"
      : /趋势|逾期|动支|风险/.test(normalized)
        ? "产品线、时间周期、风险等级、机构"
        : "机构、产品线、客群、时间周期";
  const metrics = /逾期|风险/.test(normalized)
    ? "M1逾期率、余额、环比变化、客户数、风险迁徙率"
    : /ROI|成本|渠道/.test(normalized)
      ? "获客成本、ROI、进件转化率、投放金额、有效授信率"
      : "放款金额、余额达成率、周净增、动支率、进件转化率";
  const angleCount = /归因|原因|因素|客群|画像/.test(normalized) ? 3 : 2;
  const analysisAngles =
    angleCount === 3
      ? "1）规模与达成：识别放款、余额和周净增的头尾差异；2）转化与动支：拆分进件、授信、额度确认、动支链路；3）风险与客群：结合消费贷/经营贷客群结构和M1变化定位风险压力。"
      : "1）规模与达成：对比机构和产品线贡献；2）转化与风险：结合动支、转化率和M1逾期率校验增长质量。";

  return `查询问题：${question}
分析维度：${dimension}
应用指标：${metrics}
建议图形：${angleCount}个分析角度，默认输出${visualizationLabel(visualTypes.primary)}和${visualizationLabel(visualTypes.secondary)}；根据时间、对比和明细主题在趋势图、柱状图、多维表格之间调整。
分析思路：${analysisAngles}
专业关注点：消费贷可关注获客转化、客群风险和额度使用效率；经营贷可关注经营资料、续贷留存、行业风险和动支节奏。
请求草案：以上内容仅用于向服务端表达分析意图，不是执行结果或业务结论。`;
}

export function backendDisplayValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function appendMetricReferences(plan: string, question: string, metrics: MetricDictionaryItem[]) {
  const referenced = metrics.filter((metric) => {
    const metricName = metric.metricName.trim();
    const metricId = metric.metricId.trim();
    return (metricName && question.includes(metricName)) || (metricId && question.includes(metricId));
  });
  if (!referenced.length) return plan;
  const referenceLine = `指标字典引用：${referenced.map((metric) => `${metric.metricName}(${metric.metricId})`).join("、")}`;
  return plan.includes("指标字典引用：")
    ? plan.replace(/指标字典引用：.*/, referenceLine)
    : `${plan}\n${referenceLine}`;
}

export function formatBackendPlan(question: string, plan?: BackendAnalysisPlan) {
  if (!plan) return "";
  return `查询问题：${question}
分析数据集：${plan.dataset_id ?? "未识别"}
分析维度：${(plan.dimensions ?? []).join("、") || "未识别"}
应用指标：${(plan.metrics ?? []).join("、") || "未识别"}
建议图形：${(plan.chart_types ?? []).join("、") || "table"}
分析思路：${(plan.analysis_angles ?? []).join("；") || "按核心指标和维度聚合分析。"}
专业判断：${plan.business_focus ?? "消费贷和经营贷需分别关注转化、动支、风险和经营稳定性。"}
结论状态：尚未形成；只有服务端完成真实执行、证据绑定与复核后才展示业务结论。`;
}

export function mapBackendRows(response: BackendAnalysisResponse, _fallbackQuestion: string): AnalysisRow[] {
  const firstResult = response.skill_results?.[0];
  const rows = firstResult?.data ?? [];
  if (!rows.length) return [];
  const semantic = firstResult?.semantic_info || {};
  const mapping = semantic.schema_mapping && typeof semantic.schema_mapping === "object"
    ? (semantic.schema_mapping as Record<string, unknown>)
    : {};
  const mappedMetrics = Array.isArray(mapping.metrics) ? mapping.metrics.map(String) : [];
  const mappedDimensions = Array.isArray(mapping.dimensions) ? mapping.dimensions.map(String) : [];
  const metricCandidates = Array.from(new Set([
    firstResult?.visualization_artifact?.y,
    firstResult?.chart_spec?.y,
    ...mappedMetrics,
    ...(response.analysis_plan?.metrics || []),
    "metric_value",
  ].filter((field): field is string => Boolean(field))));
  const dimensionCandidates = Array.from(new Set([
    firstResult?.visualization_artifact?.x,
    firstResult?.chart_spec?.x,
    ...mappedDimensions,
    ...(response.analysis_plan?.dimensions || []),
  ].filter((field): field is string => Boolean(field))));
  const firstRow = rows[0] || {};
  const metricField = metricCandidates.find((field) => Number.isFinite(Number(firstRow[field])))
    || Object.keys(firstRow).find((field) => Number.isFinite(Number(firstRow[field])));
  if (!metricField) return [];
  const dimensionFields = dimensionCandidates.filter((field) => field in firstRow);
  const unitMap = semantic.metric_units && typeof semantic.metric_units === "object"
    ? (semantic.metric_units as Record<string, unknown>)
    : {};
  return rows.slice(0, 200).map((sourceRow, index) => {
    const row = { ...sourceRow };
    const dimensionValue = dimensionFields.length
      ? dimensionFields.map((field) => String(row[field] ?? "—")).join(" / ")
      : String(row.branch_name ?? row.product_line ?? row.customer_segment ?? `第${index + 1}行`);
    const metricValue = Number(row[metricField]);
    return {
      branch: dimensionValue,
      productLine: backendDisplayValue(row.product_line),
      customerSegment: backendDisplayValue(row.customer_segment),
      amount: Number.isFinite(metricValue) ? metricValue : 0,
      metricName: metricField,
      metricUnit: String(unitMap[metricField] || ""),
      raw: row,
      completion: backendDisplayValue(row.completion_rate ?? row.balance_completion_rate),
      conversion: backendDisplayValue(row.conversion_rate),
      overdueRate: backendDisplayValue(row.m1_overdue_rate),
      weekChange: backendDisplayValue(row.week_change ?? row.weekly_net_increase),
    };
  });
}

export function visualTypeFromBackend(type?: string): VisualizationType {
  return normalizedVisualizationType(type) || "column";
}

export function visualTypesFromBackend(response: BackendAnalysisResponse, fallback: Record<ResultVisualKey, VisualizationType>) {
  const chartTypes = response.analysis_plan?.chart_types ?? [];
  const suggestedTypes = (response.intelligent_analysis?.visualization_suggestions ?? [])
    .map((item) => String(item.type || ""))
    .filter(Boolean);
  const firstResult = response.skill_results?.[0];
  const normalizedTypes = Array.from(new Set([
    ...suggestedTypes,
    String(firstResult?.visualization_artifact?.type || ""),
    String(firstResult?.chart_spec?.type || ""),
    ...chartTypes,
  ].map(normalizedVisualizationType).filter(
    (type): type is "line" | "column" | "table" => Boolean(type),
  )));
  const primary = normalizedTypes[0] || normalizedVisualizationType(fallback.primary) || "column";
  const fallbackSecondary = normalizedVisualizationType(fallback.secondary);
  return {
    primary,
    secondary: normalizedTypes.find((type) => type !== primary)
      || (fallbackSecondary !== primary ? fallbackSecondary : null)
      || (primary === "table" ? "column" : "table"),
  } as Record<ResultVisualKey, VisualizationType>;
}

export function sqlScriptFromBackend(response: BackendAnalysisResponse) {
  const result = response.skill_results?.[0];
  const executedSql = result?.sql?.trim() || "-- 本次执行没有返回已执行 SQL。";
  const suggestedSql = response.intelligent_analysis?.suggested_sql?.trim();
  const semantic = result?.semantic_info || {};
  const candidateSection = suggestedSql && suggestedSql !== result?.sql?.trim()
    ? `\n\n-- 第一阶段大模型候选 SQL（${semantic.model_sql_applied === true ? "已通过目录和租户策略校验后执行" : "当前数据源未执行，仅供受治理重跑"}）\n${suggestedSql}`
    : "";
  return `${executedSql}

-- Parameters
${JSON.stringify(result?.parameters ?? {}, null, 2)}${candidateSection}`;
}

export function pythonScriptFromBackend(response: BackendAnalysisResponse) {
  const result = response.skill_results?.[0];
  const processingScript = result?.data_processing_python_script?.trim();
  const visualizationScript = result?.python_script?.trim();
  if (!processingScript && !visualizationScript) return "# 本次执行没有返回已执行 Python 脚本。";
  const validationErrors = response.intelligent_analysis?.planning?.validation_errors ?? [];
  const processingNote = validationErrors.includes("model_data_processing_python_rejected")
    ? "# 模型数据加工 Python 未通过沙箱校验；以下为实际执行的安全回退脚本。"
    : "# 数据加工 Python：整理实际查询结果并输出质量核对信息。";
  const visualizationNote = validationErrors.includes("model_python_rejected")
    ? "# 模型可视化 Python 未通过沙箱校验；以下为实际执行的安全回退脚本。"
    : "# 可视化 Python：读取加工后的分析表并生成下方图表。";
  return [processingNote, processingScript, visualizationNote, visualizationScript].filter(Boolean).join("\n\n");
}

export function formatMetricScenarios(response: BackendAnalysisResponse) {
  const scenarios = response.intelligent_analysis?.metric_scenarios ?? [];
  if (!scenarios.length) return "本次第一阶段规划没有返回指标表现情景。";
  return scenarios
    .map((item, index) => `${index + 1}. ${item.metric || "未命名指标"}\n表现较好：${item.positive || "—"}\n表现平稳：${item.neutral || "—"}\n表现较差：${item.negative || "—"}`)
    .join("\n\n");
}

export function loadSavedAnalysisResults(): SavedAnalysisResult[] {
  try {
    const raw = window.localStorage.getItem(savedAnalysisStorageKey);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function downloadCsv(filename: string, rows: AnalysisRow[]) {
  const header = analysisRawFields(rows);
  const csv = [
    header.map(csvCell).join(","),
    ...rows.map((row) => header.map((field) => csvCell(row.raw[field])).join(",")),
  ].join("\n");
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function analysisRawFields(rows: AnalysisRow[]) {
  return Array.from(new Set(rows.flatMap((row) => Object.keys(row.raw))));
}

export function csvCell(value: unknown) {
  const text = value === null || value === undefined
    ? ""
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

export function displayRawCell(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export async function readKnowledgeAttachment(file: File): Promise<KnowledgeFileAttachment> {
  const attachmentName = file.name || `粘贴文件_${new Date().toISOString().replace(/[:.]/g, "-")}`;
  const textLike =
    file.type.startsWith("text/") ||
    /\.(csv|txt|json|md|sql)$/i.test(attachmentName);
  let contentPreview = "";
  if (textLike) {
    contentPreview = (await file.text()).slice(0, 24_000);
  }
  return {
    id: `${attachmentName}_${file.size}_${file.lastModified}_${Math.random().toString(36).slice(2, 8)}`,
    name: attachmentName,
    size: file.size,
    type: file.type || "application/octet-stream",
    lastModified: file.lastModified,
    contentPreview,
    detectedInstitutions: detectAttachmentInstitutions(attachmentName, contentPreview),
  };
}

/**
 * A convenience hint only: it never controls authorization or changes the
 * active tenant.  Matching is deterministic and restricted to the governed
 * institution catalogue, avoiding a model call over a user-uploaded file.
 */
export function detectAttachmentInstitutions(fileName: string, contentPreview = "") {
  const source = `${fileName}\n${contentPreview}`.toLocaleLowerCase("zh-CN");
  return operatingTenantNames.filter((institution) => source.includes(institution.toLocaleLowerCase("zh-CN")));
}
