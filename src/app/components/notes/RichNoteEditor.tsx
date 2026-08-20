import { useEffect, useRef, useState, type ClipboardEvent, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { ArrowDown, ArrowUp, Bold, MessageSquareText, Sparkles } from "lucide-react";
import { fetchReportImageObjectUrl, uploadReportImage } from "../../services/reportAttachmentApi";
import { type NoteFieldTerm } from "../visualization/noteHighlights";
import {
  NOTE_EDITOR_SURFACE_CLASS,
  NOTE_PARAGRAPH_STACK_CLASS,
  NOTE_TEXT_CLASS,
  NOTE_TEXT_STYLE,
  emptyParagraph,
  highlightSanitizedHtml,
  htmlToPlainText,
  makeNoteId,
  paragraphToHtml,
  placeCaretFromPoint,
  placeCaretAtStart,
  sanitizeNoteHtml,
  selectedTextWithin,
  selectionOffsetsWithin,
  toggleSelectionBold,
  type RichNoteItem,
} from "./richNote";

export type RichNoteUploadContext = {
  tenantId: string;
  userId: string;
  reportId: string;
  blockId?: string;
};

export function RichNoteEditor({
  items,
  onChange,
  placeholder = "输入文字，或直接粘贴图片…",
  uploadContext,
  terms = [],
  readOnly = false,
  minHeightClass = "min-h-[120px]",
  onOpenComment,
  onOpenAnalysis,
}: {
  items: RichNoteItem[];
  onChange: (items: RichNoteItem[]) => void;
  placeholder?: string;
  uploadContext: RichNoteUploadContext;
  terms?: NoteFieldTerm[];
  readOnly?: boolean;
  minHeightClass?: string;
  onOpenComment?: (selectedText: string) => void;
  onOpenAnalysis?: (selectedText: string) => void;
}) {
  const resolved = items.length ? items : [emptyParagraph("note")];

  const commit = (next: RichNoteItem[]) => {
    onChange(next.length ? next : [emptyParagraph("note")]);
  };

  const updateParagraph = (index: number, next: { text: string; html: string }) => {
    const copy = [...resolved];
    const current = copy[index];
    if (!current || current.type !== "paragraph") return;
    copy[index] = { ...current, text: next.text, html: next.html };
    commit(copy);
  };

  const pasteImagesAtCursor = async (
    event: ClipboardEvent<HTMLElement>,
    index: number,
    item: Extract<RichNoteItem, { type: "paragraph" }>,
  ) => {
    const files = Array.from(event.clipboardData.items)
      .filter((entry) => entry.type.startsWith("image/"))
      .map((entry) => entry.getAsFile())
      .filter((file): file is File => Boolean(file));
    if (!files.length) return;
    event.preventDefault();
    const editor = event.currentTarget;
    const offsets = selectionOffsetsWithin(editor, item.text.length);
    const beforeText = item.text.slice(0, offsets.start);
    const afterText = item.text.slice(offsets.end);
    const editorWidth = editor.closest<HTMLElement>("[data-rich-note-editor]")?.clientWidth || editor.clientWidth || 560;
    const maxImageWidth = Math.max(220, Math.min(editorWidth - 12, 680));
    const imageItems = await Promise.all(files.map((file) => createNoteImageItem(file, maxImageWidth, uploadContext)));
    const afterId = makeNoteId("note_line");
    const replacement: RichNoteItem[] = [
      ...(beforeText.length ? [{ ...item, text: beforeText, html: escapeTextAsHtml(beforeText) }] : []),
      ...imageItems,
      { id: afterId, type: "paragraph", text: afterText, html: escapeTextAsHtml(afterText) },
    ];
    const next = [...resolved];
    next.splice(index, 1, ...replacement);
    commit(next);
    window.setTimeout(() => {
      const nextEditor = document.querySelector(`[data-rich-note-editor-id="${afterId}"]`) as HTMLElement | null;
      nextEditor?.focus();
      placeCaretAtStart(nextEditor);
    }, 0);
  };

  const moveItem = (fromIndex: number, toIndex: number) => {
    if (toIndex < 0 || toIndex >= resolved.length || fromIndex === toIndex) return;
    const next = [...resolved];
    const [item] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, item);
    commit(next);
  };

  const resizeImage = (index: number, size: { width?: number; height?: number }) => {
    const next = [...resolved];
    const item = next[index];
    if (!item || item.type !== "image") return;
    next[index] = { ...item, ...size };
    commit(next);
  };

  const deleteItem = (index: number) => {
    commit(resolved.filter((_, itemIndex) => itemIndex !== index));
  };

  const insertBlankAroundImage = (index: number, position: "before" | "after") => {
    const insertionIndex = position === "before" ? index : index + 1;
    const existing = resolved[insertionIndex];
    const paragraphId = existing?.type === "paragraph" && !existing.text.trim() ? existing.id : makeNoteId("note_line");
    if (!(existing?.type === "paragraph" && !existing.text.trim())) {
      const next = [...resolved];
      next.splice(insertionIndex, 0, { id: paragraphId, type: "paragraph", text: "", html: "" });
      commit(next);
    }
    window.setTimeout(() => {
      const editor = document.querySelector(`[data-rich-note-editor-id="${paragraphId}"]`) as HTMLElement | null;
      editor?.focus();
      placeCaretAtStart(editor);
    }, 0);
  };

  const lastParagraphIndex = resolved.reduce((found, item, index) => (item.type === "paragraph" ? index : found), -1);

  return (
    <div
      className={`${NOTE_EDITOR_SURFACE_CLASS} ${NOTE_PARAGRAPH_STACK_CLASS} ${minHeightClass}`}
      data-rich-note-editor="true"
      data-rich-note-readonly={readOnly ? "true" : "false"}
      onMouseDown={(event) => {
        if (readOnly) return;
        const target = event.target as HTMLElement;
        if (target.closest('[contenteditable="true"], button, img, [data-rich-note-image], [data-visual-note-selection]')) return;
        event.preventDefault();
        const editors = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[contenteditable="true"]'));
        const editor = editors[editors.length - 1];
        editor?.focus();
        placeCaretFromPoint(editor, event.clientX, event.clientY);
      }}
    >
      {resolved.map((item, index) => (
        <div key={item.id} className={item.type === "paragraph" && index === lastParagraphIndex ? "relative flex min-h-0 flex-1 flex-col" : "relative"}>
          {item.type === "paragraph" ? (
            <NoteParagraphField
              item={item}
              placeholder={index === 0 ? placeholder : ""}
              terms={terms}
              readOnly={readOnly}
              fillHeight={index === lastParagraphIndex}
              onChange={(next) => updateParagraph(index, next)}
              onPasteImages={(event) => void pasteImagesAtCursor(event, index, item)}
              onOpenComment={onOpenComment}
              onOpenAnalysis={onOpenAnalysis}
            />
          ) : (
            <NoteImage
              item={item}
              index={index}
              total={resolved.length}
              readOnly={readOnly}
              onMove={moveItem}
              onResize={(size) => resizeImage(index, size)}
              onDelete={() => deleteItem(index)}
              onInsertBlank={(position) => insertBlankAroundImage(index, position)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function NoteParagraphField({
  item,
  placeholder,
  terms = [],
  readOnly,
  autoFocus = false,
  fillHeight = false,
  editorId = item.id,
  identityAttr = "data-rich-note-editor-id",
  onChange,
  onPasteImages,
  onOpenComment,
  onOpenAnalysis,
}: {
  item: { id: string; text: string; html?: string };
  placeholder: string;
  terms?: NoteFieldTerm[];
  readOnly: boolean;
  autoFocus?: boolean;
  fillHeight?: boolean;
  editorId?: string;
  identityAttr?: "data-rich-note-editor-id" | "data-comment-editor-id";
  onChange: (next: { text: string; html: string }) => void;
  onPasteImages?: (event: ClipboardEvent<HTMLElement>) => void;
  onOpenComment?: (selectedText: string) => void;
  onOpenAnalysis?: (selectedText: string) => void;
}) {
  const editorRef = useRef<HTMLDivElement>(null);
  const [actionMenu, setActionMenu] = useState<{ x: number; y: number; text: string } | null>(null);
  const html = paragraphToHtml(item);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || readOnly) return;
    if (document.activeElement === editor) return;
    if (editor.innerHTML !== html) editor.innerHTML = html || "";
  }, [html, item.id, readOnly]);

  useEffect(() => {
    if (!autoFocus || readOnly) return;
    const editor = editorRef.current;
    editor?.focus();
    placeCaretAtStart(editor);
  }, [autoFocus, readOnly]);

  const emit = () => {
    const editor = editorRef.current;
    if (!editor) return;
    const nextHtml = sanitizeNoteHtml(editor.innerHTML);
    const nextText = htmlToPlainText(nextHtml);
    if (nextHtml === (item.html || "") && nextText === item.text) return;
    onChange({ text: nextText, html: nextHtml });
  };

  const applyBold = () => {
    editorRef.current?.focus();
    toggleSelectionBold();
    emit();
  };

  const captureSelectionActions = () => {
    const editor = editorRef.current;
    if (!editor) {
      setActionMenu(null);
      return;
    }
    const text = selectedTextWithin(editor);
    if (!text) {
      setActionMenu(null);
      return;
    }
    const rect = editor.getBoundingClientRect();
    const selection = window.getSelection();
    const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
    const caret = range?.getBoundingClientRect();
    setActionMenu({
      text,
      x: caret ? Math.min(Math.max(8, caret.left - rect.left), Math.max(8, rect.width - 168)) : 8,
      y: caret ? Math.max(8, caret.top - rect.top - 36) : 8,
    });
  };

  if (readOnly) {
    if (!item.text && !item.html) {
      return (
        <div className={`min-h-[26px] ${NOTE_TEXT_CLASS}`} style={NOTE_TEXT_STYLE} data-rich-note-view-paragraph={item.id}>
          {placeholder ? <span className="text-[#c4c4c8]">{placeholder}</span> : null}
        </div>
      );
    }
    return (
      <div
        className={`min-h-[26px] ${NOTE_TEXT_CLASS}`}
        style={NOTE_TEXT_STYLE}
        data-rich-note-view-paragraph={item.id}
        dangerouslySetInnerHTML={{ __html: highlightSanitizedHtml(html, terms) }}
      />
    );
  }

  return (
    <div className={fillHeight ? "relative flex min-h-[26px] flex-1 flex-col" : "relative"}>
      {!item.text && placeholder ? (
        <span className="pointer-events-none absolute left-0 top-0 text-[16px] leading-[26px] tracking-[-0.31px] text-[#c4c4c8]">{placeholder}</span>
      ) : null}
      <div
        ref={editorRef}
        role="textbox"
        suppressContentEditableWarning
        aria-label="便签正文"
        data-visual-note-body={item.id.startsWith("note_title") ? undefined : "true"}
        data-rich-note-editor-id={identityAttr === "data-rich-note-editor-id" ? editorId : undefined}
        data-comment-editor-id={identityAttr === "data-comment-editor-id" ? editorId : undefined}
        contentEditable="true"
        onInput={emit}
        onBlur={emit}
        onPaste={(event) => {
          const hasImage = Array.from(event.clipboardData.items).some((entry) => entry.type.startsWith("image/"));
          if (hasImage) {
            onPasteImages?.(event);
            return;
          }
          event.preventDefault();
          const text = event.clipboardData.getData("text/plain");
          document.execCommand("insertText", false, text);
          emit();
        }}
        onMouseUp={captureSelectionActions}
        onKeyUp={captureSelectionActions}
        onKeyDown={(event: ReactKeyboardEvent<HTMLDivElement>) => {
          if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
            event.preventDefault();
            applyBold();
          }
        }}
        className={`relative z-10 bg-transparent outline-none selection:bg-[#dce9ff]/80 ${fillHeight ? "min-h-full flex-1" : "min-h-[26px]"} ${NOTE_TEXT_CLASS}`}
        style={NOTE_TEXT_STYLE}
      />
      {actionMenu ? (
        <div className="absolute z-20 flex overflow-hidden rounded-full border border-[#e5e5ea] bg-white shadow-lg shadow-black/10" style={{ top: actionMenu.y, left: actionMenu.x }} data-visual-note-selection="true">
          {onOpenComment ? <button type="button" className="flex h-8 items-center gap-1 px-2.5 text-[11px] text-[#636366] hover:bg-[#f2f2f7]" onMouseDown={(event) => event.preventDefault()} onClick={() => { onOpenComment(actionMenu.text); setActionMenu(null); }}><MessageSquareText className="h-3.5 w-3.5" />评论</button> : null}
          <button type="button" className={`flex h-8 items-center gap-1 px-2.5 text-[11px] text-[#636366] hover:bg-[#f2f2f7] ${onOpenComment ? "border-l border-[#ececf0]" : ""}`} data-note-bold-action="true" onMouseDown={(event) => event.preventDefault()} onClick={() => { applyBold(); setActionMenu(null); }}><Bold className="h-3.5 w-3.5" />加粗</button>
          {onOpenAnalysis ? <button type="button" className="flex h-8 items-center gap-1 border-l border-[#ececf0] px-2.5 text-[11px] text-[#636366] hover:bg-[#f2f2f7]" onMouseDown={(event) => event.preventDefault()} onClick={() => { onOpenAnalysis(actionMenu.text); setActionMenu(null); }}><Sparkles className="h-3.5 w-3.5" />AI 分析</button> : null}
        </div>
      ) : null}
    </div>
  );
}

function NoteImage({
  item,
  index,
  total,
  readOnly,
  onMove,
  onResize,
  onDelete,
  onInsertBlank,
}: {
  item: Extract<RichNoteItem, { type: "image" }>;
  index: number;
  total: number;
  readOnly: boolean;
  onMove: (fromIndex: number, toIndex: number) => void;
  onResize: (size: { width?: number; height?: number }) => void;
  onDelete: () => void;
  onInsertBlank: (position: "before" | "after") => void;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [deleteMenu, setDeleteMenu] = useState<{ x: number; y: number } | null>(null);
  const [authorizedImageSrc, setAuthorizedImageSrc] = useState("");

  useEffect(() => {
    if (!item.attachmentId) {
      setAuthorizedImageSrc("");
      return;
    }
    let disposed = false;
    let objectUrl = "";
    void fetchReportImageObjectUrl({ attachmentId: item.attachmentId })
      .then((url) => {
        objectUrl = url;
        if (!disposed) setAuthorizedImageSrc(url);
      })
      .catch(() => {
        if (!disposed) setAuthorizedImageSrc("");
      });
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [item.attachmentId]);

  useEffect(() => {
    if (!deleteMenu) return;
    const close = () => setDeleteMenu(null);
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [deleteMenu]);

  const startResize = (edge: "top-right" | "bottom-right", event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const frame = frameRef.current;
    if (!frame) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const frameRect = frame.getBoundingClientRect();
    const startWidth = frameRect.width;
    const startHeight = imageRef.current?.getBoundingClientRect().height || item.height || 220;
    const maxWidth = frame.parentElement?.clientWidth || 760;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = edge === "top-right" ? "nesw-resize" : "nwse-resize";
    document.body.style.userSelect = "none";
    const move = (pointerEvent: PointerEvent) => {
      const width = Math.max(120, Math.min(Math.round(startWidth + pointerEvent.clientX - startX), maxWidth));
      const height = Math.max(96, Math.min(Math.round(edge === "top-right" ? startHeight + startY - pointerEvent.clientY : startHeight + pointerEvent.clientY - startY), 520));
      onResize({ width, height });
    };
    const end = () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", end);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
  };

  const openDeleteMenu = (event: ReactMouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    setDeleteMenu({
      x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 84)),
      y: Math.max(8, event.clientY - rect.top),
    });
  };

  return (
    <div className="group/image-gap relative py-2" data-rich-note-image={item.id}>
      {!readOnly && <button type="button" aria-label="在图片上方插入空白行" onClick={() => onInsertBlank("before")} className="absolute inset-x-0 top-0 z-20 h-2 cursor-text rounded-full bg-transparent hover:bg-[#dce9ff]" />}
      <div ref={frameRef} onContextMenu={readOnly ? undefined : openDeleteMenu} className="group/image relative max-w-full rounded-xl border border-[#e5e5ea] bg-white p-1" style={{ width: item.width ? `${item.width}px` : "100%" }}>
        {!readOnly && (
          <div className="absolute right-2 top-2 z-40 flex items-center gap-1 opacity-0 transition-opacity group-hover/image:opacity-100">
            <button type="button" onClick={() => onMove(index, index - 1)} disabled={index === 0} className="flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] bg-white/95 text-[#636366] disabled:opacity-30" aria-label="上移图片"><ArrowUp className="h-3.5 w-3.5" /></button>
            <button type="button" onClick={() => onMove(index, index + 1)} disabled={index === total - 1} className="flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] bg-white/95 text-[#636366] disabled:opacity-30" aria-label="下移图片"><ArrowDown className="h-3.5 w-3.5" /></button>
          </div>
        )}
        <img ref={imageRef} src={authorizedImageSrc || item.src} alt={item.name} className="block w-full select-none rounded-[10px] bg-white object-contain" style={{ height: item.height ? `${item.height}px` : "auto", maxHeight: item.height ? undefined : "260px" }} draggable={false} />
        {!readOnly && (
          <>
            <button type="button" onPointerDown={(event) => startResize("top-right", event)} className="absolute right-0 top-0 z-30 h-4 w-4 cursor-nesw-resize rounded-bl-lg rounded-tr-xl bg-white/70 opacity-0 group-hover/image:opacity-100" aria-label="拖动右上角调整图片宽高" />
            <button type="button" onPointerDown={(event) => startResize("bottom-right", event)} className="absolute bottom-0 right-0 z-30 h-4 w-4 cursor-nwse-resize rounded-br-xl rounded-tl-lg bg-white/70 opacity-0 group-hover/image:opacity-100" aria-label="拖动右下角调整图片宽高" />
          </>
        )}
        {deleteMenu && (
          <div className="absolute z-30 w-20 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg" style={{ left: deleteMenu.x, top: deleteMenu.y }} onPointerDown={(event) => event.stopPropagation()}>
            <button type="button" onClick={() => { setDeleteMenu(null); onDelete(); }} className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#d92d20] hover:bg-[#fff1f0]">删除</button>
          </div>
        )}
      </div>
      {!readOnly && <button type="button" aria-label="在图片下方插入空白行" onClick={() => onInsertBlank("after")} className="absolute inset-x-0 bottom-0 z-20 h-2 cursor-text rounded-full bg-transparent hover:bg-[#dce9ff]" />}
    </div>
  );
}

async function createNoteImageItem(file: File, maxWidth: number, uploadContext: RichNoteUploadContext): Promise<Extract<RichNoteItem, { type: "image" }>> {
  const localObjectUrl = URL.createObjectURL(file);
  const measured = await measureImageSize(localObjectUrl).catch(() => ({ width: 520, height: 220 }));
  URL.revokeObjectURL(localObjectUrl);
  const uploaded = await uploadReportImage({
    file,
    reportId: uploadContext.reportId,
    blockId: uploadContext.blockId || "sticky-note",
    tenantId: uploadContext.tenantId,
    userId: uploadContext.userId,
  });
  const ratio = Math.min(1, maxWidth / (measured.width || 520), 420 / (measured.height || 220));
  return {
    id: makeNoteId("note_image"),
    type: "image",
    src: uploaded.absoluteContentUrl,
    name: file.name || "粘贴图片",
    attachmentId: uploaded.attachment.attachment_id,
    artifactId: uploaded.artifact.artifact_id,
    contentHash: uploaded.artifact.content_hash,
    width: Math.max(120, Math.round((measured.width || 520) * ratio)),
    height: Math.max(96, Math.round((measured.height || 220) * ratio)),
  };
}

function measureImageSize(src: string) {
  return new Promise<{ width: number; height: number }>((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve({ width: image.naturalWidth || 520, height: image.naturalHeight || 220 });
    image.onerror = () => reject(new Error("image_measure_failed"));
    image.src = src;
  });
}

function escapeTextAsHtml(text: string) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>");
}
