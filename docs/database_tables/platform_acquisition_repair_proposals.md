# `platform_acquisition_repair_proposals`

- 领域：数据接入
- 用途：采集失败后的受控诊断与脚本修复候选，必须评审后才能形成新版本。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `repair_proposal_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `repair_proposal_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定修复提案标识。 |
| `acquisition_run_id` | `UUID` | NOT NULL REFERENCES platform_acquisition_job_runs(acquisition_run_id) ON DELETE CASCADE | 失败运行。 |
| `failed_script_version_id` | `UUID` | NOT NULL REFERENCES platform_acquisition_script_versions(script_version_id) ON DELETE RESTRICT | 发生失败的不可变脚本版本。 |
| `diagnosis` | `JSONB` | NOT NULL | 脱敏错误诊断、证据和建议动作。 |
| `generation_method` | `VARCHAR(24)` | NOT NULL CHECK (generation_method IN ('deterministic','llm','manual')) | 候选生成方式。 |
| `candidate_source_code` | `TEXT` | 无 | 候选代码；仅作为提案，不可直接执行。 |
| `candidate_hash` | `CHAR(64)` | 无 | 候选代码 hash。 |
| `model_call_id` | `UUID` | REFERENCES platform_model_calls(model_call_id) ON DELETE SET NULL | 如由 LLM 生成，对应受治理模型调用。 |
| `review_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','approved','rejected','applied','superseded')) | 评审与应用状态。 |
| `reviewed_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 人工评审人。 |
| `reviewed_at` | `TIMESTAMPTZ` | 无 | 评审时间。 |
| `applied_script_version_id` | `UUID` | REFERENCES platform_acquisition_script_versions(script_version_id) ON DELETE SET NULL | 审批后另行创建的新脚本版本。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_acquisition_repair_proposals_tenant_updated (tenant_id, updated_at, repair_proposal_id)`
- `UNIQUE uq_platform_repair_proposal_key (tenant_id, repair_proposal_key)`
- `idx_platform_acquisition_repairs_run (tenant_id, acquisition_run_id, created_at)`
- `idx_platform_acquisition_repairs_review (tenant_id, review_status, created_at)`

## 设计说明

- 任何自动诊断或 LLM 输出都只能停留在 pending；应用时创建新 script_version，不修改 failed_script_version_id。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
