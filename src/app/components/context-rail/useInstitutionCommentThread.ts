import { useCallback, useEffect, useRef, useState } from "react";
import { createReportComment, fetchReportComments, mutateReportComment, type ReportComment } from "../../services/reportApi";
import { isDemoFallbackEnabled } from "../../services/apiContext";
import {
  formatNow,
  loadLocalReportComments,
  makeId,
  normalizeComments,
  saveLocalReportComments,
  type CommentItem,
  type CommentResolvedReason,
  type CommentTarget,
} from "../weekly-report/domain";

type MutationResponse = { comments: ReportComment[]; revision: number };

export function useInstitutionCommentThread({
  tenantId,
  userId,
  userName,
  reportId,
}: {
  tenantId: string;
  userId: string;
  userName: string;
  reportId: string;
}) {
  const [comments, setComments] = useState<CommentItem[]>([]);
  const commentsRef = useRef<CommentItem[]>([]);
  const revisionRef = useRef(0);
  const mutationQueueRef = useRef<Promise<void>>(Promise.resolve());
  const scopeKey = `${tenantId}:${userId}:${reportId}`;
  const scopeKeyRef = useRef(scopeKey);

  const replaceComments = useCallback((next: CommentItem[]) => {
    commentsRef.current = next;
    setComments(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    scopeKeyRef.current = scopeKey;
    revisionRef.current = 0;
    mutationQueueRef.current = Promise.resolve();
    replaceComments([]);

    void fetchReportComments({ tenantId, userId, reportId })
      .then((response) => {
        if (cancelled || scopeKeyRef.current !== scopeKey) return;
        revisionRef.current = Number(response.revision || 0);
        replaceComments(normalizeComments(response.comments, userId, userName));
      })
      .catch(() => {
        if (cancelled || scopeKeyRef.current !== scopeKey) return;
        replaceComments(isDemoFallbackEnabled() ? loadLocalReportComments(tenantId, reportId, userId, userName) : []);
      });

    return () => {
      cancelled = true;
    };
  }, [reportId, replaceComments, scopeKey, tenantId, userId, userName]);

  const enqueueMutation = useCallback((
    execute: (expectedRevision: number) => Promise<MutationResponse>,
    optimisticComments: CommentItem[],
  ) => {
    const mutationScope = scopeKey;
    mutationQueueRef.current = mutationQueueRef.current.then(async () => {
      if (scopeKeyRef.current !== mutationScope) return;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const response = await execute(revisionRef.current);
          if (scopeKeyRef.current !== mutationScope) return;
          revisionRef.current = Number(response.revision || revisionRef.current + 1);
          replaceComments(normalizeComments(response.comments, userId, userName));
          return;
        } catch {
          try {
            const latest = await fetchReportComments({ tenantId, userId, reportId });
            if (scopeKeyRef.current !== mutationScope) return;
            revisionRef.current = Number(latest.revision || 0);
            replaceComments(normalizeComments(latest.comments, userId, userName));
          } catch {
            break;
          }
        }
      }
      if (scopeKeyRef.current === mutationScope && isDemoFallbackEnabled()) {
        saveLocalReportComments(tenantId, reportId, optimisticComments);
        replaceComments(optimisticComments);
      }
    });
  }, [reportId, replaceComments, scopeKey, tenantId, userId, userName]);

  const createComment = useCallback((target: CommentTarget, text: string) => {
    const body = text.trim();
    if (!body) return "";
    const clientRequestId = makeId("comment_request");
    const pendingId = `pending_${clientRequestId}`;
    const pending: CommentItem = {
      id: pendingId,
      targetId: target.id,
      targetLabel: target.label,
      selectedText: target.selectedText,
      blockId: target.blockId,
      itemId: target.itemId,
      rangeStart: target.rangeStart,
      rangeEnd: target.rangeEnd,
      anchorTop: target.anchorTop,
      status: "open",
      targetKind: target.targetKind,
      author: userName || userId,
      time: formatNow(),
      text: body,
      replies: [],
    };
    const optimistic = [pending, ...commentsRef.current];
    replaceComments(optimistic);
    enqueueMutation(
      (expectedRevision) => createReportComment({
        tenantId,
        userId,
        reportId,
        comment: {
          targetId: target.id,
          targetLabel: target.label,
          selectedText: target.selectedText,
          blockId: target.blockId,
          itemId: target.itemId,
          rangeStart: target.rangeStart,
          rangeEnd: target.rangeEnd,
          anchorTop: target.anchorTop,
          targetKind: target.targetKind,
          text: body,
        },
        expectedRevision,
        clientRequestId,
      }),
      optimistic,
    );
    return pendingId;
  }, [enqueueMutation, reportId, replaceComments, tenantId, userId, userName]);

  const replyToComment = useCallback((commentId: string, text: string) => {
    const body = text.trim();
    if (!body) return;
    const clientRequestId = makeId("reply_request");
    const optimistic = commentsRef.current.map((comment) => comment.id === commentId ? {
      ...comment,
      replies: [...comment.replies, { id: `pending_${clientRequestId}`, author: userName || userId, time: formatNow(), text: body }],
    } : comment);
    replaceComments(optimistic);
    enqueueMutation(
      (expectedRevision) => mutateReportComment({
        tenantId,
        userId,
        reportId,
        commentId,
        action: "reply",
        payload: { text: body },
        expectedRevision,
        clientRequestId,
      }),
      optimistic,
    );
  }, [enqueueMutation, reportId, replaceComments, tenantId, userId, userName]);

  const resolveComment = useCallback((commentId: string, reason: CommentResolvedReason = "manual") => {
    const optimistic = commentsRef.current.map((comment) => comment.id === commentId ? {
      ...comment,
      status: "resolved" as const,
      resolvedAt: formatNow(),
      resolvedBy: userId,
      resolvedReason: reason,
    } : comment);
    replaceComments(optimistic);
    enqueueMutation(
      (expectedRevision) => mutateReportComment({
        tenantId,
        userId,
        reportId,
        commentId,
        action: "resolve",
        payload: { reason },
        expectedRevision,
      }),
      optimistic,
    );
  }, [enqueueMutation, reportId, replaceComments, tenantId, userId]);

  return { comments, createComment, replyToComment, resolveComment };
}
