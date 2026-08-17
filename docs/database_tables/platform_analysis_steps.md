# `platform_analysis_steps`

- 领域：智能分析
- 用途：分析计划中每个 Agent/Skill/Review 步骤的可恢复执行记录。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `analysis_step_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `analysis_task_id` | `UUID` | NOT NULL REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE CASCADE | 分析任务。 |
| `step_code` | `VARCHAR(120)` | NOT NULL | 步骤编码。 |
| `sequence_no` | `INTEGER` | NOT NULL CHECK (sequence_no >= 0) | 顺序。 |
| `step_type` | `VARCHAR(32)` | NOT NULL CHECK (step_type IN ('agent','skill','query','python','llm','review','publish')) | 步骤类型。 |
| `agent_id` | `UUID` | REFERENCES platform_agents(agent_id) ON DELETE RESTRICT | 执行 Agent。 |
| `skill_id` | `UUID` | REFERENCES platform_skills(skill_id) ON DELETE RESTRICT | 执行 Skill。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('pending','queued','running','succeeded','failed','skipped','cancelled')) | 状态。 |
| `input_refs` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 输入证据 ID。 |
| `output_refs` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 输出产物 ID。 |
| `attempt_no` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (attempt_no > 0) | 尝试次数。 |
| `started_at` | `TIMESTAMPTZ` | 无 | 开始时间。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `error_code` | `VARCHAR(100)` | 无 | 错误码。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_steps_tenant_updated (tenant_id, updated_at, analysis_step_id)`
- `UNIQUE uq_platform_analysis_steps (analysis_task_id, step_code, attempt_no)`
- `idx_platform_analysis_steps_order (analysis_task_id, sequence_no)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
