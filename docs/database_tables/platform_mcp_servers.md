# `platform_mcp_servers`

- 领域：Agent与模型
- 用途：MCP Server 注册、认证和健康状态。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `mcp_server_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `server_code` | `VARCHAR(160)` | NOT NULL | 稳定编码。 |
| `server_name` | `VARCHAR(200)` | NOT NULL | 名称。 |
| `transport` | `VARCHAR(24)` | NOT NULL CHECK (transport IN ('stdio','sse','streamable_http')) | MCP transport。 |
| `endpoint` | `TEXT` | 无 | 受 allowlist 管理的 endpoint。 |
| `credential_ref` | `VARCHAR(500)` | 无 | KMS/Vault 凭证引用。 |
| `allowed_agents` | `JSONB` | NOT NULL DEFAULT '[]'::jsonb | 允许调用的 Agent ID。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'configured' CHECK (status IN ('configured','healthy','degraded','disabled')) | 健康状态。 |
| `last_health_at` | `TIMESTAMPTZ` | 无 | 最后健康检查时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_mcp_servers_tenant_updated (tenant_id, updated_at, mcp_server_id)`
- `UNIQUE uq_platform_mcp_servers_code (tenant_id, server_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
