import { useEffect, useMemo, useState } from "react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from "recharts";
import {
  TrendingUp, TrendingDown, Sparkles, ShieldAlert, ArrowUpRight,
  Building2, Users, Banknote, CreditCard, Landmark,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { runApplicationAction } from "../services/applicationApi";
import { apiErrorMessage } from "../services/apiClient";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";
import { AnalysisUnderlineProvider, SelectableRegion } from "./weekly-report/SelectableRegion";
import { WeeklyReportSideRail } from "./weekly-report/WeeklyReportSideRail";
import { useInstitutionCommentThread } from "./context-rail/useInstitutionCommentThread";
import { revealContextRail } from "./context-rail/ContextSideRail";
import { replaceVisualAnalysisSourceGroup, updateAnalysisWorkspacePageContext } from "./analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "./analysis-workspace/visualAnalysisScope";
import { pageDataToSelection } from "./self-analysis/domain";
import { makeAnalysisSelectionTarget, makeTextBlock, summarizeContextValue, type CommentTarget, type WeeklyInstitutionReport } from "./weekly-report/domain";
import { PAGE_DATA_PAGE_GUTTER_CLASS, PageDataModeToggle, PageDataVisualizationModules, usePageDataComposer, type PageDataComposerController } from "./page-data/PageDataComposer";
import { StickyNoteButton, StickyNotePanel } from "./notes/StickyNote";
import { useStickyNote } from "./notes/useStickyNote";

type Product = "all" | "consumer" | "business";

export function Dashboard() {
  const { tenantId, userId, userName, selectedInstitution, isSuperAdmin } = usePlatformContext();
  const [selectedProduct, setSelectedProduct] = useState<Product>("all");
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [rightRailTab, setRightRailTab] = useState<"comments" | "analysis" | "message-board">("analysis");
  const [selectedContextTarget, setSelectedContextTarget] = useState<CommentTarget | null>(null);
  const [analysisTarget, setAnalysisTarget] = useState<CommentTarget | null>(null);
  const [analysisSelectionTargets, setAnalysisSelectionTargets] = useState<CommentTarget[]>([]);
  const [draftTargets, setDraftTargets] = useState<CommentTarget[]>([]);
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [expandedReplyInputs, setExpandedReplyInputs] = useState<Record<string, boolean>>({});
  const [expandedCommentReplies, setExpandedCommentReplies] = useState<Record<string, boolean>>({});
  const [activeCommentId, setActiveCommentId] = useState<string | null>(null);
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const pageData = usePageDataComposer({ pageCode: "dashboard", moduleKey: "dashboard", railPageKey: "multi-institution-analysis" });
  const stickyNote = useStickyNote("dashboard", "dashboard");

  useEffect(() => {
    if (!isSuperAdmin) pageData.setMode("browse");
  }, [isSuperAdmin, pageData.setMode]);
  const dashboardReportId = `multi_institution_${tenantId}`;
  const { comments, createComment, replyToComment, resolveComment } = useInstitutionCommentThread({
    tenantId,
    userId,
    userName,
    reportId: dashboardReportId,
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOperatingSnapshot({ tenantId, userId, view: "dashboard" })
      .then((result) => {
        if (!cancelled) {
          setSnapshot(result);
          setNotice("");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSnapshot(null);
          setNotice(apiErrorMessage(error, "多机构分析数据加载失败。"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  useEffect(() => {
    updateAnalysisWorkspacePageContext("multi-institution-analysis", {
      workspace_key: `multi-institution-analysis:${tenantId}`,
      artifact_id: dashboardReportId,
      filters: { institution: selectedInstitution },
      selected_content: pageData.visibleAssets.map((asset) => asset.name).join("、"),
      visualization: {
        asset_ids: pageData.visibleAssets.map((asset) => asset.id),
        visualization_types: pageData.visualTypes,
      },
    });
    replaceVisualAnalysisSourceGroup("multi-institution-analysis", "page-data", pageData.visibleAssets.map((asset) => ({
      id: asset.id,
      label: asset.name,
      tables: [pageDataToSelection(asset) as unknown as Record<string, unknown>],
      question: asset.name,
      summary: asset.sourceTableName || asset.name,
      rows: boundedVisualRows(pageData.rowsById[asset.id]?.rows),
    })));
  }, [dashboardReportId, pageData.rowsById, pageData.visibleAssets, pageData.visualTypes, selectedInstitution, tenantId]);

  useEffect(() => {
    setAnalysisTarget(null);
    setAnalysisSelectionTargets([]);
    setSelectedContextTarget(null);
    setDraftTargets([]);
    setCommentDrafts({});
    setReplyDrafts({});
    setExpandedReplyInputs({});
    setExpandedCommentReplies({});
    setActiveCommentId(null);
    setActiveDraftId(null);
  }, [tenantId, userId]);

  const dashboardModel = useMemo(() => buildDashboardModel(snapshot), [snapshot]);
  const { productKpis, consumerRisk, businessRisk, bankProductData, dualTrend, radarData, insights } = dashboardModel;
  if (!dashboardModel.hasData) {
    void [productKpis, consumerRisk, businessRisk, insights, radarData];
  }

  const runDashboardAction = (action: string, payload: Record<string, unknown> = {}) =>
    runApplicationAction({ tenantId, userId, moduleKey: "dashboard", action, payload }).catch(() => undefined);

  const dashboardReport = useMemo<WeeklyInstitutionReport>(() => ({
    id: dashboardReportId,
    institutionName: selectedInstitution,
    projectNo: "multi-institution-analysis",
    meetingTime: snapshot?.generated_at || "",
    reporters: userName,
    period: snapshot?.generated_at || "当前快照",
    status: "已编辑",
    owner: userId,
    sections: [{
      id: "dashboard_page",
      name: "多机构分析",
      blocks: [makeTextBlock("dashboard_snapshot", "多机构分析页面及关联指标数据", JSON.stringify({ selectedProduct, snapshot, dashboardModel }))],
    }],
  }), [dashboardModel, dashboardReportId, selectedInstitution, selectedProduct, snapshot, userId, userName]);

  const contextTarget = (id: string, label: string, type: CommentTarget["type"], selectedText: string): CommentTarget => ({
    id: `dashboard:${id}`,
    label,
    type,
    targetKind: type === "文本" ? "paragraph" : type === "图表" ? "chart" : "table",
    selectedText,
    blockId: "dashboard_snapshot",
  });

  const openDashboardComment = (target: CommentTarget) => {
    revealContextRail("multi-institution-analysis", "comments");
    setRightRailTab("comments");
    setSelectedContextTarget(target);
    setDraftTargets((current) => current.some((item) => item.id === target.id) ? current : [target, ...current]);
    setCommentDrafts((current) => ({ ...current, [target.id]: current[target.id] || "" }));
    setActiveDraftId(target.id);
    setActiveCommentId(null);
  };
  const openDashboardAnalysis = (target: CommentTarget) => {
    revealContextRail("multi-institution-analysis", "analysis");
    const analysisSelectionTarget = makeAnalysisSelectionTarget(target);
    if (analysisSelectionTarget.selectedText?.trim() && typeof analysisSelectionTarget.rangeStart === "number" && typeof analysisSelectionTarget.rangeEnd === "number") {
      setAnalysisSelectionTargets((current) => [analysisSelectionTarget, ...current.filter((item) => item.id !== analysisSelectionTarget.id)]);
    }
    setSelectedContextTarget(analysisSelectionTarget);
    setAnalysisTarget(analysisSelectionTarget);
    setRightRailTab("analysis");
  };
  const activateDashboardAnalysis = (target: CommentTarget, rect: DOMRect) => {
    revealContextRail("multi-institution-analysis", "analysis");
    const pageBody = document.querySelector<HTMLElement>("[data-context-page-body=\"multi-institution-analysis\"]");
    const bodyRect = pageBody?.getBoundingClientRect();
    const nextTarget = {
      ...target,
      anchorTop: bodyRect ? Math.max(12, rect.top - bodyRect.top) : target.anchorTop,
      anchorViewportTop: rect.top,
    };
    setAnalysisSelectionTargets((current) => [nextTarget, ...current.filter((item) => item.id !== nextTarget.id)]);
    setSelectedContextTarget(nextTarget);
    setAnalysisTarget(nextTarget);
    setRightRailTab("analysis");
    setActiveCommentId(null);
    setActiveDraftId(null);
  };
  const dashboardCommentAnnotations = useMemo<CommentTarget[]>(() => [
    ...draftTargets
      .filter((target) => target.selectedText?.trim() && typeof target.rangeStart === "number" && typeof target.rangeEnd === "number")
      .map((target) => ({ ...target, contextTargetId: target.contextTargetId || target.id, annotationKind: "comment" as const })),
    ...comments
      .filter((comment) => comment.status === "open" && comment.selectedText?.trim() && typeof comment.rangeStart === "number" && typeof comment.rangeEnd === "number")
      .map((comment) => ({
        id: comment.id,
        contextTargetId: comment.targetId,
        label: comment.targetLabel,
        type: comment.targetKind === "chart" ? "图表" as const : comment.targetKind === "paragraph" ? "文本" as const : "数据" as const,
        targetKind: comment.targetKind || "paragraph",
        selectedText: comment.selectedText,
        blockId: comment.blockId,
        itemId: comment.itemId,
        rangeStart: comment.rangeStart,
        rangeEnd: comment.rangeEnd,
        anchorTop: comment.anchorTop,
        annotationKind: "comment" as const,
      })),
  ], [comments, draftTargets]);
  const activateDashboardAnnotation = (target: CommentTarget, rect: DOMRect) => {
    if (target.annotationKind !== "comment") {
      activateDashboardAnalysis(target, rect);
      return;
    }
    revealContextRail("multi-institution-analysis", "comments");
    setRightRailTab("comments");
    setSelectedContextTarget(target);
    const isDraft = draftTargets.some((draft) => draft.id === target.id);
    setActiveDraftId(isDraft ? target.id : null);
    setActiveCommentId(isDraft ? null : target.id);
  };
  const saveDashboardComment = (targetId: string) => {
    const target = draftTargets.find((item) => item.id === targetId);
    const text = commentDrafts[targetId]?.trim();
    if (!target || !text) return;
    const pendingId = createComment(target, text);
    setDraftTargets((current) => current.filter((item) => item.id !== targetId));
    setCommentDrafts((current) => ({ ...current, [targetId]: "" }));
    setActiveDraftId(null);
    setActiveCommentId(pendingId || null);
  };
  const saveDashboardReply = (commentId: string) => {
    const text = replyDrafts[commentId]?.trim();
    if (!text) return;
    replyToComment(commentId, text);
    setReplyDrafts((current) => ({ ...current, [commentId]: "" }));
    setExpandedReplyInputs((current) => ({ ...current, [commentId]: false }));
  };

  const dashboardSideRail = (
    <WeeklyReportSideRail
      pageKey="multi-institution-analysis"
      pageTitle="多机构分析"
      overallPrompt="结合当前多机构分析页面和关联指标数据，比较各机构消费贷与经营贷的规模、趋势、效率和风险，给出关键差异与行动建议。"
      activeTab={rightRailTab}
      onTabChange={setRightRailTab}
      commentCount={comments.filter((comment) => comment.status === "open").length}
      railHeight={720}
      focusTargetId={selectedContextTarget?.id}
      focusTarget={rightRailTab === "analysis" || rightRailTab === "message-board" ? selectedContextTarget : null}
      onAnalysisTargetActivate={setSelectedContextTarget}
      onAnalysisTargetDismiss={(target) => {
        setAnalysisTarget((current) => current?.id === target.id ? null : current);
        setSelectedContextTarget((current) => current?.id === target.id ? null : current);
        setAnalysisSelectionTargets((current) => current.filter((item) => item.id !== target.id));
      }}
      commentsProps={{
        selectedTarget: selectedContextTarget,
        draftTargets,
        commentDrafts,
        onDraftChange: (targetId, value) => setCommentDrafts((current) => ({ ...current, [targetId]: value })),
        comments: comments.filter((comment) => comment.status === "open"),
        replyDrafts,
        expandedReplyInputs,
        expandedCommentReplies,
        highlightedCommentId: activeCommentId,
        activeCommentId,
        activeDraftId,
        railHeight: 720,
        onSave: saveDashboardComment,
        onCommentActivate: (commentId) => { setActiveCommentId(commentId); setActiveDraftId(null); },
        onResolveComment: (commentId) => resolveComment(commentId),
        onReplyDraftChange: (commentId, value) => setReplyDrafts((current) => ({ ...current, [commentId]: value })),
        onReplyToggle: (commentId, expanded) => setExpandedReplyInputs((current) => ({ ...current, [commentId]: expanded })),
        onReplySave: saveDashboardReply,
        onCommentRepliesToggle: (commentId, expanded) => setExpandedCommentReplies((current) => ({ ...current, [commentId]: expanded })),
      }}
      analysisProps={{
        report: dashboardReport,
        target: analysisTarget,
        tenantId,
        userId,
        selectedInstitution,
        topicTable: null,
        analysisSkill: null,
        memoryIds: [],
        railHeight: 720,
        noDataMessage: "本页面没有找到这一数据，请检查要分析的内容",
      }}
    />
  );

  if (pageData.loading && !pageData.assets.length) {
    return <div className={PAGE_DATA_PAGE_GUTTER_CLASS}><DashboardPageHeader controller={pageData} snapshot={snapshot} canEditLayout={isSuperAdmin} stickyNote={stickyNote} /><DashboardState message="正在读取多机构页面数据…" embedded /></div>;
  }

  return <div className={PAGE_DATA_PAGE_GUTTER_CLASS}>
    <DashboardPageHeader controller={pageData} snapshot={snapshot} canEditLayout={isSuperAdmin} stickyNote={stickyNote} />
    <StickyNotePanel className="mb-4" note={stickyNote.note} editing={stickyNote.editing} onChange={stickyNote.updateItems} onFinishEdit={stickyNote.finishEdit} onStartEdit={() => stickyNote.setEditing(true)} onHide={stickyNote.hide} uploadContext={stickyNote.uploadContext} />
    {pageData.visibleAssets.length > 0 && <PageDataVisualizationModules controller={pageData} showEditorControls={isSuperAdmin} layoutEditable={isSuperAdmin} showAssetPicker />}
    {!pageData.loading && pageData.visibleAssets.length === 0 && <DashboardState message={notice || "请先在数据管理的「多机构页面」中配置要展示的数据。"} embedded />}
  </div>;
}

type DashboardBankRow = {
  bank: string;
  cLoan?: number;
  cDrawdown?: number;
  cM1?: number;
  cBalance?: number;
  bLoan?: number;
  bDrawdown?: number;
  bM1?: number;
  bBalance?: number;
};

function buildDashboardModel(snapshot: OperatingSnapshot | null) {
  const datasetRows = (key: string) => {
    const rows = snapshot?.datasets[key]?.status === "ready" ? snapshot.datasets[key].rows : [];
    return rows;
  };
  const loanRows = datasetRows("loan_operation");
  const riskRows = datasetRows("risk_operation");
  const loanTrendRows = datasetRows("loan_product_trend");
  const riskTrendRows = datasetRows("risk_product_trend");
  const customerTrendRows = datasetRows("customer_product_trend");
  const products = { consumer: "消费贷", business: "经营贷" } as const;

  const productKpis = Object.fromEntries(
    Object.entries(products).map(([key, label]) => {
      const loanSeries = seriesFor(loanTrendRows, label);
      const riskSeries = seriesFor(riskTrendRows, label);
      const customerSeries = seriesFor(customerTrendRows, label);
      const loan = last(loanSeries);
      const priorLoan = previous(loanSeries);
      const risk = last(riskSeries);
      const priorRisk = previous(riskSeries);
      const customer = last(customerSeries);
      const priorCustomer = previous(customerSeries);
      const loanAmount = numberValue(loan?.loan_amount);
      const activeCustomers = numberValue(customer?.active_customer_count);
      return [
        key,
        {
          label,
          icon: key === "consumer" ? CreditCard : Landmark,
          kpis: [
            metricKpi("放款金额(亿)", loanAmount / 1e8, numberValue(priorLoan?.loan_amount) / 1e8),
            metricKpi("在贷余额(亿)", numberValue(risk?.loan_balance) / 1e8, numberValue(priorRisk?.loan_balance) / 1e8),
            metricKpi("活跃客户(万)", activeCustomers / 1e4, numberValue(priorCustomer?.active_customer_count) / 1e4),
            metricKpi("笔均放款(万)", activeCustomers > 0 ? loanAmount / activeCustomers / 1e4 : undefined, undefined),
            rateKpi("动支率", numberValue(loan?.drawdown_rate), numberValue(priorLoan?.drawdown_rate), true),
            rateKpi("M1逾期率", numberValue(risk?.m1_overdue_rate), numberValue(priorRisk?.m1_overdue_rate), false),
          ],
        },
      ];
    }),
  ) as Record<"consumer" | "business", { label: string; icon: typeof CreditCard; kpis: ReturnType<typeof metricKpi>[] }>;

  const consumerRisk = riskCards(riskTrendRows, "消费贷");
  const businessRisk = riskCards(riskTrendRows, "经营贷");
  const banks = Array.from(new Set(loanRows.map((row) => String(row.branch_name || "")).filter(Boolean))).sort();
  const bankProductData = banks.map((bank) => {
    const consumerLoan = latestMatching(loanRows, bank, "消费贷");
    const businessLoan = latestMatching(loanRows, bank, "经营贷");
    const consumerRiskRow = latestMatching(riskRows, bank, "消费贷");
    const businessRiskRow = latestMatching(riskRows, bank, "经营贷");
    return {
      bank,
      cLoan: optionalScaled(consumerLoan?.loan_amount, 1e8),
      cDrawdown: optionalPercent(consumerLoan?.drawdown_rate),
      cM1: optionalPercent(consumerRiskRow?.m1_overdue_rate),
      cBalance: optionalScaled(consumerRiskRow?.loan_balance, 1e8),
      bLoan: optionalScaled(businessLoan?.loan_amount, 1e8),
      bDrawdown: optionalPercent(businessLoan?.drawdown_rate),
      bM1: optionalPercent(businessRiskRow?.m1_overdue_rate),
      bBalance: optionalScaled(businessRiskRow?.loan_balance, 1e8),
    };
  });
  const months = Array.from(new Set(loanTrendRows.map((row) => String(row.month || "")).filter(Boolean))).sort();
  const dualTrend = months.map((month) => ({
    month,
    消费贷放款: optionalScaled(loanTrendRows.find((row) => row.month === month && row.product_line === "消费贷")?.loan_amount, 1e8) || 0,
    经营贷放款: optionalScaled(loanTrendRows.find((row) => row.month === month && row.product_line === "经营贷")?.loan_amount, 1e8) || 0,
  }));
  const latestByProduct = (rows: Record<string, unknown>[], product: string) => last(seriesFor(rows, product));
  const consumerScores = {
    loan: numberValue(latestByProduct(loanTrendRows, "消费贷")?.loan_amount),
    drawdown: numberValue(latestByProduct(loanTrendRows, "消费贷")?.drawdown_rate),
    customers: numberValue(latestByProduct(customerTrendRows, "消费贷")?.active_customer_count),
    quality: Math.max(0, 1 - numberValue(latestByProduct(riskTrendRows, "消费贷")?.m1_overdue_rate)),
    conversion: numberValue(latestByProduct(customerTrendRows, "消费贷")?.conversion_rate),
  };
  const businessScores = {
    loan: numberValue(latestByProduct(loanTrendRows, "经营贷")?.loan_amount),
    drawdown: numberValue(latestByProduct(loanTrendRows, "经营贷")?.drawdown_rate),
    customers: numberValue(latestByProduct(customerTrendRows, "经营贷")?.active_customer_count),
    quality: Math.max(0, 1 - numberValue(latestByProduct(riskTrendRows, "经营贷")?.m1_overdue_rate)),
    conversion: numberValue(latestByProduct(customerTrendRows, "经营贷")?.conversion_rate),
  };
  const radarData = [
    radarRow("放款规模", consumerScores.loan, businessScores.loan),
    radarRow("动支效率", consumerScores.drawdown, businessScores.drawdown),
    radarRow("活跃客户", consumerScores.customers, businessScores.customers),
    radarRow("资产质量", consumerScores.quality, businessScores.quality),
    radarRow("转化效率", consumerScores.conversion, businessScores.conversion),
  ];
  const insights = {
    consumer: evidenceInsights("消费贷", loanTrendRows, riskTrendRows, bankProductData, "cLoan", "cM1", "cDrawdown"),
    business: evidenceInsights("经营贷", loanTrendRows, riskTrendRows, bankProductData, "bLoan", "bM1", "bDrawdown"),
  };
  return {
    hasData: loanRows.length > 0 || riskRows.length > 0,
    banks,
    productKpis,
    consumerRisk,
    businessRisk,
    bankProductData,
    dualTrend,
    radarData,
    insights,
  };
}

function dashboardReadableCommentSummaries(p: { kpis: unknown }, dualTrend: unknown, bankProductData: unknown) {
  return [summarizeContextValue(p.kpis), summarizeContextValue(dualTrend), summarizeContextValue(bankProductData)].join(" ");
}

function DashboardPageHeader({ controller, snapshot, canEditLayout, stickyNote }: { controller: PageDataComposerController; snapshot: OperatingSnapshot | null; canEditLayout: boolean; stickyNote: ReturnType<typeof useStickyNote> }) {
  return <div className="mb-6 flex items-start justify-between gap-3"><div><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">多机构分析</h2><p className="mt-1 text-[13px] text-[#aeaeb2]">展示数据管理「多机构页面」中配置的数据集{snapshot?.generated_at ? ` · 快照 ${formatTimestamp(snapshot.generated_at)}` : ""}</p></div><div className="flex items-center gap-2"><StickyNoteButton onClick={stickyNote.show} />{canEditLayout && <PageDataModeToggle controller={controller} />}</div></div>;
}

function DashboardState({ message, embedded = false }: { message: string; embedded?: boolean }) {
  return (
    <div className={embedded ? "min-w-0" : "p-7"}>
      {!embedded && <><h2 className="text-[18px] text-[#1d1d1f] tracking-tight">多机构分析</h2><p className="text-[13px] text-[#aeaeb2] mt-1">消费贷 + 经营贷 双产品经营全景</p></>}
      <div className={`${embedded ? "mt-0" : "mt-6"} w-full rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]`}>{message}</div>
    </div>
  );
}

function seriesFor(rows: Record<string, unknown>[], product: string) {
  return rows.filter((row) => row.product_line === product).slice().sort((left, right) => String(left.month || "").localeCompare(String(right.month || "")));
}
function last<T>(items: T[]) { return items.length ? items[items.length - 1] : undefined; }
function previous<T>(items: T[]) { return items.length > 1 ? items[items.length - 2] : undefined; }
function numberValue(value: unknown) { const numeric = Number(value); return Number.isFinite(numeric) ? numeric : 0; }
function optionalScaled(value: unknown, scale: number) { const numeric = Number(value); return Number.isFinite(numeric) ? numeric / scale : undefined; }
function optionalPercent(value: unknown) { const numeric = Number(value); return Number.isFinite(numeric) ? numeric * 100 : undefined; }
function formatNumber(value?: number) { return value === undefined ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 }); }
function formatPercent(value?: number) { return value === undefined ? "—" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`; }
function formatTimestamp(value?: string) { if (!value) return "—"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false }); }

function metricKpi(label: string, value?: number, prior?: number) {
  const change = value !== undefined && prior !== undefined && prior !== 0 ? ((value - prior) / Math.abs(prior)) * 100 : undefined;
  return { label, value: formatNumber(value), change: change === undefined ? "暂无可比期" : `${change >= 0 ? "+" : ""}${change.toFixed(1)}%`, positive: change === undefined || change >= 0 };
}

function rateKpi(label: string, value: number, prior: number, higherBetter: boolean) {
  const change = prior ? (value - prior) * 100 : undefined;
  return { label, value: formatPercent(value * 100), change: change === undefined ? "暂无可比期" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}pp`, positive: change === undefined || (higherBetter ? change >= 0 : change <= 0) };
}

function riskCards(rows: Record<string, unknown>[], product: string) {
  const series = seriesFor(rows, product);
  const current = last(series);
  const prior = previous(series);
  const rate = numberValue(current?.m1_overdue_rate);
  const priorRate = numberValue(prior?.m1_overdue_rate);
  const rateChange = prior ? (rate - priorRate) * 100 : undefined;
  const balance = optionalScaled(current?.loan_balance, 1e8);
  const priorBalance = optionalScaled(prior?.loan_balance, 1e8);
  const balanceChange = balance !== undefined && priorBalance ? ((balance - priorBalance) / priorBalance) * 100 : undefined;
  return [
    { label: "M1逾期率", value: formatPercent(rate * 100), change: rateChange === undefined ? "暂无可比期" : `${rateChange >= 0 ? "+" : ""}${rateChange.toFixed(2)}pp`, positive: rateChange === undefined || rateChange <= 0, threshold: "未配置" },
    { label: "在贷余额", value: balance === undefined ? "—" : `${formatNumber(balance)}亿`, change: balanceChange === undefined ? "暂无可比期" : `${balanceChange >= 0 ? "+" : ""}${balanceChange.toFixed(1)}%`, positive: true, threshold: "信息指标" },
  ];
}

function latestMatching(rows: Record<string, unknown>[], branch: string, product: string) {
  return last(rows.filter((row) => row.branch_name === branch && row.product_line === product).slice().sort((left, right) => String(left.month || "").localeCompare(String(right.month || ""))));
}

function radarRow(metric: string, consumer: number, business: number) {
  const max = Math.max(consumer, business);
  return { metric, 消费贷: max > 0 ? Math.round((consumer / max) * 100) : 0, 经营贷: max > 0 ? Math.round((business / max) * 100) : 0 };
}

function evidenceInsights(
  product: string,
  loanRows: Record<string, unknown>[],
  riskRows: Record<string, unknown>[],
  branchRows: DashboardBankRow[],
  loanKey: "cLoan" | "bLoan",
  m1Key: "cM1" | "bM1",
  drawdownKey: "cDrawdown" | "bDrawdown",
) {
  const loanSeries = seriesFor(loanRows, product);
  const riskSeries = seriesFor(riskRows, product);
  const currentLoan = last(loanSeries);
  const priorLoan = previous(loanSeries);
  const currentRisk = last(riskSeries);
  const change = priorLoan && numberValue(priorLoan.loan_amount) !== 0
    ? ((numberValue(currentLoan?.loan_amount) - numberValue(priorLoan.loan_amount)) / Math.abs(numberValue(priorLoan.loan_amount))) * 100
    : undefined;
  const top = branchRows.filter((row) => row[loanKey] !== undefined).sort((left, right) => numberValue(right[loanKey]) - numberValue(left[loanKey]))[0];
  return [
    `${String(currentLoan?.month || "当前期")}放款 ${formatNumber(optionalScaled(currentLoan?.loan_amount, 1e8))} 亿元${change === undefined ? "，暂无可比期" : `，较上一期${change >= 0 ? "增长" : "下降"}${Math.abs(change).toFixed(1)}%`}`,
    `当前动支率 ${formatPercent(optionalPercent(currentLoan?.drawdown_rate))}，M1逾期率 ${formatPercent(optionalPercent(currentRisk?.m1_overdue_rate))}`,
    top ? `当前有数据机构中，${top.bank}放款金额最高（${formatNumber(top[loanKey])}亿元），动支率 ${formatPercent(top[drawdownKey])}，M1 ${formatPercent(top[m1Key])}` : "暂无机构级可比数据",
  ];
}
