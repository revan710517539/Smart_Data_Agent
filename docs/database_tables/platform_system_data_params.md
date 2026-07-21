# `platform_system_data_params`

- 领域：基础设施
- 用途：可审计且真正进入运行时的租户系统参数。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `system_param_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `param_key` | `VARCHAR(200)` | NOT NULL | 参数键。 |
| `value_type` | `VARCHAR(16)` | NOT NULL CHECK (value_type IN ('string','number','boolean','duration','json')) | 值类型。 |
| `param_value` | `JSONB` | NOT NULL | 类型化参数值。 |
| `is_sensitive` | `BOOLEAN` | NOT NULL DEFAULT false | 是否敏感；敏感值应保存凭证引用。 |
| `effective_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 生效时间。 |
| `description` | `TEXT` | NOT NULL DEFAULT '' | 参数说明。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_system_data_params_tenant_updated (tenant_id, updated_at, system_param_id)`
- `UNIQUE uq_platform_system_data_params (tenant_id, param_key)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
