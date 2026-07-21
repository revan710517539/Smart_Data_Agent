import { apiRequest } from "./apiClient";

export type RuntimeSummary = {
  sample_size: number;
  ok_count: number;
  error_count: number;
  fallback_count: number;
  avg_latency_ms: number;
  last_status: string | null;
  last_latency_ms: number | null;
  last_seen_at: string | null;
};

export type SystemHealthResponse = {
  status: string;
  ready: boolean;
  service: string;
  semantic_client_mode: string;
  semantic_routing_mode?: string;
  semantic_fallback_mode?: string;
  data_source_mode?: string;
  route_count?: number;
  environment?: string;
  checks?: Record<string, {
    ready?: boolean;
    error?: string;
    adapter?: string;
    backend?: string;
    durable?: boolean;
  }>;
  runtime: RuntimeSummary;
};

export async function getSystemHealth(): Promise<SystemHealthResponse> {
  return apiRequest<SystemHealthResponse>("/api/health", { method: "GET", timeoutMs: 8000 });
}
