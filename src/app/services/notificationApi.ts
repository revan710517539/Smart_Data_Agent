import { apiRequest } from "./apiClient";
import { getDefaultTenantId, getDefaultUserId } from "./apiContext";

export type NotificationSubscription = {
  subscription_id: string;
  subscription_name: string;
  event_types: string[];
  channel_type: "in_app" | "email" | "webhook";
  channel_provider?: string;
  channel_config: { configured: boolean };
  filter_expression: Record<string, unknown>;
  quiet_hours: Record<string, unknown>;
  status: "active" | "paused" | "disabled";
  lock_version: number;
  created_at: string;
  updated_at: string;
};

export type NotificationDelivery = {
  delivery_id: string;
  subscription_id: string;
  outbox_event_id: string;
  channel_type: string;
  status: "queued" | "sending" | "delivered" | "failed" | "suppressed" | "dead_letter";
  provider_message_id?: string;
  error_code?: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  delivered_at?: string;
};

export type NotificationBundle = {
  tenant_id: string;
  subscriptions: NotificationSubscription[];
  in_app_deliveries: NotificationDelivery[];
  count: { subscriptions: number; in_app_deliveries: number };
};

export type TeamsConnection = {
  connected: boolean;
  provider: "360teams_self";
};

export type TeamsMetricTemplateItem = {
  metricId: string;
  fontSize: "small" | "normal" | "large";
  color: "slate" | "blue" | "green" | "amber" | "red";
};

export type TeamsMessageTemplate = {
  title: string;
  subtitle: string;
  footer: string;
  metrics: TeamsMetricTemplateItem[];
  /** Sanitized editable template body. Metric values are stored as {{metric:<id>}} placeholders. */
  bodyHtml?: string;
};

export function fetchNotificationBundle({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: { tenantId?: string; userId?: string } = {}) {
  return apiRequest<NotificationBundle>("/api/subscriptions", {
    method: "GET",
    context: { tenantId, userId },
  });
}

export function createNotificationSubscription({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  subscription,
}: {
  tenantId?: string;
  userId?: string;
  subscription: Record<string, unknown>;
}) {
  return apiRequest<{ tenant_id: string; subscription: NotificationSubscription }>("/api/subscription", {
    method: "POST",
    context: { tenantId, userId },
    body: subscription,
  });
}

export function updateNotificationSubscription({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  subscriptionId,
  expectedLockVersion,
  changes,
}: {
  tenantId?: string;
  userId?: string;
  subscriptionId: string;
  expectedLockVersion: number;
  changes: Record<string, unknown>;
}) {
  return apiRequest<{ tenant_id: string; subscription: NotificationSubscription }>("/api/subscription", {
    method: "PUT",
    context: { tenantId, userId },
    body: {
      subscription_id: subscriptionId,
      expected_lock_version: expectedLockVersion,
      ...changes,
    },
  });
}

export function disableNotificationSubscription({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  subscriptionId,
  expectedLockVersion,
}: {
  tenantId?: string;
  userId?: string;
  subscriptionId: string;
  expectedLockVersion: number;
}) {
  const query = new URLSearchParams({
    subscription_id: subscriptionId,
    expected_lock_version: String(expectedLockVersion),
  });
  return apiRequest<{ tenant_id: string; subscription: NotificationSubscription }>(`/api/subscription?${query}`, {
    method: "DELETE",
    context: { tenantId, userId },
  });
}

export function fetchTeamsConnection({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: { tenantId?: string; userId?: string } = {}) {
  return apiRequest<{ tenant_id: string; connection: TeamsConnection }>("/api/teams/connection", {
    method: "GET",
    context: { tenantId, userId },
  });
}

export function startTeamsConnectionAuthorization({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: { tenantId?: string; userId?: string } = {}) {
  return apiRequest<{ authorization: { device_code: string; sso_url: string } }>("/api/teams/connection/auth/start", {
    method: "POST",
    context: { tenantId, userId },
    body: {},
  });
}

export function pollTeamsConnectionAuthorization({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  deviceCode,
}: { tenantId?: string; userId?: string; deviceCode: string }) {
  return apiRequest<{ completed: boolean; connection: TeamsConnection }>("/api/teams/connection/auth/poll", {
    method: "POST",
    context: { tenantId, userId },
    body: { device_code: deviceCode },
  });
}

export function enableTeamsMetricSubscription({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  metricIds,
  subscriptionName,
  scheduleExpression,
  scheduleTimezone = "Asia/Shanghai",
  messageTemplate,
}: {
  tenantId?: string; userId?: string; metricIds: string[]; subscriptionName?: string; scheduleExpression?: string; scheduleTimezone?: string; messageTemplate?: TeamsMessageTemplate;
}) {
  return apiRequest<{ tenant_id: string; subscription: NotificationSubscription }>("/api/teams/metric-subscription/enable", {
    method: "POST",
    context: { tenantId, userId },
    body: { metric_ids: metricIds, subscription_name: subscriptionName, schedule_expression: scheduleExpression, schedule_timezone: scheduleTimezone, message_template: messageTemplate },
  });
}

export function testTeamsMetricSubscription({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  metricIds,
  subscriptionName,
  scheduleExpression,
  scheduleTimezone = "Asia/Shanghai",
  messageTemplate,
}: {
  tenantId?: string; userId?: string; metricIds: string[]; subscriptionName?: string; scheduleExpression?: string; scheduleTimezone?: string; messageTemplate?: TeamsMessageTemplate;
}) {
  return apiRequest<{ tenant_id: string; sent: boolean; provider_message_id: string }>("/api/teams/metric-subscription/test", {
    method: "POST",
    context: { tenantId, userId },
    body: { metric_ids: metricIds, subscription_name: subscriptionName, schedule_expression: scheduleExpression, schedule_timezone: scheduleTimezone, message_template: messageTemplate },
  });
}

export function startTeamsMetricSubscriptionAuthorization({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  metricId,
  subscriptionName,
  scheduleExpression,
  scheduleTimezone = "Asia/Shanghai",
}: {
  tenantId?: string; userId?: string; metricId: string; subscriptionName?: string; scheduleExpression?: string; scheduleTimezone?: string;
}) {
  return apiRequest<{ authorization: { device_code: string; sso_url: string } }>("/api/teams/metric-subscription/auth/start", {
    method: "POST", context: { tenantId, userId },
    body: { metric_id: metricId, subscription_name: subscriptionName, schedule_expression: scheduleExpression, schedule_timezone: scheduleTimezone },
  });
}

export function finishTeamsMetricSubscriptionAuthorization({
  tenantId = getDefaultTenantId(), userId = getDefaultUserId(), deviceCode, metricId, subscriptionName, scheduleExpression, scheduleTimezone = "Asia/Shanghai",
}: {
  tenantId?: string; userId?: string; deviceCode: string; metricId: string; subscriptionName?: string; scheduleExpression?: string; scheduleTimezone?: string;
}) {
  return apiRequest<{ completed: boolean; subscription?: NotificationSubscription }>("/api/teams/metric-subscription/auth/poll", {
    method: "POST", context: { tenantId, userId },
    body: { device_code: deviceCode, metric_id: metricId, subscription_name: subscriptionName, schedule_expression: scheduleExpression, schedule_timezone: scheduleTimezone },
  });
}
