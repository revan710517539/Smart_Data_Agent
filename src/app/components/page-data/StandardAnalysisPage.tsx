import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Eye, GripVertical } from "lucide-react";
import { apiErrorMessage } from "../../services/apiClient";
import { fetchApplicationModule, runApplicationAction, type ApplicationModuleKey } from "../../services/applicationApi";
import { readVisualGridItemSize } from "../self-analysis/visualGridLayout";
import { ResizableVisualizationGrid } from "../self-analysis/ResizableVisualizationGrid";
import { StickyNoteButton, StickyNotePanel } from "../notes/StickyNote";
import type { useStickyNote } from "../notes/useStickyNote";
import { PageDataModeToggle, type ComposerMode, type PageEditController } from "./PageDataComposer";

export type StandardAnalysisStickyNoteController = ReturnType<typeof useStickyNote>;

// Institution supervision is the product-approved default shell for newly
// generated governed report pages. Domain pages only inject content/actions.
export const DEFAULT_REPORT_PAGE_TEMPLATE = "institution-supervision";

export type StandardAnalysisVisualDefinition = {
  id: string;
  label: string;
  defaultSpan: number;
  defaultHeight: number;
};

export type StandardAnalysisVisualLayoutItem = {
  id: string;
  span: number;
  height: number;
};

type StandardAnalysisModule = {
  id: string;
  content: ReactNode;
};

export function StandardAnalysisPageHeader({
  title,
  description,
  metadata,
  stickyNote,
  editController,
  canEditLayout,
  leadingActions,
  headerDataAttribute,
}: {
  title: string;
  description: string;
  metadata?: ReactNode;
  stickyNote: StandardAnalysisStickyNoteController;
  editController: PageEditController;
  canEditLayout: boolean;
  leadingActions?: ReactNode;
  headerDataAttribute?: string;
}) {
  return (
    <div
      className="mb-6 flex flex-wrap items-start justify-between gap-3"
      data-standard-analysis-page-header="true"
      data-default-report-page-template={DEFAULT_REPORT_PAGE_TEMPLATE}
      data-analysis-page-header={headerDataAttribute || undefined}
    >
      <div className="min-w-0">
        <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">{title}</h2>
        <p className="mt-1 text-[13px] text-[#aeaeb2]">{description}</p>
        {metadata ? <div className="mt-1 text-[10px] text-[#c7c7cc]">{metadata}</div> : null}
      </div>
      <div className="flex max-w-full flex-wrap items-center justify-end gap-2" data-standard-analysis-page-actions="true">
        {leadingActions}
        <StickyNoteButton onClick={stickyNote.show} />
        {canEditLayout ? <PageDataModeToggle controller={editController} /> : null}
      </div>
    </div>
  );
}

export function StandardAnalysisPageStickyNote({
  stickyNote,
  className = "mb-4",
}: {
  stickyNote: StandardAnalysisStickyNoteController;
  className?: string;
}) {
  return (
    <StickyNotePanel
      className={className}
      note={stickyNote.note}
      editing={stickyNote.editing}
      onChange={stickyNote.updateItems}
      onFinishEdit={stickyNote.finishEdit}
      onStartEdit={() => stickyNote.setEditing(true)}
      onHide={stickyNote.hide}
      uploadContext={stickyNote.uploadContext}
    />
  );
}

export function useStandardAnalysisPageLayout({
  tenantId,
  userId,
  moduleKey,
  definitions,
}: {
  tenantId: string;
  userId: string;
  moduleKey: Extract<ApplicationModuleKey, "customer_insight" | "competition_analysis">;
  definitions: StandardAnalysisVisualDefinition[];
}) {
  const defaults = useMemo(() => defaultLayout(definitions), [definitions]);
  const [layout, setLayout] = useState<StandardAnalysisVisualLayoutItem[]>(defaults);
  const [savedLayout, setSavedLayout] = useState<StandardAnalysisVisualLayoutItem[]>(defaults);
  const [mode, setMode] = useState<ComposerMode>("browse");
  const [savingLayout, setSavingLayout] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setMode("browse");
    fetchApplicationModule<{ pageVisualLayout?: unknown }>({ tenantId, userId, moduleKey })
      .then((response) => {
        if (cancelled) return;
        const next = normalizeLayout(response.state.pageVisualLayout, definitions);
        setLayout(next);
        setSavedLayout(next);
        setNotice("");
      })
      .catch((error) => {
        if (cancelled) return;
        setLayout(defaults);
        setSavedLayout(defaults);
        setNotice(apiErrorMessage(error, "页面布局状态读取失败，当前使用默认布局。"));
      });
    return () => { cancelled = true; };
  }, [defaults, definitions, moduleKey, tenantId, userId]);

  const saveLayout = async () => {
    if (mode !== "edit") return true;
    setSavingLayout(true);
    setNotice("");
    const measured = layout.map((item) => {
      const size = readVisualGridItemSize(visualGridId(moduleKey, item.id));
      return {
        id: item.id,
        span: boundedInteger(size?.span, item.span, 4, 12),
        height: boundedInteger(size?.height, item.height, 240, 1200),
      };
    });
    try {
      await runApplicationAction({ tenantId, userId, moduleKey, action: "set_page_visual_layout", payload: { items: measured } });
      setLayout(measured);
      setSavedLayout(measured);
      return true;
    } catch (error) {
      setLayout(savedLayout);
      setNotice(apiErrorMessage(error, "页面布局保存失败，已恢复上次保存的布局。"));
      return false;
    } finally {
      setSavingLayout(false);
    }
  };

  const editController: PageEditController = { mode, setMode, savingLayout, saveLayout };
  const visibleIds = new Set(layout.map((item) => item.id));

  return {
    layout,
    mode,
    notice,
    editController,
    hiddenDefinitions: definitions.filter((definition) => !visibleIds.has(definition.id)),
    hide: (id: string) => {
      if (mode !== "edit") return;
      setLayout((current) => current.filter((item) => item.id !== id));
    },
    restore: (id: string) => {
      if (mode !== "edit" || visibleIds.has(id)) return;
      const definition = definitions.find((item) => item.id === id);
      if (!definition) return;
      setLayout((current) => [...current, layoutFromDefinition(definition)]);
    },
    move: (sourceId: string, targetId: string) => {
      if (mode !== "edit" || !sourceId || sourceId === targetId) return;
      setLayout((current) => {
        const source = current.find((item) => item.id === sourceId);
        if (!source) return current;
        const next = current.filter((item) => item.id !== sourceId);
        const targetIndex = next.findIndex((item) => item.id === targetId);
        next.splice(targetIndex < 0 ? next.length : targetIndex, 0, source);
        return next;
      });
    },
  };
}

export function StandardAnalysisPageGrid({
  moduleKey,
  definitions,
  modules,
  layout,
  hiddenDefinitions,
  editable,
  onHide,
  onRestore,
  onMove,
}: {
  moduleKey: "customer_insight" | "competition_analysis";
  definitions: StandardAnalysisVisualDefinition[];
  modules: StandardAnalysisModule[];
  layout: StandardAnalysisVisualLayoutItem[];
  hiddenDefinitions: StandardAnalysisVisualDefinition[];
  editable: boolean;
  onHide: (id: string) => void;
  onRestore: (id: string) => void;
  onMove: (sourceId: string, targetId: string) => void;
}) {
  const [draggingId, setDraggingId] = useState("");
  const moduleById = new Map(modules.map((module) => [module.id, module]));
  const definitionById = new Map(definitions.map((definition) => [definition.id, definition]));
  const visible = layout.flatMap((item) => {
    const module = moduleById.get(item.id);
    return module ? [{ item, module }] : [];
  });

  return (
    <section data-standard-analysis-page-grid={moduleKey}>
      {editable ? (
        <div className="mb-3 rounded-xl border border-dashed border-[#cfe0d6] bg-white p-3" data-standard-analysis-module-picker="true">
          <div className="mb-2 text-[10px] text-[#7c8781]">页面模块</div>
          <div className="flex flex-wrap gap-2">
            {hiddenDefinitions.map((definition) => (
              <button key={definition.id} type="button" onClick={() => onRestore(definition.id)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#dfe7e2] bg-white px-3 text-[10px] text-[#59645e] hover:bg-[#f7faf8]">
                <Eye className="h-3.5 w-3.5" />显示{definition.label}
              </button>
            ))}
            {!hiddenDefinitions.length ? <span className="text-[10px] text-[#9aa39e]">全部模块均已显示；可拖动排序、拖拽边缘调整大小或隐藏模块。</span> : null}
          </div>
        </div>
      ) : null}
      {visible.length ? (
        <ResizableVisualizationGrid editable={editable}>
          {visible.map(({ item, module }) => {
            const definition = definitionById.get(item.id);
            return (
              <div
                key={visualGridId(moduleKey, item.id)}
                className="flex h-full min-h-0 flex-col"
                draggable={editable}
                onDragStart={(event) => { if (!editable) return; setDraggingId(item.id); event.dataTransfer.effectAllowed = "move"; }}
                onDragEnd={() => setDraggingId("")}
                onDragOver={(event) => { if (editable) event.preventDefault(); }}
                onDrop={() => { if (editable) onMove(draggingId, item.id); setDraggingId(""); }}
                data-standard-analysis-module={item.id}
                data-visual-grid-span={item.span}
                data-visual-grid-height={item.height}
              >
                {editable ? (
                  <div className="mb-1 flex h-7 shrink-0 items-center justify-between rounded-lg bg-[#f6f8f7] px-2 text-[10px] text-[#7c8781]">
                    <span className="inline-flex cursor-grab items-center gap-1 active:cursor-grabbing"><GripVertical className="h-3.5 w-3.5" />拖动排序</span>
                    <button type="button" onClick={() => onHide(item.id)} className="inline-flex h-6 items-center gap-1 rounded-md px-2 hover:bg-[#f0f5f2] hover:text-[#178a53]"><Eye className="h-3 w-3" />隐藏{definition?.label || "模块"}</button>
                  </div>
                ) : null}
                <div className="min-h-0 flex-1">{module.content}</div>
              </div>
            );
          })}
        </ResizableVisualizationGrid>
      ) : (
        <div className="rounded-xl border border-dashed border-[#dfe7e2] bg-white px-6 py-14 text-center text-[12px] text-[#9aa39e]">当前页面模块均已隐藏，请在编辑状态下重新显示。</div>
      )}
    </section>
  );
}

function defaultLayout(definitions: StandardAnalysisVisualDefinition[]) {
  return definitions.map(layoutFromDefinition);
}

function layoutFromDefinition(definition: StandardAnalysisVisualDefinition): StandardAnalysisVisualLayoutItem {
  return { id: definition.id, span: definition.defaultSpan, height: definition.defaultHeight };
}

function normalizeLayout(value: unknown, definitions: StandardAnalysisVisualDefinition[]) {
  if (!Array.isArray(value)) return defaultLayout(definitions);
  const definitionsById = new Map(definitions.map((definition) => [definition.id, definition]));
  const seen = new Set<string>();
  return value.flatMap((raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const record = raw as Record<string, unknown>;
    const id = String(record.id || "").trim();
    const definition = definitionsById.get(id);
    if (!definition || seen.has(id)) return [];
    seen.add(id);
    return [{
      id,
      span: boundedInteger(record.span, definition.defaultSpan, 4, 12),
      height: boundedInteger(record.height, definition.defaultHeight, 240, 1200),
    }];
  });
}

function boundedInteger(value: unknown, fallback: number, minimum: number, maximum: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(minimum, Math.min(maximum, Math.round(parsed))) : fallback;
}

function visualGridId(moduleKey: string, id: string) {
  return `standard-${moduleKey}-${id}`;
}
