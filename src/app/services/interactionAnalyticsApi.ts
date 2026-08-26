import { apiRequest } from "./apiClient";

type Context = { tenantId: string; userId: string };

export type InteractionCountItem = { value: string; count: number };
export type InteractionWeeklyItem = { week_start: string; visitors: number; visits: number; events: number; peak_hour: number | null };
export type InteractionHourlyItem = { hour: number; events: number };
export type InteractionUserSummary = {
  actor_user_id: string;
  actor_name: string;
  actor_account: string;
  visits: number;
  events: number;
  last_seen: string;
  top_page: string;
  breakpoints: number;
  tenant_ids: string[];
};
export type InteractionBreakpoint = {
  type: "menu_without_page_view" | "configuration_not_completed" | "repeated_action" | string;
  actor_user_id: string;
  actor_name: string;
  event_name: string;
  page_path: string;
  tenant_id: string;
  occurred_at: string;
  description: string;
};
export type InteractionTimelineEvent = {
  event_id: string;
  tenant_id: string;
  actor_user_id: string;
  actor_name: string;
  actor_account: string;
  event_name: string;
  event_type: string;
  page_path: string;
  page_name: string;
  chart_id: string;
  chart_name: string;
  resource_type: string;
  resource_id: string;
  extension: Record<string, unknown>;
  occurred_at: string;
};

export type InteractionAnalyticsSnapshot = {
  tenant_id: string;
  scope: "global";
  tenant_ids: string[];
  range: { since: string; until: string; timezone: string; session_gap_minutes: number };
  summary: {
    total_visitors: number;
    total_visits: number;
    total_events: number;
    average_visits_per_user: number;
    this_week_visits: number;
    active_days: number;
    peak_hour: number | null;
  };
  weekly: InteractionWeeklyItem[];
  hourly: InteractionHourlyItem[];
  top_pages: InteractionCountItem[];
  top_metrics: InteractionCountItem[];
  top_dimensions: InteractionCountItem[];
  top_styles: InteractionCountItem[];
  users: InteractionUserSummary[];
  breakpoint_summary: {
    menu_without_page_view: number;
    configuration_not_completed: number;
    repeated_action: number;
    total: number;
  };
  breakpoints: InteractionBreakpoint[];
  timeline: { items: InteractionTimelineEvent[]; total: number; page: number; page_size: number };
  sampled_events: number;
  truncated: boolean;
};

const emptySummary: InteractionAnalyticsSnapshot["summary"] = {
  total_visitors: 0,
  total_visits: 0,
  total_events: 0,
  average_visits_per_user: 0,
  this_week_visits: 0,
  active_days: 0,
  peak_hour: null,
};

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

export function normalizeInteractionAnalyticsSnapshot(
  payload: Partial<InteractionAnalyticsSnapshot> | null | undefined,
  fallback: { page: number; pageSize: number },
): InteractionAnalyticsSnapshot {
  const source = payload || {};
  const breakpoints = arrayOrEmpty<InteractionBreakpoint>(source.breakpoints);
  const users = arrayOrEmpty<InteractionUserSummary>(source.users).map((item) => ({
    ...item,
    tenant_ids: arrayOrEmpty<string>(item?.tenant_ids),
  }));
  const timeline = source.timeline || { items: [], total: 0, page: fallback.page, page_size: fallback.pageSize };
  const breakpointSummary = source.breakpoint_summary || {
    menu_without_page_view: breakpoints.filter((item) => item.type === "menu_without_page_view").length,
    configuration_not_completed: breakpoints.filter((item) => item.type === "configuration_not_completed").length,
    repeated_action: breakpoints.filter((item) => item.type === "repeated_action").length,
    total: breakpoints.length,
  };
  return {
    tenant_id: String(source.tenant_id || ""),
    scope: "global",
    tenant_ids: arrayOrEmpty<string>(source.tenant_ids),
    range: {
      since: String(source.range?.since || ""),
      until: String(source.range?.until || ""),
      timezone: String(source.range?.timezone || "Asia/Shanghai"),
      session_gap_minutes: Number(source.range?.session_gap_minutes || 30),
    },
    summary: { ...emptySummary, ...(source.summary || {}) },
    weekly: arrayOrEmpty<InteractionWeeklyItem>(source.weekly).map((item) => ({ ...item, peak_hour: item?.peak_hour ?? null })),
    hourly: arrayOrEmpty<InteractionHourlyItem>(source.hourly),
    top_pages: arrayOrEmpty<InteractionCountItem>(source.top_pages),
    top_metrics: arrayOrEmpty<InteractionCountItem>(source.top_metrics),
    top_dimensions: arrayOrEmpty<InteractionCountItem>(source.top_dimensions),
    top_styles: arrayOrEmpty<InteractionCountItem>(source.top_styles),
    users,
    breakpoint_summary: breakpointSummary,
    breakpoints,
    timeline: {
      items: arrayOrEmpty<InteractionTimelineEvent>(timeline.items),
      total: Number(timeline.total || 0),
      page: Number(timeline.page || fallback.page),
      page_size: Number(timeline.page_size || fallback.pageSize),
    },
    sampled_events: Number(source.sampled_events || 0),
    truncated: source.truncated === true,
  };
}

export async function fetchInteractionAnalytics(
  { days = 7, actorUserId = "", page = 1, pageSize = 50 }: { days?: number; actorUserId?: string; page?: number; pageSize?: number },
  context: Context,
) {
  const params = new URLSearchParams({
    days: String(days),
    page: String(page),
    page_size: String(pageSize),
  });
  if (actorUserId) params.set("actor_user_id", actorUserId);
  const response = await apiRequest<Partial<InteractionAnalyticsSnapshot>>(`/api/interaction-events/analytics?${params}`, {
    context,
    readCache: { ttlMs: 5_000, tags: ["interaction-analytics"], forceRefresh: true },
  });
  return normalizeInteractionAnalyticsSnapshot(response, { page, pageSize });
}
