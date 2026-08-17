# `platform_subscriptions`

- 领域：自动化与通知
- 用途：用户对报告、指标、告警和市场事件的推送订阅。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `subscription_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `subscription_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定订阅标识。 |
| `subscriber_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 订阅用户。 |
| `subscription_name` | `VARCHAR(300)` | NOT NULL | 订阅名称。 |
| `event_types` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 订阅的领域事件类型。 |
| `channel_type` | `VARCHAR(24)` | NOT NULL CHECK (channel_type IN ('in_app','email','webhook','feishu','wecom','sms')) | 投递渠道。 |
| `channel_config_cipher` | `BYTEA` | NOT NULL | KMS/AEAD 加密后的渠道配置。 |
| `filter_expression` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 安全等值过滤表达式。 |
| `quiet_hours` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 静默时间配置。 |
| `subscription_type` | `VARCHAR(32)` | NOT NULL DEFAULT 'task' CHECK (subscription_type IN ('report','metric','alert','market','task')) | 订阅类型。 |
| `resource_id` | `UUID` | 无 | 订阅资源。 |
| `filter_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 过滤条件。 |
| `channels` | `JSONB` | NOT NULL | 邮件、飞书、企微、站内等渠道。 |
| `schedule_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 摘要频率/静默时段。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','disabled')) | 状态。 |
| `disabled_at` | `TIMESTAMPTZ` | 无 | 禁用时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_subscriptions_tenant_updated (tenant_id, updated_at, subscription_id)`
- `UNIQUE uq_platform_subscriptions_key (tenant_id, subscription_key)`
- `idx_platform_subscriptions_user (tenant_id, subscriber_user_id, status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
