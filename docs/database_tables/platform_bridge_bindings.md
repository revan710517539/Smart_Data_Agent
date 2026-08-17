# `platform_bridge_bindings`

- 领域：外部集成
- 用途：WorkBuddy、Codex、QWork 一次点击授权形成的可撤销 Bridge 设备绑定；只保存令牌哈希。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `binding_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `binding_key` | `VARCHAR(160)` | NOT NULL UNIQUE | 不含密钥的稳定绑定标识。 |
| `token_hash` | `CHAR(64)` | NOT NULL UNIQUE | Bridge bearer token 的 SHA-256；明文不落库。 |
| `channel` | `VARCHAR(32)` | NOT NULL CHECK (channel IN ('workbuddy','codex','qwork')) | 发起连接的客户端渠道。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 用户点击允许时明确选择的租户。 |
| `user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 完成浏览器授权的用户。 |
| `visibility` | `VARCHAR(16)` | NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','tenant')) | 报告默认可见范围。 |
| `display_label` | `VARCHAR(120)` | NOT NULL | 授权管理页展示名称。 |
| `device_name` | `VARCHAR(160)` | NOT NULL | 客户端提供的设备名称。 |
| `created_at_epoch` | `BIGINT` | NOT NULL | 创建时间的 Unix 秒值，供本地与 PostgreSQL 行为一致。 |
| `revoked_at_epoch` | `BIGINT` | 无 | 撤销时间；非空即拒绝后续访问。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_bridge_bindings_owner (tenant_id, user_id, channel, revoked_at_epoch)`

## 设计说明

- 令牌只在一次性领取响应中返回，数据库仅保存摘要。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
