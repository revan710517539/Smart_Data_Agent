# `platform_memory_records`

- 领域：知识记忆
- 用途：分析案例、用户习惯、业务经验等记忆候选和正式记录。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `memory_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `memory_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定记忆标识。 |
| `memory_type` | `VARCHAR(40)` | NOT NULL CHECK (memory_type IN ('analysis_case','behavior_habit','business_fact','preference','warning','other')) | 记忆类型。 |
| `subject_type` | `VARCHAR(24)` | NOT NULL CHECK (subject_type IN ('user','role','org','tenant')) | 作用主体。 |
| `subject_id` | `VARCHAR(300)` | NOT NULL | 作用主体稳定 ID。 |
| `title` | `VARCHAR(500)` | NOT NULL | 标题。 |
| `content` | `JSONB` | NOT NULL | 结构化记忆内容。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 去重 hash。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','review','active','superseded','expired','rejected')) | 生命周期。 |
| `confidence` | `NUMERIC(7,4)` | NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1) | 置信度。 |
| `weight` | `NUMERIC(9,6)` | NOT NULL DEFAULT 1 CHECK (weight >= 0) | 随时间衰减的权重。 |
| `valid_from` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 生效时间。 |
| `expires_at` | `TIMESTAMPTZ` | 无 | 过期时间。 |
| `supersedes_memory_id` | `UUID` | REFERENCES platform_memory_records(memory_id) ON DELETE SET NULL | 被替代记忆。 |
| `source_trace_id` | `VARCHAR(100)` | 无 | 产生该记忆的端到端 Trace。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_memory_records_tenant_updated (tenant_id, updated_at, memory_id)`
- `UNIQUE uq_platform_memory_key (tenant_id, memory_key)`
- `idx_platform_memory_recall (tenant_id, subject_type, subject_id, memory_type, status)`
- `idx_platform_memory_hash (tenant_id, content_hash)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
