# `platform_report_learning_candidates`

- 领域：经营周报
- 用途：从周报版本提炼的经验、习惯和待办候选。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `learning_candidate_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `learning_candidate_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定候选标识。 |
| `report_version_id` | `UUID` | NOT NULL REFERENCES platform_weekly_report_versions(report_version_id) ON DELETE CASCADE | 来源周报版本。 |
| `candidate_type` | `VARCHAR(24)` | NOT NULL CHECK (candidate_type IN ('experience','analysis_method','behavior_habit','todo','knowledge','business_fact')) | 候选类型。 |
| `candidate_content` | `JSONB` | NOT NULL | 结构化候选内容。 |
| `evidence` | `JSONB` | NOT NULL | 来源块和分析证据。 |
| `confidence` | `NUMERIC(7,4)` | CHECK (confidence BETWEEN 0 AND 1) | 置信度。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 候选内容 hash，用于去重。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending_review' CHECK (status IN ('pending_review','approved','rejected','applied','superseded')) | 人工审核状态。 |
| `reviewed_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 审核人。 |
| `reviewed_at` | `TIMESTAMPTZ` | 无 | 审核时间。 |
| `applied_resource_type` | `VARCHAR(40)` | 无 | 生效资源类型。 |
| `applied_resource_id` | `UUID` | 无 | 生效资源 ID。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_report_learning_candidates_tenant_updated (tenant_id, updated_at, learning_candidate_id)`
- `UNIQUE uq_platform_report_learning_candidate_key (tenant_id, learning_candidate_key)`
- `UNIQUE uq_platform_report_learning_candidate_content (report_version_id, candidate_type, content_hash)`
- `idx_platform_report_learning_candidates_review (tenant_id, status, created_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
