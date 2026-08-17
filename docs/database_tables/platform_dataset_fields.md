# `platform_dataset_fields`

- 领域：数据接入
- 用途：数据集字段、类型、语义、权限和敏感分类。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `field_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `dataset_id` | `UUID` | NOT NULL REFERENCES platform_datasets(dataset_id) ON DELETE CASCADE | 所属数据集。 |
| `field_code` | `VARCHAR(200)` | NOT NULL | 物理字段编码。 |
| `field_name` | `VARCHAR(300)` | NOT NULL | 业务名称。 |
| `ordinal_position` | `INTEGER` | NOT NULL CHECK (ordinal_position > 0) | 字段顺序。 |
| `physical_type` | `VARCHAR(120)` | NOT NULL | 物理数据类型。 |
| `semantic_type` | `VARCHAR(64)` | 无 | date/org/customer/amount/rate 等语义。 |
| `is_nullable` | `BOOLEAN` | NOT NULL DEFAULT true | 是否允许空。 |
| `is_dimension` | `BOOLEAN` | NOT NULL DEFAULT false | 是否可作维度。 |
| `is_measure` | `BOOLEAN` | NOT NULL DEFAULT false | 是否可作度量。 |
| `classification` | `VARCHAR(24)` | NOT NULL DEFAULT 'internal' | 字段敏感级别。 |
| `masking_policy` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 脱敏规则。 |
| `metadata` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 上游字段注释、长度、脱敏样例和元数据版本。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_dataset_fields_tenant_updated (tenant_id, updated_at, field_id)`
- `UNIQUE uq_platform_dataset_fields_code (dataset_id, field_code)`
- `idx_platform_dataset_fields_semantic (tenant_id, semantic_type)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
