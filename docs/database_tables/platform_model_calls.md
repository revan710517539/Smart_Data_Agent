# `platform_model_calls`

- 领域：Agent与模型
- 用途：模型调用的输入证据引用、用量、成本和结果状态。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `model_call_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `model_call_key` | `VARCHAR(300)` | NOT NULL UNIQUE | API 与审计使用的稳定模型调用标识。 |
| `analysis_task_id` | `UUID` | 无 | 关联分析任务。 |
| `subject_type` | `VARCHAR(64)` | NOT NULL DEFAULT 'analysis_task' | 调用所属业务对象类型。 |
| `subject_id` | `VARCHAR(300)` | NOT NULL | 调用所属分析、修复、报告或任务对象稳定 ID。 |
| `revision` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (revision > 0) | 同一业务对象内的调用序号。 |
| `model_integration_id` | `UUID` | NOT NULL REFERENCES platform_model_integrations(model_integration_id) ON DELETE RESTRICT | 实际模型。 |
| `provider_model_name` | `VARCHAR(200)` | NOT NULL DEFAULT '' | 本次调用实际命中的提供商模型名快照。 |
| `prompt_template_id` | `UUID` | REFERENCES platform_prompt_templates(prompt_template_id) ON DELETE SET NULL | Prompt 版本。 |
| `request_hash` | `CHAR(64)` | NOT NULL | 脱敏请求 hash。 |
| `response_hash` | `CHAR(64)` | 无 | 响应 hash。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('queued','running','succeeded','degraded','failed','cancelled')) | 调用状态。 |
| `input_tokens` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (input_tokens >= 0) | 输入 token。 |
| `output_tokens` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (output_tokens >= 0) | 输出 token。 |
| `usage_source` | `VARCHAR(24)` | NOT NULL DEFAULT 'estimated' CHECK (usage_source IN ('provider','estimated')) | Token 用量来自提供商还是估算。 |
| `cost_amount` | `NUMERIC(18,6)` | NOT NULL DEFAULT 0 CHECK (cost_amount >= 0) | 成本。 |
| `latency_ms` | `INTEGER` | CHECK (latency_ms >= 0) | 耗时。 |
| `error_code` | `VARCHAR(100)` | 无 | 稳定错误码。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_model_calls_tenant_updated (tenant_id, updated_at, model_call_id)`
- `idx_platform_model_calls_task (tenant_id, analysis_task_id, created_at)`
- `UNIQUE uq_platform_model_calls_subject (tenant_id, subject_type, subject_id, revision)`

## 延后建立的外键

- `fk_platform_model_calls_analysis_task`：`analysis_task_id` → `platform_analysis_tasks(analysis_task_id)`，删除策略 `SET NULL`。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
