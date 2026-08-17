# `platform_user_tenant_memberships`

- 领域：身份权限
- 用途：用户与租户/组织的成员关系。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `membership_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 成员关系 ID。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 用户。 |
| `org_unit_id` | `UUID` | REFERENCES platform_org_units(org_unit_id) ON DELETE SET NULL | 主属机构。 |
| `membership_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (membership_status IN ('invited','active','suspended','left')) | 成员状态。 |
| `joined_at` | `TIMESTAMPTZ` | 无 | 加入时间。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |

## 索引

- `UNIQUE uq_platform_memberships_user_tenant (tenant_id, user_id)`
- `idx_platform_memberships_org (tenant_id, org_unit_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
