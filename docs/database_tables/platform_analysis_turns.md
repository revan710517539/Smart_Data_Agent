# `platform_analysis_turns`

- 领域：智能分析
- 用途：线程内不可变问题、回答、规划和证据轮次。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `turn_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `thread_id` | `UUID` | NOT NULL REFERENCES platform_analysis_threads(thread_id) ON DELETE CASCADE | 所属线程。 |
| `turn_no` | `INTEGER` | NOT NULL CHECK (turn_no > 0) | 线程内单调轮次。 |
| `actor_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 发起用户。 |
| `question` | `TEXT` | NOT NULL | 本轮问题。 |
| `answer` | `TEXT` | NOT NULL DEFAULT '' | 本轮结论。 |
| `intent` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 结构化意图及置信度。 |
| `execution_plan` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 持久化 DAG 摘要。 |
| `artifact_refs` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 产物引用列表。 |
| `evidence_refs` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 证据引用列表。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('clarification','queued','running','completed','partial','failed','cancelled')) | 轮次执行状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_turns_tenant_updated (tenant_id, updated_at, turn_id)`
- `UNIQUE uq_platform_analysis_turns_no (thread_id, turn_no)`
- `idx_platform_analysis_turns_thread (tenant_id, thread_id, created_at)`

## 设计说明

- 已完成轮次不可覆盖；重跑和合并必须创建新轮次。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
