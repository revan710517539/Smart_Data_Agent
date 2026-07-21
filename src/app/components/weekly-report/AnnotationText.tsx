import type { ReactNode } from "react";
import type { CommentItem } from "./domain";

export function renderAnnotatedText(
  text: string,
  annotations: CommentItem[],
  highlightedAnnotationId: string | null,
  onAnnotationClick: (annotationId: string, rect?: DOMRect) => void,
) {
  if (!text) return <br />;
  const sortedAnnotations = resolveAnnotations(text, annotations);
  if (!sortedAnnotations.length) return text;

  const parts: ReactNode[] = [];
  let cursor = 0;
  sortedAnnotations.forEach(({ annotation, start: resolvedStart, end: resolvedEnd }) => {
    const start = Math.max(cursor, resolvedStart);
    const end = Math.min(text.length, resolvedEnd);
    if (start > cursor) parts.push(<span key={`text_${cursor}_${start}`}>{text.slice(cursor, start)}</span>);
    if (end > start) {
      const highlighted = highlightedAnnotationId === annotation.id;
      const analysisAnnotation = annotation.annotationKind === "analysis";
      parts.push(
        <span
          key={`${annotation.id}_${start}_${end}`}
          role="button"
          tabIndex={0}
          contentEditable={false}
          data-analysis-annotation={analysisAnnotation ? annotation.id : undefined}
          data-comment-annotation={analysisAnnotation ? undefined : annotation.id}
          onMouseDown={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onAnnotationClick(annotation.id, event.currentTarget.getBoundingClientRect());
          }}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            event.stopPropagation();
            onAnnotationClick(annotation.id, event.currentTarget.getBoundingClientRect());
          }}
          className={`cursor-pointer rounded-sm border-b-2 px-0.5 pb-[1px] underline decoration-2 underline-offset-[3px] transition-colors ${annotationClassName(analysisAnnotation, highlighted)}`}
        >
          {text.slice(start, end)}
        </span>,
      );
    }
    cursor = Math.max(cursor, end);
  });
  if (cursor < text.length) parts.push(<span key={`text_${cursor}_end`}>{text.slice(cursor)}</span>);
  return parts;
}

export function renderAnnotatedSvgText(
  text: string,
  annotations: CommentItem[],
  highlightedAnnotationId: string | null,
  onAnnotationClick: (annotationId: string, rect?: DOMRect) => void,
) {
  if (!text) return null;
  const sortedAnnotations = resolveAnnotations(text, annotations);
  if (!sortedAnnotations.length) return text;

  const parts: ReactNode[] = [];
  let cursor = 0;
  sortedAnnotations.forEach(({ annotation, start: resolvedStart, end: resolvedEnd }) => {
    const start = Math.max(cursor, resolvedStart);
    const end = Math.min(text.length, resolvedEnd);
    if (start > cursor) parts.push(<tspan key={`text_${cursor}_${start}`}>{text.slice(cursor, start)}</tspan>);
    if (end > start) {
      const analysisAnnotation = annotation.annotationKind === "analysis";
      const highlighted = highlightedAnnotationId === annotation.id;
      const color = analysisAnnotation ? highlighted ? "#d70015" : "#ff3b30" : highlighted ? "#0b57d0" : "#1a73e8";
      parts.push(
        <tspan
          key={annotation.id}
          fill={color}
          data-analysis-annotation={analysisAnnotation ? annotation.id : undefined}
          data-comment-annotation={analysisAnnotation ? undefined : annotation.id}
          onMouseDown={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onAnnotationClick(annotation.id, event.currentTarget.getBoundingClientRect());
          }}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
          }}
          style={{ cursor: "pointer", textDecorationLine: "underline", textDecorationColor: color, textDecorationThickness: "2px" }}
        >
          {text.slice(start, end)}
        </tspan>,
      );
    }
    cursor = Math.max(cursor, end);
  });
  if (cursor < text.length) parts.push(<tspan key={`text_${cursor}_end`}>{text.slice(cursor)}</tspan>);
  return parts;
}

function resolveAnnotations(text: string, annotations: CommentItem[]) {
  return annotations
    .map((annotation) => {
      const range = resolveAnnotationRange(text, annotation);
      return range ? { annotation, ...range } : null;
    })
    .filter((annotation): annotation is { annotation: CommentItem; start: number; end: number } => Boolean(annotation))
    .sort((left, right) => left.start - right.start || left.end - right.end);
}

function resolveAnnotationRange(text: string, annotation: CommentItem) {
  const selectedText = annotation.selectedText?.trim();
  const rangeStart = typeof annotation.rangeStart === "number" ? annotation.rangeStart : -1;
  const rangeEnd = typeof annotation.rangeEnd === "number" ? annotation.rangeEnd : -1;
  const hasValidRange = rangeStart >= 0 && rangeEnd > rangeStart && rangeStart < text.length;
  if (hasValidRange) {
    const clampedEnd = Math.min(text.length, rangeEnd);
    const rangeText = text.slice(rangeStart, clampedEnd);
    if (!selectedText || rangeText === selectedText || rangeText.trim() === selectedText) return { start: rangeStart, end: clampedEnd };
    const offset = rangeText.indexOf(selectedText);
    if (offset >= 0) return { start: rangeStart + offset, end: rangeStart + offset + selectedText.length };
  }
  if (selectedText) {
    const nearStart = hasValidRange ? Math.max(0, rangeStart - 12) : 0;
    const nearIndex = text.indexOf(selectedText, nearStart);
    if (nearIndex >= 0) return { start: nearIndex, end: nearIndex + selectedText.length };
    const fallbackIndex = text.indexOf(selectedText);
    if (fallbackIndex >= 0) return { start: fallbackIndex, end: fallbackIndex + selectedText.length };
  }
  return hasValidRange ? { start: rangeStart, end: Math.min(text.length, rangeEnd) } : null;
}

function annotationClassName(analysis: boolean, highlighted: boolean) {
  if (analysis) {
    return highlighted
      ? "border-[#d70015] bg-[#ffe5e5] text-[#d70015] decoration-[#d70015]"
      : "border-[#ff3b30] bg-[#fff1f0] text-[#d70015] decoration-[#ff3b30]";
  }
  return highlighted
    ? "border-[#0b57d0] bg-[#dce9ff] text-[#0b57d0] decoration-[#0b57d0]"
    : "border-[#1a73e8] bg-[#eef4ff] text-[#1a73e8] decoration-[#1a73e8]";
}
