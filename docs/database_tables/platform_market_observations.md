# `platform_market_observations`

- 领域：市场监控
- 用途：带来源、时间、单位和证据的市场指标观测值。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `market_observation_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `market_observation_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定观测标识。 |
| `market_source_id` | `UUID` | NOT NULL REFERENCES platform_market_sources(market_source_id) ON DELETE RESTRICT | 市场来源。 |
| `market_entity_id` | `UUID` | NOT NULL REFERENCES platform_market_entities(market_entity_id) ON DELETE CASCADE | 市场实体。 |
| `metric_code` | `VARCHAR(160)` | NOT NULL | 观测指标编码。 |
| `observed_at` | `TIMESTAMPTZ` | NOT NULL | 观测时间。 |
| `value_numeric` | `NUMERIC(30,10)` | 无 | 数值。 |
| `value_text` | `TEXT` | 无 | 文本值。 |
| `unit` | `VARCHAR(64)` | 无 | 单位。 |
| `currency` | `CHAR(3)` | 无 | 币种。 |
| `evidence_artifact_id` | `UUID` | REFERENCES platform_data_artifacts(artifact_id) ON DELETE RESTRICT | 证据文件。 |
| `source_record_id` | `VARCHAR(300)` | 无 | 来源记录 ID。 |
| `confidence` | `NUMERIC(7,4)` | CHECK (confidence BETWEEN 0 AND 1) | 可信度。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_market_observations_tenant_updated (tenant_id, updated_at, market_observation_id)`
- `UNIQUE uq_platform_market_observation_key (tenant_id, market_observation_key)`
- `UNIQUE uq_platform_market_observations_record (tenant_id, market_source_id, source_record_id, metric_code)`
- `UNIQUE uq_platform_market_observations (tenant_id, market_source_id, market_entity_id, metric_code, observed_at, source_record_id)`
- `idx_platform_market_observations_time (tenant_id, market_entity_id, metric_code, observed_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
