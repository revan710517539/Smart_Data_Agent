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
    return [key, sanitizeExtensionValue(item, 0)];
  }));
}

function sanitizeExtensionValue(value: unknown, depth: number): unknown {
  if (depth > 2) return "[depth_limited]";
  if (typeof value === "string") return boundedInteractionText(value);
  if (typeof value === "number" || typeof value === "boolean" || value == null) return value;
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => sanitizeExtensionValue(item, depth + 1));
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).slice(0, 20).map(([key, item]) => [
      key.slice(0, 80),
      /(password|secret|token|authorization|cookie|credential|sql|rows|raw_data)/i.test(key)
        ? "[redacted]"
        : sanitizeExtensionValue(item, depth + 1),
    ]));
  }
  return String(value).slice(0, 240);
}
