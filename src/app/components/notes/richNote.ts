import type { CSSProperties } from "react";
import { highlightNoteText, type NoteFieldTerm } from "../visualization/noteHighlights";

export type RichNoteItem =
  | { id: string; type: "paragraph"; text: string; html?: string }
  | {
      id: string;
      type: "image";
      src: string;
      name: string;
      attachmentId?: string;
      artifactId?: string;
      contentHash?: string;
      width?: number;
      height?: number;
    };

export type StickyNoteRecord = {
  visible: boolean;
  items: RichNoteItem[];
  updatedAt: string;
};

export type StickyNoteSurface =
  | "dashboard"
  | "institution_supervision"
  | "weekly_report"
  | `visual_report:${string}`
  | `self_analysis:${string}`;

export const STICKY_NOTE_CHANGED_EVENT = "smart-data-agent-sticky-note-changed";

export const NOTE_TEXT_CLASS = "break-words text-[16px] leading-[26px] tracking-[-0.31px] text-[#1d1d1f]";
export const NOTE_EDITOR_SURFACE_CLASS = "cursor-text rounded-lg border border-[#dce7df] bg-white p-5";
export const NOTE_PARAGRAPH_STACK_CLASS = "flex h-full min-h-0 flex-col gap-[10px]";
export const NOTE_TEXT_STYLE: CSSProperties = {
  fontSize: "16px",
  lineHeight: "26px",
  letterSpacing: "-0.31px",
  color: "#1d1d1f",
  WebkitTextFillColor: "#1d1d1f",
};

export function emptyStickyNote(): StickyNoteRecord {
  return { visible: false, items: [emptyParagraph("sticky")], updatedAt: "" };
}

export function emptyParagraph(prefix = "note"): Extract<RichNoteItem, { type: "paragraph" }> {
  return { id: makeNoteId(prefix), type: "paragraph", text: "", html: "" };
}

export function makeNoteId(prefix: string) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function noteItemsFromText(text: string, prefix = "note"): RichNoteItem[] {
  return [{ id: makeNoteId(prefix), type: "paragraph", text: text || "", html: text ? escapeHtml(text).replace(/\n/g, "<br>") : "" }];
}

export function serializeNoteItems(items: RichNoteItem[]) {
  return items.map((item) => (item.type === "paragraph" ? item.text : `[图片：${item.name}]`)).join("\n");
}

export function noteHasContent(items: RichNoteItem[]) {
  return items.some((item) => (item.type === "image" ? Boolean(item.src) : Boolean(item.text.trim())));
}

export function normalizeStickyNote(value: unknown): StickyNoteRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) return emptyStickyNote();
  const record = value as Record<string, unknown>;
  const items = normalizeNoteItems(record.items);
  return {
    visible: Boolean(record.visible),
    items: items.length ? items : [emptyParagraph("sticky")],
    updatedAt: typeof record.updatedAt === "string" ? record.updatedAt : "",
  };
}

export function normalizeNoteItems(value: unknown): RichNoteItem[] {
  if (!Array.isArray(value)) return [];
  const items: RichNoteItem[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    const id = typeof record.id === "string" ? record.id.trim() : "";
    if (!id) continue;
    if (record.type === "image") {
      items.push({
        id,
        type: "image",
        src: typeof record.src === "string" ? record.src : "",
        name: typeof record.name === "string" && record.name.trim() ? record.name : "粘贴图片",
        attachmentId: typeof record.attachmentId === "string" ? record.attachmentId : undefined,
        artifactId: typeof record.artifactId === "string" ? record.artifactId : undefined,
        contentHash: typeof record.contentHash === "string" ? record.contentHash : undefined,
        width: numberOrUndefined(record.width),
        height: numberOrUndefined(record.height),
      });
      continue;
    }
    if (record.type === "paragraph") {
      const text = typeof record.text === "string" ? record.text : "";
      const html = typeof record.html === "string" ? sanitizeNoteHtml(record.html) : "";
      items.push({ id, type: "paragraph", text, html });
    }
  }
  return items;
}

export function localStickyNoteKey(surface: string) {
  return `sda:sticky-note:v1:${surface}`;
}

export function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function unescapeHtml(value: string) {
  return value
    .replace(/&nbsp;/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/&amp;/g, "&");
}

export function sanitizeNoteHtml(html: string) {
  const raw = html || "";
  if (typeof DOMParser === "undefined") {
    return raw
      .replace(/<\s*br\s*\/?\s*>/gi, "<br>")
      .replace(/<\s*\/\s*(b|strong)\s*>/gi, "</strong>")
      .replace(/<\s*(b|strong)(?:\s[^>]*)?>/gi, "<strong>")
      .replace(/<\/?(?!strong\b|br\b)[a-zA-Z0-9]+(?:\s[^>]*)?>/gi, "");
  }
  const parsed = new DOMParser().parseFromString(`<div>${raw}</div>`, "text/html");
  const root = parsed.body.firstElementChild;
  if (!root) return "";
  return serializeSanitizedNodes(Array.from(root.childNodes));
}

export function htmlToPlainText(html: string) {
  return unescapeHtml(
    sanitizeNoteHtml(html)
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/?strong>/gi, ""),
  );
}

export function paragraphToHtml(item: { text: string; html?: string }) {
  if (item.html && item.html.trim()) return sanitizeNoteHtml(item.html);
  return escapeHtml(item.text || "").replace(/\n/g, "<br>");
}

export function highlightSanitizedHtml(html: string, terms: NoteFieldTerm[]) {
  const sanitized = sanitizeNoteHtml(html);
  if (!terms.length) return sanitized;
  return sanitized.replace(/([^<]+)|(<[^>]+>)/g, (chunk, text: string | undefined, tag: string | undefined) => {
    if (tag) return tag;
    const decoded = unescapeHtml(text || "");
    return highlightNoteText(decoded, terms).map((part) => {
      if (!part.term) return escapeHtml(part.text);
      return `<strong data-visual-note-term="${escapeAttr(part.term.kind)}" data-visual-note-field="${escapeAttr(part.term.field)}" class="font-semibold underline decoration-2 underline-offset-2" style="color:${part.term.color}">${escapeHtml(part.text)}</strong>`;
    }).join("");
  });
}

export function toggleSelectionBold() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
  document.execCommand("bold");
  return true;
}

export function selectedTextWithin(root: HTMLElement | null) {
  const selection = window.getSelection();
  if (!root || !selection || selection.isCollapsed || !selection.rangeCount) return "";
  const range = selection.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return "";
  return selection.toString().trim();
}

export function selectionOffsetsWithin(root: HTMLElement, fallbackLength: number) {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount || !root.contains(selection.anchorNode)) {
    return { start: fallbackLength, end: fallbackLength };
  }
  const range = selection.getRangeAt(0);
  const before = document.createRange();
  before.selectNodeContents(root);
  before.setEnd(range.startContainer, range.startOffset);
  const start = before.toString().length;
  return { start, end: start + range.toString().length };
}

export function placeCaretAtStart(element: HTMLElement | null) {
  placeCaretCollapsed(element, true);
}

export function placeCaretAtEnd(element: HTMLElement | null) {
  placeCaretCollapsed(element, false);
}

export function placeCaretFromPoint(element: HTMLElement | null, clientX: number, clientY: number) {
  if (!element) return;
  const documentWithCaret = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  };
  const pointRange = documentWithCaret.caretRangeFromPoint?.(clientX, clientY);
  const pointPosition = !pointRange ? documentWithCaret.caretPositionFromPoint?.(clientX, clientY) : null;
  const selection = window.getSelection();
  if (!selection) return;
  if (pointRange && element.contains(pointRange.startContainer)) {
    selection.removeAllRanges();
    selection.addRange(pointRange);
    return;
  }
  if (pointPosition?.offsetNode && element.contains(pointPosition.offsetNode)) {
    const range = document.createRange();
    range.setStart(pointPosition.offsetNode, pointPosition.offset);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    return;
  }
  placeCaretAtEnd(element);
}

function placeCaretCollapsed(element: HTMLElement | null, start: boolean) {
  if (!element) return;
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(element);
  range.collapse(start);
  selection.removeAllRanges();
  selection.addRange(range);
}

function serializeSanitizedNodes(nodes: Node[]) {
  return nodes.map((node) => serializeSanitizedNode(node)).join("");
}

function serializeSanitizedNode(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return escapeHtml(node.textContent || "");
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const element = node as HTMLElement;
  const tag = element.tagName;
  if (tag === "BR") return "<br>";
  const inner = serializeSanitizedNodes(Array.from(element.childNodes));
  if (tag === "STRONG" || tag === "B") return `<strong>${inner}</strong>`;
  if (tag === "DIV" || tag === "P" || tag === "LI") return `${inner}<br>`;
  return inner;
}

function escapeAttr(value: string) {
  return escapeHtml(value).replace(/'/g, "&#39;");
}

function numberOrUndefined(value: unknown) {
  const next = Number(value);
  return Number.isFinite(next) && next > 0 ? next : undefined;
}
