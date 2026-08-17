# `platform_analysis_workspaces`

- 领域：智能分析
- 用途：页面、报告或自主分析对应的持久化分析工作区。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `workspace_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `workspace_key` | `VARCHAR(160)` | NOT NULL | 租户内稳定工作区标识。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 工作区所有者。 |
| `page_key` | `VARCHAR(160)` | NOT NULL | 页面或业务场景编码。 |
| `artifact_ref` | `VARCHAR(240)` | NOT NULL DEFAULT '' | 关联报表或可视化产物引用。 |
| `context_snapshot` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 数据快照、指标版本、筛选器与授权动作。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived','deleted')) | 工作区状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_workspaces_tenant_updated (tenant_id, updated_at, workspace_id)`
- `UNIQUE uq_platform_analysis_workspaces_key (tenant_id, workspace_key)`
- `idx_platform_analysis_workspaces_owner (tenant_id, owner_user_id, updated_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
