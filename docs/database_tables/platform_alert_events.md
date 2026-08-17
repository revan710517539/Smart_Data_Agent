# `platform_alert_events`

- 领域：自动化与通知
- 用途：告警规则命中、去重、确认、解决和证据。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `alert_event_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `alert_rule_id` | `UUID` | NOT NULL REFERENCES platform_alert_rules(alert_rule_id) ON DELETE RESTRICT | 告警规则。 |
| `dedupe_key` | `VARCHAR(300)` | NOT NULL | 冷却窗口内去重键。 |
| `severity` | `VARCHAR(16)` | NOT NULL | 严重度。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','suppressed')) | 处置状态。 |
| `resource_type` | `VARCHAR(40)` | NOT NULL | 问题资源类型。 |
| `resource_id` | `UUID` | 无 | 问题资源 ID。 |
| `summary` | `TEXT` | NOT NULL | 摘要。 |
| `evidence` | `JSONB` | NOT NULL | 触发值和证据引用。 |
| `first_seen_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 首次发现。 |
| `last_seen_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最近发现。 |
| `occurrence_count` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (occurrence_count > 0) | 发生次数。 |
| `acknowledged_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 确认人。 |
| `resolved_at` | `TIMESTAMPTZ` | 无 | 解决时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_alert_events_tenant_updated (tenant_id, updated_at, alert_event_id)`
- `idx_platform_alert_events_open (tenant_id, status, severity, last_seen_at)`
- `idx_platform_alert_events_dedupe (tenant_id, alert_rule_id, dedupe_key, last_seen_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
