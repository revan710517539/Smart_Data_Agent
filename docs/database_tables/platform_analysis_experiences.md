# `platform_analysis_experiences`

- 领域：知识记忆
- 用途：可审核、可版本化、可在规划阶段召回的分析经验。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `experience_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `experience_code` | `VARCHAR(160)` | NOT NULL | 稳定经验编码。 |
| `title` | `VARCHAR(500)` | NOT NULL | 经验标题。 |
| `applicable_scenarios` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 适用场景。 |
| `trigger_conditions` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 召回条件。 |
| `analysis_method` | `JSONB` | NOT NULL | 分析方法。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','review','active','superseded','archived')) | 状态。 |
| `source_memory_id` | `UUID` | REFERENCES platform_memory_records(memory_id) ON DELETE SET NULL | 来源记忆。 |
| `success_count` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (success_count >= 0) | 成功应用次数。 |
| `failure_count` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (failure_count >= 0) | 失败次数。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_experiences_tenant_updated (tenant_id, updated_at, experience_id)`
- `UNIQUE uq_platform_analysis_experiences_code (tenant_id, experience_code)`
- `idx_platform_analysis_experiences_status (tenant_id, status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
