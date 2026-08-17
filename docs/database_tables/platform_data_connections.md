# `platform_data_connections`

- 领域：数据接入
- 用途：租户数据连接的逻辑身份和当前验证版本。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `connection_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `source_system_id` | `UUID` | 无 | 所属来源系统；在来源系统表建立后补充外键。 |
| `connection_code` | `VARCHAR(160)` | NOT NULL | 稳定连接编码。 |
| `connection_name` | `VARCHAR(200)` | NOT NULL | 连接名称。 |
| `source_type` | `VARCHAR(64)` | NOT NULL | postgresql/doris/hive/qbi/api/csv/object_storage 等。 |
| `current_version_no` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (current_version_no >= 0) | 当前已发布连接版本。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','testing','verified','degraded','disabled')) | 真实连接状态。 |
| `last_verified_at` | `TIMESTAMPTZ` | 无 | 最后验证成功时间。 |
| `health_summary` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 不含凭证的健康摘要。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_data_connections_tenant_updated (tenant_id, updated_at, connection_id)`
- `UNIQUE uq_platform_data_connections_code (tenant_id, connection_code)`
- `idx_platform_data_connections_status (tenant_id, status)`

## 延后建立的外键

- `fk_platform_data_connections_source`：`source_system_id` → `platform_source_systems(source_system_id)`，删除策略 `SET NULL`。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
