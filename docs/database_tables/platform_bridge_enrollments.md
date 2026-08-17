# `platform_bridge_enrollments`

- 领域：外部集成
- 用途：十分钟内有效、只能领取一次的 Bridge 设备授权事务。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `enrollment_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `enrollment_key` | `VARCHAR(160)` | NOT NULL UNIQUE | 不含密钥的稳定授权事务标识。 |
| `device_code_hash` | `CHAR(64)` | NOT NULL UNIQUE | 设备码 SHA-256；明文不落库。 |
| `user_code_hash` | `CHAR(64)` | NOT NULL UNIQUE | 用户确认码 SHA-256；明文不落库。 |
| `channel` | `VARCHAR(32)` | NOT NULL CHECK (channel IN ('workbuddy','codex','qwork')) | 发起授权的客户端渠道。 |
| `device_name` | `VARCHAR(160)` | NOT NULL | 客户端提供的设备名称。 |
| `verifier_hash` | `CHAR(64)` | NOT NULL | 客户端 verifier 的 SHA-256，用于防止设备码被截获后领取。 |
| `status` | `VARCHAR(16)` | NOT NULL CHECK (status IN ('pending','approved','consumed')) | 一次性授权事务状态。 |
| `tenant_id` | `UUID` | REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 批准时绑定的明确租户。 |
| `user_id` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 批准时绑定的用户。 |
| `approved_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 在浏览器中点击允许的用户。 |
| `expires_at_epoch` | `BIGINT` | NOT NULL | 授权事务过期的 Unix 秒值。 |
| `approved_at_epoch` | `BIGINT` | 无 | 批准时间。 |
| `consumed_at_epoch` | `BIGINT` | 无 | 令牌被客户端领取的时间；非空后禁止重放。 |
| `binding_id` | `UUID` | REFERENCES platform_bridge_bindings(binding_id) ON DELETE SET NULL | 领取后创建的设备绑定。 |
| `created_at_epoch` | `BIGINT` | NOT NULL | 创建时间的 Unix 秒值。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_bridge_enrollments_expiry (status, expires_at_epoch)`

## 设计说明

- 批准必须来自真实浏览器会话；轮询还需匹配客户端 verifier，且只能成功一次。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
