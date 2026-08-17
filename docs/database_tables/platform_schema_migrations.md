# `platform_schema_migrations`

- 领域：基础设施
- 用途：记录已执行数据库迁移及不可变校验和。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `version` | `VARCHAR(32)` | PRIMARY KEY | 迁移版本号。 |
| `name` | `VARCHAR(200)` | NOT NULL | 迁移名称。 |
| `checksum` | `CHAR(64)` | NOT NULL | 迁移文件 SHA-256。 |
| `applied_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 应用时间。 |
| `execution_ms` | `INTEGER` | NOT NULL DEFAULT 0 CHECK (execution_ms >= 0) | 执行耗时。 |

## 索引

- 主键索引；暂无额外索引。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
