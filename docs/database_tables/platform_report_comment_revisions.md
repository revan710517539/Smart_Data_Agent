# `platform_report_comment_revisions`

- 领域：经营周报
- 用途：逻辑报告评论集合的单调修订号与快照校验和。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `comment_revision_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `report_id` | `UUID` | NOT NULL REFERENCES platform_reports(report_id) ON DELETE CASCADE | 逻辑报告。 |
| `revision_no` | `BIGINT` | NOT NULL CHECK (revision_no > 0) | 单调递增修订号。 |
| `snapshot_hash` | `CHAR(64)` | NOT NULL | 当前评论与回复集合 hash。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_report_comment_revisions_tenant_updated (tenant_id, updated_at, comment_revision_id)`
- `UNIQUE uq_platform_report_comment_revision (report_id, revision_no)`
- `idx_platform_report_comment_revision_latest (report_id, revision_no)`

## 设计说明

- 评论正文保存在规范化评论与回复表；本表只保存并发控制修订和防篡改 hash。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
