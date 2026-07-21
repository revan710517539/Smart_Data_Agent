# `platform_source_systems`

- 领域：数据接入
- 用途：外部来源系统主数据，包括市场平台和毓数/智能运营系统。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `source_system_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `source_system_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定来源系统标识。 |
| `source_code` | `VARCHAR(160)` | NOT NULL | 稳定来源编码。 |
| `source_name` | `VARCHAR(300)` | NOT NULL | 来源名称。 |
| `source_category` | `VARCHAR(32)` | NOT NULL CHECK (source_category IN ('internal_operation','yushu','smart_operation','market','warehouse','file_exchange','other')) | 来源类别。 |
| `owner_org_unit_id` | `UUID` | REFERENCES platform_org_units(org_unit_id) ON DELETE SET NULL | 责任机构。 |
| `license_metadata` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 市场数据许可、用途和到期。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','degraded','disabled','retired')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_source_systems_tenant_updated (tenant_id, updated_at, source_system_id)`
- `UNIQUE uq_platform_source_systems_key (tenant_id, source_system_key)`
- `UNIQUE uq_platform_source_systems_code (tenant_id, source_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
