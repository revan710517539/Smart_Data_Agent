# `platform_acquisition_script_versions`

- 领域：数据接入
- 用途：不可变获取脚本版本、签名和审批结果。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `script_version_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `script_version_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定脚本版本标识。 |
| `acquisition_script_id` | `UUID` | NOT NULL REFERENCES platform_acquisition_scripts(acquisition_script_id) ON DELETE CASCADE | 脚本。 |
| `version_no` | `INTEGER` | NOT NULL CHECK (version_no > 0) | 版本号。 |
| `source_code` | `TEXT` | NOT NULL | 脚本源代码。 |
| `source_hash` | `CHAR(64)` | NOT NULL | 源代码 hash。 |
| `dependency_lock` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 依赖锁。 |
| `input_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输入 schema。 |
| `output_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输出 schema。 |
| `review_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','approved','rejected','revoked')) | 审批状态。 |
| `reviewed_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 审批人。 |
| `reviewed_at` | `TIMESTAMPTZ` | 无 | 审批时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_acquisition_script_versions_tenant_updated (tenant_id, updated_at, script_version_id)`
- `UNIQUE uq_platform_script_version_key (tenant_id, script_version_key)`
- `UNIQUE uq_platform_acquisition_script_versions (acquisition_script_id, version_no)`

## 设计说明

- LLM 修复必须创建新版本并经过人工审批，禁止覆盖已发布代码。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
