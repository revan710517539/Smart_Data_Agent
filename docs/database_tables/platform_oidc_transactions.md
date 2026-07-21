# `platform_oidc_transactions`

- 领域：身份权限
- 用途：OIDC Authorization Code + PKCE 登录的一次性事务。
- 生产数据库：PostgreSQL

## 字段结构

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `oidc_transaction_id` | `UUID` | PRIMARY KEY DEFAULT gen_random_uuid() | 服务端生成的稳定主键。 |
| `transaction_key` | `VARCHAR(100)` | NOT NULL UNIQUE | 返回给登录流程的不可猜测事务标识。 |
| `state_hash` | `CHAR(64)` | NOT NULL UNIQUE | OIDC state 的 SHA-256；不保存 state 明文。 |
| `nonce` | `VARCHAR(200)` | NOT NULL | 校验 ID Token 重放的 nonce。 |
| `code_verifier_ciphertext` | `TEXT` | NOT NULL | 使用平台密钥加密的 PKCE code verifier。 |
| `redirect_uri` | `TEXT` | NOT NULL | 已校验的回调地址。 |
| `expires_at` | `TIMESTAMPTZ` | NOT NULL | 事务到期时间。 |
| `consumed_at` | `TIMESTAMPTZ` | 无 | 原子消费时间；非空后禁止重放。 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 创建时间，统一 UTC。 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT now() | 最后更新时间，统一 UTC。 |
| `lock_version` | `BIGINT` | NOT NULL DEFAULT 0 CHECK (lock_version >= 0) | 乐观锁版本。 |

## 索引

- `idx_platform_oidc_transactions_expiry (expires_at, consumed_at)`

## 设计说明

- state 仅保存摘要；code verifier 仅保存密文；消费使用条件更新保证一次性。

## 结构来源

本文件由 `backend/platform/database/schema_catalog.py` 自动生成；修改表结构时先修改 catalog，再重新生成 DDL 和文档。
