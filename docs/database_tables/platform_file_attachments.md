# `platform_file_attachments`

- 领域：数据接入
- 用途：业务对象与对象存储文件之间的授权引用。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `attachment_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `attachment_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定附件标识。 |
| `artifact_id` | `UUID` | NOT NULL REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 文件产物。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 文件所有者。 |
| `resource_type` | `VARCHAR(80)` | NOT NULL | 挂载业务对象类型。 |
| `resource_id` | `VARCHAR(300)` | NOT NULL | 业务对象稳定 ID。 |
| `file_name` | `VARCHAR(500)` | NOT NULL | 原始文件名。 |
| `detected_content_type` | `VARCHAR(200)` | NOT NULL | 服务端嗅探得到的 MIME 类型。 |
| `scan_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (scan_status IN ('pending','clean','infected','failed')) | 病毒扫描状态。 |
| `processing_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending','processing','ready','failed')) | 解析状态。 |
| `processing_error` | `VARCHAR(200)` | NOT NULL DEFAULT '' | 脱敏解析或 OCR 稳定错误码。 |
| `classification` | `VARCHAR(24)` | NOT NULL DEFAULT 'internal' | 敏感级别。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_file_attachments_tenant_updated (tenant_id, updated_at, attachment_id)`
- `UNIQUE uq_platform_file_attachments_key (tenant_id, attachment_key)`
- `idx_platform_file_attachments_resource (tenant_id, resource_type, resource_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
