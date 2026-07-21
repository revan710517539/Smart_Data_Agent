# `platform_agent_groups`

- 领域：Agent与模型
- 用途：多 Agent 编排组及阶段门禁定义。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `agent_group_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `group_code` | `VARCHAR(120)` | NOT NULL | 稳定组编码。 |
| `group_name` | `VARCHAR(200)` | NOT NULL | 组名称。 |
| `controller_agent_id` | `UUID` | REFERENCES platform_agents(agent_id) ON DELETE RESTRICT | 控制 Agent。 |
| `state_machine` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 阶段、转移和门禁定义。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','disabled')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_agent_groups_tenant_updated (tenant_id, updated_at, agent_group_id)`
- `UNIQUE uq_platform_agent_groups_code (tenant_id, group_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
