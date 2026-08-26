import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, GripVertical, LayoutDashboard, Pencil, Plus, Trash2 } from "lucide-react";
import { createClientUuid } from "../../utils/clientUuid";
import { usePlatformContext } from "../../platform/PlatformContext";
import { canDeleteOwnVisualCopy } from "../visualization/visualAccess";
import { apiErrorMessage } from "../../services/apiClient";
import { runApplicationAction, type ApplicationModuleKey } from "../../services/applicationApi";
import { fetchPageDataRows, fetchPageDataWorkspace, readPageDataWorkspaceMemory, type PageDataAsset, type PageDataPageCode, type PageDataRows } from "../../services/dataAssetApi";
import { pageDataBelongsToPage, resolvePageDataLayout } from "./assignment";
import { revealAnalysisWorkspace, replaceVisualAnalysisSourceGroup } from "../analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "../analysis-workspace/visualAnalysisScope";
import { revealContextRail } from "../context-rail/ContextSideRail";
import { AnalysisVisualCard, type VisualizationCardConfig } from "../self-analysis/ResultViews";
import { ResizableVisualizationGrid } from "../self-analysis/ResizableVisualizationGrid";
import { visualDuplicateLayout } from "../self-analysis/visualGridLayout";
import { pageDataToSelection, type AnalysisRow, type VisualizationType } from "../self-analysis/domain";
import { askConfirm } from "../ui/ConfirmDialog";

export type ComposerMode = "browse" | "edit";
export const PAGE_DATA_PAGE_GUTTER_CLASS = "p-7";

export type PageEditController = {
  mode: ComposerMode;
  setMode: (mode: ComposerMode) => void;
  savingLayout: boolean;
  saveLayout: () => Promise<boolean>;
};

type PageDataComposerOptions = {
  pageCode: PageDataPageCode;
  moduleKey: ApplicationModuleKey;
  railPageKey: string;
  refreshKey?: string | number;
};

type PageDataNote = {
  id: string;
  sourceAssetId: string;
  type?: VisualizationType;
  noteTitle: string;
  noteBody: string;
  noteTitleHidden?: boolean;
  createdByUserId?: string;
  config: VisualizationCardConfig;
};

const pageLabels: Record<PageDataPageCode, string> = {
  dashboard: "多机构分析",
  weekly_report: "经营周报",
  institution_supervision: "机构督导",
  customer_segment_analysis: "分客群分析",
};

const pageDataRowErrorMessages: Record<string, string> = {
  multi_institution_page_data_source_schema_changed: "多机构数据源结构已更新，当前图表所用字段或关联键不再兼容。请由超级管理员在“数据资产 > 页面数据”重新确认关联后保存。",
  multi_institution_page_data_relationship_unavailable: "多机构关联配置已失效。请由超级管理员在“数据资产 > 表关联”确认来源后重新绑定页面数据。",
  multi_institution_page_data_sources_unavailable: "当前账号已无法读取该多机构配置中的全部来源。请检查机构授权和表关联配置。",
  page_data_selected_field_unavailable: "页面数据所选字段已不存在或语义发生变化。请重新选择维度和指标后保存。",
  page_data_source_schema_changed: "页面数据源结构已更新，当前图表字段不再兼容。请重新绑定数据源后保存。",
  page_data_source_unavailable: "页面数据源已不可用。请检查当前机构的数据目录和页面数据绑定。",
  customer_segment_list_required: "请先在页面右上角上传并确认客户号名单，确认后系统会按名单重新计算全部图表。",
  customer_segment_list_content_changed: "当前客群名单校验失败，请重新上传并确认名单。",
  customer_segment_list_content_invalid: "当前客群名单内容无效，请重新上传符合要求的 Excel 文件。",
  customer_segment_page_data_customer_key_changed: "明细表的客户号主键已经变化，请由超级管理员在站内数据的“分客群页面”中重新保存配置。",
  customer_segment_detail_table_required: "该数据源不是客户号唯一主键的明细表，不能用于分客群分析。",
  customer_segment_source_customer_key_duplicate: "明细表中客户号主键存在重复值，请先修复原始数据后再分析。",
  csv_source_match_key_missing: "明细表中已找不到配置的客户号字段，请重新保存分客群页面数据配置。",
};

function pageDataRowErrorMessage(value: string) {
  const code = String(value || "").trim();
  if (pageDataRowErrorMessages[code]) return pageDataRowErrorMessages[code];
  return /^[a-z][a-z0-9_]*$/.test(code) ? "页面数据暂时无法读取，请检查数据源授权与页面配置后重试。" : code;
}

function applyWorkspace(workspace: { assets?: PageDataAsset[]; layout?: string[]; notes?: unknown[]; rows?: Record<string, PageDataRows>; row_errors?: Record<string, string> }, pageCode: PageDataPageCode) {
  const available = (workspace.assets || []).filter((asset) => pageDataBelongsToPage(asset, pageCode));
  const availableIds = available.map((asset) => asset.id);
  const resolvedLayout = resolvePageDataLayout(workspace.layout || [], availableIds, {
    includeNewlyAssigned: true,
  });
  return {
    assets: available,
    layoutIds: resolvedLayout,
    visualTypes: Object.fromEntries(available.map((asset) => [asset.id, asset.visualizationType as VisualizationType])),
    notes: normalizePageDataNotes(workspace.notes, new Set(resolvedLayout)),
    rowsById: workspace.rows || {},
    rowsFailed: Object.fromEntries(
      Object.entries(workspace.row_errors || {}).map(([assetId, error]) => [assetId, pageDataRowErrorMessage(error)]),
    ),
  };
}

export function usePageDataComposer({ pageCode, moduleKey, railPageKey, refreshKey }: PageDataComposerOptions) {
  const { tenantId, userId, isSuperAdmin } = usePlatformContext();
  const cached = readPageDataWorkspaceMemory(tenantId, userId, pageCode);
  const initial = cached ? applyWorkspace(cached, pageCode) : null;
  const [assets, setAssets] = useState<PageDataAsset[]>(initial?.assets || []);
  const [layoutIds, setLayoutIds] = useState<string[]>(initial?.layoutIds || []);
  const [savedLayoutIds, setSavedLayoutIds] = useState<string[]>(initial?.layoutIds || []);
  const [rowsById, setRowsById] = useState<Record<string, PageDataRows>>(initial?.rowsById || {});
  const [rowsFailed, setRowsFailed] = useState<Record<string, string>>(initial?.rowsFailed || {});
  const [visualTypes, setVisualTypes] = useState<Record<string, VisualizationType>>(initial?.visualTypes || {});
  const [mode, setMode] = useState<ComposerMode>("browse");
  const [loading, setLoading] = useState(!initial);
  const [notice, setNotice] = useState("");
  const [draggingId, setDraggingId] = useState("");
  const [savingLayout, setSavingLayout] = useState(false);
  const [notes, setNotes] = useState<PageDataNote[]>(initial?.notes || []);
  const requestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++requestRef.current;
    if (!readPageDataWorkspaceMemory(tenantId, userId, pageCode)) setLoading(true);
    fetchPageDataWorkspace({ tenantId, userId, pageCode }).then((workspace) => {
      if (cancelled || requestRef.current !== requestId) return;
      const next = applyWorkspace(workspace, pageCode);
      setAssets(next.assets);
      setLayoutIds(next.layoutIds);
      setSavedLayoutIds(next.layoutIds);
      setVisualTypes(next.visualTypes);
      setNotes(next.notes);
      setRowsById(next.rowsById);
      setRowsFailed(next.rowsFailed);
      setNotice("");
    }).catch((error) => {
      if (!cancelled) setNotice(apiErrorMessage(error, "页面数据配置加载失败。"));
    }).finally(() => {
      if (!cancelled && requestRef.current === requestId) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [pageCode, refreshKey, tenantId, userId]);

  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const visibleAssets = useMemo(() => layoutIds.map((id) => assetById.get(id)).filter((asset): asset is PageDataAsset => Boolean(asset)), [assetById, layoutIds]);
  const hasSelectedPageData = visibleAssets.length > 0;
  const hasRenderablePageData = useMemo(
    () => visibleAssets.some((asset) => (rowsById[asset.id]?.rows || []).length > 0),
    [rowsById, visibleAssets],
  );
  const waitingForPageDataRows = useMemo(
    () => visibleAssets.some((asset) => !rowsById[asset.id] && !rowsFailed[asset.id]),
    [rowsById, rowsFailed, visibleAssets],
  );

  useEffect(() => {
    replaceVisualAnalysisSourceGroup(railPageKey, "page-data", visibleAssets.map((asset) => ({
      id: asset.id,
      label: asset.name,
      tables: [pageDataToSelection(asset) as unknown as Record<string, unknown>],
      question: asset.name,
      summary: asset.sourceTableName || asset.name,
      rows: boundedVisualRows(rowsById[asset.id]?.rows),
    })));
    return () => { replaceVisualAnalysisSourceGroup(railPageKey, "page-data", []); };
  }, [railPageKey, rowsById, visibleAssets]);

  useEffect(() => {
    const missing = visibleAssets.filter((asset) => !rowsById[asset.id] && !rowsFailed[asset.id]);
    if (!missing.length) return;
    let cancelled = false;
    Promise.all(missing.map(async (asset) => {
      try {
        const rows = await fetchPageDataRows({ tenantId, userId, pageDataId: asset.id, pageCode });
        return { id: asset.id, rows };
      } catch (error) {
        const message = pageDataRowErrorMessage(apiErrorMessage(error, `${asset.name} 数据加载失败。`));
        return { id: asset.id, error: message };
      }
    })).then((results) => {
      if (cancelled) return;
      setRowsById((current) => ({
        ...current,
        ...Object.fromEntries(results.flatMap((item) => item.rows ? [[item.id, item.rows] as const] : [])),
      }));
      setRowsFailed((current) => ({
        ...current,
        ...Object.fromEntries(results.flatMap((item) => item.error ? [[item.id, item.error] as const] : [])),
      }));
      const failed = results.find((item) => item.error);
      if (failed?.error) setNotice(failed.error);
    });
    return () => { cancelled = true; };
  }, [pageCode, rowsById, rowsFailed, tenantId, userId, visibleAssets]);

  const commitLayout = async (nextIds: string[]) => {
    if (mode !== "edit") {
      setNotice("当前为浏览状态；切换到编辑后才能添加、移除或调整图表顺序。");
      return;
    }
    setLayoutIds(nextIds);
    setNotes((current) => current.filter((note) => nextIds.includes(note.sourceAssetId)));
    setNotice("");
  };

  const saveLayout = async () => {
    if (mode !== "edit") return true;
    setSavingLayout(true);
    setNotice("");
    try {
      await runApplicationAction({ tenantId, userId, moduleKey, action: "set_page_data_layout", payload: { assetIds: layoutIds, notes } });
      setSavedLayoutIds(layoutIds);
      return true;
    } catch (error) {
      setLayoutIds(savedLayoutIds);
      setNotice(apiErrorMessage(error, "页面布局保存失败，已恢复原顺序。"));
      return false;
    } finally {
      setSavingLayout(false);
    }
  };

  const toggleAsset = (assetId: string) => {
    const next = layoutIds.includes(assetId) ? layoutIds.filter((id) => id !== assetId) : [...layoutIds, assetId];
    if (!next.includes(assetId)) setNotes((current) => current.filter((note) => note.sourceAssetId !== assetId));
    void commitLayout(next);
  };

  const notesSaveTimer = useRef<number | null>(null);
  const writeNotes = async (next: PageDataNote[]) => {
    try {
      await runApplicationAction({ tenantId, userId, moduleKey, action: "set_page_data_notes", payload: { notes: next } });
    } catch (error) {
      setNotice(apiErrorMessage(error, "文本框保存失败。"));
    }
  };
  const scheduleWriteNotes = (next: PageDataNote[]) => {
    if (notesSaveTimer.current !== null) window.clearTimeout(notesSaveTimer.current);
    notesSaveTimer.current = window.setTimeout(() => { void writeNotes(next); }, 700);
  };

  const addTextCard = (sourceAssetId: string, config: VisualizationCardConfig, sourceCardId?: string) => {
    const layout = sourceCardId ? visualDuplicateLayout(sourceCardId) : {};
    setNotes((current) => {
      const next = [...current, {
        id: createClientUuid(),
        sourceAssetId,
        type: "text" as const,
        noteTitle: "",
        noteBody: "",
        noteTitleHidden: false,
        createdByUserId: userId,
        config: { ...config, noteTitle: "", noteBody: "", noteItems: [], noteTitleHidden: false, ...layout },
      }];
      void writeNotes(next);
      return next;
    });
    setNotice("");
  };

  const moveAsset = (targetId: string) => {
    if (!draggingId || draggingId === targetId || mode !== "edit") return;
    const next = layoutIds.filter((id) => id !== draggingId);
    const targetIndex = next.indexOf(targetId);
    next.splice(targetIndex < 0 ? next.length : targetIndex, 0, draggingId);
    setDraggingId("");
    void commitLayout(next);
  };

  const openRail = (asset: PageDataAsset, tab: "analysis" | "comments", detail?: { selectedText?: string; dataTables?: ReturnType<typeof pageDataToSelection>[]; label?: string; targetId?: string }) => {
    const rows = rowsById[asset.id];
    const selectedTable = detail?.dataTables?.[0] || pageDataToSelection(asset);
    const selectedDataPoint = {
      targetId: detail?.targetId || `page-data:${asset.id}`,
      targetType: visualTypes[asset.id] === "table" || visualTypes[asset.id] === "pivot" ? "table" as const : "chart" as const,
      label: detail?.label || asset.name,
      values: {
        page_data_id: asset.id,
        source_table_name: asset.sourceTableName,
        metric_fields: asset.metricFields,
        dimension_fields: asset.dimensionFields,
        visualization_type: visualTypes[asset.id] || asset.visualizationType,
        row_count: rows?.row_count || 0,
        question: asset.name,
        analysis_summary: `${asset.name}${asset.sourceTableName ? ` · ${asset.sourceTableName}` : ""}`,
        selected_content: detail?.selectedText || "",
        chart_bound_source: true,
        visual_rows: boundedVisualRows(rows?.rows),
        selected_data_table_ids: [selectedTable.id],
        selected_data_tables: [selectedTable],
        dataset_snapshot: {
          id: selectedTable.id,
          version: selectedTable.assetVersion || selectedTable.contentHash,
          content_hash: selectedTable.contentHash,
          schema_fingerprint: selectedTable.schemaFingerprint,
          generatedAt: new Date().toISOString(),
        },
      },
    };
    revealContextRail(railPageKey, tab, selectedDataPoint);
    if (tab === "analysis") revealAnalysisWorkspace(selectedDataPoint, "context-rail");
  };

  return {
    pageCode,
    assets,
    layoutIds,
    visibleAssets,
    hasSelectedPageData,
    hasRenderablePageData,
    waitingForPageDataRows,
    rowsById,
    rowsFailed,
    visualTypes,
    setVisualTypes,
    mode,
    setMode,
    loading,
    notice,
    draggingId,
    setDraggingId,
    toggleAsset,
    moveAsset,
    commitLayout,
    saveLayout,
    savingLayout,
    notes,
    addTextCard,
    updateNote: (noteId: string, patch: Partial<PageDataNote>) => {
      setNotes((current) => {
        const next = current.map((note) => note.id === noteId ? { ...note, ...patch } : note);
        scheduleWriteNotes(next);
        return next;
      });
    },
    persistNoteChanges: () => { void writeNotes(notes); },
    removeNote: (noteId: string) => {
      const target = notes.find((note) => note.id === noteId);
      if (!target || !canDeleteOwnVisualCopy({ createdByUserId: target.createdByUserId, userId, isSuperAdmin })) return;
      void askConfirm({ title: "删除结论卡片", description: `确定删除「${target.noteTitle || "该卡片"}」？`, hint: "此操作不可撤销。" }).then((ok) => {
        if (!ok) return;
        setNotes((current) => {
          const next = current.filter((note) => note.id !== noteId);
          void writeNotes(next);
          return next;
        });
      });
    },
    userId,
    isSuperAdmin,
    openRail,
  };
}

function normalizePageDataNotes(value: unknown, availableIds: Set<string>): PageDataNote[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const id = typeof record.id === "string" ? record.id.trim() : "";
    const sourceAssetId = typeof record.sourceAssetId === "string" ? record.sourceAssetId.trim() : "";
    if (!id || !sourceAssetId || !availableIds.has(sourceAssetId)) return [];
    const config = record.config && typeof record.config === "object" && !Array.isArray(record.config)
      ? record.config as VisualizationCardConfig
      : { metricFields: [], dimensionFields: [], filters: {}, filterGroups: [], sumFilteredRows: false, comboLineFields: [] };
    return [{
      id,
      sourceAssetId,
      type: typeof record.type === "string" ? record.type as VisualizationType : "text",
      noteTitle: typeof record.noteTitle === "string" ? record.noteTitle : "",
      noteBody: typeof record.noteBody === "string" ? record.noteBody : "",
      noteTitleHidden: Boolean(record.noteTitleHidden),
      createdByUserId: typeof record.createdByUserId === "string" ? record.createdByUserId : "",
      config,
    }];
  });
}

export type PageDataComposerController = ReturnType<typeof usePageDataComposer>;

export function PageDataModeToggle({ controller, className = "", onSave }: { controller: PageEditController; className?: string; onSave?: () => void | Promise<void> }) {
  const toggleMode = async () => {
    if (controller.mode === "browse") {
      controller.setMode("edit");
      return;
    }
    const saved = await controller.saveLayout();
    if (!saved) return;
    await onSave?.();
    controller.setMode("browse");
  };
  return <button type="button" disabled={controller.savingLayout} data-page-data-mode-toggle="true" data-weekly-page-data-mode-toggle="true" onClick={() => void toggleMode()} className={`inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#636366] transition-colors hover:bg-[#f2f2f7] disabled:opacity-50 ${className}`}>{controller.mode === "browse" ? <Pencil className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}{controller.mode === "browse" ? "编辑" : controller.savingLayout ? "保存中" : "保存"}</button>;
}

export function PageDataVisualizationModules({
  controller,
  className = "mt-4",
  assetIds,
  showEditorControls = true,
  layoutEditable = showEditorControls,
  showAssetPicker = false,
}: {
  controller: PageDataComposerController;
  className?: string;
  assetIds?: string[];
  showEditorControls?: boolean;
  layoutEditable?: boolean;
  showAssetPicker?: boolean;
}) {
  const {
    pageCode,
    visibleAssets,
    rowsById,
    rowsFailed,
    visualTypes,
    setVisualTypes,
    mode,
    setDraggingId,
    moveAsset,
    commitLayout,
    layoutIds,
    openRail,
    assets,
    toggleAsset,
    notes,
    addTextCard,
    updateNote,
    removeNote,
    userId,
    isSuperAdmin,
  } = controller;
  const [instanceTitles, setInstanceTitles] = useState<Record<string, string>>({});
  const [instanceConfigs, setInstanceConfigs] = useState<Record<string, import("../visualization/visualizationDataModel").VisualizationCardConfig>>({});
  const renderedAssets = assetIds?.length ? visibleAssets.filter((asset) => assetIds.includes(asset.id)) : visibleAssets;

  const pickerKind = pageCode === "dashboard" ? "多机构数据" : pageCode === "customer_segment_analysis" ? "分客群明细数据" : "单机构数据";
  const pickerSource = pageCode === "dashboard" ? "多机构页面" : pageCode === "customer_segment_analysis" ? "分客群页面" : "单机构页面";
  const picker = showAssetPicker && showEditorControls && mode === "edit" ? <div className="mb-3 rounded-xl border border-dashed border-[#cfe0d6] bg-white p-3" data-page-data-inline-picker="true"><div className="mb-2 text-[10px] text-[#7c8781]">选择要展示在{pageLabels[pageCode]}中的{pickerKind}</div><div className="flex flex-wrap gap-2">{assets.map((asset) => { const selected = layoutIds.includes(asset.id); return <button key={asset.id} type="button" onClick={() => toggleAsset(asset.id)} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[10px] ${selected ? "border-[#75b492] bg-[#edf8f1] text-[#147d4f]" : "border-[#dfe7e2] bg-white text-[#59645e] hover:bg-[#f7faf8]"}`}><span className={`flex h-3.5 w-3.5 items-center justify-center rounded border ${selected ? "border-[#178a53] bg-[#178a53] text-white" : "border-[#cfd7d2] text-transparent"}`}><Check className="h-2.5 w-2.5" /></span>{asset.name}</button>; })}{!assets.length && <span className="text-[10px] text-[#a1a7a3]">暂无可用数据，请先在站内数据的“{pickerSource}”中新增。</span>}</div></div> : null;

  if (!renderedAssets.length) return picker;

  return (
    <div className={className} data-page-data-visualization-modules={pageCode}>
      {picker}
      <ResizableVisualizationGrid editable={layoutEditable && mode === "edit"}>
        {renderedAssets.flatMap((asset, index) => {
          const pageRows = rowsById[asset.id];
          const instanceKey = `${asset.id}:${index}`;
          const analysisRows = pageRows ? toAnalysisRows(asset, pageRows) : [];
          const sourceCard = <div
            key={instanceKey}
            className="flex h-full min-h-0 flex-col"
            draggable={showEditorControls && mode === "edit"}
            onDragStart={(event) => { if (!showEditorControls || mode !== "edit") return; setDraggingId(asset.id); event.dataTransfer.effectAllowed = "move"; }}
            onDragEnd={() => setDraggingId("")}
            onDragOver={(event) => { if (showEditorControls && mode === "edit") event.preventDefault(); }}
            onDrop={() => { if (showEditorControls) moveAsset(asset.id); }}
            data-page-data-card={asset.id}
          >
            {showEditorControls && mode === "edit" && <div className="mb-1 flex h-7 shrink-0 items-center justify-between rounded-lg bg-[#f6f8f7] px-2 text-[10px] text-[#7c8781]">
              <span className="inline-flex cursor-grab items-center gap-1 active:cursor-grabbing"><GripVertical className="h-3.5 w-3.5" />拖动排序</span>
              <button type="button" onClick={() => void askConfirm({ title: "移除图表", description: `确定从当前页面移除「${asset.name}」？`, hint: "此操作不可撤销。" }).then((ok) => { if (ok) void commitLayout(layoutIds.filter((id) => id !== asset.id)); })} className="inline-flex h-6 items-center gap-1 rounded-md px-2 hover:bg-[#fff0f0] hover:text-[#d93025]"><Trash2 className="h-3 w-3" />移除</button>
            </div>}
            <div className="min-h-0 flex-1">
              {!pageRows && !rowsFailed[asset.id] ? (
                <div className="flex h-full min-h-[220px] items-center justify-center rounded-xl border border-dashed border-[#e5e5ea] bg-[#fafbfc] text-[12px] text-[#8a8a8e]" data-page-data-rows-loading={asset.id}>正在加载页面数据…</div>
              ) : rowsFailed[asset.id] ? (
                <div className="flex h-full min-h-[220px] items-center justify-center rounded-xl border border-dashed border-[#ffd7d7] bg-[#fff5f5] px-4 text-center text-[12px] text-[#b42318]" data-page-data-rows-failed={asset.id}>{rowsFailed[asset.id]}</div>
              ) : <AnalysisVisualCard
                id={instanceKey}
                stateKey={`page-data:${pageCode}:${instanceKey}`}
                title={instanceTitles[instanceKey] || asset.name}
                type={visualTypes[instanceKey] || visualTypes[asset.id] || asset.visualizationType as VisualizationType}
                rows={analysisRows}
                initialConfig={instanceConfigs[instanceKey] || { metricFields: asset.metricFields, dimensionFields: asset.dimensionFields }}
                compact
                fillHeight
                analysisSource={[pageDataToSelection(asset)]}
                onFollowUp={(detail) => openRail(asset, "analysis", detail)}
                onComment={(detail) => openRail(asset, "comments", detail)}
                onTypeChange={(type) => setVisualTypes((current) => ({ ...current, [instanceKey]: type }))}
                onTitleChange={(title) => setInstanceTitles((current) => ({ ...current, [instanceKey]: title }))}
                onConfigChange={(config) => setInstanceConfigs((current) => current[instanceKey] === config ? current : { ...current, [instanceKey]: config })}
                onCreateText={(config) => addTextCard(asset.id, config, instanceKey)}
                onDuplicate={showEditorControls && mode === "edit" ? (config, options) => {
                  if (options?.asText) { addTextCard(asset.id, config, instanceKey); return; }
                  const next = [...layoutIds];
                  next.splice(index + 1, 0, asset.id);
                  setInstanceConfigs((current) => ({ ...current, [`${asset.id}:${index + 1}`]: config }));
                  setInstanceTitles((current) => ({ ...current, [`${asset.id}:${index + 1}`]: `${instanceTitles[instanceKey] || asset.name} · 副本` }));
                  void commitLayout(next);
                } : (config, options) => { if (options?.asText) addTextCard(asset.id, config, instanceKey); }}
                onDelete={showEditorControls && mode === "edit" ? () => { void askConfirm({ title: "移除图表", description: `确定从当前页面移除「${instanceTitles[instanceKey] || asset.name}」？`, hint: "此操作不可撤销。" }).then((ok) => { if (ok) void commitLayout(layoutIds.filter((_, layoutIndex) => layoutIndex !== index)); }); } : undefined}
              />}
            </div>
          </div>;
          const noteCards = notes.filter((note) => note.sourceAssetId === asset.id).map((note) => (
            <div
              key={note.id}
              className="flex h-full min-h-0 flex-col"
              data-page-data-note={note.id}
              data-visual-grid-span={note.config.layoutSpan}
              data-visual-grid-height={note.config.layoutHeight}
              data-visual-grid-max-span={note.config.maxLayoutSpan}
              data-visual-grid-max-height={note.config.maxLayoutHeight}
            >
              <div className="min-h-0 flex-1">
                <AnalysisVisualCard
                  id={note.id}
                  stateKey={`page-data-note:${pageCode}:${note.id}`}
                  title={note.noteTitle || `${asset.name} · 结论`}
                  type={note.type || "text"}
                  rows={analysisRows}
                  initialConfig={{ ...note.config, noteTitle: note.noteTitle, noteBody: note.noteBody, noteTitleHidden: note.noteTitleHidden, metricFields: note.config.metricFields?.length ? note.config.metricFields : asset.metricFields, dimensionFields: note.config.dimensionFields?.length ? note.config.dimensionFields : asset.dimensionFields }}
                  compact
                  fillHeight
                  visualGridSpan={note.config.layoutSpan}
                  visualGridHeight={note.config.layoutHeight}
                  visualGridMaxSpan={note.config.maxLayoutSpan}
                  visualGridMaxHeight={note.config.maxLayoutHeight}
                  analysisSource={[pageDataToSelection(asset)]}
                  onFollowUp={(detail) => openRail(asset, "analysis", { ...detail, label: note.noteTitle || `${asset.name} · 结论`, targetId: `page-data-note:${note.id}` })}
                  onComment={(detail) => openRail(asset, "comments", { ...detail, label: note.noteTitle || `${asset.name} · 结论`, targetId: `page-data-note:${note.id}` })}
                  onTypeChange={(type) => updateNote(note.id, { type })}
                  onTitleChange={(title) => updateNote(note.id, { noteTitle: title })}
                  onConfigChange={(config) => updateNote(note.id, { config, noteTitle: config.noteTitle ?? note.noteTitle, noteBody: config.noteBody ?? note.noteBody, noteTitleHidden: config.noteTitleHidden ?? note.noteTitleHidden })}
                  onCreateText={(config) => addTextCard(asset.id, config, note.id)}
                  onDuplicate={(config, options) => { if (!options || options.asText) addTextCard(asset.id, config); }}
                  onDelete={canDeleteOwnVisualCopy({ createdByUserId: note.createdByUserId, userId, isSuperAdmin }) ? () => removeNote(note.id) : undefined}
                />
              </div>
            </div>
          ));
          return [sourceCard, ...noteCards];
        })}
      </ResizableVisualizationGrid>
    </div>
  );
}

export function PageDataComposer({ pageCode, moduleKey, railPageKey }: PageDataComposerOptions) {
  const controller = usePageDataComposer({ pageCode, moduleKey, railPageKey });
  const {
    assets,
    layoutIds,
    visibleAssets,
    mode,
    setMode,
    loading,
    notice,
    toggleAsset,
  } = controller;
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <section className="mb-5" data-page-data-composer={pageCode} data-page-data-mode={mode}>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div aria-label="页面编辑保存状态" data-page-data-mode-switch="true"><PageDataModeToggle controller={controller} /></div>
        <div className="relative" data-page-data-picker="true">
          <button type="button" onClick={() => setMenuOpen((open) => !open)} className="inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-lg border border-[#dfe7e2] bg-white px-3 text-[11px] text-[#435049] hover:bg-[#f7faf8]" aria-expanded={menuOpen}>
            <LayoutDashboard className="h-3.5 w-3.5 text-[#178a53]" />页面数据 {assets.length}<ChevronDown className={`h-3.5 w-3.5 transition-transform ${menuOpen ? "rotate-180" : ""}`} />
          </button>
          {menuOpen && <div className="absolute right-0 top-11 z-[80] w-[300px] overflow-hidden rounded-xl border border-[#dfe7e2] bg-white shadow-xl shadow-black/10">
            <div className="border-b border-[#eef1ef] px-3 py-2 text-[10px] text-[#8a938e]">{pageLabels[pageCode]}可用数据 · {mode === "edit" ? "点击添加或移除" : "浏览状态仅查看"}</div>
            <div className="max-h-[320px] overflow-y-auto p-1.5">
              {assets.map((asset) => {
                const selected = layoutIds.includes(asset.id);
                return <button key={asset.id} type="button" onClick={() => toggleAsset(asset.id)} className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left ${mode === "edit" ? "hover:bg-[#f3f8f5]" : "cursor-default"}`}>
                  <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${selected ? "border-[#178a53] bg-[#178a53] text-white" : "border-[#d8dedb] text-transparent"}`}><Check className="h-3 w-3" /></span>
                  <span className="min-w-0"><span className="block truncate text-[11px] text-[#1d1d1f]">{asset.name}</span><span className="mt-0.5 block truncate text-[9px] text-[#9ba29e]">{asset.sourceTableName}</span></span>
                </button>;
              })}
              {!assets.length && <div className="px-3 py-6 text-center text-[11px] text-[#a1a7a3]">请先在数据资产的“页面数据”中配置</div>}
            </div>
          </div>}
        </div>
      </div>

      {notice && <div className="mt-3 rounded-lg border border-[#e2e9e5] bg-white px-3 py-2 text-[11px] text-[#68736d]">{notice}</div>}
      {loading && <div className="mt-3 rounded-xl border border-dashed border-[#dfe7e2] bg-white px-4 py-8 text-center text-[11px] text-[#9ba29e]">正在读取页面数据配置…</div>}
      {!loading && visibleAssets.length > 0 && <PageDataVisualizationModules controller={controller} />}
      {!loading && assets.length > 0 && !visibleAssets.length && <div className="mt-3 flex items-center justify-center gap-2 rounded-xl border border-dashed border-[#dfe7e2] bg-white px-4 py-8 text-[11px] text-[#8d9891]"><Plus className="h-3.5 w-3.5" />切换到编辑，从“页面数据”下拉框添加图表</div>}
    </section>
  );
}

function toAnalysisRows(asset: PageDataAsset, data: PageDataRows): AnalysisRow[] {
  const dimension = asset.dimensionFields[0];
  const metric = asset.metricFields[0];
  return data.rows.map((raw) => ({
    branch: String(raw[dimension] ?? "—"),
    productLine: "",
    customerSegment: "",
    amount: finiteNumber(raw[metric]),
    metricName: data.field_labels[metric] || metric,
    metricUnit: "",
    fieldLabels: data.field_labels,
    raw,
    completion: "—",
    conversion: "—",
    overdueRate: "—",
    weekChange: "—",
  }));
}

function finiteNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(String(value ?? "").replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

export { pageDataScope } from "./assignment";
