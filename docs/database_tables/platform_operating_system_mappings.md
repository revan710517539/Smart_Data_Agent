# `platform_operating_system_mappings`

- 领域：数据接入
- 用途：毓数/智能运营系统与平台机构、客户、指标、主题表编码映射。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `mapping_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `source_system_id` | `UUID` | NOT NULL REFERENCES platform_source_systems(source_system_id) ON DELETE CASCADE | 毓数或智能运营来源。 |
| `mapping_type` | `VARCHAR(32)` | NOT NULL CHECK (mapping_type IN ('org','customer','metric','dataset','topic_table','product')) | 映射类型。 |
| `external_code` | `VARCHAR(300)` | NOT NULL | 外部编码。 |
| `platform_entity_type` | `VARCHAR(40)` | NOT NULL | 平台实体类型。 |
| `platform_entity_id` | `UUID` | NOT NULL | 平台实体 ID。 |
| `effective_from` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 生效时间。 |
| `effective_to` | `TIMESTAMPTZ` | 无 | 失效时间。 |
| `mapping_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (mapping_status IN ('pending','active','conflict','expired')) | 映射状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_operating_system_mappings_tenant_updated (tenant_id, updated_at, mapping_id)`
- `UNIQUE uq_platform_operating_mappings (tenant_id, source_system_id, mapping_type, external_code, effective_from)`
- `idx_platform_operating_mappings_target (tenant_id, platform_entity_type, platform_entity_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
