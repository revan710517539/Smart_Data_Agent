import { useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { AppSelect } from "../ui/AppSelect";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "../ui/FormDialog";
import type { AnalysisRow } from "../self-analysis/domain";
import {
  normalizeHexColor,
  resolveProgressDenominator,
  visualizationFilterValues,
  type VisualizationAssociationOperator,
  type VisualizationAssociationRule,
  type VisualizationFilterRule,
  type VisualizationMetricProgressConfig,
  type VisualizationProgressColorMode,
} from "./visualizationDataModel";

const operators: Array<{ value: VisualizationAssociationOperator; label: string }> = [
  { value: "gt", label: "大于" }, { value: "gte", label: "大于等于" }, { value: "eq", label: "等于" }, { value: "lte", label: "小于等于" }, { value: "lt", label: "小于" },
];

const classicPalettes = [
  { name: "雾蓝", source: "Office", colors: ["#B4C7E7", "#5B9BD5"] },
  { name: "松绿", source: "Excel", colors: ["#A9D18E", "#548235"] },
  { name: "飞书蓝", source: "Feishu", colors: ["#BACEFD", "#3370FF"] },
  { name: "岩灰", source: "Primer", colors: ["#D0D7DE", "#57606A"] },
  { name: "柔金", source: "Office", colors: ["#FFE699", "#BF9000"] },
  { name: "青瓷", source: "Feishu", colors: ["#B7EBD7", "#00A870"] },
  { name: "紫藤", source: "Primer", colors: ["#D8B9FF", "#8250DF"] },
  { name: "湖蓝", source: "Primer", colors: ["#B6E3FF", "#0969DA"] },
  { name: "珊瑚", source: "Primer", colors: ["#FFCECB", "#CF222E"] },
  { name: "黛青", source: "Feishu", colors: ["#C6D4F3", "#395F98"] },
] as const;

const primaryPalettes = classicPalettes.slice(0, 4);
const additionalPalettes = classicPalettes.slice(4);

let editorId = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${editorId++}`;
const newDenominatorRule = (field = ""): VisualizationFilterRule => ({ id: nextId("denominator"), field, operator: "in", values: [] });
const newAssociationRule = (metricField: string): VisualizationAssociationRule => ({ id: nextId("association"), source: "progress", operator: "gte", threshold: 100, targetField: metricField, style: "background", color: "#fff1b8", replacementValue: "" });
const inputClass = "h-9 rounded-lg border border-[#dfe7e2] bg-white px-2.5 text-[11px] text-[#34443c] outline-none focus:border-[#8fbaa2]";

export function TableProgressDialog({ rows, metricField, metricFields, dimensionFields, labels, initial, onCancel, onRemove, onSave }: {
  rows: AnalysisRow[];
  metricField: string;
  metricFields: string[];
  dimensionFields: string[];
  labels: Record<string, string>;
  initial?: VisualizationMetricProgressConfig;
  onCancel: () => void;
  onRemove: () => void;
  onSave: (config: VisualizationMetricProgressConfig) => void;
}) {
  const [config, setConfig] = useState<VisualizationMetricProgressConfig>(() => initial ? structuredClone(initial) : {
    metricField,
    denominatorRules: [newDenominatorRule(dimensionFields[0] || "")],
    color: "#B4C7E7",
    colorEnd: "#5B9BD5",
    colorMode: "gradient",
    associationRules: [],
  });
  const [associationOpen, setAssociationOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const denominator = useMemo(() => resolveProgressDenominator(rows, config), [config, rows]);
  const denominatorLabel = config.denominatorRules.filter((rule) => rule.field && rule.values.length).map((rule) => `${labels[rule.field] || rule.field}=${rule.values[0]}`).join(" 且 ") || "尚未指定";
  const updateDenominator = (id: string, patch: Partial<VisualizationFilterRule>) => setConfig((current) => ({ ...current, denominatorRules: current.denominatorRules.map((rule) => rule.id === id ? { ...rule, ...patch } : rule) }));
  const updateAssociation = (id: string, patch: Partial<VisualizationAssociationRule>) => setConfig((current) => ({ ...current, associationRules: current.associationRules.map((rule) => rule.id === id ? { ...rule, ...patch } : rule) }));
  const statusText = denominator.status === "ready" ? `已唯一匹配：${denominatorLabel}` : denominator.status === "multiple" ? `当前组合匹配 ${denominator.matches.length} 行，请继续添加维度条件` : denominator.status === "missing" ? "当前组合未匹配任何行" : denominator.status === "zero" ? "分母行指标值为 0，无法计算进度" : denominator.status === "non_numeric" ? "分母行指标值不是有效数值" : "请选择维度和值，唯一圈定分母所在行";
  const targetFields = [...dimensionFields, ...metricFields.filter((field) => !dimensionFields.includes(field))];
  const progressFill = config.colorMode === "solid"
    ? { backgroundColor: normalizeHexColor(config.color) }
    : config.colorMode === "reverse_gradient"
      ? { backgroundImage: `linear-gradient(90deg, ${normalizeHexColor(config.colorEnd, config.color)}, ${normalizeHexColor(config.color)})` }
      : { backgroundImage: `linear-gradient(90deg, ${normalizeHexColor(config.color)}, ${normalizeHexColor(config.colorEnd, config.color)})` };
  const setPalette = (colors: readonly [string, string]) => setConfig((current) => ({ ...current, color: colors[0], colorEnd: colors[1] }));
  const paletteButton = (palette: (typeof classicPalettes)[number], location: "primary" | "additional") => {
    const selected = normalizeHexColor(config.color) === palette.colors[0].toLowerCase() && normalizeHexColor(config.colorEnd, config.color) === palette.colors[1].toLowerCase();
    return <button key={palette.name} type="button" onClick={() => { setPalette(palette.colors); if (location === "additional") setPaletteOpen(false); }} aria-label={`应用${palette.name}进度配色`} aria-pressed={selected} title={`${palette.name} · ${palette.source}`} className={`h-8 w-10 rounded-lg border p-1 transition-colors ${selected ? "border-[#5d8d72] ring-2 ring-[#5d8d72]/15" : "border-[#dfe7e2] hover:border-[#b9cbc1]"}`} data-progress-palette={palette.name} data-progress-palette-location={location}><span className="block h-full w-full rounded-[5px]" style={{ backgroundImage: `linear-gradient(135deg, ${palette.colors[0]} 0 50%, ${palette.colors[1]} 50% 100%)` }} /></button>;
  };

  return <FormDialog
    title={`显示进度 · ${labels[metricField] || metricField}`}
    description="指定唯一分母行，设置进度呈现和条件联动。"
    onClose={onCancel}
    widthClassName="max-w-[1044px]"
    heightClassName="max-h-[min(744px,calc(100vh-108px))]"
    zIndexClassName="z-[240]"
    bodyClassName="divide-y divide-[#edf1ee]"
    ariaLabel={`${labels[metricField] || metricField}显示进度配置`}
    dataAttributes={{ "data-table-progress-dialog": "true", "data-visual-interactive": "true" }}
    footer={<>{initial && <button type="button" onClick={onRemove} className="mr-auto h-9 rounded-lg px-3 text-[11px] text-[#b14f4f] hover:bg-[#fff4f3]">取消显示进度</button>}<FormDialogCancelButton onClick={onCancel}>取消</FormDialogCancelButton><FormDialogPrimaryButton disabled={denominator.status !== "ready"} onClick={() => onSave({
      ...config,
      color: normalizeHexColor(config.color),
      colorEnd: normalizeHexColor(config.colorEnd, config.color),
      colorMode: config.colorMode === "solid" ? "solid" : config.colorMode === "reverse_gradient" ? "reverse_gradient" : "gradient",
      associationRules: config.associationRules.map((rule) => ({ ...rule, color: normalizeHexColor(rule.color, "#fff1b8"), replacementValue: String(rule.replacementValue || "").trim().slice(0, 120) })),
    })}>确定</FormDialogPrimaryButton></>}
  >
    <section className="pb-4" data-progress-formula="true">
      <div className="mb-2 text-[11px] font-medium text-[#34443c]">进度公式</div>
      <div className="flex min-h-9 flex-wrap items-center gap-2 rounded-lg bg-[#f6f8f7] px-3 text-[11px] text-[#53615a]"><span>当前单元格 [{labels[metricField] || metricField}]</span><span className="text-[#93a099]">÷</span><span>{denominatorLabel}</span><span className="text-[#93a099]">× 100%</span></div>
    </section>

    <section className="py-4" data-progress-denominator="true">
      <div className="mb-3 flex items-center justify-between"><div><div className="text-[11px] font-medium text-[#34443c]">分母指定</div><div className="mt-0.5 text-[9px] text-[#8a9690]">所有条件同时成立，并且只匹配一行</div></div><span className="rounded-md bg-[#edf5f0] px-2 py-1 text-[9px] font-medium text-[#46705c]">且</span></div>
      <div className="space-y-2 border-l border-[#d6e5dc] pl-3">{config.denominatorRules.map((rule, index) => <div key={rule.id}>{index > 0 && <div className="mb-1 flex items-center gap-2"><span className="-ml-[23px] inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-[#edf5f0] px-1 text-[9px] font-medium text-[#46705c]">且</span><span className="h-px flex-1 bg-[#edf1ee]" /></div>}<div className="grid grid-cols-[minmax(150px,1fr)_minmax(180px,1.2fr)_36px] gap-2"><AppSelect value={rule.field} onChange={(event) => updateDenominator(rule.id, { field: event.target.value, values: [] })} className="!h-9 text-[11px]"><option value="">选择维度</option>{dimensionFields.map((field) => <option key={field} value={field}>{labels[field] || field}</option>)}</AppSelect><AppSelect value={rule.values[0] || ""} onChange={(event) => updateDenominator(rule.id, { values: event.target.value ? [event.target.value] : [] })} disabled={!rule.field} className="!h-9 text-[11px]"><option value="">选择具体值</option>{visualizationFilterValues(rows, rule.field).map((value) => <option key={value} value={value}>{value}</option>)}</AppSelect><button type="button" onClick={() => setConfig((current) => ({ ...current, denominatorRules: current.denominatorRules.length > 1 ? current.denominatorRules.filter((item) => item.id !== rule.id) : [newDenominatorRule(dimensionFields[0] || "")] }))} className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[#9aa49f] hover:bg-[#f7f8f8] hover:text-[#b14f4f]" aria-label="删除分母筛选"><Trash2 className="h-3.5 w-3.5" /></button></div></div>)}</div>
      <div className="mt-3 flex items-center gap-3"><button type="button" onClick={() => setConfig((current) => ({ ...current, denominatorRules: [...current.denominatorRules, newDenominatorRule(dimensionFields.find((field) => !current.denominatorRules.some((rule) => rule.field === field)) || dimensionFields[0] || "")] }))} disabled={!dimensionFields.length} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-dashed border-[#cdded4] px-3 text-[10px] font-medium text-[#4f6f5f] hover:bg-[#f7faf8] disabled:opacity-40"><Plus className="h-3.5 w-3.5" />添加筛选</button><div className={`min-w-0 flex-1 rounded-lg px-3 py-2 text-[10px] ${denominator.status === "ready" ? "bg-[#edf7f1] text-[#2f7655]" : "bg-[#fff8ee] text-[#8a6a2b]"}`} role="status" data-progress-denominator-status={denominator.status}>{denominator.status === "ready" && <Check className="mr-1 inline h-3 w-3" />}{statusText}</div></div>
    </section>

    <section className="py-4" data-progress-color="true">
      <div className="mb-3 text-[11px] font-medium text-[#34443c]">进度条颜色</div>
      <div className="grid gap-3 lg:grid-cols-[minmax(250px,0.72fr)_minmax(500px,1.28fr)]">
        <div className="flex items-center gap-2.5"><label className="relative h-9 w-11 shrink-0 overflow-hidden rounded-lg border border-[#dfe7e2]" title="选择起始颜色"><input type="color" value={normalizeHexColor(config.color)} onChange={(event) => setConfig((current) => ({ ...current, color: event.target.value }))} className="absolute -inset-2 h-14 w-16 cursor-pointer" aria-label="选择进度条颜色" /></label><input value={config.color} onChange={(event) => setConfig((current) => ({ ...current, color: event.target.value }))} onBlur={() => setConfig((current) => ({ ...current, color: normalizeHexColor(current.color) }))} className={`${inputClass} w-28 font-mono uppercase`} aria-label="进度条颜色码" /><div className="relative h-8 min-w-24 flex-1 overflow-hidden rounded-lg bg-[#f1f3f2]" data-progress-color-preview="true"><div className="absolute inset-y-0 left-0 w-2/3" style={progressFill} /></div></div>
        <div className="flex min-w-0 items-center justify-end gap-3">
          <div className="relative flex h-9 shrink-0 items-center gap-1.5" data-progress-classic-palettes="true">{primaryPalettes.map((palette) => paletteButton(palette, "primary"))}<button type="button" onClick={() => setPaletteOpen((value) => !value)} aria-label="展开更多进度配色" aria-expanded={paletteOpen} className={`inline-flex h-8 w-9 items-center justify-center rounded-lg border transition-colors ${paletteOpen ? "border-[#8fbaa2] bg-[#f4f8f5] text-[#3f7458]" : "border-[#dfe7e2] bg-white text-[#7c8982] hover:border-[#b9cbc1]"}`} data-progress-palette-more="true"><ChevronDown className={`h-3.5 w-3.5 transition-transform ${paletteOpen ? "rotate-180" : ""}`} /></button>{paletteOpen && <div className="absolute right-0 top-[calc(100%+6px)] z-30 grid grid-cols-3 gap-1.5 rounded-xl border border-[#dfe7e2] bg-white p-2 shadow-[0_10px_28px_rgba(34,52,43,0.13)]" data-progress-palette-more-panel="true">{additionalPalettes.map((palette) => paletteButton(palette, "additional"))}</div>}</div>
          <div className="grid h-9 min-w-[248px] grid-cols-3 rounded-lg bg-[#f1f4f2] p-1" data-progress-color-mode="true">{([{"value":"gradient","label":"正向渐变色"},{"value":"reverse_gradient","label":"反向渐变色"},{"value":"solid","label":"完全色"}] as Array<{ value: VisualizationProgressColorMode; label: string }>).map((item) => <button key={item.value} type="button" onClick={() => setConfig((current) => ({ ...current, colorMode: item.value }))} aria-pressed={(config.colorMode || "gradient") === item.value} className={`rounded-md px-1.5 text-[10px] font-medium transition-colors ${(config.colorMode || "gradient") === item.value ? "bg-white text-[#2f6f50] shadow-sm" : "text-[#7a8981] hover:text-[#53615a]"}`} data-progress-color-mode-option={item.value}>{item.label}</button>)}</div>
        </div>
      </div>
    </section>

    <section className="pt-4" data-progress-association="true">
      <button type="button" onClick={() => setAssociationOpen((value) => !value)} className="flex w-full items-center justify-between py-1 text-left"><span><span className="block text-[11px] font-medium text-[#34443c]">关联规则</span><span className="mt-0.5 block text-[9px] text-[#8a9690]">条件满足后修改目标单元格的底色、字体或显示值</span></span>{associationOpen ? <ChevronDown className="h-4 w-4 text-[#8a9690]" /> : <ChevronRight className="h-4 w-4 text-[#8a9690]" />}</button>
      {associationOpen && <div className="mt-3 overflow-x-auto" data-progress-association-editor="true"><div className="min-w-[930px] space-y-2">{config.associationRules.length > 0 && <div className="grid grid-cols-[92px_108px_90px_minmax(150px,1fr)_92px_170px_36px] gap-2 px-2 text-[9px] text-[#8a9690]"><span>条件来源</span><span>比较</span><span>条件值</span><span>目标单元格</span><span>效果</span><span>效果值</span><span /></div>}{config.associationRules.map((rule) => <div key={rule.id} className="grid grid-cols-[92px_108px_90px_minmax(150px,1fr)_92px_170px_36px] items-center gap-2 rounded-xl bg-[#f7f9f8] p-2" data-association-rule-row={rule.id}><AppSelect value={rule.source} onChange={(event) => updateAssociation(rule.id, { source: event.target.value as "metric" | "progress" })} className="!h-9 text-[10px]"><option value="progress">进度</option><option value="metric">指标值</option></AppSelect><AppSelect value={rule.operator} onChange={(event) => updateAssociation(rule.id, { operator: event.target.value as VisualizationAssociationOperator })} className="!h-9 text-[10px]">{operators.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</AppSelect><input type="number" value={rule.threshold} onChange={(event) => updateAssociation(rule.id, { threshold: Number(event.target.value) })} className={`${inputClass} w-full`} aria-label="关联规则条件值" /><AppSelect value={rule.targetField} onChange={(event) => updateAssociation(rule.id, { targetField: event.target.value })} className="!h-9 text-[10px]"><option value={metricField}>当前单元格</option>{targetFields.filter((field) => field !== metricField).map((field) => <option key={field} value={field}>{labels[field] || field}</option>)}</AppSelect><AppSelect value={rule.style} onChange={(event) => updateAssociation(rule.id, { style: event.target.value as "background" | "text" | "value" })} className="!h-9 text-[10px]"><option value="background">底色</option><option value="text">字体</option><option value="value">枚举值</option></AppSelect>{rule.style === "value" ? <input value={rule.replacementValue || ""} onChange={(event) => updateAssociation(rule.id, { replacementValue: event.target.value })} className={`${inputClass} w-full`} placeholder="填写显示值" aria-label="关联规则枚举值" /> : <div className="grid h-9 grid-cols-[38px_1fr] overflow-hidden rounded-lg border border-[#dfe7e2] bg-white"><label className="relative overflow-hidden border-r border-[#dfe7e2]"><input type="color" value={normalizeHexColor(rule.color, "#fff1b8")} onChange={(event) => updateAssociation(rule.id, { color: event.target.value })} className="absolute -inset-2 h-14 w-14 cursor-pointer" aria-label="关联规则颜色" /></label><input value={rule.color} onChange={(event) => updateAssociation(rule.id, { color: event.target.value })} onBlur={() => updateAssociation(rule.id, { color: normalizeHexColor(rule.color, "#fff1b8") })} className="min-w-0 px-2 font-mono text-[10px] uppercase outline-none" aria-label="关联规则颜色码" /></div>}<button type="button" onClick={() => setConfig((current) => ({ ...current, associationRules: current.associationRules.filter((item) => item.id !== rule.id) }))} className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[#9aa49f] hover:bg-white hover:text-[#b14f4f]" aria-label="删除关联规则"><Trash2 className="h-3.5 w-3.5" /></button></div>)}<button type="button" onClick={() => setConfig((current) => ({ ...current, associationRules: [...current.associationRules, newAssociationRule(metricField)] }))} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-dashed border-[#cdded4] px-3 text-[10px] font-medium text-[#4f6f5f] hover:bg-[#f7faf8]"><Plus className="h-3.5 w-3.5" />添加关联规则</button></div></div>}
    </section>
  </FormDialog>;
}
