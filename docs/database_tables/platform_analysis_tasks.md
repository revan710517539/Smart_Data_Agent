# `platform_analysis_tasks`

- 领域：智能分析
- 用途：一次分析请求的聚合根和权威状态。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `analysis_task_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `task_key` | `VARCHAR(100)` | NOT NULL UNIQUE | API 使用的不可猜测稳定任务标识。 |
| `request_id` | `VARCHAR(100)` | NOT NULL | API 请求 ID。 |
| `trace_id` | `VARCHAR(100)` | NOT NULL | 端到端 trace ID。 |
| `requested_by` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 发起人。 |
| `question` | `TEXT` | NOT NULL | 用户问题。 |
| `execution_mode` | `VARCHAR(16)` | NOT NULL CHECK (execution_mode IN ('real','mock','degraded')) | 执行模式。 |
| `status` | `VARCHAR(32)` | NOT NULL CHECK (status IN ('queued','planning','running','review_required','succeeded','failed','cancelled')) | 权威状态。 |
| `current_revision` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (current_revision > 0) | 当前草稿/执行 revision。 |
| `analysis_plan` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 类型化执行计划。 |
| `context_snapshot` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 权限裁剪后的上下文引用。 |
| `response_snapshot` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 由规范化查询、证据和产物生成的版本化 API 读取投影。 |
| `deadline_at` | `TIMESTAMPTZ` | 无 | 总体 deadline。 |
| `started_at` | `TIMESTAMPTZ` | 无 | 开始时间。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `cancel_requested_at` | `TIMESTAMPTZ` | 无 | 取消请求时间。 |
| `error_code` | `VARCHAR(100)` | 无 | 稳定错误码。 |
| `error_summary` | `TEXT` | 无 | 脱敏错误摘要。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_tasks_tenant_updated (tenant_id, updated_at, analysis_task_id)`
- `UNIQUE uq_platform_analysis_tasks_request (tenant_id, request_id)`
- `idx_platform_analysis_tasks_user (tenant_id, requested_by, created_at)`
- `idx_platform_analysis_tasks_status (tenant_id, status, created_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
