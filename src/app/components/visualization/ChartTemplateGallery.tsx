import { Check } from "lucide-react";
import type { CSSProperties } from "react";
import { builtInChartTemplates, type BuiltInChartTemplate } from "./chartStyleTemplates";
import type { VisualizationChartStyleConfig } from "./visualizationDataModel";

function ChartTemplatePreview({ style }: { style: VisualizationChartStyleConfig }) {
  const heights = [34, 66, 48, 82, 58, 74];
  return <div className="relative h-[42px] overflow-hidden rounded-[4px] border px-1.5 pb-1.5 pt-1" style={{ backgroundColor: style.backgroundColor, borderColor: style.axisColor }} data-chart-template-preview="true">
    <div className="absolute inset-x-1.5 top-[13px] border-t border-dashed" style={{ borderColor: style.gridColor }} />
    <div className="absolute inset-x-1.5 top-[24px] border-t border-dashed" style={{ borderColor: style.gridColor }} />
    <div className="flex h-full items-end gap-1 border-b border-l pl-1" style={{ borderColor: style.axisColor }}>
      {heights.map((height, index) => <span key={index} className="min-w-0 flex-1 rounded-t-[1px]" style={{ height: `${height}%`, backgroundColor: style.palette[index % style.palette.length], borderTopLeftRadius: style.barRadius / 3, borderTopRightRadius: style.barRadius / 3 }} />)}
    </div>
  </div>;
}

function TemplateButton({ template, selected, onApply }: { template: BuiltInChartTemplate; selected: boolean; onApply: () => void }) {
  return <button type="button" onClick={onApply} className={`min-w-0 rounded-lg border p-1 text-left transition-colors ${selected ? "border-[#6a9b7e] bg-[#f3f8f5] ring-1 ring-[#6a9b7e]/10" : "border-[#e2e8e4] bg-white hover:border-[#b9ccc1] hover:bg-[#fafcfb]"}`} aria-pressed={selected} data-chart-template-built-in={template.id}>
    <ChartTemplatePreview style={template.style} />
    <div className="mt-1 flex items-center justify-between gap-1"><span className="truncate text-[8px] font-medium text-[#3d4c44]">{template.name}</span>{selected ? <Check className="h-2.5 w-2.5 shrink-0 text-[#39805c]" /> : null}</div>
    <div className="truncate text-[7px] text-[#98a39d]">{template.sourceLabel}</div>
  </button>;
}

export function ChartTemplateGallery({ currentTemplateId, position, onApply }: { currentTemplateId: string; position: CSSProperties; onApply: (template: BuiltInChartTemplate) => void }) {
  return <div className="fixed z-[180] flex max-h-[min(620px,calc(100vh-80px))] w-[min(22rem,calc(100vw-16px))] flex-col overflow-hidden rounded-xl border border-[#dce7df] bg-white shadow-xl shadow-black/[0.1]" style={position} data-chart-template-gallery="true" data-visual-interactive="true">
    <div className="shrink-0 border-b border-[#edf1ee] px-3 py-2"><div className="text-[10px] font-medium text-[#34443c]">样式模板</div><div className="text-[8px] text-[#8a9690]">只调整图形、配色、字体、留白与尺寸，保留当前数据和交互</div></div>
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2" data-chart-template-scroll="true">
      <div className="mb-2 flex items-center justify-between"><span className="text-[9px] font-medium text-[#6f7d76]">经典图表样式</span><span className="text-[8px] text-[#a1aaa5]">10 个</span></div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">{builtInChartTemplates.map((template) => <TemplateButton key={template.id} template={template} selected={currentTemplateId === template.id} onApply={() => onApply(template)} />)}</div>
    </div>
  </div>;
}
