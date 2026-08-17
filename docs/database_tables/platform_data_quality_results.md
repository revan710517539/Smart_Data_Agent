# `platform_data_quality_results`

- 领域：数据治理
- 用途：质量规则对指定分区/快照的执行结果。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `quality_result_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `quality_result_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定质量结果标识。 |
| `quality_rule_id` | `UUID` | NOT NULL REFERENCES platform_data_quality_rules(quality_rule_id) ON DELETE RESTRICT | 质量规则。 |
| `partition_id` | `UUID` | REFERENCES platform_dataset_partitions(partition_id) ON DELETE CASCADE | 数据分区。 |
| `acquisition_run_id` | `UUID` | NOT NULL REFERENCES platform_acquisition_job_runs(acquisition_run_id) ON DELETE CASCADE | 关联采集执行。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('passed','warning','failed','error')) | 结果状态。 |
| `score` | `NUMERIC(7,4)` | CHECK (score BETWEEN 0 AND 1) | 归一化得分。 |
| `observed_value` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 观测结果。 |
| `threshold` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 执行时阈值。 |
| `sample_artifact_id` | `UUID` | REFERENCES platform_data_artifacts(artifact_id) ON DELETE SET NULL | 问题样例产物。 |
| `evaluated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 评估时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_data_quality_results_tenant_updated (tenant_id, updated_at, quality_result_id)`
- `UNIQUE uq_platform_quality_result_key (tenant_id, quality_result_key)`
- `idx_platform_data_quality_results_partition (tenant_id, partition_id, status)`
- `idx_platform_data_quality_results_run (tenant_id, acquisition_run_id, evaluated_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
