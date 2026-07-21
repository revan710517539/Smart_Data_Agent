# `platform_weekly_report_versions`

- 领域：经营周报
- 用途：不可变周报版本、发布状态、父版本和校验和。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `report_version_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `report_version_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定版本标识。 |
| `report_id` | `UUID` | NOT NULL REFERENCES platform_reports(report_id) ON DELETE CASCADE | 报告。 |
| `version_no` | `INTEGER` | NOT NULL CHECK (version_no > 0) | 版本号。 |
| `parent_version_id` | `UUID` | REFERENCES platform_weekly_report_versions(report_version_id) ON DELETE SET NULL | 父版本。 |
| `period_start` | `DATE` | NOT NULL | 报告周期开始。 |
| `period_end` | `DATE` | NOT NULL | 报告周期结束。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','review','published','withdrawn','archived')) | 生命周期。 |
| `version_checksum` | `CHAR(64)` | NOT NULL | 所有块和来源的规范化 hash。 |
| `data_snapshot_at` | `TIMESTAMPTZ` | NOT NULL | 数据快照时间。 |
| `submitted_at` | `TIMESTAMPTZ` | 无 | 提交时间。 |
| `published_at` | `TIMESTAMPTZ` | 无 | 发布时间。 |
| `published_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 发布人。 |
| `document_metadata` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 不重复块正文的版本级报告与章节元数据。 |
| `evidence_summary` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 版本发布证据门禁摘要。 |
| `saved_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 页面显示的版本保存时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_weekly_report_versions_tenant_updated (tenant_id, updated_at, report_version_id)`
- `UNIQUE uq_platform_weekly_report_version_key (tenant_id, report_version_key)`
- `UNIQUE uq_platform_weekly_report_versions (report_id, version_no)`
- `UNIQUE uq_platform_weekly_report_version_hash (report_id, version_checksum)`
- `idx_platform_weekly_report_versions_period (tenant_id, period_start, period_end, status)`

## 设计说明

- published 版本不可更新；编辑必须创建新版本。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
