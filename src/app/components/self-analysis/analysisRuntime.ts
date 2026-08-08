import type { AnalysisProgressStep, BackendAnalysisResponse } from "../../services/analysisApi";
import type { ModelIntegration } from "../../services/systemConfigApi";
import type { FunAsrInputTarget } from "./domain";

export function modelInvocationIssue(response: BackendAnalysisResponse, selectedModel: ModelIntegration | null) {
  if (!selectedModel) return "";
  const planning = response.intelligent_analysis?.planning_invocation;
  if (planning && !["connected", "skipped"].includes(planning.status)) {
    const reason = planning.message ? ` 原因：${planning.message}` : "";
    return `第一阶段模型未完成调用，已使用受治理默认计划继续执行（${selectedModel.name}）。${reason}`;
  }
  const finalInvocation = response.intelligent_analysis?.model_invocation;
  if (!finalInvocation || finalInvocation.status === "connected") return "";
  const reason = finalInvocation.message ? ` 原因：${finalInvocation.message}` : "";
  return `数据查询已完成；第二阶段模型未完成调用，已保留数据并使用证据型确定性结论（${selectedModel.name}）。${reason}`;
}

export function completedProgressSteps(response: BackendAnalysisResponse): AnalysisProgressStep[] {
  const rowCount = response.skill_results?.[0]?.data?.length || 0;
  const approach = response.intelligent_analysis?.analysis_approach || response.intelligent_analysis?.planning?.analysis_approach || [];
  const planningDetail = approach.length ? `分析方案：${approach.slice(0, 3).join("；")}` : "已完成指标、维度、查询与可视化方案编排。";
  return [
    { step_code: "context_understanding", sequence_no: 10, status: "succeeded", output_refs: [{ label: "理解问题与装载上下文", detail: "已识别业务问题、机构范围和分析上下文。" }] },
    { step_code: "model_planning", sequence_no: 20, status: "succeeded", output_refs: [{ label: "生成分析方案", detail: planningDetail }] },
    { step_code: "data_query", sequence_no: 30, status: "succeeded", output_refs: [{ label: "查询业务数据", detail: `已完成受权限控制的语义查询并返回 ${rowCount} 行结果。`, row_count: rowCount }] },
    { step_code: "evidence_review", sequence_no: 40, status: "succeeded", output_refs: [{ label: "校验口径与证据", detail: "已核对指标口径、执行 SQL、返回字段和数据证据。" }] },
    { step_code: "model_conclusion", sequence_no: 50, status: "succeeded", output_refs: [{ label: "生成分析结论", detail: "已基于实际查询证据生成分析摘要和关键发现。" }] },
    { step_code: "result_finalize", sequence_no: 60, status: "succeeded", output_refs: [{ label: "整理可视化结果", detail: "分析结果、可视化与执行记录已就绪。", task_id: response.task_id }] },
  ];
}

export function modelApplicationModuleForTrigger() {
  return "intelligent_analysis_reasoning";
}

export function speechApplicationModuleForTarget(target: FunAsrInputTarget) {
  return target === "voice" ? "popup_voice_input" : "realtime_voice_input";
}

function modelSupportsApplication(model: ModelIntegration, applicationModule: string) {
  if (model.applicationModule === applicationModule) return true;
  // The backend intentionally uses this placeholder for every text scenario.
  // Keep the picker contract identical so a configured global text model does
  // not disappear from the Intelligent Analysis page.
  return model.applicationModule === "global_text_model" && !["realtime_voice_input", "popup_voice_input"].includes(applicationModule);
}

export function configuredModelForModule(models: ModelIntegration[], applicationModule: string) {
  return models.find((model) => modelSupportsApplication(model, applicationModule) && ["available", "draft"].includes(model.status) && model.testStatus !== "failed") || null;
}

export function modelsForModule(models: ModelIntegration[], applicationModule: string) {
  return models.filter((model) => modelSupportsApplication(model, applicationModule) && ["available", "draft"].includes(model.status) && model.testStatus !== "failed");
}

export function modelApplicationSelection(applicationModule: string, model: ModelIntegration | null) {
  if (applicationModule !== "intelligent_analysis_reasoning" || !model) return null;
  return {
    integrationId: model.id,
    selectedModelName: model.selectedModelName || model.enabledModels?.[0] || "",
  };
}
