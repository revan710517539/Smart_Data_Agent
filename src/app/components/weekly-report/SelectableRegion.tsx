import { createContext, useContext, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { MessageSquareText, Sparkles } from "lucide-react";
import type { CommentTarget, PendingTextSelection } from "./domain";

type AnalysisUnderlineContextValue = {
  targets: CommentTarget[];
  activeTargetId?: string;
  onActivate?: (target: CommentTarget, rect: DOMRect) => void;
};

const AnalysisUnderlineContext = createContext<AnalysisUnderlineContextValue>({ targets: [] });

export function AnalysisUnderlineProvider({
  targets,
  activeTargetId,
  onActivate,
  children,
}: AnalysisUnderlineContextValue & { children: ReactNode }) {
  return (
    <AnalysisUnderlineContext.Provider value={{ targets, activeTargetId, onActivate }}>
      {children}
    </AnalysisUnderlineContext.Provider>
  );
}

export function FloatingSelectionActions({
  selection,
  onOpenComment,
  onOpenAnalysis,
}: {
  selection: PendingTextSelection;
  onOpenComment: (target: CommentTarget) => void;
  onOpenAnalysis: (target: CommentTarget) => void;
}) {
  return (
    <div data-weekly-selection-action="true" className="absolute z-[80] flex items-center gap-1 rounded-full bg-white p-1 shadow-lg shadow-black/20" style={{ top: selection.top, left: selection.left }}>
      <SelectionButton label="添加评论" kind="comment" onMouseDown={() => onOpenComment(selection.target)} />
      <SelectionButton label="智能分析选中文本" kind="analysis" onMouseDown={() => onOpenAnalysis(selection.target)} />
    </div>
  );
}

export function SelectableRegion({
  target,
  selectedTargetId,
  onSelect,
  onOpenComment,
  onOpenAnalysis,
  analysisTargets = [],
  activeAnalysisTargetId,
  onAnalysisTargetActivate,
  children,
  className = "",
}: {
  target: CommentTarget;
  selectedTargetId?: string;
  onSelect: (target: CommentTarget) => void;
  onOpenComment: (target: CommentTarget) => void;
  onOpenAnalysis: (target: CommentTarget) => void;
  analysisTargets?: CommentTarget[];
  activeAnalysisTargetId?: string;
  onAnalysisTargetActivate?: (target: CommentTarget, rect: DOMRect) => void;
  children: ReactNode;
  className?: string;
}) {
  const underlineContext = useContext(AnalysisUnderlineContext);
  const selected = selectedTargetId === target.id || Boolean(selectedTargetId?.startsWith(`${target.id}__analysis_`));
  const rootRef = useRef<HTMLDivElement>(null);
  const capturedSelectionRef = useRef(false);
  const [selectionTarget, setSelectionTarget] = useState<CommentTarget | null>(null);
  const actionTarget = selected && selectionTarget ? selectionTarget : target;

  function captureTextSelection() {
    const container = rootRef.current;
    const selection = window.getSelection();
    if (!container || !selection || selection.isCollapsed || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!container.contains(range.commonAncestorContainer)) return;
    const rawSelectedText = selection.toString();
    const selectedText = rawSelectedText.trim();
    if (!selectedText) return;

    const beforeSelection = range.cloneRange();
    beforeSelection.selectNodeContents(container);
    beforeSelection.setEnd(range.startContainer, range.startOffset);
    const leadingWhitespace = Math.max(0, rawSelectedText.indexOf(selectedText));
    const rangeStart = beforeSelection.toString().length + leadingWhitespace;
    const nextTarget = {
      ...target,
      selectedText,
      rangeStart,
      rangeEnd: rangeStart + selectedText.length,
      ...selectionAnchor(container, range.getBoundingClientRect()),
    };
    capturedSelectionRef.current = true;
    setSelectionTarget(nextTarget);
    onSelect(nextTarget);
  }

  function selectRegion() {
    if (capturedSelectionRef.current) {
      capturedSelectionRef.current = false;
      return;
    }
    setSelectionTarget(null);
    onSelect(target);
  }

  return (
    <div
      ref={rootRef}
      className={`relative rounded-lg transition-shadow selection:bg-[#dce9ff] selection:text-[#0b57d0] ${className} ${selected ? "ring-2 ring-[#0a66c2]/25" : ""}`}
      onMouseUp={captureTextSelection}
      onClick={selectRegion}
      data-comment-target={target.id}
      data-context-target={target.id}
    >
      {children}
      <AnalysisUnderlineLayer
        containerRef={rootRef}
        targets={[...underlineContext.targets, ...analysisTargets].filter((item, index, all) =>
          (item.contextTargetId === target.id || item.id === target.id || item.id.startsWith(`${target.id}__analysis_`))
          && all.findIndex((candidate) => candidate.id === item.id) === index,
        )}
        activeTargetId={activeAnalysisTargetId || underlineContext.activeTargetId}
        onActivate={onAnalysisTargetActivate || underlineContext.onActivate}
      />
      {selected && (
        <div data-weekly-selection-action="true" className="absolute right-3 top-2 z-20 flex items-center gap-1 rounded-full bg-white p-1 shadow-lg shadow-black/15">
          <SelectionButton label={`评论 ${target.label}`} kind="comment" onClick={() => onOpenComment(actionTarget)} />
          <SelectionButton label={`分析 ${target.label}`} kind="analysis" onClick={() => onOpenAnalysis(actionTarget)} />
        </div>
      )}
    </div>
  );
}

type UnderlineRect = { left: number; top: number; width: number; height: number };

function AnalysisUnderlineLayer({
  containerRef,
  targets,
  activeTargetId,
  onActivate,
}: {
  containerRef: RefObject<HTMLDivElement>;
  targets: CommentTarget[];
  activeTargetId?: string;
  onActivate?: (target: CommentTarget, rect: DOMRect) => void;
}) {
  const [rectsByTarget, setRectsByTarget] = useState<Record<string, UnderlineRect[]>>({});
  const targetSignature = targets.map((target) => `${target.id}:${target.rangeStart}:${target.rangeEnd}`).join("|");

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container || !targets.length) {
      setRectsByTarget({});
      return;
    }

    const update = () => {
      const containerRect = container.getBoundingClientRect();
      const next: Record<string, UnderlineRect[]> = {};
      targets.forEach((analysisTarget) => {
        const range = rangeFromTextOffsets(container, analysisTarget.rangeStart, analysisTarget.rangeEnd);
        if (!range) return;
        next[analysisTarget.id] = Array.from(range.getClientRects())
          .filter((rect) => rect.width > 0 && rect.height > 0)
          .map((rect) => ({
            left: rect.left - containerRect.left,
            top: rect.top - containerRect.top,
            width: rect.width,
            height: rect.height,
          }));
      });
      setRectsByTarget(next);
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(container);
    return () => observer.disconnect();
  }, [containerRef, targetSignature]);

  if (!targets.length) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-[15]" data-analysis-underline-layer="true">
      {targets.flatMap((analysisTarget) =>
        (rectsByTarget[analysisTarget.id] || []).map((rect, index) => {
          const active = activeTargetId === analysisTarget.id;
          const commentAnnotation = analysisTarget.annotationKind === "comment";
          return (
            <button
              key={`${analysisTarget.id}_${index}`}
              type="button"
              aria-label={`${commentAnnotation ? "打开评论" : "打开AI分析"}：${analysisTarget.selectedText || analysisTarget.label}`}
              data-analysis-annotation={commentAnnotation ? undefined : analysisTarget.id}
              data-comment-annotation={commentAnnotation ? analysisTarget.id : undefined}
              data-annotation-kind={commentAnnotation ? "comment" : "analysis"}
              onMouseDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onActivate?.(analysisTarget, event.currentTarget.getBoundingClientRect());
              }}
              className={`pointer-events-auto absolute cursor-pointer rounded-sm border-b-2 transition-colors ${commentAnnotation
                ? active
                  ? "border-[#0b57d0] bg-[#dce9ff]/90"
                  : "border-[#1a73e8] bg-[#eef4ff]/65 hover:bg-[#dce9ff]/75"
                : active
                  ? "border-[#d70015] bg-[#ffe5e5]/90"
                  : "border-[#ff3b30] bg-[#fff1f0]/65 hover:bg-[#ffe5e5]/75"
              }`}
              style={rect}
            />
          );
        }),
      )}
    </div>
  );
}

function rangeFromTextOffsets(container: Element, start?: number, end?: number) {
  if (typeof start !== "number" || typeof end !== "number" || end <= start) return null;
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (parent?.closest("[data-weekly-selection-action], [data-analysis-underline-layer]")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const range = document.createRange();
  let offset = 0;
  let startSet = false;
  let node = walker.nextNode();
  while (node) {
    const length = node.textContent?.length || 0;
    if (!startSet && start <= offset + length) {
      range.setStart(node, Math.max(0, start - offset));
      startSet = true;
    }
    if (startSet && end <= offset + length) {
      range.setEnd(node, Math.max(0, end - offset));
      return range;
    }
    offset += length;
    node = walker.nextNode();
  }
  return null;
}

function selectionAnchor(container: Element, rawRect: DOMRect) {
  const fallbackRect = container.getBoundingClientRect();
  const rect = rawRect.width || rawRect.height ? rawRect : fallbackRect;
  const pageBody = container.closest<HTMLElement>("[data-context-page-body]");
  const bodyRect = pageBody?.getBoundingClientRect();
  return {
    anchorTop: bodyRect ? Math.max(12, rect.top - bodyRect.top) : 84,
    anchorViewportTop: rect.top,
  };
}

function SelectionButton({
  label,
  kind,
  onClick,
  onMouseDown,
}: {
  label: string;
  kind: "comment" | "analysis";
  onClick?: () => void;
  onMouseDown?: () => void;
}) {
  const analysis = kind === "analysis";
  const Icon = analysis ? Sparkles : MessageSquareText;
  return (
    <button
      type="button"
      aria-label={label}
      data-comment-selection-action={analysis ? undefined : "true"}
      data-analysis-selection-action={analysis ? "true" : undefined}
      onClick={(event) => { event.stopPropagation(); onClick?.(); }}
      onMouseDown={(event) => { event.preventDefault(); event.stopPropagation(); onMouseDown?.(); }}
      className={`flex h-8 w-8 items-center justify-center rounded-full text-white transition-colors ${analysis ? "bg-[#0a66c2] hover:bg-[#07549f]" : "bg-[#1d1d1f] hover:bg-[#2c2c2e]"}`}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}
