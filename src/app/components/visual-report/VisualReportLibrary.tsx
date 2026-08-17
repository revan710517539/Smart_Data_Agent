import { useEffect, useState } from "react";
import { BarChart3, ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import { deleteVisualReport, fetchVisualReports, upsertVisualReport, type VisualReport, type VisualReportDestination } from "../../services/visualReportApi";
import { VisualReportCards } from "./VisualReportCards";

export function VisualReportLibrary({
  destination,
  railPageKey,
  embedded = false,
}: {
  destination: Extract<VisualReportDestination, "mine" | "weekly">;
  railPageKey: string;
  embedded?: boolean;
}) {
  const { reports, loading, error, remove } = useVisualReportCollection(destination);
  const [expandedId, setExpandedId] = useState("");

  return <section className={embedded ? "rounded-xl border border-[#eef1ef] bg-white p-4" : ""} data-visual-report-library={destination}>
    {embedded && <div className="mb-3 flex items-center justify-between"><div><h3 className="text-[12px] text-[#1d1d1f]">可视化报表</h3><p className="mt-1 text-[10px] text-[#9ba19e]">从可视化报表工作台存入周报的报表</p></div><span className="rounded-md bg-[#f2f5f3] px-2 py-1 text-[10px] text-[#69736e]">{reports.length} 份</span></div>}
    {error && <div className="mb-3 rounded-lg border border-[#ffd0d0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#c84034]">{error}</div>}
    {loading ? <div className="rounded-lg border border-dashed border-[#e0e5e2] px-3 py-8 text-center text-[11px] text-[#9ba19e]">正在读取可视化报表…</div> : <div className="space-y-2">
      {reports.map((report) => <div key={report.id} className="overflow-hidden rounded-lg border border-[#edf0ee] bg-[#fafcfb]">
        <div className="flex items-center gap-2 px-3 py-2.5">
          <button type="button" onClick={() => setExpandedId((current) => current === report.id ? "" : report.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
            {expandedId === report.id ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#87918b]" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#87918b]" />}
            <BarChart3 className="h-4 w-4 shrink-0 text-[#4f8a67]" />
            <span className="min-w-0 flex-1"><span className="block truncate text-[12px] text-[#1d1d1f]">{report.title}</span><span className="mt-0.5 block text-[9px] text-[#a1a7a3]">{report.cards.length} 个图表 · {formatTime(report.updatedAt)}</span></span>
          </button>
          {destination === "mine" && <button type="button" onClick={() => { void remove(report); if (expandedId === report.id) setExpandedId(""); }} className="rounded-md p-1.5 text-[#8a8e8c] hover:bg-[#fff0f0] hover:text-[#c84034]" aria-label={`删除${report.title}`}><Trash2 className="h-3.5 w-3.5" /></button>}
        </div>
        {expandedId === report.id && <div className="border-t border-[#edf0ee] bg-white p-3"><VisualReportCards report={report} railPageKey={railPageKey} /></div>}
      </div>)}
      {!reports.length && <div className="rounded-lg border border-dashed border-[#e0e5e2] px-3 py-10 text-center text-[11px] text-[#9ba19e]">{destination === "mine" ? "暂无存入我的可视化报表" : "暂无存入周报的可视化报表"}</div>}
    </div>}
  </section>;
}

export function useVisualReportCollection(destination: Extract<VisualReportDestination, "mine" | "weekly">) {
  const { tenantId, userId } = usePlatformContext();
  const [reports, setReports] = useState<VisualReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    try {
      const results = await fetchVisualReports({ tenantId, userId });
      setReports(results.filter((report) => report.destinations.includes(destination)));
      setError("");
    } catch (reason) {
      setReports([]);
      setError(apiErrorMessage(reason, "可视化报表读取失败。"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    const reload = () => void refresh();
    window.addEventListener("smart-data-agent-visual-report-saved", reload);
    return () => window.removeEventListener("smart-data-agent-visual-report-saved", reload);
    // refresh is intentionally scoped to the current tenant and user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destination, tenantId, userId]);

  const remove = async (report: VisualReport) => {
    const message = destination === "weekly"
      ? `确认从经营周报移除可视化报表“${report.title}”吗？源报表仍会保留。`
      : `确认删除可视化报表“${report.title}”吗？`;
    if (!window.confirm(message)) return false;
    try {
      if (destination === "weekly") {
        await upsertVisualReport({ tenantId, userId, report: { ...report, destinations: report.destinations.filter((item) => item !== "weekly") } });
      } else {
        await deleteVisualReport({ tenantId, userId, reportId: report.id });
      }
      setReports((current) => current.filter((item) => item.id !== report.id));
      setError("");
      return true;
    } catch (reason) {
      setError(apiErrorMessage(reason, destination === "weekly" ? "可视化报表移出周报失败。" : "可视化报表删除失败。"));
      return false;
    }
  };

  return { reports, loading, error, refresh, remove };
}

function formatTime(value: string) {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString("zh-CN", { hour12: false }) : value || "时间未记录";
}
