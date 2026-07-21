# `platform_automation_task_runs`

- 领域：自动化与通知
- 用途：自动化任务每次运行、租约、重试和恢复状态。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `automation_run_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `automation_run_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定运行标识。 |
| `automation_task_id` | `UUID` | NOT NULL REFERENCES platform_automation_tasks(automation_task_id) ON DELETE RESTRICT | 任务定义。 |
| `idempotency_key` | `VARCHAR(200)` | NOT NULL | 幂等键。 |
| `trigger_type` | `VARCHAR(24)` | NOT NULL | 实际触发类型。 |
| `trigger_payload` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 脱敏触发参数。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('queued','running','retry_wait','succeeded','failed','cancelled')) | 状态。 |
| `attempt_no` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (attempt_no > 0) | 尝试次数。 |
| `lease_owner` | `VARCHAR(200)` | 无 | Worker 租约。 |
| `lease_expires_at` | `TIMESTAMPTZ` | 无 | 租约到期。 |
| `started_at` | `TIMESTAMPTZ` | 无 | 开始时间。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `next_retry_at` | `TIMESTAMPTZ` | 无 | 下次重试。 |
| `result_refs` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 产物和业务结果 ID。 |
| `error_code` | `VARCHAR(100)` | 无 | 稳定错误码。 |
| `error_summary` | `TEXT` | 无 | 脱敏错误摘要。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_automation_task_runs_tenant_updated (tenant_id, updated_at, automation_run_id)`
- `UNIQUE uq_platform_automation_runs_key (tenant_id, automation_run_key)`
- `UNIQUE uq_platform_automation_runs_idempotency (tenant_id, automation_task_id, idempotency_key)`
- `idx_platform_automation_runs_status (tenant_id, status, created_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
