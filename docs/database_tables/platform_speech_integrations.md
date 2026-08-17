# `platform_speech_integrations`

- 领域：Agent与模型
- 用途：ASR/TTS 提供商接入和凭证。
- 结构化运行主库：MySQL 8.x

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `speech_integration_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `tenant_id` | `UUID` | NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE | 所属租户。 |
| `integration_code` | `VARCHAR(160)` | NOT NULL | 稳定编码。 |
| `display_name` | `VARCHAR(200)` | NOT NULL | 页面展示名称。 |
| `source_name` | `VARCHAR(200)` | NOT NULL DEFAULT '' | 服务来源展示名称。 |
| `provider` | `VARCHAR(100)` | NOT NULL | 提供商。 |
| `capability` | `VARCHAR(16)` | NOT NULL CHECK (capability IN ('asr','tts','both')) | 语音能力。 |
| `endpoint` | `TEXT` | NOT NULL | 经 SSRF 校验的地址。 |
| `credential_ciphertext` | `BYTEA` | 无 | KMS envelope 密文。 |
| `key_version` | `VARCHAR(100)` | 无 | KMS key version。 |
| `test_result` | `JSONB` | NOT NULL DEFAULT '{}'::jsonb | 最近一次真实测试的脱敏结果。 |
| `status` | `VARCHAR(24)` | NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','testing','available','degraded','disabled')) | 状态。 |
| `last_test_at` | `TIMESTAMPTZ` | 无 | 最后测试时间。 |
| `created_by` | `UUID` | REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL | 创建人。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_speech_integrations_tenant_updated (tenant_id, updated_at, speech_integration_id)`
- `UNIQUE uq_platform_speech_integrations_code (tenant_id, integration_code)`

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
