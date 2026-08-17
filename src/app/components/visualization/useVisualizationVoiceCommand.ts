import { useEffect, useRef, useState } from "react";
import { usePlatformContext } from "../../platform/PlatformContext";
import { fetchAnalysisRuntimeConfig } from "../../services/systemConfigApi";
import {
  buildFunAsrRealtimeUrl,
  downsampleToPcm16,
  funAsrErrorMessage,
  funAsrSampleRate,
  getAudioContextConstructor,
  normalizeVoiceSegment,
  type FunAsrProxyEvent,
} from "../self-analysis/domain";

export function useVisualizationVoiceCommand(onCommand: (command: string) => void) {
  const { tenantId, userId } = usePlatformContext();
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const activeRef = useRef(false);
  const socketRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const finalRef = useRef("");
  const draftRef = useRef("");
  const silenceTimerRef = useRef<number | null>(null);
  const lastDispatchedRef = useRef("");

  const clearSilenceTimer = () => {
    if (silenceTimerRef.current !== null) window.clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = null;
  };

  const scheduleCommand = () => {
    clearSilenceTimer();
    silenceTimerRef.current = window.setTimeout(() => {
      const command = normalizeVoiceSegment(`${finalRef.current} ${draftRef.current}`);
      if (command && command !== lastDispatchedRef.current) {
        lastDispatchedRef.current = command;
        onCommand(command);
      }
      finalRef.current = "";
      draftRef.current = "";
      setTranscript("");
    }, 1_000);
  };

  const cleanup = () => {
    try { processorRef.current?.disconnect(); } catch { /* already disconnected */ }
    try { sourceRef.current?.disconnect(); } catch { /* already disconnected */ }
    processorRef.current = null;
    sourceRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioRef.current?.close().catch(() => undefined);
    audioRef.current = null;
  };

  const stop = () => {
    clearSilenceTimer();
    activeRef.current = false;
    if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify({ type: "finish" }));
    socketRef.current?.close();
    socketRef.current = null;
    cleanup();
    setListening(false);
  };

  useEffect(() => () => stop(), []);

  const start = async () => {
    setError("");
    setTranscript("");
    finalRef.current = "";
    draftRef.current = "";
    lastDispatchedRef.current = "";
    try {
      const runtime = await fetchAnalysisRuntimeConfig({ tenantId, userId, speechApplicationModule: "realtime_voice_input" });
      if (!runtime.speechIntegration) throw new Error("当前机构未启用实时语音配置");
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("当前浏览器不支持麦克风采集");
      const AudioContextConstructor = getAudioContextConstructor();
      if (!AudioContextConstructor) throw new Error("当前浏览器不支持实时音频采集");
      activeRef.current = true;
      setListening(true);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!activeRef.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      streamRef.current = stream;
      const socket = new WebSocket(buildFunAsrRealtimeUrl(tenantId, userId, "realtime_voice_input"));
      socketRef.current = socket;
      socket.onopen = () => socket.send(JSON.stringify({
        type: "start",
        provider: "aliyun_fun_asr",
        speechIntegrationId: runtime.speechIntegration!.id,
        applicationModule: "realtime_voice_input",
        sampleRate: funAsrSampleRate,
        context: [{ role: "user", content: [{ type: "input_text", text: "可视化样式、指标与维度配置" }] }],
      }));
      socket.onmessage = (event) => {
        let payload: FunAsrProxyEvent;
        try { payload = JSON.parse(String(event.data)); } catch { return; }
        if (payload.type === "ready") {
          const audio = new AudioContextConstructor({ sampleRate: funAsrSampleRate });
          const source = audio.createMediaStreamSource(stream);
          const processor = audio.createScriptProcessor(4096, 1, 1);
          processor.onaudioprocess = (audioEvent) => {
            audioEvent.outputBuffer.getChannelData(0).fill(0);
            if (!activeRef.current || socket.readyState !== WebSocket.OPEN) return;
            socket.send(downsampleToPcm16(audioEvent.inputBuffer.getChannelData(0), audio.sampleRate, funAsrSampleRate).buffer.slice(0));
          };
          source.connect(processor);
          processor.connect(audio.destination);
          audioRef.current = audio;
          sourceRef.current = source;
          processorRef.current = processor;
        } else if (payload.type === "transcript") {
          const text = normalizeVoiceSegment(payload.text || "");
          if (!text) return;
          if (payload.final) {
            finalRef.current = normalizeVoiceSegment(`${finalRef.current} ${text}`);
            draftRef.current = "";
          } else draftRef.current = text;
          const next = normalizeVoiceSegment(`${finalRef.current} ${draftRef.current}`);
          setTranscript(next);
          scheduleCommand();
        } else if (payload.type === "error") {
          setError(funAsrErrorMessage(payload.message || ""));
          stop();
        }
      };
      socket.onerror = () => { setError("实时语音连接中断，请重试"); stop(); };
      socket.onclose = () => { if (activeRef.current) { cleanup(); activeRef.current = false; setListening(false); } };
    } catch (caught) {
      stop();
      setError(funAsrErrorMessage(caught instanceof Error ? caught.message : "实时语音未启动"));
    }
  };

  return { listening, transcript, error, toggle: () => listening ? stop() : void start(), stop };
}
