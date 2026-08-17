# `platform_application_actions`

- 领域：页面兼容
- 用途：已注册页面动作的命令记录和真实 handler 结果。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `application_action_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `application_action_key` | `VARCHAR(160)` | NOT NULL | API 使用的稳定动作记录标识。 |
| `module_code` | `VARCHAR(160)` | NOT NULL | 页面模块。 |
| `action_code` | `VARCHAR(160)` | NOT NULL | 必须注册的动作编码。 |
| `actor_user_id` | `UUID` | NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT | 操作者。 |
| `idempotency_key` | `VARCHAR(200)` | NOT NULL | 幂等键。 |
| `request_payload` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 经 schema 校验和脱敏的命令参数。 |
| `status` | `VARCHAR(24)` | NOT NULL CHECK (status IN ('accepted','running','succeeded','failed','rejected')) | 真实执行状态。 |
| `handler_ref` | `VARCHAR(300)` | NOT NULL | 实际 handler。 |
| `result_ref` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 业务实体/产物引用。 |
| `error_code` | `VARCHAR(100)` | 无 | 稳定错误码。 |
| `finished_at` | `TIMESTAMPTZ` | 无 | 完成时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_application_actions_tenant_updated (tenant_id, updated_at, application_action_id)`
- `UNIQUE uq_platform_application_action_key (tenant_id, application_action_key)`
- `UNIQUE uq_platform_application_actions_idempotency (tenant_id, module_code, action_code, idempotency_key)`
- `idx_platform_application_actions_actor (tenant_id, actor_user_id, created_at)`

## 设计说明

- 未注册 action_code 必须由 API 返回 4xx，不得记录为成功。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
