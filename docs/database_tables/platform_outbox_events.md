# `platform_outbox_events`

- 领域：基础设施
- 用途：事务内登记待发布领域事件，支持可靠异步副作用。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `outbox_event_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `outbox_event_key` | `VARCHAR(160)` | NOT NULL | 投递服务使用的稳定事件标识。 |
| `aggregate_type` | `VARCHAR(120)` | NOT NULL | 聚合类型。 |
| `aggregate_id` | `VARCHAR(200)` | NOT NULL | 聚合 ID。 |
| `event_type` | `VARCHAR(160)` | NOT NULL | 事件类型。 |
| `payload` | `JSONB` | NOT NULL | 版本化事件负载。 |
| `event_version` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (event_version > 0) | 事件 schema 版本。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','publishing','published','failed')) | 投递状态。 |
| `available_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最早投递时间。 |
| `published_at` | `TIMESTAMPTZ` | 无 | 成功发布时间。 |
| `attempt_count` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (attempt_count >= 0) | 尝试次数。 |
| `last_error` | `TEXT` | 无 | 脱敏错误摘要。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_outbox_events_tenant_updated (tenant_id, updated_at, outbox_event_id)`
- `UNIQUE uq_platform_outbox_event_key (tenant_id, outbox_event_key)`
- `idx_platform_outbox_dispatch (status, available_at, outbox_event_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
