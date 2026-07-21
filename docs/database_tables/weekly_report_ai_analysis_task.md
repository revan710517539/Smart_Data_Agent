# `weekly_report_ai_analysis_task`

- 领域：经营周报
- 用途：兼容现有周报 AI 分析任务并关联正式报告/分析事实链。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `weekly_ai_task_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `weekly_ai_task_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定周报分析任务标识。 |
| `report_version_id` | `UUID` | REFERENCES platform_weekly_report_versions(report_version_id) ON DELETE CASCADE | 报告版本。 |
| `analysis_task_id` | `UUID` | REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE RESTRICT | 正式分析任务。 |
| `task_type` | `VARCHAR(40)` | NOT NULL | 周报 AI 任务类型。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('queued','running','review_required','succeeded','failed','cancelled')) | 状态。 |
| `input_hash` | `CHAR(64)` | NOT NULL | 输入版本 hash。 |
| `output_artifact_id` | `UUID` | REFERENCES platform_analysis_artifacts(analysis_artifact_id) ON DELETE RESTRICT | 输出产物。 |
| `started_at` | `TIMESTAMPTZ` | 无 | 开始时间。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `error_code` | `VARCHAR(100)` | 无 | 错误码。 |
| `input_snapshot` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 周报版本的受控输入快照。 |
| `debate_result` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 多角色分析中间结果。 |
| `final_result` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 最终分析结果。 |
| `error_summary` | `TEXT` | 无 | 脱敏错误摘要。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_weekly_report_ai_analysis_task_tenant_updated (tenant_id, updated_at, weekly_ai_task_id)`
- `UNIQUE uq_weekly_report_ai_task_key (tenant_id, weekly_ai_task_key)`
- `UNIQUE uq_weekly_report_ai_task_version (report_version_id)`
- `idx_weekly_report_ai_analysis_task_version (report_version_id, status, created_at)`

## 设计说明

- 该兼容表不再保存整份重复 payload，后续事实以 analysis_task_id 为准。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
