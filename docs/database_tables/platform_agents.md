# `platform_agents`

- 领域：Agent与模型
- 用途：可运行 Agent 定义和启用状态。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `agent_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `agent_code` | `VARCHAR(120)` | NOT NULL | 稳定 Agent 编码。 |
| `agent_name` | `VARCHAR(200)` | NOT NULL | 名称。 |
| `agent_type` | `VARCHAR(64)` | NOT NULL | planner/query/reviewer 等类型。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'configured' CHECK (status IN ('configured','implemented','healthy','disabled')) | 运行可用状态。 |
| `model_integration_id` | `UUID` | 无 | 绑定模型，外键在模型表建成后由迁移补充。 |
| `input_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输入 JSON Schema。 |
| `output_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输出 JSON Schema。 |
| `runtime_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 超时、配额等运行设置。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_agents_tenant_updated (tenant_id, updated_at, agent_id)`
- `UNIQUE uq_platform_agents_code (tenant_id, agent_code)`
- `idx_platform_agents_status (tenant_id, status)`

## 延后建立的外键

- `fk_platform_agents_model`：`model_integration_id` → `platform_model_integrations(model_integration_id)`，删除策略 `RESTRICT`。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
