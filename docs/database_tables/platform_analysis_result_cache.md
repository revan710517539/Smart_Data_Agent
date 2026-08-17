# `platform_analysis_result_cache`

- 领域：智能分析
- 用途：权限、CSV、语义和执行版本绑定的安全结果缓存索引。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `cache_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `cache_key` | `CHAR(64)` | NOT NULL | 规范化缓存输入 SHA-256。 |
| `owner_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE CASCADE | 缓存创建用户。 |
| `authorization_hash` | `CHAR(64)` | NOT NULL | 授权策略快照摘要。 |
| `csv_snapshot_hash` | `CHAR(64)` | NOT NULL | CSV 数据快照摘要。 |
| `semantic_version_hash` | `CHAR(64)` | NOT NULL | 指标和语义版本摘要。 |
| `execution_version_hash` | `CHAR(64)` | NOT NULL | Skill、模型和代码版本摘要。 |
| `result_ref` | `VARCHAR(240)` | NOT NULL | 可信产物引用。 |
| `expires_at` | `TIMESTAMPTZ` | NOT NULL | 缓存到期时间。 |
| `invalidated_at` | `TIMESTAMPTZ` | 无 | 失效时间。 |
| `invalidation_reason` | `VARCHAR(120)` | NOT NULL DEFAULT '' | 失效原因稳定码。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_analysis_result_cache_tenant_updated (tenant_id, updated_at, cache_id)`
- `UNIQUE uq_platform_analysis_result_cache_key (tenant_id, cache_key)`
- `idx_platform_analysis_result_cache_expiry (tenant_id, expires_at, invalidated_at)`

## 设计说明

- 缓存命中仍需重新计算 authorization_hash；任何组成摘要变化都不得复用。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
