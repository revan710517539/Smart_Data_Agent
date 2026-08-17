# `platform_market_sources`

- 领域：市场监控
- 用途：市场数据来源、许可、抓取方式和可信度。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `market_source_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `market_source_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定市场来源标识。 |
| `source_system_id` | `UUID` | NOT NULL REFERENCES platform_source_systems(source_system_id) ON DELETE RESTRICT | 来源系统。 |
| `source_url` | `TEXT` | 无 | 来源页面或 API。 |
| `publisher` | `VARCHAR(300)` | NOT NULL | 发布机构。 |
| `acquisition_method` | `VARCHAR(32)` | NOT NULL CHECK (acquisition_method IN ('api','database','file','licensed_feed','manual_review')) | 获取方式。 |
| `license_type` | `VARCHAR(100)` | 无 | 许可类型。 |
| `reliability_score` | `NUMERIC(7,4)` | CHECK (reliability_score BETWEEN 0 AND 1) | 可信度评分。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','expired','disabled')) | 状态。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_market_sources_tenant_updated (tenant_id, updated_at, market_source_id)`
- `UNIQUE uq_platform_market_source_key (tenant_id, market_source_key)`
- `idx_platform_market_sources_system (tenant_id, source_system_id, status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
