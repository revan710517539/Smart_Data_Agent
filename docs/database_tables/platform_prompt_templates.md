# `platform_prompt_templates`

- 领域：Agent与模型
- 用途：版本化 Prompt 模板及发布状态。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `prompt_template_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `template_code` | `VARCHAR(160)` | NOT NULL | 稳定模板编码。 |
| `version` | `INTEGER` | NOT NULL CHECK (version > 0) | 模板版本。 |
| `template_body` | `TEXT` | NOT NULL | 模板正文。 |
| `input_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 模板变量 schema。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','published','archived')) | 生命周期。 |
| `published_at` | `TIMESTAMPTZ` | 无 | 发布时间。 |
| `checksum` | `CHAR(64)` | NOT NULL | 模板内容 hash。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_prompt_templates_tenant_updated (tenant_id, updated_at, prompt_template_id)`
- `UNIQUE uq_platform_prompt_templates_version (tenant_id, template_code, version)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
