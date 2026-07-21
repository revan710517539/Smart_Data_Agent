# `platform_market_monitoring_rules`

- 领域：市场监控
- 用途：对市场实体和指标的阈值、变化和事件监控规则。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `market_rule_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `market_rule_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定规则标识。 |
| `rule_name` | `VARCHAR(300)` | NOT NULL | 规则名称。 |
| `entity_selector` | `JSONB` | NOT NULL | 实体选择条件。 |
| `metric_code` | `VARCHAR(160)` | NOT NULL | 监控指标。 |
| `condition_expression` | `JSONB` | NOT NULL | 阈值/变化/异常条件。 |
| `severity` | `VARCHAR(16)` | NOT NULL CHECK (severity IN ('info','warning','error','critical')) | 严重度。 |
| `cooldown_seconds` | `INTEGER` | NOT NULL DEFAULT 3600 CHECK (cooldown_seconds >= 0) | 告警冷却。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','paused','disabled')) | 状态。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 规则所有者。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_market_monitoring_rules_tenant_updated (tenant_id, updated_at, market_rule_id)`
- `UNIQUE uq_platform_market_rule_key (tenant_id, market_rule_key)`
- `idx_platform_market_monitoring_rules_status (tenant_id, status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
