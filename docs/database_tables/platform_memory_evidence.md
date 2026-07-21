# `platform_memory_evidence`

- 领域：知识记忆
- 用途：记忆记录的分析、报告、任务或知识证据。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `memory_evidence_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `memory_id` | `UUID` | NOT NULL REFERENCES platform_memory_records(memory_id) ON DELETE CASCADE | 记忆。 |
| `evidence_type` | `VARCHAR(40)` | NOT NULL | 证据实体类型。 |
| `evidence_id` | `VARCHAR(300)` | NOT NULL | 证据实体稳定 ID。 |
| `evidence_hash` | `CHAR(64)` | NOT NULL | 证据 hash。 |
| `support_type` | `VARCHAR(16)` | NOT NULL DEFAULT 'supports' CHECK (support_type IN ('supports','contradicts','context')) | 支持、反驳或背景。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_memory_evidence_tenant_updated (tenant_id, updated_at, memory_evidence_id)`
- `UNIQUE uq_platform_memory_evidence (memory_id, evidence_type, evidence_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
