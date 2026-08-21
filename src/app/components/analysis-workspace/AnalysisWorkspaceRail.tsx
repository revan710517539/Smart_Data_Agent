import { useEffect, useRef, useState } from "react";
import { waitForSelfAnalysis, type AnalysisProgressStep } from "../../services/analysisApi";
import { createClientUuid } from "../../utils/clientUuid";
import { AnalysisProgressPanel } from "../self-analysis/AnalysisProgressPanel";
import { WorkspaceFollowUpChart, followUpVisualFromRefs } from "./WorkspaceFollowUpChart";
import { GitBranch, GitMerge, LoaderCircle, Maximize2, Minimize2, Send, Sparkles } from "lucide-react";
import { useLocation } from "react-router";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import {
  createAnalysisBranch,
  ensureAnalysisWorkspace,
  fetchAnalysisWorkspace,
  mergeAnalysisThreads,
  type AnalysisThread,
  type AnalysisWorkspace,
  type AnalysisWorkspaceContext,
  type SelectedDataPoint,
} from "../../services/analysisWorkspaceApi";
import { TrustedArtifactPanel } from "./TrustedArtifactPanel";
import {
  mergeVisualAnalysisSourceGroups,
  pageVisualAnalysisContext,
  type VisualAnalysisSource,
} from "./visualAnalysisScope";

type PageDefinition = { pageKey: string; title: string; prompt: string };

const pageDefinitions: Record<string, PageDefinition> = {
  "/dashboard": { pageKey: "multi-institution-analysis", title: "多机构分析", prompt: "比较各机构消费贷与经营贷的规模、趋势、效率和风险，给出关键差异与行动建议。" },
  "/funnel": { pageKey: "funnel", title: "业务漏斗", prompt: "分析当前转化漏斗的主要断点与影响因素。" },
  "/sandbox": { pageKey: "sandbox", title: "经营沙盘", prompt: "分析当前经营策略、投入产出和情景变化。" },
  "/supervision": { pageKey: "supervision", title: "机构督导", prompt: "分析当前机构表现差异、风险和督导建议。" },
  "/email-daily": { pageKey: "email-daily", title: "邮件日报", prompt: "分析当前日报证据、异常和需要关注的事项。" },
  "/customers": { pageKey: "customers", title: "客群分析", prompt: "分析当前客群结构、价值、转化和风险。" },
  "/competition": { pageKey: "competition", title: "竞品分析", prompt: "分析当前竞品差异、市场位置和行动空间。" },
  "/self-analysis/query": { pageKey: "self-analysis", title: "智能分析", prompt: "基于当前分析结果继续追问、拆解或验证。" },
  "/self-analysis/visual-reports": { pageKey: "visual-reports", title: "可视化报表", prompt: "基于当前可视化和授权数据集继续追问、拆解或验证。" },
  "/self-analysis/reports": { pageKey: "my-reports", title: "我的报表", prompt: "基于当前报表继续追问并固化新的分析结论。" },
  "/weekly-report": { pageKey: "weekly-report", title: "经营周报", prompt: "基于当前周报及关联证据继续追问、分支分析或合并结论。" },
  "/data-assets/metrics": { pageKey: "metric-management", title: "指标管理", prompt: "检查当前指标语义、版本和影响范围。" },
  "/data-assets/data-management": { pageKey: "data-management", title: "数据管理", prompt: "检查当前数据 Schema、语义关系和版本影响。" },
};

export const analysisWorkspaceRevealEvent = "smart-data-agent:analysis-workspace-reveal";
export const analysisWorkspaceContextEvent = "smart-data-agent:analysis-workspace-context";
const latestPageContexts = new Map<string, Record<string, unknown>>();

export function updateAnalysisWorkspacePageContext(pageKey: string, context: Record<string, unknown>) {
  const previous = latestPageContexts.get(pageKey) || {};
  const next = { ...context };
  if (!("visual_analysis_sources" in context) && Array.isArray(previous.visual_analysis_sources)) {
    next.visual_analysis_sources = previous.visual_analysis_sources;
    const nextTables = Array.isArray(next.selected_data_tables) ? next.selected_data_tables : [];
    const previousTables = Array.isArray(previous.selected_data_tables) ? previous.selected_data_tables : [];
    if (!nextTables.length && previousTables.length) next.selected_data_tables = previous.selected_data_tables;
  }
  latestPageContexts.set(pageKey, next);
  window.dispatchEvent(new CustomEvent(analysisWorkspaceContextEvent, { detail: { pageKey, context: next } }));
}

export function replaceVisualAnalysisSourceGroup(pageKey: string, group: string, sources: VisualAnalysisSource[]) {
  const previous = latestPageContexts.get(pageKey) || {};
  updateAnalysisWorkspacePageContext(pageKey, {
    ...previous,
    ...pageVisualAnalysisContext(mergeVisualAnalysisSourceGroups(previous.visual_analysis_sources, group, sources)),
  });
}

export function revealAnalysisWorkspace(selectedDataPoint?: SelectedDataPoint, surface: "context-rail" | "agent-supervisor" = "context-rail") {
  window.dispatchEvent(new CustomEvent(analysisWorkspaceRevealEvent, { detail: { selectedDataPoint, surface } }));
}

export function AnalysisWorkspacePanel({ revealedDataPoint, wide = false, onWideChange }: { revealedDataPoint?: SelectedDataPoint; wide?: boolean; onWideChange?: (wide: boolean) => void }) {
  const location = useLocation();
  const definition = pageDefinitions[location.pathname];
  const { tenantId, userId } = usePlatformContext();
  const [workspace, setWorkspace] = useState<AnalysisWorkspace | null>(null);
  const [threads, setThreads] = useState<AnalysisThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState("");
  const [selectedDataPoint, setSelectedDataPoint] = useState<SelectedDataPoint>();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [selectedMergeIds, setSelectedMergeIds] = useState<string[]>([]);
  const [pageContext, setPageContext] = useState<Record<string, unknown>>({});
  const [pendingQuestion, setPendingQuestion] = useState("");
  const [progressSteps, setProgressSteps] = useState<AnalysisProgressStep[]>([]);
  const scopeRef = useRef("");
  const pageScopeRef = useRef(false);
  const waitAbortRef = useRef<AbortController | null>(null);

  useEffect(() => () => { waitAbortRef.current?.abort(); }, []);

  useEffect(() => {
    const incomingBound = isChartBoundDataPoint(revealedDataPoint);
    if (pageScopeRef.current && !incomingBound) return;
    if (incomingBound) {
      pageScopeRef.current = false;
      setSelectedDataPoint(revealedDataPoint);
      return;
    }
    setSelectedDataPoint((current) => {
      if (isChartBoundDataPoint(current) && current?.targetId && current.targetId === revealedDataPoint?.targetId) return current;
      return revealedDataPoint;
    });
  }, [revealedDataPoint]);

  useEffect(() => {
    const reveal = (event: Event) => {
      const detail = (event as CustomEvent<{ selectedDataPoint?: SelectedDataPoint }>).detail;
      if (!detail?.selectedDataPoint) {
        pageScopeRef.current = true;
        setSelectedDataPoint(undefined);
        return;
      }
      pageScopeRef.current = false;
      setSelectedDataPoint(detail.selectedDataPoint);
    };
    window.addEventListener(analysisWorkspaceRevealEvent, reveal);
    return () => window.removeEventListener(analysisWorkspaceRevealEvent, reveal);
  }, []);

  useEffect(() => {
    if (definition?.pageKey) setPageContext(latestPageContexts.get(definition.pageKey) || {});
    const updateContext = (event: Event) => {
      const detail = (event as CustomEvent<{ pageKey?: string; context?: Record<string, unknown> }>).detail;
      if (detail?.pageKey !== definition?.pageKey || !detail.context) return;
      setPageContext(detail.context);
    };
    window.addEventListener(analysisWorkspaceContextEvent, updateContext);
    return () => window.removeEventListener(analysisWorkspaceContextEvent, updateContext);
  }, [definition?.pageKey]);

  useEffect(() => {
    if (!definition) return;
    const scope = `${tenantId}:${userId}:${definition.pageKey}`;
    scopeRef.current = scope;
    setWorkspace(null);
    setThreads([]);
    setActiveThreadId("");
    setSelectedMergeIds([]);
    setNotice("");
    const workspaceContext: AnalysisWorkspaceContext = {
      pageKey: definition.pageKey,
      artifactId: stringValue(pageContext.artifact_id ?? pageContext.artifactId) || definition.pageKey,
      datasetSnapshot: objectValue(pageContext.dataset_snapshot ?? pageContext.datasetSnapshot),
      metricVersions: metricVersionArray(pageContext.metric_versions ?? pageContext.metricVersions),
      filters: objectValue(pageContext.filters),
      selectedDataPoint,
      allowedActions: ["follow_up", "branch", "merge", "trust", "freeze_report", "rerun"],
      evidenceRefs: evidenceRefArray(pageContext.evidence_refs ?? pageContext.evidenceRefs),
    };
    ensureAnalysisWorkspace(stringValue(pageContext.workspace_key) || definition.pageKey, workspaceContext, { tenantId, userId })
      .then(async ({ workspace: created }) => {
        if (scopeRef.current !== scope) return;
        setWorkspace(created);
        const loaded = await fetchAnalysisWorkspace(created.workspace_id, { tenantId, userId });
        if (scopeRef.current !== scope) return;
        setThreads(loaded.threads);
        setActiveThreadId(loaded.threads.find((thread) => thread.status === "active")?.thread_id || loaded.threads[0]?.thread_id || "");
      })
      .catch((error) => {
        if (scopeRef.current === scope) setNotice(apiErrorMessage(error, "分析工作区加载失败。"));
      });
  }, [definition, tenantId, userId, pageContext]);

  if (!definition) return <div className="flex h-full items-center justify-center bg-[#f8f8fa] px-6 text-center text-[11px] leading-5 text-[#8a8a8e]" data-analysis-workspace-unavailable="true">当前页面没有可分析的可视化上下文。<br />仍可切换到总管对话操作页面、查询指标、记忆和 Skill。</div>;
  const activeThread = threads.find((thread) => thread.thread_id === activeThreadId) || threads[0];
  const visibleThreads = threads.filter((thread, index) => {
    const duplicates = threads.filter((candidate) => candidate.title.trim() === thread.title.trim());
    if (duplicates.length < 2) return true;
    return thread.thread_id === activeThread?.thread_id || (!duplicates.some((candidate) => candidate.thread_id === activeThread?.thread_id) && duplicates[0]?.thread_id === thread.thread_id && index >= 0);
  });
  const analysisTitle = selectedDataPoint?.label || definition.title;
  const chartValues = objectValue(selectedDataPoint?.values);
  const pageSources = objectArray(pageContext.visual_analysis_sources);
  const chartFollowUp = Boolean(selectedDataPoint?.targetId && chartValues.chart_bound_source);
  const selectedTables = chartFollowUp
    ? boundVisualAnalysisTables(selectedDataPoint, pageContext)
    : (objectArray(pageContext.selected_data_tables).length ? objectArray(pageContext.selected_data_tables) : pageSources.flatMap((source) => objectArray(source.tables)));
  const parentTaskId = chartFollowUp
    ? (stringValue(chartValues.analysis_task_id) || stringValue(pageContext.analysis_task_id))
    : "";
  const sourceQuestion = chartFollowUp
    ? stringValue(chartValues.question)
    : pageSources.map((source) => stringValue(source.question) || stringValue(source.label)).filter(Boolean).join("；");
  const chartSnapshot = objectValue(chartValues.dataset_snapshot);
  const hasChartSnapshot = Boolean(
    chartSnapshot.id || chartSnapshot.version || chartSnapshot.content_hash || chartSnapshot.schema_fingerprint,
  );
  const effectivePageContext: Record<string, unknown> = {
    ...pageContext,
    visual_analysis_scope: chartFollowUp ? "chart" : "page",
    chart_bound_source: chartFollowUp,
    selected_data_tables: selectedTables,
    dataset_snapshot: chartFollowUp && hasChartSnapshot ? chartSnapshot : pageContext.dataset_snapshot,
    ...(parentTaskId ? { parent_task_id: parentTaskId } : { parent_task_id: undefined }),
    ...(sourceQuestion ? { follow_up_source_question: sourceQuestion } : {}),
    selected_data_point: chartFollowUp ? selectedDataPoint : undefined,
  };

  const reload = async () => {
    if (!workspace) return;
    const loaded = await fetchAnalysisWorkspace(workspace.workspace_id, { tenantId, userId });
    setThreads(loaded.threads);
  };

  const createBranch = async () => {
    if (!workspace || !activeThread) return;
    setBusy(true);
    try {
      const { thread } = await createAnalysisBranch(workspace.workspace_id, activeThread.thread_id, selectedDataPoint?.label || "分析分支", selectedDataPoint || {}, { tenantId, userId });
      await reload();
      setActiveThreadId(thread.thread_id);
      setNotice("已创建独立分析分支。 ");
    } catch (error) {
      setNotice(apiErrorMessage(error, "创建分析分支失败。"));
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    const prompt = question.trim();
    if (!prompt || !activeThread || busy) return;
    if (!selectedTables.length && !chartFollowUp && !parentTaskId && !pageSources.length && definition.pageKey === "self-analysis") {
      setNotice("请先在智能分析主输入区选择当前机构的数据表，再发起线程追问。");
      return;
    }
    setBusy(true);
    setNotice("");
    setPendingQuestion(prompt);
    setProgressSteps([{
      step_code: "request_queued",
      sequence_no: 0,
      status: "running",
      output_refs: [{ label: "理解问题", detail: chartFollowUp ? "正在装载当前图表绑定的数据。" : "正在装载当前页面全部可视化数据。" }],
    }]);
    waitAbortRef.current?.abort();
    const controller = new AbortController();
    waitAbortRef.current = controller;
    try {
      const result = await waitForSelfAnalysis({
        question: prompt,
        tenantId,
        userId,
        requestId: createClientUuid(),
        signal: controller.signal,
        pollIntervalMs: 800,
        onRun: (run) => setProgressSteps(run.progress_steps?.length ? run.progress_steps : [{
          step_code: "request_queued",
          sequence_no: 0,
          status: run.status === "queued" ? "queued" : "running",
          output_refs: [{ label: "创建分析任务", detail: "分析任务已进入执行队列。" }],
        }]),
        pageContext: {
          ...effectivePageContext,
          workspace_id: workspace?.workspace_id,
          thread_id: activeThread.thread_id,
          page_key: definition.pageKey,
          selected_data_point: chartFollowUp ? selectedDataPoint : undefined,
          model_application_module: "intelligent_analysis_reasoning",
          analysis_skill: objectWithFallback(pageContext.analysis_skill, {
            id: `page-${definition.pageKey}`,
            name: `${definition.title}页面追问`,
            category: "场景",
            description: `只基于${definition.title}当前筛选、受治理数据与证据进行追问分析。`,
          }),
          analysis_context_skills: objectArray(pageContext.analysis_context_skills).length
            ? objectArray(pageContext.analysis_context_skills)
            : [{
                id: `page-${definition.pageKey}`,
                name: `${definition.title}页面追问`,
                category: "场景",
                description: `只基于${definition.title}当前筛选、受治理数据与证据进行追问分析。`,
              }],
          analysis_policy: {
            engine: "IntelligentAnalysisEngine",
            resultDelivery: "data_first",
            conflictStrategy: "executed_query_evidence_overrides_page_context",
            detailAnalysisOrder: "selected_table_full_dimensions_metrics_then_related_detail_table",
            missingDetailMessage: "没有更细粒度数据，请关联明细数据",
            ...objectValue(effectivePageContext.analysis_policy),
            resultFormat: "brief_visual",
          },
        },
      });
      const returnedAssetContext = objectValue(result.asset_context);
      if (returnedAssetContext.detail_table_status === "unavailable") {
        setNotice(String(returnedAssetContext.detail_table_message || "没有更细粒度数据，请关联明细数据"));
      }
      setQuestion("");
      await reload();
    } catch (error) {
      if ((error as { name?: string })?.name === "AbortError") return;
      setNotice(apiErrorMessage(error, "追问执行失败，已保留现有线程。"));
    } finally {
      if (waitAbortRef.current === controller) {
        setBusy(false);
        setPendingQuestion("");
        setProgressSteps([]);
      }
    }
  };

  const mergeSelected = async () => {
    if (!activeThread || !selectedMergeIds.length) return;
    setBusy(true);
    try {
      const sourceThreads = threads.filter((thread) => selectedMergeIds.includes(thread.thread_id));
      const answer = sourceThreads.flatMap((thread) => thread.turns.slice(-1).map((turn) => turn.answer)).filter(Boolean).join("\n");
      await mergeAnalysisThreads(activeThread.thread_id, selectedMergeIds, "合并所选分支结论", answer || "所选分支暂无可合并结论。", [], { tenantId, userId });
      setSelectedMergeIds([]);
      await reload();
      setNotice("分支结论已生成新轮次，原线程历史保持不变。 ");
    } catch (error) {
      setNotice(apiErrorMessage(error, "分支合并失败。"));
    } finally {
      setBusy(false);
    }
  };

  return (
        <section className="flex h-full min-h-0 flex-col overflow-hidden bg-white" data-analysis-workspace-panel="true" data-page-key={definition.pageKey} data-visual-analysis-scope={chartFollowUp ? "chart" : "page"}>
          <div className="flex items-center border-b border-[#ececf0] bg-[#fafbfc] px-2 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" data-analysis-thread-tabs="true">
              <Sparkles className="h-4 w-4 shrink-0 text-[#636366]" aria-hidden="true" />
              {visibleThreads.map((thread) => (
                <button key={thread.thread_id} type="button" onClick={() => setActiveThreadId(thread.thread_id)} className={`shrink-0 rounded-md px-2 py-1.5 text-[10px] outline-none focus-visible:outline-none ${activeThread?.thread_id === thread.thread_id ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:bg-white"}`}>
                  {thread.parent_thread_id ? "分支 · " : ""}{thread.title}{thread.status === "merged" ? " · 已合并" : ""}
                </button>
              ))}
            </div>
            <button type="button" onClick={() => void createBranch()} disabled={!activeThread || busy} aria-label="新建分析分支" title="新建分支" className="ml-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[#636366] outline-none hover:bg-white focus-visible:outline-none disabled:opacity-40" data-analysis-branch-create="true"><GitBranch className="h-3.5 w-3.5" /></button>
            <button type="button" onClick={() => onWideChange?.(!wide)} aria-label={wide ? "恢复右栏宽度" : "放大右栏"} title={wide ? "恢复右栏宽度" : "放大右栏"} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[#636366] outline-none hover:bg-white focus-visible:outline-none" data-global-analysis-wide-toggle="true">{wide ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}</button>
          </div>
          <div className="flex-1 overflow-y-auto bg-[#f8f8fa] p-2.5">
            {!activeThread?.turns.length && !busy ? <div className="rounded-lg border border-dashed border-[#d9d9de] bg-white px-4 py-8 text-center text-[11px] leading-5 text-[#8a8a8e]">{chartFollowUp ? `基于“${analysisTitle}”继续追问、拆解或验证。` : pageSources.length ? `基于当前页面 ${pageSources.length} 个可视化继续分析。` : definition.prompt}</div> : null}
            <div className="space-y-2">
              {activeThread?.turns.map((turn) => <div key={turn.turn_id} className="rounded-lg border border-[#ececf0] bg-white p-3" data-workspace-follow-up-turn="true"><div className="text-[11px] text-[#1d1d1f]">{turn.question}</div><WorkspaceFollowUpChart visual={followUpVisualFromRefs(turn.artifact_refs)} /><div className="mt-2 whitespace-pre-wrap text-[11px] leading-5 text-[#636366]">{turn.answer || "本轮仅返回部分数据，结论尚未完成。"}</div><TrustedArtifactPanel taskId={String(turn.execution_plan.task_id || "")} compact /></div>)}
              {busy ? <div className="rounded-lg border border-[#ececf0] bg-white p-3" data-workspace-follow-up-thinking="true"><div className="text-[11px] text-[#1d1d1f]">{pendingQuestion || question}</div><div className="mt-2"><AnalysisProgressPanel embedded compact steps={progressSteps} running={busy} hasResult={false} /></div></div> : null}
            </div>
            {notice ? <div className="mt-2 rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[10px] text-[#636366]">{notice}</div> : null}
          </div>
          <div className="shrink-0 border-t border-[#ececf0] bg-white p-2" data-analysis-workspace-composer="true">
            {visibleThreads.some((thread) => thread.parent_thread_id && thread.status === "active" && thread.thread_id !== activeThread?.thread_id) ? (
              <div className="mb-2 flex items-center gap-1.5">
                {visibleThreads.filter((thread) => thread.parent_thread_id && thread.status === "active" && thread.thread_id !== activeThread?.thread_id).map((thread) => <label key={thread.thread_id} className="flex h-7 items-center gap-1 rounded-md border border-[#e5e5ea] px-2 text-[9px] text-[#636366]"><input type="checkbox" checked={selectedMergeIds.includes(thread.thread_id)} onChange={(event) => setSelectedMergeIds((current) => event.target.checked ? [...current, thread.thread_id] : current.filter((id) => id !== thread.thread_id))} />{thread.title}</label>)}
                {selectedMergeIds.length ? <button type="button" onClick={() => void mergeSelected()} disabled={busy} className="flex h-7 items-center gap-1 rounded-md bg-[#1d1d1f] px-2 text-[10px] text-white"><GitMerge className="h-3 w-3" />合并</button> : null}
              </div>
            ) : null}
            <div className="flex items-end gap-2 rounded-lg border border-[#d9d9de] bg-white px-2.5 py-1.5 focus-within:border-[#8a8a8e]">
              <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} rows={2} placeholder={chartFollowUp ? "基于当前图表继续追问…" : "基于当前页面全部可视化继续分析…"} className="min-h-[36px] flex-1 resize-none bg-transparent text-[11px] leading-5 text-[#1d1d1f] outline-none placeholder:text-[#aeaeb2]" />
              <button type="button" onClick={() => void submit()} disabled={!question.trim() || busy || !activeThread} className="flex h-7 w-7 items-center justify-center rounded-full bg-[#1d1d1f] text-white disabled:bg-[#d1d1d6]" aria-label="提交追问">{busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}</button>
            </div>
          </div>
        </section>
  );
}

function isChartBoundDataPoint(selectedDataPoint: SelectedDataPoint | undefined) {
  return Boolean(selectedDataPoint?.targetId && objectValue(selectedDataPoint.values).chart_bound_source);
}

function boundVisualAnalysisTables(selectedDataPoint: SelectedDataPoint | undefined, pageContext: Record<string, unknown>) {
  const values = objectValue(selectedDataPoint?.values);
  const fromChart = objectArray(values.selected_data_tables).map(normalizeBoundTable);
  if (fromChart.length) return fromChart;
  const pageDataId = stringValue(values.page_data_id);
  if (pageDataId) {
    return [{
      id: pageDataId,
      kind: "page_data",
      name: stringValue(selectedDataPoint?.label) || stringValue(values.source_table_name) || "页面数据",
      code: `page_data_${pageDataId}`,
    }];
  }
  return objectArray(pageContext.selected_data_tables).map(normalizeBoundTable);
}

function normalizeBoundTable(item: Record<string, unknown>) {
  const metricCodes = stringList(item.metricCodes).length ? stringList(item.metricCodes) : stringList(item.metric_codes);
  const dimensionCodes = stringList(item.dimensionCodes).length ? stringList(item.dimensionCodes) : stringList(item.dimension_codes);
  return {
    ...item,
    metricCodes,
    defaultMetrics: stringList(item.defaultMetrics).length ? stringList(item.defaultMetrics) : metricCodes,
    dimensionCodes,
    defaultDimensions: stringList(item.defaultDimensions).length ? stringList(item.defaultDimensions) : dimensionCodes,
  };
}

function stringList(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function objectArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function evidenceRefArray(value: unknown) {
  return objectArray(value).flatMap((item) => {
    const id = stringValue(item.id);
    return id ? [{ id, type: stringValue(item.type) || undefined, label: stringValue(item.label) || undefined }] : [];
  });
}

function metricVersionArray(value: unknown) {
  return objectArray(value).flatMap((item) => {
    const metricId = stringValue(item.metricId ?? item.metric_id);
    const version = stringValue(item.version ?? item.version_id);
    return metricId && version ? [{ metricId, version }] : [];
  });
}

function objectWithFallback(value: unknown, fallback: Record<string, unknown>) {
  const object = objectValue(value);
  return Object.keys(object).length ? object : fallback;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}
