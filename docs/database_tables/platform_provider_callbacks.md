# `platform_provider_callbacks`

- 领域：自动化与通知
- 用途：邮件、飞书、企微等渠道回调的幂等原始事件摘要。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `callback_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `callback_key` | `VARCHAR(160)` | NOT NULL | 稳定回调记录标识。 |
| `provider` | `VARCHAR(80)` | NOT NULL | 渠道提供商。 |
| `provider_event_id` | `VARCHAR(300)` | NOT NULL | 提供商事件 ID。 |
| `provider_message_id` | `VARCHAR(300)` | 无 | 提供商消息 ID。 |
| `event_type` | `VARCHAR(100)` | NOT NULL | delivered/bounced/read 等。 |
| `signature_valid` | `BOOLEAN` | NOT NULL | 签名是否有效。 |
| `payload_hash` | `CHAR(64)` | NOT NULL | 原始负载 hash。 |
| `safe_payload` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 脱敏字段。 |
| `processed_at` | `TIMESTAMPTZ` | 无 | 处理时间。 |
| `processing_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending','processed','ignored','failed')) | 处理状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_provider_callbacks_tenant_updated (tenant_id, updated_at, callback_id)`
- `UNIQUE uq_platform_provider_callbacks (provider, provider_event_id)`
- `idx_platform_provider_callbacks_pending (processing_status, created_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
