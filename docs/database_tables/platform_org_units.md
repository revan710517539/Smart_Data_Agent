# `platform_org_units`

- 领域：身份权限
- 用途：租户内组织机构树和数据权限范围。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `org_unit_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `parent_org_unit_id` | `UUID` | REFERENCES platform_org_units(org_unit_id) ON DELETE RESTRICT | 上级机构。 |
| `org_code` | `VARCHAR(100)` | NOT NULL | 租户内稳定机构编码。 |
| `org_name` | `VARCHAR(200)` | NOT NULL | 机构名称。 |
| `org_type` | `VARCHAR(32)` | NOT NULL DEFAULT 'department' | 机构类型。 |
| `path` | `TEXT` | NOT NULL | 物化层级路径。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')) | 生效状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_org_units_tenant_updated (tenant_id, updated_at, org_unit_id)`
- `UNIQUE uq_platform_org_units_code (tenant_id, org_code)`
- `idx_platform_org_units_parent (tenant_id, parent_org_unit_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
