from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool
from backend.platform.security.secrets import encrypt_secret

from .store import (
    DEFAULT_SYSTEM_PARAMS,
    MASKED_SECRET,
    _connection_for_output,
    _connection_secret,
    _ensure_unique_model_name,
    _mask_model_secret,
    _mask_speech_secret,
    _normalize_data_connection,
    _normalize_model,
    _normalize_speech_integration,
    _normalize_system_param,
    account_system_config_scope,
    system_config_external_code,
    system_config_storage_code,
    system_config_storage_prefix,
    system_config_storage_tenant,
)


class PostgreSQLSystemConfigStore:
    """Production integrations, versioned connections, datasets and runtime parameters."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def list_models(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, system_config_storage_tenant(tenant_id))
            prefix = system_config_storage_prefix(tenant_id)
            with connection.cursor() as cursor:
                if prefix:
                    cursor.execute(
                        self._model_select() + " WHERE m.tenant_id = %s AND m.integration_code LIKE %s ORDER BY m.integration_code",
                        (tenant_key, f"{prefix}%"),
                    )
                else:
                    cursor.execute(self._model_select() + " WHERE m.tenant_id = %s ORDER BY m.integration_code", (tenant_key,))
                rows = cursor.fetchall()
        return [self._model_from_row_for_scope(row, tenant_id, reveal_secret) for row in rows]

    def list_models_owned_by(self, user_id: str, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, Any]]:
        return _dedupe(self.list_models(account_system_config_scope(user_id), reveal_secret=reveal_secret))

    def get_model(self, tenant_id: str, model_id: str, reveal_secret: bool = False) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, system_config_storage_tenant(tenant_id))
            stored_model_id = system_config_storage_code(tenant_id, model_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._model_select() + " WHERE m.tenant_id = %s AND m.integration_code = %s",
                    (tenant_key, stored_model_id),
                )
                row = cursor.fetchone()
        return self._model_from_row_for_scope(row, tenant_id, reveal_secret) if row else None

    def upsert_model(self, tenant_id: str, model: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        normalized = _normalize_model(model)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, system_config_storage_tenant(tenant_id))
            stored_model_id = system_config_storage_code(tenant_id, normalized["id"])
            prefix = system_config_storage_prefix(tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, updated_by, required=False) if updated_by else None
            existing = self._credential(connection, "platform_model_integrations", "integration_code", tenant_key, stored_model_id)
            with connection.cursor() as cursor:
                if prefix:
                    cursor.execute(
                        self._model_select() + " WHERE m.tenant_id = %s AND m.integration_code LIKE %s",
                        (tenant_key, f"{prefix}%"),
                    )
                else:
                    cursor.execute(self._model_select() + " WHERE m.tenant_id = %s", (tenant_key,))
                _ensure_unique_model_name(
                    (self._model_from_row_for_scope(row, tenant_id, reveal_secret=False) for row in cursor.fetchall()),
                    normalized,
                )
            if normalized["value"] == MASKED_SECRET:
                if existing is None:
                    raise ValueError("model_secret_required")
                credential = existing
            else:
                credential = encrypt_secret(normalized["value"]).encode("utf-8")
            enabled = list(normalized["enabledModels"])
            capabilities = {
                "availableModels": list(normalized["availableModels"]),
                "enabledModels": enabled,
                "applicationModule": normalized["applicationModule"],
            }
            test_result = {
                "testStatus": normalized["testStatus"],
                "testMessage": normalized["testMessage"],
                "testResponse": normalized["testResponse"],
            }
            with connection.cursor() as cursor:
                if normalized["applicationModule"] == "memory_extraction":
                    prefix_clause = " AND integration_code LIKE %s" if prefix else ""
                    cursor.execute(
                        f"""
                        UPDATE platform_model_integrations
                        SET capabilities = jsonb_set(
                                COALESCE(capabilities, '{{}}'::jsonb),
                                '{{applicationModule}}',
                                to_jsonb(''::text),
                                true
                            ),
                            updated_at = now(),
                            lock_version = lock_version + 1
                        WHERE tenant_id = %s
                          AND integration_code <> %s
                          AND capabilities ->> 'applicationModule' = %s
                          {prefix_clause}
                        """,
                        (tenant_key, stored_model_id, normalized["applicationModule"], f"{prefix}%")
                        if prefix
                        else (tenant_key, stored_model_id, normalized["applicationModule"]),
                    )
                cursor.execute(
                    """
                    INSERT INTO platform_model_integrations(
                        tenant_id, integration_code, display_name, provider, model_name,
                        base_url, credential_ciphertext, capabilities, test_result,
                        status, last_test_at, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                        %s, CASE WHEN %s <> '' THEN %s::timestamptz END, %s
                    )
                    ON CONFLICT (tenant_id, integration_code) DO UPDATE SET
                        display_name = EXCLUDED.display_name, provider = EXCLUDED.provider,
                        model_name = EXCLUDED.model_name, base_url = EXCLUDED.base_url,
                        credential_ciphertext = EXCLUDED.credential_ciphertext,
                        capabilities = EXCLUDED.capabilities, test_result = EXCLUDED.test_result,
                        status = EXCLUDED.status, last_test_at = EXCLUDED.last_test_at,
                        updated_at = now(), lock_version = platform_model_integrations.lock_version + 1
                    """,
                    (
                        tenant_key, stored_model_id, normalized["name"], normalized["modelName"],
                        (enabled or normalized["availableModels"] or [normalized["name"]])[0],
                        normalized["key"], credential, _json(capabilities), _json(test_result),
                        normalized["status"], normalized["lastTestedAt"], normalized["lastTestedAt"], actor_key,
                    ),
                )
        return _mask_model_secret(normalized)

    def delete_model(self, tenant_id: str, model_id: str) -> bool:
        return self._disable(
            system_config_storage_tenant(tenant_id),
            "platform_model_integrations",
            "integration_code",
            system_config_storage_code(tenant_id, model_id),
        )

    def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, str]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, system_config_storage_tenant(tenant_id))
            prefix = system_config_storage_prefix(tenant_id)
            with connection.cursor() as cursor:
                if prefix:
                    cursor.execute(
                        self._speech_select() + " WHERE s.tenant_id = %s AND s.integration_code LIKE %s ORDER BY s.integration_code",
                        (tenant_key, f"{prefix}%"),
                    )
                else:
                    cursor.execute(self._speech_select() + " WHERE s.tenant_id = %s ORDER BY s.integration_code", (tenant_key,))
                rows = cursor.fetchall()
        return [self._speech_from_row_for_scope(row, tenant_id, reveal_secret) for row in rows]

    def list_speech_integrations_owned_by(self, user_id: str, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, str]]:
        return _dedupe(self.list_speech_integrations(account_system_config_scope(user_id), reveal_secret=reveal_secret))

    def get_speech_integration(self, tenant_id: str, integration_id: str, reveal_secret: bool = False) -> dict[str, str] | None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, system_config_storage_tenant(tenant_id))
            stored_integration_id = system_config_storage_code(tenant_id, integration_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._speech_select() + " WHERE s.tenant_id = %s AND s.integration_code = %s",
                    (tenant_key, stored_integration_id),
                )
                row = cursor.fetchone()
        return self._speech_from_row_for_scope(row, tenant_id, reveal_secret) if row else None

    def upsert_speech_integration(self, tenant_id: str, integration: dict[str, Any], updated_by: str | None = None) -> dict[str, str]:
        normalized = _normalize_speech_integration(integration)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, system_config_storage_tenant(tenant_id))
            stored_integration_id = system_config_storage_code(tenant_id, normalized["id"])
            actor_key = PostgreSQLIdentityResolver.user_id(connection, updated_by, required=False) if updated_by else None
            existing = self._credential(connection, "platform_speech_integrations", "integration_code", tenant_key, stored_integration_id)
            if normalized["apiKey"] == MASKED_SECRET:
                if existing is None:
                    raise ValueError("speech_secret_required")
                credential = existing
            else:
                credential = encrypt_secret(normalized["apiKey"]).encode("utf-8")
            test_result = {
                "testStatus": normalized["testStatus"],
                "testMessage": normalized["testMessage"],
                "testResponse": normalized["testResponse"],
                "applicationModule": normalized["applicationModule"],
            }
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_speech_integrations(
                        tenant_id, integration_code, display_name, source_name, provider,
                        capability, endpoint, credential_ciphertext, test_result,
                        status, last_test_at, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'asr', %s, %s, %s::jsonb,
                        %s, CASE WHEN %s <> '' THEN %s::timestamptz END, %s
                    )
                    ON CONFLICT (tenant_id, integration_code) DO UPDATE SET
                        display_name = EXCLUDED.display_name, source_name = EXCLUDED.source_name,
                        provider = EXCLUDED.provider, endpoint = EXCLUDED.endpoint,
                        credential_ciphertext = EXCLUDED.credential_ciphertext,
                        test_result = EXCLUDED.test_result, status = EXCLUDED.status,
                        last_test_at = EXCLUDED.last_test_at, updated_at = now(),
                        lock_version = platform_speech_integrations.lock_version + 1
                    """,
                    (
                        tenant_key, stored_integration_id, normalized["name"], normalized["source"],
                        normalized["provider"], normalized["apiBase"], credential,
                        _json(test_result), normalized["status"], normalized["lastTestedAt"],
                        normalized["lastTestedAt"], actor_key,
                    ),
                )
        return _mask_speech_secret(normalized)

    def delete_speech_integration(self, tenant_id: str, integration_id: str) -> bool:
        return self._disable(
            system_config_storage_tenant(tenant_id),
            "platform_speech_integrations",
            "integration_code",
            system_config_storage_code(tenant_id, integration_id),
        )

    def list_data_connections(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            rows = self._connection_rows(connection, "c.tenant_id = %s", (tenant_key,))
        return [self._connection_from_row(row, reveal_secret) for row in rows]

    def list_data_connections_owned_by(self, user_id: str, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id, required=False)
            rows = self._connection_rows(connection, "c.tenant_id = %s OR c.created_by = %s", (tenant_key, user_key))
        return _dedupe([self._connection_from_row(row, reveal_secret) for row in rows])

    def get_data_connection(self, tenant_id: str, connection_id: str, reveal_secret: bool = False) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            rows = self._connection_rows(
                connection, "c.tenant_id = %s AND c.connection_code = %s", (tenant_key, connection_id)
            )
        return self._connection_from_row(rows[0], reveal_secret) if rows else None

    def upsert_data_connection(self, tenant_id: str, connection: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        normalized = _normalize_data_connection(connection)
        if normalized["mockEnabled"]:
            raise ValueError("mock_data_connection_forbidden_in_production")
        with self._transaction() as db:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(db, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(db, updated_by, required=False) if updated_by else None
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.connection_id, c.current_version_no, v.credential_ciphertext
                    FROM platform_data_connections c
                    LEFT JOIN platform_connection_versions v
                      ON v.connection_id = c.connection_id AND v.version_no = c.current_version_no
                    WHERE c.tenant_id = %s AND c.connection_code = %s
                    FOR UPDATE OF c
                    """,
                    (tenant_key, normalized["id"]),
                )
                existing = cursor.fetchone()
            secret = _connection_secret(normalized)
            if secret == MASKED_SECRET:
                credential = _value(existing, "credential_ciphertext", 2) if existing else None
                if credential is None:
                    raise ValueError("connection_secret_required")
            else:
                credential = encrypt_secret(secret).encode("utf-8")
            version_no = int(_value(existing, "current_version_no", 1) or 0) + 1 if existing else 1
            source_type = _source_type(normalized["sourceType"])
            status = "verified" if normalized["status"] == "verified" and normalized["testStatus"] == "verified" else "disabled" if not normalized["enabled"] else "draft"
            validation_status = "verified" if status == "verified" else "pending"
            endpoint_config = {
                key: normalized[key]
                for key in (
                    "institution", "sourceName", "sourceType", "apiUrl", "account",
                    "loginUrl", "queryPageUrl", "metadataPageUrl", "spaceId",
                    "dataset", "defaultDatabase", "enabled", "mockEnabled", "lastTestedAt",
                    "testStatus", "testMessage", "status",
                )
            }
            endpoint_config["hasToken"] = bool(normalized.get("token"))
            config_hash = hashlib.sha256(
                (_json(endpoint_config) + ":" + hashlib.sha256(bytes(credential)).hexdigest()).encode("utf-8")
            ).hexdigest()
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_data_connections(
                        tenant_id, connection_code, connection_name, source_type,
                        current_version_no, status, last_verified_at, health_summary, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s = 'verified' THEN now() END, %s::jsonb, %s
                    )
                    ON CONFLICT (tenant_id, connection_code) DO UPDATE SET
                        connection_name = EXCLUDED.connection_name, source_type = EXCLUDED.source_type,
                        current_version_no = EXCLUDED.current_version_no, status = EXCLUDED.status,
                        last_verified_at = EXCLUDED.last_verified_at,
                        health_summary = EXCLUDED.health_summary, updated_at = now(),
                        lock_version = platform_data_connections.lock_version + 1
                    RETURNING connection_id
                    """,
                    (
                        tenant_key, normalized["id"], normalized["sourceName"], source_type,
                        version_no, status, status,
                        _json({"testStatus": normalized["testStatus"], "testMessage": normalized["testMessage"]}),
                        actor_key,
                    ),
                )
                connection_key = _value(cursor.fetchone(), "connection_id", 0)
                cursor.execute(
                    """
                    INSERT INTO platform_connection_versions(
                        tenant_id, connection_id, version_no, endpoint_config,
                        credential_ciphertext, config_hash, validation_status,
                        validation_result, verified_at, published_at, created_by
                    ) VALUES (
                        %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb,
                        CASE WHEN %s = 'verified' THEN now() END,
                        CASE WHEN %s = 'verified' THEN now() END, %s
                    )
                    """,
                    (
                        tenant_key, connection_key, version_no, _json(endpoint_config), credential,
                        config_hash, validation_status,
                        _json({"testStatus": normalized["testStatus"], "testMessage": normalized["testMessage"]}),
                        validation_status, validation_status, actor_key,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO platform_datasets(
                        tenant_id, connection_id, dataset_code, dataset_name,
                        physical_locator, dataset_type, status, created_by
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    ON CONFLICT (tenant_id, dataset_code) DO UPDATE SET
                        connection_id = EXCLUDED.connection_id, dataset_name = EXCLUDED.dataset_name,
                        physical_locator = EXCLUDED.physical_locator, dataset_type = EXCLUDED.dataset_type,
                        status = EXCLUDED.status, updated_at = now(),
                        lock_version = platform_datasets.lock_version + 1
                    """,
                    (
                        tenant_key, connection_key, normalized["dataset"], normalized["dataset"],
                        _json({"database": normalized["defaultDatabase"], "dataset": normalized["dataset"]}),
                        _dataset_type(source_type), "active" if status == "verified" else "draft", actor_key,
                    ),
                )
        return _connection_for_output(normalized, reveal_secret=False)

    def delete_data_connection(self, tenant_id: str, connection_id: str) -> bool:
        return self._disable(tenant_id, "platform_data_connections", "connection_code", connection_id)

    def list_system_params(self, tenant_id: str) -> list[dict[str, str]]:
        merged = {item["id"]: dict(item) for item in DEFAULT_SYSTEM_PARAMS}
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT param_key, param_value, description
                    FROM platform_system_data_params WHERE tenant_id = %s ORDER BY param_key
                    """,
                    (tenant_key,),
                )
                rows = cursor.fetchall()
        for row in rows:
            key = str(_value(row, "param_key", 0))
            value = _json_value(_value(row, "param_value", 1), "")
            default = merged.get(key, {"id": key, "name": key, "category": "system"})
            merged[key] = {
                **default,
                "value": str(value).lower() if isinstance(value, bool) else str(value),
                "description": str(_value(row, "description", 2) or default.get("description", "")),
            }
        return sorted(merged.values(), key=lambda item: item.get("id", ""))

    def get_system_param_value(self, tenant_id: str, param_id: str) -> str:
        item = next((item for item in self.list_system_params(tenant_id) if item["id"] == param_id), None)
        if item is None:
            raise KeyError(f"unknown_system_param:{param_id}")
        return str(item["value"])

    def upsert_system_param(self, tenant_id: str, param: dict[str, Any], updated_by: str | None = None) -> dict[str, str]:
        normalized = _normalize_system_param(param)
        value_type, typed_value = _typed_param_value(normalized["value"])
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, updated_by, required=False) if updated_by else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_system_data_params(
                        tenant_id, param_key, value_type, param_value, description, created_by
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (tenant_id, param_key) DO UPDATE SET
                        value_type = EXCLUDED.value_type, param_value = EXCLUDED.param_value,
                        description = EXCLUDED.description, effective_at = now(), updated_at = now(),
                        lock_version = platform_system_data_params.lock_version + 1
                    """,
                    (
                        tenant_key, normalized["id"], value_type, _json(typed_value),
                        normalized["description"], actor_key,
                    ),
                )
        return normalized

    @staticmethod
    def _model_select() -> str:
        return """
            SELECT m.integration_code, m.display_name, m.provider, m.model_name, m.base_url,
                   m.credential_ciphertext, m.capabilities, m.test_result, m.status, m.last_test_at
            FROM platform_model_integrations m
        """

    @staticmethod
    def _speech_select() -> str:
        return """
            SELECT s.integration_code, s.display_name, s.provider, s.source_name, s.endpoint,
                   s.credential_ciphertext, s.test_result, s.status, s.last_test_at
            FROM platform_speech_integrations s
        """

    @staticmethod
    def _model_from_row(row: Any, reveal_secret: bool) -> dict[str, Any]:
        capabilities = _json_value(_value(row, "capabilities", 6), {})
        test = _json_value(_value(row, "test_result", 7), {})
        credential = _cipher_text(_value(row, "credential_ciphertext", 5))
        item = {
            "id": str(_value(row, "integration_code", 0)),
            "name": str(_value(row, "display_name", 1)),
            "modelName": str(_value(row, "provider", 2)),
            "key": str(_value(row, "base_url", 4)),
            "value": credential,
            "availableModels": capabilities.get("availableModels", []),
            "enabledModels": capabilities.get("enabledModels", []),
            "applicationModule": capabilities.get("applicationModule", ""),
            "lastTestedAt": _iso(_value(row, "last_test_at", 9)),
            "testStatus": test.get("testStatus", "untested"),
            "testMessage": test.get("testMessage", ""),
            "testResponse": test.get("testResponse", ""),
            "status": str(_value(row, "status", 8)),
        }
        if reveal_secret:
            from backend.platform.security.secrets import decrypt_secret
            item["value"] = decrypt_secret(credential) if credential else ""
            return item
        return _mask_model_secret(item)

    @classmethod
    def _model_from_row_for_scope(cls, row: Any, scope: str, reveal_secret: bool) -> dict[str, Any]:
        item = cls._model_from_row(row, reveal_secret)
        item["id"] = system_config_external_code(scope, str(item.get("id") or ""))
        return item

    @staticmethod
    def _speech_from_row(row: Any, reveal_secret: bool) -> dict[str, str]:
        test = _json_value(_value(row, "test_result", 6), {})
        credential = _cipher_text(_value(row, "credential_ciphertext", 5))
        item = {
            "id": str(_value(row, "integration_code", 0)),
            "name": str(_value(row, "display_name", 1)),
            "provider": str(_value(row, "provider", 2)),
            "source": str(_value(row, "source_name", 3)),
            "apiBase": str(_value(row, "endpoint", 4)),
            "apiKey": credential,
            "applicationModule": test.get("applicationModule"),
            "lastTestedAt": _iso(_value(row, "last_test_at", 8)),
            "testStatus": str(test.get("testStatus", "untested")),
            "testMessage": str(test.get("testMessage", "")),
            "testResponse": str(test.get("testResponse", "")),
            "status": str(_value(row, "status", 7)),
        }
        if reveal_secret:
            from backend.platform.security.secrets import decrypt_secret
            item["apiKey"] = decrypt_secret(credential) if credential else ""
            return item
        return _mask_speech_secret(item)

    @classmethod
    def _speech_from_row_for_scope(cls, row: Any, scope: str, reveal_secret: bool) -> dict[str, str]:
        item = cls._speech_from_row(row, reveal_secret)
        item["id"] = system_config_external_code(scope, str(item.get("id") or ""))
        return item

    @staticmethod
    def _connection_rows(connection: Any, where: str, params: tuple[Any, ...]) -> list[Any]:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT c.connection_code, v.endpoint_config, v.credential_ciphertext,
                       c.status, c.connection_name, c.source_type
                FROM platform_data_connections c
                JOIN platform_connection_versions v
                  ON v.connection_id = c.connection_id AND v.version_no = c.current_version_no
                WHERE {where}
                ORDER BY c.connection_code
                """,
                params,
            )
            return list(cursor.fetchall())

    @staticmethod
    def _connection_from_row(row: Any, reveal_secret: bool) -> dict[str, Any]:
        config = dict(_json_value(_value(row, "endpoint_config", 1), {}))
        has_token = bool(config.pop("hasToken", False))
        encrypted = _cipher_text(_value(row, "credential_ciphertext", 2))
        item = {
            "id": str(_value(row, "connection_code", 0)),
            "institution": str(config.get("institution") or _value(row, "connection_name", 4)),
            "sourceName": str(config.get("sourceName") or _value(row, "connection_name", 4)),
            "sourceType": str(config.get("sourceType") or _value(row, "source_type", 5)),
            "apiUrl": str(config.get("apiUrl") or ""),
            "loginUrl": str(config.get("loginUrl") or ""),
            "queryPageUrl": str(config.get("queryPageUrl") or ""),
            "metadataPageUrl": str(config.get("metadataPageUrl") or ""),
            "spaceId": str(config.get("spaceId") or ""),
            "account": str(config.get("account") or ""),
            "password": "" if has_token else encrypted,
            "token": encrypted if has_token else "",
            "dataset": str(config.get("dataset") or ""),
            "defaultDatabase": str(config.get("defaultDatabase") or config.get("dataset") or ""),
            "enabled": bool(config.get("enabled", True)),
            "mockEnabled": False,
            "lastTestedAt": str(config.get("lastTestedAt") or ""),
            "testStatus": str(config.get("testStatus") or "untested"),
            "testMessage": str(config.get("testMessage") or ""),
            "status": str(_value(row, "status", 3)),
        }
        return _connection_for_output(item, reveal_secret=reveal_secret)

    @staticmethod
    def _credential(connection: Any, table: str, code_field: str, tenant_key: Any, code: str) -> bytes | None:
        if table not in {"platform_model_integrations", "platform_speech_integrations"}:
            raise ValueError("credential_table_not_allowed")
        if code_field != "integration_code":
            raise ValueError("credential_code_field_not_allowed")
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT credential_ciphertext FROM {table} WHERE tenant_id = %s AND {code_field} = %s",
                (tenant_key, code),
            )
            row = cursor.fetchone()
        return _value(row, "credential_ciphertext", 0) if row else None

    def _disable(self, tenant_id: str, table: str, code_field: str, code: str) -> bool:
        allowed = {
            ("platform_model_integrations", "integration_code"),
            ("platform_speech_integrations", "integration_code"),
            ("platform_data_connections", "connection_code"),
        }
        if (table, code_field) not in allowed:
            raise ValueError("disable_target_not_allowed")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {table} SET status = 'disabled', updated_at = now(), lock_version = lock_version + 1 WHERE tenant_id = %s AND {code_field} = %s AND status <> 'disabled'",
                    (tenant_key, code),
                )
                return cursor.rowcount > 0

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _source_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if "doris" in text:
        return "doris"
    if "hive" in text:
        return "hive"
    if "postgres" in text:
        return "postgresql"
    if "csv" in text:
        return "csv"
    if "oss" in text or "s3" in text or "对象" in text:
        return "object_storage"
    if "api" in text:
        return "api"
    return "qbi"


def _dataset_type(source_type: str) -> str:
    if source_type in {"csv", "object_storage"}:
        return "file_collection"
    if source_type in {"api", "qbi"}:
        return "api"
    return "semantic"


def _typed_param_value(value: str) -> tuple[str, Any]:
    text = str(value).strip()
    if text.lower() in {"true", "false"}:
        return "boolean", text.lower() == "true"
    try:
        return "number", int(text)
    except ValueError:
        return "string", text


def _cipher_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({str(item.get("id")): item for item in items}.values())


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
