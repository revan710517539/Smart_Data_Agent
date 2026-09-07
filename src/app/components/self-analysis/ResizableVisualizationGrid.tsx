import { Children, isValidElement, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import {
  defaultVisualGridSpan,
  packVisualGridItems,
  visualGridIdFromReactKey,
  visualGridSpanForWidth,
  visualGridWidthForSpan,
} from "./visualGridLayout";

type ResizeDirection = "north" | "northeast" | "east" | "southeast" | "south" | "southwest" | "west" | "northwest";
type VisualGridOverride = { span?: number; height?: number };

const visualGridGap = 16;
const defaultVisualGridHeight = 380;
const minimumVisualGridHeight = 280;
const minimumTextVisualGridHeight = 180;

export function ResizableVisualizationGrid({ children, editable = true, onLayoutChange }: { children: ReactNode; editable?: boolean; onLayoutChange?: (id: string, size: { span: number; height: number }) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [overrides, setOverrides] = useState<Record<string, VisualGridOverride>>({});
  const [activeItemId, setActiveItemId] = useState("");
  const itemRefs = useRef(new Map<string, HTMLDivElement>());
  const frameRef = useRef<number | null>(null);
  const entries = useMemo(() => Children.toArray(children).filter(isValidElement).map((child, index) => {
    const hints = gridHintsFromChild(child.props);
    return {
      id: visualGridIdFromReactKey(child.key, index),
      child,
      hints,
    };
  }), [children]);
  const defaultSpan = defaultVisualGridSpan(entries.length);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const updateWidth = () => setContainerWidth(container.getBoundingClientRect().width);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const activeIds = new Set(entries.map((entry) => entry.id));
    setOverrides((current) => Object.fromEntries(Object.entries(current).filter(([id]) => activeIds.has(id))));
  }, [entries]);

  const effectiveWidth = Math.max(1, containerWidth);
  const layout = useMemo(() => packVisualGridItems(entries.map((entry) => {
    const maxSpan = entry.hints.maxSpan;
    const maxHeight = entry.hints.maxHeight;
    const span = overrides[entry.id]?.span ?? entry.hints.span ?? defaultSpan;
    const height = overrides[entry.id]?.height ?? entry.hints.height ?? defaultVisualGridHeight;
    return {
      id: entry.id,
      span: maxSpan ? Math.min(span, maxSpan) : span,
      height: maxHeight ? Math.min(height, maxHeight) : height,
    };
  }), effectiveWidth, visualGridGap), [defaultSpan, effectiveWidth, entries, overrides]);
  const positionById = useMemo(() => new Map(layout.positions.map((position) => [position.id, position])), [layout.positions]);

  const startResize = (id: string, direction: ResizeDirection, event: ReactPointerEvent<HTMLDivElement>) => {
    if (!editable) return;
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const position = positionById.get(id);
    if (!position) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const startWidth = position.width;
    const startHeight = position.height;
    const hints = entries.find((entry) => entry.id === id)?.hints;
    const minWidth = visualGridWidthForSpan(effectiveWidth, visualGridGap, 1);
    const hintMaxWidth = hints?.maxSpan ? visualGridWidthForSpan(effectiveWidth, visualGridGap, hints.maxSpan) : effectiveWidth;
    const edgeMaxWidth = direction.includes("west") ? position.x + startWidth : effectiveWidth - position.x;
    const maxWidth = Math.max(minWidth, Math.min(hintMaxWidth, edgeMaxWidth, effectiveWidth));
    const maxHeight = hints?.maxHeight ?? Number.POSITIVE_INFINITY;
    const minHeight = hints?.maxHeight ? minimumTextVisualGridHeight : minimumVisualGridHeight;
    let nextWidth = startWidth;
    let nextHeight = startHeight;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    document.body.style.cursor = resizeCursor(direction);
    document.body.style.userSelect = "none";
    setActiveItemId(id);

    const move = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId !== event.pointerId) return;
      const horizontal = direction.includes("east") || direction.includes("west");
      const vertical = direction.includes("north") || direction.includes("south");
      const widthDelta = direction.includes("west") ? startX - pointerEvent.clientX : pointerEvent.clientX - startX;
      const heightDelta = direction.includes("north") ? startY - pointerEvent.clientY : pointerEvent.clientY - startY;
      nextWidth = horizontal ? Math.min(maxWidth, Math.max(minWidth, startWidth + widthDelta)) : startWidth;
      nextHeight = vertical ? Math.min(maxHeight, Math.max(minHeight, startHeight + heightDelta)) : startHeight;
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = requestAnimationFrame(() => {
        const item = itemRefs.current.get(id);
        if (!item) return;
        const offsetX = direction.includes("west") ? startWidth - nextWidth : 0;
        const offsetY = direction.includes("north") ? startHeight - nextHeight : 0;
        item.style.width = `${nextWidth}px`;
        item.style.height = `${nextHeight}px`;
        item.style.transform = `translate3d(${position.x + offsetX}px, ${position.y + offsetY}px, 0)`;
        if (containerRef.current) containerRef.current.style.height = `${Math.max(layout.height, position.y + offsetY + nextHeight)}px`;
      });
    };
    const end = (pointerEvent?: PointerEvent) => {
      if (pointerEvent && pointerEvent.pointerId !== event.pointerId) return;
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      const nextSize = { span: visualGridSpanForWidth(effectiveWidth, visualGridGap, nextWidth), height: Math.round(nextHeight) };
      setOverrides((current) => ({ ...current, [id]: { ...current[id], ...nextSize } }));
      onLayoutChange?.(id, nextSize);
      setActiveItemId("");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  };

  return (
    <div
      ref={containerRef}
      className={`relative w-full overflow-x-hidden ${activeItemId ? "" : "transition-[height] duration-150 motion-reduce:transition-none"}`}
      style={{ height: layout.height }}
      data-resizable-visual-grid="true"
      data-visual-grid-count={entries.length}
      data-visual-grid-default={entries.length === 1 ? "full-width" : "two-per-row"}
      data-visual-grid-editable={editable ? "true" : "false"}
    >
      {entries.map(({ id, child }) => {
        const position = positionById.get(id);
        const span = position?.span ?? defaultSpan;
        const height = position?.height ?? defaultVisualGridHeight;
        const width = position?.width ?? visualGridWidthForSpan(effectiveWidth, visualGridGap, span);
        return (
          <div
            key={id}
            ref={(node) => { if (node) itemRefs.current.set(id, node); else itemRefs.current.delete(id); }}
            className={`group absolute left-0 top-0 ${activeItemId === id ? "z-20" : "z-0 transition-[transform,width,height] duration-150 motion-reduce:transition-none"}`}
            style={{ width, height, transform: `translate3d(${position?.x ?? 0}px, ${position?.y ?? 0}px, 0)` }}
            data-resizable-visual-item={id}
            data-visual-grid-span={span}
          >
            <div className="h-full min-h-0">{child}</div>
            {editable && <>
            <div role="separator" aria-label="从上边调整可视化高度" aria-orientation="horizontal" onPointerDown={(event) => startResize(id, "north", event)} className="absolute -top-1 left-3 right-3 z-40 h-2 cursor-ns-resize rounded-full opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[#178a53]/20" data-visual-resize-handle="north" />
            <div
              role="separator"
              aria-label="横向调整可视化宽度"
              aria-orientation="vertical"
              onPointerDown={(event) => startResize(id, "east", event)}
              className="absolute bottom-3 right-0 top-3 z-40 w-2 cursor-ew-resize touch-none rounded-full opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[#178a53]/20"
              data-visual-resize-handle="east"
            />
            <div role="separator" aria-label="从左边调整可视化宽度" aria-orientation="vertical" onPointerDown={(event) => startResize(id, "west", event)} className="absolute -left-1 bottom-3 top-3 z-40 w-2 cursor-ew-resize rounded-full opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[#178a53]/20" data-visual-resize-handle="west" />
            <div
              role="separator"
              aria-label="纵向调整可视化高度"
              aria-orientation="horizontal"
              onPointerDown={(event) => startResize(id, "south", event)}
              className="absolute -bottom-1 left-3 right-3 z-40 h-2 cursor-ns-resize rounded-full opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[#178a53]/20"
              data-visual-resize-handle="south"
            />
            <div role="separator" aria-label="从左上角调整可视化大小" onPointerDown={(event) => startResize(id, "northwest", event)} className="absolute -left-1.5 -top-1.5 z-50 h-4 w-4 cursor-nwse-resize opacity-0 group-hover:opacity-100" data-visual-resize-handle="northwest" />
            <div role="separator" aria-label="从右上角调整可视化大小" onPointerDown={(event) => startResize(id, "northeast", event)} className="absolute -right-1.5 -top-1.5 z-50 h-4 w-4 cursor-nesw-resize opacity-0 group-hover:opacity-100" data-visual-resize-handle="northeast" />
            <div role="separator" aria-label="从左下角调整可视化大小" onPointerDown={(event) => startResize(id, "southwest", event)} className="absolute -bottom-1.5 -left-1.5 z-50 h-4 w-4 cursor-nesw-resize opacity-0 group-hover:opacity-100" data-visual-resize-handle="southwest" />
            <div
              role="separator"
              aria-label="同时调整可视化宽度和高度"
              onPointerDown={(event) => startResize(id, "southeast", event)}
              className="absolute bottom-0 right-0 z-[60] h-6 w-6 cursor-nwse-resize touch-none rounded-br-xl border-b-2 border-r-2 border-transparent opacity-0 transition-opacity group-hover:border-[#178a53]/35 group-hover:opacity-100"
              data-visual-resize-handle="southeast"
            />
            </>}
          </div>
        );
      })}
    </div>
  );
}

function gridHintsFromChild(props: unknown) {
  const record = props && typeof props === "object" ? props as Record<string, unknown> : {};
  return {
    span: numberHint(record["data-visual-grid-span"] ?? record.visualGridSpan),
    height: numberHint(record["data-visual-grid-height"] ?? record.visualGridHeight),
    maxSpan: numberHint(record["data-visual-grid-max-span"] ?? record.visualGridMaxSpan),
    maxHeight: numberHint(record["data-visual-grid-max-height"] ?? record.visualGridMaxHeight),
  };
}

function numberHint(value: unknown) {
  const next = Number(value);
  return Number.isFinite(next) && next > 0 ? next : undefined;
}

function resizeCursor(direction: ResizeDirection) {
  if (direction === "east" || direction === "west") return "ew-resize";
  if (direction === "north" || direction === "south") return "ns-resize";
  return direction === "northeast" || direction === "southwest" ? "nesw-resize" : "nwse-resize";
}
