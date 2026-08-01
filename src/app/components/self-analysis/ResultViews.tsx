import { ChevronDown, Download } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  analysisRawFields,
  displayRawCell,
  visualizationLabel,
  visualizationOptions,
  type AnalysisRow,
  type ResultVisualKey,
  type VisualizationType,
} from "./domain";

export function RawDataTable({ rows, onDownload }: { rows: AnalysisRow[]; onDownload: () => void }) {
  const fields = analysisRawFields(rows);
  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className="mb-3 flex items-center justify-between gap-3"><div><div className="text-[12px] text-[#1d1d1f]">可视化原始数据</div><div className="mt-0.5 text-[11px] text-[#aeaeb2]">当前图形对应的 SQL 返回数据，默认显示 20 条</div></div><button type="button" onClick={onDownload} disabled={!rows.length} className="inline-flex items-center gap-1 rounded-lg border border-[#e5e5ea] bg-white px-3 py-1.5 text-[11px] text-[#636366] hover:bg-[#f2f2f7] disabled:cursor-not-allowed disabled:opacity-40"><Download className="h-3 w-3" />下载数据</button></div>
      <ResultTable rows={rows.slice(0, 20)} emptyLabel="暂无 SQL 返回数据" />
    </div>
  );
}

export function AnalysisVisualCard({ id, title, type, rows, open, compact = false, onMenuToggle, onTypeChange }: { id: ResultVisualKey; title: string; type: VisualizationType; rows: AnalysisRow[]; open: boolean; compact?: boolean; onMenuToggle: () => void; onTypeChange: (type: VisualizationType) => void }) {
  return <div data-visual-card={id} className="relative rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
    <div className="mb-3 flex items-start justify-between gap-3"><div><div className="text-[12px] text-[#1d1d1f]">{title}</div><div className="mt-0.5 text-[11px] text-[#aeaeb2]">右侧可切换可视化组件</div></div><button type="button" onClick={onMenuToggle} className="inline-flex items-center gap-1 rounded-lg border border-[#e5e5ea] bg-white px-2.5 py-1.5 text-[11px] text-[#636366] hover:bg-[#f2f2f7]" aria-label={`切换${title}可视化`}>{visualizationLabel(type)}<ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} /></button></div>
    {open && <div className="absolute right-4 top-12 z-20 w-32 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg shadow-black/[0.08]">{visualizationOptions.map((option) => <button key={option.type} type="button" onClick={() => onTypeChange(option.type)} className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] ${option.type === type ? "bg-[#f2f2f7] text-[#1d1d1f]" : "text-[#636366] hover:bg-[#fafbfc]"}`}><option.icon className="h-3.5 w-3.5 text-[#8a8a8e]" />{option.label}</button>)}</div>}
    <VisualizationRenderer type={type} rows={rows} compact={compact} />
  </div>;
}

function ResultTable({ rows, emptyLabel }: { rows: AnalysisRow[]; emptyLabel: string }) {
  const fields = analysisRawFields(rows);
  return <div className="overflow-x-auto rounded-lg border border-[#f0f0f2] bg-white"><table className="w-full text-[12px]"><thead><tr className="border-b border-[#f0f0f2] text-[#aeaeb2]">{fields.map((field) => <th key={field} className="whitespace-nowrap px-3 py-2 text-left font-normal">{field}</th>)}</tr></thead><tbody>{rows.length ? rows.map((row, index) => <tr key={`${row.branch}_${index}`} className="border-b border-[#fafafa] last:border-b-0">{fields.map((field) => <td key={field} className="whitespace-nowrap px-3 py-2 text-[#3a3a3c]">{displayRawCell(row.raw[field])}</td>)}</tr>) : <tr><td className="px-3 py-8 text-center text-[#8a8a8e]" colSpan={Math.max(1, fields.length)}>{emptyLabel}</td></tr>}</tbody></table></div>;
}

function VisualizationRenderer({ type, rows, compact }: { type: VisualizationType; rows: AnalysisRow[]; compact?: boolean }) {
  const height = compact ? 220 : 300;
  const visibleRows = rows.slice(0, compact ? 5 : 8);
  const metricName = rows[0]?.metricName || "metric_value";
  if (!rows.length) return <div className="flex h-[220px] items-center justify-center rounded-lg border border-dashed border-[#e5e5ea] bg-[#fafbfc] text-[12px] text-[#8a8a8e]">暂无可视化数据</div>;
  if (type === "table") return <ResultTable rows={visibleRows} emptyLabel="暂无可视化数据" />;
  if (type === "column") return <ResponsiveContainer width="100%" height={height}><BarChart data={visibleRows} margin={{ top: 12, right: 8, left: -18, bottom: 0 }}><CartesianGrid stroke="#f0f0f2" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="branch" tick={{ fontSize: 10, fill: "#8a8a8e" }} tickLine={false} axisLine={false} /><YAxis tick={{ fontSize: 10, fill: "#aeaeb2" }} tickLine={false} axisLine={false} /><Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #f0f0f2" }} /><Bar dataKey="amount" name={metricName} fill="#636366" radius={[4, 4, 0, 0]} barSize={compact ? 18 : 24} /></BarChart></ResponsiveContainer>;
  if (type === "line") return <ResponsiveContainer width="100%" height={height}><LineChart data={visibleRows} margin={{ top: 12, right: 16, left: -18, bottom: 0 }}><CartesianGrid stroke="#f0f0f2" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="branch" tick={{ fontSize: 10, fill: "#8a8a8e" }} tickLine={false} axisLine={false} /><YAxis tick={{ fontSize: 10, fill: "#aeaeb2" }} tickLine={false} axisLine={false} /><Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #f0f0f2" }} /><Line type="monotone" dataKey="amount" name={metricName} stroke="#1d1d1f" strokeWidth={2} dot={{ r: 2.5 }} /></LineChart></ResponsiveContainer>;
  if (type === "radar") { const radarRows = visibleRows.map((row) => ({ factor: row.branch, value: row.amount })); return <ResponsiveContainer width="100%" height={height}><RadarChart data={radarRows} outerRadius={compact ? 78 : 104}><PolarGrid stroke="#e5e5ea" /><PolarAngleAxis dataKey="factor" tick={{ fontSize: 11, fill: "#636366" }} /><PolarRadiusAxis angle={90} tick={{ fontSize: 10, fill: "#aeaeb2" }} /><Radar name={metricName} dataKey="value" stroke="#1d1d1f" fill="#1d1d1f" fillOpacity={0.14} /><Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #f0f0f2" }} /></RadarChart></ResponsiveContainer>; }
  return <ResponsiveContainer width="100%" height={height}><BarChart data={visibleRows} layout="vertical" margin={{ top: 12, right: 12, left: 10, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="#f0f0f2" horizontal={false} /><XAxis type="number" tick={{ fontSize: 10, fill: "#c7c7cc" }} stroke="transparent" tickLine={false} /><YAxis type="category" dataKey="branch" tick={{ fontSize: 11, fill: "#636366" }} stroke="transparent" tickLine={false} width={45} /><Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #f0f0f2" }} /><Bar dataKey="amount" name={metricName} fill="#8e8e93" radius={[0, 4, 4, 0]} barSize={18} /></BarChart></ResponsiveContainer>;
}
