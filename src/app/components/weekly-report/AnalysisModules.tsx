import { useEffect, useRef, useState } from "react";
import { ChevronsDown, Eye, EyeOff, GripVertical, Trash2 } from "lucide-react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { visualizationLabel, type SavedAnalysisResult, type StoredVisualizationType, type TableBlock } from "./domain";

export type WeeklyAnalysisModulePreference = { id: string; visible: boolean };
export type WeeklyAnalysisModuleSettings = {
  preferences: WeeklyAnalysisModulePreference[];
  orderCustomized: boolean;
};
export type WeeklyAnalysisModule = {
  id: string;
  kind: "core" | "saved";
  title: string;
  analysisTime: string;
  visible: boolean;
  savedAnalysisId?: string;
  savedAnalysisIds?: string[];
};

export type WeeklyDataModule = {
  id: string;
  kind: "page-data" | "core" | "visual-report" | "saved-analysis";
  title: string;
  subtitle: string;
  visible: boolean;
  deletable: boolean;
  sourceId: string;
};

export function buildWeeklyAnalysisModules({
  coreMetricBlock,
  savedAnalysisResults,
  preferences,
  orderCustomized = false,
}: {
  coreMetricBlock?: TableBlock;
  savedAnalysisResults: SavedAnalysisResult[];
  preferences: WeeklyAnalysisModulePreference[];
  orderCustomized?: boolean;
}): WeeklyAnalysisModule[] {
  const modulesById = new Map<string, WeeklyAnalysisModule>();
  const moduleIdBySignature = new Map<string, string>();
  savedAnalysisResults.forEach((result) => {
    const contentSignature = `content:${[result.title, result.query].map((value) => String(value || "").trim().toLocaleLowerCase("zh-CN").replace(/\s+/g, "")).join("|") || result.id}`;
    const signatures = [result.analysisTaskId ? `task:${result.analysisTaskId}` : "", contentSignature].filter(Boolean);
    const duplicateModuleId = signatures.map((signature) => moduleIdBySignature.get(signature)).find(Boolean);
    if (duplicateModuleId) {
      const duplicate = modulesById.get(duplicateModuleId)!;
      modulesById.set(duplicateModuleId, { ...duplicate, savedAnalysisIds: [...(duplicate.savedAnalysisIds || [duplicate.savedAnalysisId!]), result.id] });
      signatures.forEach((signature) => moduleIdBySignature.set(signature, duplicateModuleId));
      return;
    }
    const moduleId = `saved:${result.id}`;
    modulesById.set(moduleId, {
      id: moduleId,
      kind: "saved",
      title: result.title || result.query || "已保存分析",
      analysisTime: result.savedAt || "时间未记录",
      visible: false,
      savedAnalysisId: result.id,
      savedAnalysisIds: [result.id],
    });
    signatures.forEach((signature) => moduleIdBySignature.set(signature, moduleId));
  });
  const preferenceById = new Map(preferences.map((item) => [item.id, item]));
  const defaultSortedIds = [...modulesById.values()]
    .filter((item) => item.kind === "saved")
    .sort((left, right) => analysisTimestamp(right.analysisTime) - analysisTimestamp(left.analysisTime))
    .map((item) => item.id);
  const orderedIds = orderCustomized && preferences.length
    ? [...preferences.map((item) => item.id).filter((id) => modulesById.has(id)), ...defaultSortedIds.filter((id) => !preferenceById.has(id))]
    : defaultSortedIds;
  return orderedIds.map((id) => {
    const module = modulesById.get(id)!;
    const preference = preferenceById.get(id);
    return { ...module, visible: preference ? preference.visible : false };
  });
}

function analysisTimestamp(value: string) {
  const normalized = String(value || "").replace(/年|月/g, "-").replace(/日/g, "").replace(/上午|下午/g, "").replace(/\//g, "-");
  const timestamp = new Date(normalized).getTime();
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export function SavedAnalysisEmbed({ result }: { result: SavedAnalysisResult }) {
  return <div className="mb-4 rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4" data-weekly-report-ai-module="true">
    <div className="mb-3 flex flex-col gap-2 md:flex-row md:items-start md:justify-between"><div><div className="text-[13px] text-[#1d1d1f]">{result.title}</div><div className="mt-0.5 text-[11px] text-[#aeaeb2]">来自自助分析 · {result.savedAt}</div></div><span className="w-fit rounded-md border border-[#e5e5ea] bg-white px-2 py-1 text-[11px] text-[#8a8a8e]">已引用分析结果</span></div>
    <div className="mb-3 grid gap-3 md:grid-cols-2"><SavedAnalysisVisual title={`主视图 · ${visualizationLabel(result.visualTypes.primary)}`} type={result.visualTypes.primary} rows={result.rows} /><SavedAnalysisVisual title={`补充视图 · ${visualizationLabel(result.visualTypes.secondary)}`} type={result.visualTypes.secondary} rows={result.rows} /></div>
    <div className="rounded-lg border border-[#f0f0f2] bg-white p-3"><div className="mb-1 text-[12px] text-[#1d1d1f]">AI分析结论</div><p className="text-[12px] leading-[1.7] text-[#636366]">{result.summary}</p></div>
  </div>;
}

function SavedAnalysisVisual({ title, type, rows }: { title: string; type: StoredVisualizationType; rows: SavedAnalysisResult["rows"] }) {
  const maxAmount = Math.max(...rows.map((row) => row.amount), 1);
  if (type === "table") return <div className="rounded-lg border border-[#f0f0f2] bg-white p-3"><div className="mb-2 text-[12px] text-[#1d1d1f]">{title}</div><div className="overflow-x-auto"><table className="w-full text-[11px]"><tbody>{rows.slice(0, 4).map((row) => <tr key={row.branch} className="border-b border-[#f8f8f8] last:border-b-0"><td className="py-1.5 text-[#3a3a3c]">{row.branch}</td><td className="py-1.5 text-right text-[#636366]">{row.amount}万</td><td className="py-1.5 text-right text-[#8a8a8e]">{row.completion}</td></tr>)}</tbody></table></div></div>;
  return <div className="rounded-lg border border-[#f0f0f2] bg-white p-3"><div className="mb-2 flex items-center justify-between gap-2"><div className="text-[12px] text-[#1d1d1f]">{title}</div><span className="text-[10px] text-[#aeaeb2]">{visualizationLabel(type)}</span></div><div className="space-y-2">{rows.slice(0, 5).map((row, index) => <div key={row.branch} className="grid grid-cols-[48px_minmax(0,1fr)_54px] items-center gap-2 text-[11px]"><span className="truncate text-[#636366]">{row.branch}</span><div className="h-2 overflow-hidden rounded-full bg-[#f2f2f7]"><div className={`h-full rounded-full ${index === 0 ? "bg-[#1d1d1f]" : "bg-[#8e8e93]"}`} style={{ width: `${Math.max(12, (row.amount / maxAmount) * 100)}%` }} /></div><span className="text-right text-[#8a8a8e]">{row.amount}万</span></div>)}</div></div>;
}

export function weeklyAnalysisModuleStorageKey(tenantId: string, userId: string) {
  return `smart_data_agent_weekly_analysis_modules_v2_${tenantId}_${userId}`;
}

export function loadWeeklyAnalysisModulePreferences(tenantId: string, userId: string): WeeklyAnalysisModuleSettings {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(weeklyAnalysisModuleStorageKey(tenantId, userId)) || "[]");
    const rawPreferences = Array.isArray(parsed) ? parsed : parsed?.preferences;
    return {
      preferences: Array.isArray(rawPreferences)
        ? rawPreferences.filter((item) => item && typeof item.id === "string").map((item) => ({ id: item.id, visible: Boolean(item.visible) }))
        : [],
      orderCustomized: !Array.isArray(parsed) && parsed?.orderCustomized === true,
    };
  } catch {
    return { preferences: [], orderCustomized: false };
  }
}

export function WeeklyAnalysisModuleMenu({
  items,
  editable,
  loading = false,
  notice = "",
  onToggle,
  onMove,
  onDelete,
}: {
  items: WeeklyDataModule[];
  editable: boolean;
  loading?: boolean;
  notice?: string;
  onToggle: (item: WeeklyDataModule) => void;
  onMove: (sourceId: string, targetId: string) => void;
  onDelete: (item: WeeklyDataModule) => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div ref={menuRef} className="relative">
      <button type="button" aria-label="选择分析数据模块" title="分析数据" onClick={() => setOpen((value) => !value)} className={`flex h-8 w-8 items-center justify-center rounded-lg border transition-colors ${open ? "border-[#c7c7cc] bg-[#f2f2f7] text-[#1d1d1f]" : "border-[#e5e5ea] bg-white text-[#8a8a8e] hover:bg-[#f8f8f8]"}`}><ChevronsDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} /></button>
      {open ? <div className="absolute right-0 z-50 mt-2 w-[360px] max-w-[82vw] rounded-xl border border-[#e5e5ea] bg-white p-2 shadow-xl shadow-black/10">
        <div className="flex items-center justify-between px-2 pb-2 pt-1"><span className="text-[11px] text-[#636366]">周报数据</span><span className="text-[10px] text-[#aeaeb2]">{editable ? "拖动排序 · 点击显隐 · 可删除" : "拖动排序 · 点击显隐"}</span></div>
        <div className="max-h-[360px] space-y-1 overflow-y-auto" data-weekly-unified-data-menu="true">
          {loading ? <div className="px-3 py-4 text-center text-[11px] text-[#aeaeb2]">正在读取周报数据…</div> : items.map((item) => <div
            key={item.id}
            draggable
            onDragStart={(event) => { setDraggedId(item.id); event.dataTransfer.effectAllowed = "move"; }}
            onDragEnd={() => setDraggedId(null)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => { event.preventDefault(); if (draggedId) onMove(draggedId, item.id); setDraggedId(null); }}
            className={`flex w-full cursor-grab items-center rounded-lg border text-left active:cursor-grabbing ${item.visible ? "border-[#cdebd5] bg-[#eef8f1]" : "border-transparent bg-[#fafbfc] hover:border-[#e5e5ea] hover:bg-white"} ${draggedId === item.id ? "opacity-45" : ""}`}
            data-weekly-data-item={item.id}
            data-weekly-data-kind={item.kind}
          >
            <span className="ml-2 inline-flex h-7 w-5 shrink-0 items-center justify-center text-[#b2b8b4]" aria-hidden="true"><GripVertical className="h-3.5 w-3.5" /></span>
            <span className="min-w-0 flex-1 px-1 py-2.5">
              <span className={`block truncate text-[11px] ${item.visible ? "text-[#258a3f]" : "text-[#3a3a3c]"}`}>{item.title}</span>
              <span className="mt-0.5 block truncate text-[9px] text-[#aeaeb2]">{item.subtitle}</span>
            </span>
            <button
              type="button"
              aria-label={`${item.visible ? "隐藏" : "显示"}${item.title}`}
              title={item.visible ? "隐藏" : "显示"}
              onClick={() => onToggle(item)}
              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[#7d8982] hover:bg-white hover:text-[#258a3f]"
            >{item.visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}</button>
            {editable && item.deletable ? <button type="button" aria-label={`删除${item.title}`} title="删除" onClick={() => onDelete(item)} className="mr-2 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[#aeaeb2] hover:bg-[#fff0f0] hover:text-[#d93025]"><Trash2 className="h-3.5 w-3.5" /></button> : <span className="mr-2 h-7 w-7 shrink-0" aria-hidden="true" />}
          </div>)}
          {!loading && !items.length ? <div className="px-3 py-4 text-center text-[11px] text-[#aeaeb2]">暂无可编排的周报数据</div> : null}
          {notice ? <div className="mx-2 mt-1 rounded-md bg-[#f7faf8] px-2 py-1.5 text-[10px] text-[#68736d]">{notice}</div> : null}
        </div>
      </div> : null}
    </div>
  );
}

function numberValue(value: string | number | undefined) {
  if (typeof value === "number") return value;
  const match = String(value || "").replaceAll(",", "").match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : 0;
}

export function CoreMetricChart({ block }: { block: TableBlock }) {
  const data = block.rows.map((row, index) => ({ period: String(row.日期 || row.周次 || `第${index + 1}期`), 在贷余额: numberValue(row.在贷余额), 放款金额: numberValue(row.放款金额), 新增余额: numberValue(row.新增余额) })).reverse();
  return <div className="rounded-xl border border-[#f0f0f2] bg-white p-4">
    <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
      <div><div className="text-[12px] text-[#1d1d1f]">核心指标周度趋势</div><div className="mt-0.5 text-[10px] text-[#aeaeb2]">按日期从早到晚 · 单位：亿元</div></div>
      <div className="flex flex-wrap items-center gap-3 text-[10px] text-[#8a8a8e]"><span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-[2px] bg-[#8e8e93]" />放款金额</span><span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-[2px] bg-[#d1d1d6]" />新增余额</span><span className="inline-flex items-center gap-1.5"><i className="h-px w-3 bg-[#1d1d1f]" />在贷余额</span></div>
    </div>
    <div className="h-[240px] min-w-0" role="img" aria-label="在贷余额、放款金额和新增余额周度趋势图，横轴按日期从早到晚排列，单位为亿元"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} barGap={6} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}><CartesianGrid stroke="#f5f5f5" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="period" tick={{ fill: "#c7c7cc", fontSize: 10 }} tickLine={false} axisLine={false} /><YAxis yAxisId="amount" tick={{ fill: "#c7c7cc", fontSize: 10 }} tickLine={false} axisLine={false} width={38} /><YAxis yAxisId="balance" orientation="right" tick={{ fill: "#c7c7cc", fontSize: 10 }} tickLine={false} axisLine={false} width={38} /><Tooltip cursor={{ fill: "#f8f8fa" }} contentStyle={{ borderRadius: 8, border: "1px solid #f0f0f2", boxShadow: "0 8px 20px rgba(0,0,0,0.06)", fontSize: 11 }} labelStyle={{ color: "#636366", marginBottom: 4 }} itemStyle={{ color: "#3a3a3c" }} formatter={(value, name) => [`${Number(value).toFixed(2)}亿`, String(name)]} /><Bar yAxisId="amount" dataKey="放款金额" fill="#8e8e93" radius={[3, 3, 0, 0]} maxBarSize={24} /><Bar yAxisId="amount" dataKey="新增余额" fill="#d1d1d6" radius={[3, 3, 0, 0]} maxBarSize={24} /><Line yAxisId="balance" type="monotone" dataKey="在贷余额" stroke="#1d1d1f" strokeWidth={1.6} dot={{ r: 2.5, fill: "#1d1d1f", strokeWidth: 0 }} activeDot={{ r: 3.5 }} /></ComposedChart></ResponsiveContainer></div>
  </div>;
}
