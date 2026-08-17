# `platform_market_entities`

- 领域：市场监控
- 用途：竞品、机构、产品、行业等市场实体主数据。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `market_entity_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `market_entity_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定市场实体标识。 |
| `entity_type` | `VARCHAR(40)` | NOT NULL CHECK (entity_type IN ('institution','product','industry','region','index','event_subject')) | 实体类型。 |
| `entity_code` | `VARCHAR(160)` | NOT NULL | 稳定编码。 |
| `entity_name` | `VARCHAR(300)` | NOT NULL | 名称。 |
| `aliases` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 别名。 |
| `attributes` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 低频扩展属性。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','merged','inactive')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_market_entities_tenant_updated (tenant_id, updated_at, market_entity_id)`
- `UNIQUE uq_platform_market_entity_key (tenant_id, market_entity_key)`
- `UNIQUE uq_platform_market_entities_code (tenant_id, entity_type, entity_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
