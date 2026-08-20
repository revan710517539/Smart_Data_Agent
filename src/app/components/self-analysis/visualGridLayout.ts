export const visualGridColumnCount = 12;

export type VisualGridSize = {
  span: number;
  height: number;
};

export type VisualGridPosition = VisualGridSize & {
  id: string;
  x: number;
  y: number;
  width: number;
};

export function defaultVisualGridSpan(itemCount: number) {
  return itemCount === 1 ? visualGridColumnCount : visualGridColumnCount / 2;
}

export function visualGridWidthForSpan(containerWidth: number, gap: number, span: number) {
  const boundedSpan = Math.max(1, Math.min(visualGridColumnCount, Math.round(span)));
  const columnWidth = Math.max(0, (containerWidth - gap * (visualGridColumnCount - 1)) / visualGridColumnCount);
  return columnWidth * boundedSpan + gap * (boundedSpan - 1);
}

export function visualGridSpanForWidth(containerWidth: number, gap: number, width: number, minimumSpan = 4) {
  const columnWidth = Math.max(1, (containerWidth - gap * (visualGridColumnCount - 1)) / visualGridColumnCount);
  const requested = Math.round((Math.max(0, width) + gap) / (columnWidth + gap));
  return Math.max(minimumSpan, Math.min(visualGridColumnCount, requested));
}

export function visualDuplicateLayout(sourceId: string) {
  const size = readVisualGridItemSize(sourceId);
  return {
    layoutSpan: size?.span,
    layoutHeight: size?.height,
    maxLayoutSpan: size?.span,
    maxLayoutHeight: size?.height,
  };
}

export function readVisualGridItemSize(id: string) {
  const item = document.querySelector<HTMLElement>(`[data-resizable-visual-item="${CSS.escape(id)}"]`);
  if (!item) return null;
  const span = Number(item.dataset.visualGridSpan);
  return {
    span: Number.isFinite(span) && span > 0 ? span : undefined,
    height: item.offsetHeight || undefined,
    width: item.offsetWidth || undefined,
  };
}

export function packVisualGridItems(
  items: Array<{ id: string; span: number; height: number }>,
  containerWidth: number,
  gap: number,
) {
  const skyline = Array.from({ length: visualGridColumnCount }, () => 0);
  const positions: VisualGridPosition[] = [];

  for (const item of items) {
    const span = Math.max(1, Math.min(visualGridColumnCount, Math.round(item.span)));
    let selectedColumn = 0;
    let selectedTop = Number.POSITIVE_INFINITY;

    for (let column = 0; column <= visualGridColumnCount - span; column += 1) {
      const candidateTop = Math.max(...skyline.slice(column, column + span));
      if (candidateTop < selectedTop) {
        selectedTop = candidateTop;
        selectedColumn = column;
      }
    }

    const columnStride = (containerWidth + gap) / visualGridColumnCount;
    const width = visualGridWidthForSpan(containerWidth, gap, span);
    const height = Math.max(1, item.height);
    positions.push({
      id: item.id,
      span,
      height,
      width,
      x: selectedColumn * columnStride,
      y: selectedTop,
    });

    const nextTop = selectedTop + height + gap;
    for (let column = selectedColumn; column < selectedColumn + span; column += 1) skyline[column] = nextTop;
  }

  return {
    positions,
    height: positions.length ? Math.max(...positions.map((position) => position.y + position.height)) : 0,
  };
}
