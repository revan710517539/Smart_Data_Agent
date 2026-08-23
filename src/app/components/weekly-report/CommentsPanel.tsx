import { useEffect, useRef, useState } from "react";
import { ChevronsDown, ChevronsUp, Image as ImageIcon, MessageSquarePlus, MessageSquareText, MoreHorizontal, Plus, Save, ThumbsUp, X } from "lucide-react";
import { readableContextText, type CommentItem, type CommentTarget } from "./domain";

export type CommentPanelEntry =
  | {
      kind: "draft";
      id: string;
      anchorTop: number;
      target: CommentTarget;
    }
  | {
      kind: "comment";
      id: string;
      anchorTop: number;
      comment: CommentItem;
    };

export function positionCommentEntries(
  entries: CommentPanelEntry[],
  expandedReplyInputs: Record<string, boolean>,
  expandedCommentReplies: Record<string, boolean>,
  startTop = 12,
) {
  let nextTop = startTop;
  return entries.map((entry) => {
    const displayTop = nextTop;
    nextTop = displayTop + estimateCommentEntryHeight(entry, expandedReplyInputs, expandedCommentReplies) + 14;
    return { ...entry, displayTop };
  });
}

export function estimateCommentEntryHeight(
  entry: CommentPanelEntry,
  expandedReplyInputs: Record<string, boolean>,
  expandedCommentReplies: Record<string, boolean>,
) {
  if (entry.kind === "draft") return 180 + estimateQuoteHeight(entry.target.selectedText);
  const comment = entry.comment;
  const repliesExpanded = Boolean(expandedCommentReplies[comment.id]);
  const replySpace = comment.replies.length
    ? repliesExpanded
      ? Math.min(3, comment.replies.length) * 58 + 18
      : 42
    : 0;
  const replyInputSpace = expandedReplyInputs[comment.id] ? 96 : 34;
  return 150 + estimateQuoteHeight(comment.selectedText || comment.targetLabel) + replySpace + replyInputSpace;
}

export function estimateQuoteHeight(text?: string) {
  const length = text?.trim().length ?? 0;
  if (!length) return 28;
  return Math.min(96, Math.max(32, Math.ceil(length / 17) * 18));
}

export function getCommentQuoteText(text?: string, fallback = "对选中区域添加评论") {
  return readableContextText(text, fallback);
}

export function formatCommentTimestamp(value?: string) {
  const normalized = value?.trim();
  if (!normalized) return "";
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    const match = normalized.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d{1,2})/);
    if (!match) return "";
    const [, year, month, day, hour, minute, second] = match;
    return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")} ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}:${second.padStart(2, "0")}`;
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

export function CommentsPanel({
  showHeader = true,
  stableFlow = true,
  selectedTarget,
  draftTargets,
  commentDrafts,
  onDraftChange,
  comments,
  replyDrafts,
  expandedReplyInputs,
  expandedCommentReplies,
  highlightedCommentId,
  activeCommentId,
  activeDraftId,
  railHeight,
  composerScopeKey,
  onCreateComment,
  onSave,
  onCommentActivate,
  onResolveComment,
  onReplyDraftChange,
  onReplyToggle,
  onReplySave,
  onCommentRepliesToggle,
}: {
  showHeader?: boolean;
  stableFlow?: boolean;
  selectedTarget: CommentTarget | null;
  draftTargets: CommentTarget[];
  commentDrafts: Record<string, string>;
  onDraftChange: (targetId: string, value: string) => void;
  comments: CommentItem[];
  replyDrafts: Record<string, string>;
  expandedReplyInputs: Record<string, boolean>;
  expandedCommentReplies: Record<string, boolean>;
  highlightedCommentId: string | null;
  activeCommentId: string | null;
  activeDraftId: string | null;
  railHeight: number;
  composerScopeKey: string;
  onCreateComment: (text: string) => void;
  onSave: (targetId: string) => void;
  onCommentActivate: (commentId: string) => void;
  onResolveComment: (commentId: string) => void;
  onReplyDraftChange: (commentId: string, value: string) => void;
  onReplyToggle: (commentId: string, expanded: boolean) => void;
  onReplySave: (commentId: string) => void;
  onCommentRepliesToggle: (commentId: string, expanded: boolean) => void;
}) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [newCommentOpen, setNewCommentOpen] = useState(false);
  const [newCommentText, setNewCommentText] = useState("");
  const newCommentInputRef = useRef<HTMLTextAreaElement>(null);

  const closeNewComment = () => {
    setNewCommentText("");
    setNewCommentOpen(false);
  };

  const openNewComment = () => {
    setNewCommentOpen(true);
    window.setTimeout(() => newCommentInputRef.current?.focus(), 0);
  };

  const saveNewComment = () => {
    const text = newCommentText.trim();
    if (!text) return;
    onCreateComment(text);
    closeNewComment();
  };

  useEffect(() => {
    setNewCommentText("");
    setNewCommentOpen(false);
  }, [composerScopeKey]);

  useEffect(() => {
    if (!openMenuId) return;

    const handleDocumentMouseDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest("[data-comment-menu-root]")) return;
      setOpenMenuId(null);
    };

    document.addEventListener("mousedown", handleDocumentMouseDown);
    return () => document.removeEventListener("mousedown", handleDocumentMouseDown);
  }, [openMenuId]);

  useEffect(() => {
    const entryId = activeDraftId || activeCommentId;
    if (!entryId) return;
    const timeoutId = window.setTimeout(() => {
      const selector = activeDraftId ? `[data-draft-id="${CSS.escape(entryId)}"]` : `[data-comment-id="${CSS.escape(entryId)}"]`;
      const entry = document.querySelector<HTMLElement>(selector);
      const scroller = entry?.closest<HTMLElement>("[data-context-rail-scroll]");
      if (!entry || !scroller) return;
      const entryRect = entry.getBoundingClientRect();
      const scrollerRect = scroller.getBoundingClientRect();
      const targetTop = scroller.scrollTop + entryRect.top - scrollerRect.top - 12;
      scroller.scrollTo({ top: Math.max(0, targetTop), behavior: "auto" });
    }, 80);
    return () => window.clearTimeout(timeoutId);
  }, [activeCommentId, activeDraftId]);

  const entries = [
    ...draftTargets.map((target) => ({
      kind: "draft" as const,
      id: target.id,
      anchorTop: target.anchorTop ?? 84,
      target,
    })),
    ...comments.map((comment) => ({
      kind: "comment" as const,
      id: comment.id,
      anchorTop: comment.anchorTop ?? 84,
      comment,
    })),
  ];
  const positionedEntries = positionCommentEntries(entries, expandedReplyInputs, expandedCommentReplies, showHeader ? 96 : 12);

  return (
    <div className="relative py-2" data-weekly-comments-panel="true" data-comment-layout={stableFlow ? "stable-flow" : "anchored"} style={{ minHeight: stableFlow ? undefined : railHeight }}>
      {showHeader && (
        <div className="sticky top-4 z-30 flex items-start gap-2 bg-white rounded-xl border border-[#f0f0f2] p-4 shadow-sm shadow-black/[0.03]">
          <MessageSquareText className="w-4 h-4 text-[#8a8a8e] mt-0.5" />
          <div>
            <h3 className="text-[13px] text-[#1d1d1f]">评论区</h3>
            <p className="text-[11px] text-[#aeaeb2] mt-0.5">
              {selectedTarget ? "点击黑色气泡可添加区域评论；选择正文可直接生成文本评论。" : "选择正文、表格或趋势图后添加评论。"}
            </p>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={openNewComment}
        className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[#b8cce2] bg-white px-3 py-3 text-[12px] text-[#0a66c2] transition-colors hover:border-[#0a66c2] hover:bg-[#f7fbff]"
        data-comments-new="true"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#edf4fb]"><Plus className="h-3.5 w-3.5" /></span>
        新增评论
      </button>

      {newCommentOpen && (
        <article className="mt-2.5 rounded-xl border border-[#e5e5ea] bg-white" data-comments-new-editor="true">
          <header className="flex items-center justify-between border-b border-[#f0f0f2] px-3 py-2.5">
            <div className="flex min-w-0 items-center gap-2 text-[12px] text-[#1d1d1f]">
              <MessageSquarePlus className="h-4 w-4 shrink-0 text-[#0a66c2]" />
              <span className="truncate">新增评论</span>
            </div>
            <button type="button" onClick={closeNewComment} className="rounded-md p-1 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label="关闭评论编辑">
              <X className="h-3.5 w-3.5" />
            </button>
          </header>
          <div className="p-3">
            <textarea
              ref={newCommentInputRef}
              value={newCommentText}
              onChange={(event) => setNewCommentText(event.target.value)}
              rows={4}
              maxLength={2000}
              placeholder="输入评论内容"
              className="w-full resize-none rounded-lg border border-[#e5e5ea] bg-transparent px-3 py-2 text-[13px] leading-5 text-[#1d1d1f] outline-none placeholder:text-[#b4b4b8] focus:border-[#8bb7e6]"
              data-comments-new-input="true"
            />
            <div className="mt-2 flex items-center justify-between border-t border-[#f0f0f2] pt-2">
              <span className="text-[10px] text-[#aeaeb2]">{newCommentText.length}/2000</span>
              <div className="flex items-center gap-2">
                <button type="button" onClick={closeNewComment} className="h-8 rounded-lg px-3 text-[11px] text-[#636366] hover:bg-[#f2f3f5]">取消</button>
                <button
                  type="button"
                  onClick={saveNewComment}
                  disabled={!newCommentText.trim()}
                  className="flex h-8 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[11px] text-white hover:bg-[#2c2c2e] disabled:cursor-not-allowed disabled:opacity-40"
                  data-comments-new-save="true"
                >
                  <Save className="h-3.5 w-3.5" />
                  保存
                </button>
              </div>
            </div>
          </div>
        </article>
      )}

      {entries.length === 0 && !newCommentOpen && (
        <div className="mt-3 rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4 text-[12px] leading-relaxed text-[#8a8a8e]" data-comments-empty-state="true">
          暂无评论。选中文本后会在同一水平位置生成评论输入框。
        </div>
      )}

      <div className={`mt-3 space-y-3 ${stableFlow ? "" : "xl:mt-0 xl:block"}`}>
        {positionedEntries.map((entry) => {
          const top = entry.displayTop;
          if (entry.kind === "draft") {
            const target = entry.target;
            const active = activeDraftId === target.id;
            const quoteText = getCommentQuoteText(target.selectedText);
            return (
              <div
                key={entry.id}
                data-draft-id={target.id}
                className={stableFlow ? "relative" : "xl:absolute xl:left-0 xl:right-0"}
                style={{ ...(stableFlow ? {} : { top }), zIndex: active ? 70 : 20 }}
              >
                <div className={`rounded-xl border bg-white p-3 transition-colors ${active ? "border-[#3370ff]" : "border-[#e5e5ea]"}`}>
                  <div className="flex items-start gap-3 mb-3">
                    <div className="w-8 h-8 rounded-full bg-[#34a853] text-white flex items-center justify-center text-[12px] shrink-0">
                      我
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <div className="text-[12px] text-[#1d1d1f] truncate">{target.label}</div>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#f2f2f7] text-[#8a8a8e] shrink-0">{target.type}</span>
                      </div>
                      <div
                        data-draft-quote="true"
                        title={quoteText}
                        className="max-h-24 overflow-y-auto whitespace-pre-wrap break-words pl-2 text-[11px] leading-relaxed text-[#8a8a8e] border-l-2 border-[#d1d1d6]"
                      >
                        {quoteText}
                      </div>
                    </div>
                  </div>
                  <div className="overflow-hidden rounded-lg border border-[#e5e5ea] bg-white">
                    <textarea
                      value={commentDrafts[target.id] ?? ""}
                      onChange={(event) => onDraftChange(target.id, event.target.value)}
                      placeholder="回复"
                      className="w-full min-h-[64px] px-3 py-2 text-[13px] text-[#3a3a3c] outline-none resize-none"
                    />
                    <div className="flex items-center justify-between px-2.5 py-2 border-t border-[#f0f0f2]">
                      <button className="text-[#636366] hover:text-[#1d1d1f]" aria-label="添加图片">
                        <ImageIcon className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => onSave(target.id)}
                        disabled={!commentDrafts[target.id]?.trim()}
                        className="px-3 py-1.5 rounded-md bg-[#1d1d1f] text-white text-[12px] disabled:opacity-40"
                      >
                        保存
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          }

          const comment = entry.comment;
          const quoteText = getCommentQuoteText(comment.selectedText, comment.targetLabel);
          const expanded = Boolean(expandedReplyInputs[comment.id]);
          const shouldFoldReplies = comment.replies.length > 0;
          const repliesExpanded = !shouldFoldReplies || Boolean(expandedCommentReplies[comment.id]);
          const visibleReplies = repliesExpanded ? comment.replies : [];
          const highlighted = highlightedCommentId === comment.id;
          const active = activeCommentId === comment.id;
          return (
            <div
              key={entry.id}
              className={stableFlow ? "relative" : "xl:absolute xl:left-0 xl:right-0"}
              style={{ ...(stableFlow ? {} : { top }), zIndex: active || highlighted ? 60 : 10 }}
            >
              <article
                data-comment-id={comment.id}
                onMouseDown={() => onCommentActivate(comment.id)}
                className={`relative rounded-xl border p-3 pb-9 pr-10 bg-white transition-colors ${
                  highlighted || active ? "border-[#3370ff]" : "border-[#e5e5ea]"
                }`}
              >
                <div
                  className="absolute right-2 top-2"
                  data-comment-menu-root="true"
                  onMouseDown={(event) => event.stopPropagation()}
                >
                  <button
                    type="button"
                    aria-label="评论操作"
                    onMouseDown={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                    }}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      onCommentActivate(comment.id);
                      setOpenMenuId((current) => (current === comment.id ? null : comment.id));
                    }}
                    className="flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                  {openMenuId === comment.id && (
                    <div className="absolute right-0 top-8 z-[90] w-20 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg shadow-black/10">
                      <button
                        type="button"
                        onMouseDown={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                        }}
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setOpenMenuId(null);
                          window.setTimeout(() => onResolveComment(comment.id), 0);
                        }}
                        className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7]"
                      >
                        已完成
                      </button>
                    </div>
                  )}
                </div>
                <div className="mb-3 pl-2 border-l-2 border-[#d1d1d6]">
                  <div
                    data-comment-quote="true"
                    title={quoteText}
                    className="max-h-24 overflow-y-auto whitespace-pre-wrap break-words text-[12px] leading-relaxed text-[#8a8a8e]"
                  >
                    {quoteText}
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-[#67b226] text-white flex items-center justify-center text-[12px] shrink-0">
                    我
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <strong className="text-[12px] text-[#1d1d1f] font-normal">{comment.author}</strong>
                      <span className="text-[11px] text-[#aeaeb2]">{formatCommentTimestamp(comment.time)}</span>
                    </div>
                    <p className="text-[13px] text-[#3a3a3c] leading-relaxed whitespace-pre-wrap">{comment.text}</p>
                    <div className="flex items-center gap-3 mt-2 text-[#636366]">
                      <ThumbsUp className="w-4 h-4" />
                      <MessageSquareText className="w-4 h-4" />
                    </div>

                    {comment.replies.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {visibleReplies.length > 0 ? (
                          visibleReplies.map((reply) => (
                            <div key={reply.id} className="rounded-lg bg-[#fafbfc] px-3 py-2">
                              <div className="flex items-center gap-2 mb-1">
                                <strong className="text-[12px] text-[#1d1d1f] font-normal">{reply.author}</strong>
                                <span className="text-[10px] text-[#aeaeb2]">{formatCommentTimestamp(reply.time)}</span>
                              </div>
                              <p className="text-[12px] text-[#636366] leading-relaxed whitespace-pre-wrap">{reply.text}</p>
                            </div>
                          ))
                        ) : (
                          <div className="rounded-lg bg-[#fafbfc] px-3 py-2 pr-9 text-[12px] text-[#8a8a8e]">
                            已折叠 {comment.replies.length} 条追评
                          </div>
                        )}
                      </div>
                    )}

                    {expanded ? (
                      <div className="mt-3 rounded-lg border border-[#e5e5ea] bg-white overflow-hidden">
                        <textarea
                          value={replyDrafts[comment.id] ?? ""}
                          onChange={(event) => onReplyDraftChange(comment.id, event.target.value)}
                          placeholder="追加评论"
                          className="w-full min-h-[44px] px-3 py-2 text-[12px] text-[#3a3a3c] outline-none resize-none"
                        />
                        <div className="flex items-center justify-between px-2.5 py-1.5 border-t border-[#f0f0f2]">
                          <ImageIcon className="w-4 h-4 text-[#636366]" />
                          <button
                            onClick={() => onReplySave(comment.id)}
                            disabled={!replyDrafts[comment.id]?.trim()}
                            className="px-2.5 py-1 rounded-md bg-[#f2f2f7] text-[#636366] text-[12px] disabled:opacity-40"
                          >
                            保存
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onReplyToggle(comment.id, true)}
                        className="mt-3 text-[12px] text-[#aeaeb2] hover:text-[#636366] transition-colors"
                      >
                        追评……
                      </button>
                    )}
                  </div>
                </div>
                {shouldFoldReplies && (
                  <button
                    type="button"
                    aria-label={repliesExpanded ? "折叠追评" : "展开追评"}
                    onClick={() => onCommentRepliesToggle(comment.id, !repliesExpanded)}
                    className="absolute bottom-2 right-2 flex h-7 w-7 items-center justify-center rounded-full text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f] transition-colors"
                  >
                    {repliesExpanded ? <ChevronsUp className="h-4 w-4" /> : <ChevronsDown className="h-4 w-4" />}
                  </button>
                )}
              </article>
            </div>
          );
        })}
      </div>
    </div>
  );
}
