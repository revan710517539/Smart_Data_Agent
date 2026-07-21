import { apiRequest } from "./apiClient";
import { getDefaultTenantId, getDefaultUserId } from "./apiContext";

export type MarketSource = {
  market_source_id: string;
  publisher: string;
  license_type: string;
  source_url?: string;
  reliability_score: number;
  status: string;
};

export type MarketEntity = {
  market_entity_id: string;
  entity_type: string;
  entity_code: string;
  entity_name: string;
  attributes: Record<string, unknown>;
  status: string;
};

export type MarketObservation = {
  market_observation_id: string;
  market_source_id: string;
  market_entity_id: string;
  entity_name: string;
  metric_code: string;
  observed_at: string;
  value_numeric?: number;
  value_text?: string;
  unit?: string;
  currency?: string;
  evidence_artifact_id: string;
  evidence_hash: string;
  publisher: string;
  license_type: string;
  confidence: number;
};

export type MarketRule = {
  market_rule_id: string;
  rule_name: string;
  metric_code: string;
  condition_expression: { operator?: string; threshold?: number };
  severity: string;
  status: string;
  created_at: string;
};

export type MarketEvent = {
  market_event_id: string;
  market_rule_id: string;
  status: string;
  severity: string;
  event_summary: string;
  evidence: Record<string, unknown>;
  detected_at: string;
};

export type MarketBundle = {
  tenant_id: string;
  sources: MarketSource[];
  entities: MarketEntity[];
  observations: MarketObservation[];
  rules: MarketRule[];
  events: MarketEvent[];
};

export function fetchMarketBundle({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: { tenantId?: string; userId?: string } = {}) {
  return apiRequest<MarketBundle>("/api/market-monitoring", {
    method: "GET",
    context: { tenantId, userId },
  });
}
