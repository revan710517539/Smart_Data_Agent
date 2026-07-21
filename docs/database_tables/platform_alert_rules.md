# `platform_alert_rules`

- 领域：自动化与通知
- 用途：数据、任务、指标和系统异常的统一告警规则。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `alert_rule_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `rule_code` | `VARCHAR(160)` | NOT NULL | 稳定规则编码。 |
| `rule_name` | `VARCHAR(300)` | NOT NULL | 规则名称。 |
| `rule_domain` | `VARCHAR(32)` | NOT NULL CHECK (rule_domain IN ('data_quality','freshness','metric','job','system','security','market')) | 规则域。 |
| `condition_expression` | `JSONB` | NOT NULL | 可执行条件。 |
| `severity` | `VARCHAR(16)` | NOT NULL CHECK (severity IN ('info','warning','error','critical')) | 严重度。 |
| `cooldown_seconds` | `INTEGER` | NOT NULL DEFAULT 300 CHECK (cooldown_seconds >= 0) | 冷却时间。 |
| `notification_policy` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 通知升级策略。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','paused','disabled')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_alert_rules_tenant_updated (tenant_id, updated_at, alert_rule_id)`
- `UNIQUE uq_platform_alert_rules_code (tenant_id, rule_code)`
- `idx_platform_alert_rules_status (tenant_id, status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
