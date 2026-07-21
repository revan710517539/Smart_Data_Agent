# `platform_acquisition_jobs`

- 领域：数据接入
- 用途：实时/离线/API/文件数据获取任务定义。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `acquisition_job_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `job_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定采集任务标识。 |
| `job_code` | `VARCHAR(160)` | NOT NULL | 稳定任务编码。 |
| `job_name` | `VARCHAR(300)` | NOT NULL | 任务名称。 |
| `source_system_id` | `UUID` | NOT NULL REFERENCES platform_source_systems(source_system_id) ON DELETE RESTRICT | 来源系统。 |
| `script_version_id` | `UUID` | NOT NULL REFERENCES platform_acquisition_script_versions(script_version_id) ON DELETE RESTRICT | 已审批脚本版本。 |
| `connection_id` | `UUID` | NOT NULL REFERENCES platform_data_connections(connection_id) ON DELETE RESTRICT | 数据连接。 |
| `target_dataset_id` | `UUID` | REFERENCES platform_datasets(dataset_id) ON DELETE RESTRICT | 目标数据集。 |
| `topic_table_id` | `UUID` | REFERENCES platform_topic_tables(topic_table_id) ON DELETE SET NULL | 可选主题表。 |
| `trigger_type` | `VARCHAR(24)` | NOT NULL CHECK (trigger_type IN ('manual','schedule','event')) | 触发类型。 |
| `schedule_expression` | `VARCHAR(200)` | 无 | 调度表达式。 |
| `execution_mode` | `VARCHAR(16)` | NOT NULL CHECK (execution_mode IN ('realtime','offline')) | 实时或离线。 |
| `job_config` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 分页、分区、游标和超时。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','disabled')) | 状态。 |
| `next_run_at` | `TIMESTAMPTZ` | 无 | 下次执行。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 任务负责人。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_acquisition_jobs_tenant_updated (tenant_id, updated_at, acquisition_job_id)`
- `UNIQUE uq_platform_acquisition_jobs_key (tenant_id, job_key)`
- `UNIQUE uq_platform_acquisition_jobs_code (tenant_id, job_code)`
- `idx_platform_acquisition_jobs_due (status, next_run_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
