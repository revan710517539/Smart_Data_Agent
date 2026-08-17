# `platform_report_comment_replies`

- 领域：经营周报
- 用途：评论线程中的单条回复。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `reply_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `reply_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定回复标识。 |
| `client_request_id` | `VARCHAR(200)` | 无 | 客户端请求幂等键。 |
| `comment_id` | `UUID` | NOT NULL REFERENCES platform_report_comments(comment_id) ON DELETE CASCADE | 主评论。 |
| `author_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 真实作者。 |
| `reply_body` | `TEXT` | NOT NULL | 回复正文。 |
| `status` | `VARCHAR(16)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_report_comment_replies_tenant_updated (tenant_id, updated_at, reply_id)`
- `UNIQUE uq_platform_report_reply_key (tenant_id, reply_key)`
- `UNIQUE uq_platform_report_reply_request (tenant_id, comment_id, client_request_id)` WHERE client_request_id IS NOT NULL
- `idx_platform_report_comment_replies (comment_id, created_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
