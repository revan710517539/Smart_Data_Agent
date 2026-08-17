# `platform_notification_deliveries`

- 领域：自动化与通知
- 用途：每条通知的真实渠道投递、回执和重试。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `delivery_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `delivery_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定投递标识。 |
| `subscription_id` | `UUID` | REFERENCES platform_subscriptions(subscription_id) ON DELETE SET NULL | 订阅。 |
| `outbox_event_id` | `UUID` | NOT NULL REFERENCES platform_outbox_events(outbox_event_id) ON DELETE RESTRICT | 来源领域事件。 |
| `recipient_user_id` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 接收用户。 |
| `channel` | `VARCHAR(24)` | NOT NULL CHECK (channel IN ('in_app','email','feishu','wecom','sms','webhook')) | 渠道。 |
| `template_code` | `VARCHAR(160)` | NOT NULL | 通知模板。 |
| `payload_ref` | `JSONB` | NOT NULL | 内容或对象引用，不复制敏感正文。 |
| `idempotency_key` | `VARCHAR(200)` | NOT NULL | 投递幂等键。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sending','accepted','delivered','failed','bounced','cancelled','suppressed','dead_letter')) | 真实状态。 |
| `provider_message_id` | `VARCHAR(300)` | 无 | 渠道消息 ID。 |
| `attempt_count` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (attempt_count >= 0) | 尝试次数。 |
| `next_attempt_at` | `TIMESTAMPTZ` | 无 | 下次尝试。 |
| `accepted_at` | `TIMESTAMPTZ` | 无 | 渠道受理时间。 |
| `delivered_at` | `TIMESTAMPTZ` | 无 | 送达时间。 |
| `error_code` | `VARCHAR(100)` | 无 | 错误码。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_notification_deliveries_tenant_updated (tenant_id, updated_at, delivery_id)`
- `UNIQUE uq_platform_notification_delivery_key (tenant_id, delivery_key)`
- `UNIQUE uq_platform_notification_deliveries (tenant_id, channel, idempotency_key)`
- `idx_platform_notification_deliveries_status (tenant_id, status, next_attempt_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
