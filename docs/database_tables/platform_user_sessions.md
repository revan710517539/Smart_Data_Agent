# `platform_user_sessions`

- 领域：身份权限
- 用途：可撤销的用户设备会话和刷新令牌摘要。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `session_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 登录用户。 |
| `device_session_key` | `VARCHAR(100)` | NOT NULL UNIQUE | 暴露给访问令牌的不可猜测设备会话标识。 |
| `access_jti` | `VARCHAR(100)` | NOT NULL UNIQUE | 当前访问令牌唯一标识；刷新时原子轮换。 |
| `refresh_token_hash` | `CHAR(64)` | NOT NULL UNIQUE | 刷新令牌摘要。 |
| `tenant_codes` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 该会话获准访问的稳定租户编码快照。 |
| `device_name` | `VARCHAR(200)` | 无 | 设备名称。 |
| `user_agent_hash` | `CHAR(64)` | 无 | User-Agent 摘要，不保存原始标识。 |
| `ip_hash` | `CHAR(64)` | 无 | 脱敏 IP 摘要。 |
| `access_expires_at` | `TIMESTAMPTZ` | NOT NULL | 当前访问令牌到期时间。 |
| `idle_expires_at` | `TIMESTAMPTZ` | NOT NULL | 会话空闲到期时间。 |
| `expires_at` | `TIMESTAMPTZ` | NOT NULL | 会话绝对到期时间。 |
| `idle_timeout_seconds` | `INTEGER` | NOT NULL CHECK (idle_timeout_seconds >= 60) | 空闲超时策略秒数。 |
| `last_seen_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后活动时间。 |
| `revoked_at` | `TIMESTAMPTZ` | 无 | 撤销时间。 |
| `revoke_reason` | `VARCHAR(200)` | NOT NULL DEFAULT '' | 撤销原因稳定码。 |
| `rotated_at` | `TIMESTAMPTZ` | 无 | 最近一次刷新令牌轮换时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_user_sessions_tenant_updated (tenant_id, updated_at, session_id)`
- `idx_platform_user_sessions_user (tenant_id, user_id, expires_at)`
- `idx_platform_user_sessions_access (access_jti, revoked_at)`

## 设计说明

- 只保存刷新令牌哈希；访问令牌和刷新令牌明文永不落库。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
