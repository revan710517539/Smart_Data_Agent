import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartData } from "./AgentSupervisor";

export default function SupervisorChart({ chart }: { chart: ChartData }) {
  return <div className={`mt-2 h-40 rounded-lg border p-2 text-[#3a3a3c] ${chart.mode === "exercise" ? "border-[#f1d6b8] bg-[#fffaf1]" : "border-[#e5e5ea] bg-white"}`}><div className="mb-1 flex items-center justify-between gap-2"><p className="truncate text-[10px] text-[#636366]">{chart.title}</p><span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] ${chart.mode === "exercise" ? "bg-[#fff0d7] text-[#9a5a09]" : "bg-[#eaf8ed] text-[#258a3f]"}`}>{chart.mode === "exercise" ? "演练，不可发布" : "已通过发布门"}</span></div><ResponsiveContainer width="100%" height="88%"><BarChart data={chart.rows}><CartesianGrid vertical={false} stroke="#f0f0f2" /><XAxis dataKey="label" tick={{ fontSize: 9 }} /><YAxis tick={{ fontSize: 9 }} /><Tooltip /><Bar dataKey="value" name={chart.metric} fill={chart.mode === "exercise" ? "#b7791f" : "#1d1d1f"} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div>;
}
