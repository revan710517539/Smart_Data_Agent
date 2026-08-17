# `auth_roles`

- 领域：身份权限
- 用途：全局或租户级角色定义。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `role_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 角色 ID。 |
| `tenant_id` | `UUID` | REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 为空表示全局系统角色。 |
| `role_code` | `VARCHAR(100)` | NOT NULL | 稳定角色编码。 |
| `role_name` | `VARCHAR(200)` | NOT NULL | 角色名称。 |
| `role_level` | `INTEGER` | NOT NULL CHECK (role_level BETWEEN 0 AND 100) | 管理级别。 |
| `is_system` | `BOOLEAN` | NOT NULL DEFAULT false | 是否系统角色。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')) | 角色状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 更新时间。 |

## 索引

- `UNIQUE uq_auth_roles_scope_code (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), role_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
