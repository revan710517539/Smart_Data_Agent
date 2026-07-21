# `platform_metric_dictionary`

- 领域：指标语义
- 用途：指标逻辑身份和当前发布版本。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `metric_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `metric_key` | `VARCHAR(160)` | NOT NULL | 页面和外部系统使用的稳定指标 ID。 |
| `metric_code` | `VARCHAR(160)` | NOT NULL | 稳定指标编码。 |
| `metric_name` | `VARCHAR(300)` | NOT NULL | 指标名称。 |
| `metric_domain` | `VARCHAR(120)` | NOT NULL | 指标域。 |
| `unit` | `VARCHAR(64)` | NOT NULL DEFAULT 'count' | 单位。 |
| `current_version_no` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (current_version_no >= 0) | 当前发布版本。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','published','deprecated','disabled')) | 生命周期。 |
| `owner_user_id` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 指标负责人。 |
| `metadata` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 描述、应用场景、可见范围等非执行元数据。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_metric_dictionary_tenant_updated (tenant_id, updated_at, metric_id)`
- `UNIQUE uq_platform_metric_dictionary_key (tenant_id, metric_key)`
- `UNIQUE uq_platform_metric_dictionary_code (tenant_id, metric_code)`
- `idx_platform_metric_dictionary_domain (tenant_id, metric_domain, status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
