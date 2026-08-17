# `platform_analysis_evidence`

- 领域：智能分析
- 用途：结论与查询、分区、数据值、知识引用之间的证据边。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `analysis_evidence_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `evidence_key` | `VARCHAR(200)` | NOT NULL | 上游生成的稳定证据标识。 |
| `analysis_task_id` | `UUID` | NOT NULL REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE CASCADE | 分析任务。 |
| `conclusion_artifact_id` | `UUID` | REFERENCES platform_analysis_artifacts(analysis_artifact_id) ON DELETE CASCADE | 结论产物。 |
| `evidence_type` | `VARCHAR(32)` | NOT NULL CHECK (evidence_type IN ('query','partition','row','aggregate','knowledge','market','quality')) | 证据类型。 |
| `evidence_ref_id` | `UUID` | NOT NULL | 证据实体 ID。 |
| `metric_id` | `UUID` | REFERENCES platform_metric_dictionary(metric_id) ON DELETE RESTRICT | 指标。 |
| `dimension_context` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 维度和值。 |
| `observed_value` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 引用值。 |
| `evidence_hash` | `CHAR(64)` | NOT NULL | 证据 hash。 |
| `freshness_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'unknown' CHECK (freshness_status IN ('fresh','stale','unknown','blocked')) | 新鲜度。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_evidence_tenant_updated (tenant_id, updated_at, analysis_evidence_id)`
- `UNIQUE uq_platform_analysis_evidence_key (tenant_id, evidence_key)`
- `idx_platform_analysis_evidence_task (analysis_task_id, evidence_type)`
- `idx_platform_analysis_evidence_conclusion (conclusion_artifact_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
