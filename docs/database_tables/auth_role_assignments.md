# `auth_role_assignments`

- 领域：身份权限
- 用途：用户在指定租户内的角色授权。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `assignment_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 授权 ID。 |
| `tenant_id` | `UUID` | REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 租户；为空仅允许表示全局超级管理员授权。 |
| `user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 用户。 |
| `role_id` | `UUID` | NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE | 角色。 |
| `granted_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 授权人。 |
| `granted_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 授权时间。 |
| `expires_at` | `TIMESTAMPTZ` | 无 | 临时授权到期时间。 |

## 索引

- `UNIQUE uq_auth_role_assignments (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), user_id, role_id)`
- `idx_auth_role_assignments_user (user_id, tenant_id)`

## 设计说明

- tenant_id 为空的授权只能指向全局超级管理员角色，由应用仓储强制校验。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
