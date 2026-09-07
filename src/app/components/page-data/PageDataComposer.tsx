import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, GripVertical, LayoutDashboard, Pencil, Plus, SlidersHorizontal, Trash2, X } from "lucide-react";
import { createClientUuid } from "../../utils/clientUuid";
import { usePlatformContext } from "../../platform/PlatformContext";
import { canDeleteOwnVisualCopy } from "../visualization/visualAccess";
import { apiErrorMessage } from "../../services/apiClient";
import { runApplicationAction, type ApplicationModuleKey } from "../../services/applicationApi";
import { fetchPageDataRows, fetchPageDataWorkspace, patchPageDataWorkspaceMemory, readPageDataWorkspaceMemory, type PageDataAsset, type PageDataPageCode, type PageDataRows } from "../../services/dataAssetApi";
import { pageDataBelongsToPage, resolvePageDataLayout } from "./assignment";
import { revealAnalysisWorkspace, replaceVisualAnalysisSourceGroup } from "../analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "../analysis-workspace/visualAnalysisScope";
import { revealContextRail } from "../context-rail/ContextSideRail";
import { AnalysisVisualCard, type VisualizationCardConfig } from "../self-analysis/ResultViews";
import { ResizableVisualizationGrid } from "../self-analysis/ResizableVisualizationGrid";
import { readVisualGridItemSize, visualDuplicateLayout } from "../self-analysis/visualGridLayout";
import { pageDataToSelection, type AnalysisRow, type VisualizationType } from "../self-analysis/domain";
import { askConfirm } from "../ui/ConfirmDialog";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "../ui/FormDialog";
import { AppSelect } from "../ui/AppSelect";
import { applyReportPageStyleToCards, normalizeReportPageStyleId, ReportPageStyleButton, ReportPageStyleSurface, type ReportPageStyleId } from "../report-style/reportPageStyles";
import { moveReportPublicFilterControl, normalizeReportPublicFilterPositions, orderedReportPublicFilterControls, PublicFilterFieldChip, type ReportPublicFilterControlRef, type ReportPublicFilterGroup } from "../report-filters/ReportPublicFilters";

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
  autoSave?: boolean;
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

export type PageDataCard = {
  id: string;
  sourceAssetId: string;
  title: string;
  type: VisualizationType;
  config: VisualizationCardConfig;
};

export type PageDataPublicFilterGroup = ReportPublicFilterGroup;

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

function applyWorkspace(workspace: { assets?: PageDataAsset[]; layout?: string[]; cards?: unknown[]; public_filters?: unknown[]; page_style_id?: unknown; notes?: unknown[]; rows?: Record<string, PageDataRows>; row_errors?: Record<string, string> }, pageCode: PageDataPageCode) {
  const available = (workspace.assets || []).filter((asset) => pageDataBelongsToPage(asset, pageCode));
  const availableIds = available.map((asset) => asset.id);
  const resolvedLayout = resolvePageDataLayout(workspace.layout || [], availableIds, {
    includeNewlyAssigned: true,
  });
  const cards = normalizePageDataCards(workspace.cards, available, resolvedLayout);
  return {
    assets: available,
    cards,
    publicFilters: normalizePageDataPublicFilters(workspace.public_filters, availableIds),
    pageStyleId: normalizeReportPageStyleId(workspace.page_style_id),
    layoutIds: cards.map((card) => card.sourceAssetId),
    notes: normalizePageDataNotes(workspace.notes, new Set(resolvedLayout)),
    rowsById: workspace.rows || {},
    rowsFailed: Object.fromEntries(
      Object.entries(workspace.row_errors || {}).map(([assetId, error]) => [assetId, pageDataRowErrorMessage(error)]),
    ),
  };
}

export function usePageDataComposer({ pageCode, moduleKey, railPageKey, refreshKey, autoSave = false }: PageDataComposerOptions) {
  const { tenantId, userId, isSuperAdmin } = usePlatformContext();
  const cached = readPageDataWorkspaceMemory(tenantId, userId, pageCode);
  const initial = cached ? applyWorkspace(cached, pageCode) : null;
  const [assets, setAssets] = useState<PageDataAsset[]>(initial?.assets || []);
  const [cards, setCards] = useState<PageDataCard[]>(initial?.cards || []);
  const [savedCards, setSavedCards] = useState<PageDataCard[]>(initial?.cards || []);
  const [publicFilters, setPublicFilters] = useState<PageDataPublicFilterGroup[]>(initial?.publicFilters || []);
  const [savedPublicFilters, setSavedPublicFilters] = useState<PageDataPublicFilterGroup[]>(initial?.publicFilters || []);
  const [pageStyleId, setPageStyleId] = useState<ReportPageStyleId>(initial?.pageStyleId || normalizeReportPageStyleId(undefined));
  const [savedPageStyleId, setSavedPageStyleId] = useState<ReportPageStyleId>(initial?.pageStyleId || normalizeReportPageStyleId(undefined));
  const [rowsById, setRowsById] = useState<Record<string, PageDataRows>>(initial?.rowsById || {});
  const [rowsFailed, setRowsFailed] = useState<Record<string, string>>(initial?.rowsFailed || {});
  const [mode, setMode] = useState<ComposerMode>(autoSave && isSuperAdmin ? "edit" : "browse");
  const [loading, setLoading] = useState(!initial);
  const [notice, setNotice] = useState("");
  const [draggingId, setDraggingId] = useState("");
  const [savingLayout, setSavingLayout] = useState(false);
  const [notes, setNotes] = useState<PageDataNote[]>(initial?.notes || []);
  const requestRef = useRef(0);
  const cardsRef = useRef(cards);
  const notesRef = useRef(notes);
  const publicFiltersRef = useRef(publicFilters);
  const pageStyleIdRef = useRef(pageStyleId);
  cardsRef.current = cards;
  notesRef.current = notes;
  publicFiltersRef.current = publicFilters;
  pageStyleIdRef.current = pageStyleId;

  useEffect(() => {
    if (autoSave && isSuperAdmin) setMode("edit");
  }, [autoSave, isSuperAdmin]);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++requestRef.current;
    if (!readPageDataWorkspaceMemory(tenantId, userId, pageCode)) setLoading(true);
    fetchPageDataWorkspace({ tenantId, userId, pageCode }).then((workspace) => {
      if (cancelled || requestRef.current !== requestId) return;
      const next = applyWorkspace(workspace, pageCode);
      setAssets(next.assets);
      setCards(next.cards);
      setSavedCards(next.cards);
      setPublicFilters(next.publicFilters);
      setSavedPublicFilters(next.publicFilters);
      setPageStyleId(next.pageStyleId);
      pageStyleIdRef.current = next.pageStyleId;
      setSavedPageStyleId(next.pageStyleId);
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

  const layoutIds = useMemo(() => cards.map((card) => card.sourceAssetId), [cards]);
  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const visibleAssets = useMemo(() => Array.from(new Map(layoutIds.flatMap((id) => {
    const asset = assetById.get(id);
    return asset ? [[id, asset] as const] : [];
  })).values()), [assetById, layoutIds]);
  const visualTypes = useMemo(() => Object.fromEntries(cards.map((card) => [card.id, card.type])), [cards]);
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
    const availableCards = new Map<string, PageDataCard[]>();
    for (const card of cardsRef.current) {
      const queue = availableCards.get(card.sourceAssetId) || [];
      queue.push(card);
      availableCards.set(card.sourceAssetId, queue);
    }
    const nextCards = nextIds.flatMap((sourceAssetId) => {
      const existing = availableCards.get(sourceAssetId)?.shift();
      if (existing) return [existing];
      const asset = assetById.get(sourceAssetId);
      return asset ? [createPageDataCard(asset)] : [];
    });
    setCards(nextCards);
    cardsRef.current = nextCards;
    setNotes((current) => current.filter((note) => nextIds.includes(note.sourceAssetId)));
    const nextIdSet = new Set(nextIds);
    const nextPublicFilters = normalizeReportPublicFilterPositions(publicFiltersRef.current.flatMap((group) => {
      const datasetIds = group.datasetIds.filter((datasetId) => nextIdSet.has(datasetId));
      return datasetIds.length ? [{ ...group, datasetIds }] : [];
    }));
    setPublicFilters(nextPublicFilters);
    publicFiltersRef.current = nextPublicFilters;
    setNotice("");
    scheduleAutoSave(nextCards);
  };

  const measuredCards = (source: PageDataCard[]) => source.map((card) => {
    const size = readVisualGridItemSize(card.id);
    if (!size?.span && !size?.height) return card;
    return { ...card, config: { ...card.config, layoutSpan: size.span, layoutHeight: size.height } };
  });

  const writeLayout = async (nextCards: PageDataCard[], nextNotes: PageDataNote[], restoreOnFailure: boolean, nextPublicFilters = publicFiltersRef.current, keepalive = false, nextPageStyleId = pageStyleIdRef.current) => {
    setSavingLayout(true);
    setNotice("");
    const sourceIds = Array.from(new Set(nextCards.map((card) => card.sourceAssetId)));
    try {
      const response = await runApplicationAction<{ pageDataCards?: PageDataCard[]; pageDataPublicFilters?: PageDataPublicFilterGroup[]; pageReportStyleId?: string }>({
        tenantId,
        userId,
        moduleKey,
        action: "set_page_data_layout",
        payload: { assetIds: sourceIds, cards: nextCards, publicFilters: nextPublicFilters, pageStyleId: nextPageStyleId, notes: nextNotes },
        keepalive,
      });
      const acknowledged = normalizePageDataCards(response.module.state.pageDataCards, assets, nextCards.map((card) => card.sourceAssetId));
      setCards(acknowledged);
      cardsRef.current = acknowledged;
      setSavedCards(acknowledged);
      const acknowledgedFilters = normalizePageDataPublicFilters(response.module.state.pageDataPublicFilters, sourceIds);
      setPublicFilters(acknowledgedFilters);
      publicFiltersRef.current = acknowledgedFilters;
      setSavedPublicFilters(acknowledgedFilters);
      const acknowledgedStyleId = normalizeReportPageStyleId(response.module.state.pageReportStyleId || nextPageStyleId);
      setPageStyleId(acknowledgedStyleId);
      pageStyleIdRef.current = acknowledgedStyleId;
      setSavedPageStyleId(acknowledgedStyleId);
      patchPageDataWorkspaceMemory(tenantId, userId, pageCode, {
        layout: sourceIds,
        cards: acknowledged,
        public_filters: acknowledgedFilters,
        page_style_id: acknowledgedStyleId,
        notes: nextNotes,
      });
      return true;
    } catch (error) {
      if (restoreOnFailure) {
        setCards(savedCards);
        cardsRef.current = savedCards;
        setPublicFilters(savedPublicFilters);
        publicFiltersRef.current = savedPublicFilters;
        setPageStyleId(savedPageStyleId);
        pageStyleIdRef.current = savedPageStyleId;
      }
      setNotice(apiErrorMessage(error, autoSave ? "周报图表自动保存失败；当前修改尚未由服务端确认。" : "页面布局保存失败，已恢复上次保存的布局。"));
      return false;
    } finally {
      setSavingLayout(false);
    }
  };

  const saveLayout = async () => {
    if (mode !== "edit") return true;
    return writeLayout(measuredCards(cardsRef.current), notesRef.current, !autoSave);
  };

  const autoSaveTimer = useRef<number | null>(null);
  function scheduleAutoSave(nextCards: PageDataCard[]) {
    if (!autoSave || !isSuperAdmin) return;
    if (autoSaveTimer.current !== null) window.clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = window.setTimeout(() => {
      void writeLayout(measuredCards(nextCards), notesRef.current, false);
    }, 700);
  }

  const toggleAsset = (assetId: string) => {
    const next = layoutIds.includes(assetId) ? layoutIds.filter((id) => id !== assetId) : [...layoutIds, assetId];
    if (!next.includes(assetId)) setNotes((current) => current.filter((note) => note.sourceAssetId !== assetId));
    void commitLayout(next);
  };

  const notesSaveTimer = useRef<number | null>(null);
  const writeNotes = async (next: PageDataNote[], keepalive = false) => {
    try {
      await runApplicationAction({ tenantId, userId, moduleKey, action: "set_page_data_notes", payload: { notes: next }, keepalive });
      patchPageDataWorkspaceMemory(tenantId, userId, pageCode, { notes: next });
    } catch (error) {
      setNotice(apiErrorMessage(error, "文本框保存失败。"));
    }
  };
  const scheduleWriteNotes = (next: PageDataNote[]) => {
    if (notesSaveTimer.current !== null) window.clearTimeout(notesSaveTimer.current);
    notesSaveTimer.current = window.setTimeout(() => { void writeNotes(next); }, 700);
  };

  const flushPendingWritesRef = useRef<() => void>(() => undefined);
  flushPendingWritesRef.current = () => {
    const hasLayoutWrite = autoSaveTimer.current !== null;
    const hasNotesWrite = notesSaveTimer.current !== null;
    if (autoSaveTimer.current !== null) {
      window.clearTimeout(autoSaveTimer.current);
      autoSaveTimer.current = null;
    }
    if (notesSaveTimer.current !== null) {
      window.clearTimeout(notesSaveTimer.current);
      notesSaveTimer.current = null;
    }
    if (hasLayoutWrite) {
      void writeLayout(measuredCards(cardsRef.current), notesRef.current, false, publicFiltersRef.current, true);
    } else if (hasNotesWrite) {
      void writeNotes(notesRef.current, true);
    }
  };

  useEffect(() => {
    const flushOnPageHide = () => flushPendingWritesRef.current();
    const flushOnVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushPendingWritesRef.current();
    };
    window.addEventListener("pagehide", flushOnPageHide);
    document.addEventListener("visibilitychange", flushOnVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", flushOnPageHide);
      document.removeEventListener("visibilitychange", flushOnVisibilityChange);
      flushPendingWritesRef.current();
    };
  }, []);

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
    const source = cardsRef.current.find((card) => card.id === draggingId);
    if (!source) return;
    const nextCards = cardsRef.current.filter((card) => card.id !== draggingId);
    const targetIndex = nextCards.findIndex((card) => card.id === targetId);
    nextCards.splice(targetIndex < 0 ? nextCards.length : targetIndex, 0, source);
    setCards(nextCards);
    cardsRef.current = nextCards;
    setDraggingId("");
    scheduleAutoSave(nextCards);
  };

  const openRail = (asset: PageDataAsset, tab: "analysis" | "comments", detail?: { selectedText?: string; dataTables?: ReturnType<typeof pageDataToSelection>[]; label?: string; targetId?: string }) => {
    const rows = rowsById[asset.id];
    const selectedTable = detail?.dataTables?.[0] || pageDataToSelection(asset);
    const selectedCard = cardsRef.current.find((card) => card.id === detail?.targetId || card.sourceAssetId === asset.id);
    const selectedType = selectedCard?.type || asset.visualizationType as VisualizationType;
    const selectedDataPoint = {
      targetId: detail?.targetId || `page-data:${asset.id}`,
      targetType: selectedType === "table" || selectedType === "pivot" ? "table" as const : "chart" as const,
      label: detail?.label || asset.name,
      values: {
        page_data_id: asset.id,
        source_table_name: asset.sourceTableName,
        metric_fields: asset.metricFields,
        dimension_fields: asset.dimensionFields,
        visualization_type: selectedType,
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

  const applyPageStyle = (nextStyleId: ReportPageStyleId) => {
    const nextCards = applyReportPageStyleToCards(cardsRef.current, nextStyleId);
    const nextNotes: PageDataNote[] = applyReportPageStyleToCards(
      notesRef.current.map((note) => ({ ...note, type: note.type || "text" as VisualizationType })),
      nextStyleId,
    );
    setPageStyleId(nextStyleId);
    pageStyleIdRef.current = nextStyleId;
    setCards(nextCards);
    cardsRef.current = nextCards;
    setNotes(nextNotes);
    notesRef.current = nextNotes;
    scheduleAutoSave(nextCards);
  };

  return {
    pageCode,
    assets,
    cards,
    publicFilters,
    pageStyleId,
    layoutIds,
    visibleAssets,
    hasSelectedPageData,
    hasRenderablePageData,
    waitingForPageDataRows,
    rowsById,
    rowsFailed,
    visualTypes,
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
    applyPageStyle,
    notes,
    addTextCard,
    updateCard: (cardId: string, patch: Partial<PageDataCard>) => {
      const next = cardsRef.current.map((card) => card.id === cardId ? { ...card, ...patch } : card);
      if (JSON.stringify(next) === JSON.stringify(cardsRef.current)) return;
      setCards(next);
      cardsRef.current = next;
      scheduleAutoSave(next);
    },
    updateCardLayout: (cardId: string, size: { span: number; height: number }) => {
      const next = cardsRef.current.map((card) => card.id === cardId ? { ...card, config: { ...card.config, layoutSpan: size.span, layoutHeight: size.height } } : card);
      setCards(next);
      cardsRef.current = next;
      scheduleAutoSave(next);
    },
    duplicateCard: (cardId: string, config: VisualizationCardConfig) => {
      const index = cardsRef.current.findIndex((card) => card.id === cardId);
      if (index < 0) return;
      const source = cardsRef.current[index];
      const duplicate: PageDataCard = {
        ...source,
        id: createClientUuid(),
        title: `${source.title} · 副本`,
        config: { ...config, ...visualDuplicateLayout(cardId) },
      };
      const next = [...cardsRef.current];
      next.splice(index + 1, 0, duplicate);
      setCards(next);
      cardsRef.current = next;
      scheduleAutoSave(next);
    },
    replacePublicFilters: (next: PageDataPublicFilterGroup[]) => {
      setPublicFilters(next);
      publicFiltersRef.current = next;
      scheduleAutoSave(cardsRef.current);
    },
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

function defaultPageDataCardConfig(asset: PageDataAsset): VisualizationCardConfig {
  return {
    metricFields: asset.metricFields,
    dimensionFields: asset.dimensionFields,
    filters: {},
    filterGroups: [],
    sumFilteredRows: false,
    comboLineFields: [],
  };
}

function defaultEmptyVisualizationConfig(): VisualizationCardConfig {
  return { metricFields: [], dimensionFields: [], filters: {}, filterGroups: [], sumFilteredRows: false, comboLineFields: [] };
}

function createPageDataCard(asset: PageDataAsset, index = 0): PageDataCard {
  return {
    id: `page-data:${asset.id}:${index}`.slice(0, 160),
    sourceAssetId: asset.id,
    title: asset.name,
    type: asset.visualizationType as VisualizationType,
    config: defaultPageDataCardConfig(asset),
  };
}

function normalizePageDataCards(value: unknown, assets: PageDataAsset[], layout: string[]): PageDataCard[] {
  const assetById = new Map(assets.map((asset) => [asset.id, asset]));
  const seen = new Set<string>();
  const cards = (Array.isArray(value) ? value : []).flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const id = typeof record.id === "string" ? record.id.trim() : "";
    const sourceAssetId = typeof record.sourceAssetId === "string" ? record.sourceAssetId.trim() : "";
    const asset = assetById.get(sourceAssetId);
    if (!id || seen.has(id) || !asset) return [];
    seen.add(id);
    const rawConfig = record.config && typeof record.config === "object" && !Array.isArray(record.config)
      ? record.config as Partial<VisualizationCardConfig>
      : {};
    return [{
      id,
      sourceAssetId,
      title: typeof record.title === "string" && record.title.trim() ? record.title.trim() : asset.name,
      type: typeof record.type === "string" ? record.type as VisualizationType : asset.visualizationType as VisualizationType,
      config: { ...defaultPageDataCardConfig(asset), ...rawConfig },
    }];
  });
  const represented = new Set(cards.map((card) => card.sourceAssetId));
  for (const [index, sourceAssetId] of layout.entries()) {
    if (represented.has(sourceAssetId)) continue;
    const asset = assetById.get(sourceAssetId);
    if (!asset) continue;
    cards.push(createPageDataCard(asset, index));
    represented.add(sourceAssetId);
  }
  return cards;
}

function normalizePageDataPublicFilters(value: unknown, availableIds: string[]): PageDataPublicFilterGroup[] {
  const allowed = new Set(availableIds);
  const seen = new Set<string>();
  const groups = (Array.isArray(value) ? value : []).flatMap((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const id = typeof record.id === "string" ? record.id.trim() : "";
    const datasetIds = Array.isArray(record.datasetIds)
      ? Array.from(new Set(record.datasetIds.map(String).map((item) => item.trim()).filter((item) => allowed.has(item))))
      : [];
    const fields = Array.isArray(record.fields) ? Array.from(new Set(record.fields.map(String).map((item) => item.trim()).filter(Boolean))) : [];
    if (!id || seen.has(id) || !datasetIds.length || !fields.length) return [];
    seen.add(id);
    const rawSelections = record.selections && typeof record.selections === "object" && !Array.isArray(record.selections)
      ? record.selections as Record<string, unknown>
      : {};
    const order = Array.isArray(record.controlOrder)
      ? record.controlOrder.map(String).filter((field) => fields.includes(field))
      : [];
    const rawPositions = record.controlPositions && typeof record.controlPositions === "object" && !Array.isArray(record.controlPositions)
      ? record.controlPositions as Record<string, unknown>
      : {};
    return [{
      id,
      name: typeof record.name === "string" && record.name.trim() ? record.name.trim() : `公共筛选 ${index + 1}`,
      datasetIds,
      fields,
      controlOrder: Array.from(new Set([...order, ...fields])),
      controlPositions: Object.fromEntries(fields.flatMap((field) => typeof rawPositions[field] === "number" && Number.isFinite(rawPositions[field]) ? [[field, Number(rawPositions[field])]] : [])),
      selections: Object.fromEntries(fields.map((field) => [field, String(rawSelections[field] || "")])),
    }];
  });
  return normalizeReportPublicFilterPositions(groups);
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

export function PageDataPublicFilterButton({ controller, className = "" }: { controller: PageDataComposerController; className?: string }) {
  const [open, setOpen] = useState(false);
  const [draftGroups, setDraftGroups] = useState<PageDataPublicFilterGroup[]>([]);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]);
  const [removedFields, setRemovedFields] = useState<string[]>([]);
  const [name, setName] = useState("");
  const selectedAssets = controller.visibleAssets.filter((asset) => selectedDatasetIds.includes(asset.id));
  const commonFields = useMemo(() => {
    if (!selectedAssets.length) return [];
    const intersection = selectedAssets.slice(1).reduce(
      (current, asset) => current.filter((field) => asset.sourceFields.some((candidate) => candidate.fieldNameEn === field.fieldNameEn)),
      selectedAssets[0].sourceFields,
    );
    return intersection.filter((field) => !removedFields.includes(field.fieldNameEn));
  }, [removedFields, selectedAssets]);

  const begin = () => {
    setDraftGroups(controller.publicFilters);
    setSelectedDatasetIds([]);
    setRemovedFields([]);
    setName("");
    setOpen(true);
  };
  const addDraftGroup = () => {
    if (!selectedDatasetIds.length || !commonFields.length) return;
    setDraftGroups((current) => normalizeReportPublicFilterPositions([...current, {
      id: createClientUuid(),
      name: name.trim() || `公共筛选 ${current.length + 1}`,
      datasetIds: selectedDatasetIds,
      fields: commonFields.map((field) => field.fieldNameEn),
      controlOrder: commonFields.map((field) => field.fieldNameEn),
      selections: {},
    }]));
    setSelectedDatasetIds([]);
    setRemovedFields([]);
    setName("");
  };

  return <>
    <button type="button" onClick={begin} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#cfe0d6] bg-white px-3 text-[10px] text-[#3f7656] hover:bg-[#f3f8f5] ${className}`} data-page-public-filter-button="true"><SlidersHorizontal className="h-3.5 w-3.5" />公共筛选{controller.publicFilters.length ? ` ${controller.publicFilters.length}` : ""}</button>
    <FormDialog
      open={open}
      title="公共筛选"
      description="选择多个数据集后，仅保留它们共有的字段。右键字段可从当前分组移除。"
      widthClassName="max-w-[820px]"
      heightClassName="max-h-[86vh]"
      zIndexClassName="z-[180]"
      onClose={() => setOpen(false)}
      bodyClassName="space-y-4"
      overlayDataAttributes={{ "data-page-public-filter-dialog": "true" }}
      footer={<>
        <FormDialogCancelButton onClick={() => setOpen(false)} />
        <button type="button" disabled={!selectedDatasetIds.length || !commonFields.length} onClick={addDraftGroup} className="inline-flex h-9 items-center rounded-lg border border-[#cfe0d6] bg-white px-4 text-[11px] text-[#34704d] disabled:opacity-40" data-page-public-filter-save-group="true">保存</button>
        <FormDialogPrimaryButton onClick={() => { controller.replacePublicFilters(draftGroups); setOpen(false); }} data-page-public-filter-confirm="true">确认</FormDialogPrimaryButton>
      </>}
    >
      <section className="rounded-xl border border-[#e1e8e4] bg-[#f8faf9] p-3" data-page-public-filter-common-fields="true">
        <div className="flex items-center justify-between gap-3"><span className="text-[11px] text-[#4f5d55]">公共字段</span><span className="text-[9px] text-[#98a19c]">右键移除</span></div>
        <div className="mt-2 flex min-h-9 flex-wrap gap-2">
          {commonFields.map((field) => <PublicFilterFieldChip key={field.fieldNameEn} field={field.fieldNameEn} label={field.fieldNameCn || field.fieldNameEn} onRemove={() => setRemovedFields((current) => [...current, field.fieldNameEn])} />)}
          {!selectedDatasetIds.length ? <span className="py-2 text-[10px] text-[#9aa39e]">请先在下方选择数据集</span> : !commonFields.length ? <span className="py-2 text-[10px] text-[#b42318]">所选数据集没有可用的公共字段</span> : null}
        </div>
      </section>
      <section>
        <label className="text-[10px] text-[#69756e]">分组名称</label>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder={`公共筛选 ${draftGroups.length + 1}`} className="mt-1 h-9 w-full rounded-lg border border-[#dfe5e1] bg-white px-3 text-[11px] outline-none focus:border-[#7fb596]" />
      </section>
      <section data-page-public-filter-datasets="true">
        <div className="mb-2 text-[11px] text-[#4f5d55]">可用数据集</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {controller.visibleAssets.map((asset) => {
            const selected = selectedDatasetIds.includes(asset.id);
            return <button key={asset.id} type="button" onClick={() => { setSelectedDatasetIds((current) => selected ? current.filter((id) => id !== asset.id) : [...current, asset.id]); setRemovedFields([]); }} className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-left ${selected ? "border-[#75b492] bg-[#edf8f1]" : "border-[#e2e7e4] bg-white hover:bg-[#f8faf9]"}`}><span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${selected ? "border-[#178a53] bg-[#178a53] text-white" : "border-[#cfd7d2] text-transparent"}`}><Check className="h-3 w-3" /></span><span className="min-w-0"><span className="block truncate text-[11px] text-[#27342c]">{asset.name}</span><span className="mt-0.5 block truncate text-[9px] text-[#8f9993]">{asset.sourceTableName}</span></span></button>;
          })}
          {!controller.visibleAssets.length ? <span className="px-3 py-8 text-center text-[10px] text-[#9aa39e] sm:col-span-2">当前报表还没有可用于联合筛选的数据集</span> : null}
        </div>
      </section>
      {draftGroups.length ? <section className="space-y-2 border-t border-[#edf0ee] pt-3" data-page-public-filter-saved-groups="true">
        <div className="text-[11px] text-[#4f5d55]">已保存分组</div>
        {draftGroups.map((group) => <div key={group.id} className="flex items-center justify-between gap-3 rounded-lg border border-[#e2e7e4] bg-white px-3 py-2"><div className="min-w-0"><div className="truncate text-[11px] text-[#27342c]">{group.name}</div><div className="mt-0.5 truncate text-[9px] text-[#8f9993]">{group.datasetIds.length} 个数据集 · {group.fields.length} 个字段</div></div><button type="button" onClick={() => setDraftGroups((current) => current.filter((item) => item.id !== group.id))} className="flex h-7 w-7 items-center justify-center rounded-md text-[#8d9690] hover:bg-[#fff1f1] hover:text-[#c62828]" aria-label={`删除${group.name}`}><X className="h-3.5 w-3.5" /></button></div>)}
      </section> : null}
    </FormDialog>
  </>;
}

export function PageDataPublicFilterControls({ controller, className = "mb-3" }: { controller: PageDataComposerController; className?: string }) {
  const [dragging, setDragging] = useState<ReportPublicFilterControlRef | null>(null);
  const draggingRef = useRef<ReportPublicFilterControlRef | null>(null);
  if (!controller.publicFilters.length) return null;
  const labels = Object.assign({}, ...controller.assets.map((asset) => Object.fromEntries(asset.sourceFields.map((field) => [field.fieldNameEn, field.fieldNameCn || field.fieldNameEn]))));
  const values = (group: PageDataPublicFilterGroup, field: string) => Array.from(new Set(group.datasetIds.flatMap((datasetId) => (controller.rowsById[datasetId]?.rows || []).map((row) => String(row[field] ?? "—"))))).sort((a, b) => a.localeCompare(b, "zh-CN")).slice(0, 200);
  const move = (target: ReportPublicFilterControlRef) => {
    const source = draggingRef.current || dragging;
    if (!source) return;
    controller.replacePublicFilters(moveReportPublicFilterControl(controller.publicFilters, source, target));
    draggingRef.current = null;
    setDragging(null);
  };
  const controls = orderedReportPublicFilterControls(controller.publicFilters);
  return <div className={`${className} flex flex-wrap items-end gap-2 rounded-xl border border-[#e1e8e4] bg-[#f8faf9] p-3`} data-page-public-filter-controls="true">
    {controls.map(({ group, field }) => <label key={`${group.id}:${field}`} draggable={controller.mode === "edit"} onDragStart={() => { const source = { groupId: group.id, field }; draggingRef.current = source; setDragging(source); }} onDragEnd={() => { draggingRef.current = null; setDragging(null); }} onDragOver={(event) => { if (controller.mode === "edit") event.preventDefault(); }} onDrop={() => move({ groupId: group.id, field })} className="min-w-[160px] cursor-default" data-page-public-filter-control={field}>
      <span className="mb-1 flex items-center gap-1 text-[9px] text-[#7a8680]">{controller.mode === "edit" ? <GripVertical className="h-3 w-3 cursor-grab" /> : null}{group.name} · {labels[field] || field}</span>
      <AppSelect value={group.selections[field] || ""} onChange={(event) => controller.replacePublicFilters(controller.publicFilters.map((item) => item.id === group.id ? { ...item, selections: { ...item.selections, [field]: event.target.value } } : item))} className="h-9 w-full rounded-lg border border-[#dbe3de] bg-white px-2.5 text-[11px] text-[#27342c] outline-none focus:border-[#7fb596]"><option value="">全部</option>{values(group, field).map((value) => <option key={value} value={value}>{value}</option>)}</AppSelect>
    </label>)}
  </div>;
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
    cards,
    rowsById,
    rowsFailed,
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
    updateCard,
    updateCardLayout,
    duplicateCard,
    updateNote,
    removeNote,
    userId,
    isSuperAdmin,
  } = controller;
  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const renderedCards = assetIds?.length ? cards.filter((card) => assetIds.includes(card.sourceAssetId)) : cards;

  const pickerKind = pageCode === "dashboard" ? "多机构数据" : pageCode === "customer_segment_analysis" ? "分客群明细数据" : "单机构数据";
  const pickerSource = pageCode === "dashboard" ? "多机构页面" : pageCode === "customer_segment_analysis" ? "分客群页面" : "单机构页面";
  const picker = showAssetPicker && showEditorControls && mode === "edit" ? <div className="mb-3 rounded-xl border border-dashed border-[#cfe0d6] bg-white p-3" data-page-data-inline-picker="true">
    <div className="mb-2 flex items-center justify-between gap-3"><span className="text-[10px] text-[#7c8781]">选择要展示在{pageLabels[pageCode]}中的{pickerKind}</span><span className="flex items-center gap-2"><PageDataPublicFilterButton controller={controller} /><ReportPageStyleButton styleId={controller.pageStyleId} onSelect={controller.applyPageStyle} /></span></div>
    <div className="flex flex-wrap gap-2">{assets.map((asset) => { const selected = layoutIds.includes(asset.id); return <button key={asset.id} type="button" onClick={() => toggleAsset(asset.id)} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[10px] ${selected ? "border-[#75b492] bg-[#edf8f1] text-[#147d4f]" : "border-[#dfe7e2] bg-white text-[#59645e] hover:bg-[#f7faf8]"}`}><span className={`flex h-3.5 w-3.5 items-center justify-center rounded border ${selected ? "border-[#178a53] bg-[#178a53] text-white" : "border-[#cfd7d2] text-transparent"}`}><Check className="h-2.5 w-2.5" /></span>{asset.name}</button>; })}{!assets.length && <span className="text-[10px] text-[#a1a7a3]">暂无可用数据，请先在站内数据的“{pickerSource}”中新增。</span>}</div>
  </div> : null;

  if (!renderedCards.length) return picker;

  return (
    <ReportPageStyleSurface styleId={controller.pageStyleId} className={className} data-page-data-visualization-modules={pageCode}>
      {picker}
      {showAssetPicker ? <PageDataPublicFilterControls controller={controller} /> : null}
      <ResizableVisualizationGrid
        editable={layoutEditable && mode === "edit"}
        onLayoutChange={(id, size) => {
          if (cards.some((card) => card.id === id)) updateCardLayout(id, size);
          else updateNote(id, { config: { ...(notes.find((note) => note.id === id)?.config || defaultEmptyVisualizationConfig()), layoutSpan: size.span, layoutHeight: size.height } });
        }}
      >
        {renderedCards.flatMap((card, index) => {
          const asset = assetById.get(card.sourceAssetId);
          if (!asset) return [];
          const pageRows = rowsById[asset.id];
          const instanceKey = card.id;
          const analysisRows = pageRows ? applyPageDataPublicFilters(toAnalysisRows(asset, pageRows), asset.id, controller.publicFilters) : [];
          const sourceCard = <div
            key={instanceKey}
            className="flex h-full min-h-0 flex-col"
            draggable={showEditorControls && mode === "edit"}
            onDragStart={(event) => { if (!showEditorControls || mode !== "edit") return; setDraggingId(card.id); event.dataTransfer.effectAllowed = "move"; }}
            onDragEnd={() => setDraggingId("")}
            onDragOver={(event) => { if (showEditorControls && mode === "edit") event.preventDefault(); }}
            onDrop={() => { if (showEditorControls) moveAsset(card.id); }}
            data-page-data-card={asset.id}
            data-page-data-card-id={card.id}
            data-visual-grid-span={card.config.layoutSpan}
            data-visual-grid-height={card.config.layoutHeight}
          >
            {showEditorControls && mode === "edit" && <div className="mb-1 flex h-7 shrink-0 items-center justify-between rounded-lg bg-[#f6f8f7] px-2 text-[10px] text-[#7c8781]">
              <span className="inline-flex cursor-grab items-center gap-1 active:cursor-grabbing"><GripVertical className="h-3.5 w-3.5" />拖动排序</span>
              <button type="button" onClick={() => void askConfirm({ title: "移除图表", description: `确定从当前页面移除「${card.title}」？`, hint: "此操作不可撤销。" }).then((ok) => { if (ok) void commitLayout(layoutIds.filter((_, layoutIndex) => layoutIndex !== index)); })} className="inline-flex h-6 items-center gap-1 rounded-md px-2 hover:bg-[#fff0f0] hover:text-[#d93025]"><Trash2 className="h-3 w-3" />移除</button>
            </div>}
            <div className="min-h-0 flex-1">
              {!pageRows && !rowsFailed[asset.id] ? (
                <div className="flex h-full min-h-[220px] items-center justify-center rounded-xl border border-dashed border-[#e5e5ea] bg-[#fafbfc] text-[12px] text-[#8a8a8e]" data-page-data-rows-loading={asset.id}>正在加载页面数据…</div>
              ) : rowsFailed[asset.id] ? (
                <div className="flex h-full min-h-[220px] items-center justify-center rounded-xl border border-dashed border-[#ffd7d7] bg-[#fff5f5] px-4 text-center text-[12px] text-[#b42318]" data-page-data-rows-failed={asset.id}>{rowsFailed[asset.id]}</div>
              ) : <AnalysisVisualCard
                id={instanceKey}
                stateKey={`page-data:${pageCode}:${instanceKey}`}
                title={card.title}
                type={card.type}
                rows={analysisRows}
                initialConfig={card.config}
                configAuthority="server"
                compact
                fillHeight
                visualGridSpan={card.config.layoutSpan}
                visualGridHeight={card.config.layoutHeight}
                analysisSource={[pageDataToSelection(asset)]}
                onFollowUp={(detail) => openRail(asset, "analysis", detail)}
                onComment={(detail) => openRail(asset, "comments", detail)}
                onTypeChange={(type) => updateCard(card.id, { type })}
                onTitleChange={(title) => updateCard(card.id, { title })}
                onConfigChange={(config) => updateCard(card.id, { config })}
                onCreateText={(config) => addTextCard(asset.id, config, instanceKey)}
                onDuplicate={showEditorControls && mode === "edit" ? (config, options) => {
                  if (options?.asText) { addTextCard(asset.id, config, instanceKey); return; }
                  duplicateCard(card.id, config);
                } : (config, options) => { if (options?.asText) addTextCard(asset.id, config, instanceKey); }}
                onDelete={showEditorControls && mode === "edit" ? () => { void askConfirm({ title: "移除图表", description: `确定从当前页面移除「${card.title}」？`, hint: "此操作不可撤销。" }).then((ok) => { if (ok) void commitLayout(layoutIds.filter((_, layoutIndex) => layoutIndex !== index)); }); } : undefined}
              />}
            </div>
          </div>;
          const noteCards = cards.findIndex((candidate) => candidate.sourceAssetId === asset.id) === cards.findIndex((candidate) => candidate.id === card.id)
            ? notes.filter((note) => note.sourceAssetId === asset.id).map((note) => (
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
                  configAuthority="server"
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
            ))
            : [];
          return [sourceCard, ...noteCards];
        })}
      </ResizableVisualizationGrid>
    </ReportPageStyleSurface>
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

function applyPageDataPublicFilters(rows: AnalysisRow[], assetId: string, groups: PageDataPublicFilterGroup[]) {
  const rules = groups.flatMap((group) => group.datasetIds.includes(assetId)
    ? group.controlOrder.flatMap((field) => group.selections[field] ? [{ field, value: group.selections[field] }] : [])
    : []);
  if (!rules.length) return rows;
  return rows.filter((row) => rules.every((rule) => String(row.raw[rule.field] ?? "—") === rule.value));
}

function finiteNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(String(value ?? "").replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

export { pageDataScope } from "./assignment";
