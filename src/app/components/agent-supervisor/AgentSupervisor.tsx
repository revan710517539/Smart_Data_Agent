import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { AudioLines, Bot, BrainCircuit, Database, ExternalLink, Eye, History, ListChecks, Mic, Send, ShieldCheck, Sparkles, X, type LucideIcon } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useLocation, useNavigate } from "react-router";
import { fetchPlatformCapabilities } from "../../services/capabilitiesApi";
import { fetchMetricDictionary } from "../../services/metricDictionaryApi";
import { apiErrorMessage, apiRequest } from "../../services/apiClient";
import { waitForSelfAnalysis, type BackendAnalysisResponse, type BackendSkillResult } from "../../services/analysisApi";
import { runApplicationAction } from "../../services/applicationApi";
import { fetchAnalysisRuntimeConfig, type FunAsrRuntimeIntegration } from "../../services/systemConfigApi";
import { usePlatformContext } from "../../platform/PlatformContext";
import {
  appendRealtimeVoiceText,
  buildFunAsrRealtimeUrl,
  downsampleToPcm16,
  funAsrErrorMessage,
  funAsrSampleRate,
  getAudioContextConstructor,
  normalizeVoiceSegment,
  type FunAsrProxyEvent,
} from "../self-analysis/domain";
import { agentActionRegistry, type AgentActionDefinition } from "./actionRegistry";

type Message = {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  chart?: ChartData;
};

type ChartData = {
  title: string;
  metric: string;
  rows: Array<{ label: string; value: number }>;
  mode: "formal" | "exercise";
};

type StoredConversation = { id: string; title: string; updatedAt: string; messages: Message[] };
type PageControlKind = "button" | "link" | "select" | "input" | "textarea" | "checkbox" | "radio" | "tab" | "dialog";
type PageControl = { kind: PageControlKind; label: string; element: HTMLElement };
type PageInventory = { headings: string[]; dialogs: string[]; controls: PageControl[]; contentPreview: string };
type NavigationAction = AgentActionDefinition & { path?: string };
type SupervisorVoiceMode = "manual" | "realtime";

const historyStorageKey = "smart_data_agent_agent_supervisor_conversations_v1";
const supervisorSelector = "[data-agent-supervisor]";
const highImpactTerms = /删除|保存|提交|发布|启用|停用|退出|确认删除|确认保存|导入|上传|下载|发送|取消任务/;
// The main self-analysis screen retains its independent 5-second behavior.
// The supervisor is a conversational control surface, so it follows the
// explicit 3-second pause requested for real-time dialogue here.
const supervisorRealtimeVoiceSilenceMs = 3_000;

const navigationActions = [
  { id: "dashboard", label: "打开多机构分析", description: "进入多机构经营分析首页", path: "/" },
  { id: "weekly-report", label: "打开经营周报", description: "进入经营周报", path: "/weekly-report" },
  { id: "supervision", label: "打开机构督导", description: "进入机构督导", path: "/supervision" },
  { id: "customers", label: "打开客群分析", description: "进入客群分析", path: "/customers" },
  { id: "competition", label: "打开竞品分析", description: "进入竞品分析", path: "/competition" },
  { id: "analysis", label: "打开自助分析", description: "进入正式的自助分析页面", path: "/self-analysis/query" },
  { id: "my-reports", label: "打开我的报告", description: "查看已生成的分析报告", path: "/self-analysis/reports" },
  { id: "analysis-config", label: "打开分析配置", description: "进入分析配置", path: "/self-analysis/config" },
  { id: "todos", label: "打开待办任务", description: "查看待办任务", path: "/agent/todos" },
  { id: "tasks", label: "打开自动化任务", description: "查看自动化任务和能力编排", path: "/agent/tasks" },
  { id: "skills", label: "打开 Skill 管理", description: "查看系统 Skill 与运行状态", path: "/agent/skills" },
  { id: "metrics", label: "打开指标管理", description: "查看并维护已保存的指标字典", path: "/data-assets/metrics" },
  { id: "memory", label: "打开知识记忆", description: "查看知识、经验与行为记忆", path: "/data-assets/knowledge" },
  { id: "assets", label: "打开数据管理", description: "查看原始表、主题表和数据资产", path: "/data-assets/data-management" },
  { id: "quality", label: "打开质量监控", description: "查看数据质量监控", path: "/data-assets/quality" },
  { id: "tools", label: "打开工具调用", description: "查看工具调用记录", path: "/data-assets/tools" },
  { id: "alerts", label: "打开预警规则", description: "进入预警规则", path: "/notifications/alerts" },
  { id: "subscriptions", label: "打开订阅管理", description: "进入订阅管理", path: "/notifications/subscriptions" },
  { id: "notification-history", label: "打开推送记录", description: "查看推送记录", path: "/notifications/history" },
  { id: "users", label: "打开用户管理", description: "进入用户管理", path: "/settings/users" },
  { id: "roles", label: "打开角色权限", description: "进入角色权限", path: "/settings/roles" },
  { id: "audit", label: "打开审计日志", description: "查看审计日志", path: "/settings/audit" },
  { id: "settings", label: "打开系统管理", description: "进入系统配置", path: "/settings/config" },
] as const;

export function AgentSupervisor() {
  const navigate = useNavigate();
  const location = useLocation();
  const { currentTenantRoles, selectedInstitution, tenantId, userId } = usePlatformContext();
  const [open, setOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [voiceMode, setVoiceMode] = useState<SupervisorVoiceMode | null>(null);
  const [voiceNotice, setVoiceNotice] = useState("");
  const [pendingAction, setPendingAction] = useState<AgentActionDefinition | null>(null);
  const [messages, setMessages] = useState<Message[]>(() => [welcomeMessage(selectedInstitution)]);
  const [history, setHistory] = useState<StoredConversation[]>(readHistory);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const messagesPanelRef = useRef<HTMLDivElement | null>(null);
  const runningRef = useRef(false);
  const submitRef = useRef<(override?: string) => Promise<void>>(async () => undefined);
  const voiceModeRef = useRef<SupervisorVoiceMode | null>(null);
  const voiceActiveRef = useRef(false);
  const voiceStartingRef = useRef(false);
  const voiceSocketRef = useRef<WebSocket | null>(null);
  const voiceStreamRef = useRef<MediaStream | null>(null);
  const voiceAudioContextRef = useRef<AudioContext | null>(null);
  const voiceSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const voiceProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const voiceBaseRef = useRef("");
  const voiceFinalRef = useRef("");
  const voiceDraftRef = useRef("");
  const voiceRenderedRef = useRef("");
  const voiceSegmentIdRef = useRef(0);
  const voiceSilenceTimerRef = useRef<number | null>(null);
  const [, refreshActions] = useReducer((value) => value + 1, 0);

  useEffect(() => agentActionRegistry.subscribe(refreshActions), []);
  useEffect(() => {
    const cleanups = navigationActions.map((action) => agentActionRegistry.register({
      ...action,
      execute: () => navigate(action.path),
    }));
    return () => cleanups.forEach((cleanup) => cleanup());
  }, [navigate]);

  // Keep the conversation focused on the latest exchange. This runs for the
  // user's question as well as every asynchronous supervisor response.
  useEffect(() => {
    const panel = messagesPanelRef.current;
    if (!panel) return;
    const frame = window.requestAnimationFrame(() => {
      panel.scrollTo({ top: panel.scrollHeight, behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages]);

  useEffect(() => {
    runningRef.current = running;
  }, [running]);

  const actions = agentActionRegistry.list();
  const pageLabel = useMemo(() => `${selectedInstitution} · ${location.pathname}`, [location.pathname, selectedInstitution]);

  const appendMessage = (message: Omit<Message, "id">) => {
    setMessages((current) => [...current, { ...message, id: crypto.randomUUID() }]);
  };

  const clearVoiceSilenceTimer = () => {
    if (voiceSilenceTimerRef.current !== null) {
      window.clearTimeout(voiceSilenceTimerRef.current);
      voiceSilenceTimerRef.current = null;
    }
  };

  const cleanupVoiceAudio = () => {
    try { voiceProcessorRef.current?.disconnect(); } catch { /* already disconnected */ }
    try { voiceSourceRef.current?.disconnect(); } catch { /* already disconnected */ }
    voiceProcessorRef.current = null;
    voiceSourceRef.current = null;
    voiceStreamRef.current?.getTracks().forEach((track) => track.stop());
    voiceStreamRef.current = null;
    void voiceAudioContextRef.current?.close().catch(() => undefined);
    voiceAudioContextRef.current = null;
  };

  const stopVoiceInput = (notice = "") => {
    clearVoiceSilenceTimer();
    voiceActiveRef.current = false;
    const socket = voiceSocketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "finish" }));
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
    voiceSocketRef.current = null;
    cleanupVoiceAudio();
    voiceModeRef.current = null;
    setVoiceMode(null);
    if (notice) setVoiceNotice(notice);
  };

  const resetVoiceTranscript = (baseText: string) => {
    voiceSegmentIdRef.current += 1;
    voiceBaseRef.current = baseText;
    voiceFinalRef.current = "";
    voiceDraftRef.current = "";
    voiceRenderedRef.current = baseText;
  };

  const scheduleRealtimeVoiceSubmit = () => {
    clearVoiceSilenceTimer();
    if (!voiceActiveRef.current || voiceModeRef.current !== "realtime") return;
    const candidate = normalizeVoiceSegment(voiceRenderedRef.current);
    if (!candidate) return;
    const segmentId = voiceSegmentIdRef.current;
    voiceSilenceTimerRef.current = window.setTimeout(() => {
      voiceSilenceTimerRef.current = null;
      const question = normalizeVoiceSegment(voiceRenderedRef.current);
      if (!voiceActiveRef.current || voiceModeRef.current !== "realtime" || runningRef.current || !question || segmentId !== voiceSegmentIdRef.current) return;
      resetVoiceTranscript("");
      setInput("");
      setVoiceNotice("已停顿 3 秒，正在自动执行语音问题…");
      void submitRef.current(question);
    }, supervisorRealtimeVoiceSilenceMs);
  };

  const applyVoiceTranscript = (text: string, isFinal: boolean) => {
    const normalized = normalizeVoiceSegment(text);
    if (!normalized) return;
    if (isFinal) {
      voiceFinalRef.current = normalizeVoiceSegment(`${voiceFinalRef.current} ${normalized}`);
      voiceDraftRef.current = "";
    } else {
      voiceDraftRef.current = normalized;
    }
    const recognized = normalizeVoiceSegment(`${voiceFinalRef.current} ${voiceDraftRef.current}`);
    const nextInput = appendRealtimeVoiceText(voiceBaseRef.current, recognized);
    voiceRenderedRef.current = nextInput;
    setInput(nextInput);
    setVoiceNotice(voiceModeRef.current === "realtime"
      ? "实时语音中：停止说话 3 秒后将自动执行。"
      : "语音录入中：转写内容已填入输入框，点击发送后执行。",
    );
    if (voiceModeRef.current === "realtime") scheduleRealtimeVoiceSubmit();
  };

  const startVoiceAudioStream = async (socket: WebSocket, stream: MediaStream) => {
    const AudioContextConstructor = getAudioContextConstructor();
    if (!AudioContextConstructor) throw new Error("当前浏览器不支持实时音频采集，可继续直接输入。");
    const audioContext = new AudioContextConstructor({ sampleRate: funAsrSampleRate });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (event) => {
      event.outputBuffer.getChannelData(0).fill(0);
      if (!voiceActiveRef.current || socket.readyState !== WebSocket.OPEN) return;
      const pcm = downsampleToPcm16(event.inputBuffer.getChannelData(0), audioContext.sampleRate, funAsrSampleRate);
      socket.send(pcm.buffer.slice(0));
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    voiceAudioContextRef.current = audioContext;
    voiceSourceRef.current = source;
    voiceProcessorRef.current = processor;
  };

  const startVoiceInput = async (mode: SupervisorVoiceMode) => {
    if (voiceStartingRef.current) return;
    if (voiceActiveRef.current && voiceModeRef.current === mode) {
      stopVoiceInput(mode === "manual" ? "已停止语音录入；可检查转写内容后点击发送。" : "已停止实时语音交互。");
      return;
    }
    voiceStartingRef.current = true;
    stopVoiceInput();
    const applicationModule = mode === "manual" ? "popup_voice_input" : "realtime_voice_input";
    let integration: FunAsrRuntimeIntegration | null = null;
    setVoiceNotice("正在加载语音配置…");
    try {
      const runtime = await fetchAnalysisRuntimeConfig({ tenantId, userId, speechApplicationModule: applicationModule });
      integration = runtime.speechIntegration;
      if (!integration) {
        setVoiceNotice("当前机构没有已启用的阿里云 Fun-ASR 接入。请在系统配置 → 模型接入管理 → 语音转文字中保存配置；无需连通性测试。");
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        setVoiceNotice("当前浏览器不支持实时麦克风采集，可继续直接输入。");
        return;
      }
      voiceActiveRef.current = true;
      voiceModeRef.current = mode;
      resetVoiceTranscript(input);
      setVoiceMode(mode);
      setVoiceNotice(mode === "manual" ? "语音录入中：转写完成后点击发送执行。" : "实时语音中：停止说话 3 秒后将自动执行。");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!voiceActiveRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      voiceStreamRef.current = stream;
      const socket = new WebSocket(buildFunAsrRealtimeUrl(tenantId, userId, applicationModule));
      voiceSocketRef.current = socket;
      socket.onopen = () => {
        if (!voiceActiveRef.current || !integration) return;
        socket.send(JSON.stringify({
          type: "start",
          provider: "aliyun_fun_asr",
          speechIntegrationId: integration.id,
          applicationModule,
          sampleRate: funAsrSampleRate,
          context: [],
        }));
      };
      socket.onmessage = (event) => {
        if (!voiceActiveRef.current) return;
        let payload: FunAsrProxyEvent;
        try { payload = JSON.parse(String(event.data)) as FunAsrProxyEvent; } catch { return; }
        if (payload.type === "ready") {
          void startVoiceAudioStream(socket, stream).catch((error) => stopVoiceInput(apiErrorMessage(error, "实时音频采集失败，可继续直接输入。")));
          return;
        }
        if (payload.type === "config" && payload.provider !== "aliyun_fun_asr") {
          stopVoiceInput("语音入口未连接阿里云 Fun-ASR，已停止本次录音。");
          return;
        }
        if (payload.type === "transcript") {
          applyVoiceTranscript(payload.text || "", Boolean(payload.final));
          return;
        }
        if (payload.type === "error") {
          stopVoiceInput(funAsrErrorMessage(payload.message || ""));
          return;
        }
        if (payload.type === "finished") stopVoiceInput(mode === "manual" ? "语音录入已结束；可点击发送执行。" : "实时语音已结束。");
      };
      socket.onerror = () => {
        if (voiceActiveRef.current) stopVoiceInput("实时语音连接失败，可继续直接输入。");
      };
      socket.onclose = () => {
        if (!voiceActiveRef.current) return;
        stopVoiceInput("实时语音连接已关闭，可继续直接输入。");
      };
      inputRef.current?.focus();
      void runApplicationAction({
        tenantId,
        userId,
        moduleKey: "self_analysis",
        action: mode === "manual" ? "start_voice_input_fun_asr" : "start_realtime_voice",
        payload: { target: "agent_supervisor", applicationModule, speechIntegrationId: integration.id },
      }).catch(() => undefined);
    } catch (error) {
      stopVoiceInput(funAsrErrorMessage(apiErrorMessage(error, "实时语音未启动，可继续直接输入。")));
    } finally {
      voiceStartingRef.current = false;
    }
  };

  const persistHistory = (next: Message[]) => {
    const firstQuestion = next.find((item) => item.role === "user")?.content;
    if (!firstQuestion) return;
    const entry: StoredConversation = {
      id: crypto.randomUUID(),
      title: firstQuestion.slice(0, 30),
      updatedAt: new Date().toISOString(),
      messages: next.slice(-30),
    };
    setHistory((current) => {
      const saved = [entry, ...current].slice(0, 30);
      window.localStorage.setItem(historyStorageKey, JSON.stringify(saved));
      return saved;
    });
  };

  const executeAction = async (action: AgentActionDefinition, confirmed = false, announce = true) => {
    const risk = action.risk || "low";
    if ((risk === "medium" || risk === "high") && !confirmed) {
      setPendingAction(action);
      if (announce) appendMessage({ role: "system", content: `“${action.label}”会更改页面状态或触发高影响操作。请在总管中确认后执行；没有确认不会写入、删除、发布或启用任何内容。` });
      return;
    }
    setPendingAction(null);
    try {
      await action.execute();
      if (announce) appendMessage({ role: "agent", content: `已执行：${action.label}。${action.description}` });
    } catch (error) {
      appendMessage({ role: "system", content: error instanceof Error ? error.message : `执行“${action.label}”失败。` });
    }
  };

  const submit = async (override?: string) => {
    const question = (override ?? input).trim();
    if (!question || running) return;
    const userMessage: Message = { id: crypto.randomUUID(), role: "user", content: question };
    setMessages((current) => {
      const next = [...current, userMessage];
      persistHistory(next);
      return next;
    });
    setInput("");
    setRunning(true);
    try {
      const navigationAction = resolveNavigationAction(question, actions);
      if (navigationAction) {
          if (hasExplicitPageOperation(question) && navigationAction.path && navigationAction.path !== location.pathname) {
            await executeAction(navigationAction, false, false);
            window.setTimeout(() => {
              const afterNavigation = resolvePageAction(question);
              if (afterNavigation) void executeAction(afterNavigation);
              else appendMessage({ role: "system", content: `已打开“${navigationAction.label.replace(/^打开/, "")}”，但当前页没有找到“${extractRequestedLabel(question)}”。请先用“当前页面有什么内容和操作”查看可执行节点。` });
            }, 250);
            appendMessage({ role: "agent", content: `已打开：${navigationAction.label.replace(/^打开/, "")}；正在定位后续页面动作。` });
            return;
          }
          await executeAction(navigationAction);
          return;
        }
      const pageAction = resolvePageAction(question);
      if (pageAction) {
        await executeAction(pageAction);
        return;
      }
      if (hasExplicitPageOperation(question)) {
        appendMessage({ role: "system", content: `当前页面没有找到“${extractRequestedLabel(question)}”这个可执行节点，因此没有执行任何页面操作。你可以先问“当前页面有什么内容和操作”，或明确先打开目标页面。` });
        return;
      }
      if (isPageQuestion(question)) {
        appendMessage({ role: "agent", content: pageInventoryAnswer(scanPageInventory()) });
        return;
      }
      if (isMetricQuestion(question)) {
        const response = await fetchMetricDictionary({ tenantId, userId });
        appendMessage({ role: "agent", content: metricAnswer(question, response.metrics) });
        return;
      }
      if (isSkillQuestion(question)) {
        const response = await fetchPlatformCapabilities({ tenantId, userId });
        const active = response.skills.filter((skill) => skill.enabled && skill.healthy);
        const configured = response.skills.filter((skill) => skill.configured).length;
        appendMessage({
          role: "agent",
          content: `系统总管已读取到 ${response.skills.length} 个运行时登记 Skill（${configured} 个已配置），其中 ${active.length} 个处于启用且健康状态；${response.agents.length} 个 Agent、${response.agent_groups.length} 个 Agent 组可编排。\n\n${active.slice(0, 12).map((skill) => `• ${skill.skill_id} · ${skill.status}`).join("\n") || "当前没有可用 Skill。"}\n\n我可以打开 Skill 管理并操作该页已有的新增、编辑、启用等控件；会保留页面既有权限、审批和确认机制，不会通过聊天窗口绕过它们。`,
        });
        return;
      }
      if (isMemoryQuestion(question)) {
        const response = await apiRequest<{ records: Array<Record<string, unknown>>; count: number }>("/api/memory?view=active", {
          method: "GET",
          context: { tenantId, userId },
        });
        const names = response.records.slice(0, 12).map(memoryLabel);
        appendMessage({ role: "agent", content: `当前机构中，你有权限读取的已激活记忆共 ${response.count} 条。\n${names.length ? names.map((name) => `• ${name}`).join("\n") : "暂无已激活记忆。"}\n\n这里只返回当前账号可见的记忆摘要，不显示未授权内容；需要维护时可让我打开“知识记忆”。` });
        return;
      }
      await runAnalysis(question, { tenantId, userId, selectedInstitution, currentTenantRoles, appendMessage });
    } catch (error) {
      appendMessage({ role: "system", content: error instanceof Error ? error.message : "总管暂时无法完成此请求。" });
    } finally {
      setRunning(false);
    }
  };
  submitRef.current = submit;

  useEffect(() => () => stopVoiceInput(), []);

  return (
    <div
      className={`fixed inset-0 z-[70] ${open ? "pointer-events-auto" : "pointer-events-none"}`}
      data-agent-supervisor="true"
      onMouseDown={(event) => {
        if (event.target !== event.currentTarget || !open) return;
        stopVoiceInput();
        setHistoryOpen(false);
        setPendingAction(null);
        setOpen(false);
      }}
    >
      {open && (
        <div className={`pointer-events-auto absolute bottom-[88px] right-6 flex h-[min(640px,calc(100vh-112px))] max-w-[calc(100vw-32px)] overflow-hidden rounded-2xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/15 ${historyOpen ? "w-[min(600px,calc(100vw-32px))]" : "w-[min(440px,calc(100vw-32px))]"}`} role="dialog" aria-label="Agent 总管">
          {historyOpen && (
            <aside className="flex w-40 shrink-0 flex-col border-r border-[#e5e5ea] bg-[#fafbfc] p-2">
              <div className="mb-2 flex items-center justify-between text-[11px] text-[#636366]"><span>历史对话</span><button type="button" onClick={() => setHistoryOpen(false)} aria-label="关闭历史" className="rounded p-0.5 hover:bg-white"><X className="h-3 w-3" /></button></div>
              <div className="h-[calc(100%-24px)] space-y-1 overflow-y-auto">
                {history.map((item) => <button type="button" key={item.id} onClick={() => { setMessages(item.messages); setHistoryOpen(false); }} className="w-full rounded-md px-2 py-1.5 text-left text-[10px] text-[#636366] hover:bg-white"><span className="line-clamp-2 block">{item.title}</span><time className="mt-0.5 block text-[9px] text-[#aeaeb2]">{new Date(item.updatedAt).toLocaleDateString("zh-CN")}</time></button>)}
                {!history.length && <p className="p-2 text-[10px] text-[#aeaeb2]">暂无历史</p>}
              </div>
            </aside>
          )}
          <section className="flex h-full min-w-0 flex-1 flex-col bg-white">
            <header className="flex items-start justify-between border-b border-[#ebebf0] px-4 py-3">
              <div><div className="flex items-center gap-1.5 text-[10px] tracking-[0.12em] text-[#8a8a8e]"><Bot className="h-3.5 w-3.5" />AGENT SUPERVISOR</div><div className="mt-1 flex items-center gap-2 text-[14px] text-[#1d1d1f]"><strong>系统 Agent 总管</strong><button type="button" onClick={() => setHistoryOpen((value) => !value)} title="历史对话" aria-label="历史对话"><History className="h-3.5 w-3.5 text-[#8a8a8e]" /></button></div><p className="mt-0.5 max-w-[270px] truncate text-[10px] text-[#aeaeb2]">{pageLabel}</p></div>
              <button type="button" onClick={() => { stopVoiceInput(); setOpen(false); }} aria-label="关闭 Agent 总管" className="rounded-md p-1 text-[#8a8a8e] hover:bg-[#f2f2f7]"><X className="h-4 w-4" /></button>
            </header>
            <div className="flex flex-wrap gap-1 border-b border-[#f0f0f2] px-3 py-2">
              <QuickAction icon={Eye} label="当前页" onClick={() => void submit("当前页面有什么内容和操作")} />
              <QuickAction icon={Database} label="查指标" onClick={() => void submit("有哪些指标和指标口径")} />
              <QuickAction icon={BrainCircuit} label="查记忆" onClick={() => void submit("有哪些记忆")} />
              <QuickAction icon={Sparkles} label="查 Skill" onClick={() => void submit("有哪些 Skill")} />
              <QuickAction icon={ExternalLink} label="自助分析" onClick={() => { const action = actions.find((item) => item.id === "analysis"); if (action) void executeAction(action); }} />
            </div>
            <div ref={messagesPanelRef} className="flex-1 space-y-3 overflow-y-auto p-3">
              {messages.map((message) => <MessageCard key={message.id} message={message} />)}
            </div>
            {pendingAction && <div className="flex items-center gap-2 border-t border-[#f1d6b8] bg-[#fff7ed] px-3 py-2 text-[11px] text-[#9a5a09]"><ShieldCheck className="h-4 w-4 shrink-0" /><span className="min-w-0 flex-1">确认执行：{pendingAction.label}</span><button type="button" onClick={() => setPendingAction(null)} className="rounded px-2 py-1 hover:bg-white">取消</button><button type="button" onClick={() => void executeAction(pendingAction, true)} className="rounded bg-[#1d1d1f] px-2 py-1 text-white">确认</button></div>}
            <form className="border-t border-[#ebebf0] p-3" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
              <div className="flex gap-1.5"><input ref={inputRef} value={input} onChange={(event) => { const value = event.target.value; setInput(value); if (voiceActiveRef.current) resetVoiceTranscript(value); }} placeholder="问指标、记忆、Skill，或说“打开/点击/填写…”" className="min-w-0 flex-1 rounded-lg bg-[#f2f2f7] px-3 py-2 text-[12px] outline-none ring-0 focus:bg-white focus:ring-1 focus:ring-[#c7c7cc]" /><button type="button" onClick={() => void startVoiceInput("manual")} className={`rounded-lg px-2.5 transition ${voiceMode === "manual" ? "bg-[#1d1d1f] text-white" : "bg-[#f2f2f7] text-[#636366] hover:bg-[#e5e5ea]"}`} aria-label={voiceMode === "manual" ? "停止语音录入" : "语音录入"} title="语音录入：转写后点击发送执行"><Mic className={`h-4 w-4 ${voiceMode === "manual" ? "animate-pulse" : ""}`} /></button><button type="button" onClick={() => void startVoiceInput("realtime")} className={`rounded-lg px-2.5 transition ${voiceMode === "realtime" ? "bg-[#1d1d1f] text-white" : "bg-[#f2f2f7] text-[#636366] hover:bg-[#e5e5ea]"}`} aria-label={voiceMode === "realtime" ? "停止实时语音交互" : "实时语音交互"} title="实时语音：停顿 3 秒自动执行"><AudioLines className={`h-4 w-4 ${voiceMode === "realtime" ? "animate-pulse" : ""}`} /></button><button disabled={!input.trim() || running} className="rounded-lg bg-[#1d1d1f] px-3 text-white disabled:opacity-40" aria-label="发送指令">{running ? <ListChecks className="h-4 w-4 animate-pulse" /> : <Send className="h-4 w-4" />}</button></div>
              <p className="mt-1.5 text-[10px] text-[#aeaeb2]" aria-live="polite">{voiceNotice || "会实时扫描当前页面的菜单、按钮、下拉框、输入框和弹窗。写入、删除、发布、启停均须确认；演练数据会明确标识为不可发布。"}</p>
            </form>
          </section>
        </div>
      )}
      <button type="button" onClick={() => { if (open) stopVoiceInput(); setOpen((value) => !value); window.setTimeout(() => inputRef.current?.focus(), 80); }} aria-label="打开 Agent 总管" aria-expanded={open} className="pointer-events-auto absolute bottom-6 right-6 flex h-12 w-12 items-center justify-center rounded-full bg-[#1d1d1f] text-white shadow-xl shadow-black/20 transition hover:scale-105 hover:bg-[#2c2c2e]"><Bot className="h-5 w-5" /><span className="absolute right-0 top-0 h-3 w-3 rounded-full border-2 border-white bg-[#34c759]" /></button>
    </div>
  );
}

function welcomeMessage(institution: string): Message {
  return { id: "welcome", role: "agent", content: `我是 ${institution} 的系统 Agent 总管。\n\n我会扫描当前页面已经渲染的菜单、下拉框、按钮、子模块、输入框和弹窗；你可以问指标口径、记忆、Skill，也可以让我调用既有自助分析链路。` };
}

function readHistory(): StoredConversation[] {
  try { return JSON.parse(window.localStorage.getItem(historyStorageKey) || "[]") as StoredConversation[]; } catch { return []; }
}

function QuickAction({ icon: Icon, label, onClick }: { icon: LucideIcon; label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex items-center gap-1 rounded-md border border-[#e5e5ea] px-2 py-1 text-[10px] text-[#636366] hover:bg-[#f8f8fa]"><Icon className="h-3 w-3" />{label}</button>;
}

function MessageCard({ message }: { message: Message }) {
  const tone = message.role === "user" ? "ml-8 bg-[#1d1d1f] text-white" : message.role === "system" ? "mr-8 border border-[#f1d6b8] bg-[#fff7ed] text-[#9a5a09]" : "mr-4 bg-[#f2f2f7] text-[#3a3a3c]";
  return <article className={`rounded-xl px-3 py-2.5 text-[12px] leading-5 ${tone}`}><div className="mb-1 text-[9px] opacity-60">{message.role === "user" ? "你" : message.role === "system" ? "系统" : "Agent 总管"}</div><p className="whitespace-pre-wrap">{message.content}</p>{message.chart && <SupervisorChart chart={message.chart} />}</article>;
}

function SupervisorChart({ chart }: { chart: ChartData }) {
  return <div className={`mt-2 h-40 rounded-lg border p-2 text-[#3a3a3c] ${chart.mode === "exercise" ? "border-[#f1d6b8] bg-[#fffaf1]" : "border-[#e5e5ea] bg-white"}`}><div className="mb-1 flex items-center justify-between gap-2"><p className="truncate text-[10px] text-[#636366]">{chart.title}</p><span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] ${chart.mode === "exercise" ? "bg-[#fff0d7] text-[#9a5a09]" : "bg-[#eaf8ed] text-[#258a3f]"}`}>{chart.mode === "exercise" ? "演练，不可发布" : "已通过发布门"}</span></div><ResponsiveContainer width="100%" height="88%"><BarChart data={chart.rows}><CartesianGrid vertical={false} stroke="#f0f0f2" /><XAxis dataKey="label" tick={{ fontSize: 9 }} /><YAxis tick={{ fontSize: 9 }} /><Tooltip /><Bar dataKey="value" name={chart.metric} fill={chart.mode === "exercise" ? "#b7791f" : "#1d1d1f"} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div>;
}

function resolveNavigationAction(question: string, actions: AgentActionDefinition[]) {
  const normalized = normalizeText(question).toLowerCase();
  if (!/打开|进入|跳转|查看/.test(normalized)) return undefined;
  const requested = normalized.replace(/^(?:请)?(?:帮我)?(?:打开|进入|跳转到?|查看)/, "").replace(/(?:页面|菜单|模块|界面)$/g, "");
  const navigation = actions.filter((action): action is NavigationAction => Boolean((action as NavigationAction).path));
  const exact = navigation.find((action) => normalizeText(action.label.replace(/^打开/, "")).toLowerCase() === requested);
  if (exact) return exact;
  const aliases: Array<[string, string[]]> = [
    ["metrics", ["指标", "口径"]], ["memory", ["记忆", "知识"]], ["skills", ["skill", "技能"]], ["analysis", ["自助", "智能分析"]], ["tasks", ["任务工作台"]], ["assets", ["数据资产", "主题表", "原始表"]], ["settings", ["系统管理", "系统设置"]],
  ];
  const matched = aliases.find(([, terms]) => terms.some((term) => requested.includes(normalizeText(term).toLowerCase())));
  return matched ? navigation.find((action) => action.id === matched[0]) : undefined;
}

function resolvePageAction(question: string): AgentActionDefinition | undefined {
  const fill = parseFieldFill(question);
  if (fill) {
    const field = findMatchingControl(fill.label, ["input", "textarea"]);
    if (field && (field.element instanceof HTMLInputElement || field.element instanceof HTMLTextAreaElement)) {
      return makeInputAction(field, fill.value);
    }
  }

  const check = parseCheckboxAction(question);
  if (check) {
    const control = findMatchingControl(check.label, ["checkbox"]);
    if (control?.element instanceof HTMLInputElement) return makeCheckboxAction(control, check.checked);
  }

  const selection = question.match(/(?:选择|切换到)\s*[“"']?([^“”"'，。,.！!]{1,30})/);
  if (selection) {
    const optionLabel = stripQuotes(selection[1]);
    const control = scanPageInventory().controls.find((item) => item.kind === "select" && item.element instanceof HTMLSelectElement && Array.from(item.element.options).some((option) => normalizedIncludes(option.textContent || "", optionLabel)));
    if (control?.element instanceof HTMLSelectElement) {
      const option = Array.from(control.element.options).find((item) => normalizedIncludes(item.textContent || "", optionLabel));
      if (option) return makeSelectAction(control, option);
    }
  }

  const match = question.match(/(?:点击|打开|展开|关闭)\s*[“"']?([^“”"'，。,.！!]{2,40})/);
  if (!match) return undefined;
  const label = stripQuotes(match[1]).replace(/(按钮|菜单|下拉框|弹窗)$/, "");
  const control = findMatchingControl(label, ["button", "link", "dialog", "select", "radio", "tab"]);
  return control ? makeClickAction(control) : undefined;
}

function makeClickAction(control: PageControl): AgentActionDefinition {
  const risk: AgentActionDefinition["risk"] = highImpactTerms.test(control.label) ? "medium" : "low";
  return {
    id: `dom:${control.kind}:${control.label}`,
    label: `${control.kind === "dialog" ? "操作弹窗" : "操作当前页"}：${control.label}`,
    description: "已通过当前页面已渲染的控件执行。",
    risk,
    execute: () => {
      control.element.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
      control.element.focus?.();
      control.element.click();
    },
  };
}

function makeSelectAction(control: PageControl, option: HTMLOptionElement): AgentActionDefinition {
  const select = control.element as HTMLSelectElement;
  return {
    id: `select:${control.label}:${option.value}`,
    label: `选择下拉项：${option.textContent?.trim() || option.value}`,
    description: `已在“${control.label}”中完成选择。`,
    execute: () => setNativeValue(select, option.value),
  };
}

function makeInputAction(control: PageControl, value: string): AgentActionDefinition {
  const input = control.element as HTMLInputElement | HTMLTextAreaElement;
  return {
    id: `fill:${control.label}`,
    label: `填写：${control.label}`,
    description: "已将内容填写到当前弹窗或页面字段；尚未保存。",
    risk: "medium",
    execute: () => setNativeValue(input, value),
  };
}

function makeCheckboxAction(control: PageControl, checked: boolean): AgentActionDefinition {
  const input = control.element as HTMLInputElement;
  return {
    id: `check:${control.label}:${checked}`,
    label: `${checked ? "勾选" : "取消勾选"}：${control.label}`,
    description: "已改变页面复选状态；尚未保存。",
    risk: "medium",
    execute: () => {
      if (input.checked !== checked) input.click();
    },
  };
}

function scanPageInventory(): PageInventory {
  const main = document.querySelector<HTMLElement>("main[data-agent-main-shell]") || document.querySelector<HTMLElement>("main") || document.body;
  const sidebar = document.querySelector<HTMLElement>("[data-agent-sidebar]");
  // The shell keeps side navigation outside main. Include it explicitly so the
  // supervisor can discover every currently visible menu without treating its
  // own floating panel as a page action.
  const roots = Array.from(new Set([main, sidebar].filter(Boolean) as HTMLElement[]));
  const withinRoots = <T extends HTMLElement>(selector: string) => roots.flatMap((root) => Array.from(root.querySelectorAll<T>(selector))).filter((element) => isUsableElement(element));
  const headings = withinRoots<HTMLElement>("h1,h2,h3,[role='heading']").map(elementLabel).filter(unique).slice(0, 16);
  const dialogs = withinRoots<HTMLElement>("[role='dialog']").map(elementLabel).filter(unique).slice(0, 10);
  const controls: PageControl[] = [
    ...withinRoots<HTMLButtonElement>("button").filter((element) => !element.disabled).map((element) => ({ kind: "button" as const, label: elementLabel(element), element })),
    ...withinRoots<HTMLAnchorElement>("a[href]").map((element) => ({ kind: "link" as const, label: elementLabel(element), element })),
    ...withinRoots<HTMLSelectElement>("select").filter((element) => !element.disabled).map((element) => ({ kind: "select" as const, label: elementLabel(element), element })),
    ...withinRoots<HTMLInputElement>("input:not([type='hidden'])").filter((element) => !element.disabled && element.type !== "checkbox" && element.type !== "radio").map((element) => ({ kind: "input" as const, label: elementLabel(element), element })),
    ...withinRoots<HTMLTextAreaElement>("textarea").filter((element) => !element.disabled).map((element) => ({ kind: "textarea" as const, label: elementLabel(element), element })),
    ...withinRoots<HTMLInputElement>("input[type='checkbox']").filter((element) => !element.disabled).map((element) => ({ kind: "checkbox" as const, label: elementLabel(element), element })),
    ...withinRoots<HTMLInputElement>("input[type='radio']").filter((element) => !element.disabled).map((element) => ({ kind: "radio" as const, label: elementLabel(element), element })),
    ...withinRoots<HTMLElement>("[role='tab']").filter((element) => !element.hasAttribute("aria-disabled")).map((element) => ({ kind: "tab" as const, label: elementLabel(element), element })),
  ];
  const contentPreview = normalizeText(main.innerText || "").slice(0, 800);
  return { headings, dialogs, controls: dedupeControls(controls).slice(0, 120), contentPreview };
}

function findMatchingControl(label: string, kinds: PageControlKind[]) {
  const wanted = normalizeText(label);
  const ranked = scanPageInventory().controls
    .filter((control) => kinds.includes(control.kind))
    .map((control) => ({ control, score: controlMatchScore(control, wanted) }))
    .sort((left, right) => right.score - left.score);
  const best = ranked[0];
  // A zero-overlap match must never turn into a click on the first control in
  // document order. It is safer to report that a requested node is not on the
  // current page than to operate an unrelated button.
  return best && best.score >= Math.min(2, Math.max(1, wanted.length)) ? best.control : undefined;
}

function controlMatchScore(control: PageControl, wanted: string) {
  const actual = normalizeText(control.label);
  if (actual === wanted) return 100;
  if (actual.includes(wanted)) return 80;
  if (wanted.includes(actual)) return 60;
  return tokenOverlap(actual, wanted);
}

function pageInventoryAnswer(inventory: PageInventory) {
  const groups = new Map<PageControlKind, string[]>();
  inventory.controls.forEach((control) => groups.set(control.kind, [...(groups.get(control.kind) || []), control.label]));
  const groupText = (["button", "select", "input", "textarea", "checkbox", "radio", "tab", "link"] as PageControlKind[])
    .filter((kind) => (groups.get(kind) || []).length)
    .map((kind) => `• ${controlKindLabel(kind)} ${groups.get(kind)!.length} 项：${groups.get(kind)!.slice(0, 9).join("、")}${groups.get(kind)!.length > 9 ? "…" : ""}`)
    .join("\n");
  return `当前页内容与动作目录\n\n标题：${inventory.headings.join("、") || "未识别标题"}\n${inventory.dialogs.length ? `当前弹窗：${inventory.dialogs.join("、")}\n` : ""}\n已发现 ${inventory.controls.length} 个可操作节点：\n${groupText || "当前没有可操作节点。"}\n\n页面摘要：${inventory.contentPreview || "当前页面没有可提取的文字内容。"}\n\n示例：\n• “点击新增指标”\n• “选择第 2 页 / 共 12 页”\n• “把指标名称填写为 月度放款人数”\n• “勾选华兴银行”\n所有填写、勾选、保存、删除、发布、启停类操作均需要你在总管中再次确认。`;
}

function isMetricQuestion(question: string) { return /指标|口径|取值逻辑|公式/.test(question); }
function isSkillQuestion(question: string) { return /skill|技能|能力|agent总管|智能体/.test(question.toLowerCase()); }
function isMemoryQuestion(question: string) { return /记忆|知识库|知识文件|经验/.test(question); }
function isPageQuestion(question: string) { return /当前页|当前页面|页面内容|页面有什么|可操作|动作目录|页面操作|有哪些按钮|有哪些菜单|有哪些下拉/.test(question); }

function metricAnswer(question: string, metrics: Array<Record<string, unknown>>) {
  const terms = question.replace(/指标|口径|取值逻辑|公式|有哪些|查询|查看|帮我|请|？|\?|的|和|与|全部/g, " ").split(/\s+/).map((item) => item.trim()).filter((item) => item.length >= 2);
  const matches = terms.length ? metrics.filter((metric) => terms.some((term) => [metric.metricName, metric.metricId, metric.definition, metric.valueLogic, metric.sourceTable].join(" ").includes(term))) : metrics;
  const shown = matches.slice(0, 8);
  return `当前可见指标共 ${metrics.length} 条${terms.length ? `，匹配 “${terms.join("、")}” 的有 ${matches.length} 条` : ""}。\n\n${shown.map((metric) => `• ${String(metric.metricName || metric.metricId)}\n  口径：${String(metric.definition || "未配置")}\n  取值：${String(metric.valueLogic || "未配置")}\n  来源：${String(metric.sourceTable || "未配置")}`).join("\n\n") || "未找到匹配指标。可以换指标名称、表名或口径关键词。"}${matches.length > shown.length ? `\n\n其余 ${matches.length - shown.length} 条请在“指标管理”中查看。` : ""}`;
}

function memoryLabel(memory: Record<string, unknown>) {
  return String(memory.title || memory.name || memory.summary || memory.memory_id || "未命名记忆").replace(/\s+/g, " ").slice(0, 100);
}

async function runAnalysis(question: string, context: { tenantId: string; userId: string; selectedInstitution: string; currentTenantRoles: Array<{ role: string }>; appendMessage: (message: Omit<Message, "id">) => void }) {
  const response = await waitForSelfAnalysis({
    question,
    tenantId: context.tenantId,
    userId: context.userId,
    requestId: crypto.randomUUID(),
    pageContext: {
      route: "agent_supervisor",
      selected_institution: context.selectedInstitution,
      analysis_trigger: "agent_supervisor",
      model_application_module: "intelligent_analysis_reasoning",
      page_roles: context.currentTenantRoles.map((role) => role.role),
    },
  });
  const result = reviewableAnalysisResult(response);
  const conclusions = (response.conclusions || []).filter((item) => item.trim());
  if (!result || !conclusions.length) throw new Error("分析没有形成可复核的结论和结构化证据。总管不会补写默认结论或伪造图表，请在自助分析检查数据连接、权限和执行结果。");
  const formal = isFormalAnalysis(response, result);
  const chart = buildChart(result, formal ? "formal" : "exercise");
  const evidenceId = String(result.evidence?.evidence_id || "已绑定");
  const source = String(result.evidence?.data_source || result.semantic_info?.data_source || "未知数据源");
  const prefix = formal
    ? "正式分析结果：已通过真实数据、证据和发布闸门。"
    : `本地演练结果：数据源为 ${source}，当前未通过正式发布闸门；以下图表和结论仅供功能演练，不能用于正式经营决策或外发。`;
  context.appendMessage({ role: "agent", content: `${prefix}\n\n${conclusions.join("\n")}\n\n任务：${response.task_id}\n证据：${evidenceId}`, chart });
}

function reviewableAnalysisResult(response: BackendAnalysisResponse): BackendSkillResult | null {
  const result = response.skill_results?.[0];
  const evidence = result?.evidence;
  const review = response.review || {};
  const sourceSnapshot = evidence?.source_snapshot || result?.semantic_info?.source_snapshot;
  return response.status === "completed" && review.status === "passed" && Boolean(evidence?.evidence_id) && Boolean(sourceSnapshot && Object.keys(sourceSnapshot).length) ? result || null : null;
}

function isFormalAnalysis(response: BackendAnalysisResponse, result: BackendSkillResult) {
  const review = response.review || {};
  const semantic = result.semantic_info || {};
  return review.publication_gate === "allowed" && semantic.execution_mode === "real" && semantic.publishable === true;
}

function buildChart(result: BackendSkillResult, mode: ChartData["mode"]): ChartData | undefined {
  const artifact = result.visualization_artifact;
  const series = artifact?.series || [];
  const rows = series.map((item, index) => ({ label: String(item.name || `分组${index + 1}`), value: Number(item.value) })).filter((item) => Number.isFinite(item.value)).slice(0, 12);
  return rows.length ? { title: String(artifact?.title || "分析结果"), metric: String(artifact?.y || "指标值"), rows, mode } : undefined;
}

function parseFieldFill(question: string) {
  const match = question.match(/(?:把|在)?\s*[“"']?([^“”"'，。,.！!]{1,40}?)[”"']?\s*(?:填写为|填入|输入|设置为|改为)\s*[“"']?(.+?)[”"']?\s*$/);
  return match ? { label: stripQuotes(match[1]), value: stripQuotes(match[2]) } : null;
}

function parseCheckboxAction(question: string) {
  const match = question.match(/(取消勾选|取消选择|取消选中|勾选|选择|选中)\s*[“"']?([^“”"'，。,.！!]{1,40})/);
  if (!match) return null;
  return { checked: !match[1].startsWith("取消"), label: stripQuotes(match[2]) };
}

function hasExplicitPageOperation(question: string) {
  return /(?:点击|展开|关闭|选择|切换到|填写为|填入|输入|设置为|改为|勾选|取消勾选|取消选择|取消选中)/.test(question);
}

function setNativeValue(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const prototype = Object.getPrototypeOf(element) as { constructor: { prototype: object } };
  const descriptor = Object.getOwnPropertyDescriptor(prototype.constructor.prototype, "value");
  descriptor?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function elementLabel(element: HTMLElement) {
  const aria = element.getAttribute("aria-label") || "";
  const labelledBy = (element.getAttribute("aria-labelledby") || "").split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" ");
  const title = element.getAttribute("title") || "";
  const placeholder = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement ? element.placeholder : "";
  const name = element.getAttribute("name") || "";
  const id = element.id;
  const explicitLabel = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`)?.textContent || "" : "";
  const parentLabel = element.closest("label")?.textContent || "";
  const text = element.textContent || "";
  // Native select text includes every option. Prefer the semantic label and
  // only fall back to the currently selected option, which keeps the action
  // directory readable and makes matching much less ambiguous.
  const selectValue = element instanceof HTMLSelectElement ? element.selectedOptions[0]?.textContent || "" : "";
  return normalizeText(aria || labelledBy || title || explicitLabel || placeholder || parentLabel || selectValue || text || name || id || element.tagName.toLowerCase()).slice(0, 100);
}

function isUsableElement(element: HTMLElement) {
  if (element.closest(supervisorSelector)) return false;
  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
}

function dedupeControls(controls: PageControl[]) {
  const seen = new Set<string>();
  return controls.filter((control) => {
    const key = `${control.kind}:${control.label}`;
    if (!control.label || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function controlKindLabel(kind: PageControlKind) {
  return ({ button: "按钮", link: "菜单/链接", select: "下拉框", input: "输入框", textarea: "文本框", checkbox: "复选框", radio: "单选项", tab: "页签", dialog: "弹窗" } satisfies Record<PageControlKind, string>)[kind];
}

function normalizeText(value: string) { return value.replace(/\s+/g, "").trim(); }
function normalizedIncludes(value: string, needle: string) { return normalizeText(value).includes(normalizeText(needle)); }
function stripQuotes(value: string) { return value.trim().replace(/^[“”"']+|[“”"']+$/g, "").trim(); }
function extractRequestedLabel(question: string) {
  const match = question.match(/(?:点击|打开|展开|关闭|选择)\s*[“"']?([^“”"'，。,.！!]{1,40})/);
  return stripQuotes(match?.[1] || question).replace(/(按钮|菜单|下拉框|弹窗)$/, "");
}
function tokenOverlap(left: string, right: string) { return Array.from(new Set(right)).filter((item) => left.includes(item)).length; }
function unique(value: string, index: number, values: string[]) { return Boolean(value) && values.indexOf(value) === index; }
