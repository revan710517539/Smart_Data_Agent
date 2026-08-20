import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { MessageSquarePlus, MessageSquareText, PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react";

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
}) {
  const [collapsed, setCollapsed] = useState(true);
  const [edgeVisible, setEdgeVisible] = useState(false);
  const railRef = useRef<HTMLElement>(null);

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

  useLayoutEffect(() => {
    if (collapsed) return;
    const rail = railRef.current;
    if (!rail) return;
    const orbClearancePx = 104;
    const apply = () => {
      const top = rail.getBoundingClientRect().top;
      const nextHeight = Math.max(280, Math.round(window.innerHeight - top - orbClearancePx));
      rail.style.height = `${nextHeight}px`;
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
    };
  }, [collapsed, pageKey, wide]);

  return (
    <>
      <aside
        ref={railRef}
        className={`weekly-report-print-hidden sticky top-4 mr-20 h-[calc(100vh-8rem)] shrink-0 overflow-hidden rounded-xl border border-[#e5e5ea] bg-white ${wide ? "w-[640px]" : "w-[320px]"} ${collapsed ? "hidden" : ""}`}
        data-context-rail={collapsed ? "collapsed" : "expanded"}
        data-context-page={pageKey}
        data-context-rail-wide={wide ? "true" : "false"}
        data-context-rail-orb-clearance="true"
      >
        <div className="absolute inset-x-0 top-0 z-[75] border-b border-[#ececf0] bg-white p-2" data-context-rail-tabs="true">
          <div className="grid grid-cols-[32px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-1">
            <button type="button" onClick={() => { onWideChange?.(false); setCollapsed(true); }} className="flex h-10 items-center justify-center rounded-lg text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" aria-label="收起右侧评论与智能分析栏" title="收起右侧栏" data-context-rail-collapse="true">
              <PanelRightClose className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => onTabChange("comments")} className={`flex h-10 items-center justify-center gap-1.5 rounded-lg text-[12px] transition-colors ${activeTab === "comments" ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#636366] hover:bg-[#f2f2f7]"}`}>
              <MessageSquareText className="h-3.5 w-3.5" />
              评论{commentCount ? ` ${commentCount}` : ""}
            </button>
            <button type="button" onClick={() => onTabChange("analysis")} className={`flex h-10 items-center justify-center gap-1.5 rounded-lg text-[12px] transition-colors ${activeTab === "analysis" ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#636366] hover:bg-[#f2f2f7]"}`}>
              <Sparkles className="h-3.5 w-3.5" />
              AI 分析
            </button>
            <button type="button" onClick={() => onTabChange("message-board")} className={`flex h-10 items-center justify-center gap-1 rounded-lg text-[12px] transition-colors ${activeTab === "message-board" ? "bg-[#edf4fb] text-[#0a66c2]" : "text-[#636366] hover:bg-[#f2f2f7]"}`} data-context-rail-message-board="true">
              <MessageSquarePlus className="h-3.5 w-3.5" />
              留言板
            </button>
          </div>
        </div>
        <div className="absolute inset-x-0 bottom-0 top-[57px] flex min-h-0 flex-col overflow-y-auto overscroll-contain bg-[#f7f8fa] px-2 pb-3" data-context-rail-scroll="true">
          <div className={activeTab === "comments" ? "min-h-0" : "hidden"}>{comments}</div>
          <div className={activeTab === "analysis" ? "flex min-h-0 flex-1 flex-col overflow-hidden" : "hidden"}>{analysis}</div>
          <div className={activeTab === "message-board" ? "min-h-0" : "hidden"}>{messageBoard}</div>
        </div>
      </aside>

      {collapsed && (
        <aside className="weekly-report-print-hidden w-0 shrink-0" data-context-rail-edge="true" data-context-page={pageKey}>
          <div
            className="fixed bottom-0 right-0 top-0 z-[110] w-10"
            data-context-rail-edge-zone="true"
            onMouseEnter={() => {
              setEdgeVisible(true);
            }}
            onMouseLeave={() => setEdgeVisible(false)}
          >
            <button
              type="button"
              aria-label="展开右侧评论与智能分析栏"
              title="展开右侧栏"
              onClick={() => setCollapsed(false)}
              className={`fixed right-2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-[#d9d9de] bg-white text-[#636366] shadow-lg shadow-black/10 transition-opacity hover:bg-[#f2f2f7] hover:text-[#1d1d1f] ${edgeVisible ? "opacity-100" : "pointer-events-none opacity-0"}`}
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
