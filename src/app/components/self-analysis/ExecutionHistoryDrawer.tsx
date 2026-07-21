import { Eye, ListTree, LoaderCircle, Trash2, X } from "lucide-react";
import type { AnalysisTraceSpan, BackendAnalysisResponse } from "../../services/analysisApi";

export function ExecutionHistoryDrawer({
  open,
  tasks,
  expandedTaskId,
  spans,
  loading,
  onClose,
  onView,
  onDelete,
  onToggleDetails,
}: {
  open: boolean;
  tasks: BackendAnalysisResponse[];
  expandedTaskId: string;
  spans: AnalysisTraceSpan[];
  loading: boolean;
  onClose: () => void;
  onView: (task: BackendAnalysisResponse) => void;
  onDelete: (task: BackendAnalysisResponse) => void;
  onToggleDetails: (task: BackendAnalysisResponse) => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[80] bg-black/10" onMouseDown={onClose}>
      <aside className="absolute bottom-0 right-0 top-0 w-full max-w-[470px] overflow-y-auto border-l border-[#e5e5ea] bg-[#f8f8fa] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[#e5e5ea] bg-white px-5 py-4">
          <div><h3 className="text-[15px] text-[#1d1d1f]">执行记录</h3><p className="mt-1 text-[11px] text-[#8a8a8e]">查看历史问题、分析结果、思考阶段和执行链路。</p></div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]"><X className="h-4 w-4" /></button>
        </div>
        <div className="bg-white">
          {loading ? <div className="border-b border-[#f0f0f2] px-4 py-12 text-center text-[12px] text-[#aeaeb2]">正在读取执行记录…</div> : null}
          {!loading && !tasks.length ? <div className="border-b border-[#f0f0f2] px-4 py-12 text-center text-[12px] text-[#aeaeb2]">暂无执行记录。</div> : null}
          {tasks.map((task) => {
            const expanded = expandedTaskId === task.task_id;
            const running = ["created", "queued", "planning", "running", "retry_wait"].includes(task.status || "");
            return <div key={task.task_id} className="border-b border-[#f0f0f2]"><div className="flex items-start gap-2.5 px-4 py-2.5"><span className="mt-[5px] h-2 w-2 shrink-0 rounded-full border border-[#8a8a8e] bg-white" aria-hidden="true" /><div className="min-w-0 flex-1"><div className="flex h-5 min-w-0 items-center gap-1"><div className="min-w-0 flex-1 truncate text-[12px] leading-5 text-[#1d1d1f]" title={task.question || "未命名分析问题"}>{task.question || "未命名分析问题"}</div>{running ? <LoaderCircle className="h-3 w-3 shrink-0 animate-spin text-[#0a84ff]" aria-label="正在运行" /> : null}<div className="flex shrink-0 items-center gap-0.5"><button type="button" onClick={() => onDelete(task)} className="inline-flex h-5 w-5 items-center justify-center rounded text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025]" title="删除执行记录" aria-label={`删除${task.question || "执行记录"}`}><Trash2 className="h-3 w-3" /></button><button type="button" onClick={() => onView(task)} className="inline-flex h-5 w-5 items-center justify-center rounded text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" title="查看分析结果" aria-label={`查看${task.question || "执行记录"}`}><Eye className="h-3 w-3" /></button><button type="button" onClick={() => onToggleDetails(task)} className={`inline-flex h-5 w-5 items-center justify-center rounded hover:bg-[#f2f2f7] hover:text-[#1d1d1f] ${expanded ? "bg-[#f2f2f7] text-[#1d1d1f]" : "text-[#8a8a8e]"}`} title={expanded ? "收起执行详情" : "展开执行详情"} aria-label={`${expanded ? "收起" : "展开"}${task.question || "执行记录"}详情`}><ListTree className="h-3 w-3" /></button></div></div><div className="truncate text-[10px] leading-4 text-[#aeaeb2]">{formatDate(task.updated_at || task.created_at)} · {task.status || "completed"} · {task.task_id}</div></div></div>{expanded ? <div className="border-t border-[#f5f5f7] bg-[#fafbfc] px-8 py-3"><div className="mb-2 text-[11px] text-[#636366]">思考阶段与执行链</div><div className="space-y-2">{spans.map((span, index) => <div key={`${span.trace_id}_${span.span_id}`} className="relative flex gap-3 pl-1"><div className="flex w-4 flex-col items-center"><span className={`mt-1 h-2 w-2 rounded-full ${span.status === "error" ? "bg-[#ff3b30]" : "bg-[#34c759]"}`} />{index < spans.length - 1 ? <span className="mt-1 h-full w-px bg-[#d1d1d6]" /> : null}</div><div className="min-w-0 pb-2"><div className="text-[11px] text-[#3a3a3c]">{humanizeSpan(span)}</div><div className="mt-0.5 break-all text-[10px] leading-4 text-[#8a8a8e]">{span.status} · {summarizeSpan(span)}</div></div></div>)}{!spans.length ? <div className="text-[11px] text-[#aeaeb2]">当前记录没有可展示的执行跨度。</div> : null}</div></div> : null}</div>;
          })}
        </div>
      </aside>
    </div>
  );
}

function formatDate(value?: string) {
  if (!value) return "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function humanizeSpan(span: AnalysisTraceSpan) {
  const name = span.span_name;
  const input = span.inputs || {};
  const labels: Record<string, string> = {
    "api.analysis.start": "接收问题并建立执行上下文",
    "agent.intent.parse": "理解问题与识别分析意图",
    "agent.planner.plan": "生成指标、维度与执行计划",
    "skill.supersonic.query": "执行语义查询与取数",
    "skill.execute.start": "开始执行语义查询与取数",
    "skill.execute.finish": "完成语义查询并返回数据",
    "api.analysis.finish": "复核证据并生成分析结果",
  };
  if (name === "agent.operation.authorized") {
    return `权限校验：${String(input.operation_id || "受治理操作")}`;
  }
  if (name === "agent.stage_gate") {
    const gates: Record<string, string> = {
      plan_compiled: "执行计划完整性校验",
      permission_enforced: "数据权限执行校验",
      evidence_bound: "数据证据绑定校验",
      final_review_passed: "结论发布复核",
    };
    return gates[String(input.gate || "")] || "执行阶段校验";
  }
  return labels[name] || name.replaceAll(".", " → ");
}

function summarizeSpan(span: AnalysisTraceSpan) {
  const input = span.inputs || {};
  const output = span.outputs || {};
  const evidence = output.evidence && typeof output.evidence === "object" ? output.evidence as Record<string, unknown> : {};
  const useful = [
    input.operation_id,
    input.skill_id,
    input.gate,
    output.passed === true ? "校验通过" : output.passed === false ? "校验未通过" : "",
    evidence.evidence_id,
    evidence.review_status,
    output.status,
    output.task_id,
    output.latency_ms ? `${output.latency_ms}ms` : "",
  ].filter(Boolean);
  return useful.join(" · ") || "步骤已记录";
}
