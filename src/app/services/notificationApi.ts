import { apiRequest } from "./apiClient";
import { getDefaultTenantId, getDefaultUserId } from "./apiContext";

export type NotificationSubscription = {
  subscription_id: string;
  subscription_name: string;
  event_types: string[];
  channel_type: "in_app" | "email" | "webhook";
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
