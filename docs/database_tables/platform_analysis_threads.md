# `platform_analysis_threads`

- 领域：智能分析
- 用途：总体分析及图表、指标、机构或数据点的分支线程。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `thread_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `workspace_id` | `UUID` | NOT NULL REFERENCES platform_analysis_workspaces(workspace_id) ON DELETE CASCADE | 所属工作区。 |
| `parent_thread_id` | `UUID` | REFERENCES platform_analysis_threads(thread_id) ON DELETE RESTRICT | 父线程；根线程为空。 |
| `root_thread_id` | `UUID` | REFERENCES platform_analysis_threads(thread_id) ON DELETE RESTRICT | 根线程；创建根线程后回填自身。 |
| `title` | `VARCHAR(240)` | NOT NULL DEFAULT '' | 线程标题。 |
| `anchor` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 图表、文本、指标或数据点锚点。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','merged','archived')) | 线程状态。 |
| `merged_into_thread_id` | `UUID` | REFERENCES platform_analysis_threads(thread_id) ON DELETE RESTRICT | 合并目标线程。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_threads_tenant_updated (tenant_id, updated_at, thread_id)`
- `idx_platform_analysis_threads_workspace (tenant_id, workspace_id, updated_at)`
- `idx_platform_analysis_threads_parent (workspace_id, parent_thread_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
