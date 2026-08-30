import type { ScriptTab } from "./domain";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "../ui/FormDialog";

export function AnalysisScriptEditor({
  open,
  sqlScript,
  pythonScript,
  analysisScenarios,
  analysisSummary,
  analysisPlan,
  scriptPlanName,
  activeScriptTab,
  onSqlScriptChange,
  onPythonScriptChange,
  onAnalysisScenariosChange,
  onAnalysisSummaryChange,
  onAnalysisPlanChange,
  onScriptPlanNameChange,
  onActiveScriptTabChange,
  onClose,
  onSave,
  onExecute,
}: {
  open: boolean;
  sqlScript: string;
  pythonScript: string;
  analysisScenarios: string;
  analysisSummary: string;
  analysisPlan: string;
  scriptPlanName: string;
  activeScriptTab: ScriptTab;
  onSqlScriptChange: (value: string) => void;
  onPythonScriptChange: (value: string) => void;
  onAnalysisScenariosChange: (value: string) => void;
  onAnalysisSummaryChange: (value: string) => void;
  onAnalysisPlanChange: (value: string) => void;
  onScriptPlanNameChange: (value: string) => void;
  onActiveScriptTabChange: (tab: ScriptTab) => void;
  onClose: () => void;
  onSave: () => void;
  onExecute: () => void;
}) {
  if (!open) return null;
  return (
    <FormDialog title="脚本编辑" description="编辑分析思路、SQL、Python 可视化和 AI 总结后可保存或执行重跑" onClose={onClose} widthClassName="max-w-[1040px]" heightClassName="max-h-[92vh]" bodyClassName="grid gap-4 lg:grid-cols-[minmax(0,1.16fr)_minmax(300px,0.84fr)]" footer={<><FormDialogCancelButton onClick={onClose}>取消</FormDialogCancelButton><FormDialogCancelButton onClick={onSave}>保存</FormDialogCancelButton><FormDialogPrimaryButton onClick={onExecute}>执行</FormDialogPrimaryButton></>}>
          <div className="flex h-[470px] min-h-0 flex-col overflow-hidden rounded-lg border border-[#24252a] bg-[#101114]">
            <div className="flex gap-1 border-b border-white/10 bg-[#15161a] px-2 py-2">
              {[
                { key: "sql", label: "SQL" },
                { key: "python", label: "Python" },
                { key: "scenarios", label: "指标情景" },
                { key: "summary", label: "AI总结" },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => onActiveScriptTabChange(tab.key as ScriptTab)}
                  className={`rounded-md px-3 py-1.5 text-[12px] transition-colors ${
                    activeScriptTab === tab.key
                      ? "bg-white text-[#1d1d1f]"
                      : "text-[#c7c7cc] hover:bg-white/10 hover:text-white"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <textarea
              value={
                activeScriptTab === "sql"
                  ? sqlScript
                  : activeScriptTab === "python"
                    ? pythonScript
                    : activeScriptTab === "scenarios"
                      ? analysisScenarios
                      : analysisSummary
              }
              onChange={(event) => {
                if (activeScriptTab === "sql") onSqlScriptChange(event.target.value);
                else if (activeScriptTab === "python") onPythonScriptChange(event.target.value);
                else if (activeScriptTab === "scenarios") onAnalysisScenariosChange(event.target.value);
                else onAnalysisSummaryChange(event.target.value);
              }}
              className="min-h-0 flex-1 resize-none !bg-[#101114] px-4 py-3 font-mono text-[12px] leading-[1.7] !text-[#f5f5f7] outline-none"
              style={{ colorScheme: "dark" }}
            />
          </div>
          <div className="flex min-h-[470px] flex-col rounded-lg border border-[#e5e5ea] bg-[#fafbfc] p-4">
            <label className="mb-3 block">
              <span className="mb-1 block text-[12px] text-[#1d1d1f]">分析思路名称</span>
              <input
                value={scriptPlanName}
                onChange={(event) => onScriptPlanNameChange(event.target.value)}
                className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
              />
            </label>
            <div className="mb-2 text-[12px] text-[#1d1d1f]">分析思路</div>
            <textarea
              value={analysisPlan}
              onChange={(event) => onAnalysisPlanChange(event.target.value)}
              placeholder="写清楚分析目的、指标、维度、筛选条件、校验规则和输出口径。"
              className="min-h-[330px] flex-1 rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[13px] text-[#3a3a3c] leading-[1.7] outline-none focus:border-[#c7c7cc] resize-none"
            />
          </div>
    </FormDialog>
  );
}
