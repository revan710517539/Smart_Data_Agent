import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, ClipboardList, Download, Image as ImageIcon, LoaderCircle, MessageSquarePlus, Quote, RefreshCw, Search } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { ApiRequestError } from "../services/apiClient";
import { trackInteraction } from "../services/interactionTelemetry";
import {
  downloadAdoptedMessageBoardExport,
  fetchMessageBoardAdmin,
  updateMessageBoardAppendContent,
  updateMessageBoardStatus,
  type MessageBoardEntry,
  type MessageBoardQuote,
} from "../services/messageBoardApi";
import { globalMessageBoardSubmittedEvent } from "./message-board/GlobalMessageBoardShortcut";
import { MessageBoardAttachmentGallery } from "./message-board/MessageBoardAttachmentGallery";
import { DataPageSelector } from "./ui/DataPageSelector";
import { AppSelect } from "./ui/AppSelect";

const messagePageSize = 20;
const messageStatusOptions: { value: MessageBoardEntry["status"] | ""; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "new", label: "新增加" },
  { value: "adopted", label: "已采纳" },
  { value: "completed", label: "已完成" },
];
type MessageTimeSort = "" | "asc" | "desc";

export function MessageBoardManagement() {
  const { isSuperAdmin, tenantId, userId } = usePlatformContext();
  const [messages, setMessages] = useState<MessageBoardEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<MessageBoardEntry["status"] | "">("");
  const [timeSort, setTimeSort] = useState<MessageTimeSort>("");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"error" | "info">("error");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [updatingId, setUpdatingId] = useState("");
  const [appendDrafts, setAppendDrafts] = useState<Record<string, string>>({});
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [page, setPage] = useState(1);
  const exportMenuRef = useRef<HTMLDivElement | null>(null);
  const appendDraftsRef = useRef(appendDrafts);
  const messagesRef = useRef(messages);
  const appendTimersRef = useRef<Record<string, number>>({});
  const contextRef = useRef({ tenantId, userId });
  appendDraftsRef.current = appendDrafts;
  messagesRef.current = messages;
  contextRef.current = { tenantId, userId };

  useEffect(() => {
    const refresh = () => {
      setPage(1);
      setRefreshKey((value) => value + 1);
    };
    window.addEventListener(globalMessageBoardSubmittedEvent, refresh);
    return () => window.removeEventListener(globalMessageBoardSubmittedEvent, refresh);
  }, []);

  useEffect(() => {
    if (!isSuperAdmin) return;
    let cancelled = false;
    setLoading(true);
    setNotice("");
    setNoticeTone("error");
    fetchMessageBoardAdmin({ query: appliedQuery, page, pageSize: messagePageSize, status: statusFilter, sort: timeSort }, { tenantId, userId })
      .then((response) => {
        if (cancelled) return;
        setMessages(response.messages);
        setTotal(response.total);
      })
      .catch((error) => { if (!cancelled) setNotice(error instanceof Error ? error.message : "留言加载失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [appliedQuery, isSuperAdmin, page, refreshKey, statusFilter, tenantId, timeSort, userId]);

  useEffect(() => {
    if (!exportOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!exportMenuRef.current?.contains(event.target as Node)) setExportOpen(false);
    };
    window.addEventListener("mousedown", onPointerDown);
    return () => window.removeEventListener("mousedown", onPointerDown);
  }, [exportOpen]);

  const summary = useMemo(() => ({
    users: new Set(messages.map((item) => item.author_user_id)).size,
    pages: new Set(messages.map((item) => item.page_key)).size,
    quoted: messages.filter((item) => Boolean((item.quote_context as MessageBoardQuote)?.selected_text)).length,
    surveys: messages.filter((item) => item.page_key === "login-survey").length,
  }), [messages]);

  const changeStatus = async (message: MessageBoardEntry, status: MessageBoardEntry["status"]) => {
    if (updatingId || status === message.status) return;
    setUpdatingId(message.message_id);
    setNotice("");
    setNoticeTone("error");
    try {
      const response = await updateMessageBoardStatus(message.message_id, status, message.lock_version, { tenantId, userId });
      setMessages((current) => current.map((item) => item.message_id === response.message.message_id ? response.message : item));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "状态更新失败，请刷新后重试");
    } finally {
      setUpdatingId("");
    }
  };

  const persistAppendContent = async (messageId: string) => {
    const current = messagesRef.current.find((item) => item.message_id === messageId);
    const next = (appendDraftsRef.current[messageId] ?? current?.append_content ?? "").trim();
    if (!current || next === (current.append_content || "").trim()) return;
    const { tenantId: nextTenantId, userId: nextUserId } = contextRef.current;
    const send = (lockVersion: number, keepalive = false) => updateMessageBoardAppendContent(messageId, next, lockVersion, { tenantId: nextTenantId, userId: nextUserId }, { keepalive });
    try {
      let response;
      try {
        response = await send(current.lock_version);
      } catch (error) {
        if (!(error instanceof ApiRequestError) || error.code !== "message_board_revision_conflict") throw error;
        const latest = messagesRef.current.find((item) => item.message_id === messageId);
        if (!latest) throw error;
        response = await send(latest.lock_version);
      }
      setMessages((items) => items.map((item) => item.message_id === response.message.message_id ? response.message : item));
      setAppendDrafts((drafts) => {
        if ((drafts[messageId] ?? "").trim() !== next) return drafts;
        const copy = { ...drafts };
        delete copy[messageId];
        return copy;
      });
    } catch (error) {
      setNoticeTone("error");
      setNotice(error instanceof Error ? error.message : "追加内容保存失败，请刷新后重试");
    }
  };

  const scheduleAppendSave = (messageId: string) => {
    window.clearTimeout(appendTimersRef.current[messageId]);
    appendTimersRef.current[messageId] = window.setTimeout(() => {
      void persistAppendContent(messageId);
    }, 500);
  };

  useEffect(() => {
    const flush = (keepalive = false) => {
      Object.values(appendTimersRef.current).forEach((timer) => window.clearTimeout(timer));
      Object.keys(appendDraftsRef.current).forEach((messageId) => {
        const current = messagesRef.current.find((item) => item.message_id === messageId);
        const next = (appendDraftsRef.current[messageId] ?? current?.append_content ?? "").trim();
        if (!current || next === (current.append_content || "").trim()) return;
        const { tenantId: nextTenantId, userId: nextUserId } = contextRef.current;
        void updateMessageBoardAppendContent(messageId, next, current.lock_version, { tenantId: nextTenantId, userId: nextUserId }, { keepalive });
      });
    };
    const onHide = () => flush(true);
    window.addEventListener("pagehide", onHide);
    window.addEventListener("beforeunload", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      window.removeEventListener("beforeunload", onHide);
      flush(true);
    };
  }, []);

  const exportAdopted = async (format: "excel" | "feishu") => {
    if (exporting) return;
    setExporting(true);
    setExportOpen(false);
    setNotice("");
    try {
      const count = await downloadAdoptedMessageBoardExport(format, { tenantId, userId });
      trackInteraction({ eventName: "export_result", resourceType: "message_board", extension: { outcome: "success", format, exported_count: count } });
      setNoticeTone("info");
      setNotice(count ? `已导出 ${count} 条已采纳留言` : "当前没有已采纳的留言");
    } catch (error) {
      setNoticeTone("error");
      setNotice(error instanceof Error ? error.message : "已采纳留言导出失败");
    } finally {
      setExporting(false);
    }
  };

  if (!isSuperAdmin) {
    return <div className="m-7 rounded-xl border border-[#ffd7d7] bg-[#fff5f5] px-4 py-3 text-[13px] text-[#b42318]">仅超级管理员可访问留言板管理。</div>;
  }

  return (
    <div className="p-7" data-message-board-management="true">
      <div className="mb-7 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">留言板管理</h2>
          <p className="mt-1 text-[13px] text-[#aeaeb2]">查看当前机构各账号提交的登录调查、产品意见和需求</p>
          {notice && <p className={`mt-1 text-[11px] ${noticeTone === "error" ? "text-[#b42318]" : "text-[#8a8a8e]"}`}>{notice}</p>}
        </div>
        <div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true">
          <button type="button" onClick={() => setRefreshKey((value) => value + 1)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7]">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
          <div ref={exportMenuRef} className="relative">
            <button
              type="button"
              data-message-board-export="true"
              disabled={exporting}
              onClick={() => setExportOpen((value) => !value)}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7] disabled:opacity-50"
            >
              {exporting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              下载
            </button>
            {exportOpen && (
              <div className="absolute right-0 top-full z-20 mt-1 min-w-[148px] overflow-hidden rounded-lg border border-[#ececf0] bg-white py-1 shadow-lg shadow-black/5">
                <button type="button" onClick={() => void exportAdopted("excel")} className="flex h-8 w-full items-center px-3 text-left text-[12px] text-[#3a3a3c] hover:bg-[#f7f8fa]">Excel 文档</button>
                <button type="button" onClick={() => void exportAdopted("feishu")} className="flex h-8 w-full items-center px-3 text-left text-[12px] text-[#3a3a3c] hover:bg-[#f7f8fa]">飞书表格</button>
              </div>
            )}
          </div>
        </div>
      </div>

      <section className="overflow-hidden rounded-xl border border-[#f0f0f2] bg-white">
        <div className="flex items-center justify-between gap-4 border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">全部留言</h3>
            <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[#8a8a8e]" data-message-board-inline-summary="true">
              <span>留言总数 {total}</span><span>登录调查 {summary.surveys}</span><span>留言账号 {summary.users}</span><span>来源页面 {summary.pages}</span><span>引用内容 {summary.quoted}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            {total > messagePageSize && <DataPageSelector page={page} totalPages={Math.ceil(total / messagePageSize)} shownCount={messages.length} totalCount={total} onChange={setPage} ariaLabel="留言分页" />}
            <AppSelect
              value={statusFilter}
              onChange={(event) => {
                setPage(1);
                setStatusFilter(event.target.value as MessageBoardEntry["status"] | "");
              }}
              aria-label="按状态筛选留言"
              data-message-board-status-filter="true"
              className="h-9 min-w-[128px] rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-2 text-[12px] text-[#1d1d1f] outline-none focus:border-[#8bb7e6] focus:bg-white"
            >
              {messageStatusOptions.map((option) => (
                <option key={option.value || "all"} value={option.value}>{option.label}</option>
              ))}
            </AppSelect>
            <form onSubmit={(event) => { event.preventDefault(); setPage(1); setAppliedQuery(query.trim()); }} className="relative w-[320px] max-w-full">
              <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#aeaeb2]" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索留言人、内容、页面或机构" className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-[#fafbfc] pl-9 pr-3 text-[12px] text-[#1d1d1f] outline-none focus:border-[#8bb7e6] focus:bg-white" />
            </form>
          </div>
        </div>

        <div className="grid grid-cols-[150px_150px_minmax(260px,1fr)_170px_84px_110px_40px] gap-3 border-b border-[#ececf0] bg-[#fafbfc] px-5 py-2.5 text-[11px] text-[#8a8a8e]" data-message-board-table-header="true">
          <div
            role="columnheader"
            tabIndex={0}
            onClick={() => {
              setPage(1);
              setTimeSort((current) => current === "" ? "asc" : current === "asc" ? "desc" : "");
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              setPage(1);
              setTimeSort((current) => current === "" ? "asc" : current === "asc" ? "desc" : "");
            }}
            aria-label={timeSort === "asc" ? "留言时间正排，点击改为倒排" : timeSort === "desc" ? "留言时间倒排，点击恢复默认顺序" : "按留言时间排序"}
            title="点击按时间正排、倒排或恢复默认顺序"
            data-message-board-time-sort="true"
            data-sort={timeSort || "default"}
            className="inline-flex cursor-pointer items-center gap-1 outline-none"
          >
            留言时间
            {timeSort === "asc" ? <ArrowUp className="h-3 w-3" /> : timeSort === "desc" ? <ArrowDown className="h-3 w-3" /> : null}
          </div>
          <div>留言人</div><div>留言内容</div><div>留言页面</div><div>引用内容</div><div>状态</div><div />
        </div>
        {loading ? (
          <div className="flex h-52 items-center justify-center text-[#8a8a8e]"><LoaderCircle className="h-5 w-5 animate-spin" /></div>
        ) : messages.length === 0 ? (
          <div className="flex h-52 flex-col items-center justify-center text-[#aeaeb2]"><MessageSquarePlus className="mb-2 h-6 w-6" /><span className="text-[12px]">没有符合条件的留言</span></div>
        ) : messages.map((message) => {
          const expanded = expandedId === message.message_id;
          const quote = message.quote_context as MessageBoardQuote;
          return (
            <article key={message.message_id} className="border-b border-[#f0f0f2] last:border-b-0" data-message-board-admin-row={message.message_id}>
              <div className="grid w-full grid-cols-[150px_150px_minmax(260px,1fr)_170px_84px_110px_40px] items-center gap-3 px-5 py-3 text-left hover:bg-[#fafbfc]">
                <div className="text-[11px] text-[#636366]">{formatDateTime(message.created_at)}</div>
                <div className="min-w-0">
                  <div className="truncate text-[12px] text-[#1d1d1f]">{message.author_name}</div>
                  <div className="truncate text-[10px] text-[#aeaeb2]">{message.tenant_id.replace(/^tenant:/, "")}</div>
                </div>
                <div className="line-clamp-2 text-[12px] leading-5 text-[#3a3a3c]">{message.content}</div>
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <div className="truncate text-[12px] text-[#3a3a3c]">{message.page_title}</div>
                    {message.page_key === "login-survey" && <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#eef8f2] px-1.5 py-0.5 text-[9px] text-[#0f8554]"><ClipboardList className="h-2.5 w-2.5" />登录调查</span>}
                  </div>
                  <div className="truncate text-[10px] text-[#aeaeb2]">{message.page_url || message.page_key}</div>
                </div>
                <div>{quote?.selected_text ? <span className="inline-flex items-center gap-1 rounded-full bg-[#f5f1fb] px-2 py-0.5 text-[10px] text-[#7654a8]"><Quote className="h-3 w-3" />是</span> : <span className="text-[11px] text-[#aeaeb2]">否</span>}</div>
                <AppSelect
                  value={message.status}
                  onChange={(event) => void changeStatus(message, event.target.value as MessageBoardEntry["status"])}
                  disabled={updatingId === message.message_id}
                  aria-label={`更新${message.author_name}留言状态`}
                  className="h-8 rounded-md border border-[#dcdfe4] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none disabled:opacity-50"
                >
                  <option value="new">新增加</option>
                  <option value="adopted">已采纳</option>
                  <option value="completed">已完成</option>
                </AppSelect>
                <div className="flex items-center justify-end gap-1.5 text-[#8a8a8e]">
                  {message.attachment_ids.length > 0 && <span className="flex items-center gap-0.5 text-[10px]"><ImageIcon className="h-3.5 w-3.5" />{message.attachment_ids.length}</span>}
                  <button type="button" onClick={() => setExpandedId((current) => current === message.message_id ? null : message.message_id)} aria-label={expanded ? "折叠留言详情" : "展开留言详情"} className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-[#f2f3f5]">{expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button>
                </div>
              </div>
              {expanded && (
                <div className="grid grid-cols-[300px_minmax(0,1fr)] gap-4 bg-[#fafbfc] px-5 py-4">
                  <div className="rounded-lg border border-[#ececf0] bg-white p-3">
                    <div className="text-[10px] text-[#8a8a8e]">来源信息</div>
                    <dl className="mt-2 space-y-1.5 text-[11px] leading-5">
                      <div className="flex gap-2"><dt className="w-16 shrink-0 text-[#aeaeb2]">机构</dt><dd className="text-[#3a3a3c]">{message.tenant_id.replace(/^tenant:/, "")}</dd></div>
                      <div className="flex gap-2"><dt className="w-16 shrink-0 text-[#aeaeb2]">留言人</dt><dd className="break-all text-[#3a3a3c]">{message.author_name}</dd></div>
                      <div className="flex gap-2"><dt className="w-16 shrink-0 text-[#aeaeb2]">来源</dt><dd className="text-[#3a3a3c]">{message.page_key === "login-survey" ? "登录页数据使用调查" : message.page_title}</dd></div>
                      <div className="flex gap-2"><dt className="w-16 shrink-0 text-[#aeaeb2]">附件</dt><dd className="text-[#3a3a3c]">{message.attachment_ids.length} 张截图</dd></div>
                      <div className="flex gap-2"><dt className="w-16 shrink-0 text-[#aeaeb2]">更新时间</dt><dd className="text-[#3a3a3c]">{formatDateTime(message.updated_at)}</dd></div>
                    </dl>
                  </div>
                  <div className="space-y-3">
                    <div className="rounded-lg border border-[#ececf0] bg-white p-3 text-[12px] leading-6 text-[#1d1d1f] whitespace-pre-wrap">{message.content}</div>
                    {message.attachment_ids.length > 0 && <MessageBoardAttachmentGallery attachmentIds={message.attachment_ids} tenantId={tenantId} userId={userId} className="grid max-w-[720px] grid-cols-3 gap-2" />}
                    {quote?.selected_text && <div className="rounded-lg border-l-2 border-[#8bb7e6] bg-white px-3 py-2.5"><div className="text-[10px] text-[#8a8a8e]">引用 · {quote.label || "具体内容"}</div><div className="mt-1 text-[11px] leading-5 text-[#636366]">{quote.selected_text}</div></div>}
                    <textarea
                      aria-label="追加内容"
                      data-message-board-append-content="true"
                      value={appendDrafts[message.message_id] ?? message.append_content ?? ""}
                      onChange={(event) => {
                        const value = event.target.value;
                        setAppendDrafts((current) => ({ ...current, [message.message_id]: value }));
                        scheduleAppendSave(message.message_id);
                      }}
                      onBlur={() => {
                        window.clearTimeout(appendTimersRef.current[message.message_id]);
                        void persistAppendContent(message.message_id);
                      }}
                      className="min-h-[96px] w-full resize-y rounded-lg border border-[#ececf0] bg-white px-3 py-2.5 text-[12px] leading-6 text-[#1d1d1f] outline-none focus:border-[#8bb7e6]"
                    />
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}
