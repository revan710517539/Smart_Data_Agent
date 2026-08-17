import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Image as ImageIcon, LoaderCircle, MessageSquarePlus, Quote, RefreshCw, Search } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { fetchMessageBoardAdmin, updateMessageBoardStatus, type MessageBoardEntry, type MessageBoardQuote } from "../services/messageBoardApi";
import { DataPageSelector } from "./ui/DataPageSelector";

const messagePageSize = 20;

export function MessageBoardManagement() {
  const { isSuperAdmin, tenantId, userId } = usePlatformContext();
  const [messages, setMessages] = useState<MessageBoardEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [updatingId, setUpdatingId] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!isSuperAdmin) return;
    let cancelled = false;
    setLoading(true);
    setNotice("");
    fetchMessageBoardAdmin({ query: appliedQuery, page, pageSize: messagePageSize }, { tenantId, userId })
      .then((response) => {
        if (cancelled) return;
        setMessages(response.messages);
        setTotal(response.total);
      })
      .catch((error) => { if (!cancelled) setNotice(error instanceof Error ? error.message : "留言加载失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [appliedQuery, isSuperAdmin, page, refreshKey, tenantId, userId]);

  const summary = useMemo(() => ({
    users: new Set(messages.map((item) => item.author_user_id)).size,
    pages: new Set(messages.map((item) => item.page_key)).size,
    quoted: messages.filter((item) => Boolean((item.quote_context as MessageBoardQuote)?.selected_text)).length,
  }), [messages]);

  const changeStatus = async (message: MessageBoardEntry, status: MessageBoardEntry["status"]) => {
    if (updatingId || status === message.status) return;
    setUpdatingId(message.message_id);
    setNotice("");
    try {
      const response = await updateMessageBoardStatus(message.message_id, status, message.lock_version, { tenantId, userId });
      setMessages((current) => current.map((item) => item.message_id === response.message.message_id ? response.message : item));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "状态更新失败，请刷新后重试");
    } finally {
      setUpdatingId("");
    }
  };

  if (!isSuperAdmin) {
    return <div className="m-7 rounded-xl border border-[#ffd7d7] bg-[#fff5f5] px-4 py-3 text-[13px] text-[#b42318]">仅超级管理员可访问留言板管理。</div>;
  }

  return (
    <div className="p-7" data-message-board-management="true">
      <div className="mb-7 flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#f2f2f7]">
            <MessageSquarePlus className="h-[18px] w-[18px] text-[#636366]" />
          </div>
          <div className="min-w-0">
            <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">留言板管理</h2>
            <p className="mt-0.5 text-[13px] text-[#aeaeb2]">统一查看各机构、各账号从业务页面提交的产品意见和需求</p>
            {notice && <p className="mt-1 text-[11px] text-[#b42318]">{notice}</p>}
          </div>
        </div>
        <button type="button" onClick={() => setRefreshKey((value) => value + 1)} className="flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#636366] hover:bg-[#f7f8fa]">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      <section className="overflow-hidden rounded-xl border border-[#f0f0f2] bg-white">
        <div className="flex items-center justify-between gap-4 border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">全部留言</h3>
            <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[#8a8a8e]" data-message-board-inline-summary="true">
              <span>留言总数 {total}</span><span>留言账号 {summary.users}</span><span>来源页面 {summary.pages}</span><span>引用内容 {summary.quoted}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            {total > messagePageSize && <DataPageSelector page={page} totalPages={Math.ceil(total / messagePageSize)} shownCount={messages.length} totalCount={total} onChange={setPage} ariaLabel="留言分页" />}
            <form onSubmit={(event) => { event.preventDefault(); setPage(1); setAppliedQuery(query.trim()); }} className="relative w-[320px] max-w-full">
              <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#aeaeb2]" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索留言人、内容、页面或机构" className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-[#fafbfc] pl-9 pr-3 text-[12px] text-[#1d1d1f] outline-none focus:border-[#8bb7e6] focus:bg-white" />
            </form>
          </div>
        </div>

        <div className="grid grid-cols-[150px_150px_minmax(260px,1fr)_170px_84px_110px_40px] gap-3 border-b border-[#ececf0] bg-[#fafbfc] px-5 py-2.5 text-[11px] text-[#8a8a8e]" data-message-board-table-header="true">
          <div>留言时间</div><div>留言人</div><div>留言内容</div><div>留言页面</div><div>引用内容</div><div>状态</div><div />
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
                  <div className="truncate text-[12px] text-[#3a3a3c]">{message.page_title}</div>
                  <div className="truncate text-[10px] text-[#aeaeb2]">{message.page_url || message.page_key}</div>
                </div>
                <div>{quote?.selected_text ? <span className="inline-flex items-center gap-1 rounded-full bg-[#f5f1fb] px-2 py-0.5 text-[10px] text-[#7654a8]"><Quote className="h-3 w-3" />是</span> : <span className="text-[11px] text-[#aeaeb2]">否</span>}</div>
                <select
                  value={message.status}
                  onChange={(event) => void changeStatus(message, event.target.value as MessageBoardEntry["status"])}
                  disabled={updatingId === message.message_id}
                  aria-label={`更新${message.author_name}留言状态`}
                  className="h-8 rounded-md border border-[#dcdfe4] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none disabled:opacity-50"
                >
                  <option value="new">新增加</option>
                  <option value="adopted">已采纳</option>
                  <option value="completed">已完成</option>
                </select>
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
                      <div className="flex gap-2"><dt className="w-16 shrink-0 text-[#aeaeb2]">附件</dt><dd className="text-[#3a3a3c]">{message.attachment_ids.length} 张截图</dd></div>
                      <div className="flex gap-2"><dt className="w-16 shrink-0 text-[#aeaeb2]">更新时间</dt><dd className="text-[#3a3a3c]">{formatDateTime(message.updated_at)}</dd></div>
                    </dl>
                  </div>
                  <div className="space-y-3">
                    <div className="rounded-lg border border-[#ececf0] bg-white p-3 text-[12px] leading-6 text-[#1d1d1f] whitespace-pre-wrap">{message.content}</div>
                    {quote?.selected_text && <div className="rounded-lg border-l-2 border-[#8bb7e6] bg-white px-3 py-2.5"><div className="text-[10px] text-[#8a8a8e]">引用 · {quote.label || "具体内容"}</div><div className="mt-1 text-[11px] leading-5 text-[#636366]">{quote.selected_text}</div></div>}
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
