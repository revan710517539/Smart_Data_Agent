import { Check, Circle, LoaderCircle, X } from "lucide-react";
import type { AnalysisProgressStep } from "../../services/analysisApi";
import { AnalysisRunningRabbit } from "./AnalysisRunningRabbit";

export function AnalysisProgressPanel({
  steps,
  running,
  error,
  hasResult,
  embedded = false,
  compact = false,
}: {
  steps: AnalysisProgressStep[];
  running: boolean;
  error?: string;
  hasResult: boolean;
  embedded?: boolean;
  compact?: boolean;
}) {
  const hasFailureSignal = steps.some((step) => step.status === "failed") || Boolean(error);
  const degraded = hasResult && hasFailureSignal;
  const failed = !hasResult && hasFailureSignal;
  const showRunningRabbit = !failed && !degraded && steps.length > 0 && (running || !hasResult);
  return (
    <div
      className={embedded ? "overflow-hidden bg-transparent" : "overflow-hidden rounded-lg border border-[#e5e5ea] bg-[#fafbfc]"}
      data-analysis-progress-embedded={embedded ? "true" : "false"}
    >
      {!embedded && (
        <div className="flex items-center justify-between border-b border-[#ececf0] bg-white px-4 py-3">
          <div className="flex min-w-0 flex-1 items-center">
            <div className="shrink-0">
              <div className="text-[12px] font-medium text-[#1d1d1f]">思考链</div>
              <div className="mt-0.5 text-[10px] text-[#8a8a8e]">展示可审计的执行阶段和阶段摘要，不展示模型私有原始推理。</div>
            </div>
            {showRunningRabbit && <AnalysisRunningRabbit />}
          </div>
          <div className={`flex items-center gap-1.5 text-[10px] ${failed ? "text-[#ff3b30]" : degraded ? "text-[#b56a00]" : running ? "text-[#0a84ff]" : "text-[#34c759]"}`}>
            {failed ? <X className="h-3 w-3" /> : running ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            {failed ? "执行异常" : degraded ? "数据已返回 · 降级完成" : running ? "实时更新中" : "执行完成"}
          </div>
        </div>
      )}
      <div className={`${compact ? "max-h-[168px] min-h-0 overflow-y-auto overscroll-contain px-0 py-1" : `max-h-[360px] min-h-[240px] overflow-y-auto overscroll-contain ${embedded ? "px-0 py-1" : "px-4 py-3"}`}`} aria-live="polite" data-analysis-progress-scroll="manual">
        <div className="space-y-0">
          {steps.map((step, index) => {
            const summary = step.output_refs?.[0] || {};
            const isLast = index === steps.length - 1;
            return (
              <div key={`${step.step_code}_${step.sequence_no}`} className="flex gap-3">
                <div className="flex w-4 shrink-0 flex-col items-center">
                  <StepIcon status={step.status} />
                  {!isLast && <span className="mt-1 min-h-8 w-px flex-1 bg-[#d9d9de]" />}
                </div>
                <div className="min-w-0 flex-1 pb-4">
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-medium text-[#3a3a3c]">{summary.label || humanizeStep(step.step_code)}</span>
                    <span className="text-[9px] uppercase tracking-wide text-[#aeaeb2]">{statusLabel(step.status)}</span>
                  </div>
                  <p className="mt-1 text-[11px] leading-5 text-[#636366]">{summary.detail || defaultDetail(step.status)}</p>
                  {typeof summary.row_count === "number" && (
                    <span className="mt-1.5 inline-flex rounded bg-white px-1.5 py-0.5 text-[9px] text-[#8a8a8e] shadow-sm">
                      已返回 {summary.row_count} 行
                    </span>
                  )}
                </div>
              </div>
            );
          })}
          {!steps.length && <div className="py-16 text-center text-[11px] text-[#aeaeb2]">正在创建分析任务…</div>}
        </div>
      </div>
      {error && (
        <div className={`${embedded ? "mt-2 px-2 py-2" : "border-t px-4 py-3"} text-[11px] leading-5 ${degraded ? `${embedded ? "" : "border-[#f3d29a]"} bg-[#fff9ed] text-[#8a5700]` : `${embedded ? "" : "border-[#ffd2cf]"} bg-[#fff4f3] text-[#d93025]`}`}>
          {error}
        </div>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: string }) {
  if (status === "running") return <LoaderCircle className="mt-0.5 h-3.5 w-3.5 animate-spin text-[#0a84ff]" />;
  if (status === "failed") return <span className="mt-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-[#ff3b30]"><X className="h-2.5 w-2.5 text-white" /></span>;
  if (status === "succeeded") return <span className="mt-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-[#34c759]"><Check className="h-2.5 w-2.5 text-white" /></span>;
  return <Circle className="mt-0.5 h-3.5 w-3.5 text-[#c7c7cc]" />;
}

function humanizeStep(code: string) {
  return ({
    request_queued: "创建分析任务",
    execute_handler: "启动分析引擎",
    context_understanding: "理解问题与装载上下文",
    model_planning: "生成分析方案",
    data_query: "查询业务数据",
    evidence_review: "校验口径与证据",
    model_conclusion: "生成分析结论",
    result_finalize: "整理可视化结果",
  } as Record<string, string>)[code] || code;
}

function statusLabel(status: string) {
  return ({ queued: "等待中", running: "进行中", succeeded: "已完成", failed: "失败", skipped: "已复用" } as Record<string, string>)[status] || status;
}

function defaultDetail(status: string) {
  if (status === "queued") return "任务已进入执行队列。";
  if (status === "running") return "该阶段正在执行。";
  if (status === "failed") return "该阶段未完成，请根据错误提示检查配置。";
  if (status === "skipped") return "该阶段已复用治理后的配置或结果。";
  return "该阶段已完成。";
}
