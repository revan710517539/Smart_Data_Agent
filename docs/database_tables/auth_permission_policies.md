# `auth_permission_policies`

- 领域：身份权限
- 用途：角色的资源、动作、组织、行列和指标权限策略。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `policy_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 策略 ID。 |
| `role_id` | `UUID` | NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE | 所属角色。 |
| `tenant_id` | `UUID` | REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 策略租户范围。 |
| `resource_pattern` | `VARCHAR(300)` | NOT NULL | 资源匹配表达式。 |
| `action` | `VARCHAR(64)` | NOT NULL | read/create/update/delete/execute/publish 等动作。 |
| `effect` | `VARCHAR(16)` | NOT NULL DEFAULT 'allow' CHECK (effect IN ('allow','deny')) | 允许或拒绝。 |
| `org_scope` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 机构范围。 |
| `row_filter` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 可编译的行过滤表达式。 |
| `field_scope` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 字段范围。 |
| `metric_scope` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 指标范围。 |
| `priority` | `INTEGER` | NOT NULL DEFAULT 100 | 策略优先级。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |

## 索引

- `idx_auth_permission_policies_role (role_id, priority)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
