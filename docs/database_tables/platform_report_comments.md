# `platform_report_comments`

- 领域：经营周报
- 用途：报告版本或块上的单条评论和解决状态。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `comment_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `comment_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定评论标识。 |
| `client_request_id` | `VARCHAR(200)` | 无 | 客户端请求幂等键。 |
| `report_id` | `UUID` | NOT NULL REFERENCES platform_reports(report_id) ON DELETE CASCADE | 逻辑报告；评论可跨再生成版本保持。 |
| `report_version_id` | `UUID` | REFERENCES platform_weekly_report_versions(report_version_id) ON DELETE CASCADE | 创建评论时的可选报告版本。 |
| `report_block_id` | `UUID` | REFERENCES platform_report_blocks(report_block_id) ON DELETE CASCADE | 可选报告块。 |
| `author_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 真实作者。 |
| `comment_body` | `TEXT` | NOT NULL | 评论正文。 |
| `anchor` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 选区、表格单元格或图表锚点。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','reopened','deleted')) | 评论状态。 |
| `resolved_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 解决人。 |
| `resolved_at` | `TIMESTAMPTZ` | 无 | 解决时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_report_comments_tenant_updated (tenant_id, updated_at, comment_id)`
- `UNIQUE uq_platform_report_comment_key (tenant_id, comment_key)`
- `UNIQUE uq_platform_report_comment_request (tenant_id, report_id, client_request_id)` WHERE client_request_id IS NOT NULL
- `idx_platform_report_comments_report (report_id, status, created_at)`
- `idx_platform_report_comments_version (report_version_id, status, created_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
