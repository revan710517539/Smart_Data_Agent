import { useEffect, useState } from "react";
import { BarChart3, ChevronDown, ChevronRight, Star, Trash2 } from "lucide-react";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import { deleteVisualReport, fetchVisualReports, upsertVisualReport, type VisualReport, type VisualReportDestination } from "../../services/visualReportApi";
import { useFeaturedReports } from "../self-analysis/featuredReports";
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
  const { tenantId, userId, isSuperAdmin, isInstitutionAdmin } = usePlatformContext();
  const featuredReports = useFeaturedReports(tenantId, userId);
  const [expandedId, setExpandedId] = useState("");
  const [pendingDelete, setPendingDelete] = useState<VisualReport | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const allowFeatured = destination === "mine";

  return <section className={embedded ? "rounded-xl border border-[#eef1ef] bg-white p-4" : ""} data-visual-report-library={destination}>
    {embedded && <div className="mb-3 flex items-center justify-between"><div><h3 className="text-[12px] text-[#1d1d1f]">可视化报表</h3><p className="mt-1 text-[10px] text-[#9ba19e]">从可视化报表工作台存入周报的报表</p></div><span className="rounded-md bg-[#f2f5f3] px-2 py-1 text-[10px] text-[#69736e]">{reports.length} 份</span></div>}
    {error && <div className="mb-3 rounded-lg border border-[#ffd0d0] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#c84034]">{error}</div>}
    {loading ? <div className="rounded-lg border border-dashed border-[#e0e5e2] px-3 py-8 text-center text-[11px] text-[#9ba19e]">正在读取可视化报表…</div> : <div className="space-y-2">
      {reports.map((report) => <VisualReportRow
        key={report.id}
        report={report}
        expanded={expandedId === report.id}
        onToggleExpanded={() => setExpandedId((current) => current === report.id ? "" : report.id)}
        railPageKey={railPageKey}
        featured={allowFeatured ? featuredReports.isFeatured("visual", report.id) : undefined}
        onToggleFeatured={allowFeatured ? () => featuredReports.toggle("visual", report.id) : undefined}
        onRequestDelete={destination === "mine" || (destination === "weekly" && (isSuperAdmin || isInstitutionAdmin || report.ownerUserId === userId)) ? () => { setDeleteError(""); setPendingDelete(report); } : undefined}
      />)}
      {!reports.length && <div className="rounded-lg border border-dashed border-[#e0e5e2] px-3 py-10 text-center text-[11px] text-[#9ba19e]">{destination === "mine" ? "暂无存入我的可视化报表" : "暂无存入周报的可视化报表"}</div>}
    </div>}
    {pendingDelete && <VisualReportDeleteConfirm destination={destination} report={pendingDelete} deleting={deleting} error={deleteError} onCancel={() => { if (!deleting) setPendingDelete(null); }} onConfirm={() => {
      void (async () => {
        setDeleting(true);
        setDeleteError("");
        const result = await remove(pendingDelete);
        setDeleting(false);
        if (result.ok) {
          featuredReports.remove("visual", pendingDelete.id);
          if (expandedId === pendingDelete.id) setExpandedId("");
          setPendingDelete(null);
        } else {
          setDeleteError(result.error);
        }
      })();
    }} />}
  </section>;
}

export function VisualReportRow({
  report,
  expanded,
  onToggleExpanded,
  railPageKey,
  featured,
  onToggleFeatured,
  onRequestDelete,
  kindBadge,
}: {
  report: VisualReport;
  expanded: boolean;
  onToggleExpanded: () => void;
  railPageKey: string;
  featured?: boolean;
  onToggleFeatured?: () => void;
  onRequestDelete?: () => void;
  kindBadge?: string;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#edf0ee] bg-[#fafcfb]" data-visual-report-row={report.id}>
      <div className="flex items-center gap-2 px-3 py-2.5">
        <button type="button" onClick={onToggleExpanded} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#87918b]" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#87918b]" />}
          <BarChart3 className="h-4 w-4 shrink-0 text-[#4f8a67]" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[12px] text-[#1d1d1f]">{report.title}</span>
            <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[9px] text-[#a1a7a3]">
              {kindBadge ? <span className="inline-flex items-center rounded bg-[#f2f2f7] px-1.5 py-0.5 text-[10px] text-[#636366]">{kindBadge}</span> : null}
              <span>{report.cards.length} 个图表 · {formatTime(report.updatedAt)}</span>
            </span>
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-1">
          {onToggleFeatured ? (
            <button
              type="button"
              data-featured-report-star="visual"
              aria-pressed={Boolean(featured)}
              aria-label={featured ? `取消精选${report.title}` : `精选${report.title}`}
              title={featured ? "取消精选" : "精选"}
              onClick={onToggleFeatured}
              className="rounded-md p-1.5 text-[#c7c7cc] hover:bg-white"
            >
              <Star className={`h-3.5 w-3.5 ${featured ? "fill-[#f5a524] text-[#f5a524]" : "text-[#c7c7cc]"}`} />
            </button>
          ) : null}
          {onRequestDelete ? <button type="button" onClick={onRequestDelete} className="rounded-md p-1.5 text-[#8a8e8c] hover:bg-[#fff0f0] hover:text-[#c84034]" aria-label={`删除${report.title}`}><Trash2 className="h-3.5 w-3.5" /></button> : null}
        </div>
      </div>
      {expanded ? <div className="empty:hidden border-t border-[#edf0ee] bg-white p-3"><VisualReportCards report={report} railPageKey={railPageKey} /></div> : null}
    </div>
  );
}

export function useVisualReportCollection(destination: Extract<VisualReportDestination, "mine" | "weekly">, enabled = true) {
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
    if (!enabled) {
      setReports([]);
      setError("");
      setLoading(false);
      return;
    }
    void refresh();
    const reload = () => void refresh();
    window.addEventListener("smart-data-agent-visual-report-saved", reload);
    return () => window.removeEventListener("smart-data-agent-visual-report-saved", reload);
    // refresh is intentionally scoped to the current tenant and user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destination, enabled, tenantId, userId]);

  const remove = async (report: VisualReport) => {
    try {
      if (destination === "weekly") {
        await upsertVisualReport({ tenantId, userId, report: { ...report, destinations: report.destinations.filter((item) => item !== "weekly") } });
      } else {
        await deleteVisualReport({ tenantId, userId, reportId: report.id });
      }
      setReports((current) => current.filter((item) => item.id !== report.id));
      setError("");
      return { ok: true as const };
    } catch (reason) {
      const message = apiErrorMessage(reason, destination === "weekly" ? "可视化报表移出周报失败。" : "可视化报表删除失败。");
      setError(message);
      return { ok: false as const, error: message };
    }
  };

  return { reports, loading, error, refresh, remove };
}

export function VisualReportDeleteConfirm({
  destination,
  report,
  deleting,
  error = "",
  onCancel,
  onConfirm,
}: {
  destination: Extract<VisualReportDestination, "mine" | "weekly">;
  report: VisualReport;
  deleting: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const weekly = destination === "weekly";
  return (
    <ConfirmDialog
      open
      title={weekly ? "从经营周报移除可视化报表？" : "删除这条可视化报表？"}
      description={report.title}
      hint={weekly ? "源报表仍会保留，仅从本周报移除。" : "确认后将从当前账号的可视化报表中删除，操作不可撤销。"}
      error={error}
      confirmLabel={weekly ? "确认移除" : "确认删除"}
      busyLabel={weekly ? "移除中…" : "删除中…"}
      busy={deleting}
      zIndexClass="z-[180]"
      data-visual-report-delete-overlay="true"
      data-visual-report-delete-dialog="true"
      titleId="visual-report-delete-title"
      descriptionId="visual-report-delete-copy"
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

function formatTime(value: string) {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString("zh-CN", { hour12: false }) : value || "时间未记录";
}
