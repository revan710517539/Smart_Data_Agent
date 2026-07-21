# `platform_agent_group_members`

- 领域：Agent与模型
- 用途：Agent 在编排组中的顺序、职责和门禁。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `agent_group_id` | `UUID` | NOT NULL REFERENCES platform_agent_groups(agent_group_id) ON DELETE CASCADE | Agent 组。 |
| `agent_id` | `UUID` | NOT NULL REFERENCES platform_agents(agent_id) ON DELETE RESTRICT | Agent。 |
| `stage_code` | `VARCHAR(100)` | NOT NULL | 阶段编码。 |
| `sequence_no` | `INTEGER` | NOT NULL CHECK (sequence_no >= 0) | 执行顺序。 |
| `is_required` | `BOOLEAN` | NOT NULL DEFAULT true | 是否必需。 |
| `gate_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 进入/退出门禁。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |
| 表级约束 | — | `PRIMARY KEY (agent_group_id, agent_id, stage_code)` | 表级主键。 |

## 索引

- `idx_platform_agent_group_members_order (agent_group_id, sequence_no)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
