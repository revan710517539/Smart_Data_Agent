# `platform_data_asset_items`

- 领域：数据治理
- 用途：兼容现有数据资产页面的版本化目录记录。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `asset_item_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `item_type` | `VARCHAR(40)` | NOT NULL | raw_table/topic/intent/experience 等兼容类型。 |
| `item_code` | `VARCHAR(200)` | NOT NULL | 稳定编码。 |
| `item_name` | `VARCHAR(300)` | NOT NULL | 名称。 |
| `canonical_ref_type` | `VARCHAR(40)` | 无 | 规范化实体类型。 |
| `canonical_ref_id` | `UUID` | 无 | 规范化实体 ID。 |
| `payload` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 迁移期间保留的低频扩展属性。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','active','rejected','archived')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_data_asset_items_tenant_updated (tenant_id, updated_at, asset_item_id)`
- `UNIQUE uq_platform_data_asset_items (tenant_id, item_type, item_code)`

## 设计说明

- 新功能优先写入规范化实体，本表只作页面兼容和迁移索引。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
