import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertTriangle, Building2, Sparkles, Users } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { runApplicationAction } from "../services/applicationApi";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";
import { updateAnalysisWorkspacePageContext } from "./analysis-workspace/AnalysisWorkspaceRail";
import { useStickyNote } from "./notes/useStickyNote";
import { PAGE_DATA_PAGE_GUTTER_CLASS } from "./page-data/PageDataComposer";
import {
  StandardAnalysisPageGrid,
  StandardAnalysisPageHeader,
  StandardAnalysisPageStickyNote,
  useStandardAnalysisPageLayout,
  type StandardAnalysisVisualDefinition,
} from "./page-data/StandardAnalysisPage";
import { ReportPageStyleButton } from "./report-style/reportPageStyles";

const pieColors = ["var(--sda-report-chart-1, #1d1d1f)", "var(--sda-report-chart-2, #3a3a3c)", "var(--sda-report-chart-3, #636366)", "var(--sda-report-chart-4, #8e8e93)"];
const CUSTOMER_VISUAL_DEFINITIONS: StandardAnalysisVisualDefinition[] = [
  { id: "segments", label: "客群卡片", defaultSpan: 12, defaultHeight: 220 },
  { id: "distribution", label: "客群规模分布", defaultSpan: 4, defaultHeight: 340 },
  { id: "conversion", label: "客群转化率", defaultSpan: 4, defaultHeight: 340 },
  { id: "summary", label: "证据型客群摘要", defaultSpan: 4, defaultHeight: 340 },
  { id: "trend", label: "选中客群月度趋势", defaultSpan: 6, defaultHeight: 320 },
  { id: "risk", label: "流失风险与个人画像", defaultSpan: 6, defaultHeight: 320 },
  { id: "branches", label: "各分行客群规模与转化", defaultSpan: 12, defaultHeight: 380 },
];

export function CustomerInsight() {
  const { tenantId, userId, isSuperAdmin } = usePlatformContext();
  const [selectedSegment, setSelectedSegment] = useState(0);
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const stickyNote = useStickyNote("customer_insight", "customer_insight");
  const pageLayout = useStandardAnalysisPageLayout({ tenantId, userId, moduleKey: "customer_insight", definitions: CUSTOMER_VISUAL_DEFINITIONS });

  useEffect(() => {
    if (!isSuperAdmin) pageLayout.editController.setMode("browse");
  }, [isSuperAdmin, pageLayout.editController.setMode]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOperatingSnapshot({
      tenantId,
      userId,
      view: "customer_insight",
    })
      .then((result) => {
        if (cancelled) return;
        setSnapshot(result);
        setNotice("");
      })
      .catch((error) => {
        if (!cancelled) {
          setSnapshot(null);
          setNotice(apiErrorMessage(error, "客群数据加载失败。"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const model = useMemo(() => buildCustomerModel(snapshot), [snapshot]);
  const activeSegment = model.segments[Math.min(selectedSegment, Math.max(0, model.segments.length - 1))];
  const activeTrend = activeSegment
    ? model.trend.filter((row) => row.customer_segment === activeSegment.segmentName && row.product_line === activeSegment.productLine)
    : [];

  useEffect(() => {
    if (!snapshot) return;
    updateAnalysisWorkspacePageContext("customers", {
      route: "customers",
      filters: { branch_name: "", product_line: "", customer_segment: activeSegment?.segmentName || "" },
      dataset_snapshot: snapshotDatasetSnapshot(snapshot),
      evidence_refs: snapshotEvidenceRefs(snapshot),
      visualization: { selected_segment: activeSegment || null, segment_count: model.segments.length },
      analysis_plan_hint: {
        dataset_id: "customer_operation_mart",
        metrics: ["conversion_rate", "active_customer_count"],
        dimensions: ["customer_segment", "product_line", "branch_name", "month"],
        chart_types: ["column", "line", "table"],
        analysis_angles: ["比较客群规模与转化表现", "解释全机构、全产品客群范围内的差异边界"],
      },
    });
  }, [activeSegment, model.segments.length, snapshot]);
  const runCustomerInsightAction = (action: string, payload: Record<string, unknown> = {}) =>
    runApplicationAction({ tenantId, userId, moduleKey: "customer_insight", action, payload }).catch(() => undefined);

  const modules = model.hasData ? [
    {
      id: "segments",
      content: <div className={`grid h-full content-start gap-3 overflow-y-auto rounded-xl ${model.segments.length <= 5 ? "grid-cols-5" : "grid-cols-6"}`}>
        {model.segments.map((segment, index) => (
          <button
            key={segment.name}
            type="button"
            onClick={() => {
              setSelectedSegment(index);
              void runCustomerInsightAction("select_segment", { selectedSegment: index, segment: segment.segmentName, productLine: segment.productLine });
            }}
            className={`text-left bg-white p-4 rounded-xl border cursor-pointer transition-all ${selectedSegment === index ? "border-[#3a3a3c]" : "border-[#f0f0f2] hover:border-[#d1d1d6]"}`}
          >
            <div className="text-[12px] text-[#1d1d1f] mb-1">{segment.name}</div>
            <div className="text-[18px] text-[#1d1d1f] tracking-tight">{segment.count.toLocaleString("zh-CN")}</div>
            <div className="text-[10px] text-[#aeaeb2] mt-1">占比 {segment.pct.toFixed(1)}%</div>
            <div className="mt-2 text-[10px] text-[#8a8a8e]">转化率 {formatPercent(segment.conversionRate)}</div>
          </button>
        ))}
      </div>,
    },
    {
      id: "distribution",
      content: <div className="flex h-full min-h-0 flex-col rounded-xl border border-[#f0f0f2] bg-white p-5"><h3 className="mb-3 shrink-0 text-[13px] text-[#1d1d1f]">客群规模分布</h3><div className="min-h-0 flex-1"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={model.segments.map((item) => ({ name: item.name, value: item.count }))} dataKey="value" nameKey="name" innerRadius="38%" outerRadius="68%" paddingAngle={2}>{model.segments.map((item, index) => <Cell key={item.name} fill={pieColors[index % pieColors.length]} />)}</Pie><Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} /></PieChart></ResponsiveContainer></div></div>,
    },
    {
      id: "conversion",
      content: <div className="flex h-full min-h-0 flex-col rounded-xl border border-[#f0f0f2] bg-white p-5"><h3 className="mb-3 shrink-0 text-[13px] text-[#1d1d1f]">客群转化率</h3><div className="min-h-0 flex-1"><ResponsiveContainer width="100%" height="100%"><BarChart data={model.segments} layout="vertical"><CartesianGrid strokeDasharray="3 3" stroke="var(--sda-report-chart-grid, #f5f5f5)" horizontal={false} /><XAxis type="number" unit="%" tick={{ fontSize: 9, fill: "var(--sda-report-chart-muted, #c7c7cc)" }} stroke="transparent" /><YAxis type="category" dataKey="name" width={78} tick={{ fontSize: 9, fill: "var(--sda-report-chart-muted, #8a8a8e)" }} stroke="transparent" /><Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid var(--sda-report-border, #f0f0f2)" }} /><Bar dataKey="conversionPct" fill="var(--sda-report-chart-1, #636366)" radius={[0, 4, 4, 0]} barSize={16} /></BarChart></ResponsiveContainer></div></div>,
    },
    {
      id: "summary",
      content: <div className="h-full overflow-y-auto rounded-xl border border-[#f0f0f2] bg-white p-5"><div className="flex items-center gap-2 mb-3"><Sparkles className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">证据型客群摘要</h3></div><div className="space-y-3 text-[11px] leading-[1.7] text-[#8a8a8e]"><p>• 最大客群：{model.largest?.name || "—"}，活跃客户 {model.largest?.count.toLocaleString("zh-CN") || "—"}。</p><p>• 最高转化客群：{model.bestConversion?.name || "—"}，转化率 {formatPercent(model.bestConversion?.conversionRate)}。</p><p>• 当前选中：{activeSegment?.name || "—"}；所有数字均引用语义查询 evidence_id。</p></div><div className="mt-3 break-all text-[9px] text-[#c7c7cc]">{model.evidenceId || "无证据 ID"}</div></div>,
    },
    {
      id: "trend",
      content: <div className="flex h-full min-h-0 flex-col rounded-xl border border-[#f0f0f2] bg-white p-5"><div className="mb-3 flex shrink-0 items-center gap-2"><Users className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">选中客群月度趋势</h3></div><div className="min-h-0 flex-1">{activeTrend.length > 0 ? <ResponsiveContainer width="100%" height="100%"><BarChart data={activeTrend}><CartesianGrid strokeDasharray="3 3" stroke="var(--sda-report-chart-grid, #f5f5f5)" vertical={false} /><XAxis dataKey="month" tick={{ fontSize: 9, fill: "var(--sda-report-chart-muted, #c7c7cc)" }} stroke="transparent" /><YAxis tick={{ fontSize: 9, fill: "var(--sda-report-chart-muted, #c7c7cc)" }} stroke="transparent" /><Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid var(--sda-report-border, #f0f0f2)" }} /><Bar dataKey="active_customer_count" name="活跃客户" fill="var(--sda-report-chart-1, #636366)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer> : <Unavailable text="当前客群没有月度趋势数据。" />}</div></div>,
    },
    {
      id: "risk",
      content: <div className="h-full overflow-y-auto rounded-xl border border-[#f0f0f2] bg-white p-5"><div className="flex items-center gap-2 mb-3"><AlertTriangle className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">流失风险与个人画像</h3></div><Unavailable text="现有主题表没有客户级行为、收入、行业、NPL、抵押物或流失标签；为避免虚构姓名与风险原因，本区域不展示推断结果。" /></div>,
    },
    {
      id: "branches",
      content: <div className="flex h-full min-h-0 flex-col rounded-xl border border-[#f0f0f2] bg-white p-5"><div className="mb-4 flex shrink-0 items-center gap-2"><Building2 className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">各分行客群规模与转化</h3></div><div className="min-h-0 flex-1 overflow-auto"><table className="w-full text-[12px]"><thead className="sticky top-0 bg-white"><tr className="text-[11px] text-[#aeaeb2] border-b border-[#f0f0f2]"><th className="text-left py-2 px-2">分行</th><th className="text-left px-2">产品</th><th className="text-right px-2">活跃客户</th><th className="text-right px-2">转化率</th></tr></thead><tbody>{model.branches.map((row) => <tr key={`${row.branch_name}-${row.product_line}`} className="border-b border-[#f8f8f8] hover:bg-[#fafbfc]"><td className="py-2.5 px-2 text-[#1d1d1f]">{String(row.branch_name || "—")}</td><td className="px-2 text-[#636366]">{String(row.product_line || "—")}</td><td className="text-right px-2 text-[#1d1d1f]">{Number(row.active_customer_count || 0).toLocaleString("zh-CN")}</td><td className="text-right px-2 text-[#636366]">{formatPercent(Number(row.conversion_rate))}</td></tr>)}</tbody></table></div></div>,
    },
  ] : [];

  return (
    <div className={PAGE_DATA_PAGE_GUTTER_CLASS} data-customer-insight-page="true">
      <StandardAnalysisPageHeader
        title="客群分析"
        description="消费贷个人客群 vs 经营贷企业客群 · 分行客群对比"
        stickyNote={stickyNote}
        editController={pageLayout.editController}
        canEditLayout={isSuperAdmin}
        headerDataAttribute="customer-insight"
        pageStyleControl={isSuperAdmin && pageLayout.mode === "edit" ? <ReportPageStyleButton styleId={pageLayout.pageStyleId} onSelect={pageLayout.applyPageStyle} /> : null}
      />
      <StandardAnalysisPageStickyNote stickyNote={stickyNote} />

      {(notice || pageLayout.notice) && (
        <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">
          {notice || pageLayout.notice}
        </div>
      )}
      {loading && !snapshot ? <CustomerState message="正在读取受治理客群数据…" embedded /> : !model.hasData ? <CustomerState message={notice || "当前租户没有已授权的客群主题数据，页面不会展示内置画像或虚构流失客户。"} embedded /> : <StandardAnalysisPageGrid moduleKey="customer_insight" definitions={CUSTOMER_VISUAL_DEFINITIONS} modules={modules} layout={pageLayout.layout} hiddenDefinitions={pageLayout.hiddenDefinitions} editable={isSuperAdmin && pageLayout.mode === "edit"} onHide={pageLayout.hide} onRestore={pageLayout.restore} onMove={pageLayout.move} pageStyleId={pageLayout.pageStyleId} onApplyPageStyle={pageLayout.applyPageStyle} />}
    </div>
  );
}

function buildCustomerModel(snapshot: OperatingSnapshot | null) {
  const segmentDataset = snapshot?.datasets.customer_segments;
  const rows = segmentDataset?.status === "ready" ? segmentDataset.rows : [];
  const total = rows.reduce((sum, row) => sum + Number(row.active_customer_count || 0), 0);
  const segments = rows.map((row) => {
    const count = Number(row.active_customer_count || 0);
    const conversionRate = Number(row.conversion_rate);
    const segmentName = String(row.customer_segment || "未命名客群");
    const productLine = String(row.product_line || "未分类产品");
    return {
      name: `${productLine} · ${segmentName}`,
      segmentName,
      productLine,
      count,
      pct: total > 0 ? (count / total) * 100 : 0,
      conversionRate: Number.isFinite(conversionRate) ? conversionRate : undefined,
      conversionPct: Number.isFinite(conversionRate) ? conversionRate * 100 : 0,
    };
  }).sort((left, right) => right.count - left.count);
  const trendDataset = snapshot?.datasets.customer_segment_trend;
  const trend = trendDataset?.status === "ready" ? trendDataset.rows : [];
  const branchDataset = snapshot?.datasets.customer_branches;
  const branches = branchDataset?.status === "ready" ? branchDataset.rows : [];
  return {
    hasData: segments.length > 0,
    segments,
    trend,
    branches,
    largest: segments[0],
    bestConversion: segments.slice().sort((left, right) => Number(right.conversionRate || 0) - Number(left.conversionRate || 0))[0],
    evidenceId: segmentDataset?.evidence.evidence_id,
  };
}

function CustomerState({ message, embedded = false }: { message: string; embedded?: boolean }) {
  return <div className={embedded ? "min-w-0" : PAGE_DATA_PAGE_GUTTER_CLASS}>{!embedded ? <><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">客群分析</h2><p className="text-[13px] text-[#aeaeb2] mt-1">消费贷个人客群 vs 经营贷企业客群 · 分行客群对比</p></> : null}<div className={`${embedded ? "mt-0" : "mt-6"} rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]`}>{message}</div></div>;
}

function snapshotEvidenceRefs(snapshot: OperatingSnapshot) { return Object.entries(snapshot.datasets).flatMap(([key, dataset]) => dataset.evidence.evidence_id ? [{ id: dataset.evidence.evidence_id, type: "operating_snapshot", label: key }] : []); }
function snapshotDatasetSnapshot(snapshot: OperatingSnapshot) { return { id: snapshot.view, version: snapshot.generated_at, generatedAt: snapshot.generated_at }; }

function Unavailable({ text }: { text: string }) {
  return <div className="flex min-h-[160px] items-center justify-center rounded-lg bg-[#fafbfc] px-6 text-center text-[11px] leading-6 text-[#aeaeb2]">{text}</div>;
}

function formatPercent(value?: number) {
  return value === undefined || !Number.isFinite(value) ? "—" : `${(value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
}
