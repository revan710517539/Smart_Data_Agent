import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Building2, ChevronDown, CreditCard, Download, Landmark, Play, RotateCcw, SlidersHorizontal, Sparkles } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { runApplicationAction } from "../services/applicationApi";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";
import { updateAnalysisWorkspacePageContext } from "./analysis-workspace/AnalysisWorkspaceRail";

type ProductView = "consumer" | "business";

export function BusinessSandbox() {
  const { tenantId, userId } = usePlatformContext();
  const [productView, setProductView] = useState<ProductView>("consumer");
  const [selectedBank, setSelectedBank] = useState("全部分行");
  const [knownBanks, setKnownBanks] = useState<string[]>([]);
  const [showSimulation, setShowSimulation] = useState(false);
  const [simParams, setSimParams] = useState({ rateAdjust: 0, creditLimit: 0, approvalRate: 0, pushRate: 0 });
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOperatingSnapshot({
      tenantId,
      userId,
      view: "dashboard",
      filters: selectedBank === "全部分行" ? {} : { branch_name: selectedBank },
    })
      .then((result) => {
        if (cancelled) return;
        setSnapshot(result);
        setNotice("");
        const rows = result.datasets.loan_operation?.rows || [];
        setKnownBanks((current) => Array.from(new Set([...current, ...rows.map((row) => String(row.branch_name || "")).filter(Boolean)])).sort());
      })
      .catch((error) => {
        if (!cancelled) {
          setSnapshot(null);
          setNotice(apiErrorMessage(error, "经营沙盘数据加载失败。"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedBank, tenantId, userId]);

  const model = useMemo(() => buildSandboxModel(snapshot, productView), [productView, snapshot]);

  useEffect(() => {
    if (!snapshot) return;
    updateAnalysisWorkspacePageContext("sandbox", {
      route: "sandbox",
      filters: { branch_name: selectedBank === "全部分行" ? "" : selectedBank, product_line: productView === "consumer" ? "消费贷" : "经营贷" },
      dataset_snapshot: snapshotDatasetSnapshot(snapshot),
      evidence_refs: snapshotEvidenceRefs(snapshot),
      visualization: { product_view: productView, simulation_parameters: simParams, simulation_executed: false, kpis: model.kpis, trend_points: model.trend.length },
      analysis_plan_hint: {
        dataset_id: "loan_operation_mart",
        metrics: ["loan_amount", "drawdown_rate"],
        dimensions: ["branch_name", "product_line", "month"],
        chart_types: ["line", "column", "table"],
        analysis_angles: ["分析当前筛选下的经营趋势", "说明沙盘参数尚未执行，不得把参数当成事实结果"],
      },
    });
  }, [model.kpis, model.trend.length, productView, selectedBank, simParams, snapshot]);

  const resetSimulation = async () => {
    setSimParams({ rateAdjust: 0, creditLimit: 0, approvalRate: 0, pushRate: 0 });
    await runApplicationAction({ tenantId, userId, moduleKey: "business_sandbox", action: "reset_simulation", payload: { productView, selectedBank } }).catch(() => undefined);
  };

  if (loading && !snapshot) return <SandboxState message="正在读取受治理经营数据…" />;
  if (!model.hasData) return <SandboxState message={notice || "当前租户没有可用于沙盘基线的经营事实，页面不会展示内置趋势和固定模拟结果。"} />;

  return (
    <div className="p-7">
      <div className="flex items-center justify-between mb-6">
        <div><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">经营沙盘</h2><p className="text-[13px] text-[#aeaeb2] mt-1">分产品线经营深度分析 · 策略推演与ROI模拟</p></div>
        <div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true">
          <div className="relative">
            <select value={selectedBank} onChange={(event) => setSelectedBank(event.target.value)} className="h-9 appearance-none rounded-lg border border-[#e5e5ea] bg-white pl-8 pr-7 text-[12px] text-[#3a3a3c] focus:outline-none cursor-pointer">
              <option>全部分行</option>{knownBanks.map((bank) => <option key={bank}>{bank}</option>)}
            </select>
            <Building2 className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#c7c7cc]" /><ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[#c7c7cc] pointer-events-none" />
          </div>
          <button onClick={() => setShowSimulation(!showSimulation)} className={`inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-[12px] transition-all ${showSimulation ? "bg-[#1d1d1f] text-white" : "border border-[#e5e5ea] bg-white text-[#3a3a3c] hover:bg-[#f2f2f7]"}`}><SlidersHorizontal className="w-3.5 h-3.5" /> 策略模拟</button>
          <button onClick={() => setNotice("沙盘导出需先形成可追溯模型运行 artifact；当前没有可导出的模拟产物。") } className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7]"><Download className="w-3.5 h-3.5" /> 导出</button>
        </div>
      </div>

      {(notice || !snapshot?.publishable) && <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">{notice || `当前数据模式：${snapshot?.data_modes.join("、") || "未知"}；基线不可用于正式策略决策。`}</div>}

      <div className="flex gap-px bg-[#f2f2f7] rounded-lg p-0.5 w-fit mb-6">
        {([{ key: "consumer", label: "消费贷经营", icon: CreditCard }, { key: "business", label: "经营贷经营", icon: Landmark }] as const).map((tab) => (
          <button key={tab.key} onClick={() => { setProductView(tab.key); void runApplicationAction({ tenantId, userId, moduleKey: "business_sandbox", action: "select_product_view", payload: { productView: tab.key } }).catch(() => undefined); }} className={`px-4 py-[6px] rounded-md text-[13px] transition-all flex items-center gap-1.5 ${productView === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e]"}`}><tab.icon className="w-3.5 h-3.5" /> {tab.label}</button>
        ))}
      </div>

      <div className="grid grid-cols-6 gap-3 mb-6">
        {model.kpis.map((kpi) => (
          <div key={kpi.label} className="bg-white p-4 rounded-xl border border-[#f0f0f2]"><div className="text-[11px] text-[#aeaeb2]">{kpi.label}</div><div className="text-[18px] text-[#1d1d1f] mt-1 tracking-tight">{kpi.value}</div><span className="text-[11px] text-[#636366] mt-0.5">{kpi.change}</span></div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 mb-6">
        <h3 className="text-[13px] text-[#1d1d1f] mb-4">{productView === "consumer" ? "消费贷" : "经营贷"}经营趋势</h3>
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={model.trend}>
            <defs><linearGradient id="gSandbox" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3a3a3c" stopOpacity={0.06} /><stop offset="100%" stopColor="#3a3a3c" stopOpacity={0.01} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" vertical={false} /><XAxis dataKey="month" tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" /><YAxis tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" /><YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" /><Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} /><Legend wrapperStyle={{ fontSize: 10 }} />
            <Area type="monotone" dataKey="放款" stroke="#3a3a3c" fill="url(#gSandbox)" strokeWidth={1.5} /><Area type="monotone" dataKey="M1" stroke="#c7c7cc" fill="none" strokeWidth={1} strokeDasharray="4 4" yAxisId="right" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-2 gap-5 mb-6">
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <h3 className="text-[13px] text-[#1d1d1f] mb-4">渠道获客成本与 ROI</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={model.channels}><CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" vertical={false} /><XAxis dataKey="channel" tick={{ fontSize: 9, fill: "#8a8a8e" }} stroke="transparent" /><YAxis tick={{ fontSize: 9, fill: "#c7c7cc" }} stroke="transparent" /><Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} /><Legend wrapperStyle={{ fontSize: 10 }} /><Bar dataKey="获客成本" fill="#636366" radius={[3, 3, 0, 0]} /><Bar dataKey="ROI" fill="#c7c7cc" radius={[3, 3, 0, 0]} /></BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center gap-2 mb-3"><Sparkles className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">基线证据说明</h3></div>
          <div className="text-[11px] leading-[1.8] text-[#8a8a8e]">当前页面只展示已执行语义查询中的放款、余额、动支、M1、活跃客户、转化、获客成本和 ROI。利率、审批、额度、目标、NPL 等未接入指标保持不可用，不用固定常数补齐。</div>
          <div className="mt-3 text-[9px] break-all text-[#c7c7cc]">{model.evidenceIds.join(" · ")}</div>
        </div>
      </div>

      {showSimulation && (
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center justify-between mb-4"><div><h3 className="text-[13px] text-[#1d1d1f]">策略参数模拟</h3><p className="text-[10px] text-[#aeaeb2] mt-1">需要经审批的模型版本、校准数据与置信区间后才能运行。</p></div><button onClick={() => void resetSimulation()} className="flex items-center gap-1 text-[11px] text-[#636366]"><RotateCcw className="w-3 h-3" /> 重置</button></div>
          <div className="grid grid-cols-4 gap-4 opacity-60">
            {Object.entries(simParams).map(([key, value]) => <label key={key} className="text-[11px] text-[#8a8a8e]">{parameterLabel(key)}<input type="range" min="-20" max="20" value={value} onChange={(event) => setSimParams((current) => ({ ...current, [key]: Number(event.target.value) }))} className="mt-2 w-full" /></label>)}
          </div>
          <button disabled title="未配置已审批的模型版本" className="mt-5 flex items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white opacity-40"><Play className="w-3.5 h-3.5" /> 运行模拟</button>
          <div className="mt-3 text-[11px] text-[#aeaeb2]">模拟已被服务端关闭：缺少模型版本、训练/校准数据、适用范围和评估报告。</div>
        </div>
      )}
    </div>
  );
}

function buildSandboxModel(snapshot: OperatingSnapshot | null, view: ProductView) {
  const product = view === "consumer" ? "消费贷" : "经营贷";
  const loanRows = readyRows(snapshot, "loan_product_trend").filter((row) => row.product_line === product).sort(byMonth);
  const riskRows = readyRows(snapshot, "risk_product_trend").filter((row) => row.product_line === product).sort(byMonth);
  const customerRows = readyRows(snapshot, "customer_product_trend").filter((row) => row.product_line === product).sort(byMonth);
  const channelRows = readyRows(snapshot, "channel_operation").filter((row) => row.product_line === product);
  const currentLoan = loanRows.at(-1); const priorLoan = loanRows.at(-2); const currentRisk = riskRows.at(-1); const priorRisk = riskRows.at(-2); const currentCustomer = customerRows.at(-1); const priorCustomer = customerRows.at(-2);
  const months = Array.from(new Set([...loanRows, ...riskRows].map((row) => String(row.month || "")))).filter(Boolean).sort();
  const trend = months.map((month) => ({ month, 放款: scaled(loanRows.find((row) => row.month === month)?.loan_amount, 1e8) || 0, M1: percent(riskRows.find((row) => row.month === month)?.m1_overdue_rate) || 0 }));
  const channels = channelRows.map((row) => ({ channel: String(row.channel || "未命名"), 获客成本: numeric(row.customer_acquisition_cost), ROI: numeric(row.roi) }));
  const kpis = [
    valueKpi("放款金额(亿)", scaled(currentLoan?.loan_amount, 1e8), scaled(priorLoan?.loan_amount, 1e8)),
    valueKpi("在贷余额(亿)", scaled(currentRisk?.loan_balance, 1e8), scaled(priorRisk?.loan_balance, 1e8)),
    valueKpi("活跃客户(万)", scaled(currentCustomer?.active_customer_count, 1e4), scaled(priorCustomer?.active_customer_count, 1e4)),
    rateKpi("动支率", percent(currentLoan?.drawdown_rate), percent(priorLoan?.drawdown_rate)),
    rateKpi("M1逾期率", percent(currentRisk?.m1_overdue_rate), percent(priorRisk?.m1_overdue_rate)),
    rateKpi("转化率", percent(currentCustomer?.conversion_rate), percent(priorCustomer?.conversion_rate)),
  ];
  const evidenceIds = ["loan_product_trend", "risk_product_trend", "customer_product_trend", "channel_operation"].map((key) => snapshot?.datasets[key]?.evidence.evidence_id).filter((value): value is string => Boolean(value));
  return { hasData: loanRows.length > 0 || riskRows.length > 0, trend, channels, kpis, evidenceIds };
}

function readyRows(snapshot: OperatingSnapshot | null, key: string) { return snapshot?.datasets[key]?.status === "ready" ? snapshot.datasets[key].rows : []; }
function snapshotEvidenceRefs(snapshot: OperatingSnapshot) { return Object.entries(snapshot.datasets).flatMap(([key, dataset]) => dataset.evidence.evidence_id ? [{ id: dataset.evidence.evidence_id, type: "operating_snapshot", label: key }] : []); }
function snapshotDatasetSnapshot(snapshot: OperatingSnapshot) { return { id: snapshot.view, version: snapshot.generated_at, generatedAt: snapshot.generated_at }; }
function byMonth(left: Record<string, unknown>, right: Record<string, unknown>) { return String(left.month || "").localeCompare(String(right.month || "")); }
function numeric(value: unknown) { const result = Number(value); return Number.isFinite(result) ? result : 0; }
function scaled(value: unknown, scale: number) { const result = Number(value); return Number.isFinite(result) ? result / scale : undefined; }
function percent(value: unknown) { const result = Number(value); return Number.isFinite(result) ? result * 100 : undefined; }
function display(value?: number) { return value === undefined ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 }); }
function valueKpi(label: string, value?: number, prior?: number) { const change = value !== undefined && prior ? ((value - prior) / Math.abs(prior)) * 100 : undefined; return { label, value: display(value), change: change === undefined ? "暂无可比期" : `${change >= 0 ? "+" : ""}${change.toFixed(1)}% 环比` }; }
function rateKpi(label: string, value?: number, prior?: number) { const change = value !== undefined && prior !== undefined ? value - prior : undefined; return { label, value: value === undefined ? "—" : `${display(value)}%`, change: change === undefined ? "暂无可比期" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}pp 环比` }; }
function parameterLabel(key: string) { return ({ rateAdjust: "利率调整", creditLimit: "额度调整", approvalRate: "审批率调整", pushRate: "触达率调整" } as Record<string, string>)[key] || key; }

function SandboxState({ message }: { message: string }) {
  return <div className="p-7"><div className="mb-6 flex items-start justify-between gap-4"><div><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">经营沙盘</h2><p className="text-[13px] text-[#aeaeb2] mt-1">分产品线经营深度分析 · 策略推演与ROI模拟</p></div><div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true" /></div><div className="mt-6 rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]">{message}</div></div>;
}
