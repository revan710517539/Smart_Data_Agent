# `platform_knowledge_documents`

- 领域：知识记忆
- 用途：租户隔离的知识文档逻辑身份和处理状态。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `document_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `document_key` | `VARCHAR(200)` | NOT NULL | API 使用的稳定文档标识。 |
| `document_code` | `VARCHAR(200)` | NOT NULL | 稳定文档编码。 |
| `title` | `VARCHAR(500)` | NOT NULL | 文档标题。 |
| `document_type` | `VARCHAR(40)` | NOT NULL CHECK (document_type IN ('metric_rule','business_rule','report','case','manual','policy','market','other')) | 知识类型。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 所有者。 |
| `classification` | `VARCHAR(24)` | NOT NULL DEFAULT 'internal' | 敏感分类。 |
| `domains` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 业务域标签。 |
| `tags` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 检索标签。 |
| `current_version_no` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (current_version_no >= 0) | 当前版本。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','processing','review','active','failed','archived')) | 生命周期。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_knowledge_documents_tenant_updated (tenant_id, updated_at, document_id)`
- `UNIQUE uq_platform_knowledge_documents_key (tenant_id, document_key)`
- `UNIQUE uq_platform_knowledge_documents_code (tenant_id, document_code)`
- `idx_platform_knowledge_documents_status (tenant_id, status, updated_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
