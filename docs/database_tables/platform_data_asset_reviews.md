# `platform_data_asset_reviews`

- 领域：数据治理
- 用途：数据资产版本的追加式人工复核决策。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `asset_review_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `asset_version_id` | `UUID` | NOT NULL REFERENCES platform_data_asset_versions(asset_version_id) ON DELETE CASCADE | 被复核资产版本。 |
| `decision` | `VARCHAR(24)` | NOT NULL CHECK (decision IN ('approved','rejected','changes_required')) | 复核决策。 |
| `reviewer_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 复核人。 |
| `comments` | `TEXT` | NOT NULL DEFAULT '' | 复核意见。 |
| `decided_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 决策时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_data_asset_reviews_tenant_updated (tenant_id, updated_at, asset_review_id)`
- `idx_platform_data_asset_reviews_version (tenant_id, asset_version_id, decided_at)`

## 设计说明

- 复核记录只追加不覆盖；发布状态由服务端状态机推进。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
