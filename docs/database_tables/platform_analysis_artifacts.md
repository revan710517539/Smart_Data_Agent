# `platform_analysis_artifacts`

- 领域：智能分析
- 用途：脚本、图表、表格、草稿和结论等分析产物。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `analysis_artifact_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `analysis_task_id` | `UUID` | NOT NULL REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE CASCADE | 分析任务。 |
| `analysis_step_id` | `UUID` | REFERENCES platform_analysis_steps(analysis_step_id) ON DELETE SET NULL | 产生步骤。 |
| `revision` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (revision > 0) | 所属分析 revision。 |
| `artifact_type` | `VARCHAR(32)` | NOT NULL CHECK (artifact_type IN ('plan','python_script','chart','table','conclusion','model_draft','review','export')) | 产物类型。 |
| `execution_status` | `VARCHAR(24)` | NOT NULL CHECK (execution_status IN ('draft','executed','verified','rejected')) | 执行/验证状态。 |
| `content` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 小型结构化内容。 |
| `data_artifact_id` | `UUID` | REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 大型对象产物。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 产物 hash。 |
| `parent_artifact_id` | `UUID` | REFERENCES platform_analysis_artifacts(analysis_artifact_id) ON DELETE SET NULL | 父 revision。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_artifacts_tenant_updated (tenant_id, updated_at, analysis_artifact_id)`
- `idx_platform_analysis_artifacts_task (analysis_task_id, artifact_type, created_at)`
- `UNIQUE uq_platform_analysis_artifacts_revision (analysis_task_id, revision, artifact_type)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
