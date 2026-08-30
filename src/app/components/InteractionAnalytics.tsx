import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock3,
  MousePointerClick,
  RefreshCw,
  Route,
  Users,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import {
  fetchInteractionAnalytics,
  type InteractionAnalyticsSnapshot,
  type InteractionCountItem,
  type InteractionTimelineEvent,
} from "../services/interactionAnalyticsApi";
import { ApiRequestError, apiErrorMessage } from "../services/apiClient";
import { AppSelect } from "./ui/AppSelect";

type AnalyticsLoadStatus = "loading" | "retrying" | "ready" | "failed";
type TrendMetricKey = "visits" | "visitors" | "this_week_visits" | "events" | "peak_hour";

const analyticsRetryDelaysMs = [0, 1_000, 2_000, 4_000, 8_000, 12_000, 16_000, 20_000] as const;

const eventLabels: Record<string, string> = {
  login_submit: "登录成功",
  primary_menu_click: "点击一级菜单",
  secondary_menu_click: "点击二级菜单",
  page_view: "页面曝光",
  visual_more_click: "打开图表更多操作",
  visual_text_card_click: "新建文本框",
  visual_condition_click: "打开条件配置",
  visual_style_click: "打开样式配置",
  visual_metric_click: "打开指标配置",
  visual_dimension_click: "打开维度配置",
  visual_follow_up_click: "追问图表",
  visualization_result: "完成图表配置",
  weekly_report_text_saved: "保存周报文字",
  export_result: "完成导出",
};

const pageLabels: Record<string, string> = {
  dashboard: "多机构分析",
  "business-analysis.weekly-report": "经营周报",
  "business-analysis.supervision": "机构督导",
  "business-analysis.customer-segment": "分客群分析",
  "self-analysis.visual-reports": "可视化报表",
  "self-analysis.smart-analysis": "智能分析",
  "self-analysis.my-reports": "我的报表",
  "self-analysis.analysis-config": "分析配置",
  "task-workbench.message-board": "留言板管理",
  "task-workbench.interaction-analytics": "埋点分析",
  "data-assets.metrics": "指标字典",
  "data-assets.knowledge": "知识记忆",
  "data-assets.data-management": "站内数据",
  "settings.roles": "角色权限",
  "settings.config": "系统配置",
};

export function InteractionAnalytics() {
  const { isSuperAdmin, tenantId, userId } = usePlatformContext();
  const [days, setDays] = useState(7);
  const [trendMetric, setTrendMetric] = useState<TrendMetricKey>("visits");
  const [selectedActor, setSelectedActor] = useState("");
  const [appliedActor, setAppliedActor] = useState("");
  const [page, setPage] = useState(1);
  const [refreshToken, setRefreshToken] = useState(0);
  const [snapshot, setSnapshot] = useState<InteractionAnalyticsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadStatus, setLoadStatus] = useState<AnalyticsLoadStatus>("loading");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!isSuperAdmin) {
      setLoading(false);
      setSnapshot(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadStatus("loading");
    setNotice("");
    const loadSnapshot = async () => {
      for (let attempt = 0; attempt < analyticsRetryDelaysMs.length; attempt += 1) {
        const delayMs = analyticsRetryDelaysMs[attempt];
        if (delayMs > 0) {
          setLoadStatus("retrying");
          await new Promise((resolve) => window.setTimeout(resolve, delayMs));
          if (cancelled) return;
        }
        try {
          const response = await fetchInteractionAnalytics({ days, actorUserId: selectedActor, page, pageSize: 50 }, { tenantId, userId });
          if (cancelled) return;
          setSnapshot(response);
          setAppliedActor(selectedActor);
          setLoadStatus("ready");
          setLoading(false);
          return;
        } catch (error) {
          const exhausted = attempt === analyticsRetryDelaysMs.length - 1;
          if (!isRetryableInteractionAnalyticsError(error) || exhausted) {
            if (!cancelled) {
              setNotice(apiErrorMessage(error, "埋点分析读取失败，请稍后重试"));
              setLoadStatus("failed");
              setLoading(false);
            }
            return;
          }
        }
      }
    };
    void loadSnapshot();
    return () => { cancelled = true; };
  }, [days, isSuperAdmin, page, refreshToken, selectedActor, tenantId, userId]);

  const selectedUser = snapshot?.users.find((item) => item.actor_user_id === appliedActor);
  const peakHours = useMemo(() => [...(snapshot?.hourly || [])].sort((left, right) => right.events - left.events).slice(0, 3), [snapshot]);
  const breakpointSummary = snapshot?.breakpoint_summary;

  if (!isSuperAdmin) {
    return <div className="p-7"><EmptyState title="无权查看埋点分析" detail="该页面包含全平台用户行为，仅全局超级管理员可查看。" /></div>;
  }

  return (
    <div className="min-h-full p-7" data-interaction-analytics-page="true">
      <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">埋点分析</h2>
          <p className="mt-1 text-[13px] text-[#aeaeb2]">全平台跨机构视角 · 从同一张轻量行为明细表识别来访、数据使用与访问断点</p>
        </div>
        <div className="flex items-center gap-2" data-page-header-actions="true">
          <AppSelect value={days} onChange={(event) => { setDays(Number(event.target.value)); setPage(1); }} className="h-9" aria-label="统计周期">
            <option value={7}>近 7 天</option>
            <option value={30}>近 30 天</option>
            <option value={90}>近 90 天</option>
          </AppSelect>
          <button type="button" onClick={() => setRefreshToken((value) => value + 1)} disabled={loading} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] hover:bg-[#f5f5f7] disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />刷新
          </button>
        </div>
      </header>

      {loadStatus === "retrying" && <div className="mb-5 rounded-xl border border-[#ead8a8] bg-[#fffaf0] px-4 py-3 text-[12px] text-[#8a6714]" role="status" aria-live="polite">Data Agent API 正在启动，页面将在服务就绪后自动恢复。</div>}
      {notice && <div className="mb-5 flex items-center justify-between gap-3 rounded-xl border border-[#f2c7c7] bg-[#fff7f7] px-4 py-3 text-[12px] text-[#b42318]" role="alert"><span>{notice}</span><button type="button" onClick={() => setRefreshToken((value) => value + 1)} className="shrink-0 rounded-md border border-[#e6b9b9] bg-white px-2.5 py-1 text-[11px] hover:bg-[#fff1f1]">重新读取</button></div>}
      {snapshot?.truncated && <div className="mb-5 rounded-xl border border-[#ead8a8] bg-[#fffaf0] px-4 py-3 text-[12px] text-[#8a6714]">当前周期共有 {formatNumber(snapshot.summary.total_events)} 条事件，轻量快照仅聚合最近 {formatNumber(snapshot.sampled_events)} 条；缩短统计周期可查看完整口径。</div>}

      {loading && !snapshot ? <LoadingState /> : snapshot && snapshot.summary.total_events > 0 ? (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="访问总体指标">
            <MetricCard icon={Users} label="访问人数" value={formatNumber(snapshot.summary.total_visitors)} hint={`${days} 天内去重用户 · ${snapshot.tenant_ids.length} 个机构`} selected={trendMetric === "visitors"} onSelect={() => setTrendMetric("visitors")} />
            <MetricCard icon={Route} label="访问次数" value={formatNumber(snapshot.summary.total_visits)} hint={`30 分钟无操作后计新访问`} selected={trendMetric === "visits"} onSelect={() => setTrendMetric("visits")} />
            <MetricCard icon={CalendarDays} label="本周访问" value={formatNumber(snapshot.summary.this_week_visits)} hint={`人均 ${snapshot.summary.average_visits_per_user} 次`} selected={trendMetric === "this_week_visits"} onSelect={() => setTrendMetric("this_week_visits")} />
            <MetricCard icon={MousePointerClick} label="行为事件" value={formatNumber(snapshot.summary.total_events)} hint={`${snapshot.summary.active_days} 个活跃日`} selected={trendMetric === "events"} onSelect={() => setTrendMetric("events")} />
            <MetricCard icon={Clock3} label="访问高峰" value={snapshot.summary.peak_hour === null ? "—" : `${padHour(snapshot.summary.peak_hour)}:00`} hint={peakHours.filter((item) => item.events > 0).map((item) => `${padHour(item.hour)}时`).join("、") || "暂无高峰"} selected={trendMetric === "peak_hour"} onSelect={() => setTrendMetric("peak_hour")} />
          </section>

          <section className="mt-4 grid gap-4 lg:grid-cols-[1.35fr_1fr]">
            <Panel title={trendDefinition(trendMetric).title} subtitle={trendDefinition(trendMetric).subtitle}>
              <WeeklyTrend items={snapshot.weekly} metric={trendMetric} />
            </Panel>
            <Panel title="访问断点" subtitle="用于定位点击后未到达或未完成的操作">
              <div className="grid grid-cols-3 gap-2">
                <MiniCount label="菜单未曝光" value={breakpointSummary?.menu_without_page_view || 0} />
                <MiniCount label="配置未完成" value={breakpointSummary?.configuration_not_completed || 0} />
                <MiniCount label="重复操作" value={breakpointSummary?.repeated_action || 0} />
              </div>
              <div className="mt-3 max-h-36 space-y-2 overflow-y-auto pr-1">
                {snapshot.breakpoints.slice(0, 5).map((item, index) => <div key={`${item.actor_user_id}-${item.occurred_at}-${index}`} className="flex gap-2 rounded-lg bg-[#fffaf0] px-3 py-2 text-[11px]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#b7791f]" /><div className="min-w-0"><div className="truncate text-[#4a4030]">{item.actor_name} · {item.description}</div><div className="mt-0.5 text-[#9a835c]">{tenantDisplayName(item.tenant_id)} · {formatTime(item.occurred_at)}</div></div></div>)}
                {!snapshot.breakpoints.length && <MutedEmpty text="当前周期未发现明显访问断点" />}
              </div>
            </Panel>
          </section>

          <section className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <RankingPanel title="高频指标" items={snapshot.top_metrics} empty="尚未记录指标最终选择" />
            <RankingPanel title="高频维度" items={snapshot.top_dimensions} empty="尚未记录维度最终选择" />
            <RankingPanel title="常用样式" items={snapshot.top_styles} empty="尚未记录样式最终选择" />
            <RankingPanel title="高频页面" items={snapshot.top_pages.map((item) => ({ ...item, value: pageDisplayName(item.value) }))} empty="尚无页面曝光" />
          </section>

          <section className="mt-4 grid min-h-[520px] gap-4 lg:grid-cols-[0.8fr_1.2fr]">
            <Panel title="来访用户" subtitle="选择用户后追索其完整操作链路">
              <button type="button" onClick={() => { setSelectedActor(""); setPage(1); }} className={`mb-2 flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[11px] ${!appliedActor ? "bg-[#eaf7ef] text-[#178a53]" : "bg-[#f7f8fa] text-[#636366]"}`}><span>全部用户</span><span>{snapshot.summary.total_visitors} 人</span></button>
              <div className="max-h-[430px] space-y-1.5 overflow-y-auto pr-1">
                {snapshot.users.map((item) => <button key={item.actor_user_id} type="button" onClick={() => { setSelectedActor(item.actor_user_id); setPage(1); }} className={`w-full rounded-xl border p-3 text-left transition-colors ${appliedActor === item.actor_user_id ? "border-[#b7ddc3] bg-[#f1faf4]" : "border-[#ececf0] bg-white hover:bg-[#fafbfc]"}`}>
                  <div className="flex items-center justify-between gap-3"><span className="truncate text-[12px] font-medium text-[#1d1d1f]">{item.actor_name}</span><span className="shrink-0 text-[11px] tabular-nums text-[#178a53]">{item.visits} 次访问</span></div>
                  <div className="mt-1 truncate text-[10px] text-[#9a9aa0]">{item.actor_account || item.actor_user_id}</div>
                  <div className="mt-1 truncate text-[10px] text-[#6f8778]" title={item.tenant_ids.map(tenantDisplayName).join("、")}>机构：{item.tenant_ids.map(tenantDisplayName).join("、") || "未知机构"}</div>
                  <div className="mt-2 flex items-center justify-between text-[10px] text-[#77777d]"><span className="truncate">常看：{item.top_page ? pageDisplayName(item.top_page) : "—"}</span><span className={item.breakpoints ? "text-[#b7791f]" : ""}>{item.events} 个动作{item.breakpoints ? ` · ${item.breakpoints} 个断点` : ""}</span></div>
                </button>)}
              </div>
            </Panel>

            <Panel title="访问链路追索" subtitle={selectedUser ? `${selectedUser.actor_name} · 按时间倒序` : "全部用户 · 按时间倒序"}>
              <div className="relative max-h-[470px] overflow-y-auto pr-1">
                {snapshot.timeline.items.map((event, index) => <TimelineRow key={event.event_id || `${event.occurred_at}-${index}`} event={event} first={index === 0} last={index === snapshot.timeline.items.length - 1} />)}
                {!snapshot.timeline.items.length && <MutedEmpty text="当前筛选条件下没有行为记录" />}
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-[#f0f0f2] pt-3 text-[10px] text-[#8a8a8e]">
                <span>共 {snapshot.timeline.total} 条 · 第 {snapshot.timeline.page} 页</span>
                <div className="flex gap-1.5">
                  <button type="button" aria-label="上一页" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1} className="flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] bg-white disabled:opacity-40"><ChevronLeft className="h-3.5 w-3.5" /></button>
                  <button type="button" aria-label="下一页" onClick={() => setPage((value) => value + 1)} disabled={page * snapshot.timeline.page_size >= snapshot.timeline.total} className="flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] bg-white disabled:opacity-40"><ChevronRight className="h-3.5 w-3.5" /></button>
                </div>
              </div>
            </Panel>
          </section>
        </>
      ) : <EmptyState title="当前周期暂无埋点数据" detail="用户完成登录、菜单访问或图表配置后，行为会通过现有轻量链路写入并显示在这里。" />}
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, hint, selected, onSelect }: { icon: typeof Activity; label: string; value: string; hint: string; selected: boolean; onSelect: () => void }) {
  return <button type="button" onClick={onSelect} aria-pressed={selected} data-trend-metric-card={label} className={`rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#86c99d] ${selected ? "border-[#86c99d] bg-[#f4fbf6] shadow-[0_0_0_1px_#d9efdf]" : "border-[#f0f0f2] bg-white hover:border-[#cfe8d7] hover:bg-[#fbfefc]"}`}><div className="flex items-center justify-between"><span className={`text-[11px] ${selected ? "font-medium text-[#26724a]" : "text-[#77777d]"}`}>{label}</span><Icon className="h-4 w-4 text-[#55a578]" /></div><div className="mt-3 text-[24px] font-light tabular-nums text-[#1d1d1f]">{value}</div><div className="mt-1 truncate text-[10px] text-[#a0a0a5]" title={hint}>{hint}</div></button>;
}

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return <section className="rounded-xl border border-[#f0f0f2] bg-white p-4"><div className="mb-3"><h3 className="text-[14px] text-[#1d1d1f]">{title}</h3>{subtitle && <p className="mt-1 text-[11px] text-[#8a8a8e]">{subtitle}</p>}</div>{children}</section>;
}

function WeeklyTrend({ items, metric }: { items: InteractionAnalyticsSnapshot["weekly"]; metric: TrendMetricKey }) {
  const definition = trendDefinition(metric);
  const values = items.map((item) => definition.value(item));
  const max = Math.max(1, ...values.map((value) => value ?? 0));
  if (!items.length) return <MutedEmpty text="暂无周访问数据" />;
  return <div className="flex h-40 items-end gap-3 overflow-x-auto px-1 pt-4" data-weekly-trend-metric={metric}>{items.map((item, index) => {
    const value = values[index];
    const heightValue = value ?? 0;
    return <div key={item.week_start} className="flex min-w-[54px] flex-1 flex-col items-center justify-end"><div className="mb-1 text-[10px] tabular-nums text-[#178a53]">{definition.format(value)}</div><div className="w-full max-w-12 rounded-t-md bg-gradient-to-t from-[#c9ead4] to-[#66b684]" style={{ height: `${value === null ? 2 : Math.max(8, heightValue / max * 104)}px` }} title={`${formatWeek(item.week_start)} · ${definition.format(value)}`} /><div className="mt-2 whitespace-nowrap text-[9px] text-[#8a8a8e]">{formatWeek(item.week_start)}</div></div>;
  })}</div>;
}

function trendDefinition(metric: TrendMetricKey) {
  const definitions: Record<TrendMetricKey, {
    title: string;
    subtitle: string;
    value: (item: InteractionAnalyticsSnapshot["weekly"][number]) => number | null;
    format: (value: number | null) => string;
  }> = {
    visits: { title: "每周访问次数趋势", subtitle: "访问次数按 30 分钟会话间隔推导", value: (item) => item.visits, format: (value) => `${formatNumber(value || 0)} 次` },
    visitors: { title: "每周访问人数趋势", subtitle: "每周按用户去重，跨机构访问仍计为同一用户", value: (item) => item.visitors, format: (value) => `${formatNumber(value || 0)} 人` },
    this_week_visits: { title: "每周访问次数趋势", subtitle: "当前卡片值为本周访问次数，趋势展示各周同口径访问次数", value: (item) => item.visits, format: (value) => `${formatNumber(value || 0)} 次` },
    events: { title: "每周行为事件趋势", subtitle: "按事件发生周汇总现有轻量埋点", value: (item) => item.events, format: (value) => `${formatNumber(value || 0)} 条` },
    peak_hour: { title: "每周访问高峰趋势", subtitle: "每周事件量最高的小时（北京时间）", value: (item) => item.peak_hour, format: (value) => value === null ? "—" : `${padHour(value)}:00` },
  };
  return definitions[metric];
}

function MiniCount({ label, value }: { label: string; value: number }) {
  return <div className="rounded-xl bg-[#f7f8fa] px-2 py-3 text-center"><div className="text-[20px] font-light tabular-nums text-[#1d1d1f]">{value}</div><div className="mt-1 text-[9px] text-[#8a8a8e]">{label}</div></div>;
}

function RankingPanel({ title, items, empty }: { title: string; items: InteractionCountItem[]; empty: string }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return <Panel title={title}>{items.length ? <div className="space-y-2.5">{items.slice(0, 6).map((item, index) => <div key={item.value}><div className="flex items-center justify-between gap-2 text-[10px]"><span className="truncate text-[#4a4a4f]">{index + 1}. {item.value}</span><span className="tabular-nums text-[#8a8a8e]">{item.count}</span></div><div className="mt-1 h-1 rounded-full bg-[#f0f0f2]"><div className="h-full rounded-full bg-[#69b486]" style={{ width: `${Math.max(6, item.count / max * 100)}%` }} /></div></div>)}</div> : <MutedEmpty text={empty} />}</Panel>;
}

function TimelineRow({ event, first, last }: { event: InteractionTimelineEvent; first: boolean; last: boolean }) {
  const detail = eventDetail(event);
  return <div className="relative grid grid-cols-[18px_minmax(0,1fr)] gap-3 pb-4"><div className="relative flex justify-center">{!first && <span className="absolute bottom-1/2 top-0 w-px bg-[#e2e8e4]" />}{!last && <span className="absolute bottom-0 top-1/2 w-px bg-[#e2e8e4]" />}<span className="relative mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#4eaa75] shadow-[0_0_0_1px_#b7ddc3]" /></div><div className="min-w-0 rounded-xl border border-[#f0f0f2] bg-[#fbfcfd] px-3 py-2.5"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-[11px] font-medium text-[#2f3c34]">{eventLabels[event.event_name] || event.event_name}</span><time className="text-[9px] tabular-nums text-[#9a9aa0]">{formatTime(event.occurred_at)}</time></div><div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[10px] text-[#737379]"><span>{event.actor_name}</span><span>· {tenantDisplayName(event.tenant_id)}</span>{(event.page_name || event.page_path) && <span>· {pageDisplayName(event.page_name || event.page_path)}</span>}{event.chart_name && <span>· 图表：{event.chart_name}</span>}</div>{detail && <div className="mt-1.5 rounded-md bg-white px-2 py-1 text-[10px] text-[#53615a]">{detail}</div>}</div></div>;
}

function eventDetail(event: InteractionTimelineEvent) {
  const extension = event.extension || {};
  const action = String(extension.action || "");
  const values = action === "metric" ? extension.metric_fields : action === "dimension" ? extension.dimension_fields : action === "style" ? [extension.chart_type] : action === "condition" ? [`${Number(extension.filter_count || 0)} 个条件`] : null;
  const list = Array.isArray(values) ? values.map(String).filter(Boolean) : [];
  if (action && list.length) return `${actionLabel(action)}：${list.join("、")}`;
  if (event.event_name === "export_result") return `导出格式：${String(extension.format || "未知")}`;
  return "";
}

function isRetryableInteractionAnalyticsError(error: unknown) {
  if (!(error instanceof ApiRequestError)) return false;
  return error.status === 0
    || [408, 429, 502, 503, 504].includes(error.status)
    || ["api_starting", "api_unavailable", "network_error", "request_timeout"].includes(error.code);
}

function actionLabel(action: string) { return ({ metric: "指标", dimension: "维度", style: "样式", condition: "条件" } as Record<string, string>)[action] || action; }
function pageDisplayName(value: string) { return pageLabels[value] || value; }
function tenantDisplayName(value: string) { return value.replace(/^tenant:/, "") || "未知机构"; }
function formatNumber(value: number) { return new Intl.NumberFormat("zh-CN").format(value); }
function padHour(value: number) { return String(value).padStart(2, "0"); }
function formatWeek(value: string) { const date = new Date(`${value}T00:00:00+08:00`); return `${date.getMonth() + 1}/${date.getDate()}`; }
function formatTime(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value)); }
function MutedEmpty({ text }: { text: string }) { return <div className="flex min-h-20 items-center justify-center rounded-xl border border-dashed border-[#e5e5ea] bg-[#fafbfc] px-3 text-center text-[10px] text-[#9a9aa0]">{text}</div>; }
function LoadingState() { return <div className="grid animate-pulse gap-4 sm:grid-cols-2 lg:grid-cols-5">{Array.from({ length: 5 }, (_, index) => <div key={index} className="h-32 rounded-xl border border-[#ececf0] bg-white" />)}</div>; }
function EmptyState({ title, detail }: { title: string; detail: string }) { return <div className="flex min-h-[420px] flex-col items-center justify-center rounded-xl border border-dashed border-[#dedfe3] bg-white text-center"><BarChart3 className="h-9 w-9 text-[#a8cdb5]" /><div className="mt-4 text-[14px] font-medium text-[#3a3a3c]">{title}</div><div className="mt-1 max-w-md text-[11px] leading-5 text-[#8a8a8e]">{detail}</div></div>; }
