# `platform_data_asset_versions`

- 领域：数据治理
- 用途：数据资产不可变版本、schema 校验结果与发布状态。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `asset_version_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `asset_item_id` | `UUID` | NOT NULL REFERENCES platform_data_asset_items(asset_item_id) ON DELETE CASCADE | 资产逻辑身份。 |
| `version_number` | `INTEGER` | NOT NULL CHECK (version_number >= 1) | 单资产递增版本号。 |
| `schema_version` | `VARCHAR(32)` | NOT NULL DEFAULT '1.0' | 资产 payload schema 版本。 |
| `payload` | `JSONB` | NOT NULL | 通过对应类型 schema 校验的不可变内容。 |
| `payload_hash` | `CHAR(64)` | NOT NULL | 规范化 payload SHA-256。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('draft','review','active','rejected','archived')) | 治理状态。 |
| `submitted_by` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 提交人。 |
| `submitted_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 提交时间。 |
| `reviewed_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 复核人。 |
| `reviewed_at` | `TIMESTAMPTZ` | 无 | 复核时间。 |
| `review_comment` | `TEXT` | NOT NULL DEFAULT '' | 复核意见。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_data_asset_versions_tenant_updated (tenant_id, updated_at, asset_version_id)`
- `UNIQUE uq_platform_data_asset_versions_number (tenant_id, asset_item_id, version_number)`
- `idx_platform_data_asset_versions_status (tenant_id, status, submitted_at)`

## 设计说明

- 同一资产只有一个 active 版本；提交人与批准人必须不同。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
