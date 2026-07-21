# `platform_metric_versions`

- 领域：指标语义
- 用途：不可变指标口径、公式、分子分母、粒度和来源版本。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `metric_version_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `metric_id` | `UUID` | NOT NULL REFERENCES platform_metric_dictionary(metric_id) ON DELETE CASCADE | 指标。 |
| `version_no` | `INTEGER` | NOT NULL CHECK (version_no > 0) | 版本号。 |
| `definition` | `TEXT` | NOT NULL | 业务定义。 |
| `aggregation_type` | `VARCHAR(32)` | NOT NULL CHECK (aggregation_type IN ('sum','count','distinct_count','ratio','weighted_rate','avg','min','max','custom')) | 聚合语义。 |
| `value_expression` | `TEXT` | NOT NULL | 受控语义表达式。 |
| `numerator_expression` | `TEXT` | 无 | 率指标分子。 |
| `denominator_expression` | `TEXT` | 无 | 率指标分母。 |
| `multiplier` | `NUMERIC(20,8)` | NOT NULL DEFAULT 1 CHECK (multiplier > 0) | 率指标缩放倍数，例如百分比口径为 100。 |
| `default_grain` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 默认粒度。 |
| `source_dataset_id` | `UUID` | NOT NULL REFERENCES platform_datasets(dataset_id) ON DELETE RESTRICT | 来源数据集。 |
| `time_field_id` | `UUID` | REFERENCES platform_dataset_fields(field_id) ON DELETE RESTRICT | 时间字段。 |
| `allowed_dimensions` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 允许维度 ID。 |
| `effective_from` | `TIMESTAMPTZ` | NOT NULL | 生效起点。 |
| `effective_to` | `TIMESTAMPTZ` | 无 | 失效时间。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','published','superseded','rejected')) | 版本状态。 |
| `checksum` | `CHAR(64)` | NOT NULL | 口径 hash。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_metric_versions_tenant_updated (tenant_id, updated_at, metric_version_id)`
- `UNIQUE uq_platform_metric_versions (metric_id, version_no)`
- `idx_platform_metric_versions_effective (metric_id, status, effective_from)`

## 设计说明

- ratio/weighted_rate 必须同时提供 numerator_expression 和 denominator_expression，且聚合顺序为 SUM(分子)/SUM(分母)。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
