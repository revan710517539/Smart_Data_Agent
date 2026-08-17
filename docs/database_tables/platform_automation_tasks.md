# `platform_automation_tasks`

- 领域：自动化与通知
- 用途：定时、事件和手动自动化任务定义。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `automation_task_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `automation_task_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定任务标识。 |
| `task_code` | `VARCHAR(160)` | NOT NULL | 稳定任务编码。 |
| `task_name` | `VARCHAR(300)` | NOT NULL | 名称。 |
| `task_type` | `VARCHAR(40)` | NOT NULL CHECK (task_type IN ('acquisition','analysis','report','export','notification','quality','market_monitoring','custom')) | 任务类型。 |
| `trigger_type` | `VARCHAR(24)` | NOT NULL CHECK (trigger_type IN ('manual','schedule','event')) | 触发类型。 |
| `schedule_expression` | `VARCHAR(200)` | 无 | 调度表达式。 |
| `event_type` | `VARCHAR(160)` | 无 | 事件触发类型。 |
| `handler_ref` | `VARCHAR(300)` | NOT NULL | 已注册 handler。 |
| `task_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 类型化任务配置。 |
| `retry_policy` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 重试策略。 |
| `timeout_seconds` | `INTEGER` | NOT NULL DEFAULT 900 CHECK (timeout_seconds BETWEEN 1 AND 86400) | 总体超时。 |
| `max_concurrency` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (max_concurrency BETWEEN 1 AND 100) | 任务并发上限。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','disabled')) | 状态。 |
| `next_run_at` | `TIMESTAMPTZ` | 无 | 下次运行。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 任务所有者。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_automation_tasks_tenant_updated (tenant_id, updated_at, automation_task_id)`
- `UNIQUE uq_platform_automation_tasks_key (tenant_id, automation_task_key)`
- `UNIQUE uq_platform_automation_tasks_code (tenant_id, task_code)`
- `idx_platform_automation_tasks_due (status, next_run_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
