# `platform_topic_table_fields`

- 领域：指标语义
- 用途：主题表输出字段及其来源映射。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `topic_field_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `topic_table_id` | `UUID` | NOT NULL REFERENCES platform_topic_tables(topic_table_id) ON DELETE CASCADE | 主题表。 |
| `field_code` | `VARCHAR(200)` | NOT NULL | 输出字段编码。 |
| `field_name` | `VARCHAR(300)` | NOT NULL | 业务名称。 |
| `data_type` | `VARCHAR(120)` | NOT NULL | 输出类型。 |
| `ordinal_position` | `INTEGER` | NOT NULL CHECK (ordinal_position > 0) | 字段顺序。 |
| `source_expression` | `TEXT` | NOT NULL | 受控来源表达式。 |
| `is_dimension` | `BOOLEAN` | NOT NULL DEFAULT false | 是否维度。 |
| `is_measure` | `BOOLEAN` | NOT NULL DEFAULT false | 是否度量。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_topic_table_fields_tenant_updated (tenant_id, updated_at, topic_field_id)`
- `UNIQUE uq_platform_topic_table_fields (topic_table_id, field_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
