import { useEffect, useState, type MouseEvent as ReactMouseEvent } from "react";
import { StickyNote as StickyNoteIcon } from "lucide-react";
import { RichNoteEditor, type RichNoteUploadContext } from "./RichNoteEditor";
import { selectedTextWithin, type StickyNoteRecord } from "./richNote";

export function StickyNotePanel({
  note,
  editing,
  onChange,
  onFinishEdit,
  onStartEdit,
  onHide,
  uploadContext,
  className = "",
}: {
  note: StickyNoteRecord;
  editing: boolean;
  onChange: (items: StickyNoteRecord["items"]) => void;
  onFinishEdit: () => void;
  onStartEdit: () => void;
  onHide: () => void;
  uploadContext: RichNoteUploadContext;
  className?: string;
}) {
  const [deleteMenu, setDeleteMenu] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!deleteMenu) return;
    const close = () => setDeleteMenu(null);
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [deleteMenu]);

  if (!note.visible) return null;

  const openDeleteMenu = (event: ReactMouseEvent<HTMLElement>) => {
    if (selectedTextWithin(event.currentTarget)) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    setDeleteMenu({
      x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 84)),
      y: Math.max(8, event.clientY - rect.top),
    });
  };

  return (
    <section
      className={`relative rounded-xl border border-[#dce7df] bg-[#fbfdfc] p-3 ${className}`}
      data-page-sticky-note="true"
      onDoubleClick={() => { if (!editing) onStartEdit(); }}
      onContextMenu={openDeleteMenu}
    >
      <div className="mb-2 flex items-center gap-1.5 text-[11px] text-[#6f8177]">
        <StickyNoteIcon className="h-3.5 w-3.5" />
        便签
        <span className="text-[10px] text-[#9aa39e]">{editing ? "编辑后自动保存" : "双击文字继续编辑"}</span>
      </div>
      <div
        onBlur={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
          if (editing) onFinishEdit();
        }}
      >
        <RichNoteEditor
          items={note.items}
          onChange={onChange}
          uploadContext={uploadContext}
          readOnly={!editing}
          placeholder="填写需要在可视化图表上方展示的说明，可直接粘贴图片…"
          minHeightClass="min-h-[96px]"
        />
      </div>
      {deleteMenu ? (
        <div
          className="absolute z-40 w-20 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg"
          style={{ left: deleteMenu.x, top: deleteMenu.y }}
          data-sticky-note-delete-menu="true"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            data-sticky-note-delete="true"
            onClick={() => { setDeleteMenu(null); onHide(); }}
            className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#d92d20] hover:bg-[#fff1f0]"
          >
            删除
          </button>
        </div>
      ) : null}
    </section>
  );
}

export function StickyNoteButton({
  onClick,
  className = "",
  size = "default",
}: {
  onClick: () => void;
  className?: string;
  size?: "default" | "compact";
}) {
  const compact = size === "compact";
  return (
    <button
      type="button"
      onClick={onClick}
      data-sticky-note-toggle="true"
      className={compact
        ? `flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-[11px] text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#636366] ${className}`
        : `inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] transition-colors hover:bg-[#f2f2f7] ${className}`}
    >
      <StickyNoteIcon className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
      便签
    </button>
  );
}
