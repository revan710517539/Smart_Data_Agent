# `platform_raw_table_external_references`

- 领域：数据治理
- 用途：CSV 原始表在 SDA 中的外部引用授权；不写入或修改 CSV 文件。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 授权所属租户。 |
| `source_key` | `VARCHAR(128)` | NOT NULL | 原始表的稳定来源键。 |
| `mode` | `VARCHAR(16)` | NOT NULL CHECK (mode IN ('private','shared')) | 外部引用模式；shared 才允许 Bridge 读取。 |
| `schema_fingerprint` | `VARCHAR(128)` | NOT NULL | 授权时表结构指纹，结构变化后授权失效。 |
| `updated_by` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 最近明确授权或收回授权的用户。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最近授权状态更新时间。 |
| 表级约束 | — | `PRIMARY KEY (tenant_id, source_key)` | 租户内每张原始表只有一条外部引用授权。 |

## 索引

- 主键索引；暂无额外索引。

## 设计说明

- 只记录用户授权和 schema 指纹；原始行数据仍留在权威 CSV 来源。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
