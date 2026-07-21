# `platform_acquisition_scripts`

- 领域：数据接入
- 用途：数据获取脚本逻辑身份和已发布版本。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `acquisition_script_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `script_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定脚本标识。 |
| `script_code` | `VARCHAR(160)` | NOT NULL | 稳定脚本编码。 |
| `script_name` | `VARCHAR(300)` | NOT NULL | 名称。 |
| `runtime` | `VARCHAR(32)` | NOT NULL CHECK (runtime IN ('python','sql','http','browser','shell_restricted')) | 受控运行时。 |
| `current_version_no` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (current_version_no >= 0) | 当前发布版本。 |
| `owner_user_id` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 负责人。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','active','degraded','disabled')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_acquisition_scripts_tenant_updated (tenant_id, updated_at, acquisition_script_id)`
- `UNIQUE uq_platform_acquisition_scripts_key (tenant_id, script_key)`
- `UNIQUE uq_platform_acquisition_scripts_code (tenant_id, script_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
