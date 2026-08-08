import { useEffect, useState, type ReactNode } from "react";
import { MessageSquareText, PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react";

export type ContextRailTab = "comments" | "analysis";
const contextRailRevealEvent = "smart-data-agent:reveal-context-rail";

export function revealContextRail(pageKey: string, tab: ContextRailTab) {
  window.dispatchEvent(new CustomEvent(contextRailRevealEvent, { detail: { pageKey, tab } }));
}

export function ContextSideRail({
  pageKey,
  activeTab,
  onTabChange,
  commentCount,
  comments,
  analysis,
}: {
  pageKey: string;
  activeTab: ContextRailTab;
  onTabChange: (tab: ContextRailTab) => void;
  commentCount: number;
  comments: ReactNode;
  analysis: ReactNode;
}) {
  const storageKey = `smart_data_agent_context_rail_collapsed:${pageKey}`;
  const [collapsed, setCollapsed] = useState(() => window.localStorage.getItem(storageKey) === "true");
  const [edgeVisible, setEdgeVisible] = useState(false);

  useEffect(() => {
    window.localStorage.setItem(storageKey, String(collapsed));
  }, [collapsed, storageKey]);

  useEffect(() => {
    const reveal = (event: Event) => {
      const detail = (event as CustomEvent<{ pageKey?: string; tab?: ContextRailTab }>).detail;
      if (detail?.pageKey !== pageKey) return;
      if (detail.tab === "comments" || detail.tab === "analysis") onTabChange(detail.tab);
      setCollapsed(false);
    };
    window.addEventListener(contextRailRevealEvent, reveal);
    return () => window.removeEventListener(contextRailRevealEvent, reveal);
  }, [onTabChange, pageKey]);

  return (
    <>
      <aside
        className={`weekly-report-print-hidden sticky top-4 h-[calc(100vh-32px)] w-[320px] shrink-0 overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-sm shadow-black/[0.03] ${collapsed ? "hidden" : ""}`}
        data-context-rail={collapsed ? "collapsed" : "expanded"}
        data-context-page={pageKey}
      >
        <div className="absolute inset-x-0 top-0 z-[75] border-b border-[#ececf0] bg-white p-2" data-context-rail-tabs="true">
          <div className="grid grid-cols-[36px_minmax(0,1fr)_minmax(0,1fr)] gap-1">
            <button type="button" onClick={() => setCollapsed(true)} className="flex h-10 items-center justify-center rounded-lg text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" aria-label="收起右侧评论与智能分析栏" title="收起右侧栏" data-context-rail-collapse="true">
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
          </div>
        </div>
        <div className="absolute inset-x-0 bottom-0 top-[57px] overflow-y-auto overscroll-contain bg-[#f7f8fa] px-2 pb-4" data-context-rail-scroll="true">
          <div className={activeTab === "comments" ? "" : "hidden"}>{comments}</div>
          <div className={activeTab === "analysis" ? "" : "hidden"}>{analysis}</div>
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
              className={`fixed right-2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-[#d9d9de] bg-white text-[#636366] shadow-lg shadow-black/10 transition-all hover:bg-[#f2f2f7] hover:text-[#1d1d1f] ${edgeVisible ? "scale-100 opacity-100" : "pointer-events-none scale-90 opacity-0"}`}
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
