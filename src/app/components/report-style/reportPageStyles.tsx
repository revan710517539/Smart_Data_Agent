import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Check, ChevronDown, LayoutTemplate } from "lucide-react";
import type { VisualizationType } from "../self-analysis/domain";
import type { VisualizationCardConfig } from "../visualization/visualizationDataModel";
import { chartTemplateById } from "../visualization/chartStyleTemplates";
import { builtInTableTemplates } from "../visualization/tableStyleTemplates";

export const DEFAULT_REPORT_PAGE_STYLE_ID = "balanced-canvas";

export type ReportPageStyleId =
  | "executive-overview"
  | "trend-story"
  | "variance-benchmark"
  | "risk-watch"
  | "operations-dense"
  | "segment-lens"
  | "funnel-journey"
  | "board-brief"
  | "evidence-ledger"
  | "balanced-canvas";

type ReportPageStyleTemplate = {
  id: ReportPageStyleId;
  name: string;
  method: string;
  description: string;
  chartTemplateId: string;
  tableTemplateId: string;
  borderless: boolean;
  order: "natural" | "kpi-first" | "trend-first" | "comparison-first" | "risk-first" | "table-first" | "segment-first" | "funnel-first";
  spans: number[];
  heights: number[];
  tokens: {
    canvas: string;
    surface: string;
    border: string;
    title: string;
    muted: string;
    accent: string;
    radius: number;
    gap: number;
    shadow: string;
    font: string;
  };
};

// Original template definitions. Public BI references inform the analytical
// hierarchy, while all tokens, layout sequences and names are authored here.
export const reportPageStyleTemplates: ReportPageStyleTemplate[] = [
  { id: "executive-overview", name: "经营总览", method: "关键指标优先", description: "先看核心指标，再看主趋势与明细。", chartTemplateId: "chart-jade", tableTemplateId: "handsontable-main", borderless: false, order: "kpi-first", spans: [4, 4, 4, 8, 4, 6, 6, 12], heights: [250, 250, 250, 410, 410, 350, 350, 460], tokens: { canvas: "#F4F7F5", surface: "#FBFDFC", border: "#DCE7E0", title: "#20372D", muted: "#718079", accent: "#287557", radius: 12, gap: 14, shadow: "0 8px 24px rgba(35,72,55,.05)", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "trend-story", name: "趋势叙事", method: "时间趋势展开", description: "主趋势占满首屏，再承接拆解指标。", chartTemplateId: "chart-deep-sea", tableTemplateId: "handsontable-horizon", borderless: true, order: "trend-first", spans: [12, 6, 6, 4, 4, 4, 12], heights: [440, 340, 340, 250, 250, 250, 460], tokens: { canvas: "#F3F6F9", surface: "#FFFFFF", border: "#D8E2EA", title: "#23394A", muted: "#6E7E89", accent: "#2D6694", radius: 10, gap: 16, shadow: "none", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "variance-benchmark", name: "差异对标", method: "同类比较", description: "并列对照差异，再用宽表解释来源。", chartTemplateId: "chart-graphite", tableTemplateId: "tabulator-modern", borderless: false, order: "comparison-first", spans: [6, 6, 8, 4, 6, 6, 12], heights: [370, 370, 400, 400, 340, 340, 500], tokens: { canvas: "#F5F6F7", surface: "#FFFFFF", border: "#D8DEE2", title: "#30383F", muted: "#737D85", accent: "#3B6C91", radius: 6, gap: 12, shadow: "0 1px 3px rgba(48,56,63,.06)", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "risk-watch", name: "风险监测", method: "异常优先", description: "风险与偏离项前置，正常项保持克制。", chartTemplateId: "chart-slate-amber", tableTemplateId: "excel-gold", borderless: false, order: "risk-first", spans: [8, 4, 6, 6, 12, 6, 6], heights: [420, 300, 360, 360, 500, 340, 340], tokens: { canvas: "#F7F6F2", surface: "#FFFDF9", border: "#E2DCCF", title: "#403E37", muted: "#817D72", accent: "#8B6733", radius: 8, gap: 14, shadow: "0 8px 22px rgba(80,66,38,.045)", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "operations-dense", name: "运营驾驶舱", method: "明细驱动", description: "明细表先行，紧凑承载高频运营信息。", chartTemplateId: "chart-monochrome", tableTemplateId: "datatables-slate", borderless: true, order: "table-first", spans: [12, 4, 4, 4, 6, 6, 12], heights: [560, 230, 230, 230, 330, 330, 430], tokens: { canvas: "#F2F4F5", surface: "#FAFAFA", border: "#D9DEE1", title: "#262B2F", muted: "#72797E", accent: "#526D82", radius: 4, gap: 10, shadow: "none", font: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" } },
  { id: "segment-lens", name: "客群透镜", method: "分群比较", description: "分布与分群图并列，随后查看结构差异。", chartTemplateId: "chart-celadon", tableTemplateId: "excel-teal", borderless: false, order: "segment-first", spans: [6, 6, 4, 4, 4, 8, 4, 12], heights: [390, 390, 270, 270, 270, 390, 390, 480], tokens: { canvas: "#F3F7F6", surface: "#FFFFFF", border: "#D7E6E2", title: "#29423D", muted: "#728783", accent: "#287E78", radius: 14, gap: 14, shadow: "0 10px 26px rgba(40,126,120,.045)", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "funnel-journey", name: "转化路径", method: "漏斗拆解", description: "转化主路径居前，节点指标在侧补充。", chartTemplateId: "chart-cloud-blue", tableTemplateId: "excel-blue", borderless: false, order: "funnel-first", spans: [8, 4, 12, 6, 6, 4, 4, 4], heights: [440, 310, 360, 350, 350, 250, 250, 250], tokens: { canvas: "#F4F7FB", surface: "#FFFFFF", border: "#DDE4EE", title: "#273142", muted: "#737C89", accent: "#3370FF", radius: 10, gap: 15, shadow: "0 8px 24px rgba(51,112,255,.045)", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "board-brief", name: "董事会简报", method: "结论先行", description: "留白、无边框、少而大的关键图表。", chartTemplateId: "chart-graphite", tableTemplateId: "tabulator-simple", borderless: true, order: "kpi-first", spans: [12, 8, 4, 12, 6, 6], heights: [300, 430, 430, 470, 360, 360], tokens: { canvas: "#F7F8F8", surface: "#F7F8F8", border: "#E3E7EA", title: "#20262A", muted: "#687178", accent: "#3B6C91", radius: 0, gap: 22, shadow: "none", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "evidence-ledger", name: "证据明细", method: "证据追溯", description: "宽表与证据卡优先，图表用于辅助定位。", chartTemplateId: "chart-pine", tableTemplateId: "tabulator-simple", borderless: false, order: "table-first", spans: [12, 12, 6, 6, 8, 4, 12], heights: [600, 500, 350, 350, 400, 400, 470], tokens: { canvas: "#F6F7F6", surface: "#FFFFFF", border: "#DDE2DE", title: "#314037", muted: "#758079", accent: "#426D52", radius: 2, gap: 11, shadow: "0 1px 2px rgba(49,64,55,.05)", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
  { id: "balanced-canvas", name: "均衡画布", method: "总分均衡", description: "主次分明的 8:4 起手与双列延展。", chartTemplateId: "chart-jade", tableTemplateId: "handsontable-main", borderless: false, order: "natural", spans: [8, 4, 6, 6, 4, 4, 4, 12], heights: [410, 410, 360, 360, 280, 280, 280, 480], tokens: { canvas: "#F5F8F6", surface: "#FFFFFF", border: "#DCE8E0", title: "#27382F", muted: "#758079", accent: "#287557", radius: 12, gap: 14, shadow: "0 7px 22px rgba(40,117,87,.04)", font: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif" } },
];

const templatesById = new Map(reportPageStyleTemplates.map((template) => [template.id, template]));

export function normalizeReportPageStyleId(value: unknown): ReportPageStyleId {
  return templatesById.has(String(value || "") as ReportPageStyleId) ? String(value) as ReportPageStyleId : DEFAULT_REPORT_PAGE_STYLE_ID;
}

export function reportPageStyleById(value: unknown) {
  return templatesById.get(normalizeReportPageStyleId(value)) || reportPageStyleTemplates.at(-1)!;
}

const categories: Record<Exclude<ReportPageStyleTemplate["order"], "natural">, VisualizationType[]> = {
  "kpi-first": ["kpi", "text", "line", "area", "combo", "column", "bar", "stacked_bar", "donut", "scatter", "funnel", "treemap", "radar", "table", "pivot"],
  "trend-first": ["line", "area", "combo", "kpi", "column", "bar", "stacked_bar", "scatter", "donut", "treemap", "radar", "funnel", "table", "pivot", "text"],
  "comparison-first": ["bar", "column", "stacked_bar", "radar", "scatter", "combo", "line", "area", "kpi", "donut", "treemap", "funnel", "table", "pivot", "text"],
  "risk-first": ["radar", "bar", "column", "stacked_bar", "scatter", "funnel", "kpi", "line", "area", "combo", "table", "pivot", "donut", "treemap", "text"],
  "table-first": ["table", "pivot", "kpi", "column", "bar", "stacked_bar", "line", "area", "combo", "scatter", "radar", "donut", "treemap", "funnel", "text"],
  "segment-first": ["donut", "treemap", "radar", "bar", "column", "stacked_bar", "kpi", "line", "area", "combo", "scatter", "funnel", "table", "pivot", "text"],
  "funnel-first": ["funnel", "kpi", "line", "area", "combo", "bar", "column", "stacked_bar", "donut", "treemap", "radar", "scatter", "table", "pivot", "text"],
};

export function applyReportPageStyleToCards<T extends { type: VisualizationType; config?: VisualizationCardConfig }>(cards: T[], styleId: unknown): T[] {
  const template = reportPageStyleById(styleId);
  const chartStyle = chartTemplateById(template.chartTemplateId).style;
  const tableStyle = builtInTableTemplates.find((item) => item.id === template.tableTemplateId)?.style || builtInTableTemplates[0].style;
  const ordered = template.order === "natural" ? [...cards] : [...cards].sort((left, right) => {
    const rank = categories[template.order];
    return rank.indexOf(left.type) - rank.indexOf(right.type);
  });
  return ordered.map((card, index) => ({
    ...card,
    config: {
      ...(card.config || { metricFields: [], dimensionFields: [], filters: {}, filterGroups: [], sumFilteredRows: false, comboLineFields: [] }),
      borderless: template.borderless,
      layoutSpan: template.spans[index % template.spans.length],
      layoutHeight: template.heights[index % template.heights.length],
      ...(card.type === "table" || card.type === "pivot" ? { tableStyle: { ...tableStyle } } : card.type === "text" ? {} : { chartStyle: { ...chartStyle } }),
    },
  }));
}

export function applyReportPageStyleToLayout<T extends { id: string; span: number; height: number }>(items: T[], styleId: unknown): T[] {
  const template = reportPageStyleById(styleId);
  return items.map((item, index) => ({ ...item, span: template.spans[index % template.spans.length], height: template.heights[index % template.heights.length] }));
}

export function reportPageStyleVars(styleId: unknown): CSSProperties {
  const template = reportPageStyleById(styleId);
  const tokens = template.tokens;
  const chartStyle = chartTemplateById(template.chartTemplateId).style;
  const tableStyle = builtInTableTemplates.find((item) => item.id === template.tableTemplateId)?.style || builtInTableTemplates[0].style;
  const palette = chartStyle.palette || [];
  return {
    "--sda-report-canvas": tokens.canvas,
    "--sda-report-surface": tokens.surface,
    "--sda-report-border": tokens.border,
    "--sda-report-title": tokens.title,
    "--sda-report-muted": tokens.muted,
    "--sda-report-accent": tokens.accent,
    "--sda-report-radius": `${tokens.radius}px`,
    "--sda-report-gap": `${tokens.gap}px`,
    "--sda-report-shadow": tokens.shadow,
    "--sda-report-font": tokens.font,
    "--sda-report-chart-1": palette[0] || tokens.accent,
    "--sda-report-chart-2": palette[1] || tokens.muted,
    "--sda-report-chart-3": palette[2] || tokens.border,
    "--sda-report-chart-4": palette[3] || tokens.title,
    "--sda-report-chart-grid": chartStyle.gridColor,
    "--sda-report-chart-axis": chartStyle.axisColor,
    "--sda-report-chart-text": chartStyle.textColor,
    "--sda-report-chart-muted": chartStyle.mutedTextColor,
    "--sda-report-chart-line-width": `${chartStyle.lineWidth}px`,
    "--sda-report-table-header-bg": tableStyle.headerBackground,
    "--sda-report-table-header-text": tableStyle.headerTextColor,
    "--sda-report-table-body-bg": tableStyle.bodyBackground,
    "--sda-report-table-alt-bg": tableStyle.alternateRowBackground,
    "--sda-report-table-body-text": tableStyle.bodyTextColor,
    "--sda-report-table-border": tableStyle.borderColor,
  } as CSSProperties;
}

export function ReportPageStyleButton({ styleId, onSelect, disabled = false, className = "" }: { styleId: unknown; onSelect: (styleId: ReportPageStyleId) => void; disabled?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const current = reportPageStyleById(styleId);
  useEffect(() => {
    const close = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  return <div ref={rootRef} className={`relative ${className}`} data-report-page-style-control="true">
    <button type="button" disabled={disabled} onClick={() => setOpen((value) => !value)} className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg border border-[#d8e1dc] bg-white px-3 text-[10px] text-[#4f6258] transition-colors hover:bg-[#f4f8f5] disabled:cursor-not-allowed disabled:opacity-50" aria-expanded={open} data-report-page-style-button="true"><LayoutTemplate className="h-3.5 w-3.5" />样式<span className="max-w-[76px] truncate text-[#178a53]">{current.name}</span><ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} /></button>
    {open ? <div className="absolute right-0 top-10 z-[80] w-[520px] max-w-[calc(100vw-32px)] rounded-xl border border-[#dce4df] bg-white p-2 shadow-xl shadow-black/10" data-report-page-style-menu="true">
      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {reportPageStyleTemplates.map((template) => <button key={template.id} type="button" onClick={() => { onSelect(template.id); setOpen(false); }} className={`group flex min-w-0 items-center gap-3 rounded-lg border p-2.5 text-left transition-colors ${template.id === current.id ? "border-[#91c4a4] bg-[#f0f8f3]" : "border-[#edf0ee] bg-white hover:border-[#cfded5] hover:bg-[#fafcfb]"}`} data-report-page-style-option={template.id}>
          <span className="grid h-12 w-[74px] shrink-0 grid-cols-3 gap-1 rounded-md p-1" style={{ background: template.tokens.canvas, border: `1px solid ${template.tokens.border}`, borderRadius: Math.max(3, template.tokens.radius / 2) }} aria-hidden="true"><span className="col-span-2 rounded-[2px]" style={{ background: template.tokens.surface, border: template.borderless ? "none" : `1px solid ${template.tokens.border}` }} /><span className="rounded-[2px]" style={{ background: template.tokens.surface, border: template.borderless ? "none" : `1px solid ${template.tokens.border}` }} /><span className="col-span-3 rounded-[2px]" style={{ background: template.tokens.surface, border: template.borderless ? "none" : `1px solid ${template.tokens.border}` }} /></span>
          <span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="truncate text-[11px] text-[#27342c]">{template.name}</span>{template.id === current.id ? <Check className="h-3.5 w-3.5 shrink-0 text-[#178a53]" /> : null}</span><span className="mt-0.5 block text-[9px] text-[#758079]">{template.method}</span><span className="mt-0.5 block truncate text-[9px] text-[#a0a7a3]">{template.description}</span></span>
        </button>)}
      </div>
    </div> : null}
  </div>;
}

export function ReportPageStyleSurface({ styleId, children, className = "", ...attributes }: { styleId: unknown; children: React.ReactNode; className?: string } & Record<`data-${string}`, string | undefined>) {
  const normalized = normalizeReportPageStyleId(styleId);
  return <div className={`sda-report-style-surface ${className}`} data-report-page-style={normalized} style={reportPageStyleVars(normalized)} {...attributes}>{children}</div>;
}
