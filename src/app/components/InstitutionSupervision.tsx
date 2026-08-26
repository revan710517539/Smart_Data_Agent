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
import { AlertTriangle, Building2, CreditCard, Landmark, Sparkles } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { runApplicationAction } from "../services/applicationApi";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";
import { replaceVisualAnalysisSourceGroup, updateAnalysisWorkspacePageContext } from "./analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "./analysis-workspace/visualAnalysisScope";
import { pageDataToSelection } from "./self-analysis/domain";
import { PAGE_DATA_PAGE_GUTTER_CLASS, PageDataVisualizationModules, usePageDataComposer, type PageDataComposerController } from "./page-data/PageDataComposer";
import { StandardAnalysisPageHeader, StandardAnalysisPageStickyNote } from "./page-data/StandardAnalysisPage";
import { useStickyNote } from "./notes/useStickyNote";

type ProductFilter = "all" | "consumer" | "business";
type ProductFacts = { loan?: number; drawdown?: number; balance?: number; m1?: number; month?: string };
type BranchFacts = { name: string; consumer: ProductFacts; business: ProductFacts };

export function InstitutionSupervision() {
  const { tenantId, userId, isSuperAdmin } = usePlatformContext();
  const [productFilter, setProductFilter] = useState<ProductFilter>("all");
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const pageData = usePageDataComposer({ pageCode: "institution_supervision", moduleKey: "institution_supervision", railPageKey: "supervision" });
  const stickyNote = useStickyNote("institution_supervision", "institution_supervision");

  useEffect(() => {
    if (!isSuperAdmin) pageData.setMode("browse");
  }, [isSuperAdmin, pageData.setMode]);

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

  useEffect(() => {
    if (!snapshot) return;
    updateAnalysisWorkspacePageContext("supervision", {
      route: "supervision",
      filters: { branch_name: selectedBranch || "", product_line: productFilter === "consumer" ? "消费贷" : productFilter === "business" ? "经营贷" : "" },
      dataset_snapshot: snapshotDatasetSnapshot(snapshot),
      evidence_refs: snapshotEvidenceRefs(snapshot),
      visualization: { product_filter: productFilter, selected_branch: selectedBranch, branch_count: model.branches.length, selected_branch_facts: selected || null },
      analysis_plan_hint: {
        dataset_id: productFilter === "all" || productFilter === "consumer" ? "loan_operation_mart" : "risk_operation_mart",
        metrics: productFilter === "business" ? ["m1_overdue_rate", "loan_balance"] : ["loan_amount", "drawdown_rate"],
        dimensions: ["branch_name", "product_line", "month"],
        chart_types: ["column", "table"],
        analysis_angles: ["比较机构规模、效率和风险", "仅基于当前筛选和重新执行的证据形成督导结论"],
      },
    });
    replaceVisualAnalysisSourceGroup("supervision", "page-data", pageData.visibleAssets.map((asset) => ({
      id: asset.id,
      label: asset.name,
      tables: [pageDataToSelection(asset) as unknown as Record<string, unknown>],
      question: asset.name,
      summary: asset.sourceTableName || asset.name,
      rows: boundedVisualRows(pageData.rowsById[asset.id]?.rows),
    })));
  }, [model.branches.length, pageData.rowsById, pageData.visibleAssets, productFilter, selected, selectedBranch, snapshot]);
  const runSupervisionAction = (action: string, payload: Record<string, unknown> = {}) =>
    runApplicationAction({ tenantId, userId, moduleKey: "institution_supervision", action, payload }).catch(() => undefined);

  if (pageData.loading && !pageData.assets.length) {
    return <div className={PAGE_DATA_PAGE_GUTTER_CLASS}><SupervisionHeader controller={pageData} canEditLayout={isSuperAdmin} stickyNote={stickyNote} /><SupervisionState message="正在读取机构督导页面数据…" embedded /></div>;
  }

  return <div className={PAGE_DATA_PAGE_GUTTER_CLASS}>
    <SupervisionHeader controller={pageData} canEditLayout={isSuperAdmin} stickyNote={stickyNote} />
    <StandardAnalysisPageStickyNote stickyNote={stickyNote} />
    {(pageData.hasSelectedPageData || pageData.mode === "edit") && <PageDataVisualizationModules controller={pageData} showEditorControls={isSuperAdmin} layoutEditable={isSuperAdmin} showAssetPicker />}
    {pageData.waitingForPageDataRows && !pageData.hasSelectedPageData ? <SupervisionState message="正在读取机构督导页面数据…" embedded /> : null}
    {!pageData.loading && !pageData.waitingForPageDataRows && !pageData.hasSelectedPageData && <SupervisionState message={pageData.notice || notice || "请先在站内数据的「单机构页面」中把数据集放到机构督导。"} embedded />}
  </div>;
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
function snapshotEvidenceRefs(snapshot: OperatingSnapshot) { return Object.entries(snapshot.datasets).flatMap(([key, dataset]) => dataset.evidence.evidence_id ? [{ id: dataset.evidence.evidence_id, type: "operating_snapshot", label: key }] : []); }
function snapshotDatasetSnapshot(snapshot: OperatingSnapshot) { return { id: snapshot.view, version: snapshot.generated_at, generatedAt: snapshot.generated_at }; }
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

function SupervisionHeader({ controller, canEditLayout, stickyNote }: { controller: PageDataComposerController; canEditLayout: boolean; stickyNote: ReturnType<typeof useStickyNote> }) {
  return <StandardAnalysisPageHeader title="机构督导" description="展示站内数据「单机构页面」中放到机构督导的数据集" stickyNote={stickyNote} editController={controller} canEditLayout={canEditLayout} headerDataAttribute="institution-supervision" />;
}

function SupervisionState({ message, embedded = false }: { message: string; embedded?: boolean }) {
  return <div className={embedded ? "min-w-0" : PAGE_DATA_PAGE_GUTTER_CLASS}>{!embedded && <><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">机构督导</h2><p className="text-[13px] text-[#aeaeb2] mt-1">分行 × 产品矩阵分析 · 消费贷/经营贷分维度督导</p></>}<div className={`${embedded ? "mt-0" : "mt-6"} w-full rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]`}>{message}</div></div>;
}
