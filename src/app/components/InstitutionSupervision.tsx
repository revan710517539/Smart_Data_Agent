import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertTriangle, Building2, CreditCard, Download, Landmark, Sparkles } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { runApplicationAction } from "../services/applicationApi";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";

type ProductFilter = "all" | "consumer" | "business";
type ProductFacts = { loan?: number; drawdown?: number; balance?: number; m1?: number; month?: string };
type BranchFacts = { name: string; consumer: ProductFacts; business: ProductFacts };

export function InstitutionSupervision() {
  const { tenantId, userId } = usePlatformContext();
  const [productFilter, setProductFilter] = useState<ProductFilter>("all");
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOperatingSnapshot({ tenantId, userId, view: "institution_supervision" })
      .then((result) => {
        if (!cancelled) {
          setSnapshot(result);
          setNotice("");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSnapshot(null);
          setNotice(apiErrorMessage(error, "机构督导数据加载失败。"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const model = useMemo(() => buildSupervisionModel(snapshot), [snapshot]);
  const selected = model.branches.find((branch) => branch.name === selectedBranch);
  const runSupervisionAction = (action: string, payload: Record<string, unknown> = {}) =>
    runApplicationAction({ tenantId, userId, moduleKey: "institution_supervision", action, payload }).catch(() => undefined);

  if (loading && !snapshot) return <SupervisionState message="正在读取受治理机构数据…" />;
  if (!model.hasData) return <SupervisionState message={notice || "当前租户没有机构级经营事实，页面不会展示内置排名和督导结论。"} />;

  return (
    <div className="p-7">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">机构督导</h2>
          <p className="text-[13px] text-[#aeaeb2] mt-1">分行 × 产品矩阵分析 · 消费贷/经营贷分维度督导</p>
        </div>
        <button onClick={() => setNotice("真实导出需先生成带授权和过期时间的 artifact；系统不会导出页面拼接数据。") } className="flex items-center gap-1 px-3 py-1.5 bg-white border border-[#e5e5ea] rounded-lg text-[12px] text-[#636366] hover:bg-[#f2f2f7]"><Download className="w-3.5 h-3.5" /> 导出报告</button>
      </div>

      {(notice || !snapshot?.publishable) && <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">{notice || `当前数据模式：${snapshot?.data_modes.join("、") || "未知"}；不可作为正式督导报告发布。`}</div>}

      <div className="flex items-center gap-3 mb-6">
        <div className="flex gap-px bg-[#f2f2f7] rounded-lg p-0.5">
          {([
            { key: "all", label: "全部产品" },
            { key: "consumer", label: "消费贷" },
            { key: "business", label: "经营贷" },
          ] as const).map((tab) => (
            <button key={tab.key} onClick={() => { setProductFilter(tab.key); void runSupervisionAction("select_product_filter", { productFilter: tab.key, selectedBranch }); }} className={`px-4 py-[6px] rounded-md text-[13px] transition-all ${productFilter === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e]"}`}>{tab.label}</button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 mb-6">
        <h3 className="text-[13px] text-[#1d1d1f] mb-4">各分行双产品放款排名(亿)</h3>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={model.chartData} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#636366" }} stroke="transparent" tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {(productFilter === "all" || productFilter === "consumer") && <Bar dataKey="消费贷" fill="#3a3a3c" radius={[3, 3, 0, 0]} barSize={productFilter === "all" ? 18 : 28} />}
            {(productFilter === "all" || productFilter === "business") && <Bar dataKey="经营贷" fill="#c7c7cc" radius={[3, 3, 0, 0]} barSize={productFilter === "all" ? 18 : 28} />}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 mb-6">
        <div className="flex items-center justify-between mb-4"><h3 className="text-[13px] text-[#1d1d1f]">分行经营明细</h3><span className="text-[11px] text-[#aeaeb2]">点击分行查看证据画像</span></div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead><tr className="text-[11px] text-[#aeaeb2] border-b border-[#f0f0f2]"><th className="text-left py-2 px-2">分行</th>{(productFilter === "all" || productFilter === "consumer") && <><th className="text-right px-2">消费贷放款(亿)</th><th className="text-right px-2">动支率</th><th className="text-right px-2">M1</th><th className="text-right px-2">余额(亿)</th></>}{(productFilter === "all" || productFilter === "business") && <><th className="text-right px-2">经营贷放款(亿)</th><th className="text-right px-2">动支率</th><th className="text-right px-2">M1</th><th className="text-right px-2">余额(亿)</th></>}</tr></thead>
            <tbody>
              {model.branches.map((branch) => (
                <tr key={branch.name} onClick={() => { const next = selectedBranch === branch.name ? null : branch.name; setSelectedBranch(next); void runSupervisionAction("select_branch", { selectedBranch: next, productFilter }); }} className={`border-b border-[#f8f8f8] hover:bg-[#fafbfc] cursor-pointer ${selectedBranch === branch.name ? "bg-[#fafbfc]" : ""}`}>
                  <td className="py-2.5 px-2 text-[#1d1d1f]">{branch.name}</td>
                  {(productFilter === "all" || productFilter === "consumer") && <ProductCells facts={branch.consumer} />}
                  {(productFilter === "all" || productFilter === "business") && <ProductCells facts={branch.business} />}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <div className="grid grid-cols-2 gap-5">
          <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
            <div className="flex items-center gap-2 mb-3"><Building2 className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">{selected.name}相对画像</h3></div>
            <ResponsiveContainer width="100%" height={250}>
              <RadarChart data={relativeRadar(selected, model.branches)}>
                <PolarGrid stroke="#f0f0f2" /><PolarAngleAxis dataKey="metric" tick={{ fontSize: 10, fill: "#aeaeb2" }} /><PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                <Radar name="消费贷" dataKey="消费贷" stroke="#3a3a3c" fill="#3a3a3c" fillOpacity={0.06} /><Radar name="经营贷" dataKey="经营贷" stroke="#aeaeb2" fill="none" strokeDasharray="4 4" />
              </RadarChart>
            </ResponsiveContainer>
            <div className="text-[10px] text-[#c7c7cc]">相对分数仅在当前快照机构间归一，不是目标完成率或绩效评级。</div>
          </div>
          <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
            <div className="flex items-center gap-2 mb-3"><Sparkles className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">证据型督导摘要</h3></div>
            <div className="space-y-3 text-[11px] leading-[1.7] text-[#8a8a8e]">
              <p>• 消费贷：放款 {formatNumber(selected.consumer.loan)} 亿元，动支率 {formatPercent(selected.consumer.drawdown)}，M1 {formatPercent(selected.consumer.m1)}。</p>
              <p>• 经营贷：放款 {formatNumber(selected.business.loan)} 亿元，动支率 {formatPercent(selected.business.drawdown)}，M1 {formatPercent(selected.business.m1)}。</p>
              <p>• 当前仅有规模、余额、动支与 M1 证据；目标、审批、抵押、续贷等字段未接入时不生成督导判断。</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ProductCells({ facts }: { facts: ProductFacts }) {
  return <><td className="text-right px-2 text-[#1d1d1f]">{formatNumber(facts.loan)}</td><td className="text-right px-2 text-[#636366]">{formatPercent(facts.drawdown)}</td><td className="text-right px-2 text-[#636366]">{formatPercent(facts.m1)}</td><td className="text-right px-2 text-[#636366]">{formatNumber(facts.balance)}</td></>;
}

function buildSupervisionModel(snapshot: OperatingSnapshot | null) {
  const loanRows = snapshot?.datasets.loan_operation?.status === "ready" ? snapshot.datasets.loan_operation.rows : [];
  const riskRows = snapshot?.datasets.risk_operation?.status === "ready" ? snapshot.datasets.risk_operation.rows : [];
  const names = Array.from(new Set(loanRows.map((row) => String(row.branch_name || "")).filter(Boolean))).sort();
  const branches = names.map((name) => ({ name, consumer: factsFor(name, "消费贷", loanRows, riskRows), business: factsFor(name, "经营贷", loanRows, riskRows) }));
  return { hasData: branches.length > 0, branches, chartData: branches.map((branch) => ({ name: branch.name.replace("分行", ""), 消费贷: branch.consumer.loan || 0, 经营贷: branch.business.loan || 0 })) };
}

function factsFor(branch: string, product: string, loanRows: Record<string, unknown>[], riskRows: Record<string, unknown>[]): ProductFacts {
  const loan = latest(loanRows.filter((row) => row.branch_name === branch && row.product_line === product));
  const risk = latest(riskRows.filter((row) => row.branch_name === branch && row.product_line === product));
  return { loan: scaled(loan?.loan_amount, 1e8), drawdown: percent(loan?.drawdown_rate), balance: scaled(risk?.loan_balance, 1e8), m1: percent(risk?.m1_overdue_rate), month: String(loan?.month || risk?.month || "") };
}

function latest(rows: Record<string, unknown>[]) { return rows.slice().sort((left, right) => String(left.month || "").localeCompare(String(right.month || ""))).at(-1); }
function scaled(value: unknown, scale: number) { const number = Number(value); return Number.isFinite(number) ? number / scale : undefined; }
function percent(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number * 100 : undefined; }
function formatNumber(value?: number) { return value === undefined ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 }); }
function formatPercent(value?: number) { return value === undefined ? "—" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`; }

function relativeRadar(selected: BranchFacts, branches: BranchFacts[]) {
  const dimensions: Array<[string, keyof ProductFacts, boolean]> = [["放款规模", "loan", true], ["动支效率", "drawdown", true], ["资产质量", "m1", false], ["余额规模", "balance", true]];
  return dimensions.map(([metric, key, higherBetter]) => {
    const values = branches.flatMap((branch) => [branch.consumer[key], branch.business[key]]).filter((value): value is number => typeof value === "number");
    const max = Math.max(...values, 0); const min = Math.min(...values, 0);
    const score = (value?: string | number) => { if (typeof value !== "number") return 0; if (max === min) return 50; const normalized = ((value - min) / (max - min)) * 100; return Math.round(higherBetter ? normalized : 100 - normalized); };
    return { metric, 消费贷: score(selected.consumer[key]), 经营贷: score(selected.business[key]) };
  });
}

function SupervisionState({ message }: { message: string }) {
  return <div className="p-7"><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">机构督导</h2><p className="text-[13px] text-[#aeaeb2] mt-1">分行 × 产品矩阵分析 · 消费贷/经营贷分维度督导</p><div className="mt-6 rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]">{message}</div></div>;
}
