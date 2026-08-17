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
import { AlertTriangle, Building2, ChevronDown, CreditCard, Landmark, Sparkles, Users } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { runApplicationAction } from "../services/applicationApi";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";
import { updateAnalysisWorkspacePageContext } from "./analysis-workspace/AnalysisWorkspaceRail";

type ProductView = "consumer" | "business";
const pieColors = ["#1d1d1f", "#3a3a3c", "#636366", "#8e8e93", "#aeaeb2", "#c7c7cc"];

export function CustomerInsight() {
  const { tenantId, userId } = usePlatformContext();
  const [productView, setProductView] = useState<ProductView>("consumer");
  const [selectedBank, setSelectedBank] = useState("全部分行");
  const [selectedSegment, setSelectedSegment] = useState(0);
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [knownBanks, setKnownBanks] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOperatingSnapshot({
      tenantId,
      userId,
      view: "customer_insight",
      filters: selectedBank === "全部分行" ? {} : { branch_name: selectedBank },
    })
      .then((result) => {
        if (cancelled) return;
        setSnapshot(result);
        setNotice("");
        const branchRows = result.datasets.customer_branches?.rows || [];
        setKnownBanks((current) => Array.from(new Set([...current, ...branchRows.map((row) => String(row.branch_name || "")).filter(Boolean)])).sort());
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
  }, [selectedBank, tenantId, userId]);

  const model = useMemo(() => buildCustomerModel(snapshot, productView), [productView, snapshot]);
  const activeSegment = model.segments[Math.min(selectedSegment, Math.max(0, model.segments.length - 1))];

  useEffect(() => {
    if (!snapshot) return;
    updateAnalysisWorkspacePageContext("customers", {
      route: "customers",
      filters: { branch_name: selectedBank === "全部分行" ? "" : selectedBank, product_line: productView === "consumer" ? "消费贷" : "经营贷", customer_segment: activeSegment?.name || "" },
      dataset_snapshot: snapshotDatasetSnapshot(snapshot),
      evidence_refs: snapshotEvidenceRefs(snapshot),
      visualization: { product_view: productView, selected_segment: activeSegment || null, segment_count: model.segments.length },
      analysis_plan_hint: {
        dataset_id: "customer_operation_mart",
        metrics: ["conversion_rate", "active_customer_count"],
        dimensions: ["customer_segment", "product_line", "branch_name", "month"],
        chart_types: ["column", "line", "table"],
        analysis_angles: ["比较客群规模与转化表现", "解释当前机构和客群筛选下的差异边界"],
      },
    });
  }, [activeSegment, model.segments.length, productView, selectedBank, snapshot]);
  const runCustomerInsightAction = (action: string, payload: Record<string, unknown> = {}) =>
    runApplicationAction({ tenantId, userId, moduleKey: "customer_insight", action, payload }).catch(() => undefined);

  if (loading && !snapshot) return <CustomerState message="正在读取受治理客群数据…" />;
  if (!model.hasData) return <CustomerState message={notice || "当前租户没有已授权的客群主题数据，页面不会展示内置画像或虚构流失客户。"} />;

  return (
    <div className="p-7">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">客群分析</h2>
          <p className="text-[13px] text-[#aeaeb2] mt-1">消费贷个人客群 vs 经营贷企业客群 · 分行客群对比</p>
        </div>
        <div className="relative">
          <select
            value={selectedBank}
            onChange={(event) => {
              setSelectedBank(event.target.value);
              setSelectedSegment(0);
              void runCustomerInsightAction("select_bank", { selectedBank: event.target.value, productView });
            }}
            className="appearance-none pl-8 pr-7 py-[6px] bg-white border border-[#e5e5ea] rounded-lg text-[12px] text-[#636366] focus:outline-none cursor-pointer"
          >
            <option>全部分行</option>
            {knownBanks.map((bank) => <option key={bank}>{bank}</option>)}
          </select>
          <Building2 className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#c7c7cc]" />
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[#c7c7cc] pointer-events-none" />
        </div>
      </div>

      {(notice || !snapshot?.publishable) && (
        <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">
          {notice || `当前数据模式：${snapshot?.data_modes.join("、") || "未知"}；该快照不可用于正式报告发布。`}
        </div>
      )}

      <div className="flex gap-px bg-[#f2f2f7] rounded-lg p-0.5 w-fit mb-6">
        {([
          { key: "consumer", label: "消费贷客群", icon: CreditCard },
          { key: "business", label: "经营贷客群", icon: Landmark },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setProductView(tab.key);
              setSelectedSegment(0);
              void runCustomerInsightAction("select_product_view", { productView: tab.key, selectedBank });
            }}
            className={`px-4 py-[6px] rounded-md text-[13px] transition-all flex items-center gap-1.5 ${productView === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e]"}`}
          >
            <tab.icon className="w-3.5 h-3.5" /> {tab.label}
          </button>
        ))}
      </div>

      <div className={`grid gap-3 mb-6 ${model.segments.length <= 5 ? "grid-cols-5" : "grid-cols-6"}`}>
        {model.segments.map((segment, index) => (
          <button
            key={segment.name}
            onClick={() => {
              setSelectedSegment(index);
              void runCustomerInsightAction("select_segment", { productView, selectedBank, selectedSegment: index, segment: segment.name });
            }}
            className={`text-left bg-white p-4 rounded-xl border cursor-pointer transition-all ${selectedSegment === index ? "border-[#3a3a3c]" : "border-[#f0f0f2] hover:border-[#d1d1d6]"}`}
          >
            <div className="text-[12px] text-[#1d1d1f] mb-1">{segment.name}</div>
            <div className="text-[18px] text-[#1d1d1f] tracking-tight">{segment.count.toLocaleString("zh-CN")}</div>
            <div className="text-[10px] text-[#aeaeb2] mt-1">占比 {segment.pct.toFixed(1)}%</div>
            <div className="mt-2 text-[10px] text-[#8a8a8e]">转化率 {formatPercent(segment.conversionRate)}</div>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-5 mb-6">
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <h3 className="text-[13px] text-[#1d1d1f] mb-3">客群规模分布</h3>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={model.segments.map((item) => ({ name: item.name, value: item.count }))} dataKey="value" nameKey="name" innerRadius={52} outerRadius={82} paddingAngle={2}>
                {model.segments.map((item, index) => <Cell key={item.name} fill={pieColors[index % pieColors.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <h3 className="text-[13px] text-[#1d1d1f] mb-3">客群转化率</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={model.segments} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" horizontal={false} />
              <XAxis type="number" unit="%" tick={{ fontSize: 9, fill: "#c7c7cc" }} stroke="transparent" />
              <YAxis type="category" dataKey="name" width={78} tick={{ fontSize: 9, fill: "#8a8a8e" }} stroke="transparent" />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} />
              <Bar dataKey="conversionPct" fill="#636366" radius={[0, 4, 4, 0]} barSize={16} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center gap-2 mb-3"><Sparkles className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">证据型客群摘要</h3></div>
          <div className="space-y-3 text-[11px] leading-[1.7] text-[#8a8a8e]">
            <p>• 最大客群：{model.largest?.name || "—"}，活跃客户 {model.largest?.count.toLocaleString("zh-CN") || "—"}。</p>
            <p>• 最高转化客群：{model.bestConversion?.name || "—"}，转化率 {formatPercent(model.bestConversion?.conversionRate)}。</p>
            <p>• 当前选中：{activeSegment?.name || "—"}；所有数字均引用语义查询 evidence_id。</p>
          </div>
          <div className="mt-3 text-[9px] break-all text-[#c7c7cc]">{model.evidenceId || "无证据 ID"}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-5 mb-6">
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center gap-2 mb-3"><Users className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">选中客群月度趋势</h3></div>
          {activeSegment && model.trend.filter((row) => row.customer_segment === activeSegment.name).length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={model.trend.filter((row) => row.customer_segment === activeSegment.name)}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 9, fill: "#c7c7cc" }} stroke="transparent" />
                <YAxis tick={{ fontSize: 9, fill: "#c7c7cc" }} stroke="transparent" />
                <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} />
                <Bar dataKey="active_customer_count" name="活跃客户" fill="#636366" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <Unavailable text="当前客群没有月度趋势数据。" />}
        </div>

        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center gap-2 mb-3"><AlertTriangle className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">流失风险与个人画像</h3></div>
          <Unavailable text="现有主题表没有客户级行为、收入、行业、NPL、抵押物或流失标签；为避免虚构姓名与风险原因，本区域不展示推断结果。" />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
        <div className="flex items-center gap-2 mb-4"><Building2 className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">各分行客群规模与转化</h3></div>
        <table className="w-full text-[12px]">
          <thead><tr className="text-[11px] text-[#aeaeb2] border-b border-[#f0f0f2]"><th className="text-left py-2 px-2">分行</th><th className="text-left px-2">产品</th><th className="text-right px-2">活跃客户</th><th className="text-right px-2">转化率</th></tr></thead>
          <tbody>
            {model.branches.map((row) => (
              <tr key={`${row.branch_name}-${row.product_line}`} className="border-b border-[#f8f8f8] hover:bg-[#fafbfc]"><td className="py-2.5 px-2 text-[#1d1d1f]">{String(row.branch_name || "—")}</td><td className="px-2 text-[#636366]">{String(row.product_line || "—")}</td><td className="text-right px-2 text-[#1d1d1f]">{Number(row.active_customer_count || 0).toLocaleString("zh-CN")}</td><td className="text-right px-2 text-[#636366]">{formatPercent(Number(row.conversion_rate))}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function buildCustomerModel(snapshot: OperatingSnapshot | null, productView: ProductView) {
  const product = productView === "consumer" ? "消费贷" : "经营贷";
  const segmentDataset = snapshot?.datasets.customer_segments;
  const rows = segmentDataset?.status === "ready" ? segmentDataset.rows.filter((row) => row.product_line === product) : [];
  const total = rows.reduce((sum, row) => sum + Number(row.active_customer_count || 0), 0);
  const segments = rows.map((row) => {
    const count = Number(row.active_customer_count || 0);
    const conversionRate = Number(row.conversion_rate);
    return {
      name: String(row.customer_segment || "未命名客群"),
      count,
      pct: total > 0 ? (count / total) * 100 : 0,
      conversionRate: Number.isFinite(conversionRate) ? conversionRate : undefined,
      conversionPct: Number.isFinite(conversionRate) ? conversionRate * 100 : 0,
    };
  }).sort((left, right) => right.count - left.count);
  const trendDataset = snapshot?.datasets.customer_segment_trend;
  const trend = trendDataset?.status === "ready" ? trendDataset.rows.filter((row) => row.product_line === product) : [];
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

function CustomerState({ message }: { message: string }) {
  return <div className="p-7"><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">客群分析</h2><p className="text-[13px] text-[#aeaeb2] mt-1">消费贷个人客群 vs 经营贷企业客群 · 分行客群对比</p><div className="mt-6 rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]">{message}</div></div>;
}

function snapshotEvidenceRefs(snapshot: OperatingSnapshot) { return Object.entries(snapshot.datasets).flatMap(([key, dataset]) => dataset.evidence.evidence_id ? [{ id: dataset.evidence.evidence_id, type: "operating_snapshot", label: key }] : []); }
function snapshotDatasetSnapshot(snapshot: OperatingSnapshot) { return { id: snapshot.view, version: snapshot.generated_at, generatedAt: snapshot.generated_at }; }

function Unavailable({ text }: { text: string }) {
  return <div className="flex min-h-[160px] items-center justify-center rounded-lg bg-[#fafbfc] px-6 text-center text-[11px] leading-6 text-[#aeaeb2]">{text}</div>;
}

function formatPercent(value?: number) {
  return value === undefined || !Number.isFinite(value) ? "—" : `${(value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
}
