# `platform_market_monitoring_events`

- 领域：市场监控
- 用途：市场规则命中事件、证据和处置状态。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `market_event_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `market_event_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定事件标识。 |
| `market_rule_id` | `UUID` | NOT NULL REFERENCES platform_market_monitoring_rules(market_rule_id) ON DELETE RESTRICT | 命中规则。 |
| `market_entity_id` | `UUID` | NOT NULL REFERENCES platform_market_entities(market_entity_id) ON DELETE RESTRICT | 相关实体。 |
| `observation_id` | `UUID` | REFERENCES platform_market_observations(market_observation_id) ON DELETE SET NULL | 触发观测。 |
| `severity` | `VARCHAR(16)` | NOT NULL | 事件严重度。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','suppressed')) | 处置状态。 |
| `event_summary` | `TEXT` | NOT NULL | 有证据的摘要。 |
| `evidence` | `JSONB` | NOT NULL | 规则和值证据。 |
| `detected_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 发现时间。 |
| `resolved_at` | `TIMESTAMPTZ` | 无 | 解决时间。 |
| `acknowledged_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 确认或处置人。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_market_monitoring_events_tenant_updated (tenant_id, updated_at, market_event_id)`
- `UNIQUE uq_platform_market_event_key (tenant_id, market_event_key)`
- `UNIQUE uq_platform_market_event_observation (market_rule_id, observation_id)` WHERE observation_id IS NOT NULL
- `idx_platform_market_events_open (tenant_id, status, severity, detected_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
