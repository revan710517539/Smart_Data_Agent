# `platform_tenants`

- 领域：身份权限
- 用途：租户/机构隔离根实体。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `tenant_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_code` | `VARCHAR(64)` | NOT NULL UNIQUE | 稳定租户编码。 |
| `tenant_name` | `VARCHAR(200)` | NOT NULL | 租户名称。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed')) | 租户状态。 |
| `timezone` | `VARCHAR(64)` | NOT NULL DEFAULT 'Asia/Shanghai' | 业务时区。 |
| `settings` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 低频扩展设置。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_tenants_status (status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
