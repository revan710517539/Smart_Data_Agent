# `auth_manageable_roles`

- 领域：身份权限
- 用途：定义某角色允许管理的下级角色。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `role_id` | `UUID` | NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE | 管理角色。 |
| `manageable_role_id` | `UUID` | NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE | 可管理角色。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |
| 表级约束 | — | `PRIMARY KEY (role_id, manageable_role_id), CHECK (role_id <> manageable_role_id)` | 表级约束。 |

## 索引

- 主键索引；暂无额外索引。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
