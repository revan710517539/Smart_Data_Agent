# `platform_knowledge_versions`

- 领域：知识记忆
- 用途：不可变知识正文版本及对象存储来源。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `knowledge_version_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `version_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定版本标识。 |
| `document_id` | `UUID` | NOT NULL REFERENCES platform_knowledge_documents(document_id) ON DELETE CASCADE | 文档。 |
| `version_no` | `INTEGER` | NOT NULL CHECK (version_no > 0) | 版本号。 |
| `source_attachment_id` | `UUID` | REFERENCES platform_file_attachments(attachment_id) ON DELETE RESTRICT | 原文件。 |
| `content_artifact_id` | `UUID` | REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 解析正文产物。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 正文 hash。 |
| `language` | `VARCHAR(32)` | NOT NULL DEFAULT 'zh-CN' | 语言。 |
| `parser_name` | `VARCHAR(160)` | 无 | 解析器和版本。 |
| `processing_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending','scanning','parsing','indexing','ready','failed')) | 处理状态。 |
| `published_at` | `TIMESTAMPTZ` | 无 | 发布时间。 |
| `reviewed_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 批准发布的评审人。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_knowledge_versions_tenant_updated (tenant_id, updated_at, knowledge_version_id)`
- `UNIQUE uq_platform_knowledge_version_key (tenant_id, version_key)`
- `UNIQUE uq_platform_knowledge_versions (document_id, version_no)`

## 设计说明

- 正文不进入审计或任务 JSON；通过 artifact_id 受控读取。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
