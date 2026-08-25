import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, AudioLines, BarChart3, CheckCircle2, ChevronDown, ChevronUp, Database, LoaderCircle, Maximize2, Minimize2, Sparkles, Square } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { waitForSelfAnalysis, type AnalysisProgressStep, type BackendAnalysisResponse } from "../../services/analysisApi";
import { runApplicationAction } from "../../services/applicationApi";
import { ApiRequestError } from "../../services/apiClient";
import {
  appendAnalysisTurn,
  createAnalysisBranch,
  ensureAnalysisWorkspace,
  fetchAnalysisWorkspace,
  type AnalysisThread,
} from "../../services/analysisWorkspaceApi";
import type { AnalysisSkillAsset, TopicTableAsset } from "../../services/dataAssetApi";
import { fetchAnalysisRuntimeConfig } from "../../services/systemConfigApi";
import { createClientUuid } from "../../utils/clientUuid";
import { AnalysisProgressPanel } from "../self-analysis/AnalysisProgressPanel";
import { TrustedArtifactPanel } from "../analysis-workspace/TrustedArtifactPanel";
import { completedProgressSteps } from "../self-analysis/analysisRuntime";
import {
  appendRealtimeVoiceText,
  buildFunAsrRealtimeUrl,
  downsampleToPcm16,
  funAsrErrorMessage,
  funAsrSampleRate,
  getAudioContextConstructor,
  normalizeVoiceSegment,
  realtimeVoiceSilenceAnalysisMs,
  type FunAsrProxyEvent,
} from "../self-analysis/domain";
import {
  createRealtimeSpeakerGateState,
  extractRealtimeVoiceAnalysisCommand,
  gateRealtimeSpeakerFrame,
  type RealtimeSpeakerGateState,
  type RealtimeVoiceTrigger,
} from "../self-analysis/realtimeVoice";
import type { CommentTarget, ReportBlock, WeeklyInstitutionReport } from "./domain";

type AnalysisTrigger = "manual" | RealtimeVoiceTrigger;
type ResultTab = "thinking" | "data" | "visual" | "summary";

export function WeeklyContextAnalysisPanel({
  report,
  target,
  tenantId,
  userId,
  selectedInstitution,
  topicTable,
  analysisSkill,
  memoryIds,
  pageKey = "weekly-report",
  pageTitle = "经营周报",
  overallPrompt = "请结合当前页面及关联指标数据进行总体分析，说明关键变化、风险与建议。",
  noDataMessage = "本页面没有找到这一数据，请检查要分析的内容",
  active = false,
  onActivate,
  onComplete,
  onStartedChange,
  railWide = false,
  onRailWideChange,
}: {
  report: WeeklyInstitutionReport;
  target: CommentTarget | null;
  tenantId: string;
  userId: string;
  selectedInstitution: string;
  topicTable: TopicTableAsset | null;
  analysisSkill: AnalysisSkillAsset | null;
  memoryIds: string[];
  railHeight: number;
  pageKey?: string;
  pageTitle?: string;
  overallPrompt?: string;
  noDataMessage?: string;
  active?: boolean;
  onActivate?: () => void;
  onComplete?: () => void;
  onStartedChange?: (started: boolean) => void;
  railWide?: boolean;
  onRailWideChange?: (wide: boolean) => void;
}) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const silenceTimerRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const expectedCloseRef = useRef<"session_end" | "">("");
  const voiceActiveRef = useRef(false);
  const voiceBaseRef = useRef("");
  const voiceFinalRef = useRef("");
  const voiceDraftRef = useRef("");
  const voiceRenderedRef = useRef("");
  const speakerGateRef = useRef<RealtimeSpeakerGateState>(createRealtimeSpeakerGateState());
  const ignoredSpeakersRef = useRef(0);
  const questionRef = useRef("");
  const analyzingRef = useRef(false);
  const lastAutoQuestionRef = useRef("");
  const queuedAnalysisRef = useRef<{ question: string; trigger: AnalysisTrigger } | null>(null);
  const workspaceRef = useRef<{ workspaceId: string; threadId: string } | null>(null);
  const mountedRef = useRef(true);

  const [question, setQuestion] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);
  const [activeResultTab, setActiveResultTab] = useState<ResultTab>("thinking");
  const [progressSteps, setProgressSteps] = useState<AnalysisProgressStep[]>([]);
  const [response, setResponse] = useState<BackendAnalysisResponse | null>(null);
  const [analysisError, setAnalysisError] = useState("");
  const [voiceListening, setVoiceListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [voiceprintStatus, setVoiceprintStatus] = useState<"idle" | "calibrating" | "locked">("idle");
  const [ignoredSpeakers, setIgnoredSpeakers] = useState(0);
  const [collapsed, setCollapsed] = useState(false);

  const context = useMemo(() => buildWeeklyReportContext(report, target), [report, target]);
  const backendRows = response?.skill_results?.[0]?.data || [];
  const rows = backendRows.length
    ? backendRows
    : context.dataModule?.type === "table"
      ? context.dataModule.rows
      : [];
  const summary = response?.intelligent_analysis?.analysis_summary?.trim()
    || response?.conclusions?.filter((item) => item.trim()).join("\n")
    || "";
  const chart = useMemo(() => buildChartData(response, rows), [response, rows]);

  useEffect(() => {
    questionRef.current = question;
  }, [question]);

  useEffect(() => {
    analyzingRef.current = isAnalyzing;
  }, [isAnalyzing]);

  useEffect(() => {
    onStartedChange?.(hasStarted);
  }, [hasStarted, onStartedChange]);

  useEffect(() => {
    stopRealtimeVoice(false);
    const nextQuestion = target
      ? `请分析选中的${target.type}“${(target.selectedText || target.label).slice(0, 120)}”，说明关键变化、原因、风险与建议。`
      : overallPrompt;
    setQuestion(nextQuestion);
    questionRef.current = nextQuestion;
    setResponse(null);
    setHasStarted(false);
    setProgressSteps([]);
    setAnalysisError("");
    setActiveResultTab("thinking");
    setCollapsed(false);
    if (!target?.selectedText?.trim()) window.setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 0);
  }, [target?.id, overallPrompt]);

  useEffect(() => {
    let cancelled = false;
    workspaceRef.current = null;
    const selectedDataPoint = target ? {
      targetType: target.type === "数据" ? "table" as const : target.type === "文本" ? "text" as const : "chart" as const,
      targetId: target.id,
      label: target.label,
      values: { blockId: target.blockId, selectedText: target.selectedText },
    } : undefined;
    ensureAnalysisWorkspace(`${pageKey}:${report.id}`, {
      pageKey,
      artifactId: report.id,
      datasetSnapshot: {},
      metricVersions: [],
      filters: { institution: selectedInstitution },
      selectedDataPoint,
      allowedActions: ["follow_up", "branch", "merge", "trust", "freeze_report", "rerun"],
      evidenceRefs: [],
    }, { tenantId, userId }).then(async ({ workspace }) => {
      const loaded = await fetchAnalysisWorkspace(workspace.workspace_id, { tenantId, userId });
      if (cancelled) return;
      let thread: AnalysisThread | undefined;
      if (target) {
        thread = loaded.threads.find((item) => item.anchor?.target_id === target.id);
        if (!thread) {
          const created = await createAnalysisBranch(
            workspace.workspace_id,
            loaded.threads.find((item) => !item.parent_thread_id)?.thread_id || null,
            target.label || "图表分析分支",
            { target_id: target.id, target_type: target.type, block_id: target.blockId },
            { tenantId, userId },
          );
          thread = created.thread;
        }
      } else {
        thread = loaded.threads.find((item) => !item.parent_thread_id);
      }
      if (!cancelled && thread) workspaceRef.current = { workspaceId: workspace.workspace_id, threadId: thread.thread_id };
    }).catch(() => {
      // Existing page analysis remains usable; the run itself will surface any API failure.
    });
    return () => { cancelled = true; };
  }, [pageKey, report.id, selectedInstitution, target?.id, tenantId, userId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stopRealtimeVoice(false);
    };
  }, []);

  function resetVoiceTranscript(baseText: string) {
    voiceBaseRef.current = baseText;
    voiceFinalRef.current = "";
    voiceDraftRef.current = "";
    voiceRenderedRef.current = baseText;
  }

  function clearSilenceTimer() {
    if (silenceTimerRef.current === null) return;
    window.clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = null;
  }

  function clearReconnectTimer() {
    if (reconnectTimerRef.current === null) return;
    window.clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
  }

  function cleanupAudio() {
    try { processorRef.current?.disconnect(); } catch { /* already disconnected */ }
    try { sourceRef.current?.disconnect(); } catch { /* already disconnected */ }
    processorRef.current = null;
    sourceRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
  }

  function stopRealtimeVoice(sendFinish = true) {
    clearSilenceTimer();
    clearReconnectTimer();
    expectedCloseRef.current = "";
    voiceActiveRef.current = false;
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN && sendFinish) {
      socket.send(JSON.stringify({ type: "finish" }));
    }
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
    socketRef.current = null;
    cleanupAudio();
    if (mountedRef.current) {
      setVoiceListening(false);
      setVoiceprintStatus("idle");
    }
  }

  function scheduleSilenceAnalysis(candidate?: string) {
    clearSilenceTimer();
    if (!voiceActiveRef.current) return;
    const seed = normalizeVoiceSegment(candidate || voiceRenderedRef.current || questionRef.current);
    if (!seed) return;
    silenceTimerRef.current = window.setTimeout(() => {
      silenceTimerRef.current = null;
      if (!voiceActiveRef.current) return;
      const nextQuestion = normalizeVoiceSegment(voiceRenderedRef.current || questionRef.current);
      if (!nextQuestion || nextQuestion === lastAutoQuestionRef.current) return;
      lastAutoQuestionRef.current = nextQuestion;
      resetVoiceTranscript("");
      void runAnalysis(nextQuestion, "realtime_voice_silence");
    }, realtimeVoiceSilenceAnalysisMs);
  }

  function applyTranscript(text: string, isFinal: boolean) {
    const normalized = normalizeVoiceSegment(text);
    if (!normalized) return;
    if (isFinal) {
      voiceFinalRef.current = normalizeVoiceSegment(`${voiceFinalRef.current} ${normalized}`);
      voiceDraftRef.current = "";
    } else {
      voiceDraftRef.current = normalized;
    }
    const recognized = normalizeVoiceSegment(`${voiceFinalRef.current} ${voiceDraftRef.current}`);
    const nextQuestion = appendRealtimeVoiceText(voiceBaseRef.current, recognized);
    voiceRenderedRef.current = nextQuestion;
    questionRef.current = nextQuestion;
    setQuestion(nextQuestion);
    if (isFinal) {
      const command = extractRealtimeVoiceAnalysisCommand(nextQuestion);
      if (command.triggered) {
        clearSilenceTimer();
        if (!command.query || command.query === lastAutoQuestionRef.current) return;
        lastAutoQuestionRef.current = command.query;
        resetVoiceTranscript("");
        setQuestion(command.query);
        questionRef.current = command.query;
        void runAnalysis(command.query, "realtime_voice_keyword");
        return;
      }
    }
    scheduleSilenceAnalysis(nextQuestion);
    inputRef.current?.focus();
  }

  async function startAudioStream(socket: WebSocket, stream: MediaStream) {
    const AudioContextConstructor = getAudioContextConstructor();
    if (!AudioContextConstructor) throw new Error("当前浏览器不支持实时音频采集，可继续直接输入。");
    const audioContext = new AudioContextConstructor({ sampleRate: funAsrSampleRate });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (event) => {
      event.outputBuffer.getChannelData(0).fill(0);
      if (!voiceActiveRef.current || socket.readyState !== WebSocket.OPEN) return;
      const channel = event.inputBuffer.getChannelData(0);
      const gated = gateRealtimeSpeakerFrame(speakerGateRef.current, channel, audioContext.sampleRate);
      speakerGateRef.current = gated.state;
      if (gated.justLocked) setVoiceprintStatus("locked");
      if (gated.rejectedSpeakerStarted) {
        ignoredSpeakersRef.current += 1;
        setIgnoredSpeakers(ignoredSpeakersRef.current);
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
    audioContextRef.current = audioContext;
    sourceRef.current = source;
    processorRef.current = processor;
  }

  async function startRealtimeVoice(preserveSpeakerProfile = false) {
    setVoiceError("");
    let integration = null;
    try {
      const runtime = await fetchAnalysisRuntimeConfig({
        tenantId,
        userId,
        speechApplicationModule: "realtime_voice_input",
      });
      integration = runtime.speechIntegration;
    } catch (error) {
      setVoiceError(voiceStartupErrorMessage(error));
      return;
    }
    if (!integration) {
      setVoiceError("当前机构没有已启用的阿里云 Fun-ASR 接入。请在模型接入管理的语音转文字中配置实时语音录入模块。");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setVoiceError("当前浏览器不支持实时麦克风采集，可继续直接输入。");
      return;
    }

    clearSilenceTimer();
    clearReconnectTimer();
    const priorSocket = socketRef.current;
    if (priorSocket && priorSocket.readyState < WebSocket.CLOSING) priorSocket.close();
    socketRef.current = null;
    cleanupAudio();
    voiceActiveRef.current = true;
    setVoiceListening(true);
    resetVoiceTranscript(questionRef.current);
    if (!preserveSpeakerProfile) {
      speakerGateRef.current = createRealtimeSpeakerGateState();
      ignoredSpeakersRef.current = 0;
      reconnectAttemptsRef.current = 0;
      setIgnoredSpeakers(0);
      setVoiceprintStatus("calibrating");
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!voiceActiveRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      const socket = new WebSocket(buildFunAsrRealtimeUrl(tenantId, userId, "realtime_voice_input"));
      socketRef.current = socket;
      socket.onopen = () => {
        if (!voiceActiveRef.current) return;
        socket.send(JSON.stringify({
          type: "start",
          provider: "aliyun_fun_asr",
          speechIntegrationId: integration.id,
          applicationModule: "realtime_voice_input",
          sampleRate: funAsrSampleRate,
          context: [{
            role: "user",
            content: [{
              type: "input_text",
              text: `${pageTitle}；当前范围：${target?.label || "全页总体分析"}；机构：${report.institutionName}`.slice(0, 400),
            }],
          }],
        }));
      };
      socket.onmessage = (event) => {
        if (!voiceActiveRef.current) return;
        let payload: FunAsrProxyEvent;
        try { payload = JSON.parse(String(event.data)) as FunAsrProxyEvent; } catch { return; }
        if (payload.type === "ready") {
          reconnectAttemptsRef.current = 0;
          setVoiceError("");
          void startAudioStream(socket, stream).catch((error) => {
            setVoiceError(errorMessage(error, "实时音频采集失败，可继续直接输入。"));
            stopRealtimeVoice(false);
          });
          return;
        }
        if (payload.type === "config" && payload.provider !== "aliyun_fun_asr") {
          setVoiceError("语音入口未连接阿里云 Fun-ASR，已停止本次录音。");
          stopRealtimeVoice(false);
          return;
        }
        if (payload.type === "transcript") {
          applyTranscript(payload.text || "", Boolean(payload.final));
          return;
        }
        if (payload.type === "error") {
          setVoiceError(funAsrErrorMessage(payload.message || ""));
          stopRealtimeVoice(false);
          return;
        }
        if (payload.type === "finished") {
          expectedCloseRef.current = "session_end";
          socket.close();
        }
      };
      socket.onerror = () => {
        if (!voiceActiveRef.current) return;
        setVoiceError("实时语音连接中断，正在自动重连…");
        socket.close();
      };
      socket.onclose = () => {
        if (!voiceActiveRef.current) return;
        const expectedClose = expectedCloseRef.current;
        expectedCloseRef.current = "";
        socketRef.current = null;
        cleanupAudio();
        setVoiceListening(true);
        if (expectedClose !== "session_end") {
          setVoiceError("实时语音连接中断，正在自动重连…");
        }
        const attempt = reconnectAttemptsRef.current + 1;
        reconnectAttemptsRef.current = attempt;
        const delay = expectedClose === "session_end" ? 0 : Math.min(10_000, 800 * 2 ** Math.min(attempt - 1, 4));
        reconnectTimerRef.current = window.setTimeout(() => {
          reconnectTimerRef.current = null;
          if (voiceActiveRef.current) void startRealtimeVoice(true);
        }, delay);
      };
      void runApplicationAction({
        tenantId,
        userId,
        moduleKey: pageKey === "weekly-report" ? "weekly_report" : "dashboard",
        action: "start_realtime_voice",
        payload: {
          targetId: target?.id || `${pageKey}:overall`,
          reportId: report.id,
          speechIntegrationId: integration.id,
          applicationModule: "realtime_voice_input",
        },
      }).catch(() => undefined);
    } catch (error) {
      stopRealtimeVoice(false);
      setVoiceError(funAsrErrorMessage(errorMessage(error, "实时语音未启动，可继续直接输入。")));
    }
  }

  async function runAnalysis(candidate: string, trigger: AnalysisTrigger) {
    const nextQuestion = candidate.trim();
    if (!nextQuestion) {
      setAnalysisError("请输入明确的分析问题后再执行。");
      inputRef.current?.focus();
      return;
    }
    clearSilenceTimer();
    if (analyzingRef.current) {
      queuedAnalysisRef.current = { question: nextQuestion, trigger };
      return;
    }
    resetVoiceTranscript("");
    setQuestion(nextQuestion);
    questionRef.current = nextQuestion;
    setHasStarted(true);
    setIsAnalyzing(true);
    analyzingRef.current = true;
    setResponse(null);
    setAnalysisError("");
    setActiveResultTab("thinking");
    setProgressSteps([{
      step_code: "request_queued",
      sequence_no: 0,
      status: "queued",
      output_refs: [{ label: "创建分析任务", detail: "正在装载选中周报模块及其数据上下文。" }],
    }]);

    const selectedTables = topicTable && target?.blockId?.endsWith("_core_metrics")
      ? [topicTableToSelection(topicTable)]
      : [];
    const contextText = serializeWeeklyContext(context);
    const sessionId = `${pageKey.replace(/[^a-z0-9_-]/gi, "_")}_context_${report.id}_${target?.id || "overall"}`;
    const realtimeTrigger = trigger === "realtime_voice_keyword" || trigger === "realtime_voice_silence";
    try {
      const nextResponse = await waitForSelfAnalysis({
        question: nextQuestion,
        tenantId,
        userId,
        requestId: createClientUuid(),
        onRun: (run) => {
          if (mountedRef.current) setProgressSteps(run.progress_steps || []);
        },
        pageContext: {
          route: `${pageKey}/context-analysis`,
          page_title: pageTitle,
          selected_institution: selectedInstitution,
          analysis_trigger: trigger,
          model_application_module: "intelligent_analysis_reasoning",
          weekly_report_context: context,
          conversation_session: {
            session_id: sessionId,
            current_question: nextQuestion,
            turn_count: 1,
            compression_enabled: false,
            turns: [{
              id: `turn_${Date.now()}`,
              role: "user",
              content: `${contextText}\n\n用户问题：${nextQuestion}`,
              createdAt: new Date().toISOString(),
              query: nextQuestion,
            }],
          },
          analysis_skill: analysisSkill || { id: pageKey, name: `${pageTitle}分析`, category: "场景", description: `按${pageTitle}当前页面及关联指标分析业绩、波动、风险与行动项。` },
          analysis_context_skills: analysisSkill ? [analysisSkill] : [{ id: pageKey, name: `${pageTitle}分析`, category: "场景", description: `按${pageTitle}当前页面及关联指标分析业绩、波动、风险与行动项。` }],
          selected_data_tables: selectedTables,
          analysis_memory_ids: memoryIds,
          realtime_voice_auto_analysis: realtimeTrigger ? {
            enabled: true,
            trigger,
            silenceMs: realtimeVoiceSilenceAnalysisMs,
            commandKeyword: trigger === "realtime_voice_keyword" ? "开始分析" : null,
            contextInputs: ["input_text", "weekly_report_context", "selected_data_tables"],
            expectedOutputs: ["sql", "python_script", "visualization_suggestions", "analysis_summary"],
          } : null,
          analysis_policy: {
            engine: "IntelligentAnalysisEngine",
            resultDelivery: "data_first",
            multiRoleDebate: "reuse_weekly_learning_memory_chain_when_writing_back_experience",
            timeDecay: "preserve_knowledge_memory_weighting_and_do_not_override_current_fact_data",
            conflictStrategy: "selected_weekly_report_context_has_priority_for_current_run",
          },
          files: [],
          plugins: [],
        },
      });
      if (!mountedRef.current) return;
      setResponse(nextResponse);
      setProgressSteps(completedProgressSteps(nextResponse));
      setActiveResultTab("visual");
      const workspaceBinding = workspaceRef.current;
      if (workspaceBinding && !nextResponse.workspace_turn) {
        const answer = nextResponse.intelligent_analysis?.analysis_summary?.trim()
          || nextResponse.conclusions?.filter((item) => item.trim()).join("\n")
          || "本轮返回了数据产物，但没有生成文字结论。";
        await appendAnalysisTurn(workspaceBinding.threadId, {
          question: nextQuestion,
          answer,
          status: "completed",
          intent: nextResponse.analysis_plan || {},
          execution_plan: { progress_steps: completedProgressSteps(nextResponse), task_id: nextResponse.task_id },
          artifact_refs: nextResponse.skill_results?.flatMap((result) => result.visualization_artifact ? [{ type: "visualization", task_id: nextResponse.task_id }] : []) || [],
          evidence_refs: nextResponse.skill_results?.flatMap((result) => result.evidence ? [result.evidence] : []) || [],
        }, { tenantId, userId });
      }
      const hasReturnedData = Boolean(nextResponse.skill_results?.some((result) => (result.data || []).length))
        || Boolean(nextResponse.intelligent_analysis?.analysis_summary?.trim())
        || Boolean(nextResponse.conclusions?.some((item) => item.trim()));
      if (!hasReturnedData) setAnalysisError(noDataMessage);
      void runApplicationAction({
        tenantId,
        userId,
        moduleKey: pageKey === "weekly-report" ? "weekly_report" : "dashboard",
        action: "analyze_selected_context",
        payload: { reportId: report.id, targetId: target?.id || `${pageKey}:overall`, taskId: nextResponse.task_id, trigger },
      }).catch(() => undefined);
    } catch (error) {
      if (!mountedRef.current) return;
      setAnalysisError(errorMessage(error, "智能分析服务暂不可用。"));
    } finally {
      if (!mountedRef.current) return;
      setIsAnalyzing(false);
      analyzingRef.current = false;
      const queued = queuedAnalysisRef.current;
      queuedAnalysisRef.current = null;
      if (queued) window.setTimeout(() => void runAnalysis(queued.question, queued.trigger), 0);
    }
  }

  function handleQuestionChange(value: string) {
    setQuestion(value);
    questionRef.current = value;
    if (voiceActiveRef.current && value !== voiceRenderedRef.current) resetVoiceTranscript(value);
  }

  return (
    <article
      className={`overflow-hidden rounded-xl border bg-white transition-colors ${active ? "border-[#3370ff]" : "border-[#e5e5ea]"}`}
      data-weekly-context-analysis="true"
      data-context-analysis-card={target?.id || "overall"}
      data-context-analysis-active={active ? "true" : "false"}
      data-context-analysis-collapsed={collapsed ? "true" : "false"}
      data-context-analysis-started={hasStarted ? "true" : "false"}
      onMouseDown={() => onActivate?.()}
    >
      <header className="flex items-start gap-2 border-b border-[#f0f0f2] px-3 py-3">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-[#0a66c2]" />
        <div className="min-w-0 flex-1">
          <h3 className="text-[13px] text-[#1d1d1f]">{target ? target.label : `${pageTitle}总体分析`}</h3>
          <p className="mt-0.5 truncate text-[11px] text-[#8a8a8e]" title={target?.selectedText || target?.label || pageTitle}>
            {target ? `已引用：${target.selectedText || target.label}` : "范围：当前页面及关联指标数据"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <button type="button" aria-label="已完成" title="已完成" onClick={onComplete} className="flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] transition-colors hover:bg-[#edf8f0] hover:text-[#34a853]">
            <CheckCircle2 className="h-4 w-4" />
          </button>
          <button type="button" aria-label={railWide ? "恢复右栏宽度" : "放大右栏"} title={railWide ? "恢复宽度" : "放大右栏"} onClick={() => onRailWideChange?.(!railWide)} className="flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" data-context-analysis-wide-toggle="true">
            {railWide ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
          <button type="button" aria-label={collapsed ? "展开分析卡片" : "折叠分析卡片"} title={collapsed ? "展开" : "折叠"} onClick={() => setCollapsed((value) => !value)} className="flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]">
            {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>
        </div>
      </header>

      {collapsed ? (
        <button type="button" onClick={() => setCollapsed(false)} className="block w-full px-3 py-3 text-left">
          <span className="line-clamp-2 text-[11px] leading-5 text-[#636366]">{summary || analysisError || question}</span>
        </button>
      ) : (
        <div className="space-y-3 p-3" data-context-analysis-body="true">
          <section className="bg-transparent px-0.5" data-context-analysis-input="true">
            <textarea
              ref={inputRef}
              value={question}
              onChange={(event) => handleQuestionChange(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                  event.preventDefault();
                  void runAnalysis(question, "manual");
                }
              }}
              placeholder={target ? "针对选中内容继续提问" : overallPrompt}
              className="min-h-[88px] w-full resize-none bg-transparent px-1 text-[12px] leading-5 text-[#1d1d1f] outline-none placeholder:text-[#aeaeb2]"
            />
            <div className="mt-1 flex items-center justify-between gap-2 border-t border-[#ececf0] pt-2">
              <span className="text-[10px] text-[#aeaeb2]">⌘/Ctrl + Enter 分析</span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => voiceListening ? stopRealtimeVoice(true) : void startRealtimeVoice(false)}
                  className={`relative flex h-8 w-8 items-center justify-center rounded-full transition-colors ${voiceListening ? "text-[#0a84ff]" : "text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"}`}
                  aria-label={voiceListening ? "停止实时语音交互" : "实时语音交互"}
                  title={voiceListening ? "停止实时语音交互" : "实时语音交互"}
                >
                  {voiceListening && <span className="absolute -inset-1 animate-pulse rounded-full bg-gradient-to-r from-[#34c759]/40 via-[#0a84ff]/40 to-[#af52de]/40 blur-sm" />}
                  <AudioLines className="relative z-10 h-4 w-4" />
                </button>
                <button type="button" onClick={() => void runAnalysis(question, "manual")} disabled={!question.trim() || isAnalyzing} className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1d1d1f] text-white transition-colors hover:bg-[#2c2c2e] disabled:opacity-35" aria-label="开始分析">
                  {isAnalyzing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
                </button>
              </div>
            </div>
          </section>

          {voiceError && (
            <div role="status" className="flex items-start justify-between gap-2 rounded-lg bg-[#fff8eb] px-2.5 py-2 text-[10px] leading-4 text-[#8a5700]">
              <span>语音转文字提示：{voiceError}</span>
              {!voiceListening && (
                <button
                  type="button"
                  onClick={() => void startRealtimeVoice(false)}
                  className="shrink-0 rounded-md border border-[#e8c982] bg-white px-2 py-0.5 text-[#8a5700] transition-colors hover:bg-[#fff3d6]"
                >
                  重新连接
                </button>
              )}
            </div>
          )}
          {voiceListening && <div className="text-[10px] leading-4 text-[#0a84ff]">实时语音持续在线 · {voiceprintStatus === "locked" ? "已锁定首位说话人音色" : "正在识别首位说话人音色"}{ignoredSpeakers ? ` · 已过滤 ${ignoredSpeakers} 段其他说话人语音` : ""}{` · 静默 ${realtimeVoiceSilenceAnalysisMs / 1000} 秒自动分析`}</div>}

          {hasStarted && (
          <section className="-mx-3 -mb-3 overflow-hidden border-t border-[#ececf0] bg-white" data-weekly-analysis-results="true">
            <div className="grid grid-cols-4 gap-px border-b border-[#ececf0] bg-[#ececf0]">
              {([
                ["thinking", "思考链", Sparkles],
                ["data", "参考数据", Database],
                ["visual", "可视化分析", BarChart3],
                ["summary", "分析结论", Square],
              ] as const).map(([key, label, Icon]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveResultTab(key)}
                  className={`flex min-h-11 flex-col items-center justify-center gap-0.5 bg-white px-1 text-[9px] transition-colors ${
                    activeResultTab === key ? "text-[#0a66c2] shadow-[inset_0_-2px_0_#0a66c2]" : "text-[#8a8a8e] hover:bg-[#fafbfc]"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{label}</span>
                </button>
              ))}
            </div>
            <div className="max-h-[480px] overflow-auto p-3">
              {activeResultTab === "thinking" && (
                <AnalysisProgressPanel embedded steps={progressSteps} running={isAnalyzing} error={analysisError} hasResult={Boolean(response)} />
              )}
              {activeResultTab === "data" && <ReferenceData rows={rows} running={isAnalyzing} />}
              {activeResultTab === "visual" && <AnalysisChart chart={chart} running={isAnalyzing} />}
              {activeResultTab === "summary" && <AnalysisSummary summary={summary} running={isAnalyzing} error={analysisError} />}
              <TrustedArtifactPanel taskId={response?.task_id} compact />
            </div>
          </section>
          )}
        </div>
      )}
    </article>
  );
}

function buildWeeklyReportContext(report: WeeklyInstitutionReport, target: CommentTarget | null) {
  const section = report.sections.find((item) => item.blocks.some((block) => block.id === target?.blockId)) || null;
  const block = section?.blocks.find((item) => item.id === target?.blockId) || null;
  return {
    report: {
      id: report.id,
      institutionName: report.institutionName,
      projectNo: report.projectNo,
      meetingTime: report.meetingTime,
      reporters: report.reporters,
      period: report.period,
      status: report.status,
    },
    selection: target ? {
      id: target.id,
      label: target.label,
      type: target.type,
      targetKind: target.targetKind,
      selectedText: target.selectedText || "",
      blockId: target.blockId || "",
      itemId: target.itemId || "",
      rangeStart: target.rangeStart,
      rangeEnd: target.rangeEnd,
    } : null,
    section: section ? { id: section.id, name: section.name } : null,
    dataModule: block ? compactBlock(block) : null,
    pageData: target ? null : report.sections.map((item) => ({
      id: item.id,
      name: item.name,
      blocks: item.blocks.map(compactBlock),
    })),
  };
}

function compactBlock(block: ReportBlock) {
  if (block.type === "table") {
    return {
      id: block.id,
      type: block.type,
      title: block.title,
      dataSource: block.dataSource,
      updatedAt: block.updatedAt,
      fields: block.fields,
      rows: block.rows.slice(0, 200),
      analysisTaskId: block.analysisTaskId || "",
      evidenceRef: block.evidenceRef || null,
      currentConclusion: block.analysis.conclusion,
    };
  }
  return {
    id: block.id,
    type: block.type,
    title: block.title,
    content: block.content.slice(0, 20_000),
    contentItems: block.contentItems.slice(0, 100).map((item) => item.type === "paragraph"
      ? { id: item.id, type: item.type, text: item.text }
      : { id: item.id, type: item.type, name: item.name }),
  };
}

function serializeWeeklyContext(context: ReturnType<typeof buildWeeklyReportContext>) {
  const promptContext = {
    selection: context.selection,
    dataModule: context.dataModule,
    pageData: context.pageData,
    section: context.section,
    report: context.report,
  };
  return `以下为当前页面及选中内容的受治理数据上下文。必须优先依据其中的数据模块、字段、行数据、当前结论和证据引用回答；若问题所需数据不存在，必须回答“本页面没有找到这一数据，请检查要分析的内容”，不得猜测或使用内置数字。\n${JSON.stringify(promptContext)}`;
}

function topicTableToSelection(topic: TopicTableAsset) {
  const fields = Array.isArray(topic.fields)
    ? topic.fields.map((field) => `${field.fieldNameEn}(${field.fieldNameCn}:${field.type})`).join(", ")
    : String(topic.fields || "");
  return {
    id: topic.id,
    kind: "topic",
    name: topic.name,
    code: topic.code,
    description: topic.description,
    sql: topic.sql,
    fields,
  };
}

function ReferenceData({ rows, running }: { rows: Array<Record<string, unknown>>; running: boolean }) {
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 10);
  if (!rows.length) return <EmptyResult text={running ? "正在查询参考数据…" : "本次分析未返回可展示的数据行。"} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-[10px]">
        <thead className="bg-[#fafbfc] text-[#8a8a8e]">
          <tr>{columns.map((column) => <th key={column} className="whitespace-nowrap px-2 py-2 text-left font-normal">{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 100).map((row, index) => (
            <tr key={index} className="border-t border-[#f2f2f7]">
              {columns.map((column) => <td key={column} className="max-w-[180px] truncate whitespace-nowrap px-2 py-2 text-[#3a3a3c]" title={String(row[column] ?? "")}>{String(row[column] ?? "")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ChartData = { title: string; dimension: string; metric: string; points: Array<{ label: string; value: number }> } | null;

function buildChartData(response: BackendAnalysisResponse | null, rows: Array<Record<string, unknown>>): ChartData {
  const artifact = response?.skill_results?.[0]?.visualization_artifact;
  const series = artifact?.series?.filter((item) => typeof item.value === "number") || [];
  if (series.length) {
    return {
      title: artifact?.title || "分析结果",
      dimension: artifact?.x || "维度",
      metric: artifact?.y || "指标值",
      points: series.slice(0, 20).map((item, index) => ({ label: item.name || `第${index + 1}项`, value: Number(item.value) })),
    };
  }
  if (!rows.length) return null;
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const metric = columns.find((column) => rows.some((row) => parseMetric(row[column]) !== null));
  if (!metric) return null;
  const dimension = columns.find((column) => column !== metric) || metric;
  return {
    title: response?.skill_results?.[0]?.chart_spec?.title || "分析结果",
    dimension,
    metric,
    points: rows.slice(0, 20).map((row, index) => ({
      label: String(row[dimension] ?? `第${index + 1}项`),
      value: parseMetric(row[metric]) || 0,
    })),
  };
}

function parseMetric(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(String(value ?? "").replace(/,/g, "").match(/-?\d+(?:\.\d+)?/)?.[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function AnalysisChart({ chart, running }: { chart: ChartData; running: boolean }) {
  if (!chart) return <EmptyResult text={running ? "正在生成可视化分析…" : "当前结果缺少可绘制的数值字段，请查看参考数据与分析结论。"} />;
  return (
    <div>
      <div className="h-[260px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart.points} margin={{ top: 10, right: 6, bottom: 36, left: -20 }}>
            <CartesianGrid stroke="#ececf0" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#8a8a8e" }} angle={-28} textAnchor="end" interval={0} />
            <YAxis tick={{ fontSize: 9, fill: "#8a8a8e" }} />
            <Tooltip contentStyle={{ border: "1px solid #e5e5ea", borderRadius: 8, fontSize: 11 }} />
            <Bar dataKey="value" name={chart.metric} fill="#5b8def" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-[9px] text-[#aeaeb2]">维度：{chart.dimension} · 指标：{chart.metric}</p>
    </div>
  );
}

function AnalysisSummary({ summary, running, error }: { summary: string; running: boolean; error: string }) {
  if (!summary) return <EmptyResult text={running ? "正在基于周报上下文生成分析结论…" : error || "本次分析未返回结论。"} />;
  return <div className="whitespace-pre-wrap py-1 text-[11px] leading-6 text-[#3a3a3c]">{summary}</div>;
}

function EmptyResult({ text }: { text: string }) {
  return <div className="flex min-h-[220px] items-center justify-center px-4 text-center text-[11px] leading-5 text-[#8a8a8e]">{text}</div>;
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function voiceStartupErrorMessage(error: unknown) {
  if (error instanceof ApiRequestError) {
    if (error.status === 0 || error.code === "network_error" || error.code === "request_timeout") {
      return "Data Agent API 暂时不可用，本次语音未启动；文字分析仍可使用。服务恢复后可点击“重新连接”。";
    }
    if (error.status === 401) {
      return "登录状态已失效，本次语音未启动；请重新登录后再连接语音服务。";
    }
    if (error.status === 403) {
      return "当前账号没有使用实时语音的权限；文字分析仍可使用。";
    }
  }
  return funAsrErrorMessage(errorMessage(error, "语音模型运行配置加载失败，请稍后重试；文字分析仍可使用。"));
}
