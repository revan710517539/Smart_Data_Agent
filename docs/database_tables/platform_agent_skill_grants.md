# `platform_agent_skill_grants`

- 领域：Agent与模型
- 用途：Agent 被允许使用的 Skill 及版本范围。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 租户。 |
| `agent_id` | `UUID` | NOT NULL REFERENCES platform_agents(agent_id) ON DELETE CASCADE | Agent。 |
| `skill_id` | `UUID` | NOT NULL REFERENCES platform_skills(skill_id) ON DELETE CASCADE | Skill。 |
| `grant_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 配额和参数限制。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |
| 表级约束 | — | `PRIMARY KEY (tenant_id, agent_id, skill_id)` | 表级主键。 |

## 索引

- 主键索引；暂无额外索引。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
