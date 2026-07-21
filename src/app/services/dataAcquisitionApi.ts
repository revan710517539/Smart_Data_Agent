import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type DataQualityResult = {
  quality_result_id: string;
  acquisition_run_id: string;
  acquisition_job_id: string;
  target_dataset_id: string;
  topic_table_id?: string | null;
  rule_code: string;
  status: "passed" | "warning" | "failed" | "error";
  score: number;
  observed_value: Record<string, unknown>;
  threshold_value: Record<string, unknown>;
  blocking: boolean;
  evaluated_at: string;
  source_snapshot: Record<string, unknown>;
  quality_summary: Record<string, unknown>;
  run_status: string;
};

export type AcquisitionJob = {
  acquisition_job_id: string;
  job_name: string;
  job_code?: string;
  connection_id: string;
  target_dataset_id: string;
  topic_table_id?: string | null;
  execution_mode?: "realtime" | "offline";
  script_version_id?: string;
  job_config?: Record<string, unknown>;
  status: string;
};

export type SQLDecomposition = {
  dialect: string;
  statement_type: string;
  normalized_sql: string;
  query_hash: string;
  raw_tables: Array<{ catalog: string; schema: string; table: string; alias: string; qualified_name: string }>;
  fields: Array<{ output_name: string; expression: string; source_columns: string[]; aggregate: string }>;
  joins: Array<{ table: string; alias: string; join_type: string; condition: string }>;
  ctes: string[];
  filters: string[];
  group_by: string[];
  order_by: string[];
  parameters: string[];
  confidence: number;
  warnings: string[];
};

export type TopicMetadataStatus = {
  topic_table_id: string;
  status: "not_fetched" | "partial" | "complete" | "failed";
  last_synced_at?: string | null;
  schema_changed: boolean;
  raw_tables: Array<{
    dataset_code: string;
    dataset_name: string;
    source_alias: string;
    join_role: string;
    field_count: number;
    unknown_field_count?: number;
    updated_at?: string;
  }>;
};

export type TopicMetadataRefreshResult = TopicMetadataStatus & {
  transport_status: string;
  schema_changed_tables: string[];
  metadata_artifact_id?: string;
  diagnostics?: Record<string, unknown>;
};

export type AcquisitionExecution = {
  acquisition_run_id: string;
  acquisition_job_id: string;
  topic_table_id?: string | null;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  rows_read: number;
  error_code?: string | null;
  error_summary?: string | null;
};

export async function fetchDataAcquisition({ tenantId, userId = getDefaultUserId() }: { tenantId: string; userId?: string }) {
  return apiRequest<{
    quality_results: DataQualityResult[];
    jobs: AcquisitionJob[];
    runs: Array<Record<string, unknown>>;
  }>("/api/data-acquisition", {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function parseAcquisitionSql({
  tenantId,
  userId = getDefaultUserId(),
  sql,
  dialect = "postgres",
}: { tenantId: string; userId?: string; sql: string; dialect?: string }) {
  return apiRequest<{ tenant_id: string; decomposition: SQLDecomposition }>("/api/data-acquisition/sql/parse", {
    method: "POST",
    context: { tenantId, userId },
    body: { sql, dialect },
  });
}

export async function refreshTopicMetadata({
  tenantId,
  userId = getDefaultUserId(),
  topicTableId,
  cascade = false,
}: { tenantId: string; userId?: string; topicTableId: string; cascade?: boolean }) {
  return apiRequest<{ tenant_id: string; metadata: TopicMetadataRefreshResult }>("/api/data-acquisition/metadata/refresh", {
    method: "POST",
    context: { tenantId, userId },
    body: { topic_table_id: topicTableId, cascade },
  });
}

export async function fetchTopicMetadataStatus({
  tenantId,
  userId = getDefaultUserId(),
  topicTableId,
}: { tenantId: string; userId?: string; topicTableId: string }) {
  const params = new URLSearchParams({ topic_table_id: topicTableId });
  return apiRequest<{ tenant_id: string; metadata: TopicMetadataStatus }>(`/api/data-acquisition/metadata-status?${params}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function fetchAcquisitionExecutions({
  tenantId,
  userId = getDefaultUserId(),
  topicTableId,
}: { tenantId: string; userId?: string; topicTableId?: string }) {
  const params = new URLSearchParams();
  if (topicTableId) params.set("topic_table_id", topicTableId);
  return apiRequest<{ tenant_id: string; executions: AcquisitionExecution[]; count: number }>(`/api/data-acquisition/executions?${params}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function createScheduledAcquisitionTask({
  tenantId,
  userId = getDefaultUserId(),
  acquisitionJobId,
  topicTableId,
  connectionId,
  orgUnitId,
  keepLatestN,
  definition,
}: {
  tenantId: string;
  userId?: string;
  acquisitionJobId: string;
  topicTableId: string;
  connectionId: string;
  orgUnitId?: string;
  keepLatestN: number;
  definition: Record<string, unknown>;
}) {
  return apiRequest<{ tenant_id: string; task: Record<string, unknown>; job: AcquisitionJob }>("/api/data-acquisition/scheduled-task", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      acquisition_job_id: acquisitionJobId,
      topic_table_id: topicTableId,
      connection_id: connectionId,
      org_unit_id: orgUnitId,
      keep_latest_n: keepLatestN,
      definition,
    },
  });
}
