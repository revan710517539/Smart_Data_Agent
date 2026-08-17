import { getApiBaseUrl } from "./apiClient";

export type InteractionEventInput = {
  eventName: string;
  eventType?: "click" | "view";
  pagePath?: string;
  pageName?: string;
  chartId?: string;
  chartName?: string;
  resourceType?: string;
  resourceId?: string;
  extension?: Record<string, unknown>;
};

export function trackInteraction(input: InteractionEventInput) {
  const payload = {
    event_name: input.eventName,
    event_type: input.eventType || "click",
    page_path: input.pagePath || window.location.pathname,
    page_name: input.pageName || document.title,
    chart_id: input.chartId || "",
    chart_name: input.chartName || "",
    resource_type: input.resourceType || "",
    resource_id: input.resourceId || "",
    extension: sanitizeExtension(input.extension || {}),
  };
  // Product telemetry is deliberately isolated from apiRequest: mutations made
  // through apiRequest invalidate the small page-read cache, while an analytics
  // write must never make the current product interaction slower or less stable.
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 3_000);
  void fetch(`${getApiBaseUrl()}/api/interaction-events`, {
    method: "POST",
    credentials: "include",
    keepalive: true,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).catch(() => undefined).finally(() => window.clearTimeout(timeoutId));
}

export function boundedInteractionText(value: string) {
  return value.replace(/(password|token|secret|authorization|cookie)\s*[:=]\s*\S+/gi, "$1=[redacted]").replace(/\s+/g, " ").trim().slice(0, 500);
}

function sanitizeExtension(value: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(value).slice(0, 30).map(([key, item]) => {
    if (/(password|secret|token|authorization|cookie|credential|sql|rows|raw_data)/i.test(key)) return [key, "[redacted]"];
    if (typeof item === "string") return [key, boundedInteractionText(item)];
    if (typeof item === "number" || typeof item === "boolean" || item == null) return [key, item];
    return [key, JSON.stringify(item).slice(0, 500)];
  }));
}
