import { useEffect, useMemo, useState } from "react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from "recharts";
import {
  TrendingUp, TrendingDown, Sparkles, ShieldAlert, ArrowUpRight,
  Building2, ChevronDown, Users, Banknote, CreditCard, Landmark,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { runApplicationAction } from "../services/applicationApi";
import { apiErrorMessage } from "../services/apiClient";
import { fetchOperatingSnapshot, type OperatingSnapshot } from "../services/operatingSnapshotApi";
import { AnalysisUnderlineProvider, SelectableRegion } from "./weekly-report/SelectableRegion";
import { WeeklyReportSideRail } from "./weekly-report/WeeklyReportSideRail";
import { useInstitutionCommentThread } from "./context-rail/useInstitutionCommentThread";
import { revealContextRail } from "./context-rail/ContextSideRail";
import { makeAnalysisSelectionTarget, makeTextBlock, summarizeContextValue, type CommentTarget, type WeeklyInstitutionReport } from "./weekly-report/domain";

type Product = "all" | "consumer" | "business";

export function Dashboard() {
  const { tenantId, userId, userName, selectedInstitution } = usePlatformContext();
  const [selectedProduct, setSelectedProduct] = useState<Product>("all");
  const [selectedBank, setSelectedBank] = useState("全部分行");
  const [snapshot, setSnapshot] = useState<OperatingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [rightRailTab, setRightRailTab] = useState<"comments" | "analysis">("analysis");
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
    fetchOperatingSnapshot({
      tenantId,
      userId,
      view: "dashboard",
      filters: selectedBank === "全部分行" ? {} : { branch_name: selectedBank },
    })
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
  }, [selectedBank, tenantId, userId]);

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
  }, [selectedBank, tenantId, userId]);

  const dashboardModel = useMemo(() => buildDashboardModel(snapshot), [snapshot]);
  const { banks, productKpis, consumerRisk, businessRisk, bankProductData, dualTrend, radarData, insights } = dashboardModel;

  const runDashboardAction = (action: string, payload: Record<string, unknown> = {}) =>
    runApplicationAction({ tenantId, userId, moduleKey: "dashboard", action, payload }).catch(() => undefined);

  const dashboardReport = useMemo<WeeklyInstitutionReport>(() => ({
    id: dashboardReportId,
    institutionName: selectedInstitution,
    projectNo: "multi-institution-analysis",
    meetingTime: snapshot?.generated_at || "",
    reporters: userId,
    period: snapshot?.generated_at || "当前快照",
    status: "已编辑",
    owner: userId,
    sections: [{
      id: "dashboard_page",
      name: "多机构分析",
      blocks: [makeTextBlock("dashboard_snapshot", "多机构分析页面及关联指标数据", JSON.stringify({ selectedBank, selectedProduct, snapshot, dashboardModel }))],
    }],
  }), [dashboardModel, dashboardReportId, selectedBank, selectedInstitution, selectedProduct, snapshot, userId]);

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

  if (loading && !snapshot) {
    return <DashboardState message="正在读取受治理经营数据…" />;
  }

  if (!dashboardModel.hasData) {
    return <DashboardState message={notice || "当前租户没有可用于多机构分析的授权经营数据，页面不会显示内置数字。"} />;
  }

  return (
    <div className="p-7">
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_auto]">
      <AnalysisUnderlineProvider
        targets={[...dashboardCommentAnnotations, ...analysisSelectionTargets]}
        activeTargetId={rightRailTab === "analysis" ? selectedContextTarget?.id : activeDraftId || activeCommentId || undefined}
        onActivate={activateDashboardAnnotation}
      >
      <main className="min-w-0" data-multi-institution-content="true" data-context-page-body="multi-institution-analysis">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">多机构分析</h2>
          <p className="text-[13px] text-[#aeaeb2] mt-1">消费贷 + 经营贷 双产品经营全景 · 快照 {formatTimestamp(snapshot?.generated_at)}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <select
              value={selectedBank}
              onChange={(e) => {
                setSelectedBank(e.target.value);
                void runDashboardAction("select_bank", { selectedBank: e.target.value, selectedProduct });
              }}
              className="appearance-none pl-8 pr-7 py-[6px] bg-white border border-[#e5e5ea] rounded-lg text-[12px] text-[#636366] focus:outline-none cursor-pointer">
              <option>全部分行</option>
              {banks.map((b) => (<option key={b}>{b}</option>))}
            </select>
            <Building2 className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#c7c7cc]" />
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[#c7c7cc] pointer-events-none" />
          </div>
        </div>
      </div>

      {(notice || !snapshot?.publishable) && (
        <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">
          {notice || `当前数据模式：${snapshot?.data_modes.join("、") || "未知"}。该快照可用于功能验证，但不可作为正式报告发布证据。`}
        </div>
      )}

      {/* 双产品KPI卡片 - 左右对比 */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        {(["consumer", "business"] as const).map((pKey) => {
          const p = productKpis[pKey];
          const target = contextTarget(`${pKey}-kpis`, `${p.label}核心指标`, "数据", summarizeContextValue(p.kpis));
          return (
            <SelectableRegion key={pKey} target={target} selectedTargetId={selectedContextTarget?.id} onSelect={setSelectedContextTarget} onOpenComment={openDashboardComment} onOpenAnalysis={openDashboardAnalysis}>
            <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
              <div className="flex items-center gap-2 mb-4">
                <p.icon className="w-4 h-4 text-[#8a8a8e]" />
                <span className="text-[13px] text-[#1d1d1f]">{p.label}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ml-1 ${pKey === "consumer" ? "bg-[#3a3a3c]/6 text-[#3a3a3c]" : "bg-[#8e8e93]/10 text-[#636366]"}`}>
                  {pKey === "consumer" ? "个人信用" : "企业经营"}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3">
                {p.kpis.map((kpi) => (
                  <div key={kpi.label} className="p-3 bg-[#fafbfc] rounded-lg">
                    <div className="text-[11px] text-[#aeaeb2]">{kpi.label}</div>
                    <div className="text-[18px] text-[#1d1d1f] mt-1 tracking-tight">{kpi.value}</div>
                    <span className={`text-[11px] flex items-center gap-0.5 mt-0.5 ${kpi.positive ? "text-[#34a853]" : "text-[#ea4335]"}`}>
                      {kpi.positive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                      {kpi.change}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            </SelectableRegion>
          );
        })}
      </div>

      {/* 经营趋势 + 产品结构对比 */}
      <div className="grid grid-cols-3 gap-5 mb-6">
        <SelectableRegion className="col-span-2" target={contextTarget("loan-trend", "双产品放款趋势", "图表", summarizeContextValue(dualTrend))} selectedTargetId={selectedContextTarget?.id} onSelect={setSelectedContextTarget} onOpenComment={openDashboardComment} onOpenAnalysis={openDashboardAnalysis}>
        <div className="col-span-2 bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-[13px] text-[#1d1d1f]">双产品放款趋势</h3>
            <div className="flex gap-3 text-[11px] text-[#aeaeb2]">
              <span className="flex items-center gap-1"><span className="w-3 h-px bg-[#3a3a3c] inline-block" /> 消费贷</span>
              <span className="flex items-center gap-1"><span className="w-3 h-px bg-[#aeaeb2] inline-block" style={{ borderTop: "1px dashed #aeaeb2", height: 0 }} /> 经营贷</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={dualTrend}>
              <defs>
                <linearGradient id="gConsumer" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3a3a3c" stopOpacity={0.06} />
                  <stop offset="100%" stopColor="#3a3a3c" stopOpacity={0.01} />
                </linearGradient>
                <linearGradient id="gBusiness" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#aeaeb2" stopOpacity={0.06} />
                  <stop offset="100%" stopColor="#aeaeb2" stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f5f5f5" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #f0f0f2" }} />
              <Area type="monotone" dataKey="消费贷放款" stroke="#3a3a3c" fill="url(#gConsumer)" strokeWidth={1.5} />
              <Area type="monotone" dataKey="经营贷放款" stroke="#aeaeb2" fill="url(#gBusiness)" strokeWidth={1.5} strokeDasharray="5 3" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        </SelectableRegion>

        <SelectableRegion target={contextTarget("product-radar", "产品竞争力对比", "图表", summarizeContextValue(radarData))} selectedTargetId={selectedContextTarget?.id} onSelect={setSelectedContextTarget} onOpenComment={openDashboardComment} onOpenAnalysis={openDashboardAnalysis}>
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <h3 className="text-[13px] text-[#1d1d1f] mb-1">产品竞争力对比</h3>
          <p className="text-[11px] text-[#c7c7cc] mb-2">按当前证据做相对归一对比</p>
          <ResponsiveContainer width="100%" height={220}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="#f0f0f2" />
              <PolarAngleAxis dataKey="metric" tick={{ fontSize: 10, fill: "#aeaeb2" }} />
              <PolarRadiusAxis tick={false} axisLine={false} />
              <Radar name="消费贷" dataKey="消费贷" stroke="#3a3a3c" fill="#3a3a3c" fillOpacity={0.06} strokeWidth={1.5} />
              <Radar name="经营贷" dataKey="经营贷" stroke="#aeaeb2" fill="#aeaeb2" fillOpacity={0.04} strokeWidth={1} strokeDasharray="4 4" />
            </RadarChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-4 text-[11px] text-[#8a8a8e]">
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[#3a3a3c]" />消费贷</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[#aeaeb2]" />经营贷</span>
          </div>
        </div>
        </SelectableRegion>
      </div>

      {/* 双产品风险看板 */}
      <div className="grid grid-cols-2 gap-5 mb-6">
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center gap-2 mb-3">
            <ShieldAlert className="w-4 h-4 text-[#aeaeb2]" />
            <h3 className="text-[13px] text-[#1d1d1f]">消费贷风险</h3>
            <span className="text-[10px] text-[#aeaeb2] bg-[#f2f2f7] px-1.5 py-0.5 rounded">个人信用风险</span>
          </div>
          <div className="space-y-1.5">
            {consumerRisk.map((r) => (
              <div key={r.label} className="flex items-center justify-between py-2 px-3 rounded-lg bg-[#fafbfc]">
                <div>
                  <div className="text-[12px] text-[#636366]">{r.label}</div>
                  <div className="text-[10px] text-[#c7c7cc]">阈值 {r.threshold}</div>
                </div>
                <div className="text-right">
                  <div className="text-[14px] text-[#1d1d1f]">{r.value}</div>
                  <span className={`text-[11px] ${r.positive ? "text-[#34a853]" : "text-[#ea4335]"}`}>{r.change}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center gap-2 mb-3">
            <ShieldAlert className="w-4 h-4 text-[#aeaeb2]" />
            <h3 className="text-[13px] text-[#1d1d1f]">经营贷风险</h3>
            <span className="text-[10px] text-[#aeaeb2] bg-[#f2f2f7] px-1.5 py-0.5 rounded">企业经营+抵押风险</span>
          </div>
          <div className="space-y-1.5">
            {businessRisk.map((r) => (
              <div key={r.label} className="flex items-center justify-between py-2 px-3 rounded-lg bg-[#fafbfc]">
                <div>
                  <div className="text-[12px] text-[#636366]">{r.label}</div>
                  <div className="text-[10px] text-[#c7c7cc]">阈值 {r.threshold}</div>
                </div>
                <div className="text-right">
                  <div className="text-[14px] text-[#1d1d1f]">{r.value}</div>
                  <span className={`text-[11px] ${r.positive ? "text-[#34a853]" : "text-[#ea4335]"}`}>{r.change}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 各行双产品经营数据 */}
      <SelectableRegion target={contextTarget("branch-comparison", "各分行双产品经营对比", "数据", summarizeContextValue(bankProductData))} selectedTargetId={selectedContextTarget?.id} onSelect={setSelectedContextTarget} onOpenComment={openDashboardComment} onOpenAnalysis={openDashboardAnalysis}>
      <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Building2 className="w-4 h-4 text-[#aeaeb2]" />
            <h3 className="text-[13px] text-[#1d1d1f]">各分行双产品经营对比</h3>
          </div>
          <div className="flex gap-px bg-[#f2f2f7] rounded-lg p-0.5">
            {(["all", "consumer", "business"] as Product[]).map((p) => (
              <button
                key={p}
                onClick={() => {
                  setSelectedProduct(p);
                  void runDashboardAction("select_product", { selectedProduct: p, selectedBank });
                }}
                className={`px-3 py-1 rounded-md text-[12px] transition-all ${selectedProduct === p ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e]"}`}>
                {p === "all" ? "全部" : p === "consumer" ? "消费贷" : "经营贷"}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-[11px] text-[#aeaeb2] border-b border-[#f0f0f2]">
                <th className="text-left py-2.5 px-2">分行</th>
                {(selectedProduct === "all" || selectedProduct === "consumer") && (
                  <>
                    <th className="text-right py-2.5 px-2" colSpan={selectedProduct === "all" ? 1 : undefined}>消费贷放款(亿)</th>
                    <th className="text-right py-2.5 px-2">消费贷动支率</th>
                    <th className="text-right py-2.5 px-2">消费贷M1</th>
                    {selectedProduct === "consumer" && <th className="text-right py-2.5 px-2">消费贷余额(亿)</th>}
                  </>
                )}
                {(selectedProduct === "all" || selectedProduct === "business") && (
                  <>
                    <th className="text-right py-2.5 px-2">经营贷放款(亿)</th>
                    <th className="text-right py-2.5 px-2">经营贷动支率</th>
                    <th className="text-right py-2.5 px-2">经营贷M1</th>
                    {selectedProduct === "business" && <th className="text-right py-2.5 px-2">经营贷余额(亿)</th>}
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {bankProductData.map((row) => {
                return (
                  <tr key={row.bank} className="border-b border-[#f8f8f8] hover:bg-[#fafbfc] transition-colors cursor-pointer">
                    <td className="py-2.5 px-2 text-[#1d1d1f]">{row.bank}</td>
                    {(selectedProduct === "all" || selectedProduct === "consumer") && (
                      <>
                        <td className="text-right px-2 text-[#1d1d1f]">{row.cLoan}</td>
                        <td className="text-right px-2 text-[#636366]">{formatPercent(row.cDrawdown)}</td>
                        <td className="text-right px-2 text-[#636366]">{formatPercent(row.cM1)}</td>
                        {selectedProduct === "consumer" && <td className="text-right px-2 text-[#636366]">{formatNumber(row.cBalance)}</td>}
                      </>
                    )}
                    {(selectedProduct === "all" || selectedProduct === "business") && (
                      <>
                        <td className="text-right px-2 text-[#1d1d1f]">{row.bLoan}</td>
                        <td className="text-right px-2 text-[#636366]">{formatPercent(row.bDrawdown)}</td>
                        <td className="text-right px-2 text-[#636366]">{formatPercent(row.bM1)}</td>
                        {selectedProduct === "business" && <td className="text-right px-2 text-[#636366]">{formatNumber(row.bBalance)}</td>}
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      </SelectableRegion>

      {/* AI 智能洞察 */}
      <SelectableRegion target={contextTarget("evidence-insights", "证据型双产品经营洞察", "文本", summarizeContextValue(insights))} selectedTargetId={selectedContextTarget?.id} onSelect={setSelectedContextTarget} onOpenComment={openDashboardComment} onOpenAnalysis={openDashboardAnalysis}>
      <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="w-4 h-4 text-[#aeaeb2]" />
          <h3 className="text-[13px] text-[#1d1d1f]">证据型双产品经营洞察</h3>
          <span className="text-[11px] text-[#aeaeb2] ml-1">仅引用当前快照</span>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 bg-[#fafbfc] rounded-lg">
            <div className="flex items-center gap-1.5 mb-2">
              <CreditCard className="w-3.5 h-3.5 text-[#8a8a8e]" />
              <span className="text-[12px] text-[#636366]">消费贷洞察</span>
            </div>
            <div className="text-[11px] text-[#8a8a8e] leading-[1.7] space-y-1">
              {insights.consumer.map((text) => <p key={text}>• {text}</p>)}
            </div>
          </div>
          <div className="p-4 bg-[#fafbfc] rounded-lg">
            <div className="flex items-center gap-1.5 mb-2">
              <Landmark className="w-3.5 h-3.5 text-[#8a8a8e]" />
              <span className="text-[12px] text-[#636366]">经营贷洞察</span>
            </div>
            <div className="text-[11px] text-[#8a8a8e] leading-[1.7] space-y-1">
              {insights.business.map((text) => <p key={text}>• {text}</p>)}
            </div>
          </div>
        </div>
        <div className="flex gap-2 mt-3">
          {["消费贷详细分析", "经营贷详细分析", "各行对比报告", "风险预警明细"].map((action) => (
            <button
              key={action}
              onClick={() => void runDashboardAction("open_insight_action", { action, selectedProduct, selectedBank })}
              className="px-3 py-1.5 border border-[#e5e5ea] rounded-lg text-[12px] text-[#636366] hover:bg-[#f2f2f7] transition-colors flex items-center gap-1"
            >
              {action}<ArrowUpRight className="w-3 h-3 opacity-40" />
            </button>
          ))}
        </div>
      </div>
      </SelectableRegion>
      </main>
      <WeeklyReportSideRail
        pageKey="multi-institution-analysis"
        pageTitle="多机构分析"
        overallPrompt="结合当前多机构分析页面和关联指标数据，比较各机构消费贷与经营贷的规模、趋势、效率和风险，给出关键差异与行动建议。"
        activeTab={rightRailTab}
        onTabChange={setRightRailTab}
        commentCount={comments.filter((comment) => comment.status === "open").length}
        railHeight={720}
        focusTargetId={selectedContextTarget?.id}
        focusTarget={rightRailTab === "analysis" ? selectedContextTarget : null}
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
      </AnalysisUnderlineProvider>
      </div>
    </div>
  );
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
  const datasetRows = (key: string) => snapshot?.datasets[key]?.status === "ready" ? snapshot.datasets[key].rows : [];
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

function DashboardState({ message }: { message: string }) {
  return (
    <div className="p-7">
      <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">多机构分析</h2>
      <p className="text-[13px] text-[#aeaeb2] mt-1">消费贷 + 经营贷 双产品经营全景</p>
      <div className="mt-6 rounded-xl border border-[#f0f0f2] bg-white px-6 py-16 text-center text-[12px] text-[#aeaeb2]">{message}</div>
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
