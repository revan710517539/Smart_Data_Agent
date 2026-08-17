import { useEffect, useMemo, useState } from "react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Cell,
} from "recharts";
import {
  TrendingDown, TrendingUp, AlertTriangle, Lightbulb, ChevronDown, Filter,
  Download, Sparkles, CreditCard, Landmark, Building2, ArrowUpRight,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { runApplicationAction } from "../services/applicationApi";
import { apiErrorMessage } from "../services/apiClient";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";
import { updateAnalysisWorkspacePageContext } from "./analysis-workspace/AnalysisWorkspaceRail";

type ProductView = "consumer" | "business" | "compare";

export function BusinessFunnel() {
  const { tenantId, userId } = usePlatformContext();
  const [productView, setProductView] = useState<ProductView>("compare");
  const [selectedBank, setSelectedBank] = useState("全部分行");
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOperatingSnapshot({ tenantId, userId, view: "business_funnel" })
      .then((result) => {
        if (!cancelled) {
          setSnapshot(result);
          setNotice("");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSnapshot(null);
          setNotice(apiErrorMessage(error, "业务漏斗数据加载失败。"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const funnelModel = useMemo(() => buildFunnelModel(snapshot, selectedBank), [selectedBank, snapshot]);
  const { consumerFunnel, businessFunnel, bankRows, dailyTrend, trendKeys, stageComparison, insights, banks, stageNames } = funnelModel;

  useEffect(() => {
    if (!snapshot) return;
    const productLine = productView === "consumer" ? "消费贷" : productView === "business" ? "经营贷" : "";
    updateAnalysisWorkspacePageContext("funnel", {
      route: "funnel",
      filters: {
        branch_name: selectedBank === "全部分行" ? "" : selectedBank,
        product_line: productLine,
      },
      dataset_snapshot: snapshotDatasetSnapshot(snapshot),
      evidence_refs: snapshotEvidenceRefs(snapshot),
      visualization: { product_view: productView, stage_names: stageNames, row_count: snapshot.datasets.funnel_operation?.rows.length || 0 },
      analysis_plan_hint: {
        dataset_id: "funnel_operation_mart",
        metrics: ["stage_count"],
        dimensions: ["product_line", "branch_name", "stage_name", "stage_order", "stat_date"],
        chart_types: ["column", "table"],
        analysis_angles: ["识别当前筛选下的漏斗断点", "比较相邻阶段转化和机构差异"],
      },
    });
  }, [productView, selectedBank, snapshot, stageNames]);

  const exportFunnel = () => setNotice("漏斗真实导出产物尚未生成；系统不会下载基于页面数组拼出的伪 CSV。 ");

  if (loading && !snapshot) return <FunnelState message="正在读取受治理漏斗数据…" />;
  if (!funnelModel.hasData) {
    return <FunnelState message={notice || "当前租户未接入 funnel_operation_mart，页面不会使用固定漏斗人数和随机趋势补位。"} />;
  }

  const renderFunnel = (stages: { name: string; value: number; rate: string }[], color: string) => {
    const maxVal = stages[0].value;
    return (
      <div className="flex items-end gap-1 h-[150px]">
        {stages.map((stage, i) => {
          const height = Math.max((stage.value / maxVal) * 130, 20);
          const prevRate = i > 0 ? parseFloat(stages[i].rate) : 100;
          return (
            <div key={stage.name} className="flex-1 flex flex-col items-center">
              <div className="text-[10px] text-[#aeaeb2] mb-1">{stage.rate}</div>
              <div
                className="w-full rounded-sm transition-all hover:opacity-70 cursor-pointer"
                style={{ height: `${height}px`, backgroundColor: `${color}${i === 0 ? "18" : Math.max(8, 20 - i * 2).toString(16)}`, borderBottom: `2px solid ${color}` }}
              />
              <div className="text-[10px] text-[#636366] mt-1.5 text-center leading-tight">{stage.name}</div>
              <div className="text-[9px] text-[#c7c7cc]">{(stage.value / 10000).toFixed(1)}万</div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="p-7">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">业务漏斗</h2>
          <p className="text-[13px] text-[#aeaeb2] mt-1">消费贷线上自助漏斗 vs 经营贷关系驱动漏斗 · 定位转化断点</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <select
              value={selectedBank}
              onChange={(e) => {
                setSelectedBank(e.target.value);
                void runApplicationAction({
                  tenantId,
                  userId,
                  moduleKey: "business_funnel",
                  action: "select_bank",
                  payload: { selectedBank: e.target.value, productView },
                }).catch(() => undefined);
              }}
              className="appearance-none pl-8 pr-7 py-[6px] bg-white border border-[#e5e5ea] rounded-lg text-[12px] text-[#636366] focus:outline-none cursor-pointer">
              <option>全部分行</option>
              {banks.map((b) => (<option key={b}>{b}</option>))}
            </select>
            <Building2 className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#c7c7cc]" />
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[#c7c7cc] pointer-events-none" />
          </div>
          <button
            onClick={() => void exportFunnel()}
            className="flex items-center gap-1 px-3 py-1.5 bg-white border border-[#e5e5ea] rounded-lg text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
          >
            <Download className="w-3.5 h-3.5" /> 导出
          </button>
        </div>
      </div>

      {(notice || !snapshot?.publishable) && (
        <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">
          {notice || `当前数据模式：${snapshot?.data_modes.join("、") || "未知"}；不可作为正式报告发布证据。`}
        </div>
      )}

      {/* Product Toggle */}
      <div className="flex gap-px bg-[#f2f2f7] rounded-lg p-0.5 w-fit mb-6">
        {([
          { key: "compare", label: "双产品对比" },
          { key: "consumer", label: "消费贷" },
          { key: "business", label: "经营贷" },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setProductView(tab.key);
              void runApplicationAction({
                tenantId,
                userId,
                moduleKey: "business_funnel",
                action: "select_product_view",
                payload: { productView: tab.key, selectedBank },
              }).catch(() => undefined);
            }}
            className={`px-4 py-[6px] rounded-md text-[13px] transition-all ${productView === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e]"}`}>
            {tab.label}
          </button>
        ))}
      </div>

      {productView === "compare" && (
        <>
          {/* 双漏斗并排对比 */}
          <div className="grid grid-cols-2 gap-5 mb-6">
            <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
              <div className="flex items-center gap-2 mb-4">
                <CreditCard className="w-4 h-4 text-[#8a8a8e]" />
                <h3 className="text-[13px] text-[#1d1d1f]">消费贷漏斗</h3>
                <span className="text-[10px] text-[#aeaeb2] bg-[#f2f2f7] px-1.5 py-0.5 rounded">线上自助 · 快审批</span>
              </div>
              {renderFunnel(consumerFunnel, "#3a3a3c")}
              <div className="mt-4 grid grid-cols-3 gap-2">
                <div className="p-2 bg-[#fafbfc] rounded-lg text-center">
                  <div className="text-[10px] text-[#c7c7cc]">端到端转化</div>
                  <div className="text-[14px] text-[#1d1d1f]">{endToEndRate(consumerFunnel)}</div>
                </div>
                <div className="p-2 bg-[#fafbfc] rounded-lg text-center">
                  <div className="text-[10px] text-[#c7c7cc]">平均时效</div>
                  <div className="text-[14px] text-[#1d1d1f]">未接入</div>
                </div>
                <div className="p-2 bg-[#fafbfc] rounded-lg text-center">
                  <div className="text-[10px] text-[#c7c7cc]">线上占比</div>
                  <div className="text-[14px] text-[#1d1d1f]">未接入</div>
                </div>
              </div>
            </div>
            <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
              <div className="flex items-center gap-2 mb-4">
                <Landmark className="w-4 h-4 text-[#8a8a8e]" />
                <h3 className="text-[13px] text-[#1d1d1f]">经营贷漏斗</h3>
                <span className="text-[10px] text-[#aeaeb2] bg-[#f2f2f7] px-1.5 py-0.5 rounded">客户经理 · 实地尽调</span>
              </div>
              {renderFunnel(businessFunnel, "#8e8e93")}
              <div className="mt-4 grid grid-cols-3 gap-2">
                <div className="p-2 bg-[#fafbfc] rounded-lg text-center">
                  <div className="text-[10px] text-[#c7c7cc]">端到端转化</div>
                  <div className="text-[14px] text-[#1d1d1f]">{endToEndRate(businessFunnel)}</div>
                </div>
                <div className="p-2 bg-[#fafbfc] rounded-lg text-center">
                  <div className="text-[10px] text-[#c7c7cc]">平均时效</div>
                  <div className="text-[14px] text-[#1d1d1f]">未接入</div>
                </div>
                <div className="p-2 bg-[#fafbfc] rounded-lg text-center">
                  <div className="text-[10px] text-[#c7c7cc]">线下占比</div>
                  <div className="text-[14px] text-[#1d1d1f]">未接入</div>
                </div>
              </div>
            </div>
          </div>

          {/* 对比分析表 */}
          <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 mb-6">
            <h3 className="text-[13px] text-[#1d1d1f] mb-4">业务模式差异对比</h3>
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-[11px] text-[#aeaeb2] border-b border-[#f0f0f2]">
                  <th className="text-left py-2 px-2">维度</th>
                  <th className="text-center py-2 px-2">消费贷</th>
                  <th className="text-center py-2 px-2">经营贷</th>
                  <th className="text-center py-2 px-2">差异说明</th>
                </tr>
              </thead>
              <tbody>
                {stageComparison.map((row) => (
                  <tr key={row.dim} className="border-b border-[#f8f8f8] hover:bg-[#fafbfc]">
                    <td className="py-2.5 px-2 text-[#636366]">{row.dim}</td>
                    <td className="text-center px-2 text-[#1d1d1f]">{row.c}</td>
                    <td className="text-center px-2 text-[#1d1d1f]">{row.b}</td>
                    <td className="text-center px-2 text-[#aeaeb2] text-[11px]">{row.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {(productView === "consumer" || productView === "business") && (
        <>
          {/* 单产品漏斗详情 */}
          <div className="grid grid-cols-3 gap-5 mb-6">
            <div className="col-span-2 bg-white rounded-xl border border-[#f0f0f2] p-5">
              <div className="flex items-center gap-2 mb-4">
                {productView === "consumer" ? <CreditCard className="w-4 h-4 text-[#8a8a8e]" /> : <Landmark className="w-4 h-4 text-[#8a8a8e]" />}
                <h3 className="text-[13px] text-[#1d1d1f]">{productView === "consumer" ? "消费贷" : "经营贷"}全链路漏斗</h3>
              </div>
              {renderFunnel(productView === "consumer" ? consumerFunnel : businessFunnel, productView === "consumer" ? "#3a3a3c" : "#8e8e93")}
              <div className="mt-5">
                <h4 className="text-[12px] text-[#636366] mb-3">各环节转化率趋势(本月)</h4>
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={dailyTrend[productView]}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#c7c7cc" }} stroke="transparent" tickLine={false} />
                    <YAxis tick={{ fontSize: 9, fill: "#c7c7cc" }} stroke="transparent" tickLine={false} axisLine={false} domain={[40, 100]} />
                    <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    {trendKeys[productView].map((key, index) => (
                      <Area key={key} type="monotone" dataKey={key} stroke={["#3a3a3c", "#8e8e93", "#c7c7cc"][index % 3]} fill={index === 0 ? "#3a3a3c08" : "none"} strokeWidth={index === 0 ? 1.5 : 1} strokeDasharray={index === 0 ? undefined : "4 4"} dot={false} />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* 右侧AI洞察 */}
            <div className="space-y-4">
              <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles className="w-4 h-4 text-[#aeaeb2]" />
                  <h3 className="text-[13px] text-[#1d1d1f]">证据型漏损分析</h3>
                </div>
                <div className="space-y-3">
                  {insights[productView].map((insight, index) => (
                    <div key={insight.title} className="p-3 bg-[#fafbfc] rounded-lg">
                      <div className={`flex items-center gap-1 text-[12px] mb-1 ${index === 0 ? "text-[#ea4335]" : "text-[#636366]"}`}>
                        <AlertTriangle className="w-3 h-3" /> {insight.title}
                      </div>
                      <p className="text-[11px] text-[#8a8a8e] leading-[1.6]">{insight.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* 各行漏斗对比 */}
          <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Building2 className="w-4 h-4 text-[#aeaeb2]" />
              <h3 className="text-[13px] text-[#1d1d1f]">各分行{productView === "consumer" ? "消费贷" : "经营贷"}漏斗对比</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[11px] text-[#aeaeb2] border-b border-[#f0f0f2]">
                    <th className="text-left py-2 px-2">分行</th>
                    {stageNames[productView].slice(0, 6).map((name) => <th key={name} className="text-right px-2">{name}</th>)}
                    <th className="text-right px-2">端到端转化</th>
                    <th className="text-right px-2">数据日期</th>
                  </tr>
                </thead>
                <tbody>
                  {bankRows[productView].map((row) => (
                    <tr key={row.bank} className="border-b border-[#f8f8f8] hover:bg-[#fafbfc]">
                      <td className="py-2.5 px-2 text-[#1d1d1f]">{row.bank}</td>
                      {stageNames[productView].slice(0, 6).map((name) => <td key={name} className="text-right px-2 text-[#636366]">{formatStageCount(row.values[name])}</td>)}
                      <td className="text-right px-2 text-[#1d1d1f]">{row.convRate}</td>
                      <td className="text-right px-2 text-[#aeaeb2]">{row.date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

type FunnelStage = { name: string; code: string; order: number; value: number; rate: string };
type FunnelBankRow = { bank: string; values: Record<string, number>; convRate: string; date: string };

function buildFunnelModel(snapshot: OperatingSnapshot | null, selectedBank: string) {
  const dataset = snapshot?.datasets.funnel_operation;
  const allRows = dataset?.status === "ready" ? dataset.rows : [];
  const rows = selectedBank === "全部分行" ? allRows : allRows.filter((row) => row.branch_name === selectedBank);
  const products = { consumer: "消费贷", business: "经营贷" } as const;
  const stagesByProduct = Object.fromEntries(
    Object.entries(products).map(([key, product]) => [key, aggregateLatestStages(rows, product)]),
  ) as Record<"consumer" | "business", FunnelStage[]>;
  const bankRows = Object.fromEntries(
    Object.entries(products).map(([key, product]) => [key, buildBankRows(allRows, product)]),
  ) as Record<"consumer" | "business", FunnelBankRow[]>;
  const dailyTrend = Object.fromEntries(
    Object.entries(products).map(([key, product]) => [key, buildDailyTrend(rows, product)]),
  ) as Record<"consumer" | "business", Record<string, string | number>[]>;
  const trendKeys = {
    consumer: transitionNames(stagesByProduct.consumer).slice(0, 3),
    business: transitionNames(stagesByProduct.business).slice(0, 3),
  };
  const maxStages = Math.max(stagesByProduct.consumer.length, stagesByProduct.business.length);
  const stageComparison = Array.from({ length: maxStages }, (_, index) => {
    const consumer = stagesByProduct.consumer[index];
    const business = stagesByProduct.business[index];
    return {
      dim: `第 ${index + 1} 阶段`,
      c: consumer ? `${consumer.name} · ${formatStageCount(consumer.value)}` : "—",
      b: business ? `${business.name} · ${formatStageCount(business.value)}` : "—",
      note: "同一授权快照的阶段位置对比",
    };
  });
  return {
    hasData: allRows.length > 0,
    consumerFunnel: stagesByProduct.consumer,
    businessFunnel: stagesByProduct.business,
    bankRows,
    dailyTrend,
    trendKeys,
    stageComparison,
    insights: {
      consumer: buildFunnelInsights(stagesByProduct.consumer, bankRows.consumer),
      business: buildFunnelInsights(stagesByProduct.business, bankRows.business),
    },
    banks: Array.from(new Set(allRows.map((row) => String(row.branch_name || "")).filter(Boolean))).sort(),
    stageNames: {
      consumer: stagesByProduct.consumer.map((stage) => stage.name),
      business: stagesByProduct.business.map((stage) => stage.name),
    },
  };
}

function snapshotEvidenceRefs(snapshot: OperatingSnapshot) {
  return Object.entries(snapshot.datasets).flatMap(([key, dataset]) => dataset.evidence.evidence_id ? [{ id: dataset.evidence.evidence_id, type: "operating_snapshot", label: key }] : []);
}

function snapshotDatasetSnapshot(snapshot: OperatingSnapshot) {
  return { id: snapshot.view, version: snapshot.generated_at, generatedAt: snapshot.generated_at };
}

function FunnelState({ message }: { message: string }) {
  return (
    <div className="p-7">
      <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">业务漏斗</h2>
      <p className="text-[13px] text-[#aeaeb2] mt-1">消费贷线上自助漏斗 vs 经营贷关系驱动漏斗 · 定位转化断点</p>
      <div className="mt-6 rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]">{message}</div>
    </div>
  );
}

function aggregateLatestStages(rows: Record<string, unknown>[], product: string) {
  const productRows = rows.filter((row) => row.product_line === product);
  const latestDate = productRows.map((row) => String(row.stat_date || "")).sort().at(-1);
  const stageRows = productRows.filter((row) => String(row.stat_date || "") === latestDate);
  const grouped = new Map<string, { name: string; code: string; order: number; value: number }>();
  stageRows.forEach((row) => {
    const code = String(row.stage_code || row.stage_name || "");
    if (!code) return;
    const current = grouped.get(code) || {
      name: String(row.stage_name || code),
      code,
      order: Number(row.stage_order) || 0,
      value: 0,
    };
    current.value += Number(row.stage_count) || 0;
    grouped.set(code, current);
  });
  const stages = Array.from(grouped.values()).sort((left, right) => left.order - right.order || left.code.localeCompare(right.code));
  return stages.map((stage, index) => ({
    ...stage,
    rate: index === 0 ? "100%" : stages[index - 1].value > 0 ? `${((stage.value / stages[index - 1].value) * 100).toFixed(1)}%` : "—",
  }));
}

function buildBankRows(rows: Record<string, unknown>[], product: string): FunnelBankRow[] {
  const branches = Array.from(new Set(rows.filter((row) => row.product_line === product).map((row) => String(row.branch_name || "")).filter(Boolean)));
  return branches.map((bank) => {
    const bankRows = rows.filter((row) => row.product_line === product && row.branch_name === bank);
    const date = bankRows.map((row) => String(row.stat_date || "")).sort().at(-1) || "—";
    const latest = bankRows.filter((row) => String(row.stat_date || "") === date).sort((left, right) => Number(left.stage_order) - Number(right.stage_order));
    const values = Object.fromEntries(latest.map((row) => [String(row.stage_name || row.stage_code), Number(row.stage_count) || 0]));
    const firstValue = Number(latest[0]?.stage_count) || 0;
    const lastValue = Number(latest.at(-1)?.stage_count) || 0;
    return { bank, values, convRate: firstValue > 0 ? `${((lastValue / firstValue) * 100).toFixed(1)}%` : "—", date };
  });
}

function buildDailyTrend(rows: Record<string, unknown>[], product: string) {
  const dates = Array.from(new Set(rows.filter((row) => row.product_line === product).map((row) => String(row.stat_date || "")).filter(Boolean))).sort();
  return dates.map((date) => {
    const stages = aggregateLatestStages(rows.filter((row) => row.stat_date === date), product);
    const trend: Record<string, string | number> = { date };
    stages.slice(1).forEach((stage, index) => {
      const previous = stages[index];
      trend[`${previous.name}→${stage.name}`] = previous.value > 0 ? (stage.value / previous.value) * 100 : 0;
    });
    return trend;
  });
}

function transitionNames(stages: FunnelStage[]) {
  return stages.slice(1).map((stage, index) => `${stages[index].name}→${stage.name}`);
}

function buildFunnelInsights(stages: FunnelStage[], branches: FunnelBankRow[]) {
  const transitions = stages.slice(1).map((stage, index) => ({
    title: `${stages[index].name}→${stage.name}`,
    rate: stages[index].value > 0 ? (stage.value / stages[index].value) * 100 : 0,
    loss: Math.max(0, stages[index].value - stage.value),
  })).sort((left, right) => left.rate - right.rate);
  const weakest = branches.slice().sort((left, right) => parseFloat(left.convRate) - parseFloat(right.convRate))[0];
  return [
    transitions[0]
      ? { title: `最大转化断点：${transitions[0].title}`, content: `阶段转化率 ${transitions[0].rate.toFixed(1)}%，本快照流失 ${formatStageCount(transitions[0].loss)}。该结论只描述已执行漏斗事实，不推测原因。` }
      : { title: "暂无转化断点", content: "至少需要两个有顺序的漏斗阶段。" },
    weakest
      ? { title: `最低端到端转化：${weakest.bank}`, content: `端到端转化率 ${weakest.convRate}，数据日期 ${weakest.date}。需进入智能分析结合渠道和客群证据归因。` }
      : { title: "暂无机构对比", content: "当前快照没有机构维度数据。" },
  ];
}

function endToEndRate(stages: FunnelStage[]) {
  if (stages.length < 2 || stages[0].value <= 0) return "—";
  return `${((stages.at(-1)!.value / stages[0].value) * 100).toFixed(1)}%`;
}

function formatStageCount(value?: number) {
  if (value === undefined) return "—";
  return value >= 10000 ? `${(value / 10000).toFixed(1)}万` : value.toLocaleString("zh-CN");
}
