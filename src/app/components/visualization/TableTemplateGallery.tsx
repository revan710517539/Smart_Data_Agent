import { Check, Save, Trash2 } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "../ui/FormDialog";
import { builtInTableTemplates, type BuiltInTableTemplate, type CustomTableTemplate } from "./tableStyleTemplates";
import type { VisualizationTableStyleConfig } from "./visualizationDataModel";

function TableTemplatePreview({ style, progressColors }: { style: VisualizationTableStyleConfig; progressColors?: readonly [string, string] }) {
  const rows = style.bandedRows ? [style.bodyBackground, style.alternateRowBackground, style.bodyBackground] : [style.bodyBackground, style.bodyBackground, style.bodyBackground];
  return <div className="overflow-hidden rounded-[4px] border" style={{ borderColor: style.borderColor, fontFamily: style.fontFamily === "mono" ? "ui-monospace, monospace" : style.fontFamily === "serif" ? "Georgia, serif" : "inherit" }} data-table-template-preview="true">
    <div className="grid h-2.5 grid-cols-[1.2fr_.8fr_.8fr]" style={{ backgroundColor: style.headerBackground, color: style.headerTextColor }}><span className="border-r" style={{ borderColor: style.headerBorderColor }} /><span className="border-r" style={{ borderColor: style.headerBorderColor }} /><span /></div>
    {rows.map((background, index) => <div key={index} className="grid h-1.5 grid-cols-[1.2fr_.8fr_.8fr]" style={{ backgroundColor: background }}><span className="relative border-r" style={{ borderColor: style.borderColor }}><i className="absolute left-0.5 top-0.5 block h-px w-4/5 rounded-full" style={{ backgroundColor: index === 0 && style.emphasizeFirstColumn ? style.accentColor : style.bodyTextColor, opacity: index === 0 && style.emphasizeFirstColumn ? 0.7 : 0.18 }} /></span><span className="relative border-r" style={{ borderColor: style.borderColor }}>{index === 1 && <i className="absolute inset-y-px left-0.5 w-3/5 rounded-[1px]" style={{ backgroundImage: `linear-gradient(90deg, ${progressColors?.[0] || style.accentColor}, ${progressColors?.[1] || style.accentColor})`, opacity: 0.72 }} />}</span><span /></div>)}
    <div className="h-1" style={{ backgroundColor: style.totalBackground }} />
  </div>;
}

function BuiltInTemplateButton({ template, selected, onApply }: { template: BuiltInTableTemplate; selected: boolean; onApply: () => void }) {
  return <button type="button" onClick={onApply} className={`group min-w-0 rounded-lg border p-1 text-left transition-colors ${selected ? "border-[#6a9b7e] bg-[#f3f8f5] ring-1 ring-[#6a9b7e]/10" : "border-[#e2e8e4] bg-white hover:border-[#b9ccc1] hover:bg-[#fafcfb]"}`} aria-pressed={selected} data-table-template-built-in={template.id}>
    <TableTemplatePreview style={template.style} progressColors={template.progressColors} />
    <div className="mt-1 flex items-center justify-between gap-1"><span className="truncate text-[8px] font-medium text-[#3d4c44]">{template.name}</span>{selected && <Check className="h-2.5 w-2.5 shrink-0 text-[#39805c]" />}</div>
    <div className="truncate text-[7px] text-[#98a39d]">{template.sourceLabel}</div>
  </button>;
}

function CustomTemplateButton({ template, selected, featured = false, onApply, onDelete }: { template: CustomTableTemplate; selected: boolean; featured?: boolean; onApply: () => void; onDelete?: () => void }) {
  return <div className={`group relative min-w-0 rounded-lg border p-1 transition-colors ${selected ? "border-[#6a9b7e] bg-[#f3f8f5] ring-1 ring-[#6a9b7e]/10" : "border-[#e2e8e4] bg-white hover:border-[#b9ccc1]"}`} data-table-template-custom={template.id} data-table-template-featured={featured ? "true" : undefined}>
    <button type="button" onClick={onApply} className="block w-full text-left" aria-pressed={selected}><TableTemplatePreview style={template.tableStyle} progressColors={template.previewProgressColors} /><div className="mt-1 flex items-center justify-between gap-1"><span className="truncate text-[8px] font-medium text-[#3d4c44]">{template.name}</span>{selected && <Check className="h-2.5 w-2.5 shrink-0 text-[#39805c]" />}</div><div className="truncate text-[7px] text-[#98a39d]">{featured ? "内置 · " : ""}{template.metricRankings.length} 排名 · {template.metricProgress.length} 进度</div></button>
    {onDelete && <button type="button" onClick={(event) => { event.stopPropagation(); onDelete(); }} className="absolute right-1 top-1 hidden h-5 w-5 items-center justify-center rounded bg-white/95 text-[#9aa49f] shadow-sm hover:text-[#b14f4f] group-hover:flex" aria-label={`删除模板：${template.name}`} data-delete-table-template={template.id}><Trash2 className="h-2.5 w-2.5" /></button>}
  </div>;
}

export function TableTemplateGallery({ currentTemplateId, featuredTemplates = [], customTemplates, position, onApplyBuiltIn, onApplyCustom, onDeleteCustom }: { currentTemplateId: string; featuredTemplates?: CustomTableTemplate[]; customTemplates: CustomTableTemplate[]; position: CSSProperties; onApplyBuiltIn: (template: BuiltInTableTemplate) => void; onApplyCustom: (template: CustomTableTemplate) => void; onDeleteCustom: (template: CustomTableTemplate) => void }) {
  return <div className="fixed z-[180] flex max-h-[min(900px,calc(100vh-80px))] w-[min(22rem,calc(100vw-16px))] flex-col overflow-hidden rounded-xl border border-[#dce7df] bg-white shadow-xl shadow-black/[0.1]" style={position} data-table-template-gallery="true" data-visual-interactive="true">
    <div className="shrink-0 border-b border-[#edf1ee] px-3 py-2"><div className="text-[10px] font-medium text-[#34443c]">样式模板</div><div className="text-[8px] text-[#8a9690]">仅复制样式与规则，保留当前表格数据</div></div>
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2" data-table-template-scroll="true">
      <div className="mb-2 flex items-center justify-between"><span className="text-[9px] font-medium text-[#6f7d76]">经典样式</span><span className="text-[8px] text-[#a1aaa5]">10 个</span></div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">{builtInTableTemplates.map((template) => <BuiltInTemplateButton key={template.id} template={template} selected={currentTemplateId === template.id} onApply={() => onApplyBuiltIn(template)} />)}</div>
      <div className="mb-1.5 mt-3 flex items-center justify-between"><span className="text-[9px] font-medium text-[#6f7d76]">自定义表格样式</span><span className="text-[8px] text-[#a1aaa5]">精选 {featuredTemplates.length} · 自定义 {customTemplates.length}/20</span></div>
      {featuredTemplates.length || customTemplates.length ? <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">{featuredTemplates.map((template) => <CustomTemplateButton key={template.id} template={template} featured selected={currentTemplateId === template.id} onApply={() => onApplyCustom(template)} />)}{customTemplates.map((template) => <CustomTemplateButton key={template.id} template={template} selected={currentTemplateId === template.id} onApply={() => onApplyCustom(template)} onDelete={() => onDeleteCustom(template)} />)}</div> : <div className="rounded-lg border border-dashed border-[#dce6e0] bg-[#fafcfb] px-2 py-3 text-center text-[8px] text-[#96a19b]">在更多菜单中选择“保存模板”后显示在这里</div>}
    </div>
  </div>;
}

export function SaveTableTemplateDialog({ suggestedName, onCancel, onSave }: { suggestedName: string; onCancel: () => void; onSave: (name: string) => void }) {
  const [name, setName] = useState(suggestedName.slice(0, 60));
  return <FormDialog title="保存表格模板" description="保存当前表格的样式、排名、进度、触发规则和计算列；不会保存数据、筛选条件或行内容。" onClose={onCancel} widthClassName="max-w-[480px]" zIndexClassName="z-[260]" ariaLabel="保存表格模板" dataAttributes={{ "data-save-table-template-dialog": "true", "data-visual-interactive": "true" }} footer={<><FormDialogCancelButton onClick={onCancel}>取消</FormDialogCancelButton><FormDialogPrimaryButton disabled={!name.trim()} onClick={() => onSave(name.trim())}><Save className="mr-1 h-3.5 w-3.5" />保存</FormDialogPrimaryButton></>}>
    <label className="block"><span className="mb-1.5 block text-[10px] font-medium text-[#53615a]">模板名称</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && name.trim()) onSave(name.trim()); }} maxLength={60} className="h-10 w-full rounded-lg border border-[#dfe7e2] bg-white px-3 text-[12px] text-[#34443c] outline-none focus:border-[#86b49a]" aria-label="表格模板名称" /></label>
    <div className="mt-3 rounded-lg bg-[#f4f8f5] px-3 py-2 text-[9px] leading-5 text-[#617268]">模板按当前租户和用户保存在本浏览器，最多 20 个。套用到新表时优先匹配字段 ID，其次匹配唯一的显示名称。</div>
  </FormDialog>;
}
