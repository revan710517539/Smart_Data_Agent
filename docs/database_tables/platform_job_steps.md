# `platform_job_steps`

- 领域：自动化与通知
- 用途：自动化运行中的步骤、检查点和补偿状态。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `job_step_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `job_step_key` | `VARCHAR(160)` | NOT NULL | 稳定步骤记录标识。 |
| `automation_run_id` | `UUID` | NOT NULL REFERENCES platform_automation_task_runs(automation_run_id) ON DELETE CASCADE | 自动化运行。 |
| `step_code` | `VARCHAR(120)` | NOT NULL | 步骤编码。 |
| `sequence_no` | `INTEGER` | NOT NULL CHECK (sequence_no >= 0) | 顺序。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('pending','running','succeeded','failed','skipped','compensated')) | 状态。 |
| `checkpoint` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 可恢复检查点。 |
| `input_refs` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 输入引用。 |
| `output_refs` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 输出引用。 |
| `started_at` | `TIMESTAMPTZ` | 无 | 开始时间。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `error_code` | `VARCHAR(100)` | 无 | 错误码。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_job_steps_tenant_updated (tenant_id, updated_at, job_step_id)`
- `UNIQUE uq_platform_job_steps (automation_run_id, step_code)`
- `idx_platform_job_steps_order (automation_run_id, sequence_no)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
