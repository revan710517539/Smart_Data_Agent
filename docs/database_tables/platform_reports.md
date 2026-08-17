# `platform_reports`

- 领域：经营周报
- 用途：报告逻辑身份、所有者、模板和当前版本。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `report_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `report_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定报告标识。 |
| `report_code` | `VARCHAR(160)` | NOT NULL | 稳定报告编码。 |
| `report_name` | `VARCHAR(500)` | NOT NULL | 报告名称。 |
| `report_type` | `VARCHAR(40)` | NOT NULL CHECK (report_type IN ('weekly','daily','monthly','dashboard','ad_hoc')) | 报告类型。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 所有者。 |
| `org_unit_id` | `UUID` | REFERENCES platform_org_units(org_unit_id) ON DELETE SET NULL | 所属机构。 |
| `template_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 版本化模板引用和块定义。 |
| `current_version_no` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (current_version_no >= 0) | 当前版本。 |
| `visibility` | `VARCHAR(16)` | NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','org','tenant')) | 共享范围。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived','deleted')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_reports_tenant_updated (tenant_id, updated_at, report_id)`
- `UNIQUE uq_platform_reports_key (tenant_id, report_key)`
- `UNIQUE uq_platform_reports_code (tenant_id, report_code)`
- `idx_platform_reports_owner (tenant_id, owner_user_id, updated_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
