# `platform_application_module_state`

- 领域：页面兼容
- 用途：现有页面非核心 UI 状态的服务端持久化兼容层。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `module_state_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `module_code` | `VARCHAR(160)` | NOT NULL | 页面模块编码。 |
| `owner_user_id` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 个人状态所有者；为空表示租户共享。 |
| `state_key` | `VARCHAR(200)` | NOT NULL | 状态键。 |
| `state_value` | `JSONB` | NOT NULL | 非核心页面状态。 |
| `state_schema_version` | `INTEGER` | NOT NULL DEFAULT 1 CHECK (state_schema_version > 0) | 状态 schema 版本。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_application_module_state_tenant_updated (tenant_id, updated_at, module_state_id)`
- `UNIQUE uq_platform_application_module_state (tenant_id, module_code, COALESCE(owner_user_id, '00000000-0000-0000-0000-000000000000'::uuid), state_key)`

## 设计说明

- 报告、评论、任务等核心实体不得继续写入该通用状态表。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
