# `platform_capability_approvals`

- 领域：身份权限
- 用途：高风险 Skill 与 MCP 调用的一次性限时审批票据。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `approval_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `approval_key` | `VARCHAR(100)` | NOT NULL UNIQUE | API 使用的不可猜测稳定审批标识。 |
| `subject_type` | `VARCHAR(16)` | NOT NULL CHECK (subject_type IN ('skill','mcp')) | 能力类型。 |
| `subject_id` | `VARCHAR(300)` | NOT NULL | Skill ID 或 MCP server.tool。 |
| `action` | `VARCHAR(64)` | NOT NULL | 被批准的动作。 |
| `input_hash` | `CHAR(64)` | NOT NULL | 规范化输入 SHA-256；不复制敏感输入。 |
| `reason` | `TEXT` | NOT NULL DEFAULT '' | 申请原因。 |
| `requested_by` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 申请人。 |
| `requested_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 申请时间。 |
| `status` | `VARCHAR(16)` | NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','expired','consumed')) | 审批状态。 |
| `reviewed_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 审批人。 |
| `reviewed_at` | `TIMESTAMPTZ` | 无 | 审批时间。 |
| `expires_at` | `TIMESTAMPTZ` | 无 | 批准票据到期时间。 |
| `consumed_at` | `TIMESTAMPTZ` | 无 | 一次性消费时间。 |
| `review_comment` | `TEXT` | NOT NULL DEFAULT '' | 审批意见。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_capability_approvals_tenant_updated (tenant_id, updated_at, approval_id)`
- `idx_platform_capability_approvals_queue (tenant_id, status, requested_at)`
- `idx_platform_capability_approvals_subject (tenant_id, subject_type, subject_id, requested_by, status)`

## 设计说明

- 申请人与审批人必须不同；approved 票据与输入哈希绑定且只能消费一次。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
