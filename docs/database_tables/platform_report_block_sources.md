# `platform_report_block_sources`

- 领域：经营周报
- 用途：报告块与分析、查询、数据分区和知识证据之间的来源关系。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `report_block_id` | `UUID` | NOT NULL REFERENCES platform_report_blocks(report_block_id) ON DELETE CASCADE | 报告块。 |
| `source_type` | `VARCHAR(32)` | NOT NULL CHECK (source_type IN ('analysis_task','analysis_query','analysis_artifact','partition','knowledge','market_event')) | 来源类型。 |
| `source_id` | `UUID` | NOT NULL | 来源实体 ID。 |
| `source_hash` | `CHAR(64)` | NOT NULL | 生成时来源 hash。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |
| 表级约束 | — | `PRIMARY KEY (report_block_id, source_type, source_id)` | 表级主键。 |

## 索引

- `idx_platform_report_block_sources_source (source_type, source_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
