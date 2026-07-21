# `platform_connection_versions`

- 领域：数据接入
- 用途：不可变数据连接配置与加密凭证版本。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `connection_version_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `connection_id` | `UUID` | NOT NULL REFERENCES platform_data_connections(connection_id) ON DELETE CASCADE | 逻辑连接。 |
| `version_no` | `INTEGER` | NOT NULL CHECK (version_no > 0) | 递增版本。 |
| `endpoint_config` | `JSONB` | NOT NULL | 主机、库、参数等非密钥配置。 |
| `credential_ciphertext` | `BYTEA` | 无 | KMS envelope 密文。 |
| `key_version` | `VARCHAR(100)` | 无 | KMS key version。 |
| `config_hash` | `CHAR(64)` | NOT NULL | 规范化配置 hash。 |
| `validation_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (validation_status IN ('pending','testing','verified','failed','revoked')) | 验证状态。 |
| `validation_result` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 脱敏测试结果。 |
| `verified_at` | `TIMESTAMPTZ` | 无 | 验证成功时间。 |
| `published_at` | `TIMESTAMPTZ` | 无 | 发布生效时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_connection_versions_tenant_updated (tenant_id, updated_at, connection_version_id)`
- `UNIQUE uq_platform_connection_versions (connection_id, version_no)`

## 设计说明

- 已发布版本不可原地修改；凭证变更创建新版本。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
