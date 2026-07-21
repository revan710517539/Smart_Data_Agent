# `platform_data_artifacts`

- 领域：数据接入
- 用途：CSV/Parquet/JSON/图表/导出等不可变对象存储产物。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `artifact_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `artifact_key` | `VARCHAR(160)` | NOT NULL | API 和对象存储服务使用的稳定产物标识。 |
| `artifact_type` | `VARCHAR(32)` | NOT NULL CHECK (artifact_type IN ('csv','parquet','json','image','chart','export','document','other')) | 产物类型。 |
| `object_uri` | `TEXT` | NOT NULL | 对象存储 URI。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 文件 SHA-256。 |
| `content_type` | `VARCHAR(200)` | NOT NULL | MIME 类型。 |
| `size_bytes` | `BIGINT` | NOT NULL CHECK (size_bytes >= 0) | 大小。 |
| `encryption_key_ref` | `VARCHAR(500)` | 无 | 对象加密 key 引用。 |
| `retention_until` | `TIMESTAMPTZ` | 无 | 保留期限。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('uploading','active','quarantined','expired','deleted')) | 对象状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_data_artifacts_tenant_updated (tenant_id, updated_at, artifact_id)`
- `UNIQUE uq_platform_data_artifacts_key (tenant_id, artifact_key)`
- `UNIQUE uq_platform_data_artifacts_hash (tenant_id, content_hash, object_uri)`
- `idx_platform_data_artifacts_retention (status, retention_until)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
