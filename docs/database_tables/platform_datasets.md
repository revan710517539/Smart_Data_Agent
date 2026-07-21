# `platform_datasets`

- 领域：数据接入
- 用途：真实数据集、库表、API 资源或文件集合的元数据。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `dataset_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `connection_id` | `UUID` | NOT NULL REFERENCES platform_data_connections(connection_id) ON DELETE RESTRICT | 数据连接。 |
| `dataset_code` | `VARCHAR(200)` | NOT NULL | 租户内稳定编码。 |
| `dataset_name` | `VARCHAR(300)` | NOT NULL | 名称。 |
| `physical_locator` | `JSONB` | NOT NULL | schema/table、API path 或对象前缀。 |
| `dataset_type` | `VARCHAR(32)` | NOT NULL CHECK (dataset_type IN ('table','view','api','file_collection','stream','semantic')) | 类型。 |
| `data_classification` | `VARCHAR(24)` | NOT NULL DEFAULT 'internal' CHECK (data_classification IN ('public','internal','confidential','restricted')) | 敏感级别。 |
| `freshness_sla_seconds` | `INTEGER` | CHECK (freshness_sla_seconds > 0) | 新鲜度 SLA。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','degraded','deprecated','disabled')) | 生命周期。 |
| `schema_hash` | `CHAR(64)` | 无 | 字段 schema hash。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_datasets_tenant_updated (tenant_id, updated_at, dataset_id)`
- `UNIQUE uq_platform_datasets_code (tenant_id, dataset_code)`
- `idx_platform_datasets_connection (connection_id, status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
