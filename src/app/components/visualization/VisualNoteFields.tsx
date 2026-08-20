import { useEffect, useMemo, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { RichNoteEditor, type RichNoteUploadContext } from "../notes/RichNoteEditor";
import { noteItemsFromText, normalizeNoteItems, serializeNoteItems, type RichNoteItem } from "../notes/richNote";
import { noteFieldTerms } from "./noteHighlights";

export function VisualNoteTitle({
  title,
  onTitleChange,
  onHideTitle,
}: {
  title: string;
  onTitleChange: (value: string) => void;
  onHideTitle?: () => void;
}) {
  const [titleDeleteVisible, setTitleDeleteVisible] = useState(false);
  const hoverTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
  }, []);

  const revealDelete = () => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => setTitleDeleteVisible(true), 1000);
  };
  const hideDelete = () => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    setTitleDeleteVisible(false);
  };

  return (
    <div
      className="relative"
      data-visual-note-title-row="true"
      onMouseEnter={revealDelete}
      onMouseLeave={hideDelete}
    >
      <input
        value={title}
        onChange={(event) => onTitleChange(event.target.value)}
        placeholder="填写名称"
        aria-label="文本框标题"
        data-visual-note-title="true"
        className="h-8 w-full shrink-0 rounded-md border border-[#dce7df] bg-white px-2.5 pr-9 text-[12px] text-[#1d1d1f] outline-none placeholder:text-[#b4b4b8] focus:border-[#8fbaa2] focus:ring-2 focus:ring-[#2b7b5a]/10"
      />
      {onHideTitle && (
        <button
          type="button"
          aria-label="删除标题文本框"
          title="删除标题"
          data-visual-note-title-delete="true"
          onClick={onHideTitle}
          className={`absolute right-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-md text-[#b14f4f] transition-opacity hover:bg-[#fff1f0] ${titleDeleteVisible ? "opacity-100" : "pointer-events-none opacity-0"}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

export function VisualNoteFields({
  title,
  body,
  items,
  titleHidden = false,
  fields,
  metricFields,
  dimensionFields,
  labels,
  uploadContext,
  onTitleChange,
  onBodyChange,
  onItemsChange,
  onHideTitle,
  onOpenComment,
  onOpenAnalysis,
}: {
  title: string;
  body: string;
  items?: RichNoteItem[];
  titleHidden?: boolean;
  fields: string[];
  metricFields: string[];
  dimensionFields: string[];
  labels: Record<string, string>;
  uploadContext: RichNoteUploadContext;
  onTitleChange: (value: string) => void;
  onBodyChange: (value: string) => void;
  onItemsChange?: (items: RichNoteItem[]) => void;
  onHideTitle?: () => void;
  onOpenComment: (selectedText: string) => void;
  onOpenAnalysis: (selectedText: string) => void;
}) {
  const terms = useMemo(
    () => noteFieldTerms({ fields, metricFields, dimensionFields, labels }),
    [dimensionFields, fields, labels, metricFields],
  );
  const resolvedItems = useMemo(() => {
    const fromItems = normalizeNoteItems(items);
    if (fromItems.length) return fromItems;
    return noteItemsFromText(body, "visual_note");
  }, [body, items]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-2" data-visual-note="true">
      {!titleHidden && (
        <VisualNoteTitle title={title} onTitleChange={onTitleChange} onHideTitle={onHideTitle} />
      )}
      <div className="min-h-0 flex-1">
        <RichNoteEditor
          items={resolvedItems}
          terms={terms}
          uploadContext={uploadContext}
          placeholder="针对这张图填写结论、口径解释或需要关注的数据变化，可直接粘贴图片。"
          minHeightClass="h-full min-h-[180px]"
          onOpenComment={onOpenComment}
          onOpenAnalysis={onOpenAnalysis}
          onChange={(next) => {
            onItemsChange?.(next);
            onBodyChange(serializeNoteItems(next));
          }}
        />
      </div>
    </div>
  );
}
