# `platform_skills`

- 领域：Agent与模型
- 用途：Skill 配置、实现、版本和运行策略。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `skill_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `skill_code` | `VARCHAR(160)` | NOT NULL | 稳定 Skill 编码。 |
| `skill_name` | `VARCHAR(200)` | NOT NULL | 名称。 |
| `version` | `VARCHAR(64)` | NOT NULL | 语义版本。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'configured' CHECK (status IN ('configured','implemented','healthy','disabled')) | 可用状态。 |
| `handler_ref` | `VARCHAR(500)` | 无 | 受控 handler 入口。 |
| `risk_level` | `VARCHAR(16)` | NOT NULL DEFAULT 'low' CHECK (risk_level IN ('low','medium','high','critical')) | 风险等级。 |
| `permission_scope` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 所需权限。 |
| `input_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输入 schema。 |
| `output_schema` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 输出 schema。 |
| `timeout_ms` | `INTEGER` | NOT NULL DEFAULT 30000 CHECK (timeout_ms BETWEEN 100 AND 3600000) | 超时。 |
| `retry_policy` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 重试策略。 |
| `package_hash` | `CHAR(64)` | 无 | 安装包校验和。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_skills_tenant_updated (tenant_id, updated_at, skill_id)`
- `UNIQUE uq_platform_skills_code_version (tenant_id, skill_code, version)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
