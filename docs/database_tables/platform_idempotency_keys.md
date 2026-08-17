# `platform_idempotency_keys`

- 领域：基础设施
- 用途：写请求幂等、重复提交和结果重放。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `idempotency_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `idempotency_key` | `VARCHAR(200)` | NOT NULL | 客户端或服务端业务幂等键。 |
| `request_scope` | `VARCHAR(200)` | NOT NULL | 路由或业务动作。 |
| `request_hash` | `CHAR(64)` | NOT NULL | 请求摘要。 |
| `response_status` | `INTEGER` | 无 | 已完成响应码。 |
| `response_body` | `JSONB` | 无 | 可安全重放的响应。 |
| `state` | `VARCHAR(16)` | NOT NULL DEFAULT 'processing' CHECK (state IN ('processing','completed','failed')) | 处理状态。 |
| `expires_at` | `TIMESTAMPTZ` | NOT NULL | 幂等记录到期时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_idempotency_keys_tenant_updated (tenant_id, updated_at, idempotency_id)`
- `UNIQUE uq_platform_idempotency_scope (tenant_id, request_scope, idempotency_key)`
- `idx_platform_idempotency_expiry (expires_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
