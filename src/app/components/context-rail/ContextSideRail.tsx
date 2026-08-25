import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { MessageSquarePlus, MessageSquareText, PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react";
import { revealAnalysisWorkspace } from "../analysis-workspace/AnalysisWorkspaceRail";

export type ContextRailTab = "comments" | "analysis" | "message-board";
export const contextRailRevealEvent = "smart-data-agent:reveal-context-rail";
export const contextRailWideEvent = "smart-data-agent:context-rail-wide";

export type ContextRailRevealTarget = {
  targetId: string;
  targetType: "chart" | "table" | "metric" | "institution" | "text";
  label?: string;
  values?: Record<string, unknown>;
};

export function revealContextRail(pageKey: string, tab: ContextRailTab, target?: ContextRailRevealTarget) {
  window.dispatchEvent(new CustomEvent(contextRailRevealEvent, { detail: { pageKey, tab, target } }));
}

export function ContextSideRail({
  pageKey,
  activeTab,
  onTabChange,
  commentCount,
  comments,
  analysis,
  messageBoard,
  wide = false,
  onWideChange,
  flushToViewport = false,
}: {
  pageKey: string;
  activeTab: ContextRailTab;
  onTabChange: (tab: ContextRailTab) => void;
  commentCount: number;
  comments: ReactNode;
  analysis: ReactNode;
  messageBoard: ReactNode;
  wide?: boolean;
  onWideChange?: (wide: boolean) => void;
  flushToViewport?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const [edgeVisible, setEdgeVisible] = useState(false);
  const railRef = useRef<HTMLElement>(null);
  const railWidthClass = wide ? "w-[640px]" : "w-[320px]";
  const viewport = useVisualViewportBox();

  useEffect(() => {
    setCollapsed(true);
    setEdgeVisible(false);
    onWideChange?.(false);
  }, [pageKey]);

  useEffect(() => {
    const reveal = (event: Event) => {
      const detail = (event as CustomEvent<{ pageKey?: string; tab?: ContextRailTab }>).detail;
      if (detail?.pageKey !== pageKey) return;
      if (detail.tab === "comments" || detail.tab === "analysis" || detail.tab === "message-board") onTabChange(detail.tab);
      setCollapsed(false);
    };
    window.addEventListener(contextRailRevealEvent, reveal);
    return () => window.removeEventListener(contextRailRevealEvent, reveal);
  }, [onTabChange, pageKey]);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent(contextRailWideEvent, { detail: { pageKey, wide } }));
  }, [pageKey, wide]);

  useEffect(() => {
    if (!collapsed) {
      setEdgeVisible(false);
      return;
    }
    const onMove = (event: PointerEvent) => {
      const fromRight = window.innerWidth - event.clientX;
      setEdgeVisible(fromRight >= 0 && fromRight <= 40);
    };
    const onLeave = () => setEdgeVisible(false);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
    };
  }, [collapsed]);

  useLayoutEffect(() => {
    if (collapsed || flushToViewport) return;
    const rail = railRef.current;
    if (!rail) return;
    const apply = () => {
      const top = rail.getBoundingClientRect().top;
      const nextHeight = Math.max(280, Math.round(viewport.bottom - top));
      rail.style.height = `${nextHeight}px`;
      rail.style.maxHeight = `${Math.max(280, viewport.height)}px`;
    };
    apply();
    const main = document.querySelector("[data-agent-main-shell]");
    window.addEventListener("resize", apply);
    window.addEventListener("scroll", apply, true);
    main?.addEventListener("scroll", apply, { passive: true });
    return () => {
      window.removeEventListener("resize", apply);
      window.removeEventListener("scroll", apply, true);
      main?.removeEventListener("scroll", apply);
      rail.style.height = "";
      rail.style.maxHeight = "";
    };
  }, [collapsed, flushToViewport, pageKey, viewport.bottom, viewport.height, wide]);

  return (
    <>
      {flushToViewport && !collapsed ? <div className={`weekly-report-print-hidden shrink-0 ${railWidthClass}`} data-context-rail-spacer="true" /> : null}
      {!collapsed ? (
      <aside
        ref={railRef}
        className={`weekly-report-print-hidden flex min-h-0 flex-col overflow-hidden rounded-tl-xl border border-b-0 border-r-0 border-[#e5e5ea] bg-white ${railWidthClass} ${flushToViewport ? "fixed top-4 right-0 bottom-0 z-[65]" : "sticky top-0 z-30 h-[min(100dvh,100vh)] max-h-[100dvh] shrink-0 self-start"}`}
        style={flushToViewport ? { top: Math.max(16, viewport.offsetTop), bottom: viewport.bottomInset, paddingBottom: "env(safe-area-inset-bottom, 0px)" } : { maxHeight: `${Math.max(280, viewport.height)}px` }}
        data-context-rail="expanded"
        data-context-page={pageKey}
        data-context-rail-wide={wide ? "true" : "false"}
        data-context-rail-flush="true"
      >
        <div className="z-20 shrink-0 border-b border-[#ececf0] bg-white p-2" data-context-rail-tabs="true">
          <div className="grid grid-cols-[32px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-1">
            <button type="button" onClick={() => { onWideChange?.(false); setCollapsed(true); }} className="flex h-10 items-center justify-center rounded-lg text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" aria-label="收起右侧评论与智能分析栏" title="收起右侧栏" data-context-rail-collapse="true">
              <PanelRightClose className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => onTabChange("comments")} className={`flex h-10 min-w-0 items-center justify-center gap-1 whitespace-nowrap rounded-lg px-1 text-[11px] transition-colors sm:text-[12px] ${activeTab === "comments" ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#636366] hover:bg-[#f2f2f7]"}`}>
              <MessageSquareText className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">评论{commentCount ? ` ${commentCount}` : ""}</span>
            </button>
            <button type="button" data-context-rail-analysis-tab="true" onClick={() => { revealAnalysisWorkspace(undefined); onTabChange("analysis"); }} className={`flex h-10 min-w-0 items-center justify-center gap-1 whitespace-nowrap rounded-lg px-1 text-[11px] transition-colors sm:text-[12px] ${activeTab === "analysis" ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#636366] hover:bg-[#f2f2f7]"}`}>
              <Sparkles className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">AI 分析</span>
            </button>
            <button type="button" onClick={() => onTabChange("message-board")} className={`flex h-10 min-w-0 items-center justify-center gap-1 whitespace-nowrap rounded-lg px-1 text-[11px] transition-colors sm:text-[12px] ${activeTab === "message-board" ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#636366] hover:bg-[#f2f2f7]"}`} data-context-rail-message-board="true">
              <MessageSquarePlus className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">留言板</span>
            </button>
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden overscroll-contain bg-[#f7f8fa] px-2 pb-2" data-context-rail-scroll="true">
          <div className={activeTab === "comments" ? "flex h-full min-h-0 flex-1 flex-col overflow-hidden" : "hidden"}>{comments}</div>
          <div className={activeTab === "analysis" ? "flex h-full min-h-0 flex-1 flex-col overflow-hidden" : "hidden"}>{analysis}</div>
          <div className={activeTab === "message-board" ? "flex h-full min-h-0 flex-1 flex-col overflow-hidden" : "hidden"}>{messageBoard}</div>
        </div>
      </aside>
      ) : null}

      {collapsed && (
        <aside className="weekly-report-print-hidden w-[0.2cm] shrink-0" data-context-rail="collapsed" data-context-rail-edge="true" data-context-page={pageKey}>
          <div
            className="pointer-events-none fixed bottom-0 right-0 top-0 z-[110] w-10"
            data-context-rail-edge-zone="true"
          >
            <button
              type="button"
              aria-label="展开右侧评论与智能分析栏"
              title="展开右侧栏"
              onClick={() => setCollapsed(false)}
              className={`fixed right-2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-[#d9d9de] bg-white text-[#636366] shadow-lg shadow-black/10 transition-opacity hover:bg-[#f2f2f7] hover:text-[#1d1d1f] ${edgeVisible ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"}`}
              style={{ top: "50%" }}
              data-context-rail-expand="true"
            >
              <PanelRightOpen className="h-4 w-4" />
            </button>
          </div>
        </aside>
      )}
    </>
  );
}

function useVisualViewportBox() {
  const [box, setBox] = useState({ offsetTop: 0, bottomInset: 0, height: 0, bottom: 0 });

  useLayoutEffect(() => {
    const apply = () => {
      const viewport = window.visualViewport;
      const height = Math.round(viewport?.height || window.innerHeight);
      const offsetTop = Math.max(0, Math.round(viewport?.offsetTop || 0));
      const bottomInset = Math.max(0, Math.round(window.innerHeight - offsetTop - height));
      setBox({ offsetTop, bottomInset, height, bottom: offsetTop + height });
    };
    apply();
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", apply);
    viewport?.addEventListener("scroll", apply);
    window.addEventListener("resize", apply);
    return () => {
      viewport?.removeEventListener("resize", apply);
      viewport?.removeEventListener("scroll", apply);
      window.removeEventListener("resize", apply);
    };
  }, []);

  return box;
}
