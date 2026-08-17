# `platform_runtime_events`

- 领域：可观测性
- 用途：系统运行事件、状态和降级记录。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `runtime_event_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `trace_id` | `VARCHAR(100)` | 无 | 关联 Trace。 |
| `event_type` | `VARCHAR(160)` | NOT NULL | 事件类型。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('ok','degraded','error','cancelled')) | 状态。 |
| `latency_ms` | `INTEGER` | CHECK (latency_ms >= 0) | 耗时。 |
| `fallback_used` | `BOOLEAN` | NOT NULL DEFAULT false | 是否发生降级。 |
| `detail` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 脱敏详情。 |
| `occurred_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 发生时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_runtime_events_tenant_updated (tenant_id, updated_at, runtime_event_id)`
- `idx_platform_runtime_events_type (tenant_id, event_type, occurred_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
