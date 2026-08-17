# `platform_mcp_tools`

- 领域：Agent与模型
- 用途：从 MCP Server 同步并授权的工具目录。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `mcp_tool_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `mcp_server_id` | `UUID` | NOT NULL REFERENCES platform_mcp_servers(mcp_server_id) ON DELETE CASCADE | 所属 Server。 |
| `tool_name` | `VARCHAR(200)` | NOT NULL | 工具名称。 |
| `description` | `TEXT` | NOT NULL DEFAULT '' | 工具说明。 |
| `input_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输入 schema。 |
| `risk_level` | `VARCHAR(16)` | NOT NULL DEFAULT 'medium' CHECK (risk_level IN ('low','medium','high','critical')) | 风险等级。 |
| `is_enabled` | `BOOLEAN` | NOT NULL DEFAULT false | 是否启用。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_mcp_tools_tenant_updated (tenant_id, updated_at, mcp_tool_id)`
- `UNIQUE uq_platform_mcp_tools_name (mcp_server_id, tool_name)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
