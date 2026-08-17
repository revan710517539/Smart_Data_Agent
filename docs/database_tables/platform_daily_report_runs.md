# `platform_daily_report_runs`

- 领域：自动化与通知
- 用途：从可发布报告证据生成的不可变日报邮件产物及投递汇总。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `daily_report_run_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `daily_report_run_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定日报运行标识。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 生成和发送所有者。 |
| `report_date` | `DATE` | NOT NULL | 日报业务日期。 |
| `source_report_version_id` | `UUID` | NOT NULL REFERENCES platform_weekly_report_versions(report_version_id) ON DELETE RESTRICT | 唯一来源报告版本。 |
| `subject` | `VARCHAR(998)` | NOT NULL | 经换行清理后的邮件主题。 |
| `body_artifact_id` | `UUID` | NOT NULL REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 不可变 HTML 正文产物。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 正文内容 hash。 |
| `evidence_summary` | `JSONB` | NOT NULL | 来源版本、块、快照和发布门禁摘要。 |
| `preview_text` | `TEXT` | NOT NULL DEFAULT '' | 脱敏纯文本预览。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('generated','queued','sending','delivered','failed')) | 真实生成和投递汇总状态。 |
| `outbox_event_id` | `UUID` | REFERENCES platform_outbox_events(outbox_event_id) ON DELETE RESTRICT | 幂等发送事件。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_daily_report_runs_tenant_updated (tenant_id, updated_at, daily_report_run_id)`
- `UNIQUE uq_platform_daily_report_run_key (tenant_id, daily_report_run_key)`
- `UNIQUE uq_platform_daily_report_runs_content (tenant_id, owner_user_id, report_date, content_hash)`
- `idx_platform_daily_report_runs_status (tenant_id, status, report_date)`

## 设计说明

- 只有 evidence_summary.publishable=true 的来源版本可以生成；发送只发布 artifact 引用，不复制正文。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
