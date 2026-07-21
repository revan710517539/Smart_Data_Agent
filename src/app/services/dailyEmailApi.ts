import { apiRequest } from "./apiClient";
import { getDefaultTenantId, getDefaultUserId } from "./apiContext";

export type DailyEmailRun = {
  daily_report_run_id: string;
  report_date: string;
  source_report_version_id: string;
  subject: string;
  body_artifact_id: string;
  content_hash: string;
  evidence_summary: Record<string, unknown>;
  preview_text: string;
  status: "generated" | "queued" | "sending" | "delivered" | "failed";
  outbox_event_id?: string;
  created_at: string;
  updated_at: string;
};

export type DailyEmailState = {
  tenant_id: string;
  runs: DailyEmailRun[];
  latest: DailyEmailRun | null;
  email_subscription_count: number;
  delivery_summary: Record<string, number>;
};

type Context = { tenantId?: string; userId?: string };

export function fetchDailyEmailState({ tenantId = getDefaultTenantId(), userId = getDefaultUserId() }: Context = {}) {
  return apiRequest<DailyEmailState>("/api/email-daily", { method: "GET", context: { tenantId, userId } });
}

export function generateDailyEmail({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  reportDate,
}: Context & { reportDate?: string } = {}) {
  return apiRequest<{ tenant_id: string; run: DailyEmailRun }>("/api/email-daily/generate", {
    method: "POST",
    context: { tenantId, userId },
    body: reportDate ? { report_date: reportDate } : {},
  });
}

export function sendDailyEmail({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  dailyReportRunId,
}: Context & { dailyReportRunId: string }) {
  return apiRequest<{ tenant_id: string; run: DailyEmailRun }>("/api/email-daily/send", {
    method: "POST",
    context: { tenantId, userId },
    body: { daily_report_run_id: dailyReportRunId },
  });
}
