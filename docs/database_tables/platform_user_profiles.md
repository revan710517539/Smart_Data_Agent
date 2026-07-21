# `platform_user_profiles`

- 领域：身份权限
- 用途：平台用户身份档案，不在此表保存密码。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `user_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `external_subject` | `VARCHAR(255)` | UNIQUE | 企业 IdP subject。 |
| `email` | `VARCHAR(320)` | NOT NULL | 规范化登录邮箱。 |
| `display_name` | `VARCHAR(200)` | NOT NULL | 展示姓名。 |
| `phone` | `VARCHAR(64)` | 无 | 脱敏联系电话。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'active' CHECK (status IN ('invited','active','locked','disabled')) | 账号状态。 |
| `last_login_at` | `TIMESTAMPTZ` | 无 | 最后成功登录时间。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `UNIQUE uq_platform_user_profiles_email (lower(email))`
- `idx_platform_user_profiles_status (status)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
