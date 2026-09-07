import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent } from "react";
import { AudioLines, Check, LoaderCircle, MessageSquarePlus, Send, X } from "lucide-react";
import { useLocation } from "react-router";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import { createMessageBoardEntry, uploadMessageBoardImage } from "../../services/messageBoardApi";
import { createClientUuid } from "../../utils/clientUuid";
import { useMessageBoardVoice } from "./MessageBoardPanel";
import {
  clearMessageBoardDraft,
  loadMessageBoardDraft,
  messageBoardDraftKey,
  saveMessageBoardDraft,
} from "./messageBoardDraftStore";

type DraftImage = { file: File; previewUrl: string };
type DraftStatus = "loading" | "saving" | "saved" | "";

const pageTitles: Record<string, string> = {
  "/dashboard": "多机构分析",
  "/funnel": "业务漏斗",
  "/sandbox": "经营沙盘",
  "/supervision": "机构督导",
  "/customer-segment-analysis": "分客群分析",
  "/weekly-report": "经营周报",
  "/email-daily": "邮件日报",
  "/customers": "客群分析",
  "/competition": "竞品分析",
  "/self-analysis/visual-reports": "可视化报表",
  "/self-analysis/query": "智能分析",
  "/self-analysis/reports": "我的报表",
  "/self-analysis/config": "分析配置",
  "/agent/todos": "待办任务",
  "/agent/tasks": "自动化任务",
  "/agent/message-board": "留言板管理",
  "/agent/interaction-analytics": "埋点分析",
  "/agent/skills": "skill/插件",
  "/data-assets/metrics": "指标字典",
  "/data-assets/knowledge": "知识记忆",
  "/data-assets/rules": "规则管理",
  "/data-assets/data-management": "站内数据",
  "/data-assets/quality": "质量监控",
  "/data-assets/tools": "工具调用",
  "/notifications/alerts": "预警规则",
  "/notifications/subscriptions": "订阅管理",
  "/notifications/history": "推送记录",
  "/settings/users": "用户管理",
  "/settings/roles": "角色权限",
  "/settings/audit": "审计日志",
  "/settings/config": "系统配置",
  "/settings/skin": "皮肤管理",
  "/bridge-authorize": "Bridge 授权",
};

export const globalMessageBoardSubmittedEvent = "smart-data-agent:message-board-submitted";

export function GlobalMessageBoardShortcut() {
  const location = useLocation();
  const { tenantId, userId } = usePlatformContext();
  const [open, setOpen] = useState(false);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [fallbackRight, setFallbackRight] = useState("0.4cm");
  const [submitted, setSubmitted] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const pageTitle = pageTitles[location.pathname] || routeTitle(location.pathname);
  const pageKey = routePageKey(location.pathname);

  useLayoutEffect(() => {
    const main = document.querySelector<HTMLElement>('main[data-agent-main-shell="true"]');
    if (!main) return;
    let frame = 0;
    const syncHost = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const next = findPageHeaderHost(main) || main;
        setHost((current) => current === next ? current : next);
        const rightGap = Math.max(0, window.innerWidth - main.getBoundingClientRect().right);
        setFallbackRight(rightGap > 2 ? `${Math.round(rightGap + 15)}px` : "var(--sda-shell-edge-gap)");
      });
    };
    syncHost();
    const observer = new MutationObserver(syncHost);
    observer.observe(main, { childList: true, subtree: true });
    window.addEventListener("resize", syncHost);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncHost);
      window.cancelAnimationFrame(frame);
    };
  }, [location.pathname]);

  useEffect(() => {
    setOpen(false);
    setSubmitted(false);
  }, [location.pathname, tenantId, userId]);

  useLayoutEffect(() => {
    const wrapper = wrapperRef.current;
    if (!host || !wrapper || host.matches('main[data-agent-main-shell="true"]')) return;
    const keepRightmost = () => {
      if (host.lastElementChild !== wrapper) host.append(wrapper);
    };
    keepRightmost();
    const observer = new MutationObserver(keepRightmost);
    observer.observe(host, { childList: true });
    return () => observer.disconnect();
  }, [host, location.pathname]);

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !wrapperRef.current?.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", dismiss, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!host) return null;
  const fallback = host.matches('main[data-agent-main-shell="true"]');
  const inActionRow = host.matches('[data-page-header-actions="true"], [data-standard-analysis-page-actions="true"]');
  return createPortal(
    <div
      ref={wrapperRef}
      className={fallback ? "fixed z-[85]" : `relative box-border h-9 shrink-0 ${inActionRow ? "" : "ml-auto self-center"}`}
      style={fallback ? { right: fallbackRight, top: "var(--sda-shell-edge-gap)" } : undefined}
      data-global-message-board-host={fallback ? "fallback" : "page-header"}
    >
      <button
        type="button"
        onClick={() => { setOpen((current) => !current); setSubmitted(false); }}
        className={`flex h-9 items-center gap-1.5 rounded-lg border px-3 text-[12px] transition-colors ${open ? "border-[#1d1d1f] bg-[#1d1d1f] text-white" : "border-[#e5e5ea] bg-white text-[#3a3a3c] hover:bg-[#f2f2f7]"}`}
        aria-label={`在${pageTitle}新增留言`}
        aria-expanded={open}
        data-global-message-board-trigger="true"
      >
        {submitted ? <Check className="h-3.5 w-3.5" /> : <MessageSquarePlus className="h-3.5 w-3.5" />}
        {submitted ? "已提交" : "留言板"}
      </button>
      <QuickMessageBoardComposer
        open={open}
        tenantId={tenantId}
        userId={userId}
        pageKey={pageKey}
        pageTitle={pageTitle}
        pageUrl={`${location.pathname}${location.search}${location.hash}`}
        onCancel={() => setOpen(false)}
        onSubmitted={() => {
          setOpen(false);
          setSubmitted(true);
          window.setTimeout(() => setSubmitted(false), 2_000);
          window.dispatchEvent(new CustomEvent(globalMessageBoardSubmittedEvent));
        }}
      />
    </div>,
    host,
  );
}

function QuickMessageBoardComposer({ open, tenantId, userId, pageKey, pageTitle, pageUrl, onCancel, onSubmitted }: { open: boolean; tenantId: string; userId: string; pageKey: string; pageTitle: string; pageUrl: string; onCancel: () => void; onSubmitted: () => void }) {
  const [content, setContent] = useState("");
  const [images, setImages] = useState<DraftImage[]>([]);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [draftStatus, setDraftStatus] = useState<DraftStatus>("loading");
  const [draftLoaded, setDraftLoaded] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const imageUrlsRef = useRef(new Set<string>());
  const messageIdRef = useRef(newMessageId());
  const draftKey = messageBoardDraftKey(tenantId, userId, pageKey);
  const voice = useMessageBoardVoice({ tenantId, userId, pageTitle, content, setContent, textareaRef });

  useEffect(() => {
    let cancelled = false;
    imageUrlsRef.current.forEach(URL.revokeObjectURL);
    imageUrlsRef.current.clear();
    setImages([]);
    setContent("");
    setNotice("");
    setDraftLoaded(false);
    setDraftStatus("loading");
    messageIdRef.current = newMessageId();
    void loadMessageBoardDraft(draftKey).then((draft) => {
      if (cancelled) return;
      const restored = (draft?.images || []).map((image) => {
        const file = new File([image.blob], image.name, { type: image.type, lastModified: image.lastModified });
        const previewUrl = URL.createObjectURL(file);
        imageUrlsRef.current.add(previewUrl);
        return { file, previewUrl };
      });
      setContent(draft?.content || "");
      setImages(restored);
      setDraftLoaded(true);
      setDraftStatus(draft ? "saved" : "");
    });
    return () => { cancelled = true; };
  }, [draftKey]);

  useEffect(() => () => {
    imageUrlsRef.current.forEach(URL.revokeObjectURL);
    imageUrlsRef.current.clear();
  }, []);

  useEffect(() => {
    if (!draftLoaded) return;
    setDraftStatus("saving");
    const timer = window.setTimeout(() => {
      const empty = !content.trim() && !images.length;
      const operation = empty
        ? clearMessageBoardDraft(draftKey)
        : saveMessageBoardDraft(draftKey, {
            content,
            images: images.map((image) => ({ name: image.file.name, type: image.file.type, lastModified: image.file.lastModified, blob: image.file })),
            updatedAt: new Date().toISOString(),
          });
      void operation.then(() => setDraftStatus(empty ? "" : "saved")).catch(() => setDraftStatus(""));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [content, draftKey, draftLoaded, images]);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.max(160, textarea.scrollHeight)}px`;
  }, [content, images.length, open]);

  useEffect(() => {
    if (open) window.setTimeout(() => textareaRef.current?.focus(), 0);
    else voice.stop();
  }, [open]);

  const addImages = (files: File[]) => {
    const candidates = files.filter((file) => file.type.startsWith("image/"));
    if (!candidates.length) return;
    if (candidates.some((file) => file.size > 5 * 1024 * 1024)) {
      setNotice("单张截图不能超过 5MB");
      return;
    }
    const accepted = candidates.slice(0, Math.max(0, 5 - images.length));
    if (!accepted.length) {
      setNotice("每条留言最多保留 5 张截图");
      return;
    }
    const next = accepted.map((file) => {
      const previewUrl = URL.createObjectURL(file);
      imageUrlsRef.current.add(previewUrl);
      return { file, previewUrl };
    });
    setImages((current) => [...current, ...next]);
    setNotice(candidates.length > accepted.length ? "每条留言最多保留 5 张截图" : "");
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.files || []).filter((file) => file.type.startsWith("image/"));
    if (!files.length) return;
    event.preventDefault();
    addImages(files);
  };

  const submit = async () => {
    const text = content.trim();
    if (!text || saving) {
      if (!text) setNotice("请用一句话描述页面中遇到的问题");
      return;
    }
    setSaving(true);
    setNotice("");
    voice.stop();
    try {
      const uploaded = await Promise.all(images.map((image) => uploadMessageBoardImage(image.file, messageIdRef.current, { tenantId, userId })));
      await createMessageBoardEntry({
        message_id: messageIdRef.current,
        page_key: pageKey,
        page_title: pageTitle,
        page_url: pageUrl,
        content: text,
        quote_context: {},
        attachment_ids: uploaded.map((item) => item.attachment.attachment_id),
      }, { tenantId, userId });
      await clearMessageBoardDraft(draftKey);
      imageUrlsRef.current.forEach(URL.revokeObjectURL);
      imageUrlsRef.current.clear();
      setImages([]);
      setContent("");
      setDraftStatus("");
      messageIdRef.current = newMessageId();
      onSubmitted();
    } catch (error) {
      setNotice(apiErrorMessage(error, "留言提交失败，请稍后重试"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className={`${open ? "flex" : "hidden"} absolute right-0 top-[calc(100%+8px)] z-[120] w-[12cm] min-h-[10cm] max-h-[20cm] flex-col overflow-hidden rounded-2xl border border-[#dedfe3] bg-white shadow-[0_18px_48px_rgba(0,0,0,0.16)]`}
      role={open ? "dialog" : undefined}
      aria-hidden={open ? undefined : true}
      aria-label={`${pageTitle}新增留言`}
      data-global-message-board-popover="true"
      data-message-board-draft-key={draftKey}
      data-message-board-draft-status={draftStatus}
    >
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-[#f0f0f2] px-3">
        <div className="truncate text-[12px] font-medium text-[#1d1d1f]">新增留言</div>
        <button type="button" onClick={onCancel} className="flex h-7 w-7 items-center justify-center rounded-md text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" aria-label="关闭留言气泡"><X className="h-3.5 w-3.5" /></button>
      </header>
      <div className="flex min-h-[calc(10cm-40px)] max-h-[calc(20cm-40px)] flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-2 pt-2.5" data-global-message-board-scroll="true">
          <textarea
            ref={textareaRef}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            onPaste={onPaste}
            maxLength={5000}
            placeholder="描述这个页面上遇到的问题，可直接粘贴截图…"
            className="block min-h-[160px] w-full resize-none overflow-hidden bg-transparent text-[12px] leading-5 text-[#1d1d1f] outline-none placeholder:text-[#b4b5b9]"
            data-global-message-board-input="true"
          />
          {images.length > 0 && <div className="mt-2 grid grid-cols-2 gap-1.5" data-global-message-board-images="true">{images.map((image, index) => (
            <div key={`${image.file.name}-${index}`} className="group relative aspect-[4/3] overflow-hidden rounded-lg border border-[#ececf0] bg-[#f7f8fa]">
              <img src={image.previewUrl} alt={`待提交截图 ${index + 1}`} className="h-full w-full object-cover" />
              <button type="button" onClick={() => { URL.revokeObjectURL(image.previewUrl); imageUrlsRef.current.delete(image.previewUrl); setImages((current) => current.filter((_, itemIndex) => itemIndex !== index)); }} className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white opacity-0 transition-opacity group-hover:opacity-100" aria-label={`移除截图 ${index + 1}`}><X className="h-3 w-3" /></button>
            </div>
          ))}</div>}
          {notice && <div className="mt-2 rounded-lg bg-[#fff7ed] px-2.5 py-2 text-[10px] leading-4 text-[#9a5b13]" role="status">{notice}</div>}
          {voice.error && <div className="mt-2 rounded-lg bg-[#fff7ed] px-2.5 py-2 text-[10px] leading-4 text-[#9a5b13]">语音提示：{voice.error}</div>}
        </div>
        <footer className="flex shrink-0 items-center justify-between border-t border-[#f0f0f2] bg-white/95 px-3 py-2 backdrop-blur" data-global-message-board-toolbar="true">
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => voice.listening ? voice.stop() : void voice.start()} className={`relative flex h-8 w-8 items-center justify-center rounded-full ${voice.listening ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#777b80] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"}`} title={voice.listening ? "停止实时语音录入" : "实时语音录入"} aria-label={voice.listening ? "停止实时语音录入" : "实时语音录入"} data-global-message-board-voice="true">
              {voice.listening && <span className="absolute inset-0 animate-ping rounded-full bg-[#0a66c2]/15" />}
              <AudioLines className="relative h-4 w-4" />
            </button>
            <span className="text-[9px] tabular-nums text-[#a5a7ab]">{voice.listening ? "转写中" : `${content.length}/5000`}</span>
          </div>
          <div className="flex items-center gap-1">
            <button type="button" onClick={onCancel} disabled={saving} className="h-8 rounded-lg px-2 text-[10px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-40">取消</button>
            <button type="button" onClick={() => void submit()} disabled={saving || !content.trim()} className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#1d1d1f] px-2.5 text-[10px] font-medium text-white hover:bg-[#2c2c2e] disabled:cursor-not-allowed disabled:opacity-35">
              {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              提交
            </button>
          </div>
        </footer>
      </div>
    </section>
  );
}

function findPageHeaderHost(main: HTMLElement) {
  const explicit = main.querySelector<HTMLElement>('[data-page-header-actions="true"], [data-standard-analysis-page-actions="true"]');
  if (explicit && displayVisible(explicit)) return explicit;
  const mainRect = main.getBoundingClientRect();
  const heading = Array.from(main.querySelectorAll<HTMLElement>("h1, h2")).find((candidate) => {
    const rect = candidate.getBoundingClientRect();
    return painted(candidate) && rect.top >= mainRect.top && rect.top < mainRect.top + 190;
  });
  let current = heading?.parentElement || null;
  for (let depth = 0; current && current !== main && depth < 6; depth += 1, current = current.parentElement) {
    const nested = current.querySelector<HTMLElement>('[data-page-header-actions="true"], [data-standard-analysis-page-actions="true"]');
    if (nested && displayVisible(nested)) return nested;
    if (!isHeaderFlex(current, mainRect)) continue;
    return pickActionRow(current, heading) || current;
  }
  return null;
}

function pickActionRow(header: HTMLElement, heading: HTMLElement | undefined) {
  const children = Array.from(header.children).filter((child): child is HTMLElement => child instanceof HTMLElement && displayVisible(child));
  const actionRows = children.filter((child) => {
    if (heading && child.contains(heading)) return false;
    if (child.matches("button, a, input, select, textarea, label")) return false;
    return isFlexLike(child);
  });
  return actionRows.at(-1) || null;
}

function isHeaderFlex(element: HTMLElement, mainRect: DOMRect) {
  const rect = element.getBoundingClientRect();
  return isFlexLike(element) && rect.width >= Math.min(420, mainRect.width * 0.62) && rect.top < mainRect.top + 170;
}

function isFlexLike(element: HTMLElement) {
  const display = window.getComputedStyle(element).display;
  return display === "flex" || display === "inline-flex" || display === "grid";
}

function displayVisible(element: HTMLElement) {
  const style = window.getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden";
}

function painted(element: HTMLElement) {
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 && displayVisible(element);
}

function routePageKey(pathname: string) {
  return pathname.replace(/^\/+/, "").replaceAll("/", "-") || "home";
}

function routeTitle(pathname: string) {
  const segment = pathname.split("/").filter(Boolean).at(-1) || "当前页面";
  return decodeURIComponent(segment).replaceAll("-", " ");
}

function newMessageId() {
  return `mb_${createClientUuid().replaceAll("-", "")}`;
}
