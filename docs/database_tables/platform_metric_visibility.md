# `platform_metric_visibility`

- 领域：指标语义
- 用途：按用户、角色或组织授予指标可见范围。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `visibility_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 记录 ID。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 租户。 |
| `metric_id` | `UUID` | NOT NULL REFERENCES platform_metric_dictionary(metric_id) ON DELETE CASCADE | 指标。 |
| `subject_type` | `VARCHAR(16)` | NOT NULL CHECK (subject_type IN ('user','role','org','tenant')) | 授权主体类型。 |
| `subject_id` | `UUID` | NOT NULL | 授权主体 ID。 |
| `effect` | `VARCHAR(16)` | NOT NULL DEFAULT 'allow' CHECK (effect IN ('allow','deny')) | 允许/拒绝。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 授权人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间。 |

## 索引

- `UNIQUE uq_platform_metric_visibility (tenant_id, metric_id, subject_type, subject_id)`
- `idx_platform_metric_visibility_subject (tenant_id, subject_type, subject_id)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
