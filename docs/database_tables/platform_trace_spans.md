# `platform_trace_spans`

- 领域：可观测性
- 用途：OpenTelemetry 兼容的父子 Span、耗时和资源属性。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `span_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `span_key` | `VARCHAR(160)` | NOT NULL | 运行时生成的稳定 Span 标识。 |
| `trace_id` | `VARCHAR(100)` | NOT NULL | Trace ID。 |
| `parent_span_id` | `UUID` | REFERENCES platform_trace_spans(span_id) ON DELETE SET NULL | 父 Span。 |
| `span_name` | `VARCHAR(240)` | NOT NULL | Span 名称。 |
| `span_kind` | `VARCHAR(24)` | NOT NULL DEFAULT 'internal' | Span kind。 |
| `status` | `VARCHAR(16)` | NOT NULL CHECK (status IN ('unset','ok','error')) | 状态。 |
| `started_at` | `TIMESTAMPTZ` | NOT NULL | 开始时间。 |
| `ended_at` | `TIMESTAMPTZ` | 无 | 结束时间。 |
| `duration_ms` | `INTEGER` | CHECK (duration_ms >= 0) | 耗时。 |
| `attributes` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 脱敏属性。 |
| `error_code` | `VARCHAR(100)` | 无 | 稳定错误码。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_trace_spans_tenant_updated (tenant_id, updated_at, span_id)`
- `UNIQUE uq_platform_trace_spans_key (tenant_id, trace_id, span_key)`
- `idx_platform_trace_spans_trace (tenant_id, trace_id, started_at)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
