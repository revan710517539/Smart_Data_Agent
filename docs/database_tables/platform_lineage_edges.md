# `platform_lineage_edges`

- 领域：数据治理
- 用途：字段、指标、主题表、分析、报告之间的有向血缘。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `lineage_edge_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `edge_key` | `VARCHAR(100)` | NOT NULL | API 使用的确定性边标识。 |
| `source_type` | `VARCHAR(40)` | NOT NULL | 来源实体类型。 |
| `source_id` | `VARCHAR(300)` | NOT NULL | 来源实体稳定 ID。 |
| `target_type` | `VARCHAR(40)` | NOT NULL | 目标实体类型。 |
| `target_id` | `VARCHAR(300)` | NOT NULL | 目标实体稳定 ID。 |
| `edge_type` | `VARCHAR(40)` | NOT NULL CHECK (edge_type IN ('reads','derives','aggregates','references','publishes','generates')) | 血缘关系。 |
| `expression` | `TEXT` | 无 | 转换表达式。 |
| `expression_hash` | `CHAR(64)` | 无 | 转换表达式或已执行查询摘要。 |
| `confidence` | `NUMERIC(7,4)` | NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1) | 血缘置信度。 |
| `metadata` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 执行版本、指标聚合等安全元数据。 |
| `valid_from` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 生效时间。 |
| `valid_to` | `TIMESTAMPTZ` | 无 | 失效时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_lineage_edges_tenant_updated (tenant_id, updated_at, lineage_edge_id)`
- `UNIQUE uq_platform_lineage_identity (tenant_id, source_type, source_id, target_type, target_id, edge_type)`
- `idx_platform_lineage_source (tenant_id, source_type, source_id)`
- `idx_platform_lineage_target (tenant_id, target_type, target_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
