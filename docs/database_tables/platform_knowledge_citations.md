# `platform_knowledge_citations`

- 领域：知识记忆
- 用途：分析结论、报告块对知识分块的可验证引用。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `citation_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `citation_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定引用标识。 |
| `chunk_id` | `UUID` | NOT NULL REFERENCES platform_knowledge_chunks(chunk_id) ON DELETE RESTRICT | 知识分块。 |
| `resource_type` | `VARCHAR(40)` | NOT NULL | analysis_conclusion/report_block 等引用方。 |
| `resource_id` | `VARCHAR(300)` | NOT NULL | 引用方稳定 ID。 |
| `quote_hash` | `CHAR(64)` | NOT NULL | 引用片段 hash。 |
| `locator` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 页码、段落、字符区间。 |
| `relevance_score` | `NUMERIC(7,4)` | CHECK (relevance_score BETWEEN 0 AND 1) | 相关度。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_knowledge_citations_tenant_updated (tenant_id, updated_at, citation_id)`
- `UNIQUE uq_platform_knowledge_citation (tenant_id, chunk_id, resource_type, resource_id)`
- `idx_platform_knowledge_citations_resource (tenant_id, resource_type, resource_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
