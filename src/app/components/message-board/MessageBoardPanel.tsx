import { useEffect, useRef, useState, type ClipboardEvent } from "react";
import { AudioLines, ChevronDown, ChevronRight, LoaderCircle, MessageSquarePlus, Plus, Save, X } from "lucide-react";
import { fetchAnalysisRuntimeConfig } from "../../services/systemConfigApi";
import { createClientUuid } from "../../utils/clientUuid";
import {
  deleteMessageBoardEntry,
  createMessageBoardEntry,
  fetchMessageBoard,
  fetchMessageBoardAttachment,
  updateMessageBoardEntry,
  uploadMessageBoardImage,
  type MessageBoardEntry,
  type MessageBoardQuote,
} from "../../services/messageBoardApi";
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
import type { CommentTarget } from "../weekly-report/domain";

type DraftImage = { file: File; previewUrl: string };

export function MessageBoardPanel({
  tenantId,
  userId,
  pageKey,
  pageTitle,
  target,
}: {
  tenantId: string;
  userId: string;
  pageKey: string;
  pageTitle: string;
  target?: CommentTarget | null;
}) {
  const [messages, setMessages] = useState<MessageBoardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [draftOpen, setDraftOpen] = useState(false);
  const [editing, setEditing] = useState<MessageBoardEntry | null>(null);
  const [content, setContent] = useState("");
  const [images, setImages] = useState<DraftImage[]>([]);
  const imageUrlsRef = useRef(new Set<string>());
  const [saving, setSaving] = useState(false);
  const [archivingId, setArchivingId] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const messageIdRef = useRef(newMessageId());
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const voice = useMessageBoardVoice({ tenantId, userId, pageTitle, content, setContent, textareaRef });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchMessageBoard(pageKey, { tenantId, userId })
      .then((response) => { if (!cancelled) setMessages(response.messages); })
      .catch((error) => { if (!cancelled) setNotice(error instanceof Error ? error.message : "留言加载失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [pageKey, tenantId, userId]);

  useEffect(() => () => imageUrlsRef.current.forEach((url) => URL.revokeObjectURL(url)), []);

  const resetEditor = () => {
    voice.stop();
    imageUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    imageUrlsRef.current.clear();
    setImages([]);
    setContent("");
    setEditing(null);
    setDraftOpen(false);
    messageIdRef.current = newMessageId();
  };

  const openNew = () => {
    resetEditor();
    setDraftOpen(true);
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const openEdit = (message: MessageBoardEntry) => {
    resetEditor();
    messageIdRef.current = message.message_id;
    setEditing(message);
    setContent(message.content);
    setDraftOpen(true);
    setExpandedId(message.message_id);
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const addImages = (files: File[]) => {
    const accepted = files.filter((file) => file.type.startsWith("image/")).slice(0, Math.max(0, 5 - images.length));
    if (!accepted.length) return;
    if (accepted.some((file) => file.size > 5 * 1024 * 1024)) {
      setNotice("单张截图不能超过 5MB");
      return;
    }
    const next = accepted.map((file) => {
      const previewUrl = URL.createObjectURL(file);
      imageUrlsRef.current.add(previewUrl);
      return { file, previewUrl };
    });
    setImages((current) => [...current, ...next]);
  };

  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.files || []).filter((file) => file.type.startsWith("image/"));
    if (files.length) {
      event.preventDefault();
      addImages(files);
    }
  };

  const save = async () => {
    const text = content.trim();
    if (!text || saving) {
      if (!text) setNotice("请输入留言内容");
      return;
    }
    setSaving(true);
    setNotice("");
    voice.stop();
    try {
      const uploaded = await Promise.all(images.map((image) => uploadMessageBoardImage(image.file, messageIdRef.current, { tenantId, userId })));
      const attachmentIds = [
        ...(editing?.attachment_ids || []),
        ...uploaded.map((item) => item.attachment.attachment_id),
      ];
      const quote = quoteForTarget(target);
      const response = editing
        ? await updateMessageBoardEntry({
            message_id: editing.message_id,
            content: text,
            quote_context: Object.keys(editing.quote_context || {}).length ? editing.quote_context : quote,
            attachment_ids: attachmentIds,
            expected_lock_version: editing.lock_version,
          }, { tenantId, userId })
        : await createMessageBoardEntry({
            message_id: messageIdRef.current,
            page_key: pageKey,
            page_title: pageTitle,
            page_url: `${window.location.pathname}${window.location.search}${window.location.hash}`,
            content: text,
            quote_context: quote,
            attachment_ids: attachmentIds,
          }, { tenantId, userId });
      setMessages((current) => [response.message, ...current.filter((item) => item.message_id !== response.message.message_id)]);
      setNotice(editing ? "留言已更新" : "留言已保存");
      resetEditor();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "留言保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  const removeMessage = async (message: MessageBoardEntry) => {
    if (archivingId) return;
    setArchivingId(message.message_id);
    setNotice("");
    try {
      await deleteMessageBoardEntry(message.message_id, message.lock_version, { tenantId, userId });
      setMessages((current) => current.filter((item) => item.message_id !== message.message_id));
      setExpandedId((current) => current === message.message_id ? null : current);
      setNotice("留言已删除");
      if (editing?.message_id === message.message_id) resetEditor();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "留言存档失败，请刷新后重试");
    } finally {
      setArchivingId("");
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-message-board-panel="true">
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto overscroll-contain py-2">
      {notice && <div className="rounded-lg bg-white px-3 py-2 text-[11px] text-[#636366]" role="status">{notice}</div>}
      {loading ? (
        <div className="flex items-center justify-center py-10 text-[#8a8a8e]"><LoaderCircle className="h-4 w-4 animate-spin" /></div>
      ) : messages.map((message) => (
        <MessageCard key={message.message_id} message={message} expanded={expandedId === message.message_id} onToggle={() => setExpandedId((current) => current === message.message_id ? null : message.message_id)} onEdit={() => openEdit(message)} onArchive={() => void removeMessage(message)} archiving={archivingId === message.message_id} tenantId={tenantId} userId={userId} />
      ))}
      </div>
      <div className="shrink-0 border-t border-[#ececf0] bg-[#f7f8fa] pt-2" data-message-board-composer="true">
      <button
        type="button"
        onClick={openNew}
        className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[#b8cce2] bg-white px-3 py-3 text-[12px] text-[#0a66c2] transition-colors hover:border-[#0a66c2] hover:bg-[#f7fbff]"
        data-message-board-new="true"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#edf4fb]"><Plus className="h-3.5 w-3.5" /></span>
        新增留言
      </button>

      {draftOpen && (
        <article className="mt-2 rounded-xl border border-[#e5e5ea] bg-white" data-message-board-editor="true">
          <header className="flex items-center justify-between border-b border-[#f0f0f2] px-3 py-2.5">
            <div className="flex min-w-0 items-center gap-2 text-[12px] text-[#1d1d1f]">
              <MessageSquarePlus className="h-4 w-4 shrink-0 text-[#0a66c2]" />
              <span className="truncate">{editing ? "编辑留言" : "新增留言"}</span>
            </div>
            <button type="button" onClick={resetEditor} className="rounded-md p-1 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label="关闭留言编辑"><X className="h-3.5 w-3.5" /></button>
          </header>
          {target && !editing && (
            <div className="mx-3 mt-3 rounded-lg border-l-2 border-[#8bb7e6] bg-[#f7f9fc] px-3 py-2">
              <div className="text-[11px] text-[#636366]">引用 · {target.label || "页面内容"}</div>
            </div>
          )}
          <div className="p-3">
            <textarea
              ref={textareaRef}
              value={content}
              onChange={(event) => setContent(event.target.value)}
              onPaste={handlePaste}
              rows={5}
              maxLength={5000}
              placeholder="输入产品意见或需求；回车换行，也可直接粘贴截图。仅点击保存后提交。"
              className="w-full resize-none rounded-lg border border-[#e5e5ea] bg-transparent px-3 py-2 text-[13px] leading-6 text-[#1d1d1f] outline-none placeholder:text-[#b4b4b8]"
              data-message-board-input="true"
            />
            {images.length > 0 && (
              <div className="mt-2 grid grid-cols-3 gap-2">
                {images.map((image, index) => (
                  <div key={`${image.file.name}-${index}`} className="group relative aspect-square overflow-hidden rounded-lg border border-[#ececf0] bg-[#f7f8fa]">
                    <img src={image.previewUrl} alt="待上传截图" className="h-full w-full object-cover" />
                    <button type="button" onClick={() => { URL.revokeObjectURL(image.previewUrl); imageUrlsRef.current.delete(image.previewUrl); setImages((current) => current.filter((_, itemIndex) => itemIndex !== index)); }} className="absolute right-1 top-1 hidden rounded-full bg-black/60 p-1 text-white group-hover:block" aria-label="移除截图"><X className="h-3 w-3" /></button>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-2 flex items-center justify-between border-t border-[#f0f0f2] pt-2">
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => voice.listening ? voice.stop() : void voice.start()} className={`relative flex h-8 w-8 items-center justify-center rounded-full ${voice.listening ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"}`} title={voice.listening ? "停止实时语音录入" : "实时语音录入"} aria-label={voice.listening ? "停止实时语音录入" : "实时语音录入"}>
                  {voice.listening && <span className="absolute inset-0 animate-ping rounded-full bg-[#0a66c2]/15" />}
                  <AudioLines className="relative h-4 w-4" />
                </button>
                <span className="text-[10px] text-[#aeaeb2]">{voice.listening ? "正在实时转写" : `${content.length}/5000`}</span>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={resetEditor} disabled={saving} className="h-8 rounded-lg px-3 text-[11px] text-[#636366] hover:bg-[#f2f3f5] disabled:opacity-40">取消</button>
                <button type="button" onClick={() => void save()} disabled={saving || !content.trim()} className="flex h-8 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[11px] text-white hover:bg-[#2c2c2e] disabled:cursor-not-allowed disabled:opacity-40">
                  {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                  保存
                </button>
              </div>
            </div>
            {voice.error && <div className="mt-2 rounded-lg bg-[#fff7ed] px-2.5 py-2 text-[10px] leading-4 text-[#9a5b13]">语音提示：{voice.error}</div>}
          </div>
        </article>
      )}
      </div>
    </div>
  );
}

function MessageCard({ message, expanded, onToggle, onEdit, onArchive, archiving, tenantId, userId }: { message: MessageBoardEntry; expanded: boolean; onToggle: () => void; onEdit: () => void; onArchive: () => void; archiving: boolean; tenantId: string; userId: string }) {
  const quote = message.quote_context as MessageBoardQuote;
  return (
    <article className="overflow-hidden rounded-xl border border-[#e5e5ea] bg-white" data-message-board-card={message.message_id}>
      <div className="flex items-start gap-2 p-3">
        <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-start gap-2 text-left">
          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#0a66c2]" />
          <div className="min-w-0 flex-1">
            <div className={`${expanded ? "" : "line-clamp-2"} text-[13px] leading-5 text-[#1d1d1f]`}>{message.content}</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="rounded-full bg-[#edf4fb] px-2 py-0.5 text-[10px] text-[#0a66c2]">待办留言</span>
              <span className="rounded-full bg-[#f2f2f7] px-2 py-0.5 text-[10px] text-[#636366]">{message.page_title}</span>
              {quote?.selected_text && <span className="rounded-full bg-[#f5f1fb] px-2 py-0.5 text-[10px] text-[#7654a8]">已引用</span>}
            </div>
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-1">
          {message.status !== "new" && <StatusBadge status={message.status} />}
          <button type="button" onClick={onArchive} disabled={archiving} aria-label="删除留言" title="删除留言" className="flex h-7 w-7 items-center justify-center rounded-md text-[#8a8a8e] hover:bg-[#fff1f0] hover:text-[#d92d20] disabled:opacity-40">{archiving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}</button>
          <button type="button" onClick={onToggle} aria-label={expanded ? "折叠留言" : "展开留言"} className="flex h-7 w-7 items-center justify-center rounded-md text-[#8a8a8e] hover:bg-[#f2f3f5] hover:text-[#1d1d1f]">{expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button>
        </div>
      </div>
      {expanded && (
        <div className="border-t border-[#f0f0f2] px-3 pb-3 pt-2.5">
          {quote?.selected_text && <div className="rounded-lg border-l-2 border-[#8bb7e6] bg-[#f7f9fc] px-3 py-2 text-[11px] leading-5 text-[#636366]">引用 · {quote.label || message.page_title}</div>}
          {message.attachment_ids.length > 0 && <AttachmentGrid attachmentIds={message.attachment_ids} tenantId={tenantId} userId={userId} />}
          <div className="mt-3 flex items-end justify-between gap-2">
            <div className="text-[10px] leading-4 text-[#8a8a8e]">
              <div>{message.author_name}</div>
              <div>{formatDate(message.created_at)}</div>
            </div>
            {message.status !== "completed" && <button type="button" onClick={onEdit} className="rounded-lg border border-[#e5e5ea] px-2.5 py-1.5 text-[10px] text-[#636366] hover:bg-[#f7f8fa]">继续编辑</button>}
          </div>
        </div>
      )}
    </article>
  );
}

function StatusBadge({ status }: { status: MessageBoardEntry["status"] }) {
  const label = status === "adopted" ? "已采纳" : status === "completed" ? "已完成" : "新增加";
  return <span className={`rounded px-1.5 py-0.5 text-[9px] ${status === "adopted" ? "bg-[#e8f3ff] text-[#1677ff]" : status === "completed" ? "bg-[#eef6ee] text-[#2f7d32]" : "bg-[#f2f3f5] text-[#646a73]"}`}>{label}</span>;
}

function AttachmentGrid({ attachmentIds, tenantId, userId }: { attachmentIds: string[]; tenantId: string; userId: string }) {
  const [urls, setUrls] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    const loaded: string[] = [];
    Promise.all(attachmentIds.map((id) => fetchMessageBoardAttachment(id, { tenantId, userId })))
      .then((next) => { loaded.push(...next); if (!cancelled) setUrls(next); })
      .catch(() => undefined);
    return () => { cancelled = true; loaded.forEach(URL.revokeObjectURL); };
  }, [attachmentIds, tenantId, userId]);
  return <div className="mt-2 grid grid-cols-3 gap-2">{urls.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer" className="aspect-square overflow-hidden rounded-lg border border-[#ececf0]"><img src={url} alt={`留言截图 ${index + 1}`} className="h-full w-full object-cover" /></a>)}</div>;
}

function useMessageBoardVoice({ tenantId, userId, pageTitle, content, setContent, textareaRef }: { tenantId: string; userId: string; pageTitle: string; content: string; setContent: (value: string) => void; textareaRef: React.RefObject<HTMLTextAreaElement | null> }) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");
  const activeRef = useRef(false);
  const socketRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const baseRef = useRef("");
  const finalRef = useRef("");
  const draftRef = useRef("");

  const cleanup = () => {
    try { processorRef.current?.disconnect(); } catch { /* disconnected */ }
    try { sourceRef.current?.disconnect(); } catch { /* disconnected */ }
    processorRef.current = null;
    sourceRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioRef.current?.close().catch(() => undefined);
    audioRef.current = null;
  };

  const stop = () => {
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
    try {
      const runtime = await fetchAnalysisRuntimeConfig({ tenantId, userId, speechApplicationModule: "realtime_voice_input" });
      if (!runtime.speechIntegration) throw new Error("当前机构没有已启用的阿里云 Fun-ASR 实时语音配置。请先在模型接入管理中完成配置。");
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("当前浏览器不支持实时麦克风采集。");
      const AudioContextConstructor = getAudioContextConstructor();
      if (!AudioContextConstructor) throw new Error("当前浏览器不支持实时音频采集。");
      activeRef.current = true;
      setListening(true);
      baseRef.current = content;
      finalRef.current = "";
      draftRef.current = "";
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!activeRef.current) { stream.getTracks().forEach((track) => track.stop()); return; }
      streamRef.current = stream;
      const socket = new WebSocket(buildFunAsrRealtimeUrl(tenantId, userId, "realtime_voice_input"));
      socketRef.current = socket;
      socket.onopen = () => socket.send(JSON.stringify({ type: "start", provider: "aliyun_fun_asr", speechIntegrationId: runtime.speechIntegration!.id, applicationModule: "realtime_voice_input", sampleRate: funAsrSampleRate, context: [{ role: "user", content: [{ type: "input_text", text: `${pageTitle}产品留言录入` }] }] }));
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
          if (payload.final) { finalRef.current = normalizeVoiceSegment(`${finalRef.current} ${text}`); draftRef.current = ""; } else draftRef.current = text;
          setContent(appendRealtimeVoiceText(baseRef.current, normalizeVoiceSegment(`${finalRef.current} ${draftRef.current}`)));
          textareaRef.current?.focus();
        } else if (payload.type === "error") {
          setError(funAsrErrorMessage(payload.message || ""));
          stop();
        }
      };
      socket.onerror = () => { setError("实时语音连接中断，可继续文字输入后重试。"); stop(); };
      socket.onclose = () => { if (activeRef.current) { cleanup(); activeRef.current = false; setListening(false); } };
    } catch (caught) {
      stop();
      setError(funAsrErrorMessage(caught instanceof Error ? caught.message : "实时语音未启动"));
    }
  };
  return { listening, error, start, stop };
}

function quoteForTarget(target?: CommentTarget | null): MessageBoardQuote | Record<string, never> {
  const selectedText = target?.selectedText?.trim();
  if (!target || !selectedText) return {};
  return { target_id: target.id, target_type: target.type, label: target.label, selected_text: selectedText.slice(0, 1000) };
}

function newMessageId() { return `mb_${createClientUuid().replaceAll("-", "")}`; }
function formatDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date); }
