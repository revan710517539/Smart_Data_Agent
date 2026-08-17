# `platform_analysis_queries`

- 领域：智能分析
- 用途：经权限编译并真实执行的 SQL/语义查询和结果摘要。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `analysis_query_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `analysis_task_id` | `UUID` | NOT NULL REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE CASCADE | 分析任务。 |
| `analysis_step_id` | `UUID` | REFERENCES platform_analysis_steps(analysis_step_id) ON DELETE SET NULL | 查询步骤。 |
| `connection_version_id` | `UUID` | NOT NULL REFERENCES platform_connection_versions(connection_version_id) ON DELETE RESTRICT | 实际连接版本。 |
| `dataset_id` | `UUID` | NOT NULL REFERENCES platform_datasets(dataset_id) ON DELETE RESTRICT | 数据集。 |
| `query_revision` | `INTEGER` | NOT NULL CHECK (query_revision > 0) | 人工修改后的 revision。 |
| `compiled_sql` | `TEXT` | NOT NULL | 权限下推后的已执行 SQL。 |
| `sql_hash` | `CHAR(64)` | NOT NULL | 执行 SQL hash。 |
| `parameters` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 类型化绑定参数。 |
| `policy_snapshot` | `JSONB` | NOT NULL | 编译时权限证据。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')) | 状态。 |
| `result_artifact_id` | `UUID` | REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 完整结果产物。 |
| `result_hash` | `CHAR(64)` | 无 | 规范化结果 hash。 |
| `row_count` | `BIGINT` | CHECK (row_count >= 0) | 完整结果行数。 |
| `summary` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 完整总计和分页摘要。 |
| `started_at` | `TIMESTAMPTZ` | 无 | 开始时间。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_queries_tenant_updated (tenant_id, updated_at, analysis_query_id)`
- `UNIQUE uq_platform_analysis_queries_revision (analysis_task_id, query_revision)`
- `idx_platform_analysis_queries_hash (tenant_id, sql_hash, created_at)`

## 设计说明

- 页面展示 SQL 必须与 compiled_sql 和 sql_hash 完全一致。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
