# `platform_email_messages`

- 领域：自动化与通知
- 用途：邮件主题、正文产物、收件人和发送回执。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `email_message_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `email_message_key` | `VARCHAR(160)` | NOT NULL | 稳定邮件记录标识。 |
| `delivery_id` | `UUID` | NOT NULL REFERENCES platform_notification_deliveries(delivery_id) ON DELETE CASCADE | 通知投递。 |
| `subject` | `VARCHAR(998)` | NOT NULL | 邮件主题。 |
| `body_artifact_id` | `UUID` | NOT NULL REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 邮件正文产物。 |
| `from_address` | `VARCHAR(320)` | NOT NULL | 发件地址。 |
| `to_addresses` | `JSONB` | NOT NULL | 收件地址列表。 |
| `cc_addresses` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 抄送。 |
| `attachment_ids` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 附件 ID。 |
| `provider_response` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 脱敏渠道响应。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_email_messages_tenant_updated (tenant_id, updated_at, email_message_id)`
- `UNIQUE uq_platform_email_messages_delivery (delivery_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
