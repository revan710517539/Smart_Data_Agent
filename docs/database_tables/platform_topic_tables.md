# `platform_topic_tables`

- 领域：指标语义
- 用途：主题表逻辑身份、发布版本和新鲜度要求。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `topic_table_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `topic_code` | `VARCHAR(160)` | NOT NULL | 稳定主题表编码。 |
| `topic_name` | `VARCHAR(300)` | NOT NULL | 名称。 |
| `description` | `TEXT` | NOT NULL DEFAULT '' | 业务说明。 |
| `current_version_no` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (current_version_no >= 0) | 当前版本。 |
| `query_template` | `TEXT` | NOT NULL | 经解析校验的参数化查询。 |
| `query_hash` | `CHAR(64)` | NOT NULL | 规范化查询 hash。 |
| `freshness_sla_seconds` | `INTEGER` | CHECK (freshness_sla_seconds > 0) | 新鲜度要求。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','validating','published','degraded','archived')) | 状态。 |
| `validated_at` | `TIMESTAMPTZ` | 无 | 最近验证时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_topic_tables_tenant_updated (tenant_id, updated_at, topic_table_id)`
- `UNIQUE uq_platform_topic_tables_code (tenant_id, topic_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
