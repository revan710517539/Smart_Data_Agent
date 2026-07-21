# `platform_analysis_feedback`

- 领域：智能分析
- 用途：用户对分析结果的评分、纠错和采用结果。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `feedback_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `analysis_task_id` | `UUID` | NOT NULL REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE CASCADE | 分析任务。 |
| `user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 反馈用户。 |
| `rating` | `INTEGER` | CHECK (rating BETWEEN 1 AND 5) | 评分。 |
| `feedback_type` | `VARCHAR(24)` | NOT NULL CHECK (feedback_type IN ('helpful','incorrect','incomplete','unsafe','adopted','other')) | 反馈类型。 |
| `comment` | `TEXT` | NOT NULL DEFAULT '' | 反馈说明。 |
| `correction` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 结构化纠错。 |
| `resolved_at` | `TIMESTAMPTZ` | 无 | 处理时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_feedback_tenant_updated (tenant_id, updated_at, feedback_id)`
- `idx_platform_analysis_feedback_task (analysis_task_id, created_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
