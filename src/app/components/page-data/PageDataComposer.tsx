import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, GripVertical, LayoutDashboard, Pencil, Plus, Trash2 } from "lucide-react";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import { fetchApplicationModule, runApplicationAction, type ApplicationModuleKey } from "../../services/applicationApi";
import { fetchDataAssets, fetchPageDataRows, type PageDataAsset, type PageDataPageCode, type PageDataRows } from "../../services/dataAssetApi";
import { revealContextRail } from "../context-rail/ContextSideRail";
import { AnalysisVisualCard } from "../self-analysis/ResultViews";
import { ResizableVisualizationGrid } from "../self-analysis/ResizableVisualizationGrid";
import type { AnalysisRow, VisualizationType } from "../self-analysis/domain";

export type ComposerMode = "browse" | "edit";
export const PAGE_DATA_PAGE_GUTTER_CLASS = "p-7";

type PageDataComposerOptions = {
  pageCode: PageDataPageCode;
  moduleKey: ApplicationModuleKey;
  railPageKey: string;
};

const pageLabels: Record<PageDataPageCode, string> = {
  dashboard: "多机构分析",
  weekly_report: "经营周报",
  institution_supervision: "机构督导",
};

export function usePageDataComposer({ pageCode, moduleKey, railPageKey }: PageDataComposerOptions) {
  const { tenantId, userId } = usePlatformContext();
  const [assets, setAssets] = useState<PageDataAsset[]>([]);
  const [layoutIds, setLayoutIds] = useState<string[]>([]);
  const [savedLayoutIds, setSavedLayoutIds] = useState<string[]>([]);
  const [rowsById, setRowsById] = useState<Record<string, PageDataRows>>({});
  const [visualTypes, setVisualTypes] = useState<Record<string, VisualizationType>>({});
  const [mode, setMode] = useState<ComposerMode>("browse");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [draggingId, setDraggingId] = useState("");
  const [savingLayout, setSavingLayout] = useState(false);
  const requestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++requestRef.current;
    setLoading(true);
    Promise.all([
      fetchDataAssets({ tenantId, userId, scope: "runtime" }),
      fetchApplicationModule<{ pageDataLayout?: string[] }>({ tenantId, userId, moduleKey }),
    ]).then(([bundle, module]) => {
      if (cancelled || requestRef.current !== requestId) return;
      const available = (bundle.page_data || []).filter((asset) => asset.targetPages.includes(pageCode) && (
        pageCode === "dashboard" ? pageDataScope(asset) === "multi_institution" : pageDataScope(asset) === "single_institution"
      ));
      const availableIds = new Set(available.map((asset) => asset.id));
      const savedLayout = Array.isArray(module.state.pageDataLayout) ? module.state.pageDataLayout : [];
      setAssets(available);
      const resolvedLayout = savedLayout.filter((id) => availableIds.has(id));
      setLayoutIds(resolvedLayout);
      setSavedLayoutIds(resolvedLayout);
      setVisualTypes(Object.fromEntries(available.map((asset) => [asset.id, asset.visualizationType as VisualizationType])));
      setNotice("");
    }).catch((error) => {
      if (!cancelled) setNotice(apiErrorMessage(error, "页面数据配置加载失败。"));
    }).finally(() => {
      if (!cancelled && requestRef.current === requestId) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [moduleKey, pageCode, tenantId, userId]);

  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const visibleAssets = useMemo(() => layoutIds.map((id) => assetById.get(id)).filter((asset): asset is PageDataAsset => Boolean(asset)), [assetById, layoutIds]);

  useEffect(() => {
    const missing = visibleAssets.filter((asset) => !rowsById[asset.id]);
    if (!missing.length) return;
    let cancelled = false;
    Promise.all(missing.map(async (asset) => {
      try {
        const rows = await fetchPageDataRows({ tenantId, userId, pageDataId: asset.id, pageCode });
        return [asset.id, rows] as const;
      } catch (error) {
        if (!cancelled) setNotice(apiErrorMessage(error, `${asset.name} 数据加载失败。`));
        return null;
      }
    })).then((results) => {
      if (cancelled) return;
      setRowsById((current) => ({ ...current, ...Object.fromEntries(results.filter((item): item is readonly [string, PageDataRows] => Boolean(item))) }));
    });
    return () => { cancelled = true; };
  }, [pageCode, rowsById, tenantId, userId, visibleAssets]);

  const commitLayout = async (nextIds: string[]) => {
    if (mode !== "edit") {
      setNotice("当前为浏览状态；切换到编辑后才能添加、移除或调整图表顺序。");
      return;
    }
    setLayoutIds(nextIds);
    setNotice("");
  };

  const saveLayout = async () => {
    if (mode !== "edit") return true;
    setSavingLayout(true);
    setNotice("");
    try {
      await runApplicationAction({ tenantId, userId, moduleKey, action: "set_page_data_layout", payload: { assetIds: layoutIds } });
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
    void commitLayout(next);
  };

  const moveAsset = (targetId: string) => {
    if (!draggingId || draggingId === targetId || mode !== "edit") return;
    const next = layoutIds.filter((id) => id !== draggingId);
    const targetIndex = next.indexOf(targetId);
    next.splice(targetIndex < 0 ? next.length : targetIndex, 0, draggingId);
    setDraggingId("");
    void commitLayout(next);
  };

  const openRail = (asset: PageDataAsset, tab: "analysis" | "comments") => {
    const rows = rowsById[asset.id];
    revealContextRail(railPageKey, tab, {
      targetId: `page-data:${asset.id}`,
      targetType: visualTypes[asset.id] === "table" || visualTypes[asset.id] === "pivot" ? "table" : "chart",
      label: asset.name,
      values: {
        page_data_id: asset.id,
        source_table_name: asset.sourceTableName,
        metric_fields: asset.metricFields,
        dimension_fields: asset.dimensionFields,
        visualization_type: visualTypes[asset.id] || asset.visualizationType,
        row_count: rows?.row_count || 0,
      },
    });
  };

  return {
    pageCode,
    assets,
    layoutIds,
    visibleAssets,
    rowsById,
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
    openRail,
  };
}

export type PageDataComposerController = ReturnType<typeof usePageDataComposer>;

export function PageDataModeToggle({ controller, className = "", onSave }: { controller: PageDataComposerController; className?: string; onSave?: () => void | Promise<void> }) {
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
  return <button type="button" disabled={controller.savingLayout} data-page-data-mode-toggle="true" data-weekly-page-data-mode-toggle="true" onClick={() => void toggleMode()} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#636366] transition-colors hover:bg-[#f2f2f7] disabled:opacity-50 ${className}`}>{controller.mode === "browse" ? <Pencil className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}{controller.mode === "browse" ? "编辑" : controller.savingLayout ? "保存中" : "保存"}</button>;
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
  } = controller;
  const [instanceTitles, setInstanceTitles] = useState<Record<string, string>>({});
  const [instanceConfigs, setInstanceConfigs] = useState<Record<string, import("../visualization/visualizationDataModel").VisualizationCardConfig>>({});
  const renderedAssets = assetIds?.length ? visibleAssets.filter((asset) => assetIds.includes(asset.id)) : visibleAssets;

  const picker = showAssetPicker && showEditorControls && mode === "edit" ? <div className="mb-3 rounded-xl border border-dashed border-[#cfe0d6] bg-white p-3" data-page-data-inline-picker="true"><div className="mb-2 text-[10px] text-[#7c8781]">选择要展示在{pageLabels[pageCode]}中的多机构数据</div><div className="flex flex-wrap gap-2">{assets.map((asset) => { const selected = layoutIds.includes(asset.id); return <button key={asset.id} type="button" onClick={() => toggleAsset(asset.id)} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[10px] ${selected ? "border-[#75b492] bg-[#edf8f1] text-[#147d4f]" : "border-[#dfe7e2] bg-white text-[#59645e] hover:bg-[#f7faf8]"}`}><span className={`flex h-3.5 w-3.5 items-center justify-center rounded border ${selected ? "border-[#178a53] bg-[#178a53] text-white" : "border-[#cfd7d2] text-transparent"}`}><Check className="h-2.5 w-2.5" /></span>{asset.name}</button>; })}{!assets.length && <span className="text-[10px] text-[#a1a7a3]">暂无可用数据，请先在数据管理的“多机构页面”中新增。</span>}</div></div> : null;

  if (!renderedAssets.length) return picker;

  return (
    <div className={className} data-page-data-visualization-modules={pageCode}>
      {picker}
      <ResizableVisualizationGrid editable={layoutEditable && mode === "edit"}>
        {renderedAssets.map((asset, index) => {
          const pageRows = rowsById[asset.id];
          const instanceKey = `${asset.id}:${index}`;
          return <div
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
              <button type="button" onClick={() => void commitLayout(layoutIds.filter((id) => id !== asset.id))} className="inline-flex h-6 items-center gap-1 rounded-md px-2 hover:bg-[#fff0f0] hover:text-[#d93025]"><Trash2 className="h-3 w-3" />移除</button>
            </div>}
            <div className="min-h-0 flex-1">
              <AnalysisVisualCard
                id={instanceKey}
                stateKey={`page-data:${pageCode}:${instanceKey}`}
                title={instanceTitles[instanceKey] || asset.name}
                type={visualTypes[instanceKey] || visualTypes[asset.id] || asset.visualizationType as VisualizationType}
                rows={pageRows ? toAnalysisRows(asset, pageRows) : []}
                initialConfig={instanceConfigs[instanceKey]}
                compact
                fillHeight
                onFollowUp={() => openRail(asset, "analysis")}
                onComment={() => openRail(asset, "comments")}
                onTypeChange={(type) => setVisualTypes((current) => ({ ...current, [instanceKey]: type }))}
                onTitleChange={(title) => setInstanceTitles((current) => ({ ...current, [instanceKey]: title }))}
                onConfigChange={(config) => setInstanceConfigs((current) => current[instanceKey] === config ? current : { ...current, [instanceKey]: config })}
                onDuplicate={showEditorControls && mode === "edit" ? (config) => { const next = [...layoutIds]; next.splice(index + 1, 0, asset.id); setInstanceConfigs((current) => ({ ...current, [`${asset.id}:${index + 1}`]: config })); setInstanceTitles((current) => ({ ...current, [`${asset.id}:${index + 1}`]: `${instanceTitles[instanceKey] || asset.name} · 副本` })); void commitLayout(next); } : undefined}
                onDelete={showEditorControls && mode === "edit" ? () => { const next = layoutIds.filter((_, layoutIndex) => layoutIndex !== index); void commitLayout(next); } : undefined}
              />
            </div>
          </div>;
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

function pageDataScope(asset: PageDataAsset) {
  if (asset.institutionScope) return asset.institutionScope;
  return asset.targetPages.length === 1 && asset.targetPages[0] === "dashboard" ? "multi_institution" : "single_institution";
}
