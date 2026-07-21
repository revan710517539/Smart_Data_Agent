# `platform_topic_table_sources`

- 领域：指标语义
- 用途：主题表依赖的数据集及连接版本。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `topic_table_id` | `UUID` | NOT NULL REFERENCES platform_topic_tables(topic_table_id) ON DELETE CASCADE | 主题表。 |
| `dataset_id` | `UUID` | NOT NULL REFERENCES platform_datasets(dataset_id) ON DELETE RESTRICT | 来源数据集。 |
| `source_alias` | `VARCHAR(160)` | NOT NULL | 查询别名。 |
| `join_role` | `VARCHAR(32)` | NOT NULL DEFAULT 'primary' CHECK (join_role IN ('primary','lookup','bridge')) | 来源角色。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |
| 表级约束 | — | `PRIMARY KEY (topic_table_id, dataset_id)` | 表级主键。 |

## 索引

- 主键索引；暂无额外索引。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
