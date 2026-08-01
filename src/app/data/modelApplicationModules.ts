export const modelApplicationModuleOptions = [
  { value: "realtime_voice_input", label: "实时语音录入" },
  { value: "popup_voice_input", label: "弹窗语音录入" },
  { value: "intelligent_analysis_reasoning", label: "智能分析推理分析" },
  { value: "weekly_report_conclusion_regeneration", label: "周报结论重新生成" },
  { value: "automatic_analysis", label: "自动分析任务" },
  { value: "memory_extraction", label: "记忆模块" },
  { value: "skill_evolution_learning", label: "Skill自学习与演化" },
] as const;

export type ModelApplicationModule = (typeof modelApplicationModuleOptions)[number]["value"];

export function modelApplicationModuleLabel(value?: string) {
  return modelApplicationModuleOptions.find((option) => option.value === value)?.label || "未分配";
}
