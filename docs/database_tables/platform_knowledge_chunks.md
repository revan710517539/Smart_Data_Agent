# `platform_knowledge_chunks`

- 领域：知识记忆
- 用途：知识版本的可检索分块、关键词与向量引用。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `chunk_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `chunk_key` | `VARCHAR(160)` | NOT NULL | API 和引用使用的稳定分块标识。 |
| `knowledge_version_id` | `UUID` | NOT NULL REFERENCES platform_knowledge_versions(knowledge_version_id) ON DELETE CASCADE | 文档版本。 |
| `chunk_no` | `INTEGER` | NOT NULL CHECK (chunk_no >= 0) | 分块序号。 |
| `content` | `TEXT` | NOT NULL | 受权限保护的分块文本。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 分块 hash。 |
| `token_count` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (token_count >= 0) | token 数。 |
| `heading_path` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 标题路径。 |
| `keywords` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 关键词。 |
| `locator` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 页码、段落和字符区间。 |
| `embedding_model` | `VARCHAR(200)` | 无 | 向量模型。 |
| `embedding_ref` | `VARCHAR(500)` | 无 | 向量库引用；不强制在业务库保存大向量。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_knowledge_chunks_tenant_updated (tenant_id, updated_at, chunk_id)`
- `UNIQUE uq_platform_knowledge_chunk_key (tenant_id, chunk_key)`
- `UNIQUE uq_platform_knowledge_chunks (knowledge_version_id, chunk_no)`
- `idx_platform_knowledge_chunks_hash (tenant_id, content_hash)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
