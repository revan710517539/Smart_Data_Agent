# `platform_report_blocks`

- 领域：经营周报
- 用途：报告版本中的表格、图表、文本、结论和图片块。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `report_block_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `report_block_key` | `VARCHAR(160)` | NOT NULL | 版本内稳定块标识。 |
| `report_version_id` | `UUID` | NOT NULL REFERENCES platform_weekly_report_versions(report_version_id) ON DELETE CASCADE | 报告版本。 |
| `section_code` | `VARCHAR(120)` | NOT NULL | 区块所属章节。 |
| `block_code` | `VARCHAR(160)` | NOT NULL | 版本内稳定块编码。 |
| `block_type` | `VARCHAR(24)` | NOT NULL CHECK (block_type IN ('text','table','chart','conclusion','image','todo_summary')) | 块类型。 |
| `sequence_no` | `INTEGER` | NOT NULL CHECK (sequence_no >= 0) | 展示顺序。 |
| `content` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 小型结构化块内容。 |
| `artifact_id` | `UUID` | REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 图片或大型产物。 |
| `content_hash` | `CHAR(64)` | NOT NULL | 块内容 hash。 |
| `generation_status` | `VARCHAR(24)` | NOT NULL DEFAULT 'manual' CHECK (generation_status IN ('manual','generated','reviewed','rejected')) | 生成/审核状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_report_blocks_tenant_updated (tenant_id, updated_at, report_block_id)`
- `UNIQUE uq_platform_report_blocks_code (report_version_id, block_code)`
- `idx_platform_report_blocks_order (report_version_id, sequence_no)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
