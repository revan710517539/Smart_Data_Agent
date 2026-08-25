import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, BarChart3, BookmarkPlus, Check, Clock3, Lightbulb, Pencil, Plus, RotateCcw, Search, Sparkles, Table2, X } from "lucide-react";
import { useNavigate } from "react-router";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { fetchDataAssets, fetchPageDataRows, fetchTopicData, saveDataAssetItem, type PageDataAsset, type RawTableAsset, type TopicTableAsset } from "../services/dataAssetApi";
import { fetchVisualReports, upsertVisualReport, type VisualReport, type VisualReportCard, type VisualReportDestination } from "../services/visualReportApi";
import type { AnalysisRow, VisualizationType } from "./self-analysis/domain";
import { AnalysisVisualCard } from "./self-analysis/ResultViews";
import type { VisualizationCardConfig } from "./visualization/visualizationDataModel";
import { VisualReportCards } from "./visual-report/VisualReportCards";
import { StickyNoteButton, StickyNotePanel } from "./notes/StickyNote";
import { useStickyNote } from "./notes/useStickyNote";
import { PAGE_DATA_PAGE_GUTTER_CLASS } from "./page-data/PageDataComposer";
import { DEFAULT_REPORT_PAGE_TEMPLATE } from "./page-data/StandardAnalysisPage";
import { isPageDataDataset, rowsFromPageVisualDataset, rowsFromRawVisualDataset, rowsFromTopicVisualDataset, visualReportDatasetReference, type VisualReportDataset } from "./visual-report/reportData";

const emptyConfig: VisualizationCardConfig = {
  metricFields: [],
  dimensionFields: [],
  filters: {},
  filterGroups: [],
  sumFilteredRows: false,
  comboLineFields: [],
};

type VisualChartDraft = {
  type: VisualizationType;
  config: VisualizationCardConfig;
};

export function VisualReportBuilder() {
  const { tenantId, userId, selectedInstitution } = usePlatformContext();
  const navigate = useNavigate();
  const [view, setView] = useState<"landing" | "editor">("landing");
  const [reports, setReports] = useState<VisualReport[]>([]);
  const [reportSearch, setReportSearch] = useState("");
  const [report, setReport] = useState<VisualReport>(() => newVisualReport());
  const [mode, setMode] = useState<"browse" | "edit">("browse");
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(report.title);
  const [modalOpen, setModalOpen] = useState(false);
  const [rawTables, setRawTables] = useState<RawTableAsset[]>([]);
  const [topicTables, setTopicTables] = useState<TopicTableAsset[]>([]);
  const [pageDataTables, setPageDataTables] = useState<PageDataAsset[]>([]);
  const [reportLoading, setReportLoading] = useState(true);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [visualChartDrafts, setVisualChartDrafts] = useState<Record<string, VisualChartDraft>>({});
  const [visualChartDraftRevision, setVisualChartDraftRevision] = useState(0);
  const hydratedRef = useRef(false);
  const catalogLoadedRef = useRef(false);
  const savedSignatureRef = useRef("");
  const stickyNote = useStickyNote("self_analysis", `visual_report:${report.id}`);

  useEffect(() => {
    let cancelled = false;
    setReportLoading(true);
    setView("landing");
    setReports([]);
    setRawTables([]);
    setTopicTables([]);
    setPageDataTables([]);
    setVisualChartDrafts({});
    setVisualChartDraftRevision((current) => current + 1);
    catalogLoadedRef.current = false;
    hydratedRef.current = false;
    void fetchVisualReports({ tenantId, userId }).then((results) => {
      if (cancelled) return;
      setReports(sortReports(results));
      setError("");
      hydratedRef.current = true;
    }).catch((reason) => {
      if (!cancelled) setError(apiErrorMessage(reason, "可视化报表加载失败。"));
    }).finally(() => {
      if (!cancelled) setReportLoading(false);
    });
    return () => { cancelled = true; };
  }, [tenantId, userId]);

  useEffect(() => {
    if (view !== "editor" || catalogLoadedRef.current) return;
    let cancelled = false;
    setCatalogLoading(true);
    void fetchDataAssets({ tenantId, userId, scope: "visualization" }).then((catalog) => {
      if (cancelled) return;
      setRawTables(catalog.raw_tables || []);
      setTopicTables(catalog.topic_tables || []);
      setPageDataTables((catalog.page_data || []).filter((item) => item.institutionScope === "multi_institution"));
      catalogLoadedRef.current = true;
    }).catch((reason) => {
      if (!cancelled) setError(apiErrorMessage(reason, "授权数据集加载失败。"));
    }).finally(() => {
      if (!cancelled) setCatalogLoading(false);
    });
    return () => { cancelled = true; };
  }, [tenantId, userId, view]);

  useEffect(() => {
    if (!hydratedRef.current || view !== "editor") return;
    const signature = reportSignature(report);
    if (signature === savedSignatureRef.current) return;
    const timer = window.setTimeout(() => { void persistReport(report, false); }, 650);
    return () => window.clearTimeout(timer);
    // persistReport intentionally follows the current report snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, view]);

  const persistReport = async (next: VisualReport, showNotice = true) => {
    setSaving(true);
    setError("");
    try {
      const saved = await upsertVisualReport({ tenantId, userId, report: { ...next, stickyNote: stickyNote.note } });
      savedSignatureRef.current = reportSignature(saved);
      setReport(saved);
      setReports((current) => upsertReportList(current, saved));
      if (showNotice) setNotice("可视化报表已保存。");
      return saved;
    } catch (reason) {
      setError(apiErrorMessage(reason, "可视化报表保存失败。"));
      return null;
    } finally {
      setSaving(false);
    }
  };

  const commitTitle = () => {
    const title = titleDraft.trim() || "未命名可视化报表";
    const next = { ...report, title };
    setReport(next);
    setTitleDraft(title);
    setEditingTitle(false);
    void persistReport(next);
  };

  const saveDestination = async (destination: VisualReportDestination) => {
    if (!report.cards.length) {
      setError("请先新增至少一个可视化图表。" );
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (destination !== "topic") await saveAsTopic(report, rawTables, topicTables, tenantId, userId);
      if (destination === "experience") await saveAsExperience(report, selectedInstitution, tenantId, userId);
      const destinations = report.destinations.includes(destination) ? report.destinations : [...report.destinations, destination];
      const saved = await upsertVisualReport({ tenantId, userId, report: { ...report, destinations } });
      savedSignatureRef.current = reportSignature(saved);
      setReport(saved);
      setReports((current) => upsertReportList(current, saved));
      setNotice(destinationMessage(destination));
      window.dispatchEvent(new CustomEvent("smart-data-agent-visual-report-saved", { detail: saved }));
      if (destination === "mine") navigate("/self-analysis/reports");
    } catch (reason) {
      setError(apiErrorMessage(reason, `${destinationLabel(destination)}失败。`));
    } finally {
      setSaving(false);
    }
  };

  const addCard = (card: VisualReportCard) => {
    const next = { ...report, cards: [...report.cards, card] };
    setReport(next);
    setModalOpen(false);
    resetVisualChartDrafts();
    void persistReport(next);
  };

  const updateVisualChartDraft = (key: string, patch: Partial<VisualChartDraft>) => {
    setVisualChartDrafts((current) => ({
      ...current,
      [key]: {
        type: current[key]?.type || "table",
        config: current[key]?.config || emptyConfig,
        ...patch,
      },
    }));
  };

  const resetVisualChartDrafts = () => {
    if (typeof window !== "undefined") {
      const datasets: VisualReportDataset[] = [...rawTables, ...topicTables, ...pageDataTables];
      for (const dataset of datasets) {
        sessionStorage.removeItem(visualChartSessionKey(report.id, visualChartDraftRevision, dataset));
      }
    }
    setVisualChartDrafts({});
    setVisualChartDraftRevision((current) => current + 1);
  };

  const openReport = (selected: VisualReport, nextMode: "browse" | "edit" = "edit") => {
    resetVisualChartDrafts();
    setReport(selected);
    setTitleDraft(selected.title);
    savedSignatureRef.current = reportSignature(selected);
    setEditingTitle(false);
    setModalOpen(false);
    setMode(nextMode);
    setNotice("");
    setError("");
    setView("editor");
  };

  const createReport = () => openReport(newVisualReport(), "edit");

  const previewReport = async () => {
    if (mode === "browse") {
      setMode("edit");
      return;
    }
    const saved = await persistReport(report);
    if (saved) setMode("browse");
  };

  const filteredReports = useMemo(() => {
    const keyword = reportSearch.trim().toLocaleLowerCase();
    if (!keyword) return reports;
    return reports.filter((item) => reportSearchText(item).includes(keyword));
  }, [reportSearch, reports]);
  const recentReports = useMemo(() => reports.slice(0, 6), [reports]);
  const recommendedReports = useMemo(() => [...reports]
    .filter((item) => item.cards.length > 0)
    .sort((left, right) => recommendationScore(right) - recommendationScore(left) || reportTime(right) - reportTime(left))
    .slice(0, 6), [reports]);

  if (view === "landing") {
    return <VisualReportLanding
      loading={reportLoading}
      error={error}
      search={reportSearch}
      onSearch={setReportSearch}
      onCreate={createReport}
      onOpen={openReport}
      searchResults={filteredReports}
      recentReports={recentReports}
      recommendedReports={recommendedReports}
    />;
  }

  return (
    <div className={PAGE_DATA_PAGE_GUTTER_CLASS} data-visual-report-builder="true" data-visual-report-mode={mode} data-default-report-page-template={DEFAULT_REPORT_PAGE_TEMPLATE}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <button type="button" onClick={() => setView("landing")} className="mb-2 inline-flex items-center gap-1 text-[10px] text-[#7d8781] hover:text-[#178a53]" data-visual-report-back="true"><ArrowLeft className="h-3 w-3" />返回报表首页</button>
          {editingTitle ? (
            <input
              autoFocus
              value={titleDraft}
              onChange={(event) => setTitleDraft(event.target.value)}
              onBlur={commitTitle}
              onKeyDown={(event) => {
                if (event.key === "Enter") event.currentTarget.blur();
                if (event.key === "Escape") { setTitleDraft(report.title); setEditingTitle(false); }
              }}
              aria-label="可视化报表名称"
              className="h-9 w-full max-w-[520px] rounded-lg border border-[#cfe1d5] bg-white px-3 text-[18px] text-[#1d1d1f] outline-none ring-2 ring-[#2ca66f]/10"
            />
          ) : (
            <button type="button" onDoubleClick={() => setEditingTitle(true)} className="max-w-full cursor-text truncate rounded-md px-1 py-0.5 text-left text-[18px] tracking-tight text-[#1d1d1f] hover:bg-[#f5faf7]" title="双击修改报表名称" data-visual-report-title="true">
              {report.title}
            </button>
          )}
          <p className="mt-1 text-[12px] text-[#9a9aa0]">双击名称编辑，点击其他位置自动保存 · 当前机构：{selectedInstitution}</p>
        </div>
        <div className="flex w-fit min-h-9 shrink-0 flex-wrap items-center justify-end gap-[0.2cm]" data-page-header-actions="true">
          <DestinationButton label="存我的" icon={BookmarkPlus} done={report.destinations.includes("mine")} disabled={saving} onClick={() => void saveDestination("mine")} />
          <DestinationButton label="存经验" icon={Lightbulb} done={report.destinations.includes("experience")} disabled={saving} onClick={() => void saveDestination("experience")} />
          <DestinationButton label="存周报" icon={BookmarkPlus} done={report.destinations.includes("weekly")} disabled={saving} onClick={() => void saveDestination("weekly")} />
          <StickyNoteButton onClick={stickyNote.show} className="text-[#53615a]" />
          <button type="button" onClick={() => void previewReport()} disabled={saving} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#dfe7e2] bg-white px-3 text-[12px] text-[#53615a] hover:bg-[#f4f8f5] disabled:cursor-wait disabled:opacity-60" data-visual-report-mode-toggle="true">
            {mode === "browse" ? <Pencil className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
            {mode === "browse" ? "编辑" : "保存"}
          </button>
        </div>
      </div>

      {notice && <div className="mb-4 rounded-lg border border-[#d7efd9] bg-[#eef8f1] px-3 py-2 text-[11px] text-[#258a3f]" role="status">{notice}</div>}
      {error && <div className="mb-4 rounded-lg border border-[#ffd0d0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#c84034]" role="alert">{error}</div>}
      <div className="min-h-[620px] rounded-xl border border-[#eef1ef] bg-white p-4 md:p-5" data-visual-report-canvas="true" data-report-list-loading={reportLoading ? "true" : "false"}>
          <StickyNotePanel className="mb-4" note={stickyNote.note} editing={stickyNote.editing} onChange={stickyNote.updateItems} onFinishEdit={stickyNote.finishEdit} onStartEdit={() => stickyNote.setEditing(true)} onHide={stickyNote.hide} uploadContext={stickyNote.uploadContext} />
          <VisualReportCards report={report} editable={mode === "edit"} onChange={setReport} railPageKey="visual-reports" />
          {mode === "edit" && (
            <button type="button" disabled={catalogLoading} onClick={() => setModalOpen(true)} className={`group flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[#cfdad3] bg-[#fbfdfc] text-[12px] text-[#758079] transition-colors hover:border-[#8fc8a4] hover:bg-[#f5faf7] hover:text-[#178a53] disabled:cursor-wait disabled:opacity-60 ${report.cards.length ? "mt-4 min-h-[140px]" : "min-h-[560px]"}`} data-add-visual-report-chart="true">
              <span className="flex h-10 w-10 items-center justify-center rounded-full border border-[#dbe5df] bg-white group-hover:border-[#b8d9c4]"><Plus className="h-5 w-5" /></span>
              {catalogLoading ? "正在准备数据集…" : "新增图表"}
            </button>
          )}
          {mode === "browse" && !report.cards.length && <div className="flex min-h-[560px] items-center justify-center text-center"><div><Table2 className="mx-auto h-8 w-8 text-[#d0d5d2]" /><div className="mt-3 text-[12px] text-[#8f9692]">当前报表还是空白页</div><div className="mt-1 text-[10px] text-[#b1b6b3]">点击右上角“编辑”后新增图表</div></div></div>}
      </div>
      {saving && <div className="mt-2 text-right text-[10px] text-[#9aa19d]">正在保存…</div>}
      {modalOpen && <VisualChartModal rawTables={rawTables} topicTables={topicTables} tenantId={tenantId} userId={userId} reportId={report.id} drafts={visualChartDrafts} draftRevision={visualChartDraftRevision} onDraftChange={updateVisualChartDraft} onRestore={resetVisualChartDrafts} onCancel={() => setModalOpen(false)} onSave={addCard} />}
    </div>
  );
}

function VisualReportLanding({ loading, error, search, onSearch, onCreate, onOpen, searchResults, recentReports, recommendedReports }: {
  loading: boolean;
  error: string;
  search: string;
  onSearch: (value: string) => void;
  onCreate: () => void;
  onOpen: (report: VisualReport, mode?: "browse" | "edit") => void;
  searchResults: VisualReport[];
  recentReports: VisualReport[];
  recommendedReports: VisualReport[];
}) {
  const searching = Boolean(search.trim());
  const hasLoadedReports = searchResults.length > 0 || recentReports.length > 0 || recommendedReports.length > 0;
  const showCollections = !loading || hasLoadedReports;
  return <div className="p-4 md:p-7" data-visual-report-landing="true">
    <div className="mb-6 flex items-start justify-between gap-3">
      <div>
        <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">可视化报表</h2>
        <p className="mt-1 text-[12px] text-[#9a9aa0]">查找并继续加工已有报表，或从空白画布新建报表。</p>
      </div>
      <div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true" />
    </div>
    <div className="mb-6 flex items-center gap-3">
      <label className="relative min-w-0 flex-1">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9aa29e]" />
        <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="搜索曾经创建过的报表" aria-label="搜索可视化报表" className="h-11 w-full rounded-xl border border-[#e0e7e3] bg-white pl-10 pr-4 text-[12px] outline-none transition-colors focus:border-[#89c4a0] focus:ring-2 focus:ring-[#2ca66f]/10" />
      </label>
      <button type="button" onClick={onCreate} className="inline-flex h-11 shrink-0 items-center gap-2 rounded-xl bg-[#178a53] px-4 text-[12px] text-white shadow-sm hover:bg-[#117847]" data-new-visual-report="true"><Plus className="h-4 w-4" />新建报表</button>
    </div>
    {error && <div className="mb-4 rounded-lg border border-[#ffd0d0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#c84034]" role="alert">{error}</div>}
    {loading && <div className="mb-4 rounded-xl border border-dashed border-[#dfe7e2] bg-white px-5 py-4 text-center text-[11px] text-[#9ba29e]" role="status" data-visual-report-list-loading="true">正在读取已有报表，新建报表可立即使用…</div>}
    {showCollections && (searching ? (
      <ReportCollection title="搜索结果" subtitle={`找到 ${searchResults.length} 份报表`} icon={Search} reports={searchResults} onOpen={onOpen} emptyText="没有找到匹配的可视化报表" dataKey="search" />
    ) : (
      <div className="grid gap-5 lg:grid-cols-2">
        <ReportCollection title="最近创建" subtitle="按最近编辑时间排列" icon={Clock3} reports={recentReports} onOpen={onOpen} emptyText="还没有创建过可视化报表" dataKey="recent" />
        <ReportCollection title="推荐使用" subtitle="优先推荐内容完整且常用的报表" icon={Sparkles} reports={recommendedReports} onOpen={onOpen} emptyText="有图表内容后会出现在推荐列表" dataKey="recommended" />
      </div>
    ))}
  </div>;
}

function ReportCollection({ title, subtitle, icon: Icon, reports, onOpen, emptyText, dataKey }: {
  title: string;
  subtitle: string;
  icon: typeof Search;
  reports: VisualReport[];
  onOpen: (report: VisualReport, mode?: "browse" | "edit") => void;
  emptyText: string;
  dataKey: string;
}) {
  return <section className="rounded-xl border border-[#edf1ee] bg-white p-4" data-visual-report-collection={dataKey}>
    <div className="mb-3 flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#edf7f0] text-[#178a53]"><Icon className="h-4 w-4" /></span>
      <div><h3 className="text-[13px] text-[#1d1d1f]">{title}</h3><p className="mt-0.5 text-[10px] text-[#9ba19e]">{subtitle}</p></div>
    </div>
    <div className="space-y-2">
      {reports.map((item) => <div key={item.id} className="group flex items-center gap-3 rounded-lg border border-[#edf0ee] bg-[#fafcfb] px-3 py-3 transition-colors hover:border-[#bcdcc8] hover:bg-[#f6fbf8]" data-visual-report-entry={item.id}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[#deebe3] bg-white text-[#4f8a67]"><BarChart3 className="h-4 w-4" /></span>
        <button type="button" onClick={() => onOpen(item, "browse")} className="min-w-0 flex-1 text-left" aria-label={`预览报表${item.title}`}>
          <span className="block truncate text-[12px] text-[#1d1d1f]">{item.title}</span>
          <span className="mt-1 block text-[9px] text-[#9aa19d]">{item.cards.length} 个图表 · {formatReportTime(item.updatedAt)}</span>
        </button>
        <button type="button" onClick={() => onOpen(item, "edit")} className="shrink-0 rounded-lg border border-[#dce8e0] bg-white px-2.5 py-1.5 text-[10px] text-[#407a59] hover:border-[#a9ceb7] hover:bg-[#eef8f2]">继续编辑</button>
      </div>)}
      {!reports.length && <div className="rounded-lg border border-dashed border-[#e0e5e2] px-3 py-12 text-center text-[11px] text-[#9ba19e]">{emptyText}</div>}
    </div>
  </section>;
}

function VisualChartModal({ rawTables, topicTables, tenantId, userId, reportId, drafts, draftRevision, onDraftChange, onRestore, onCancel, onSave }: {
  rawTables: RawTableAsset[];
  topicTables: TopicTableAsset[];
  tenantId: string;
  userId: string;
  reportId: string;
  drafts: Record<string, VisualChartDraft>;
  draftRevision: number;
  onDraftChange: (key: string, patch: Partial<VisualChartDraft>) => void;
  onRestore: () => void;
  onCancel: () => void;
  onSave: (card: VisualReportCard) => void;
}) {
  const loadSequenceRef = useRef(0);
  const [tab, setTab] = useState<"raw" | "topic">("raw");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<VisualReportDataset | null>(null);
  const [rows, setRows] = useState<AnalysisRow[]>([]);
  const [type, setType] = useState<VisualizationType>("table");
  const [config, setConfig] = useState<VisualizationCardConfig>(emptyConfig);
  const [loadingRows, setLoadingRows] = useState(false);
  const [rowError, setRowError] = useState("");
  const datasets = (tab === "raw" ? rawTables : topicTables)
    .filter((item) => datasetName(item).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));

  const chooseDataset = async (dataset: VisualReportDataset) => {
    const loadSequence = ++loadSequenceRef.current;
    const draft = drafts[visualDatasetDraftKey(dataset)];
    setSelected(dataset);
    setType(draft?.type || "table");
    setConfig(draft?.config || emptyConfig);
    setRows([]);
    setRowError("");
    setLoadingRows(false);
    if ("tableNameEn" in dataset) {
      const nextRows = rowsFromRawVisualDataset(dataset);
      if (loadSequence !== loadSequenceRef.current) return;
      setRows(nextRows);
      if (!nextRows.length) setRowError("该数据集当前没有可用预览行，不能创建图表。" );
      return;
    }
    if (isPageDataDataset(dataset)) {
      setLoadingRows(true);
      try {
        const snapshot = await fetchPageDataRows({ tenantId, userId, pageDataId: dataset.id, pageCode: "visual_report" });
        const nextRows = rowsFromPageVisualDataset(dataset, snapshot);
        if (loadSequence !== loadSequenceRef.current) return;
        setRows(nextRows);
        if (!nextRows.length) setRowError("该多机构页面数据当前没有可展示行。" );
      } catch (reason) {
        if (loadSequence !== loadSequenceRef.current) return;
        setRowError(apiErrorMessage(reason, "多机构页面数据读取失败。"));
      } finally {
        if (loadSequence === loadSequenceRef.current) setLoadingRows(false);
      }
      return;
    }
    setLoadingRows(true);
    try {
      const snapshot = await fetchTopicData({ tenantId, userId, referenceType: "topic", referenceId: dataset.id });
      const nextRows = rowsFromTopicVisualDataset(dataset, snapshot);
      if (loadSequence !== loadSequenceRef.current) return;
      setRows(nextRows);
      if (!nextRows.length) setRowError("该主题数据集当前没有可展示行。" );
    } catch (reason) {
      if (loadSequence !== loadSequenceRef.current) return;
      setRowError(apiErrorMessage(reason, "主题数据集读取失败。"));
    } finally {
      if (loadSequence === loadSequenceRef.current) setLoadingRows(false);
    }
  };

  const switchTab = (nextTab: "raw" | "topic") => {
    loadSequenceRef.current += 1;
    setTab(nextTab);
    setSelected(null);
    setRows([]);
    setRowError("");
    setLoadingRows(false);
  };

  const restoreDrafts = () => {
    loadSequenceRef.current += 1;
    onRestore();
    setTab("raw");
    setSearch("");
    setSelected(null);
    setRows([]);
    setType("table");
    setConfig(emptyConfig);
    setRowError("");
    setLoadingRows(false);
  };

  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/25 px-4" data-visual-report-modal="true">
    <div className="flex h-[min(88vh,900px)] w-full max-w-[1180px] flex-col overflow-hidden rounded-xl border border-[#dfe5e1] bg-white shadow-2xl shadow-black/20">
      <div className="flex shrink-0 items-center justify-between border-b border-[#eef1ef] px-5 py-4">
        <div><h3 className="text-[14px] text-[#1d1d1f]">新增可视化图表</h3><p className="mt-1 text-[10px] text-[#949b97]">先选择当前机构有权限的数据集，再通过标准图表控件选择样式、指标和维度。</p></div>
        <button type="button" onClick={onCancel} className="rounded-lg p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label="关闭新增图表弹窗"><X className="h-4 w-4" /></button>
      </div>
      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,0.8fr)_minmax(0,1.2fr)] overflow-hidden lg:grid-cols-[300px_minmax(0,1fr)] lg:grid-rows-1">
        <div className="flex min-h-0 flex-col border-b border-[#eef1ef] p-4 lg:border-b-0 lg:border-r">
          <div className="mb-3 flex rounded-lg bg-[#f2f5f3] p-0.5" data-visual-report-dataset-tabs="true">
            <button type="button" onClick={() => switchTab("raw")} className={`h-8 flex-1 rounded-md text-[11px] ${tab === "raw" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#7b827e]"}`}>原始表 {rawTables.length}</button>
            <button type="button" onClick={() => switchTab("topic")} className={`h-8 flex-1 rounded-md text-[11px] ${tab === "topic" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#7b827e]"}`}>主题表 {topicTables.length}</button>
          </div>
          <div className="relative mb-3"><Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-[#a1a7a3]" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索数据集" className="h-9 w-full rounded-lg border border-[#e1e6e3] pl-8 pr-3 text-[11px] outline-none focus:border-[#a9cdb5]" /></div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
            {datasets.map((dataset) => <button key={dataset.id} type="button" onClick={() => void chooseDataset(dataset)} className={`flex w-full items-start gap-2 rounded-lg px-3 py-2.5 text-left ${selected?.id === dataset.id ? "bg-[#edf7f0] text-[#178a53]" : "text-[#3a3a3c] hover:bg-[#f7f9f8]"}`} data-visual-report-dataset={dataset.id}>
              <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${selected?.id === dataset.id ? "border-[#178a53] bg-[#178a53] text-white" : "border-[#ccd3cf]"}`}>{selected?.id === dataset.id && <Check className="h-3 w-3" />}</span>
              <span className="min-w-0"><span className="block truncate text-[11px]">{datasetName(dataset)}</span><span className="mt-0.5 block truncate text-[9px] text-[#9ba29e]">{datasetCode(dataset)}</span></span>
            </button>)}
            {!datasets.length && <div className="px-3 py-8 text-center text-[11px] text-[#a1a7a3]">当前分类没有可用数据集</div>}
          </div>
        </div>
        <div className="min-h-0 overflow-hidden bg-[#fafcfb] p-4">
          {!selected ? <div className="flex h-full items-center justify-center text-[11px] text-[#a1a7a3]">请从左侧选择数据集</div> : loadingRows ? <div className="flex h-full items-center justify-center text-[11px] text-[#8d9791]">正在读取数据集…</div> : rowError ? <div className="flex h-full items-center justify-center text-[11px] text-[#c06c31]">{rowError}</div> : <AnalysisVisualCard id="visual-report-preview" stateKey={`visual-report-preview:${reportId}:${draftRevision}:${visualDatasetDraftKey(selected)}`} title={datasetName(selected)} type={type} rows={rows} initialConfig={config} fillHeight showFollowUp={false} onFollowUp={() => undefined} onComment={() => undefined} onTypeChange={(nextType) => { setType(nextType); onDraftChange(visualDatasetDraftKey(selected), { type: nextType }); }} onConfigChange={(nextConfig) => { setConfig(nextConfig); onDraftChange(visualDatasetDraftKey(selected), { config: nextConfig }); }} />}
        </div>
      </div>
      <div className="relative z-10 flex shrink-0 items-center justify-end gap-2 border-t border-[#eef1ef] bg-white px-5 py-3">
        <button type="button" onClick={onCancel} className="h-8 rounded-lg border border-[#e1e5e2] bg-white px-4 text-[11px] text-[#636b67] hover:bg-[#f6f8f7]">取消</button>
        <button type="button" onClick={restoreDrafts} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#e1e5e2] bg-white px-4 text-[11px] text-[#636b67] hover:bg-[#f6f8f7]" data-visual-report-restore="true"><RotateCcw className="h-3.5 w-3.5" />恢复</button>
        <button type="button" disabled={!selected || !rows.length || loadingRows || Boolean(rowError)} onClick={() => selected && onSave({ id: `visual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, title: datasetName(selected), type, dataset: visualReportDatasetReference(selected), config })} className="h-8 rounded-lg bg-[#1d1d1f] px-4 text-[11px] text-white hover:bg-[#2c2c2e] disabled:cursor-not-allowed disabled:opacity-40">保存</button>
      </div>
    </div>
  </div>;
}

function visualDatasetDraftKey(dataset: VisualReportDataset) {
  return `${"tableNameEn" in dataset ? "raw" : isPageDataDataset(dataset) ? "page_data" : "topic"}:${dataset.id}`;
}

function visualChartSessionKey(reportId: string, draftRevision: number, dataset: VisualReportDataset) {
  return `sda:visual-card:v2:${window.location.pathname}:visual-report-preview:${reportId}:${draftRevision}:${visualDatasetDraftKey(dataset)}`;
}

function DestinationButton({ label, icon: Icon, done, disabled, onClick }: { label: string; icon: typeof BookmarkPlus; done: boolean; disabled: boolean; onClick: () => void }) {
  return <button type="button" onClick={onClick} disabled={disabled} className={`inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-[12px] transition-colors disabled:cursor-wait disabled:opacity-60 ${done ? "border-[#cfe6d6] bg-[#eef8f2] text-[#178a53]" : "border-[#e5e5ea] bg-white text-[#3a3a3c] hover:bg-[#f2f2f7]"}`}><Icon className="h-3.5 w-3.5" />{done ? `已${label}` : label}</button>;
}

function newVisualReport(): VisualReport {
  const now = new Date().toISOString();
  return { id: `visual_report_${Date.now()}`, title: "可视化报表", cards: [], destinations: [], createdAt: now, updatedAt: now };
}

function upsertReportList(reports: VisualReport[], report: VisualReport) {
  return sortReports([report, ...reports.filter((item) => item.id !== report.id)]);
}

function sortReports(reports: VisualReport[]) {
  return [...reports].sort((left, right) => reportTime(right) - reportTime(left));
}

function reportTime(report: VisualReport) {
  const updated = Date.parse(report.updatedAt);
  if (Number.isFinite(updated)) return updated;
  const created = Date.parse(report.createdAt);
  return Number.isFinite(created) ? created : 0;
}

function recommendationScore(report: VisualReport) {
  return report.cards.length * 10 + report.destinations.length * 3;
}

function reportSearchText(report: VisualReport) {
  return [
    report.title,
    ...report.cards.flatMap((card) => [card.title, card.dataset.name, card.dataset.code]),
  ].join(" ").toLocaleLowerCase();
}

function formatReportTime(value: string) {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString("zh-CN", { hour12: false }) : value || "时间未记录";
}

function reportSignature(report: VisualReport) {
  return JSON.stringify({ id: report.id, title: report.title, cards: report.cards, destinations: report.destinations });
}

function datasetName(dataset: VisualReportDataset) {
  return "tableNameEn" in dataset ? dataset.tableNameCn || dataset.tableNameEn : isPageDataDataset(dataset) ? dataset.name || dataset.sourceTableName : dataset.name;
}

function datasetCode(dataset: VisualReportDataset) {
  return "tableNameEn" in dataset ? dataset.tableNameEn : isPageDataDataset(dataset) ? `page_data_${dataset.id}` : dataset.code;
}

function destinationLabel(destination: VisualReportDestination) {
  return ({ mine: "存我的", topic: "已沉淀主题", experience: "存经验", weekly: "存周报" } as const)[destination];
}

function destinationMessage(destination: VisualReportDestination) {
  if (destination === "mine") return "已存入“我的报表 > 可视化报表”。";
  if (destination === "topic") return "已提交为主题表候选；复核后进入主题数据资产。";
  if (destination === "experience") return "已提交为分析经验候选；复核后进入知识记忆。";
  return "已存入经营周报的可视化报表区域。";
}

async function saveAsTopic(report: VisualReport, rawTables: RawTableAsset[], topicTables: TopicTableAsset[], tenantId: string, userId: string) {
  const first = report.cards[0];
  if (first.dataset.kind === "page_data") return;
  const dataset = first.dataset.kind === "raw" ? rawTables.find((item) => item.id === first.dataset.id) : topicTables.find((item) => item.id === first.dataset.id);
  if (!dataset) throw new Error("当前报表引用的数据集已失效，不能存为主题。" );
  const fields = "tableNameEn" in dataset ? dataset.fields : Array.isArray(dataset.fields) ? dataset.fields : [];
  const code = `visual_${report.id}`.toLowerCase().replace(/[^a-z0-9_]+/g, "_").slice(0, 120);
  await saveDataAssetItem({ tenantId, userId, itemType: "topic_table", item: {
    id: `topic_${report.id}`,
    name: report.title,
    code,
    description: `来自可视化报表“${report.title}”的数据集引用与图表配置。`,
    sql: visualReportTopicSql(dataset),
    fields,
    fieldExplanations: "字段沿用当前授权数据集；需在数据资产复核中确认。",
    applicableScene: "可视化报表, 经营周报",
    relatedIntent: "可视化报表沉淀",
    relatedExperience: "",
    quickDisplay: false,
    reportReference: report.id,
    source: "可视化报表页面",
    updatedAt: new Date().toLocaleString("zh-CN", { hour12: false }),
  } });
}

function visualReportTopicSql(dataset: VisualReportDataset) {
  if ("tableNameEn" in dataset) {
    return `SELECT * FROM ${dataset.tableNameEn} WHERE :tenant_id IS NOT NULL`;
  }
  if (isPageDataDataset(dataset)) {
    throw new Error("多机构页面数据保留页面数据与表关系版本身份，不转换为主题表。" );
  }
  const sql = String(dataset.sql || "").trim().replace(/;+\s*$/, "");
  if (/:tenant_id\b|\btenant_id\s*=\s*\?/i.test(sql)) return sql;
  return `SELECT * FROM (${sql}) AS visual_report_source WHERE :tenant_id IS NOT NULL`;
}

async function saveAsExperience(report: VisualReport, institution: string, tenantId: string, userId: string) {
  await saveDataAssetItem({ tenantId, userId, itemType: "analysis_experience", item: {
    id: `exp_${report.id}`,
    name: report.title,
    relatedTopic: report.cards.map((card) => card.dataset.code).join(", "),
    relatedIntent: "可视化报表沉淀",
    steps: "选择授权数据集，配置标准图表样式、指标和维度，并在报表画布组合展示。",
    metrics: report.cards.flatMap((card) => card.config.metricFields).join(", "),
    rules: "只引用当前租户授权数据集；数据集或 Schema 失效时停止展示。",
    commonConclusions: `复用可视化报表“${report.title}”的 ${report.cards.length} 个图表配置。`,
    riskTips: "可视化配置不等于数据结论，使用前需重新读取当前数据。",
    summaryTemplate: "报表目标 / 图表清单 / 指标 / 维度 / 数据边界",
    institutionScope: institution,
    enabled: true,
    sourceVersionId: `visual-report:${report.id}`,
    evidence: `visual_report:${report.id}`,
    updatedAt: new Date().toLocaleString("zh-CN", { hour12: false }),
  } });
}
