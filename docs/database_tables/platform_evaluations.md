# `platform_evaluations`

- 领域：智能分析
- 用途：对最终 SQL、数据、图表、结论和权限的质量评审。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `evaluation_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `analysis_task_id` | `UUID` | NOT NULL REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE CASCADE | 分析任务。 |
| `revision` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (revision > 0) | 所属分析 revision。 |
| `evaluation_type` | `VARCHAR(40)` | NOT NULL CHECK (evaluation_type IN ('sql_data_match','metric_correctness','faithfulness','permission','freshness','visualization','overall')) | 评审类型。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('passed','warning','failed','error')) | 结果。 |
| `score` | `NUMERIC(7,4)` | CHECK (score BETWEEN 0 AND 1) | 得分。 |
| `checks` | `JSONB` | NOT NULL | 逐项检查结果。 |
| `evaluator_type` | `VARCHAR(16)` | NOT NULL CHECK (evaluator_type IN ('deterministic','model','human')) | 评审器类型。 |
| `evaluator_version` | `VARCHAR(160)` | NOT NULL | 评审器版本。 |
| `evaluated_artifact_hash` | `CHAR(64)` | NOT NULL | 被评审最终产物 hash。 |
| `evaluated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 评审时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_evaluations_tenant_updated (tenant_id, updated_at, evaluation_id)`
- `UNIQUE uq_platform_evaluations_revision (analysis_task_id, revision, evaluation_type)`
- `idx_platform_evaluations_task (analysis_task_id, evaluation_type, evaluated_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
