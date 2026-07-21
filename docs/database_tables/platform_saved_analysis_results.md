# `platform_saved_analysis_results`

- 领域：智能分析
- 用途：用户收藏的分析执行引用，不复制任务事实。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `saved_result_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `saved_result_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定收藏标识。 |
| `analysis_task_id` | `UUID` | NOT NULL REFERENCES platform_analysis_tasks(analysis_task_id) ON DELETE RESTRICT | 分析任务。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 所有者。 |
| `title` | `VARCHAR(500)` | NOT NULL | 收藏标题。 |
| `visibility` | `VARCHAR(16)` | NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','org','tenant')) | 共享范围。 |
| `folder` | `VARCHAR(300)` | NOT NULL DEFAULT '' | 逻辑文件夹。 |
| `tags` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 标签。 |
| `archived_at` | `TIMESTAMPTZ` | 无 | 保留策略归档时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_saved_analysis_results_tenant_updated (tenant_id, updated_at, saved_result_id)`
- `UNIQUE uq_platform_saved_analysis_key (tenant_id, saved_result_key)`
- `idx_platform_saved_analysis_owner (tenant_id, owner_user_id, updated_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
