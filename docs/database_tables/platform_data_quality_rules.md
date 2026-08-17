# `platform_data_quality_rules`

- 领域：数据治理
- 用途：数据完整性、准确性、一致性和新鲜度规则。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `quality_rule_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `dataset_id` | `UUID` | NOT NULL REFERENCES platform_datasets(dataset_id) ON DELETE CASCADE | 数据集。 |
| `rule_code` | `VARCHAR(160)` | NOT NULL | 规则编码。 |
| `rule_name` | `VARCHAR(300)` | NOT NULL | 规则名称。 |
| `rule_type` | `VARCHAR(32)` | NOT NULL CHECK (rule_type IN ('freshness','completeness','validity','uniqueness','consistency','custom')) | 规则类型。 |
| `rule_expression` | `JSONB` | NOT NULL | 可执行规则表达式。 |
| `severity` | `VARCHAR(16)` | NOT NULL CHECK (severity IN ('info','warning','error','critical')) | 严重度。 |
| `blocking` | `BOOLEAN` | NOT NULL DEFAULT false | 失败是否阻断分析/发布。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','disabled')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_data_quality_rules_tenant_updated (tenant_id, updated_at, quality_rule_id)`
- `UNIQUE uq_platform_data_quality_rules_code (tenant_id, dataset_id, rule_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
