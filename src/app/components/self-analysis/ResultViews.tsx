import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";
import { createPortal } from "react-dom";
import { trackInteraction } from "../../services/interactionTelemetry";
import { ArrowDown, ArrowUp, ArrowUpDown, AudioLines, Check, ChevronDown, Copy, Download, Ellipsis, Filter, MessageSquareText, Pin, Plus, SlidersHorizontal, Trash2, Type, X } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Funnel,
  FunnelChart,
  LabelList,
  Line,
  LineChart,
  Legend,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from "recharts";
import {
  analysisRawFields,
  displayRawCell,
  visualizationLabel,
  visualizationOptions,
  type AnalysisDataTableSelection,
  type AnalysisRow,
  type ResultVisualKey,
  type VisualizationType,
} from "./domain";
import { selectVisibleVisualPoints } from "../visualization/visualPointWindow";
import { useVisualizationVoiceCommand } from "../visualization/useVisualizationVoiceCommand";
import { insertVisualVoiceText, resolveVisualizationVoiceCommand } from "../visualization/visualizationCommand";
import { formatFieldValue, type FieldDisplayMetadata } from "../../data/fieldSemantics";
import { usePlatformContext } from "../../platform/PlatformContext";
import { normalizeNoteItems, noteItemsFromText, type RichNoteItem } from "../notes/richNote";
import { VisualNoteFields, VisualNoteTitle } from "../visualization/VisualNoteFields";
import { DataPageSelector, useClientPagination } from "../ui/DataPageSelector";
import {
  buildVisualDataPoints,
  defaultComboLineFields,
  filterVisualizationRows,
  groupRowsForMergedDimensions,
  legacyFiltersToFilterGroups,
  mergedDimensionCellSpan,
  metricTotal,
  moveVisualizationFieldWithinGroup,
  normalizeVisualizationFilterGroups,
  normalizeVisualizationSelections,
  numericValue,
  orderedTableFields,
  selectedTableFields,
  toggleVisualizationField,
  visualizationRoleFields,
  visualizationChartColor,
  visualizationFilterGroupsToLegacyFilters,
  visualizationFilterOperators,
  visualizationFilterValues,
  type VisualizationCardConfig,
  type VisualizationFilterGroup,
  type VisualizationFilterOperator,
  type VisualizationFilterRule,
  type VisualizationFilters,
} from "../visualization/visualizationDataModel";
import { nextTableSortState, sortTableRows, type TableSortState } from "../visualization/tableSort";

export type { VisualizationCardConfig } from "../visualization/visualizationDataModel";

export function RawDataTable({ rows, onDownload }: { rows: AnalysisRow[]; onDownload: () => void }) {
  const [mergedDimensionFields, setMergedDimensionFields] = useState<string[]>([]);
  const [frozenColumnFields, setFrozenColumnFields] = useState<string[]>([]);
  const [frozenRowKeys, setFrozenRowKeys] = useState<string[]>([]);
  const [headerMenu, setHeaderMenu] = useState<{ field: string; left: number; top: number } | null>(null);
  const [rowMenu, setRowMenu] = useState<{ rowKey: string; left: number; top: number } | null>(null);
  const [tableNotice, setTableNotice] = useState("");
  useEffect(() => {
    if (!tableNotice) return;
    const timer = window.setTimeout(() => setTableNotice(""), 4_000);
    return () => window.clearTimeout(timer);
  }, [tableNotice]);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (!(event.target instanceof Element)) return;
      if (!event.target.closest("[data-visual-table-header-menu], [data-visual-table-row-menu]")) {
        setHeaderMenu(null);
        setRowMenu(null);
      }
    };
    document.addEventListener("pointerdown", dismiss, true);
    return () => document.removeEventListener("pointerdown", dismiss, true);
  }, []);
  const freezeBlockedMessage = "有合并单元格的情况下，无法冻结，如需冻结请取消合并单元格";
  const clampMenu = (clientX: number, clientY: number, width: number) => ({ left: Math.max(8, Math.min(clientX, window.innerWidth - width - 8)), top: Math.max(8, Math.min(clientY, window.innerHeight - 160)) });
  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className="mb-3 flex items-center justify-between gap-3"><div><div className="text-[12px] text-[#1d1d1f]">可视化原始数据</div><div className="mt-0.5 text-[11px] text-[#aeaeb2]">当前图形对应的 SQL 返回数据，默认显示 20 条</div></div><button type="button" onClick={onDownload} disabled={!rows.length} className="inline-flex items-center gap-1 rounded-lg border border-[#e5e5ea] bg-white px-3 py-1.5 text-[11px] text-[#636366] hover:bg-[#f2f2f7] disabled:cursor-not-allowed disabled:opacity-40"><Download className="h-3 w-3" />下载数据</button></div>
      {tableNotice ? <div className="mb-2 rounded-lg border border-[#ead7b8] bg-[#fff8ee] px-3 py-2 text-[11px] leading-5 text-[#8a6a2b]" role="alert" data-visual-table-freeze-notice="true">{tableNotice}</div> : null}
      <ResultTable
        rows={rows.slice(0, 20)}
        emptyLabel="暂无 SQL 返回数据"
        mergedDimensionFields={mergedDimensionFields}
        frozenColumnFields={frozenColumnFields}
        frozenRowKeys={frozenRowKeys}
        onDimensionHeaderContextMenu={(field, event) => { event.preventDefault(); event.stopPropagation(); setRowMenu(null); setHeaderMenu({ field, ...clampMenu(event.clientX, event.clientY, 210) }); }}
        onRowContextMenu={(rowKey, event) => { event.preventDefault(); event.stopPropagation(); setHeaderMenu(null); setRowMenu({ rowKey, ...clampMenu(event.clientX, event.clientY, 188) }); }}
      />
      {headerMenu && createPortal(<div className="fixed z-[200] w-[210px] rounded-xl border border-[#dce7df] bg-white p-1.5 shadow-xl shadow-black/10" style={{ left: headerMenu.left, top: headerMenu.top }} data-visual-table-header-menu={headerMenu.field} data-visual-interactive="true">
        <button type="button" onClick={() => setHeaderMenu(null)} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-table-header-comment="true"><MessageSquareText className="h-3.5 w-3.5 text-[#178a53]" />评论</button>
        <button type="button" aria-pressed={mergedDimensionFields.includes(headerMenu.field)} onClick={() => { setMergedDimensionFields((current) => { const next = current.includes(headerMenu.field) ? current.filter((field) => field !== headerMenu.field) : [...current, headerMenu.field]; if (next.length) { setFrozenColumnFields([]); setFrozenRowKeys([]); } return next; }); setHeaderMenu(null); }} className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-merge-dimension={headerMenu.field}><span>{mergedDimensionFields.includes(headerMenu.field) ? "取消合并重复单元格" : "合并重复单元格"}</span>{mergedDimensionFields.includes(headerMenu.field) && <Check className="h-3.5 w-3.5 text-[#178a53]" />}</button>
        <button type="button" aria-pressed={frozenColumnFields.includes(headerMenu.field)} onClick={() => { if (mergedDimensionFields.length) { setTableNotice(freezeBlockedMessage); setHeaderMenu(null); return; } setFrozenColumnFields((current) => current.includes(headerMenu.field) ? current.filter((field) => field !== headerMenu.field) : [...current, headerMenu.field]); setHeaderMenu(null); }} className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-freeze-column={headerMenu.field}><span>{frozenColumnFields.includes(headerMenu.field) ? "取消冻结到首列" : "冻结到首列"}</span>{frozenColumnFields.includes(headerMenu.field) ? <Check className="h-3.5 w-3.5 text-[#178a53]" /> : <Pin className="h-3.5 w-3.5 text-[#8aa396]" />}</button>
      </div>, document.body)}
      {rowMenu && createPortal(<div className="fixed z-[200] w-[188px] rounded-xl border border-[#dce7df] bg-white p-1.5 shadow-xl shadow-black/10" style={{ left: rowMenu.left, top: rowMenu.top }} data-visual-table-row-menu={rowMenu.rowKey} data-visual-interactive="true">
        <button type="button" aria-pressed={frozenRowKeys.includes(rowMenu.rowKey)} onClick={() => { if (mergedDimensionFields.length) { setTableNotice(freezeBlockedMessage); setRowMenu(null); return; } setFrozenRowKeys((current) => current.includes(rowMenu.rowKey) ? current.filter((key) => key !== rowMenu.rowKey) : [...current, rowMenu.rowKey]); setRowMenu(null); }} className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-freeze-row={rowMenu.rowKey}><span>{frozenRowKeys.includes(rowMenu.rowKey) ? "取消冻结到首行" : "冻结到首行"}</span>{frozenRowKeys.includes(rowMenu.rowKey) ? <Check className="h-3.5 w-3.5 text-[#178a53]" /> : <Pin className="h-3.5 w-3.5 text-[#8aa396]" />}</button>
      </div>, document.body)}
    </div>
  );
}

type AnalysisVisualCardProps = {
  id: ResultVisualKey | string;
  stateKey?: string;
  title: string;
  type: VisualizationType;
  rows: AnalysisRow[];
  compact?: boolean;
  fillHeight?: boolean;
  showFollowUp?: boolean;
  analysisSource?: AnalysisDataTableSelection[];
  initialConfig?: Partial<VisualizationCardConfig>;
  onFollowUp: (detail?: VisualSelectionDetail) => void;
  onComment: (detail?: VisualSelectionDetail) => void;
  onTypeChange: (type: VisualizationType) => void;
  onTitleChange?: (title: string) => void;
  onConfigChange?: (config: VisualizationCardConfig) => void;
  onDuplicate?: (config: VisualizationCardConfig, options?: VisualDuplicateOptions) => void;
  onCreateText?: (config: VisualizationCardConfig) => void;
  onDelete?: () => void;
  visualGridSpan?: number;
  visualGridHeight?: number;
  visualGridMaxSpan?: number;
  visualGridMaxHeight?: number;
};

export type VisualSelectionDetail = { selectedText?: string; dataTables?: AnalysisDataTableSelection[] };
export type VisualDuplicateOptions = { asText?: boolean };

export function AnalysisVisualCard({ id, stateKey = id, title, type, rows, compact = false, fillHeight = false, showFollowUp = true, analysisSource, initialConfig, onFollowUp, onComment, onTypeChange, onTitleChange, onConfigChange, onDuplicate, onCreateText, onDelete, visualGridSpan, visualGridHeight, visualGridMaxSpan, visualGridMaxHeight }: AnalysisVisualCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const [moreMenuPos, setMoreMenuPos] = useState<{ top: number; left: number } | null>(null);
  const { tenantId, userId } = usePlatformContext();
  const fields = useMemo(() => analysisRawFields(rows), [rows]);
  const fieldLabels = rows[0]?.fieldLabels || {};
  const fieldMetadata = rows[0]?.fieldMetadata || {};
  const roleFields = useMemo(
    () => visualizationRoleFields(fields, fieldMetadata, numericRawFields(rows)),
    [fields, fieldMetadata, rows],
  );
  const numericFields = roleFields.metrics;
  const dimensionCandidates = roleFields.dimensions;
  const [metricFields, setMetricFields] = useState<string[]>(initialConfig?.metricFields || []);
  const [dimensionFields, setDimensionFields] = useState<string[]>(initialConfig?.dimensionFields || []);
  const [mergedDimensionFields, setMergedDimensionFields] = useState<string[]>(initialConfig?.mergedDimensionFields || []);
  const [frozenColumnFields, setFrozenColumnFields] = useState<string[]>(initialConfig?.frozenColumnFields || []);
  const [frozenRowKeys, setFrozenRowKeys] = useState<string[]>(initialConfig?.frozenRowKeys || []);
  const [filters, setFilters] = useState<VisualizationFilters>(initialConfig?.filters || {});
  const [filterGroups, setFilterGroups] = useState<VisualizationFilterGroup[]>(() => initialConfig?.filterGroups?.length ? normalizeVisualizationFilterGroups(initialConfig.filterGroups) : legacyFiltersToFilterGroups(initialConfig?.filters || {}));
  const [sumFilteredRows, setSumFilteredRows] = useState(Boolean(initialConfig?.sumFilteredRows));
  const [comboLineFields, setComboLineFields] = useState<string[]>(initialConfig?.comboLineFields || []);
  const [draftFilterGroups, setDraftFilterGroups] = useState<VisualizationFilterGroup[]>([]);
  const [draftSumRows, setDraftSumRows] = useState(false);
  const [showData, setShowData] = useState(false);
  const [operationsOpen, setOperationsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const filterSnapshotRef = useRef<{ filterGroups: VisualizationFilterGroup[]; filters: VisualizationFilters; sumFilteredRows: boolean } | null>(null);
  const [activePanel, setActivePanel] = useState<"style" | "metric" | "dimension" | null>(null);
  const [commentPoint, setCommentPoint] = useState<{ left: number; top: number } | null>(null);
  const [tableHeaderMenu, setTableHeaderMenu] = useState<{ field: string; left: number; top: number } | null>(null);
  const [tableRowMenu, setTableRowMenu] = useState<{ rowKey: string; left: number; top: number } | null>(null);
  const [commandNotice, setCommandNotice] = useState("");
  const [tableNotice, setTableNotice] = useState("");
  const [voiceNoticeVisible, setVoiceNoticeVisible] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState(title);
  const [noteTitle, setNoteTitle] = useState(initialConfig?.noteTitle || "");
  const [noteBody, setNoteBody] = useState(initialConfig?.noteBody || "");
  const [noteItems, setNoteItems] = useState<RichNoteItem[]>(() => {
    const savedItems = normalizeNoteItems(initialConfig?.noteItems);
    return savedItems.length ? savedItems : noteItemsFromText(initialConfig?.noteBody || "", "visual_note");
  });
  const [noteTitleHidden, setNoteTitleHidden] = useState(Boolean(initialConfig?.noteTitleHidden));
  const [cardType, setCardType] = useState<VisualizationType>(type);
  useEffect(() => { setCardType(type); }, [type]);
  const applyType = (next: VisualizationType) => {
    setCardType(next);
    if (next === "text") {
      setOperationsOpen(false);
      setActivePanel(null);
      setMoreOpen(false);
    }
    onTypeChange(next);
  };
  const cardStateHydratedRef = useRef("");
  const cardStateSkipSaveRef = useRef(false);
  const onConfigChangeRef = useRef(onConfigChange);
  const trackVisual = (eventName: string, extension: Record<string, unknown> = {}) => trackInteraction({ eventName, chartId: String(id), chartName: title, resourceType: "visualization", resourceId: String(id), extension });
  const passWheelToPage = (event: ReactWheelEvent<HTMLDivElement>) => {
    if (!event.deltaY) return;
    const origin = event.target instanceof Element ? event.target : null;
    const tableScroller = origin?.closest<HTMLElement>("[data-visual-table-scroll]");
    if (tableScroller && tableScroller.scrollHeight > tableScroller.clientHeight + 1) {
      tableScroller.scrollTop += event.deltaY;
      event.stopPropagation();
      return;
    }
    const scrollOwner = event.currentTarget.closest<HTMLElement>('[data-agent-main-shell="true"]');
    if (!scrollOwner || scrollOwner.scrollHeight <= scrollOwner.clientHeight) return;
    // Stop chart libraries from consuming the wheel gesture. Keep the browser's
    // passive event contract intact: explicitly move the app shell and do not
    // call preventDefault, which React's passive listener would reject.
    scrollOwner.scrollBy({ top: event.deltaY, behavior: "auto" });
    event.stopPropagation();
  };
  useEffect(() => { onConfigChangeRef.current = onConfigChange; }, [onConfigChange]);

  const currentConfig = useMemo<VisualizationCardConfig>(() => ({
    metricFields,
    dimensionFields,
    mergedDimensionFields,
    frozenColumnFields,
    frozenRowKeys,
    filters,
    filterGroups,
    sumFilteredRows,
    comboLineFields,
    noteTitle,
    noteBody,
    noteItems,
    noteTitleHidden,
    layoutSpan: visualGridSpan,
    layoutHeight: visualGridHeight,
    maxLayoutSpan: visualGridMaxSpan,
    maxLayoutHeight: visualGridMaxHeight,
  }), [comboLineFields, dimensionFields, filterGroups, filters, frozenColumnFields, frozenRowKeys, mergedDimensionFields, metricFields, noteBody, noteItems, noteTitle, noteTitleHidden, sumFilteredRows, visualGridHeight, visualGridMaxHeight, visualGridMaxSpan, visualGridSpan]);

  useEffect(() => { if (!editingTitle) setDraftTitle(title); }, [editingTitle, title]);

  const commitTitle = () => {
    const next = draftTitle.trim() || title;
    setDraftTitle(next);
    setEditingTitle(false);
    if (next !== title) onTitleChange?.(next);
  };

  useEffect(() => {
    const key = `sda:visual-card:v2:${window.location.pathname}:${stateKey}`;
    if (cardStateHydratedRef.current === key) return;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || "null") as (Partial<VisualizationCardConfig> & { showData?: boolean }) | null;
      const source = saved || initialConfig;
      if (source) {
        if (Array.isArray(source.metricFields)) setMetricFields(source.metricFields);
        if (Array.isArray(source.dimensionFields)) setDimensionFields(source.dimensionFields);
        if (Array.isArray(source.mergedDimensionFields)) setMergedDimensionFields(source.mergedDimensionFields);
        if (Array.isArray(source.frozenColumnFields)) setFrozenColumnFields(source.frozenColumnFields);
        if (Array.isArray(source.frozenRowKeys)) setFrozenRowKeys(source.frozenRowKeys);
        if (source.filters) setFilters(source.filters);
        setFilterGroups(source.filterGroups?.length ? normalizeVisualizationFilterGroups(source.filterGroups) : legacyFiltersToFilterGroups(source.filters || {}));
        setSumFilteredRows(Boolean(source.sumFilteredRows));
        if (Array.isArray(source.comboLineFields)) setComboLineFields(source.comboLineFields);
        if (typeof source.noteTitle === "string") setNoteTitle(source.noteTitle);
        if (typeof source.noteBody === "string") setNoteBody(source.noteBody);
        const savedItems = normalizeNoteItems(source.noteItems);
        if (savedItems.length) setNoteItems(savedItems);
        else if (typeof source.noteBody === "string") setNoteItems(noteItemsFromText(source.noteBody, "visual_note"));
        if (typeof source.noteTitleHidden === "boolean") setNoteTitleHidden(source.noteTitleHidden);
        if (saved && typeof (saved as { type?: string }).type === "string" && (saved as { type?: string }).type !== type) {
          applyType((saved as { type: VisualizationType }).type);
        }
        if (saved) setShowData(Boolean(saved.showData));
        cardStateSkipSaveRef.current = true;
      }
    } catch { /* invalid per-card session state is ignored */ }
    cardStateHydratedRef.current = key;
  }, [initialConfig, stateKey]);

  useEffect(() => {
    const normalized = normalizeVisualizationSelections(cardType, metricFields, dimensionFields, numericFields, dimensionCandidates, fieldLabels, fieldMetadata);
    if (!sameFields(metricFields, normalized.metrics)) setMetricFields(normalized.metrics);
    if (!sameFields(dimensionFields, normalized.dimensions)) setDimensionFields(normalized.dimensions);
  }, [cardType, dimensionCandidates.join("\u0000"), dimensionFields, fieldLabels, metricFields, numericFields.join("\u0000")]);

  useEffect(() => {
    const allowed = new Set([...dimensionFields, ...metricFields]);
    setMergedDimensionFields((current) => { const next = current.filter((field) => allowed.has(field)); return sameFields(current, next) ? current : next; });
    setFrozenColumnFields((current) => { const next = current.filter((field) => allowed.has(field)); return sameFields(current, next) ? current : next; });
    setTableHeaderMenu((current) => current && cardType === "table" && allowed.has(current.field) ? current : null);
  }, [cardType, dimensionFields, metricFields]);

  useEffect(() => {
    const next = defaultComboLineFields(metricFields, comboLineFields);
    if (!sameFields(next, comboLineFields)) setComboLineFields(next);
  }, [comboLineFields, metricFields]);

  useEffect(() => {
    const key = `sda:visual-card:v2:${window.location.pathname}:${stateKey}`;
    if (cardStateHydratedRef.current !== key) return;
    if (cardStateSkipSaveRef.current) { cardStateSkipSaveRef.current = false; return; }
    try { sessionStorage.setItem(key, JSON.stringify({ ...currentConfig, showData, type: cardType })); } catch { /* session quota must not block charts */ }
    onConfigChangeRef.current?.(currentConfig);
  }, [cardType, currentConfig, showData, stateKey]);

  const streamedVoiceRef = useRef("");
  const cardTypeRef = useRef(cardType);
  cardTypeRef.current = cardType;
  const applyVoiceCommand = (command: string) => {
    if (cardTypeRef.current === "text") {
      if (!streamedVoiceRef.current) insertVisualVoiceText(cardRef.current, command);
      streamedVoiceRef.current = "";
      setCommandNotice("已写入文本框");
      return;
    }
    streamedVoiceRef.current = "";
    const resolution = resolveVisualizationVoiceCommand(command, numericFields, dimensionCandidates, fieldLabels);
    if (resolution.visualizationType) applyType(resolution.visualizationType);
    if (resolution.metricField) setMetricFields((current) => toggleVisualizationField("metric", resolution.visualizationType || cardType, current.filter((field) => field !== resolution.metricField), resolution.metricField!));
    if (resolution.dimensionField) setDimensionFields((current) => toggleVisualizationField("dimension", resolution.visualizationType || cardType, current.filter((field) => field !== resolution.dimensionField), resolution.dimensionField!));
    if (resolution.dataVisibility) setShowData(resolution.dataVisibility === "shown");
    if (resolution.visualizationType || resolution.metricField || resolution.dimensionField) {
      trackVisual("visualization_result", {
        action: "voice",
        chart_type: resolution.visualizationType || cardType,
        metric_fields: resolution.metricField ? [resolution.metricField] : [],
        dimension_fields: resolution.dimensionField ? [resolution.dimensionField] : [],
      });
    }
    const parts = [resolution.visualizationType ? visualizationLabel(resolution.visualizationType) : "", resolution.metricField ? `指标 ${fieldLabels[resolution.metricField] || resolution.metricField}` : "", resolution.dimensionField ? `维度 ${fieldLabels[resolution.dimensionField] || resolution.dimensionField}` : ""].filter(Boolean);
    setCommandNotice(parts.length ? `已应用：${parts.join(" · ")}` : `已听到“${command}”，但没有匹配到样式、指标或维度，请换一种说法。`);
  };
  const handleVoiceTranscript = (text: string) => {
    if (cardTypeRef.current !== "text") return;
    const previous = streamedVoiceRef.current;
    const delta = text.startsWith(previous) ? text.slice(previous.length) : previous ? "" : text;
    if (delta) insertVisualVoiceText(cardRef.current, delta);
    streamedVoiceRef.current = text.startsWith(previous) ? text : previous;
  };
  const focusTextVoiceTarget = () => {
    const card = cardRef.current;
    if (!card) return;
    const active = document.activeElement;
    if (active instanceof HTMLElement && card.contains(active) && (active.matches("input, [contenteditable='true']"))) return;
    const editor = card.querySelector<HTMLElement>("[data-rich-note-editor-id], [data-visual-note-body]");
    editor?.focus();
  };
  const voice = useVisualizationVoiceCommand(applyVoiceCommand, handleVoiceTranscript);
  const metricReorder = useRightPressReorder(metricFields, setMetricFields, `${stateKey}-metric`, (field) => fieldLabels[field] || field);
  const dimensionReorder = useRightPressReorder(dimensionFields, setDimensionFields, `${stateKey}-dimension`, (field) => fieldLabels[field] || field);

  useEffect(() => {
    if (!(voice.listening || voice.error || commandNotice || voice.transcript)) {
      setVoiceNoticeVisible(false);
      return;
    }
    setVoiceNoticeVisible(true);
    if (voice.listening) return;
    const timer = window.setTimeout(() => setVoiceNoticeVisible(false), 1_000);
    return () => window.clearTimeout(timer);
  }, [commandNotice, voice.error, voice.listening, voice.transcript]);

  useEffect(() => {
    if (!tableNotice) return;
    const timer = window.setTimeout(() => setTableNotice(""), 4_000);
    return () => window.clearTimeout(timer);
  }, [tableNotice]);

  useEffect(() => {
    const dismissTransientControls = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const inMoreMenu = Boolean(target.closest('[data-visual-more-menu="true"]'));
      const inMoreButton = Boolean(moreButtonRef.current?.contains(target));
      if (!inMoreMenu && !inMoreButton) setMoreOpen(false);
      if (!target.closest('[data-visual-filter-panel="true"], [data-visual-filter-value-menu], [data-visual-filter-value-trigger]')) setFilterOpen(false);
      if (
        !target.closest('[data-visual-style-menu="true"]')
        && !target.closest("[data-visual-field-panel]")
        && !target.closest("[data-visual-panel-trigger]")
      ) setActivePanel(null);
      if (!target.closest('[data-visual-comment-action="true"], [data-visual-table-header-menu], [data-visual-table-row-menu]')) {
        setCommentPoint(null);
        setTableHeaderMenu(null);
        setTableRowMenu(null);
      }
    };
    document.addEventListener("pointerdown", dismissTransientControls, true);
    return () => document.removeEventListener("pointerdown", dismissTransientControls, true);
  }, [id]);

  useEffect(() => {
    if (!moreOpen) {
      setMoreMenuPos(null);
      return;
    }
    const update = () => {
      const rect = moreButtonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = 112;
      setMoreMenuPos({
        top: rect.bottom + 4,
        left: Math.min(Math.max(8, rect.left), window.innerWidth - width - 8),
      });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [moreOpen]);

  const toggleOperations = () => {
    if (operationsOpen) {
      setOperationsOpen(false);
      setActivePanel(null);
    } else setOperationsOpen(true);
  };

  const togglePanel = (panel: "style" | "metric" | "dimension") => {
    setActivePanel((current) => current === panel ? null : panel);
  };

  const applyFilterState = (groups: VisualizationFilterGroup[], sum: boolean) => {
    const normalized = normalizeVisualizationFilterGroups(groups);
    setFilterGroups(normalized);
    setFilters(visualizationFilterGroupsToLegacyFilters(normalized));
    setSumFilteredRows(sum);
  };
  const openFilters = () => {
    filterSnapshotRef.current = { filterGroups, filters, sumFilteredRows };
    const source = filterGroups.length ? filterGroups : legacyFiltersToFilterGroups(filters);
    setDraftFilterGroups(source.length ? structuredClone(source) : [createFilterGroup(dimensionCandidates[0] || "")]);
    setDraftSumRows(sumFilteredRows);
    setMoreOpen(false);
    setFilterOpen(true);
  };
  const activeFilterCount = filterGroups.reduce((count, group) => count + group.rules.filter((rule) => rule.field && rule.values.length).length, 0);

  const pointWithinCard = (clientX: number, clientY: number, width = 44) => { const rect = cardRef.current?.getBoundingClientRect(); return rect ? { left: Math.max(8, Math.min(clientX - rect.left, rect.width - width - 8)), top: Math.max(8, clientY - rect.top) } : null; };
  const eventInsideVisualTable = (target: EventTarget | null) => target instanceof Element && Boolean(target.closest("[data-visual-table-scroll]"));
  const revealCommentAt = (clientX: number, clientY: number) => { const point = pointWithinCard(clientX, clientY); if (point) { setTableHeaderMenu(null); setTableRowMenu(null); setCommentPoint(point); } };
  const revealTableHeaderMenu = (field: string, event: ReactMouseEvent<HTMLElement>) => {
    if (cardType !== "table") return;
    event.preventDefault();
    event.stopPropagation();
    setCommentPoint(null);
    setTableRowMenu(null);
    setTableHeaderMenu({ field, left: Math.max(8, Math.min(event.clientX, window.innerWidth - 218)), top: Math.max(8, Math.min(event.clientY, window.innerHeight - 180)) });
  };
  const revealTableRowMenu = (rowKey: string, event: ReactMouseEvent<HTMLElement>) => {
    if (cardType !== "table") return;
    event.preventDefault();
    event.stopPropagation();
    setCommentPoint(null);
    setTableHeaderMenu(null);
    setTableRowMenu({ rowKey, left: Math.max(8, Math.min(event.clientX, window.innerWidth - 196)), top: Math.max(8, Math.min(event.clientY, window.innerHeight - 120)) });
  };
  const hasMergedCells = mergedDimensionFields.length > 0;
  const freezeBlockedMessage = "有合并单元格的情况下，无法冻结，如需冻结请取消合并单元格";
  const toggleFrozenColumn = (field: string) => {
    if (hasMergedCells) { setTableNotice(freezeBlockedMessage); setTableHeaderMenu(null); return; }
    setFrozenColumnFields((current) => current.includes(field) ? current.filter((item) => item !== field) : [...current, field]);
    setTableHeaderMenu(null);
  };
  const toggleFrozenRow = (rowKey: string) => {
    if (hasMergedCells) { setTableNotice(freezeBlockedMessage); setTableRowMenu(null); return; }
    setFrozenRowKeys((current) => current.includes(rowKey) ? current.filter((item) => item !== rowKey) : [...current, rowKey]);
    setTableRowMenu(null);
  };
  const isTextCard = cardType === "text";
  const isTableCard = cardType === "table" || cardType === "pivot";
  const chartAreaRef = useRef<HTMLDivElement>(null);
  useVisualTableRegionWheelLock(chartAreaRef, isTableCard);
  const primaryToolsOpen = !isTextCard || operationsOpen;
  return <div ref={cardRef} data-visual-card={id} data-visual-text-card={isTextCard ? "true" : "false"} data-visual-values={showData ? "shown" : "hidden"} data-visual-grid-span={visualGridSpan} data-visual-grid-height={visualGridHeight} data-visual-grid-max-span={visualGridMaxSpan} data-visual-grid-max-height={visualGridMaxHeight} className={`relative rounded-xl border border-[#dce9e0] bg-[#fbfdfc] p-4 ${activePanel === "style" ? "overflow-hidden" : ""} ${fillHeight ? "flex h-full min-h-0 flex-col" : ""}`} onClick={(event) => { if (!(event.target instanceof Element) || event.target.closest('[data-visual-interactive="true"]') || eventInsideVisualTable(event.target)) return; trackVisual("visualization_click", { chart_type: cardType, metric_fields: metricFields, dimension_fields: dimensionFields }); revealCommentAt(event.clientX, event.clientY); }} onContextMenu={(event) => { if (event.target instanceof Element && event.target.closest("[data-rich-note-editor], [data-visual-note-selection], [data-visual-note-title-row]")) return; event.preventDefault(); if (eventInsideVisualTable(event.target)) return; revealCommentAt(event.clientX, event.clientY); }}>
    <div className={isTextCard ? "mb-3 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-1" : "mb-3 flex items-start justify-between gap-2.5"}>
      {!isTextCard && <div className="min-w-0 flex-1 pr-1" data-visual-interactive="true">{editingTitle ? <input autoFocus value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} onBlur={commitTitle} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") { setDraftTitle(title); setEditingTitle(false); } }} className="h-7 w-full rounded-md border border-[#b7ddc3] bg-white px-2 text-[12px] text-[#1d1d1f] outline-none ring-2 ring-[#2ca66f]/15" aria-label="可视化标题" data-visual-title-input="true" /> : <button type="button" onDoubleClick={(event) => { event.stopPropagation(); if (onTitleChange) setEditingTitle(true); }} className={`max-w-full truncate text-left text-[12px] text-[#1d1d1f] ${onTitleChange ? "cursor-text rounded px-1 py-1 hover:bg-[#f5faf7]" : ""}`} title={onTitleChange ? "双击修改标题" : title} data-visual-title="true">{title}</button>}</div>}
      <div className={isTextCard ? `${operationsOpen ? "col-span-2 row-start-1 flex justify-end" : "hidden"}` : "ml-auto flex shrink-0 flex-nowrap items-center justify-end gap-0 rounded-full bg-[#f0f6f2] p-0.5"} data-visual-toolbar="true" data-visual-interactive="true" data-visual-text-ops-above={isTextCard && operationsOpen ? "true" : undefined}>
        <div className={isTextCard ? "flex shrink-0 flex-nowrap items-center justify-end gap-0 rounded-full bg-[#f0f6f2] p-0.5" : "contents"}>
        <div aria-hidden={!primaryToolsOpen} {...(!primaryToolsOpen ? ({ inert: "" } as Record<string, string>) : {})} className={`flex items-center gap-0 overflow-hidden transition-[max-width,opacity] duration-200 motion-reduce:transition-none ${primaryToolsOpen ? "max-w-[360px] opacity-100" : "pointer-events-none max-w-0 opacity-0"}`} data-visual-primary-tray={primaryToolsOpen ? "expanded" : "collapsed"}>
          <div className="relative">
            <button ref={moreButtonRef} type="button" onClick={(event) => { trackVisual("visual_more_click"); const rect = event.currentTarget.getBoundingClientRect(); setMoreMenuPos({ top: rect.bottom + 4, left: Math.min(Math.max(8, rect.left), window.innerWidth - 120) }); setMoreOpen((value) => !value); setFilterOpen(false); }} className={`inline-flex h-7 w-8 items-center justify-center rounded-full ${moreOpen || activeFilterCount ? "bg-white text-[#178a53] shadow-sm" : "text-[#4f685b] hover:bg-white/80"}`} aria-label="更多可视化操作" aria-expanded={moreOpen} data-visual-more="true"><Ellipsis className="h-4 w-4" /></button>
            {moreOpen && moreMenuPos && createPortal(<div className="fixed z-[120] w-28 rounded-lg border border-[#dce7df] bg-white p-1 shadow-lg shadow-black/[0.08]" style={{ top: moreMenuPos.top, left: moreMenuPos.left }} data-visual-more-menu="true" data-visual-interactive="true">
              <MoreMenuButton icon={Type} label="文本框" dataAttr="data-visual-more-text" onClick={() => { trackVisual("visual_text_card_click"); if (onCreateText) onCreateText(currentConfig); else onDuplicate?.(currentConfig, { asText: true }); setMoreOpen(false); }} disabled={!onCreateText && !onDuplicate} />
              <MoreMenuButton icon={Filter} label={activeFilterCount ? `条件 ${activeFilterCount}` : "条件"} dataAttr="data-visual-filter-toggle" onClick={() => { trackVisual("visual_condition_click"); openFilters(); }} disabled={isTextCard} />
              <MoreMenuButton icon={Copy} label="复制" disabled={!onDuplicate} onClick={() => { trackVisual("visual_copy_click"); onDuplicate?.(currentConfig); setMoreOpen(false); }} />
              <MoreMenuButton icon={Trash2} label="删除" destructive disabled={!onDelete} onClick={() => { trackVisual("visual_delete_click"); onDelete?.(); setMoreOpen(false); }} />
            </div>, document.body)}
          </div>
          <button type="button" onClick={() => { trackVisual(showData ? "visual_hide_data_click" : "visual_show_data_click"); setShowData((value) => !value); }} disabled={!rows.length} className="h-7 whitespace-nowrap rounded-full px-2 text-[11px] text-[#4f685b] hover:bg-white/80 disabled:opacity-40" data-visual-data-toggle="true">{showData ? "隐藏数据" : "显示数据"}</button>
          {showFollowUp && <button type="button" onClick={() => { trackVisual("visual_follow_up_click"); onFollowUp({ dataTables: analysisSource }); }} className="h-7 whitespace-nowrap rounded-full px-2 text-[11px] text-[#178a53] hover:bg-white/80" aria-label={`追问${title}`} data-visual-follow-up="true">追问</button>}
        </div>
        <div aria-hidden={!operationsOpen} {...(!operationsOpen ? ({ inert: "" } as Record<string, string>) : {})} className={`flex items-center gap-0.5 overflow-hidden transition-[max-width,opacity] duration-200 motion-reduce:transition-none ${operationsOpen ? "max-w-[260px] opacity-100" : "pointer-events-none max-w-0 opacity-0"}`} data-visual-operation-tray={operationsOpen ? "expanded" : "collapsed"}>
          <button tabIndex={operationsOpen ? 0 : -1} type="button" data-visual-panel-trigger="style" onClick={() => { trackVisual("visual_style_click"); setMoreOpen(false); togglePanel("style"); }} className={`h-7 whitespace-nowrap rounded-full px-2 text-[11px] outline-none focus-visible:outline-none ${activePanel === "style" ? "bg-white text-[#178a53] shadow-sm" : "text-[#53615a] hover:bg-white/80"}`}>样式</button>
          <button tabIndex={operationsOpen ? 0 : -1} type="button" data-visual-panel-trigger="metric" onClick={() => { trackVisual("visual_metric_click"); setMoreOpen(false); togglePanel("metric"); }} className={`h-7 whitespace-nowrap rounded-full px-2 text-[11px] outline-none focus-visible:outline-none ${activePanel === "metric" ? "bg-white text-[#178a53] shadow-sm" : "text-[#53615a] hover:bg-white/80"}`}>指标</button>
          <button tabIndex={operationsOpen ? 0 : -1} type="button" data-visual-panel-trigger="dimension" onClick={() => { trackVisual("visual_dimension_click"); setMoreOpen(false); togglePanel("dimension"); }} className={`h-7 whitespace-nowrap rounded-full px-2 text-[11px] outline-none focus-visible:outline-none ${activePanel === "dimension" ? "bg-white text-[#178a53] shadow-sm" : "text-[#53615a] hover:bg-white/80"}`}>维度</button>
          <button tabIndex={operationsOpen ? 0 : -1} type="button" onClick={() => { trackVisual("visual_voice_click"); if (isTextCard) focusTextVoiceTarget(); voice.toggle(); }} className={`flex h-7 w-8 shrink-0 items-center justify-center rounded-full outline-none focus-visible:outline-none ${voice.listening ? "bg-white text-[#178a53] shadow-sm" : "text-[#53615a] hover:bg-white/80"}`} aria-label={voice.listening ? "停止可视化语音配置" : "语音配置可视化"} title="实时语音配置"><AudioLines className={`h-3.5 w-3.5 ${voice.listening ? "animate-pulse" : ""}`} /></button>
        </div>
        {!isTextCard && <button type="button" onClick={toggleOperations} className={`inline-flex h-7 w-8 shrink-0 items-center justify-center rounded-full outline-none focus-visible:outline-none ${operationsOpen ? "bg-white text-[#178a53] shadow-sm" : "text-[#4f685b] hover:bg-white/80"}`} aria-expanded={operationsOpen} aria-label={operationsOpen ? "收起可视化操作" : "展开可视化操作"} title="操作" data-visual-operation-toggle="true"><SlidersHorizontal className="h-3.5 w-3.5" /></button>}
        </div>
      </div>
      {isTextCard ? <div className={`col-start-1 min-w-0 ${operationsOpen ? "row-start-2" : "row-start-1"}`} data-visual-interactive="true"><span className="sr-only" data-visual-title="true">{noteTitle.trim() || title || "文本框"}</span>{!noteTitleHidden && <VisualNoteTitle title={noteTitle} onTitleChange={(value) => { setNoteTitle(value); onTitleChange?.(value || title); }} onHideTitle={() => setNoteTitleHidden(true)} />}</div> : null}
      {isTextCard ? <div className={`col-start-2 flex justify-end ${operationsOpen ? "row-start-2" : "row-start-1"}`}><div className="flex h-8 shrink-0 items-center rounded-full bg-[#f0f6f2] p-0.5" data-visual-toolbar="true" data-visual-interactive="true">{!operationsOpen && <button type="button" onClick={() => { trackVisual("visual_voice_click"); focusTextVoiceTarget(); voice.toggle(); }} className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full outline-none focus-visible:outline-none ${voice.listening ? "bg-white text-[#178a53] shadow-sm" : "text-[#4f685b] hover:bg-white/80"}`} aria-label={voice.listening ? "停止文本框实时语音" : "文本框实时语音"} title="实时语音" data-visual-text-voice="true"><AudioLines className={`h-3.5 w-3.5 ${voice.listening ? "animate-pulse" : ""}`} /></button>}<button type="button" onClick={toggleOperations} className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full outline-none focus-visible:outline-none ${operationsOpen ? "bg-white text-[#178a53] shadow-sm" : "text-[#4f685b] hover:bg-white/80"}`} aria-expanded={operationsOpen} aria-label={operationsOpen ? "收起可视化操作" : "展开可视化操作"} title="操作" data-visual-operation-toggle="true"><SlidersHorizontal className="h-3.5 w-3.5" /></button></div></div> : null}
    </div>

    {filterOpen && <VisualizationFilterPanel rows={rows} dimensions={dimensionCandidates} labels={fieldLabels} value={draftFilterGroups} sumRows={draftSumRows} onChange={(next) => { setDraftFilterGroups(next); applyFilterState(next, draftSumRows); }} onSumRowsChange={(next) => { setDraftSumRows(next); applyFilterState(draftFilterGroups, next); }} onCancel={() => { const snapshot = filterSnapshotRef.current; if (snapshot) { setFilterGroups(snapshot.filterGroups); setFilters(snapshot.filters); setSumFilteredRows(snapshot.sumFilteredRows); } setFilterOpen(false); }} onSave={() => { applyFilterState(draftFilterGroups, draftSumRows); trackVisual("visualization_result", { action: "condition", filter_count: draftFilterGroups.reduce((count, group) => count + group.rules.filter((rule) => rule.field && rule.values.length).length, 0), dimension_fields: Array.from(new Set(draftFilterGroups.flatMap((group) => group.rules.map((rule) => rule.field).filter(Boolean)))) }); setFilterOpen(false); }} />}
    {operationsOpen && activePanel === "style" && <div className={`absolute right-4 z-30 grid max-h-[calc(100%-4rem)] w-[min(17.5rem,calc(100%-2rem))] grid-cols-2 gap-0.5 overflow-y-auto overflow-x-hidden rounded-lg border border-[#dce7df] bg-white p-1 shadow-lg shadow-black/[0.08] ${isTextCard ? "top-11" : "top-12"}`} data-visual-style-menu="true" data-visual-style-layout="two-column" data-visual-interactive="true">{visualizationOptions.map((option) => <button key={option.type} type="button" onClick={() => { applyType(option.type); trackVisual("visualization_result", { action: "style", chart_type: option.type }); setActivePanel(null); }} className={`flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[12px] ${option.type === cardType ? "bg-[#eaf7ef] text-[#178a53]" : "text-[#636366] hover:bg-[#f5faf7]"}`}><option.icon className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{option.label}</span></button>)}</div>}
    {operationsOpen && activePanel === "metric" && <FieldPanel title="指标" fields={metricFields} candidates={numericFields} labels={fieldLabels} reorder={metricReorder} onToggle={(field) => { const next = toggleVisualizationField("metric", cardType, metricFields, field); setMetricFields(next); trackVisual("visualization_result", { action: "metric", metric_fields: next, changed_field: field }); }} />}
    {operationsOpen && activePanel === "dimension" && <FieldPanel title="维度" fields={dimensionFields} candidates={dimensionCandidates} labels={fieldLabels} reorder={dimensionReorder} onToggle={(field) => { const next = toggleVisualizationField("dimension", cardType, dimensionFields, field); setDimensionFields(next); trackVisual("visualization_result", { action: "dimension", dimension_fields: next, changed_field: field }); }} />}
    {voiceNoticeVisible && (voice.listening || voice.error || commandNotice || voice.transcript) && <div className="absolute right-4 top-12 z-40 max-w-[280px] rounded-lg border border-[#dce7df] bg-white px-3 py-2 text-[10px] leading-4 text-[#53615a] shadow-lg" role="status" data-visual-voice-notice="true" data-visual-interactive="true">{voice.listening ? (isTextCard ? "正在将语音转写到文本框…" : "正在听取样式、指标或维度指令…") : voice.error || commandNotice || voice.transcript}</div>}
    {tableNotice ? <div className="mb-2 rounded-lg border border-[#ead7b8] bg-[#fff8ee] px-3 py-2 text-[11px] leading-5 text-[#8a6a2b]" role="alert" data-visual-table-freeze-notice="true">{tableNotice}</div> : null}
    {commentPoint && <button type="button" aria-label="评论可视化" onClick={() => { onComment(); setCommentPoint(null); }} className="absolute z-40 flex h-8 w-8 items-center justify-center rounded-full bg-[#178a53] text-white shadow-lg shadow-black/20 outline-none hover:bg-[#117847] focus-visible:outline-none" style={commentPoint} data-visual-comment-action="true" data-visual-interactive="true"><MessageSquareText className="h-4 w-4" /></button>}
    {tableHeaderMenu && createPortal(<div className="fixed z-[200] w-[210px] rounded-xl border border-[#dce7df] bg-white p-1.5 shadow-xl shadow-black/10" style={{ left: tableHeaderMenu.left, top: tableHeaderMenu.top }} data-visual-table-header-menu={tableHeaderMenu.field} data-visual-interactive="true">
      <button type="button" onClick={() => { onComment({ selectedText: fieldLabels[tableHeaderMenu.field] || tableHeaderMenu.field }); setTableHeaderMenu(null); }} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-table-header-comment="true"><MessageSquareText className="h-3.5 w-3.5 text-[#178a53]" />评论</button>
      <button type="button" aria-pressed={mergedDimensionFields.includes(tableHeaderMenu.field)} onClick={() => { setMergedDimensionFields((current) => { const next = current.includes(tableHeaderMenu.field) ? current.filter((field) => field !== tableHeaderMenu.field) : [...current, tableHeaderMenu.field]; if (next.length) { setFrozenColumnFields([]); setFrozenRowKeys([]); } return next; }); setTableHeaderMenu(null); }} className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-merge-dimension={tableHeaderMenu.field}><span>{mergedDimensionFields.includes(tableHeaderMenu.field) ? "取消合并重复单元格" : "合并重复单元格"}</span>{mergedDimensionFields.includes(tableHeaderMenu.field) && <Check className="h-3.5 w-3.5 text-[#178a53]" />}</button>
      <button type="button" aria-pressed={frozenColumnFields.includes(tableHeaderMenu.field)} onClick={() => toggleFrozenColumn(tableHeaderMenu.field)} className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-freeze-column={tableHeaderMenu.field}><span>{frozenColumnFields.includes(tableHeaderMenu.field) ? "取消冻结到首列" : "冻结到首列"}</span>{frozenColumnFields.includes(tableHeaderMenu.field) ? <Check className="h-3.5 w-3.5 text-[#178a53]" /> : <Pin className="h-3.5 w-3.5 text-[#8aa396]" />}</button>
    </div>, document.body)}
    {tableRowMenu && createPortal(<div className="fixed z-[200] w-[188px] rounded-xl border border-[#dce7df] bg-white p-1.5 shadow-xl shadow-black/10" style={{ left: tableRowMenu.left, top: tableRowMenu.top }} data-visual-table-row-menu={tableRowMenu.rowKey} data-visual-interactive="true">
      <button type="button" aria-pressed={frozenRowKeys.includes(tableRowMenu.rowKey)} onClick={() => toggleFrozenRow(tableRowMenu.rowKey)} className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-[11px] text-[#53615a] hover:bg-[#f5faf7]" data-visual-freeze-row={tableRowMenu.rowKey}><span>{frozenRowKeys.includes(tableRowMenu.rowKey) ? "取消冻结到首行" : "冻结到首行"}</span>{frozenRowKeys.includes(tableRowMenu.rowKey) ? <Check className="h-3.5 w-3.5 text-[#178a53]" /> : <Pin className="h-3.5 w-3.5 text-[#8aa396]" />}</button>
    </div>, document.body)}
    <div ref={chartAreaRef} className={fillHeight ? `flex min-h-0 flex-1 flex-col ${isTableCard ? "overflow-hidden" : "overflow-auto"}` : ""} onWheelCapture={isTextCard || isTableCard ? undefined : passWheelToPage} data-chart-wheel-passthrough={isTextCard || isTableCard ? undefined : "true"} data-visual-table-region={isTableCard ? "true" : undefined}>{isTextCard ? <VisualNoteFields title={noteTitle} body={noteBody} items={noteItems} titleHidden={true} fields={fields} metricFields={metricFields} dimensionFields={dimensionFields} labels={fieldLabels} uploadContext={{ tenantId, userId, reportId: `visual-note-${stateKey}`, blockId: String(id) }} onTitleChange={(value) => { setNoteTitle(value); onTitleChange?.(value || title); }} onBodyChange={setNoteBody} onItemsChange={setNoteItems} onHideTitle={() => setNoteTitleHidden(true)} onOpenComment={(selectedText) => onComment({ selectedText })} onOpenAnalysis={(selectedText) => onFollowUp({ selectedText, dataTables: analysisSource })} /> : <VisualizationRenderer type={cardType} rows={rows} metricFields={metricFields} dimensionFields={dimensionFields} mergedDimensionFields={mergedDimensionFields} frozenColumnFields={frozenColumnFields} frozenRowKeys={frozenRowKeys} filters={filters} filterGroups={filterGroups} sumFilteredRows={sumFilteredRows} comboLineFields={comboLineFields} onComboLineFieldsChange={setComboLineFields} onMetricFieldsChange={setMetricFields} onDimensionFieldsChange={setDimensionFields} onDimensionHeaderContextMenu={revealTableHeaderMenu} onRowContextMenu={revealTableRowMenu} metricReorder={metricReorder} compact={compact} showData={showData} fillHeight={fillHeight} />}</div>
    <ReorderPreview reorder={metricReorder} /><ReorderPreview reorder={dimensionReorder} />
  </div>;
}

type ReorderController = ReturnType<typeof useRightPressReorder>;

function FieldPanel({ title, fields, candidates, labels, reorder, onToggle }: { title: string; fields: string[]; candidates: string[]; labels: Record<string, string>; reorder: ReorderController; onToggle: (field: string) => void }) {
  const orderedCandidates = [...fields.filter((field) => candidates.includes(field)), ...candidates.filter((field) => !fields.includes(field))];
  return <div className="absolute right-4 top-12 z-30 w-64 rounded-lg border border-[#dce7df] bg-white p-3 shadow-lg shadow-black/[0.08]" onPointerUp={() => reorder.end(true)} onPointerCancel={() => reorder.end(false)} data-visual-field-panel={title} data-visual-interactive="true">
    <div className="mb-2 text-[10px] text-[#8a9690]">{title} · 长按 2 秒后拖动排序</div>
    <div className="flex flex-wrap gap-1.5">{orderedCandidates.map((field) => { const selected = fields.includes(field); return <button key={field} type="button" data-reorder-field={field} data-reorder-group={reorder.group} data-reorder-index={selected ? fields.indexOf(field) : -1} data-reorder-floating={reorder.floating === field ? "true" : "false"} data-reorder-target={reorder.target === field ? "true" : "false"} onClick={() => { if (!reorder.consumeClick()) onToggle(field); }} onPointerDown={(event) => selected ? reorder.start(field, event) : undefined} onPointerUp={() => reorder.end(true)} onPointerCancel={() => reorder.end(false)} className={`rounded-md border px-2 py-1 text-[10px] transition-colors ${reorder.floating === field ? "border-[#2ca66f] bg-[#eaf7ef] text-[#178a53] shadow-sm" : reorder.target === field ? "border-[#2ca66f] bg-white text-[#178a53] ring-2 ring-[#2ca66f]/20" : selected ? "border-[#cfe6d6] bg-[#eef8f2] text-[#178a53]" : "border-[#e5e5ea] bg-white text-[#8a8a8e]"}`}>{labels[field] || field}</button>; })}</div>
  </div>;
}

function useRightPressReorder(fields: string[], setFields: (updater: (current: string[]) => string[]) => void, group = "default", labelFor = (field: string) => field) {
  const timerRef = useRef<number | null>(null);
  const draggingRef = useRef("");
  const targetRef = useRef("");
  const suppressClickRef = useRef(false);
  const frameRef = useRef<number | null>(null);
  const [floating, setFloating] = useState("");
  const [target, setTarget] = useState("");
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const clearTimer = () => { if (timerRef.current !== null) window.clearTimeout(timerRef.current); timerRef.current = null; };
  const end = (commit = true) => {
    clearTimer();
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    const source = draggingRef.current;
    const destination = targetRef.current;
    if (commit && source && destination && source !== destination) setFields((current) => moveVisualizationFieldWithinGroup(current, source, destination));
    draggingRef.current = "";
    targetRef.current = "";
    setFloating("");
    setTarget("");
    document.body.style.removeProperty("user-select");
    document.body.style.removeProperty("cursor");
  };
  useEffect(() => {
    if (!floating) return;
    const move = (event: PointerEvent) => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = requestAnimationFrame(() => {
        setPosition({ x: event.clientX, y: event.clientY });
        const element = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>(`[data-reorder-field][data-reorder-group="${CSS.escape(group)}"]`);
        const nextTarget = element?.dataset.reorderField || "";
        if (nextTarget && nextTarget !== targetRef.current) { targetRef.current = nextTarget; setTarget(nextTarget); }
      });
    };
    const release = () => end(true);
    const cancel = () => end(false);
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerup", release, { once: true });
    window.addEventListener("pointercancel", cancel, { once: true });
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", release); window.removeEventListener("pointercancel", cancel); };
  }, [floating, group]);
  return {
    group,
    floating,
    target,
    position,
    label: floating ? labelFor(floating) : "",
    start: (field: string, event: ReactPointerEvent<Element>) => {
      if (event.button !== 0) return;
      clearTimer();
      suppressClickRef.current = false;
      const { clientX, clientY } = event;
      timerRef.current = window.setTimeout(() => {
        draggingRef.current = field;
        targetRef.current = field;
        suppressClickRef.current = true;
        setFloating(field);
        setTarget(field);
        setPosition({ x: clientX, y: clientY });
        document.body.style.userSelect = "none";
        document.body.style.cursor = "grabbing";
      }, 2_000);
    },
    consumeClick: () => { const suppressed = suppressClickRef.current; suppressClickRef.current = false; return suppressed; },
    end,
  };
}

function reconcileFields(current: string[], candidates: string[], fallback: string[]) {
  const retained = current.filter((field) => candidates.includes(field));
  return retained.length ? retained : fallback;
}

function sameFields(left: string[], right: string[]) { return left.length === right.length && left.every((field, index) => field === right[index]); }

function ReorderPreview({ reorder }: { reorder: ReorderController }) {
  if (!reorder.floating) return null;
  return <div className="pointer-events-none fixed z-[120] max-w-[220px] rounded-lg border border-[#b7ddc3] bg-white px-3 py-2 text-[11px] text-[#178a53] shadow-xl shadow-black/10" style={{ left: reorder.position.x + 12, top: reorder.position.y + 12 }} data-reorder-preview="true"><span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-[#2ca66f]" />{reorder.label}</div>;
}

function MoreMenuButton({ icon: Icon, label, onClick, disabled = false, destructive = false, dataAttr }: { icon: typeof Filter; label: string; onClick: () => void; disabled?: boolean; destructive?: boolean; dataAttr?: string }) {
  return <button type="button" onClick={onClick} disabled={disabled} {...(dataAttr ? { [dataAttr]: "true" } : {})} className={`flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[11px] disabled:cursor-not-allowed disabled:opacity-35 ${destructive ? "text-[#d64b4b] hover:bg-[#fff4f4]" : "text-[#53615a] hover:bg-[#f5faf7]"}`}><Icon className="h-3.5 w-3.5" />{label}</button>;
}

let filterEditorSequence = 0;
function nextFilterEditorId(prefix: "group" | "rule") { filterEditorSequence += 1; return `${prefix}-${Date.now()}-${filterEditorSequence}`; }
function createFilterRule(field = ""): VisualizationFilterRule { return { id: nextFilterEditorId("rule"), field, operator: "in", values: [] }; }
function createFilterGroup(field = ""): VisualizationFilterGroup { return { id: nextFilterEditorId("group"), rules: [createFilterRule(field)] }; }

function VisualizationFilterPanel({ rows, dimensions, labels, value, sumRows, onChange, onSumRowsChange, onCancel, onSave }: { rows: AnalysisRow[]; dimensions: string[]; labels: Record<string, string>; value: VisualizationFilterGroup[]; sumRows: boolean; onChange: (value: VisualizationFilterGroup[]) => void; onSumRowsChange: (value: boolean) => void; onCancel: () => void; onSave: () => void }) {
  const [activeValuesRule, setActiveValuesRule] = useState<string | null>(null);
  const [valueMenuPosition, setValueMenuPosition] = useState<{ left: number; top: number; width: number; openAbove: boolean } | null>(null);
  const updateRule = (groupId: string, ruleId: string, updater: (rule: VisualizationFilterRule) => VisualizationFilterRule) => onChange(value.map((group) => group.id === groupId ? { ...group, rules: group.rules.map((rule) => rule.id === ruleId ? updater(rule) : rule) } : group));
  const addRule = (groupId: string, afterRuleId: string) => onChange(value.map((group) => { if (group.id !== groupId) return group; const rules = [...group.rules]; rules.splice(rules.findIndex((rule) => rule.id === afterRuleId) + 1, 0, createFilterRule()); return { ...group, rules }; }));
  const removeRule = (groupId: string, ruleId: string) => onChange(value.map((group) => group.id === groupId ? { ...group, rules: group.rules.length > 1 ? group.rules.filter((rule) => rule.id !== ruleId) : [createFilterRule()] } : group));
  const removeGroup = (groupId: string) => onChange(value.length > 1 ? value.filter((group) => group.id !== groupId) : [createFilterGroup()]);
  const toggleValue = (groupId: string, rule: VisualizationFilterRule, option: string) => updateRule(groupId, rule.id, (current) => ({ ...current, values: current.values.includes(option) ? current.values.filter((item) => item !== option) : [...current.values, option] }));
  const closeValueMenu = () => { setActiveValuesRule(null); setValueMenuPosition(null); };
  const toggleValueMenu = (ruleId: string, trigger: HTMLButtonElement) => {
    if (activeValuesRule === ruleId) { closeValueMenu(); return; }
    const rect = trigger.getBoundingClientRect();
    const width = Math.max(220, rect.width);
    const menuHeight = 224;
    const viewportPadding = 12;
    const spaceBelow = window.innerHeight - rect.bottom;
    const openAbove = spaceBelow < menuHeight + viewportPadding && rect.top > spaceBelow;
    setValueMenuPosition({
      left: Math.max(viewportPadding, Math.min(rect.left, window.innerWidth - width - viewportPadding)),
      top: openAbove ? rect.top - 6 : rect.bottom + 6,
      width,
      openAbove,
    });
    setActiveValuesRule(ruleId);
  };
  useEffect(() => {
    if (!activeValuesRule) return;
    const dismissValueMenu = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && (target.closest("[data-visual-filter-value-menu]") || target.closest("[data-visual-filter-value-trigger]") || target.closest("[data-visual-filter-panel]"))) return;
      closeValueMenu();
    };
    const dismissOnViewportChange = () => closeValueMenu();
    document.addEventListener("pointerdown", dismissValueMenu, true);
    window.addEventListener("resize", dismissOnViewportChange);
    return () => {
      document.removeEventListener("pointerdown", dismissValueMenu, true);
      window.removeEventListener("resize", dismissOnViewportChange);
    };
  }, [activeValuesRule]);
  if (typeof document === "undefined") return null;
  return createPortal(<div className="fixed right-6 top-24 z-[90] w-[min(720px,calc(100vw-264px))] rounded-xl border border-[#dce7df] bg-white p-4 shadow-xl shadow-black/[0.08]" data-visual-filter-panel="true" data-visual-filter-logic="or-groups-and-rules" data-visual-interactive="true">
    <div className="mb-3 flex items-center justify-between gap-3"><div><div className="text-[13px] font-medium text-[#1d1d1f]">条件</div><div className="mt-0.5 text-[10px] text-[#8a9690]">组内条件同时满足，条件组之间满足任一组即可</div></div><button type="button" onClick={onCancel} className="rounded-full p-1 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label="关闭条件"><X className="h-4 w-4" /></button></div>
    <div className="max-h-[360px] space-y-3 overflow-y-auto pr-1" onScroll={closeValueMenu}>{dimensions.length ? value.map((group, groupIndex) => <div key={group.id} data-visual-filter-group={group.id} className="relative rounded-lg border border-[#e7eeea] bg-[#fbfdfc] p-3">
      {groupIndex > 0 && <div className="absolute -top-[19px] left-5 z-10 rounded-full border border-[#d8e5dd] bg-white px-2 py-0.5 text-[9px] font-medium text-[#587065]" data-filter-group-relation="or">或</div>}
      <div className="mb-2 flex items-center justify-between"><span className="text-[10px] font-medium text-[#60756b]">条件组 {groupIndex + 1}</span>{value.length > 1 && <button type="button" onClick={() => removeGroup(group.id)} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[9px] text-[#8a9690] hover:bg-white hover:text-[#b14f4f]"><Trash2 className="h-3 w-3" />删除组</button>}</div>
      <div className="space-y-1.5 border-l border-[#d6e5dc] pl-3">{group.rules.map((rule, ruleIndex) => <div key={rule.id} className="relative" data-visual-filter-rule={rule.id}>
        {ruleIndex > 0 && <div className="mb-1 flex items-center gap-2"><span className="-ml-[23px] inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-[#edf5f0] px-1 text-[9px] font-medium text-[#46705c]" data-filter-rule-relation="and">且</span><span className="h-px flex-1 bg-[#edf1ee]" /></div>}
        <div className="grid grid-cols-[minmax(128px,1fr)_118px_minmax(180px,1.35fr)_auto_auto] items-start gap-2">
          <label className="relative"><span className="sr-only">维度</span><select value={rule.field} onChange={(event) => { setActiveValuesRule(null); updateRule(group.id, rule.id, (current) => ({ ...current, field: event.target.value, values: [] })); }} className="h-9 w-full appearance-none rounded-lg border border-[#dfe7e2] bg-white px-3 pr-7 text-[11px] text-[#34443c] outline-none focus:border-[#8fbaa2] focus:ring-2 focus:ring-[#2b7b5a]/10"><option value="">选择维度</option>{dimensions.map((field) => <option key={field} value={field}>{labels[field] || field}</option>)}</select><ChevronDown className="pointer-events-none absolute right-2.5 top-3 h-3 w-3 text-[#8a9690]" /></label>
          <label className="relative"><span className="sr-only">算子</span><select value={rule.operator} onChange={(event) => updateRule(group.id, rule.id, (current) => ({ ...current, operator: event.target.value as VisualizationFilterOperator }))} className="h-9 w-full appearance-none rounded-lg border border-[#dfe7e2] bg-white px-3 pr-7 text-[11px] text-[#34443c] outline-none focus:border-[#8fbaa2] focus:ring-2 focus:ring-[#2b7b5a]/10">{visualizationFilterOperators.map((operator) => <option key={operator.value} value={operator.value}>{operator.label}</option>)}</select><ChevronDown className="pointer-events-none absolute right-2.5 top-3 h-3 w-3 text-[#8a9690]" /></label>
          <div className="relative"><button type="button" disabled={!rule.field} onClick={(event) => toggleValueMenu(rule.id, event.currentTarget)} className="flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-[#dfe7e2] bg-white px-3 text-left text-[11px] text-[#34443c] outline-none hover:border-[#bdd2c5] focus:border-[#8fbaa2] focus:ring-2 focus:ring-[#2b7b5a]/10 disabled:cursor-not-allowed disabled:bg-[#f7f8f8] disabled:text-[#b2b8b4]" aria-expanded={activeValuesRule === rule.id} data-visual-filter-value-trigger={rule.id}><span className="truncate">{rule.values.length ? (rule.values.length <= 2 ? rule.values.join("、") : `已选 ${rule.values.length} 项`) : "选择具体值"}</span><ChevronDown className="h-3 w-3 shrink-0 text-[#8a9690]" /></button>{activeValuesRule === rule.id && valueMenuPosition && createPortal(<div className="fixed z-[120] rounded-lg border border-[#dce7df] bg-white p-1.5 shadow-xl shadow-black/[0.12]" style={{ left: valueMenuPosition.left, top: valueMenuPosition.top, width: valueMenuPosition.width, transform: valueMenuPosition.openAbove ? "translateY(-100%)" : undefined }} data-visual-filter-value-menu="true" data-visual-filter-panel="true" onPointerDown={(event) => event.stopPropagation()}><div className="max-h-44 overflow-y-auto">{visualizationFilterValues(rows, rule.field).length ? visualizationFilterValues(rows, rule.field).map((option) => { const checked = rule.values.includes(option); return <button key={option} type="button" onClick={() => toggleValue(group.id, rule, option)} className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[10px] ${checked ? "bg-[#edf6f1] text-[#286e51]" : "text-[#53615a] hover:bg-[#f6f8f7]"}`}><span className={`inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border ${checked ? "border-[#5f9278] bg-[#5f9278] text-white" : "border-[#cfd9d3] bg-white"}`}>{checked && <Check className="h-2.5 w-2.5" />}</span><span className="truncate">{option}</span></button>; }) : <div className="px-2 py-5 text-center text-[10px] text-[#8a9690]">当前维度暂无可选值</div>}</div><button type="button" onClick={closeValueMenu} className="mt-1 h-7 w-full rounded-md bg-[#f4f7f5] text-[10px] text-[#4e675a] hover:bg-[#edf3ef]">完成</button></div>, document.body)}</div>
          <button type="button" onClick={() => { setActiveValuesRule(null); addRule(group.id, rule.id); }} className="inline-flex h-9 items-center gap-1 whitespace-nowrap rounded-lg px-2 text-[10px] font-medium text-[#2c7053] hover:bg-[#edf6f1]"><Plus className="h-3.5 w-3.5" />添加筛选</button>
          <button type="button" onClick={() => removeRule(group.id, rule.id)} className="inline-flex h-9 w-8 items-center justify-center rounded-lg text-[#9aa49f] hover:bg-white hover:text-[#b14f4f]" aria-label="删除筛选"><Trash2 className="h-3.5 w-3.5" /></button>
        </div>
      </div>)}</div>
    </div>) : <div className="py-8 text-center text-[11px] text-[#8a8a8e]">当前数据没有可筛选维度</div>}</div>
    {dimensions.length > 0 && <button type="button" onClick={() => { setActiveValuesRule(null); onChange([...value, createFilterGroup(dimensions[0] || "")]); }} className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-lg border border-dashed border-[#cdded4] px-3 text-[10px] font-medium text-[#4f6f5f] hover:border-[#a9c7b5] hover:bg-[#f7faf8]" data-add-or-filter-group="true"><Plus className="h-3.5 w-3.5" />添加“或”条件组</button>}
    <div className="mt-3 flex items-center justify-end gap-2 border-t border-[#edf1ee] pt-3"><label className="mr-auto inline-flex cursor-pointer items-center gap-1.5 text-[10px] text-[#53615a]"><input type="checkbox" checked={sumRows} onChange={(event) => onSumRowsChange(event.target.checked)} className="accent-[#287557]" />求和</label><button type="button" onClick={onCancel} className="h-8 rounded-lg border border-[#e1e7e3] bg-white px-3 text-[11px] text-[#636366] hover:bg-[#f7f8f8]">取消</button><button type="button" onClick={onSave} className="h-8 rounded-lg bg-[#287557] px-3 text-[11px] text-white hover:bg-[#1f6549]">保存</button></div>
  </div>, document.body);
}

function MetricTooltip({ active, payload, label, definition, fieldMetadata = {} }: { active?: boolean; payload?: Array<{ name?: string; value?: unknown; dataKey?: string | number; payload?: { field?: string } }>; label?: string; definition: string; fieldMetadata?: Record<string, FieldDisplayMetadata> }) {
  if (!active) return null;
  return <div className="max-w-[280px] rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[11px] shadow-lg shadow-black/[0.08]">
    {label ? <div className="mb-1 text-[#1d1d1f]">{label}</div> : null}
    {payload?.map((item) => { const field = item.payload?.field || String(item.dataKey || ""); return <div key={`${field}-${String(item.name)}`} className="text-[#636366]">{item.name}：{formatFieldValue(item.value, fieldMetadata[field])}</div>; })}
    <div className="mt-1.5 border-t border-[#f0f0f2] pt-1.5 leading-5 text-[#8a8a8e]">{definition}</div>
  </div>;
}

function applyVisualTableWheel(node: HTMLElement, event: WheelEvent) {
  if (event.ctrlKey || event.defaultPrevented) return false;
  const canY = node.scrollHeight > node.clientHeight + 1;
  const canX = node.scrollWidth > node.clientWidth + 1;
  if (!canY && !canX) return false;
  const deltaY = event.shiftKey ? 0 : event.deltaY;
  const deltaX = event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX;
  if (!deltaY && !deltaX) return false;
  let used = false;
  if (canY && deltaY) {
    const atTop = node.scrollTop <= 0;
    const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1;
    if ((deltaY < 0 && !atTop) || (deltaY > 0 && !atBottom)) {
      node.scrollTop += deltaY;
      used = true;
    }
  }
  if (canX && deltaX) {
    const atLeft = node.scrollLeft <= 0;
    const atRight = node.scrollLeft + node.clientWidth >= node.scrollWidth - 1;
    if ((deltaX < 0 && !atLeft) || (deltaX > 0 && !atRight)) {
      node.scrollLeft += deltaX;
      used = true;
    }
  }
  if (!used) return false;
  event.preventDefault();
  event.stopPropagation();
  return true;
}

function useVisualTableScrollLock(scrollerRef: { current: HTMLDivElement | null }) {
  useEffect(() => {
    const node = scrollerRef.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      applyVisualTableWheel(node, event);
    };
    node.addEventListener("wheel", onWheel, { passive: false, capture: true });
    return () => node.removeEventListener("wheel", onWheel, { capture: true });
  }, [scrollerRef]);
}

function useVisualTableRegionWheelLock(regionRef: { current: HTMLElement | null }, enabled: boolean) {
  useEffect(() => {
    const region = regionRef.current;
    if (!region || !enabled) return;
    const onWheel = (event: WheelEvent) => {
      const scroller = region.querySelector<HTMLElement>("[data-visual-table-scroll]");
      if (!scroller || !(event.target instanceof Node) || !scroller.contains(event.target)) return;
      applyVisualTableWheel(scroller, event);
    };
    region.addEventListener("wheel", onWheel, { passive: false, capture: true });
    return () => region.removeEventListener("wheel", onWheel, { capture: true });
  }, [enabled, regionRef]);
}

type ResultTableProps = {
  rows: AnalysisRow[];
  emptyLabel: string;
  dimensionFields?: string[];
  metricFields?: string[];
  mergedDimensionFields?: string[];
  frozenColumnFields?: string[];
  frozenRowKeys?: string[];
  onDimensionFieldsChange?: (fields: string[]) => void;
  onMetricFieldsChange?: (fields: string[]) => void;
  onDimensionHeaderContextMenu?: (field: string, event: ReactMouseEvent<HTMLTableCellElement>) => void;
  onRowContextMenu?: (rowKey: string, event: ReactMouseEvent<HTMLTableCellElement>) => void;
  fillHeight?: boolean;
  compact?: boolean;
};

function ResultTable({ rows, emptyLabel, dimensionFields, metricFields, mergedDimensionFields = [], frozenColumnFields = [], frozenRowKeys = [], onDimensionFieldsChange, onMetricFieldsChange, onDimensionHeaderContextMenu, onRowContextMenu, fillHeight, compact }: ResultTableProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  useVisualTableScrollLock(scrollerRef);
  const instance = useId();
  const availableFields = useMemo(() => analysisRawFields(rows), [rows]);
  const controlled = Boolean(dimensionFields && metricFields);
  const [localFields, setLocalFields] = useState(availableFields);
  const [sortState, setSortState] = useState<TableSortState>(null);
  const fields = controlled ? orderedTableFields(dimensionFields || [], metricFields || [], frozenColumnFields) : [...frozenColumnFields.filter((field) => localFields.includes(field)), ...localFields.filter((field) => !frozenColumnFields.includes(field))];
  const rowEntries = useMemo(() => rows.map((row, index) => ({ key: tableRowKey(row, index), row, index })), [rows]);
  const availableRowKeys = useMemo(() => rowEntries.map((entry) => entry.key), [rowEntries]);
  const rowByKey = useMemo(() => new Map(rowEntries.map((entry) => [entry.key, entry.row])), [rowEntries]);
  const originalIndexByRow = useMemo(() => new Map(rowEntries.map((entry) => [entry.row, entry.index])), [rowEntries]);
  const [rowKeys, setRowKeys] = useState(availableRowKeys);
  const [columnLefts, setColumnLefts] = useState<number[]>([]);
  const [rowTops, setRowTops] = useState<number[]>([]);
  useEffect(() => setLocalFields((current) => reconcileFields(current, availableFields, availableFields)), [availableFields.join("\u0000")]);
  useEffect(() => setRowKeys((current) => reconcileFields(current, availableRowKeys, availableRowKeys)), [availableRowKeys.join("\u0000")]);
  useEffect(() => setSortState((current) => current && fields.includes(current.field) ? current : null), [fields.join("\u0000")]);
  const pinnedRowKeys = frozenRowKeys.filter((key) => rowByKey.has(key));
  const orderedRows = useMemo(() => {
    const rest = rowKeys.filter((key) => !pinnedRowKeys.includes(key));
    return [...pinnedRowKeys, ...rest].map((key) => rowByKey.get(key)).filter((row): row is AnalysisRow => Boolean(row));
  }, [pinnedRowKeys.join("\u0000"), rowByKey, rowKeys]);
  const localReorder = useRightPressReorder(localFields, setLocalFields, `${instance}-columns`);
  const dimensionReorder = useRightPressReorder(dimensionFields || [], (updater) => onDimensionFieldsChange?.(updater(dimensionFields || [])), `${instance}-dimensions`, (field) => rows[0]?.fieldLabels[field] || field);
  const metricReorder = useRightPressReorder(metricFields || [], (updater) => onMetricFieldsChange?.(updater(metricFields || [])), `${instance}-metrics`, (field) => rows[0]?.fieldLabels[field] || field);
  const rowReorder = useRightPressReorder(rowKeys, setRowKeys, `${instance}-rows`, (key) => orderedRows.find((row, index) => tableRowKey(row, index) === key)?.branch || "表格行");
  const fieldLabels = rows[0]?.fieldLabels || {};
  const fieldMetadata = rows[0]?.fieldMetadata || {};
  const controllerFor = (field: string) => !controlled ? localReorder : dimensionFields?.includes(field) ? dimensionReorder : metricReorder;
  const sortedRows = useMemo(() => sortTableRows(
    groupRowsForMergedDimensions(orderedRows, dimensionFields || [], mergedDimensionFields),
    sortState,
  ), [dimensionFields, mergedDimensionFields, orderedRows, sortState]);
  const displayedRows = useMemo(() => {
    if (!pinnedRowKeys.length) return sortedRows;
    const pinned = pinnedRowKeys.map((key) => rowByKey.get(key)).filter((row): row is AnalysisRow => Boolean(row));
    const pinnedSet = new Set(pinned);
    return [...pinned, ...sortedRows.filter((row) => !pinnedSet.has(row))];
  }, [pinnedRowKeys, rowByKey, sortedRows]);
  useLayoutEffect(() => {
    const root = scrollerRef.current;
    if (!root) return;
    const lefts: number[] = [];
    let left = 0;
    frozenColumnFields.forEach((field) => {
      lefts.push(left);
      const cell = root.querySelector(`[data-visual-table-field="${cssEscape(field)}"]`);
      left += cell instanceof HTMLElement ? cell.getBoundingClientRect().width : 0;
    });
    setColumnLefts(lefts);
    const header = root.querySelector("thead tr");
    const headerHeight = header instanceof HTMLElement ? header.getBoundingClientRect().height : 0;
    const tops: number[] = [];
    let top = headerHeight;
    pinnedRowKeys.forEach((key) => {
      tops.push(top);
      const row = root.querySelector(`[data-visual-table-row="${cssEscape(key)}"]`);
      top += row instanceof HTMLElement ? row.getBoundingClientRect().height : 0;
    });
    setRowTops(tops);
  }, [displayedRows.length, fields.join("\u0000"), frozenColumnFields.join("\u0000"), pinnedRowKeys.join("\u0000")]);
  return <div ref={scrollerRef} className={`min-h-0 overflow-auto overscroll-contain rounded-lg border border-[#edf1ee] bg-white ${fillHeight ? "min-h-0 flex-1" : compact ? "max-h-[220px]" : "max-h-[300px]"}`} style={{ overscrollBehavior: "none" }} data-visual-table-scroll="true" data-table-long-press-reorder="true">
    <table className="w-full border-separate border-spacing-0 text-[12px]">
      <thead className="sticky top-0 z-20 bg-[#f5faf7]" data-visual-table-frozen-header="true"><tr className="text-[#6f8177]">{fields.map((field, fieldIndex) => {
        const reorder = controllerFor(field);
        const dimension = Boolean(controlled && dimensionFields?.includes(field));
        const frozen = frozenColumnFields.includes(field);
        const frozenIndex = frozenColumnFields.indexOf(field);
        const direction = sortState?.field === field ? sortState.direction : null;
        const SortIcon = direction === "asc" ? ArrowUp : direction === "desc" ? ArrowDown : ArrowUpDown;
        const nextLabel = direction === "asc" ? "切换为倒排" : direction === "desc" ? "恢复原始顺序" : "切换为正排";
        return <th key={field} data-visual-table-field={field} data-reorder-field={field} data-reorder-group={reorder.group} data-reorder-floating={reorder.floating === field ? "true" : "false"} data-reorder-target={reorder.target === field ? "true" : "false"} data-visual-table-dimension-header={dimension ? field : undefined} data-visual-table-metric-header={!dimension && controlled ? field : undefined} data-visual-table-frozen-column={frozen ? field : undefined} onContextMenu={onDimensionHeaderContextMenu ? (event) => onDimensionHeaderContextMenu(field, event) : undefined} onClick={(event) => { if (reorder.consumeClick()) event.stopPropagation(); }} onPointerDown={(event) => reorder.start(field, event)} onPointerUp={() => reorder.end(true)} onPointerCancel={() => reorder.end(false)} className={`sticky top-0 cursor-grab whitespace-nowrap border-b border-[#edf1ee] px-3 py-2.5 text-left font-medium active:cursor-grabbing ${frozen ? "z-30 bg-[#eef6f1] shadow-[1px_0_0_#dce7df]" : "z-20 bg-[#f5faf7] shadow-[0_1px_0_0_#edf1ee]"} ${reorder.floating === field ? "bg-[#eaf7ef] text-[#178a53] shadow-[inset_0_0_0_1px_#b7ddc3]" : reorder.target === field ? "bg-[#f6fbf8] text-[#178a53] shadow-[inset_2px_0_0_#2ca66f]" : ""}`} style={frozen ? { left: columnLefts[frozenIndex] || 0 } : undefined}><span className="inline-flex items-center gap-1.5"><span>{fieldLabels[field] || field}</span>{frozen ? <Pin className="h-3 w-3 text-[#178a53]" /> : null}<button type="button" onPointerDown={(event) => event.stopPropagation()} onPointerUp={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); setSortState((current) => nextTableSortState(current, field)); }} aria-label={`${fieldLabels[field] || field}：${nextLabel}`} title={nextLabel} data-visual-table-sort={field} data-visual-table-sort-direction={direction || "original"} className={`rounded p-0.5 transition-colors hover:bg-white ${direction ? "text-[#178a53]" : "text-[#9aa7a0]"}`}><SortIcon className="h-3 w-3" /></button></span></th>;
      })}</tr></thead>
      <tbody>{displayedRows.length ? displayedRows.map((row, index) => {
        const originalIndex = originalIndexByRow.get(row) ?? index;
        const rowKey = tableRowKey(row, originalIndex);
        const frozenRow = pinnedRowKeys.includes(rowKey);
        const frozenRowIndex = pinnedRowKeys.indexOf(rowKey);
        const cellSpans = fields.map((field) => mergedDimensionCellSpan(displayedRows, index, field, dimensionFields || [], mergedDimensionFields));
        const firstVisibleFieldIndex = Math.max(0, cellSpans.findIndex((span) => span > 0));
        return <tr key={rowKey} data-visual-table-row={rowKey} data-visual-table-frozen-row={frozenRow ? rowKey : undefined} data-reorder-floating={rowReorder.floating === rowKey ? "true" : "false"} data-reorder-target={rowReorder.target === rowKey ? "true" : "false"} className={`${rowReorder.floating === rowKey ? "bg-[#eaf7ef] shadow-[inset_0_0_0_1px_#b7ddc3]" : rowReorder.target === rowKey ? "bg-[#f6fbf8] shadow-[inset_0_2px_0_#2ca66f]" : frozenRow ? "bg-[#f7fbf9]" : ""}`} style={frozenRow ? { position: "sticky", top: rowTops[frozenRowIndex] || 0, zIndex: 15 } : undefined}>{fields.map((field, fieldIndex) => {
          const span = cellSpans[fieldIndex];
          if (span === 0) return null;
          const frozen = frozenColumnFields.includes(field);
          const frozenIndex = frozenColumnFields.indexOf(field);
          return <td key={field} rowSpan={span > 1 ? span : undefined} data-table-merged-dimension={span > 1 ? field : undefined} onContextMenu={onRowContextMenu ? (event) => onRowContextMenu(rowKey, event) : undefined} {...(fieldIndex === firstVisibleFieldIndex ? { "data-reorder-field": rowKey, "data-reorder-group": rowReorder.group, onClick: (event: ReactMouseEvent<HTMLTableCellElement>) => { if (rowReorder.consumeClick()) event.stopPropagation(); }, onPointerDown: (event: ReactPointerEvent<HTMLTableCellElement>) => rowReorder.start(rowKey, event), onPointerUp: () => rowReorder.end(true), onPointerCancel: () => rowReorder.end(false) } : {})} className={`whitespace-nowrap border-b border-[#f2f4f3] px-3 py-2.5 align-middle text-[#3a3a3c] ${span > 1 ? "bg-[#f8fbf9] font-medium text-[#265d43]" : frozen || frozenRow ? "bg-[#f7fbf9]" : ""} ${frozen ? "sticky z-[16] shadow-[1px_0_0_#edf1ee]" : ""} ${fieldIndex === firstVisibleFieldIndex ? "cursor-grab active:cursor-grabbing" : ""}`} style={frozen ? { left: columnLefts[frozenIndex] || 0 } : undefined}>{displayRawCell(row.raw[field], fieldMetadata[field])}</td>;
        })}</tr>;
      }) : <tr><td className="px-3 py-8 text-center text-[#8a8a8e]" colSpan={Math.max(1, fields.length)}>{emptyLabel}</td></tr>}</tbody>
    </table>
    <ReorderPreview reorder={localReorder} /><ReorderPreview reorder={dimensionReorder} /><ReorderPreview reorder={metricReorder} /><ReorderPreview reorder={rowReorder} />
  </div>;
}

function cssEscape(value: string) {
  return typeof CSS !== "undefined" && typeof CSS.escape === "function" ? CSS.escape(value) : value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function tableRowKey(row: AnalysisRow, index: number) { return `${row.branch}\u0000${JSON.stringify(row.raw)}\u0000${index}`; }

type VisualizationRendererProps = { type: VisualizationType; rows: AnalysisRow[]; metricFields: string[]; dimensionFields: string[]; mergedDimensionFields: string[]; frozenColumnFields: string[]; frozenRowKeys: string[]; filters: VisualizationFilters; filterGroups: VisualizationFilterGroup[]; sumFilteredRows: boolean; comboLineFields: string[]; onComboLineFieldsChange: (fields: string[]) => void; onMetricFieldsChange: (fields: string[]) => void; onDimensionFieldsChange: (fields: string[]) => void; onDimensionHeaderContextMenu: (field: string, event: ReactMouseEvent<HTMLTableCellElement>) => void; onRowContextMenu: (rowKey: string, event: ReactMouseEvent<HTMLTableCellElement>) => void; metricReorder: ReorderController; compact?: boolean; showData: boolean; fillHeight?: boolean };

function VisualizationRenderer({ type, rows, metricFields, dimensionFields, mergedDimensionFields, frozenColumnFields, frozenRowKeys, filters, filterGroups, sumFilteredRows, comboLineFields, onComboLineFieldsChange, onMetricFieldsChange, onDimensionFieldsChange, onDimensionHeaderContextMenu, onRowContextMenu, metricReorder, compact, showData, fillHeight }: VisualizationRendererProps) {
  const height = fillHeight ? "100%" : compact ? 220 : 300;
  const [seriesMenu, setSeriesMenu] = useState<string | null>(null);
  const [scatterAxis, setScatterAxis] = useState<"x" | "y" | null>(null);
  const fieldLabels = rows[0]?.fieldLabels || {};
  const fieldMetadata = rows[0]?.fieldMetadata || {};
  const metricDefinition = rows[0]?.metricDefinition || "当前图表使用已选指标与维度组合生成，口径以原始数据字段为准。";
  const points = useMemo(() => buildVisualDataPoints(rows, metricFields, dimensionFields, filters, sumFilteredRows, filterGroups), [dimensionFields, filterGroups, filters, metricFields, rows, sumFilteredRows]);
  const visiblePoints = selectVisibleVisualPoints(points, type, compact);
  const chartData = visiblePoints.map((point) => ({ category: point.label, ...point.values }));
  const filteredRows = filterVisualizationRows(rows, filters, filterGroups);
  const tick = { fontSize: 10, fill: "#8a9690" };
  const label = (field: string) => fieldLabels[field] || field;
  const format = (field: string, value: unknown) => formatFieldValue(value, fieldMetadata[field]);
  const common = <><CartesianGrid stroke="#edf1ee" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="category" tick={tick} tickLine={false} axisLine={false} interval="preserveStartEnd" /><YAxis tick={tick} tickLine={false} axisLine={false} /><Tooltip content={<MetricTooltip definition={metricDefinition} fieldMetadata={fieldMetadata} />} /><Legend wrapperStyle={{ fontSize: 10, color: "#53615a" }} /></>;
  if (type === "text") return null;
  if (!rows.length || !metricFields.length) return null;

  if (type === "kpi") {
    const cards = dimensionFields.length ? visiblePoints.flatMap((point) => metricFields.map((field) => ({ key: `${point.key}-${field}`, field, name: `${label(field)} · ${point.label}`, value: point.values[field] || 0 }))) : metricFields.map((field) => ({ key: field, field, name: label(field), value: metricTotal(rows, field, filters, filterGroups) }));
    return <div className={`overflow-y-auto rounded-lg border border-[#edf1ee] bg-white p-3 ${fillHeight ? "h-full" : "max-h-[300px] min-h-[220px]"}`} data-kpi-scroll="true"><div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-2.5">{cards.map((card, index) => <div key={card.key} className="flex h-[112px] min-w-0 flex-col justify-between rounded-xl border border-[#e2ece5] bg-gradient-to-br from-white to-[#f5faf7] p-3 shadow-sm shadow-black/[0.02]"><div className="line-clamp-2 text-[10px] leading-4 text-[#6f8177]">{card.name}</div><div className="text-[25px] font-light tabular-nums text-[#1d1d1f]">{format(card.field, card.value)}</div><div className="h-0.5 w-8 rounded-full" style={{ backgroundColor: chartColor(index) }} /></div>)}</div></div>;
  }
  if (type === "table") return <ResultTable rows={filteredRows.slice(0, 50)} emptyLabel="暂无可视化数据" dimensionFields={dimensionFields} metricFields={metricFields} mergedDimensionFields={mergedDimensionFields} frozenColumnFields={frozenColumnFields} frozenRowKeys={frozenRowKeys} onDimensionFieldsChange={onDimensionFieldsChange} onMetricFieldsChange={onMetricFieldsChange} onDimensionHeaderContextMenu={onDimensionHeaderContextMenu} onRowContextMenu={onRowContextMenu} fillHeight={fillHeight} compact={compact} />;
  if (type === "pivot") return <PivotTable rows={filteredRows} dimensionFields={dimensionFields} metricFields={metricFields} labels={fieldLabels} fieldMetadata={fieldMetadata} fillHeight={fillHeight} />;
  if (type === "line" || type === "area") {
    const Chart = type === "line" ? LineChart : AreaChart;
    return <ResponsiveContainer width="100%" height={height}><Chart data={chartData} margin={{ top: showData ? 28 : 12, right: 16, left: -18, bottom: 4 }}>{common}{metricFields.map((field, index) => type === "line" ? <Line key={field} type="monotone" dataKey={field} name={label(field)} stroke={chartColor(index)} strokeWidth={2} dot={{ r: 2.5 }}>{showData && <LabelList dataKey={field} position="top" formatter={(value) => format(field, value)} fill={chartColor(index)} fontSize={9} />}</Line> : <Area key={field} type="monotone" dataKey={field} name={label(field)} stroke={chartColor(index)} fill={chartColor(index)} fillOpacity={0.08 + index * 0.025} strokeWidth={2}>{showData && <LabelList dataKey={field} position="top" formatter={(value) => format(field, value)} fill={chartColor(index)} fontSize={9} />}</Area>)}</Chart></ResponsiveContainer>;
  }
  if (type === "column" || type === "bar" || type === "stacked_bar") {
    const horizontal = type !== "bar";
    return <ResponsiveContainer width="100%" height={height}><BarChart data={chartData} layout={horizontal ? "horizontal" : "vertical"} stackOffset={type === "stacked_bar" ? "expand" : undefined} margin={{ top: showData ? 28 : 12, right: type === "bar" ? 28 : 10, left: type === "bar" ? 16 : -18, bottom: 4 }}>{horizontal ? common : <><CartesianGrid stroke="#edf1ee" strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tick={tick} tickLine={false} axisLine={false} /><YAxis type="category" dataKey="category" tick={tick} tickLine={false} axisLine={false} width={72} /><Tooltip content={<MetricTooltip definition={metricDefinition} fieldMetadata={fieldMetadata} />} /><Legend wrapperStyle={{ fontSize: 10 }} /></>}{metricFields.map((field, index) => <Bar key={field} dataKey={field} name={label(field)} stackId={type === "stacked_bar" ? "total" : undefined} fill={chartColor(index)} radius={type === "stacked_bar" ? 0 : horizontal ? [4, 4, 0, 0] : [0, 4, 4, 0]} barSize={compact ? 16 : 22}>{showData && <LabelList dataKey={field} position={type === "stacked_bar" ? "center" : horizontal ? "top" : "right"} formatter={(value) => format(field, value)} fill={type === "stacked_bar" ? "#ffffff" : chartColor(index)} fontSize={9} />}</Bar>)}</BarChart></ResponsiveContainer>;
  }
  if (type === "combo") {
    const toggleSeries = (field: string) => onComboLineFieldsChange(comboLineFields.includes(field) ? comboLineFields.filter((item) => item !== field) : [...comboLineFields, field]);
    return <div className="relative h-full min-h-[220px]" onPointerDown={() => setSeriesMenu(null)}><div className="mb-1 flex flex-wrap justify-end gap-1.5">{metricFields.map((field, index) => <div key={field} className="relative" data-combo-series-control={field}><button type="button" onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); setSeriesMenu(field); }} className="inline-flex items-center gap-1 rounded-full bg-[#f5faf7] px-2 py-1 text-[9px] text-[#53615a]" title="右键切换图形"><span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: chartColor(index) }} />{label(field)} · {comboLineFields.includes(field) ? "趋势" : "柱状"}</button>{seriesMenu === field && <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={() => { toggleSeries(field); setSeriesMenu(null); }} className="absolute left-0 top-full z-30 mt-1 whitespace-nowrap rounded-lg border border-[#dce7df] bg-white px-3 py-2 text-[10px] text-[#53615a] shadow-lg" data-combo-series-menu={field}>转为{comboLineFields.includes(field) ? "柱状图" : "趋势图"}</button>}</div>)}</div><ResponsiveContainer width="100%" height={fillHeight ? "90%" : compact ? 190 : 265}><ComposedChart data={chartData} margin={{ top: showData ? 28 : 12, right: 16, left: -18, bottom: 4 }}>{common}{metricFields.map((field, index) => comboLineFields.includes(field) ? <Line key={field} type="monotone" dataKey={field} name={label(field)} stroke={chartColor(index)} strokeWidth={2.2} dot={{ r: 2.5 }}>{showData && <LabelList dataKey={field} position="top" formatter={(value) => format(field, value)} fill={chartColor(index)} fontSize={9} />}</Line> : <Bar key={field} dataKey={field} name={label(field)} fill={chartColor(index)} radius={[3, 3, 0, 0]} barSize={18}>{showData && <LabelList dataKey={field} position="top" formatter={(value) => format(field, value)} fill={chartColor(index)} fontSize={9} />}</Bar>)}</ComposedChart></ResponsiveContainer></div>;
  }
  if (type === "donut") {
    const ringGap = compact ? 11 : 15;
    const outer = compact ? 92 : 124;
    return <div className="relative"><ResponsiveContainer width="100%" height={height}><PieChart>{metricFields.map((field, metricIndex) => { const outerRadius = outer - metricIndex * ringGap; const innerRadius = outerRadius - Math.max(7, ringGap - 3); const data = visiblePoints.map((point) => ({ name: point.label, value: point.values[field] || 0, field })); return <Pie key={field} data={data} dataKey="value" nameKey="name" innerRadius={Math.max(18, innerRadius)} outerRadius={Math.max(25, outerRadius)} paddingAngle={1}>{data.map((entry, index) => <Cell key={`${field}-${entry.name}-${index}`} fill={chartColor(index)} opacity={Math.max(0.42, 1 - metricIndex * 0.09)} />)}{showData && metricIndex === 0 && <LabelList dataKey="value" position="outside" formatter={(value) => format(field, value)} fill="#53615a" fontSize={9} />}</Pie>; })}<Tooltip content={<MetricTooltip definition={metricDefinition} fieldMetadata={fieldMetadata} />} /></PieChart></ResponsiveContainer><div className="absolute bottom-1 left-1 flex max-w-[45%] flex-col gap-1">{metricFields.map((field, index) => <span key={field} className="inline-flex items-center gap-1 text-[9px] text-[#53615a]"><span className="h-1.5 w-4 rounded-full" style={{ backgroundColor: chartColor(index) }} />{label(field)}</span>)}</div></div>;
  }
  if (type === "scatter") {
    const [xField, yField] = metricFields;
    const data = visiblePoints.map((point) => ({ name: point.label, x: point.values[xField] || 0, y: point.values[yField] || 0 }));
    const replaceAxis = (field: string) => { const other = scatterAxis === "x" ? yField : xField; onMetricFieldsChange(scatterAxis === "x" ? [field, other] : [other, field]); setScatterAxis(null); };
    return <div className="relative h-full min-h-[220px]"><div className="absolute right-1 top-0 z-20 flex gap-1"><button type="button" onContextMenu={(event) => { event.preventDefault(); setScatterAxis("x"); }} className="rounded-full bg-[#f5faf7] px-2 py-1 text-[9px] text-[#53615a]">X · {label(xField)}</button><button type="button" onContextMenu={(event) => { event.preventDefault(); setScatterAxis("y"); }} className="rounded-full bg-[#f5faf7] px-2 py-1 text-[9px] text-[#53615a]">Y · {label(yField)}</button></div>{scatterAxis && <div className="absolute right-1 top-7 z-30 w-36 rounded-lg border border-[#dce7df] bg-white p-1 shadow-lg">{numericRawFields(rows).filter((field) => !metricFields.includes(field) || field === (scatterAxis === "x" ? xField : yField)).map((field) => <button key={field} type="button" onClick={() => replaceAxis(field)} className="block w-full rounded-md px-2 py-1.5 text-left text-[10px] text-[#53615a] hover:bg-[#f5faf7]">{label(field)}</button>)}</div>}<ResponsiveContainer width="100%" height={height}><ScatterChart margin={{ top: 32, right: 16, left: -8, bottom: 6 }}><CartesianGrid stroke="#edf1ee" strokeDasharray="3 3" /><XAxis type="number" dataKey="x" name={label(xField)} tick={tick} /><YAxis type="number" dataKey="y" name={label(yField)} tick={tick} /><Tooltip cursor={{ strokeDasharray: "3 3" }} /><Scatter data={data} name={`${label(xField)} × ${label(yField)}`} fill="#178a53">{showData && <LabelList dataKey="name" position="top" fill="#53615a" fontSize={9} />}</Scatter></ScatterChart></ResponsiveContainer></div>;
  }
  if (type === "funnel") {
    return <div className={`overflow-y-auto ${fillHeight ? "h-full" : "max-h-[300px]"}`}><div className="mb-2 flex flex-wrap gap-1.5">{metricFields.map((field) => <button key={field} type="button" data-reorder-field={field} data-reorder-group={metricReorder.group} data-reorder-floating={metricReorder.floating === field ? "true" : "false"} data-reorder-target={metricReorder.target === field ? "true" : "false"} onPointerDown={(event) => metricReorder.start(field, event)} onPointerUp={() => metricReorder.end(true)} onPointerCancel={() => metricReorder.end(false)} className={`cursor-grab rounded-full border px-2 py-1 text-[9px] ${metricReorder.floating === field ? "border-[#2ca66f] bg-[#eaf7ef] text-[#178a53]" : "border-[#dce7df] bg-white text-[#53615a]"}`}>{label(field)}</button>)}</div><div className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-2">{visiblePoints.map((point) => { const data = metricFields.map((field, index) => ({ name: label(field), value: point.values[field] || 0, fill: chartColor(index), field })); return <div key={point.key} className="h-[230px] rounded-lg border border-[#edf1ee] bg-white p-2"><div className="truncate text-center text-[10px] text-[#53615a]">{point.label}</div><ResponsiveContainer width="100%" height="90%"><FunnelChart><Tooltip content={<MetricTooltip definition={metricDefinition} fieldMetadata={fieldMetadata} />} /><Funnel dataKey="value" data={data} isAnimationActive={false}><LabelList position="right" fill="#636366" stroke="none" dataKey="name" fontSize={9} /></Funnel></FunnelChart></ResponsiveContainer></div>; })}</div><ReorderPreview reorder={metricReorder} /></div>;
  }
  if (type === "treemap") {
    const field = metricFields[0];
    const data = visiblePoints.map((point) => ({ name: `${point.label}\n${label(field)} ${format(field, point.values[field])}`, size: Math.max(0, point.values[field]) }));
    return <ResponsiveContainer width="100%" height={height}><Treemap data={data} dataKey="size" nameKey="name" stroke="#ffffff" fill="#178a53" aspectRatio={4 / 3}><Tooltip /></Treemap></ResponsiveContainer>;
  }
  const radarData = visiblePoints.map((point) => ({ category: point.label.length > 12 ? `${point.label.slice(0, 12)}…` : point.label, ...point.values }));
  return <ResponsiveContainer width="100%" height={height}><RadarChart data={radarData} outerRadius={compact ? "58%" : "66%"} margin={{ top: 26, right: 44, bottom: 26, left: 44 }}><PolarGrid stroke="#dfe8e2" /><PolarAngleAxis dataKey="category" tick={{ fontSize: 9, fill: "#6f8177" }} /><PolarRadiusAxis angle={90} tick={{ fontSize: 8, fill: "#a2aca6" }} axisLine={false} /><Tooltip content={<MetricTooltip definition={metricDefinition} fieldMetadata={fieldMetadata} />} /><Legend wrapperStyle={{ fontSize: 10 }} />{metricFields.map((field, index) => <Radar key={field} name={label(field)} dataKey={field} stroke={chartColor(index)} fill={chartColor(index)} fillOpacity={0.05 + index * 0.025} strokeWidth={2}>{showData && <LabelList dataKey={field} position="top" formatter={(value) => format(field, value)} fill={chartColor(index)} fontSize={9} />}</Radar>)}</RadarChart></ResponsiveContainer>;
}

function numericRawFields(rows: AnalysisRow[]) {
  const metadata = rows[0]?.fieldMetadata || {};
  return analysisRawFields(rows).filter((field) => {
    if (metadata[field]?.semanticRole === "metric") return true;
    if (metadata[field]?.semanticRole === "dimension" || metadata[field]?.semanticRole === "date") return false;
    if (rows.some((row) => periodLikeValue(row.raw[field]))) return false;
    return rows.some((row) => numberValue(row.raw[field]) !== null);
  });
}

function periodLikeValue(value: unknown) {
  return /^(?:19|20)\d{2}[-/.年](?:0?[1-9]|1[0-2])(?:[-/.日](?:0?[1-9]|[12]\d|3[01]))?$/.test(String(value ?? "").trim());
}

function numberValue(value: unknown) {
  const number = typeof value === "number" ? value : Number(String(value ?? "").replace(/,/g, ""));
  return Number.isFinite(number) ? number : null;
}

function chartColor(index: number) {
  return visualizationChartColor(index);
}

function PivotTable({ rows, dimensionFields, metricFields, labels, fieldMetadata, fillHeight }: { rows: AnalysisRow[]; dimensionFields: string[]; metricFields: string[]; labels: Record<string, string>; fieldMetadata: Record<string, FieldDisplayMetadata>; fillHeight?: boolean }) {
  const rowField = dimensionFields[0];
  if (!rowField || !metricFields.length) return <ResultTable rows={rows.slice(0, 50)} emptyLabel="当前数据维度不足，已回退明细表" dimensionFields={dimensionFields} metricFields={metricFields} fillHeight={fillHeight} />;
  return <PaginatedPivotTable rows={rows} dimensionFields={dimensionFields} metricFields={metricFields} labels={labels} fieldMetadata={fieldMetadata} fillHeight={fillHeight} rowField={rowField} />;
}

function PaginatedPivotTable({ rows, dimensionFields, metricFields, labels, fieldMetadata, fillHeight, rowField }: { rows: AnalysisRow[]; dimensionFields: string[]; metricFields: string[]; labels: Record<string, string>; fieldMetadata: Record<string, FieldDisplayMetadata>; fillHeight?: boolean; rowField: string }) {
  const tableRef = useRef<HTMLDivElement>(null);
  useVisualTableScrollLock(tableRef);
  const columnFields = useMemo(() => dimensionFields.slice(1), [dimensionFields]);
  const pivotData = useMemo(() => {
    const columnFor = (row: AnalysisRow) => columnFields.length ? columnFields.map((field) => displayRawCell(row.raw[field], fieldMetadata[field])).join(" · ") : "汇总";
    const rowLabels = Array.from(new Set(rows.map((row) => String(row.raw[rowField] ?? "未分类"))));
    const columnLabels = Array.from(new Set(rows.map(columnFor)));
    const values = new Map<string, number>();
    rows.forEach((row) => {
      const rowLabel = String(row.raw[rowField] ?? "未分类");
      const columnLabel = columnFor(row);
      metricFields.forEach((metric) => {
        const key = `${rowLabel}\u0000${columnLabel}\u0000${metric}`;
        values.set(key, (values.get(key) || 0) + (numberValue(row.raw[metric]) || 0));
      });
    });
    return { rowLabels, columnLabels, values };
  }, [columnFields, fieldMetadata, metricFields, rowField, rows]);
  const { rowLabels, columnLabels, values } = pivotData;
  const pivotColumnPageSize = Math.max(1, Math.min(12, Math.floor(24 / Math.max(1, metricFields.length))));
  const rowPagination = useClientPagination(rowLabels, 20);
  const columnPagination = useClientPagination(columnLabels, pivotColumnPageSize);
  const columns = columnLabels.flatMap((column) => metricFields.map((metric) => ({ column, metric })));
  const visibleColumns = columnPagination.items.flatMap((column) => metricFields.map((metric) => ({ column, metric })));
  const cellValue = (row: string, column: string, metric: string) => values.get(`${row}\u0000${column}\u0000${metric}`) || 0;
  const rowMetricTotal = (row: string, metric: string) => columnLabels.reduce((sum, column) => sum + cellValue(row, column, metric), 0);
  const columnMetricTotal = (column: string, metric: string) => rowLabels.reduce((sum, row) => sum + cellValue(row, column, metric), 0);
  return <div data-pivot-table="true" className={fillHeight ? "flex min-h-0 flex-1 flex-col" : ""}>
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0 flex-1 truncate text-[10px] text-[#8a9690]">维度：{dimensionFields.map((field) => labels[field] || field).join(" → ")} · 指标：{metricFields.map((field) => labels[field] || field).join("、")}</div>
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
        {rowPagination.paginated && <DataPageSelector page={rowPagination.page} totalPages={rowPagination.totalPages} shownCount={rowPagination.items.length} totalCount={rowPagination.total} onChange={rowPagination.setPage} ariaLabel="交叉表行分页" compact className="[&>span]:hidden" />}
        {columnPagination.paginated && <DataPageSelector page={columnPagination.page} totalPages={columnPagination.totalPages} shownCount={columnPagination.items.length} totalCount={columnPagination.total} onChange={columnPagination.setPage} ariaLabel="交叉表列分页" compact className="[&>span]:hidden" />}
        <PivotExportButton label="CSV" onClick={() => exportPivotCsv(labels[rowField] || rowField, rowLabels, columns, metricFields, cellValue, rowMetricTotal)} />
        <PivotExportButton label="HTML" onClick={() => exportPivotHtml(tableRef.current)} />
        <PivotExportButton label="PDF" onClick={() => void exportPivotPdf(tableRef.current)} />
      </div>
    </div>
    <div
      ref={tableRef}
      className={`${fillHeight ? "min-h-0 flex-1" : "max-h-[360px]"} overflow-auto overscroll-contain rounded-lg border border-[#e5e5ea] bg-white`}
      style={{ overscrollBehavior: "none", overflowAnchor: "none" }}
      data-visual-table-scroll="true"
      data-pivot-row-pagination={rowPagination.paginated ? "true" : "false"}
      data-pivot-column-pagination={columnPagination.paginated ? "true" : "false"}
    >
      <table className="min-w-full border-separate border-spacing-0 text-[11px]">
        <thead className="sticky top-0 z-20 bg-[#fafbfc]" data-visual-table-frozen-header="true">
          <tr>
            <th rowSpan={2} className="sticky left-0 z-30 min-w-[120px] border-b border-r border-[#e5e5ea] bg-[#fafbfc] px-3 py-2 text-left font-normal text-[#636366]">{labels[rowField] || rowField}</th>
            {columnPagination.items.map((column) => <th key={column} colSpan={metricFields.length} className="border-b border-r border-[#e5e5ea] px-3 py-2 text-center font-normal text-[#636366]">{column}</th>)}
            <th colSpan={metricFields.length} className="border-b border-[#e5e5ea] px-3 py-2 text-center font-normal text-[#636366]">行小计</th>
          </tr>
          <tr>
            {[...columnPagination.items, "subtotal"].flatMap((column) => metricFields.map((metric) => (
              <th key={`${column}-${metric}`} className="min-w-[96px] border-b border-r border-[#ececf0] px-3 py-2 text-right font-normal text-[#8a8a8e]">{labels[metric] || metric}</th>
            )))}
          </tr>
        </thead>
        <tbody>
          {rowPagination.items.map((rowLabel) => (
            <tr key={rowLabel}>
              <th className="sticky left-0 z-10 border-b border-r border-[#ececf0] bg-white px-3 py-2 text-left font-normal text-[#3a3a3c]">{rowLabel}</th>
              {visibleColumns.map(({ column, metric }) => <td key={`${column}-${metric}`} className="border-b border-r border-[#f0f0f2] px-3 py-2 text-right tabular-nums text-[#3a3a3c]">{formatFieldValue(cellValue(rowLabel, column, metric), fieldMetadata[metric])}</td>)}
              {metricFields.map((metric) => <td key={`subtotal-${metric}`} className="border-b border-r border-[#ececf0] bg-[#fafbfc] px-3 py-2 text-right tabular-nums text-[#1d1d1f]">{formatFieldValue(rowMetricTotal(rowLabel, metric), fieldMetadata[metric])}</td>)}
            </tr>
          ))}
          <tr>
            <th className="sticky bottom-0 left-0 z-20 border-r border-[#e5e5ea] bg-[#f2f2f7] px-3 py-2 text-left font-normal text-[#1d1d1f]">总计</th>
            {visibleColumns.map(({ column, metric }) => <td key={`${column}-${metric}`} className="sticky bottom-0 border-r border-[#e5e5ea] bg-[#f2f2f7] px-3 py-2 text-right tabular-nums text-[#1d1d1f]">{formatFieldValue(columnMetricTotal(column, metric), fieldMetadata[metric])}</td>)}
            {metricFields.map((metric) => <td key={`total-${metric}`} className="sticky bottom-0 border-r border-[#e5e5ea] bg-[#e9e9ed] px-3 py-2 text-right tabular-nums text-[#1d1d1f]">{formatFieldValue(rowLabels.reduce((sum, row) => sum + rowMetricTotal(row, metric), 0), fieldMetadata[metric])}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  </div>;
}

function PivotExportButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex h-7 items-center gap-1 rounded-md border border-[#e5e5ea] bg-white px-2 text-[9px] text-[#636366] hover:bg-[#f2f2f7]"><Download className="h-3 w-3" />{label}</button>;
}

function exportPivotCsv(rowField: string, rows: string[], columns: Array<{ column: string; metric: string }>, metrics: string[], cellValue: (row: string, column: string, metric: string) => number, rowMetricTotal: (row: string, metric: string) => number) {
  const header = [rowField, ...columns.map(({ column, metric }) => `${column} · ${metric}`), ...metrics.map((metric) => `行小计 · ${metric}`)];
  const body = rows.map((row) => [row, ...columns.map(({ column, metric }) => cellValue(row, column, metric)), ...metrics.map((metric) => rowMetricTotal(row, metric))]);
  downloadBlob(new Blob(["\ufeff", [header, ...body].map((line) => line.map(csvCell).join(",")).join("\n")], { type: "text/csv;charset=utf-8" }), "智能分析交叉表.csv");
}

function exportPivotHtml(element: HTMLElement | null) {
  if (!element) return;
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>智能分析交叉表</title><style>body{font-family:Arial,sans-serif;padding:24px;color:#222}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #ddd;padding:6px;text-align:right}th{background:#f5f5f7}</style></head><body>${element.innerHTML}</body></html>`;
  downloadBlob(new Blob([html], { type: "text/html;charset=utf-8" }), "智能分析交叉表.html");
}

async function exportPivotPdf(element: HTMLElement | null) {
  if (!element) return;
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([import("html2canvas"), import("jspdf")]);
  const canvas = await html2canvas(element, { backgroundColor: "#ffffff", scale: 2, logging: false });
  const pdf = new jsPDF({ orientation: canvas.width > canvas.height ? "landscape" : "portrait", unit: "mm", format: "a4", compress: true });
  const pageWidth = pdf.internal.pageSize.getWidth() - 16;
  const pageHeight = pdf.internal.pageSize.getHeight() - 16;
  const renderedHeight = canvas.height * pageWidth / canvas.width;
  let offset = 0;
  do { if (offset > 0) pdf.addPage(); pdf.addImage(canvas, "PNG", 8, 8 - offset, pageWidth, renderedHeight, undefined, "FAST"); offset += pageHeight; } while (offset < renderedHeight);
  pdf.save("智能分析交叉表.pdf");
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function csvCell(value: unknown) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
