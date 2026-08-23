import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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
import { AlertTriangle, CreditCard, Landmark, Sparkles, Target } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { fetchMarketBundle, type MarketBundle, type MarketEntity, type MarketObservation } from "../services/marketApi";
import { runApplicationAction } from "../services/applicationApi";
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

type ProductView = "consumer" | "business";
type Competitor = {
  id: string;
  name: string;
  self: boolean;
  rate?: number;
  maxAmt?: number;
  approval?: number;
  drawdown?: number;
  speed?: number;
  cycle?: number;
  npl?: number;
  online?: number;
  collateral?: number;
  renewal?: number;
  satisfaction?: number;
  share?: number;
  observedAt?: string;
  publishers: string[];
  evidenceCount: number;
};

const EMPTY_MARKET: MarketBundle = {
  tenant_id: "",
  sources: [],
  entities: [],
  observations: [],
  rules: [],
  events: [],
};

const COMPETITION_VISUAL_DEFINITIONS: StandardAnalysisVisualDefinition[] = [
  { id: "competitors", label: "竞品概览", defaultSpan: 12, defaultHeight: 280 },
  { id: "radar", label: "综合竞争力", defaultSpan: 6, defaultHeight: 390 },
  { id: "market-share", label: "市场份额对比", defaultSpan: 6, defaultHeight: 390 },
  { id: "insights", label: "监控洞察", defaultSpan: 12, defaultHeight: 320 },
];

export function CompetitionAnalysis() {
  const { tenantId, userId, isSuperAdmin } = usePlatformContext();
  const [productView, setProductView] = useState<ProductView>("consumer");
  const [market, setMarket] = useState(EMPTY_MARKET);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const stickyNote = useStickyNote("competition_analysis", "competition_analysis");
  const pageLayout = useStandardAnalysisPageLayout({ tenantId, userId, moduleKey: "competition_analysis", definitions: COMPETITION_VISUAL_DEFINITIONS });

  useEffect(() => {
    if (!isSuperAdmin) pageLayout.editController.setMode("browse");
  }, [isSuperAdmin, pageLayout.editController.setMode]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchMarketBundle({ tenantId, userId })
      .then((bundle) => {
        if (!cancelled) setMarket(bundle);
      })
      .catch((error) => {
        if (cancelled) return;
        setMarket(EMPTY_MARKET);
        setNotice(apiErrorMessage(error, "市场监控数据加载失败。"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const competitors = useMemo(
    () => buildCompetitors(productView, market.entities, market.observations),
    [market.entities, market.observations, productView],
  );
  const radarData = useMemo(() => buildRadarData(productView, competitors), [competitors, productView]);
  const publishers = Array.from(new Set(competitors.flatMap((competitor) => competitor.publishers)));
  const latestObservedAt = competitors.map((competitor) => competitor.observedAt || "").sort().at(-1) || "";
  const relevantEvents = useMemo(() => market.events.filter((event) => {
    const observationId = String(event.evidence.observation_id || "");
    const observation = market.observations.find((item) => item.market_observation_id === observationId);
    const entity = market.entities.find((item) => item.market_entity_id === observation?.market_entity_id);
    return productType(entity) === productView;
  }), [market.entities, market.events, market.observations, productView]);

  useEffect(() => {
    updateAnalysisWorkspacePageContext("competition", {
      route: "competition",
      filters: { product_line: productView === "consumer" ? "消费贷" : "经营贷" },
      dataset_snapshot: { id: "market-monitoring", version: latestObservedAt || "unavailable", generatedAt: latestObservedAt || undefined },
      evidence_refs: market.observations.filter((item) => productType(market.entities.find((entity) => entity.market_entity_id === item.market_entity_id)) === productView).slice(0, 40).map((item) => ({ id: item.evidence_hash || item.market_observation_id, type: "market_observation", label: item.publisher || item.entity_name })),
      visualization: { product_view: productView, competitors, radar_data: radarData, events: relevantEvents.slice(0, 10) },
      analysis_skill: { id: "competition-monitoring", name: "竞品监控分析", category: "场景", description: "基于当前产品视图与已授权市场观测证据进行对标分析。" },
      analysis_policy: { engine: "IntelligentAnalysisEngine", resultDelivery: "data_first", conflictStrategy: "executed_query_evidence_overrides_page_context" },
    });
  }, [competitors, latestObservedAt, market.entities, market.observations, productView, radarData, relevantEvents]);

  const productSwitch = <div
    className="flex w-fit shrink-0 gap-px rounded-lg bg-[#f2f2f7] p-0.5"
    role="group"
    aria-label="竞品产品类型"
    data-competition-product-switch="true"
  >
    {([
      { key: "consumer", label: "消费贷竞品", icon: CreditCard },
      { key: "business", label: "经营贷竞品", icon: Landmark },
    ] as const).map((tab) => (
      <button
        key={tab.key}
        type="button"
        aria-pressed={productView === tab.key}
        onClick={() => {
          setProductView(tab.key);
          void runApplicationAction({
            tenantId,
            userId,
            moduleKey: "competition_analysis",
            action: "select_product_view",
            payload: { productView: tab.key },
          }).catch(() => setNotice("产品视图已在当前页面切换，但服务端偏好同步失败。"));
        }}
        className={`flex items-center gap-1.5 rounded-md px-4 py-[6px] text-[13px] transition-all ${productView === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e]"}`}
      >
        <tab.icon className="h-3.5 w-3.5" /> {tab.label}
      </button>
    ))}
  </div>;

  const modules = competitors.length > 0 ? [
    {
      id: "competitors",
      content: <div className={`grid h-full content-start gap-3 overflow-y-auto rounded-xl ${competitors.length <= 4 ? "grid-cols-4" : "grid-cols-5"}`}>{competitors.map((competitor) => <CompetitorCard key={competitor.id} competitor={competitor} productView={productView} />)}</div>,
    },
    {
      id: "radar",
      content: <div className="flex h-full min-h-0 flex-col rounded-xl border border-[#f0f0f2] bg-white p-5"><h3 className="mb-1 shrink-0 text-[13px] text-[#1d1d1f]">{productView === "consumer" ? "消费贷" : "经营贷"}综合竞争力</h3><div className="mb-2 shrink-0 text-[10px] text-[#c7c7cc]">仅对同批真实观测做 0–100 相对归一，不代表绝对评级。</div><div className="min-h-0 flex-1">{radarData.length > 0 ? <ResponsiveContainer width="100%" height="100%"><RadarChart data={radarData}><PolarGrid stroke="#f0f0f2" /><PolarAngleAxis dataKey="metric" tick={{ fontSize: 10, fill: "#aeaeb2" }} /><PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />{competitors.slice(0, 4).map((competitor, index) => <Radar key={competitor.id} name={competitor.name} dataKey={competitor.id} stroke={competitor.self ? "#3a3a3c" : ["#8e8e93", "#c7c7cc", "#636366"][index % 3]} fill={competitor.self ? "#3a3a3c" : "none"} fillOpacity={competitor.self ? 0.06 : 0} strokeWidth={competitor.self ? 2 : 1} strokeDasharray={competitor.self ? undefined : "4 4"} />)}<Legend wrapperStyle={{ fontSize: 10 }} /></RadarChart></ResponsiveContainer> : <ChartEmpty text="观测字段不足，无法计算相对雷达。" />}</div></div>,
    },
    {
      id: "market-share",
      content: <div className="flex h-full min-h-0 flex-col rounded-xl border border-[#f0f0f2] bg-white p-5"><h3 className="mb-4 shrink-0 text-[13px] text-[#1d1d1f]">市场份额对比</h3><div className="min-h-0 flex-1">{competitors.some((item) => item.share !== undefined) ? <ResponsiveContainer width="100%" height="100%"><BarChart data={competitors.filter((item) => item.share !== undefined).map((item) => ({ id: item.id, name: item.name, 份额: item.share, self: item.self }))} layout="vertical" margin={{ left: 10 }}><CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" horizontal={false} /><XAxis type="number" tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" tickLine={false} unit="%" /><YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#636366" }} stroke="transparent" tickLine={false} width={65} /><Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} /><Bar dataKey="份额" radius={[0, 4, 4, 0]} barSize={20}>{competitors.filter((item) => item.share !== undefined).map((item) => <Cell key={item.id} fill={item.self ? "#3a3a3c" : "#d1d1d6"} />)}</Bar></BarChart></ResponsiveContainer> : <ChartEmpty text="暂无市场份额观测。" />}</div></div>,
    },
    {
      id: "insights",
      content: <div className="h-full overflow-y-auto rounded-xl border border-[#f0f0f2] bg-white p-5"><div className="flex items-center gap-2 mb-4"><Sparkles className="w-4 h-4 text-[#aeaeb2]" /><h3 className="text-[13px] text-[#1d1d1f]">{productView === "consumer" ? "消费贷" : "经营贷"}监控洞察</h3></div>{relevantEvents.length > 0 ? <div className="grid grid-cols-3 gap-4">{relevantEvents.slice(0, 3).map((event) => <div key={event.market_event_id} className="p-4 bg-[#fafbfc] rounded-lg"><div className="flex items-center gap-1.5 mb-2">{event.severity === "critical" || event.severity === "error" ? <AlertTriangle className="w-3.5 h-3.5 text-[#8a8a8e]" /> : <Target className="w-3.5 h-3.5 text-[#8a8a8e]" />}<span className="text-[12px] text-[#636366]">{event.severity} · {event.status}</span></div><p className="text-[11px] text-[#8a8a8e] leading-[1.7]">{event.event_summary}</p><div className="text-[10px] text-[#c7c7cc] mt-2">证据 {String(event.evidence.evidence_hash || "").slice(0, 12) || "—"} · {formatTime(event.detected_at)}</div></div>)}</div> : <ChartEmpty text="暂无由已审批规则产生的证据型监控洞察。" />}</div>,
    },
  ] : [];

  return (
    <div className={PAGE_DATA_PAGE_GUTTER_CLASS} data-competition-page="true">
      <StandardAnalysisPageHeader title="竞品分析" description="消费贷/经营贷分产品竞品对标 · AI竞争策略建议" metadata={loading ? "正在读取已授权市场证据…" : competitors.length > 0 ? `真实观测 ${competitors.reduce((sum, item) => sum + item.evidenceCount, 0)} 条 · 来源 ${publishers.join("、") || "未标注"} · 最近 ${formatTime(latestObservedAt)}` : undefined} stickyNote={stickyNote} editController={pageLayout.editController} canEditLayout={isSuperAdmin} leadingActions={productSwitch} headerDataAttribute="competition" />
      <StandardAnalysisPageStickyNote stickyNote={stickyNote} />
      {(notice || pageLayout.notice) && <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">{notice || pageLayout.notice}</div>}
      {loading ? <CompetitionState message="正在读取已授权市场证据…" /> : competitors.length > 0 ? <StandardAnalysisPageGrid moduleKey="competition_analysis" definitions={COMPETITION_VISUAL_DEFINITIONS} modules={modules} layout={pageLayout.layout} hiddenDefinitions={pageLayout.hiddenDefinitions} editable={isSuperAdmin && pageLayout.mode === "edit"} onHide={pageLayout.hide} onRestore={pageLayout.restore} onMove={pageLayout.move} /> : (
        <div className="rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]">
          请先将已获授权的市场来源 CSV 放入项目 Origin_Data 文件夹，写入实体与不可变观测证据后，再配置市场监控规则。
        </div>
      )}
    </div>
  );
}

function CompetitorCard({ competitor, productView }: { competitor: Competitor; productView: ProductView }) {
  return (
    <div className={`bg-white p-4 rounded-xl border ${competitor.self ? "border-[#3a3a3c]" : "border-[#f0f0f2]"}`}>
      <div className="flex items-center gap-2 mb-3"><span className="text-[13px] text-[#1d1d1f]">{competitor.name}</span>{competitor.self && <span className="text-[10px] text-[#636366] bg-[#f2f2f7] px-1.5 py-0.5 rounded">当前</span>}</div>
      <div className="space-y-1.5 text-[11px]">
        <MetricRow label="利率" value={percent(competitor.rate)} />
        <MetricRow label="最高额度" value={amountWan(competitor.maxAmt)} />
        <MetricRow label={productView === "consumer" ? "审批时效" : "审批周期"} value={productView === "consumer" ? hours(competitor.speed) : days(competitor.cycle)} />
        <MetricRow label="通过率" value={percent(competitor.approval)} />
        <MetricRow label="NPL" value={percent(competitor.npl)} />
        {productView === "consumer" ? <MetricRow label="线上占比" value={percent(competitor.online)} /> : <MetricRow label="抵押覆盖" value={percent(competitor.collateral)} />}
        <MetricRow label="市场份额" value={percent(competitor.share)} />
      </div>
      <div className="mt-3 border-t border-[#f5f5f7] pt-2 text-[9px] leading-4 text-[#c7c7cc]">{competitor.evidenceCount} 条证据 · {competitor.publishers.join("、") || "来源未标注"}<br />{formatTime(competitor.observedAt)}</div>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between"><span className="text-[#aeaeb2]">{label}</span><span className="text-[#1d1d1f]">{value}</span></div>;
}

function ChartEmpty({ text }: { text: string }) {
  return <div className="flex h-[260px] items-center justify-center text-[11px] text-[#c7c7cc]">{text}</div>;
}

function CompetitionState({ message }: { message: string }) {
  return <div className="rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]">{message}</div>;
}

function buildCompetitors(view: ProductView, entities: MarketEntity[], observations: MarketObservation[]): Competitor[] {
  return entities
    .filter((entity) => entity.status === "active" && productType(entity) === view)
    .map((entity) => {
      const entityObservations = latestPerMetric(observations.filter((item) => item.market_entity_id === entity.market_entity_id));
      const value = (code: string) => numeric(entityObservations.get(code));
      const observedAt = Array.from(entityObservations.values()).map((item) => item.observed_at).sort().at(-1);
      return {
        id: entity.market_entity_id,
        name: entity.entity_name,
        self: Boolean(entity.attributes.is_self),
        rate: value("annual_rate_pct"),
        maxAmt: value("max_amount_wan"),
        approval: value("approval_rate_pct"),
        drawdown: value("drawdown_rate_pct"),
        speed: value("approval_hours"),
        cycle: value("approval_days"),
        npl: value("npl_pct"),
        online: value("online_share_pct"),
        collateral: value("collateral_coverage_pct"),
        renewal: value("renewal_rate_pct"),
        satisfaction: value("satisfaction_score"),
        share: value("market_share_pct"),
        observedAt,
        publishers: Array.from(new Set(Array.from(entityObservations.values()).map((item) => item.publisher))),
        evidenceCount: entityObservations.size,
      };
    })
    .filter((competitor) => competitor.evidenceCount > 0)
    .sort((left, right) => Number(right.self) - Number(left.self));
}

function buildRadarData(view: ProductView, competitors: Competitor[]) {
  const dimensions = view === "consumer"
    ? [
        ["利率竞争力", "rate", false], ["审批速度", "speed", false], ["额度水平", "maxAmt", true],
        ["用户体验", "satisfaction", true], ["风控能力", "npl", false], ["渠道覆盖", "online", true],
      ] as const
    : [
        ["利率竞争力", "rate", false], ["审批效率", "cycle", false], ["额度能力", "maxAmt", true],
        ["客户体验", "satisfaction", true], ["风控能力", "npl", false], ["续贷能力", "renewal", true],
      ] as const;
  const usable = dimensions.filter(([, key]) => competitors.filter((item) => item[key] !== undefined).length >= 2);
  if (usable.length < 3) return [];
  return usable.map(([metric, key, higherBetter]) => {
    const values = competitors.map((item) => item[key]).filter((value): value is number => value !== undefined);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const row: Record<string, string | number> = { metric };
    competitors.forEach((item) => {
      const value = item[key];
      if (value === undefined) return;
      const normalized = max === min ? 50 : ((value - min) / (max - min)) * 100;
      row[item.id] = Math.round(higherBetter ? normalized : 100 - normalized);
    });
    return row;
  });
}

function latestPerMetric(observations: MarketObservation[]) {
  const result = new Map<string, MarketObservation>();
  observations
    .slice()
    .sort((left, right) => right.observed_at.localeCompare(left.observed_at))
    .forEach((observation) => {
      if (!result.has(observation.metric_code)) result.set(observation.metric_code, observation);
    });
  return result;
}

function productType(entity?: MarketEntity): ProductView | "" {
  const value = String(entity?.attributes.product_view || entity?.attributes.product_type || "").toLowerCase();
  return value === "consumer" || value === "business" ? value : "";
}

function numeric(observation?: MarketObservation) {
  return observation?.value_numeric === undefined || observation.value_numeric === null ? undefined : Number(observation.value_numeric);
}

function percent(value?: number) { return value === undefined ? "—" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`; }
function amountWan(value?: number) { return value === undefined ? "—" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}万`; }
function hours(value?: number) { return value === undefined ? "—" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}小时`; }
function days(value?: number) { return value === undefined ? "—" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}天`; }
function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
