import { useEffect, useMemo, useRef, useState, type ComponentProps } from "react";
import { ContextSideRail } from "../context-rail/ContextSideRail";
import { CommentsPanel } from "./CommentsPanel";
import { WeeklyContextAnalysisPanel } from "./ContextAnalysisPanel";
import type { CommentTarget } from "./domain";

type CommentsProps = ComponentProps<typeof CommentsPanel>;
type AnalysisProps = ComponentProps<typeof WeeklyContextAnalysisPanel>;

export function WeeklyReportSideRail({
  activeTab,
  onTabChange,
  commentCount,
  commentsProps,
  analysisProps,
  pageKey = "weekly-report",
  pageTitle = "经营周报",
  overallPrompt = "请结合当前页面及关联指标数据进行总体分析，说明关键变化、风险与建议。",
  railHeight,
  focusTargetId,
  focusTarget,
  onAnalysisTargetActivate,
  onAnalysisTargetDismiss,
}: {
  activeTab: "comments" | "analysis";
  onTabChange: (tab: "comments" | "analysis") => void;
  commentCount: number;
  railHeight: number;
  commentsProps: Omit<CommentsProps, "showHeader">;
  analysisProps: AnalysisProps;
  pageKey?: string;
  pageTitle?: string;
  overallPrompt?: string;
  focusTargetId?: string;
  focusTarget?: CommentTarget | null;
  onAnalysisTargetActivate?: (target: CommentTarget | null) => void;
  onAnalysisTargetDismiss?: (target: CommentTarget) => void;
}) {
  const analysisScopeKey = `${analysisProps.tenantId}:${analysisProps.userId}:${pageKey}:${analysisProps.report.id}`;
  const [analysisTargets, setAnalysisTargets] = useState<Array<CommentTarget | null>>([null]);
  const [analysisStateScopeKey, setAnalysisStateScopeKey] = useState(analysisScopeKey);
  const [activeTargetKey, setActiveTargetKey] = useState<string | null>(null);
  const [startedTargetKeys, setStartedTargetKeys] = useState<Record<string, boolean>>({});
  const [cardHeights, setCardHeights] = useState<Record<string, number>>({});
  const analysisListRef = useRef<HTMLDivElement>(null);
  const requestedTargetId = analysisProps.target?.id;
  const scopeMatches = analysisStateScopeKey === analysisScopeKey;
  const scopedAnalysisTargets = scopeMatches ? analysisTargets : [null];
  const targetKey = (target: CommentTarget | null) => target?.id || "overall";

  useEffect(() => {
    setAnalysisStateScopeKey(analysisScopeKey);
    setAnalysisTargets([null]);
    setActiveTargetKey(null);
    setStartedTargetKeys({});
  }, [analysisScopeKey]);

  useEffect(() => {
    if (!scopeMatches || !analysisProps.target) return;
    const requested = analysisProps.target;
    setAnalysisTargets((current) => [requested, ...current.filter((item) => item?.id !== requested.id)]);
    setActiveTargetKey(requested.id);
  }, [analysisProps.target, requestedTargetId, scopeMatches]);

  useEffect(() => {
    const targetId = focusTarget?.id || focusTargetId;
    if (!scopeMatches || !targetId || !scopedAnalysisTargets.some((item) => item?.id === targetId)) return;
    setActiveTargetKey(targetId);
    if (focusTarget) {
      setAnalysisTargets((current) => {
        let changed = false;
        const next = current.map((item) => {
          if (item?.id !== targetId) return item;
          const unchanged = item.anchorTop === focusTarget.anchorTop
            && item.anchorViewportTop === focusTarget.anchorViewportTop
            && item.selectedText === focusTarget.selectedText
            && item.rangeStart === focusTarget.rangeStart
            && item.rangeEnd === focusTarget.rangeEnd;
          if (unchanged) return item;
          changed = true;
          return { ...item, ...focusTarget };
        });
        return changed ? next : current;
      });
    }
    if (typeof focusTarget?.anchorViewportTop === "number") {
      const timeoutId = window.setTimeout(() => alignAnalysisCard(targetId, focusTarget.anchorViewportTop!), 80);
      return () => window.clearTimeout(timeoutId);
    }
  }, [focusTarget, focusTargetId, scopeMatches, scopedAnalysisTargets]);

  useEffect(() => {
    const root = analysisListRef.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const update = () => {
      const next: Record<string, number> = {};
      root.querySelectorAll<HTMLElement>("[data-analysis-entry-key]").forEach((entry) => {
        const key = entry.dataset.analysisEntryKey;
        if (key) next[key] = Math.ceil(entry.getBoundingClientRect().height);
      });
      setCardHeights((current) => {
        const keys = Object.keys(next);
        const unchanged = keys.length === Object.keys(current).length && keys.every((key) => current[key] === next[key]);
        return unchanged ? current : next;
      });
    };
    update();
    const observer = new ResizeObserver(update);
    root.querySelectorAll<HTMLElement>("[data-analysis-entry-key]").forEach((entry) => observer.observe(entry));
    return () => observer.disconnect();
  }, [analysisTargets]);

  useEffect(() => {
    const handleDocumentMouseDown = (event: MouseEvent) => {
      const element = event.target;
      if (!(element instanceof Element) || !activeTargetKey) return;
      if (element.closest("[data-analysis-annotation]")) return;
      const clickedCard = element.closest<HTMLElement>("[data-context-analysis-card]");
      const clickedKey = clickedCard?.dataset.contextAnalysisCard || null;
      if (clickedKey === activeTargetKey) return;

      const activeTarget = scopedAnalysisTargets.find((item) => targetKey(item) === activeTargetKey);
      if (activeTarget && activeTargetKey !== "overall" && !startedTargetKeys[activeTargetKey]) {
        setAnalysisTargets((current) => current.filter((item) => targetKey(item) !== activeTargetKey));
        setStartedTargetKeys((current) => {
          const next = { ...current };
          delete next[activeTargetKey];
          return next;
        });
        onAnalysisTargetDismiss?.(activeTarget);
      }

      if (!clickedCard) {
        setActiveTargetKey(null);
        onAnalysisTargetActivate?.(null);
      }
    };

    document.addEventListener("mousedown", handleDocumentMouseDown, true);
    return () => document.removeEventListener("mousedown", handleDocumentMouseDown, true);
  }, [activeTargetKey, onAnalysisTargetActivate, onAnalysisTargetDismiss, scopedAnalysisTargets, startedTargetKeys]);

  const activateTarget = (target: CommentTarget | null) => {
    setActiveTargetKey(targetKey(target));
    onAnalysisTargetActivate?.(target);
  };

  const completeTarget = (target: CommentTarget | null) => {
    const key = targetKey(target);
    setAnalysisTargets((current) => current.filter((item) => targetKey(item) !== key));
    setActiveTargetKey((current) => current === key ? null : current);
    setStartedTargetKeys((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
    onAnalysisTargetActivate?.(null);
    if (target) onAnalysisTargetDismiss?.(target);
  };

  const updateStartedState = (key: string, started: boolean) => {
    setStartedTargetKeys((current) => {
      if (started) return current[key] ? current : { ...current, [key]: true };
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const positionedTargets = useMemo(
    () => positionAnalysisTargets(scopedAnalysisTargets, activeTargetKey, cardHeights),
    [activeTargetKey, scopedAnalysisTargets, cardHeights],
  );
  const analysisListHeight = Math.max(
    railHeight,
    ...positionedTargets.map((entry) => entry.top + (cardHeights[entry.key] || 260) + 16),
  );

  return (
    <ContextSideRail
      pageKey={pageKey}
      activeTab={activeTab}
      onTabChange={onTabChange}
      commentCount={commentCount}
      comments={<CommentsPanel {...commentsProps} showHeader={false} />}
      analysis={(
        <div ref={analysisListRef} className="relative" style={{ minHeight: analysisListHeight }} data-context-analysis-list="true">
          {positionedTargets.map(({ target, key, top }) => {
            return (
              <div
                key={`${analysisScopeKey}:${target?.id || "overall"}`}
                data-analysis-entry-key={key}
                className="absolute left-0 right-0 transition-[top] duration-300 ease-out"
                style={{ top, zIndex: activeTargetKey === key ? 60 : 10 }}
              >
                <WeeklyContextAnalysisPanel
                  {...analysisProps}
                  target={target}
                  pageKey={pageKey}
                  pageTitle={pageTitle}
                  overallPrompt={overallPrompt}
                  active={activeTargetKey === key}
                  onActivate={() => activateTarget(target)}
                  onComplete={() => completeTarget(target)}
                  onStartedChange={(started) => updateStartedState(key, started)}
                />
              </div>
            );
          })}
        </div>
      )}
    />
  );
}

function positionAnalysisTargets(
  targets: Array<CommentTarget | null>,
  activeKey: string | null,
  heights: Record<string, number>,
) {
  const ordered = [...targets].sort((left, right) => (left?.anchorTop ?? 12) - (right?.anchorTop ?? 12));
  let nextTop = 12;
  return ordered.map((target) => {
    const key = target?.id || "overall";
    const desiredTop = Math.max(12, target?.anchorTop ?? 12);
    const top = activeKey === key && target ? desiredTop : Math.max(desiredTop, nextTop);
    nextTop = Math.max(nextTop, top + (heights[key] || 260) + 12);
    return { target, key, top };
  });
}

function alignAnalysisCard(targetId: string, viewportTop: number) {
  const entry = Array.from(document.querySelectorAll<HTMLElement>("[data-analysis-entry-key]"))
    .find((element) => element.dataset.analysisEntryKey === targetId);
  const scroller = entry?.closest<HTMLElement>("[data-context-rail-scroll]");
  if (!entry || !scroller) return;
  const scrollerRect = scroller.getBoundingClientRect();
  const targetTop = Math.max(scrollerRect.top + 8, Math.min(scrollerRect.bottom - 80, viewportTop));
  const delta = entry.getBoundingClientRect().top - targetTop;
  const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  scroller.scrollTo({ top: Math.max(0, Math.min(maxScroll, scroller.scrollTop + delta)), behavior: "smooth" });
}
