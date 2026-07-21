# `platform_dataset_partitions`

- 领域：数据接入
- 用途：数据集分区、快照、新鲜度和对应 Artifact。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `partition_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `partition_code` | `VARCHAR(160)` | NOT NULL | API 使用的稳定分区标识。 |
| `dataset_id` | `UUID` | NOT NULL REFERENCES platform_datasets(dataset_id) ON DELETE CASCADE | 数据集。 |
| `topic_table_id` | `UUID` | REFERENCES platform_topic_tables(topic_table_id) ON DELETE SET NULL | 来源主题表。 |
| `org_unit_id` | `UUID` | REFERENCES platform_org_units(org_unit_id) ON DELETE SET NULL | 机构分区。 |
| `partition_key` | `JSONB` | NOT NULL | 日期、机构等分区键。 |
| `partition_hash` | `CHAR(64)` | NOT NULL | 规范化分区键 hash。 |
| `artifact_id` | `UUID` | REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 离线产物。 |
| `source_version` | `VARCHAR(200)` | 无 | 上游版本。 |
| `snapshot_at` | `TIMESTAMPTZ` | NOT NULL | 数据快照时间。 |
| `watermark_at` | `TIMESTAMPTZ` | 无 | 上游水位。 |
| `row_count` | `BIGINT` | CHECK (row_count >= 0) | 行数。 |
| `data_hash` | `CHAR(64)` | 无 | 规范化结果 hash。 |
| `freshness_status` | `VARCHAR(24)` | NOT NULL CHECK (freshness_status IN ('fresh','stale','unknown','blocked')) | 新鲜度状态。 |
| `acquisition_run_id` | `UUID` | NOT NULL REFERENCES platform_acquisition_job_runs(acquisition_run_id) ON DELETE RESTRICT | 产生该分区的采集执行。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_dataset_partitions_tenant_updated (tenant_id, updated_at, partition_id)`
- `UNIQUE uq_platform_partition_code (tenant_id, partition_code)`
- `UNIQUE uq_platform_dataset_partitions (dataset_id, partition_hash, snapshot_at)`
- `idx_platform_dataset_partitions_latest (tenant_id, dataset_id, org_unit_id, snapshot_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
