# `platform_acquisition_job_runs`

- 领域：数据接入
- 用途：每次数据获取执行、租约、游标、错误和产物。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `acquisition_run_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `run_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定采集执行标识。 |
| `acquisition_job_id` | `UUID` | NOT NULL REFERENCES platform_acquisition_jobs(acquisition_job_id) ON DELETE RESTRICT | 任务定义。 |
| `trigger_type` | `VARCHAR(24)` | NOT NULL | 实际触发类型。 |
| `idempotency_key` | `VARCHAR(200)` | NOT NULL | 业务幂等键。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','repair_review')) | 状态。 |
| `attempt_no` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (attempt_no > 0) | 尝试次数。 |
| `lease_owner` | `VARCHAR(200)` | 无 | Worker 租约持有者。 |
| `lease_expires_at` | `TIMESTAMPTZ` | 无 | 租约到期。 |
| `input_cursor` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输入同步游标。 |
| `output_cursor` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 成功游标。 |
| `rows_read` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (rows_read >= 0) | 读取行数。 |
| `rows_written` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (rows_written >= 0) | 写入行数。 |
| `source_snapshot` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 上游快照、水位和不可变版本证据。 |
| `quality_summary` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 质量规则汇总和阻断状态。 |
| `output_artifact_id` | `UUID` | 无 | 成功输出 Artifact；外键在建表完成后补充。 |
| `partition_id` | `UUID` | 无 | 成功分区；外键在建表完成后补充。 |
| `started_at` | `TIMESTAMPTZ` | 无 | 开始时间。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `error_code` | `VARCHAR(100)` | 无 | 稳定错误码。 |
| `error_summary` | `TEXT` | 无 | 脱敏错误摘要。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_acquisition_job_runs_tenant_updated (tenant_id, updated_at, acquisition_run_id)`
- `UNIQUE uq_platform_acquisition_run_key (tenant_id, run_key)`
- `UNIQUE uq_platform_acquisition_run_idempotency (tenant_id, acquisition_job_id, idempotency_key)`
- `idx_platform_acquisition_runs_status (tenant_id, status, created_at)`

## 延后建立的外键

- `fk_platform_acquisition_runs_artifact`：`output_artifact_id` → `platform_data_artifacts(artifact_id)`，删除策略 `SET NULL`。
- `fk_platform_acquisition_runs_partition`：`partition_id` → `platform_dataset_partitions(partition_id)`，删除策略 `SET NULL`。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
