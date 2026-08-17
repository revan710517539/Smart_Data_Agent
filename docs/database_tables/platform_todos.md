# `platform_todos`

- 领域：自动化与通知
- 用途：可分配、提醒、关联证据和回收结果的待办任务。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `todo_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `todo_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定待办标识。 |
| `title` | `VARCHAR(500)` | NOT NULL | 标题。 |
| `description` | `TEXT` | NOT NULL DEFAULT '' | 说明。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 创建人。 |
| `assignee_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 责任人。 |
| `org_unit_id` | `UUID` | REFERENCES platform_org_units(org_unit_id) ON DELETE SET NULL | 责任机构。 |
| `source_type` | `VARCHAR(40)` | 无 | 周报、分析、告警等来源。 |
| `source_id` | `UUID` | 无 | 来源 ID。 |
| `priority` | `VARCHAR(16)` | NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','urgent')) | 优先级。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','blocked','completed','cancelled')) | 状态。 |
| `due_at` | `TIMESTAMPTZ` | 无 | 截止时间。 |
| `completed_at` | `TIMESTAMPTZ` | 无 | 完成时间。 |
| `result_summary` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 执行结果和指标效果。 |
| `todo_metadata` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 页面所需清单、标签和来源展示元数据。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_todos_tenant_updated (tenant_id, updated_at, todo_id)`
- `UNIQUE uq_platform_todos_key (tenant_id, todo_key)`
- `idx_platform_todos_assignee (tenant_id, assignee_user_id, status, due_at)`
- `idx_platform_todos_source (tenant_id, source_type, source_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
