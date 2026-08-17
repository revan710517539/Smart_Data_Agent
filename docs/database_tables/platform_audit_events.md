# `platform_audit_events`

- 领域：基础设施
- 用途：脱敏、追加写的安全与业务审计事件。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `audit_event_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `actor_user_id` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 操作者。 |
| `event_type` | `VARCHAR(120)` | NOT NULL | 事件类型。 |
| `resource_type` | `VARCHAR(120)` | NOT NULL | 资源类型。 |
| `resource_id` | `VARCHAR(200)` | 无 | 资源稳定 ID。 |
| `action` | `VARCHAR(64)` | NOT NULL | 业务动作。 |
| `outcome` | `VARCHAR(24)` | NOT NULL CHECK (outcome IN ('success','denied','failed')) | 动作结果。 |
| `request_id` | `VARCHAR(100)` | 无 | 请求关联 ID。 |
| `trace_id` | `VARCHAR(100)` | 无 | 追踪 ID。 |
| `metadata` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 不含正文和密钥的脱敏元数据。 |
| `event_hash` | `CHAR(64)` | NOT NULL | 事件内容 hash。 |
| `occurred_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 发生时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_audit_events_tenant_updated (tenant_id, updated_at, audit_event_id)`
- `idx_platform_audit_resource (tenant_id, resource_type, resource_id, occurred_at)`
- `idx_platform_audit_actor (tenant_id, actor_user_id, occurred_at)`

## 设计说明

- 生产权限应使该表只允许追加，禁止普通应用账号 UPDATE/DELETE。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
