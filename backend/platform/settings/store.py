from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from backend.platform.storage import connect_sqlite
from typing import Any

from backend.platform.security.secrets import decrypt_secret, encrypt_secret
from backend.platform.crawler_engine.url_identity import build_crawler_url_identity, infer_crawler_mode
from .model_modules import normalize_application_module


MODEL_FIELDS = (
    "id",
    "name",
    "modelName",
    "key",
    "value",
    "applicationModule",
    "availableModels",
    "enabledModels",
    "lastTestedAt",
    "testStatus",
    "testMessage",
    "testResponse",
    "status",
)
SPEECH_INTEGRATION_FIELDS = (
    "id",
    "name",
    "provider",
    "source",
    "apiBase",
    "apiKey",
    "applicationModule",
    "lastTestedAt",
    "testStatus",
    "testMessage",
    "testResponse",
    "status",
)
DATA_CONNECTION_FIELDS = (
    "id",
    "institution",
    "sourceName",
    "sourceType",
    "apiUrl",
    "loginUrl",
    "queryPageUrl",
    "metadataPageUrl",
    "spaceId",
    "crawlerMode",
    "crawlerKey",
    "crawlerProfileId",
    "crawlerConfig",
    "account",
    "password",
    "token",
    "dataset",
    "defaultDatabase",
    "enabled",
    "mockEnabled",
    "lastTestedAt",
    "testStatus",
    "testMessage",
    "status",
)
SYSTEM_PARAM_FIELDS = ("id", "name", "value", "category", "description")
MASKED_SECRET = "******"
ACCOUNT_CONFIG_SCOPE_PREFIX = "account:"

DEFAULT_SYSTEM_PARAMS = [
    {"id": "acquisition_max_rows", "name": "单次采集最大行数", "value": "50000", "category": "data", "description": "数据获取任务单次允许写入的最大行数。"},
    {"id": "acquisition_freshness_sla_seconds", "name": "默认新鲜度阈值（秒）", "value": "86400", "category": "data", "description": "采集任务未单独设置时使用的新鲜度 SLA。"},
    {"id": "analysis_user_concurrency_limit", "name": "AI分析并发上限", "value": "2", "category": "system", "description": "单用户异步智能分析任务并发上限。"},
    {"id": "analysis_deadline_seconds", "name": "AI分析最长执行时间（秒）", "value": "900", "category": "system", "description": "Worker 强制终止单次分析的 deadline。"},
    {"id": "report_retention_days", "name": "报告保留期限（天）", "value": "365", "category": "data", "description": "周报、分析快照和导出产物的默认保留周期。"},
]

SYSTEM_PARAM_INTEGER_RANGES = {
    "acquisition_max_rows": (1, 500_000),
    "acquisition_freshness_sla_seconds": (60, 31_536_000),
    "analysis_user_concurrency_limit": (1, 10),
    "analysis_deadline_seconds": (30, 3600),
    "report_retention_days": (1, 3650),
}


def account_system_config_scope(user_id: str) -> str:
    normalized = str(user_id or "").strip()
    return f"{ACCOUNT_CONFIG_SCOPE_PREFIX}{normalized or 'anonymous'}"


class InMemorySystemConfigStore:
    def __init__(self) -> None:
        self._models_by_tenant: dict[str, dict[str, dict[str, str]]] = {}
        self._speech_by_tenant: dict[str, dict[str, dict[str, str]]] = {}
        self._connections_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
        self._system_params_by_tenant: dict[str, dict[str, dict[str, str]]] = {}

    def list_models(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, Any]]:
        models = self._models_by_tenant.get(tenant_id, {})
        items = sorted(models.values(), key=lambda item: item.get("id", ""))
        return [dict(item) if reveal_secret else _mask_model_secret(item) for item in items]

    def list_models_owned_by(
        self,
        user_id: str,
        tenant_id: str,
        reveal_secret: bool = False,
    ) -> list[dict[str, Any]]:
        scope = account_system_config_scope(user_id)
        collected: dict[str, dict[str, Any]] = {}
        for source_tenant_id in (scope, tenant_id):
            for item in self._models_by_tenant.get(source_tenant_id, {}).values():
                collected.setdefault(str(item.get("id") or ""), item)
        items = sorted(collected.values(), key=lambda item: item.get("id", ""))
        return [dict(item) if reveal_secret else _mask_model_secret(item) for item in items]

    def get_model(self, tenant_id: str, model_id: str, reveal_secret: bool = False) -> dict[str, Any] | None:
        model = self._models_by_tenant.get(tenant_id, {}).get(model_id)
        if not model:
            return None
        return dict(model) if reveal_secret else _mask_model_secret(model)

    def upsert_model(self, tenant_id: str, model: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        normalized = _normalize_model(model)
        tenant_models = self._models_by_tenant.setdefault(tenant_id, {})
        existing = tenant_models.get(normalized["id"])
        _ensure_unique_model_name(tenant_models.values(), normalized)
        if normalized["value"] == MASKED_SECRET and existing:
            normalized["value"] = str(existing.get("value") or "")
        _release_model_module_binding(tenant_models.values(), normalized)
        tenant_models[normalized["id"]] = normalized
        return _mask_model_secret(normalized)

    def delete_model(self, tenant_id: str, model_id: str) -> bool:
        return self._models_by_tenant.setdefault(tenant_id, {}).pop(model_id, None) is not None

    def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, str]]:
        integrations = self._speech_by_tenant.get(tenant_id, {})
        items = sorted(integrations.values(), key=lambda item: item.get("id", ""))
        return [dict(item) if reveal_secret else _mask_speech_secret(item) for item in items]

    def list_speech_integrations_owned_by(
        self,
        user_id: str,
        tenant_id: str,
        reveal_secret: bool = False,
    ) -> list[dict[str, str]]:
        scope = account_system_config_scope(user_id)
        collected: dict[str, dict[str, Any]] = {}
        for source_tenant_id in (scope, tenant_id):
            for item in self._speech_by_tenant.get(source_tenant_id, {}).values():
                collected.setdefault(str(item.get("id") or ""), item)
        items = sorted(collected.values(), key=lambda item: item.get("id", ""))
        return [dict(item) if reveal_secret else _mask_speech_secret(item) for item in items]

    def get_speech_integration(self, tenant_id: str, integration_id: str, reveal_secret: bool = False) -> dict[str, str] | None:
        integration = self._speech_by_tenant.get(tenant_id, {}).get(integration_id)
        if not integration:
            return None
        return dict(integration) if reveal_secret else _mask_speech_secret(integration)

    def upsert_speech_integration(self, tenant_id: str, integration: dict[str, Any], updated_by: str | None = None) -> dict[str, str]:
        normalized = _normalize_speech_integration(integration)
        existing = self._speech_by_tenant.get(tenant_id, {}).get(normalized["id"])
        if normalized["apiKey"] == MASKED_SECRET and existing:
            normalized["apiKey"] = str(existing.get("apiKey") or "")
        self._speech_by_tenant.setdefault(tenant_id, {})[normalized["id"]] = normalized
        return _mask_speech_secret(normalized)

    def delete_speech_integration(self, tenant_id: str, integration_id: str) -> bool:
        return self._speech_by_tenant.setdefault(tenant_id, {}).pop(integration_id, None) is not None

    def list_data_connections(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, str]]:
        connections = self._connections_by_tenant.get(tenant_id, {})
        return sorted(
            (_connection_for_output(connection, reveal_secret=reveal_secret) for connection in connections.values()),
            key=lambda item: item.get("id", ""),
        )

    def list_data_connections_owned_by(
        self,
        user_id: str,
        tenant_id: str,
        reveal_secret: bool = False,
    ) -> list[dict[str, str]]:
        scope = account_system_config_scope(user_id)
        collected: dict[str, dict[str, Any]] = {}
        for source_tenant_id in (scope, tenant_id):
            for item in self._connections_by_tenant.get(source_tenant_id, {}).values():
                collected.setdefault(str(item.get("id") or ""), item)
        return sorted(
            (_connection_for_output(connection, reveal_secret=reveal_secret) for connection in collected.values()),
            key=lambda item: item.get("id", ""),
        )

    def get_data_connection(self, tenant_id: str, connection_id: str, reveal_secret: bool = False) -> dict[str, str] | None:
        connection = self._connections_by_tenant.get(tenant_id, {}).get(connection_id)
        return _connection_for_output(connection, reveal_secret=reveal_secret) if connection else None

    def upsert_data_connection(
        self,
        tenant_id: str,
        connection: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, str]:
        candidate = dict(connection)
        existing = self._connections_by_tenant.get(tenant_id, {}).get(str(candidate.get("id") or ""))
        if existing and "crawlerConfig" not in candidate:
            candidate["crawlerConfig"] = dict(existing.get("crawlerConfig") or {})
        normalized = _normalize_data_connection(candidate)
        secret = _connection_secret(normalized)
        if secret == MASKED_SECRET and existing:
            normalized["password"] = str(existing.get("password") or "")
            normalized["token"] = str(existing.get("token") or "")
        else:
            normalized["password"] = encrypt_secret(secret)
        self._connections_by_tenant.setdefault(tenant_id, {})[normalized["id"]] = normalized
        return _mask_connection_secret(normalized)

    def delete_data_connection(self, tenant_id: str, connection_id: str) -> bool:
        return self._connections_by_tenant.setdefault(tenant_id, {}).pop(connection_id, None) is not None

    def list_system_params(self, tenant_id: str) -> list[dict[str, str]]:
        params = self._system_params_by_tenant.get(tenant_id, {})
        merged = {item["id"]: dict(item) for item in DEFAULT_SYSTEM_PARAMS}
        merged.update({key: dict(value) for key, value in params.items()})
        return sorted(merged.values(), key=lambda item: item.get("id", ""))

    def get_system_param_value(self, tenant_id: str, param_id: str) -> str:
        item = next((item for item in self.list_system_params(tenant_id) if item["id"] == param_id), None)
        if item is None:
            raise KeyError(f"unknown_system_param:{param_id}")
        return str(item["value"])

    def upsert_system_param(self, tenant_id: str, param: dict[str, Any], updated_by: str | None = None) -> dict[str, str]:
        normalized = _normalize_system_param(param)
        self._system_params_by_tenant.setdefault(tenant_id, {})[normalized["id"]] = normalized
        return normalized


class SQLiteSystemConfigStore:
    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_model_integrations (
                tenant_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, model_id)
            );

            CREATE TABLE IF NOT EXISTS platform_speech_integrations (
                tenant_id TEXT NOT NULL,
                integration_id TEXT NOT NULL,
                integration_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, integration_id)
            );

            CREATE TABLE IF NOT EXISTS platform_data_connections (
                tenant_id TEXT NOT NULL,
                connection_id TEXT NOT NULL,
                institution TEXT NOT NULL,
                account TEXT NOT NULL,
                secret_value TEXT NOT NULL,
                dataset TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'connected',
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, connection_id)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_model_integrations_tenant
                ON platform_model_integrations(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_platform_speech_integrations_tenant
                ON platform_speech_integrations(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_platform_data_connections_tenant
                ON platform_data_connections(tenant_id);

            CREATE TABLE IF NOT EXISTS platform_system_data_params (
                tenant_id TEXT NOT NULL,
                param_id TEXT NOT NULL,
                param_name TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, param_id)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_system_data_params_tenant
                ON platform_system_data_params(tenant_id);
            """
        )
        _ensure_column(self._conn, "platform_data_connections", "payload", "TEXT NOT NULL DEFAULT '{}'")
        self._conn.commit()

    def list_models(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT payload
            FROM platform_model_integrations
            WHERE tenant_id = ?
            ORDER BY model_id
            """,
            (tenant_id,),
        ).fetchall()
        items = [_model_from_payload(json.loads(row["payload"]), reveal_secret=reveal_secret) for row in rows]
        return items if reveal_secret else [_mask_model_secret(item) for item in items]

    def list_models_owned_by(
        self,
        user_id: str,
        tenant_id: str,
        reveal_secret: bool = False,
    ) -> list[dict[str, Any]]:
        account_scope = account_system_config_scope(user_id)
        rows = self._conn.execute(
            """
            SELECT tenant_id, model_id, payload, created_by, updated_by, updated_at
            FROM platform_model_integrations
            WHERE tenant_id IN (?, ?)
               OR created_by = ?
               OR updated_by = ?
            ORDER BY
                CASE
                    WHEN tenant_id = ? THEN 0
                    WHEN tenant_id = ? THEN 1
                    ELSE 2
                END,
                updated_at DESC,
                model_id
            """,
            (account_scope, tenant_id, user_id, user_id, account_scope, tenant_id),
        ).fetchall()
        collected: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = _model_from_payload(json.loads(row["payload"] or "{}"), reveal_secret=reveal_secret)
            if item["id"]:
                collected.setdefault(item["id"], item)
        items = list(collected.values())
        return items if reveal_secret else [_mask_model_secret(item) for item in items]

    def get_model(self, tenant_id: str, model_id: str, reveal_secret: bool = False) -> dict[str, Any] | None:
        row = self._model_row(tenant_id, model_id)
        if row is None:
            return None
        model = _model_from_payload(json.loads(row["payload"] or "{}"), reveal_secret=reveal_secret)
        return model if reveal_secret else _mask_model_secret(model)

    def upsert_model(self, tenant_id: str, model: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        normalized = _normalize_model(model)
        existing = self._model_row(tenant_id, normalized["id"])
        existing_rows = self._conn.execute(
            """
            SELECT payload
            FROM platform_model_integrations
            WHERE tenant_id = ?
            """,
            (tenant_id,),
        ).fetchall()
        _ensure_unique_model_name((json.loads(row["payload"] or "{}") for row in existing_rows), normalized)
        if normalized["value"] == MASKED_SECRET and existing:
            existing_payload = json.loads(existing["payload"] or "{}")
            normalized["value"] = str(existing_payload.get("value") or "")
        else:
            normalized["value"] = encrypt_secret(normalized["value"])
        with self._conn:
            if normalized["applicationModule"] == "memory_extraction":
                for row in existing_rows:
                    payload = json.loads(row["payload"] or "{}")
                    if (
                        str(payload.get("id") or "") != normalized["id"]
                        and str(payload.get("applicationModule") or "") == normalized["applicationModule"]
                    ):
                        payload["applicationModule"] = ""
                        self._conn.execute(
                            """
                            UPDATE platform_model_integrations
                            SET payload = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE tenant_id = ? AND model_id = ?
                            """,
                            (json.dumps(payload, ensure_ascii=False, sort_keys=True), updated_by, tenant_id, payload.get("id")),
                        )
            self._conn.execute(
                """
                INSERT INTO platform_model_integrations(
                    tenant_id, model_id, model_name, payload, created_by, updated_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, model_id) DO UPDATE SET
                    model_name = excluded.model_name,
                    payload = excluded.payload,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    normalized["id"],
                    normalized["name"],
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    updated_by,
                    updated_by,
                ),
            )
        return _mask_model_secret(normalized)

    def _model_row(self, tenant_id: str, model_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT payload
            FROM platform_model_integrations
            WHERE tenant_id = ? AND model_id = ?
            """,
            (tenant_id, model_id),
        ).fetchone()

    def delete_model(self, tenant_id: str, model_id: str) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM platform_model_integrations
                WHERE tenant_id = ? AND model_id = ?
                """,
                (tenant_id, model_id),
            )
        return cursor.rowcount > 0

    def list_speech_integrations(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, str]]:
        rows = self._conn.execute(
            """
            SELECT payload
            FROM platform_speech_integrations
            WHERE tenant_id = ?
            ORDER BY integration_id
            """,
            (tenant_id,),
        ).fetchall()
        items = [_speech_from_payload(json.loads(row["payload"]), reveal_secret=reveal_secret) for row in rows]
        return items if reveal_secret else [_mask_speech_secret(item) for item in items]

    def list_speech_integrations_owned_by(
        self,
        user_id: str,
        tenant_id: str,
        reveal_secret: bool = False,
    ) -> list[dict[str, str]]:
        account_scope = account_system_config_scope(user_id)
        rows = self._conn.execute(
            """
            SELECT tenant_id, integration_id, payload, created_by, updated_by, updated_at
            FROM platform_speech_integrations
            WHERE tenant_id IN (?, ?)
               OR created_by = ?
               OR updated_by = ?
            ORDER BY
                CASE
                    WHEN tenant_id = ? THEN 0
                    WHEN tenant_id = ? THEN 1
                    ELSE 2
                END,
                updated_at DESC,
                integration_id
            """,
            (account_scope, tenant_id, user_id, user_id, account_scope, tenant_id),
        ).fetchall()
        collected: dict[str, dict[str, str]] = {}
        for row in rows:
            item = _speech_from_payload(json.loads(row["payload"] or "{}"), reveal_secret=reveal_secret)
            if item["id"]:
                collected.setdefault(item["id"], item)
        items = list(collected.values())
        return items if reveal_secret else [_mask_speech_secret(item) for item in items]

    def get_speech_integration(self, tenant_id: str, integration_id: str, reveal_secret: bool = False) -> dict[str, str] | None:
        row = self._speech_row(tenant_id, integration_id)
        if row is None:
            return None
        item = _speech_from_payload(json.loads(row["payload"] or "{}"), reveal_secret=reveal_secret)
        return item if reveal_secret else _mask_speech_secret(item)

    def upsert_speech_integration(self, tenant_id: str, integration: dict[str, Any], updated_by: str | None = None) -> dict[str, str]:
        normalized = _normalize_speech_integration(integration)
        existing = self._speech_row(tenant_id, normalized["id"])
        if normalized["apiKey"] == MASKED_SECRET and existing:
            existing_payload = json.loads(existing["payload"] or "{}")
            normalized["apiKey"] = str(existing_payload.get("apiKey") or "")
        else:
            normalized["apiKey"] = encrypt_secret(normalized["apiKey"])
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_speech_integrations(
                    tenant_id, integration_id, integration_name, provider, payload, created_by, updated_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, integration_id) DO UPDATE SET
                    integration_name = excluded.integration_name,
                    provider = excluded.provider,
                    payload = excluded.payload,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    normalized["id"],
                    normalized["name"],
                    normalized["provider"],
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    updated_by,
                    updated_by,
                ),
            )
        return _mask_speech_secret(normalized)

    def delete_speech_integration(self, tenant_id: str, integration_id: str) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM platform_speech_integrations
                WHERE tenant_id = ? AND integration_id = ?
                """,
                (tenant_id, integration_id),
            )
        return cursor.rowcount > 0

    def _speech_row(self, tenant_id: str, integration_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT payload
            FROM platform_speech_integrations
            WHERE tenant_id = ? AND integration_id = ?
            """,
            (tenant_id, integration_id),
        ).fetchone()

    def list_data_connections(self, tenant_id: str, reveal_secret: bool = False) -> list[dict[str, str]]:
        rows = self._conn.execute(
            """
            SELECT connection_id, institution, account, secret_value, dataset, status, payload
            FROM platform_data_connections
            WHERE tenant_id = ?
            ORDER BY connection_id
            """,
            (tenant_id,),
        ).fetchall()
        return [_connection_from_row(row, reveal_secret=reveal_secret) for row in rows]

    def list_data_connections_owned_by(
        self,
        user_id: str,
        tenant_id: str,
        reveal_secret: bool = False,
    ) -> list[dict[str, str]]:
        account_scope = account_system_config_scope(user_id)
        rows = self._conn.execute(
            """
            SELECT tenant_id, connection_id, institution, account, secret_value, dataset, status, payload, created_by, updated_by, updated_at
            FROM platform_data_connections
            WHERE tenant_id IN (?, ?)
               OR created_by = ?
               OR updated_by = ?
            ORDER BY
                CASE
                    WHEN tenant_id = ? THEN 0
                    WHEN tenant_id = ? THEN 1
                    ELSE 2
                END,
                updated_at DESC,
                connection_id
            """,
            (account_scope, tenant_id, user_id, user_id, account_scope, tenant_id),
        ).fetchall()
        collected: dict[str, dict[str, str]] = {}
        for row in rows:
            item = _connection_from_row(row, reveal_secret=reveal_secret)
            if item["id"]:
                collected.setdefault(item["id"], item)
        return list(collected.values())

    def get_data_connection(self, tenant_id: str, connection_id: str, reveal_secret: bool = False) -> dict[str, str] | None:
        row = self._conn.execute(
            """
            SELECT connection_id, institution, account, secret_value, dataset, status, payload
            FROM platform_data_connections
            WHERE tenant_id = ? AND connection_id = ?
            """,
            (tenant_id, connection_id),
        ).fetchone()
        if row is None:
            return None
        return _connection_from_row(row, reveal_secret=reveal_secret)

    def upsert_data_connection(
        self,
        tenant_id: str,
        connection: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, str]:
        candidate = dict(connection)
        connection_id = str(candidate.get("id") or "").strip()
        if connection_id and "crawlerConfig" not in candidate:
            row = self._conn.execute(
                "SELECT payload FROM platform_data_connections WHERE tenant_id = ? AND connection_id = ?",
                (tenant_id, connection_id),
            ).fetchone()
            if row:
                try:
                    existing_payload = json.loads(row["payload"] or "{}")
                except json.JSONDecodeError:
                    existing_payload = {}
                if isinstance(existing_payload.get("crawlerConfig"), dict):
                    candidate["crawlerConfig"] = dict(existing_payload["crawlerConfig"])
        normalized = _normalize_data_connection(candidate)
        stored_secret = _connection_secret_for_storage(normalized)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_data_connections(
                    tenant_id, connection_id, institution, account, secret_value,
                    dataset, payload, status, created_by, updated_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, connection_id) DO UPDATE SET
                    institution = excluded.institution,
                    account = excluded.account,
                    secret_value = CASE
                        WHEN excluded.secret_value = ? THEN platform_data_connections.secret_value
                        ELSE excluded.secret_value
                    END,
                    dataset = excluded.dataset,
                    payload = excluded.payload,
                    status = excluded.status,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    normalized["id"],
                    normalized["institution"],
                    normalized["account"],
                    stored_secret,
                    normalized["dataset"],
                    json.dumps(_connection_payload(normalized), ensure_ascii=False, sort_keys=True),
                    normalized["status"],
                    updated_by,
                    updated_by,
                    MASKED_SECRET,
                ),
            )
        return _mask_connection_secret(normalized)

    def delete_data_connection(self, tenant_id: str, connection_id: str) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM platform_data_connections
                WHERE tenant_id = ? AND connection_id = ?
                """,
                (tenant_id, connection_id),
            )
        return cursor.rowcount > 0

    def list_system_params(self, tenant_id: str) -> list[dict[str, str]]:
        rows = self._conn.execute(
            """
            SELECT payload
            FROM platform_system_data_params
            WHERE tenant_id = ?
            ORDER BY param_id
            """,
            (tenant_id,),
        ).fetchall()
        merged = {item["id"]: dict(item) for item in DEFAULT_SYSTEM_PARAMS}
        for row in rows:
            item = json.loads(row["payload"])
            merged[str(item["id"])] = item
        return sorted(merged.values(), key=lambda item: item.get("id", ""))

    def get_system_param_value(self, tenant_id: str, param_id: str) -> str:
        item = next((item for item in self.list_system_params(tenant_id) if item["id"] == param_id), None)
        if item is None:
            raise KeyError(f"unknown_system_param:{param_id}")
        return str(item["value"])

    def upsert_system_param(self, tenant_id: str, param: dict[str, Any], updated_by: str | None = None) -> dict[str, str]:
        normalized = _normalize_system_param(param)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_system_data_params(
                    tenant_id, param_id, param_name, payload, created_by, updated_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, param_id) DO UPDATE SET
                    param_name = excluded.param_name,
                    payload = excluded.payload,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    normalized["id"],
                    normalized["name"],
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    updated_by,
                    updated_by,
                ),
            )
        return normalized


def _normalize_model(model: dict[str, Any]) -> dict[str, Any]:
    normalized = _model_from_payload(model, reveal_secret=True)
    normalized["applicationModule"] = normalize_application_module(normalized.get("applicationModule"))
    if not normalized["id"] or not normalized["name"] or not normalized["modelName"] or not normalized["key"] or not normalized["value"]:
        raise ValueError("model id, name, model source, API address and API key are required.")
    if normalized["status"] not in {"available", "draft"}:
        normalized["status"] = "available"
    if normalized["testStatus"] not in {"untested", "connected", "failed", "mock"}:
        normalized["testStatus"] = "untested"
    if normalized["enabledModels"]:
        available = set(normalized["availableModels"])
        normalized["enabledModels"] = [model_name for model_name in normalized["enabledModels"] if not available or model_name in available]
    return normalized


def _model_name_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _ensure_unique_model_name(existing_models: Any, normalized: dict[str, Any]) -> None:
    target_name = _model_name_key(str(normalized.get("name") or ""))
    target_id = str(normalized.get("id") or "")
    if not target_name:
        return
    for item in existing_models:
        existing = _model_from_payload(dict(item or {}), reveal_secret=False)
        if str(existing.get("id") or "") == target_id:
            continue
        if _model_name_key(str(existing.get("name") or "")) == target_name:
            raise ValueError("duplicate_model_name")


def _model_from_payload(model: dict[str, Any], reveal_secret: bool = False) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field in MODEL_FIELDS:
        if field in {"availableModels", "enabledModels"}:
            normalized[field] = _normalize_string_list(model.get(field) or model.get(_camel_to_snake(field)))
        else:
            normalized[field] = str(model.get(field) or model.get(_camel_to_snake(field)) or "").strip()
    if not normalized["modelName"]:
        normalized["modelName"] = str(model.get("model_name") or model.get("model") or "").strip()
    if normalized["modelName"] not in {"中转站", "官方网站"}:
        normalized["modelName"] = "中转站" if not normalized["modelName"] else normalized["modelName"]
    if normalized["status"] not in {"available", "draft"}:
        normalized["status"] = "available"
    if normalized["testStatus"] not in {"untested", "connected", "failed", "mock"}:
        normalized["testStatus"] = "untested"
    normalized["applicationModule"] = normalize_application_module(normalized.get("applicationModule"))
    if reveal_secret and normalized["value"] and normalized["value"] != MASKED_SECRET:
        normalized["value"] = decrypt_secret(normalized["value"])
    return normalized


def _mask_model_secret(model: dict[str, Any]) -> dict[str, Any]:
    normalized = _model_from_payload(model, reveal_secret=False)
    if normalized["value"]:
        normalized["value"] = MASKED_SECRET
    return normalized


def _normalize_speech_integration(integration: dict[str, Any]) -> dict[str, Any]:
    normalized = _speech_from_payload(integration, reveal_secret=True)
    if not normalized["id"] or not normalized["name"] or not normalized["provider"] or not normalized["apiBase"] or not normalized["apiKey"]:
        raise ValueError("speech integration id, name, provider, API base and API key are required.")
    if normalized["provider"] != "aliyun_fun_asr":
        raise ValueError("only aliyun_fun_asr speech provider is supported.")
    if not normalized["applicationModule"]:
        raise ValueError("speech integration application module is required.")
    if normalized["testStatus"] not in {"untested", "connected", "failed", "mock", ""}:
        normalized["testStatus"] = "untested"
    if normalized["status"] not in {"available", "draft"}:
        normalized["status"] = "available"
    return normalized


def _speech_from_payload(integration: dict[str, Any], reveal_secret: bool = False) -> dict[str, Any]:
    normalized = {
        field: str(integration.get(field) or "").strip()
        for field in SPEECH_INTEGRATION_FIELDS
        if field != "applicationModule"
    }
    legacy_modules = integration.get("applicationModules", integration.get("application_modules"))
    legacy_module = next((str(item).strip() for item in legacy_modules or [] if str(item).strip()), "") if isinstance(legacy_modules, (list, tuple)) else ""
    raw_module = integration.get("applicationModule", integration.get("application_module")) or legacy_module or "realtime_voice_input"
    normalized["applicationModule"] = normalize_application_module(raw_module, allow_empty=False)
    if not normalized["provider"]:
        normalized["provider"] = "aliyun_fun_asr"
    if not normalized["source"]:
        normalized["source"] = "阿里云" if normalized["provider"] == "aliyun_fun_asr" else normalized["provider"]
    if normalized["status"] not in {"available", "draft"}:
        normalized["status"] = "available"
    if reveal_secret and normalized["apiKey"] and normalized["apiKey"] != MASKED_SECRET:
        normalized["apiKey"] = decrypt_secret(normalized["apiKey"])
    return normalized


def _mask_speech_secret(integration: dict[str, Any]) -> dict[str, str]:
    normalized = _speech_from_payload(integration, reveal_secret=False)
    if normalized["apiKey"]:
        normalized["apiKey"] = MASKED_SECRET
    return normalized


def _normalize_data_connection(connection: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        field: str(connection.get(field) or "").strip()
        for field in DATA_CONNECTION_FIELDS
        if field != "crawlerConfig"
    }
    crawler_config = connection.get("crawlerConfig")
    if crawler_config in (None, ""):
        normalized["crawlerConfig"] = {}
    elif isinstance(crawler_config, dict):
        normalized["crawlerConfig"] = dict(crawler_config)
    else:
        raise ValueError("crawlerConfig must be an object.")
    if not normalized["id"] or not normalized["institution"] or not normalized["account"] or not normalized["dataset"]:
        raise ValueError("connection id, institution, account and dataset are required.")
    if not normalized["password"] and not normalized["token"]:
        raise ValueError("connection password or token is required.")
    if not normalized["sourceName"]:
        normalized["sourceName"] = normalized["institution"]
    if not normalized["sourceType"]:
        normalized["sourceType"] = "毓数QBI"
    crawler_mode = infer_crawler_mode({**connection, **normalized})
    if crawler_mode:
        normalized["loginUrl"] = normalized["loginUrl"] or normalized["apiUrl"]
        normalized["queryPageUrl"] = normalized["queryPageUrl"] or normalized["apiUrl"]
        normalized["apiUrl"] = normalized["queryPageUrl"]
        if not normalized["loginUrl"] or not normalized["queryPageUrl"]:
            raise ValueError("crawler login URL and query page URL are required.")
        identity = build_crawler_url_identity({**connection, **normalized, "crawlerMode": crawler_mode})
        if identity is None:
            raise ValueError("crawler page URL is required.")
        normalized["crawlerMode"] = identity.mode
        normalized["crawlerKey"] = identity.crawler_key
        normalized["crawlerProfileId"] = identity.profile_id
    else:
        normalized["crawlerMode"] = ""
        normalized["crawlerKey"] = ""
        normalized["crawlerProfileId"] = ""
    if not normalized["defaultDatabase"]:
        normalized["defaultDatabase"] = normalized["dataset"]
    normalized["enabled"] = _normalize_bool(connection.get("enabled"), default=True)
    normalized["mockEnabled"] = _normalize_bool(connection.get("mockEnabled"), default=False)
    if normalized["testStatus"] not in {"untested", "testing", "verified", "failed", "mock"}:
        normalized["testStatus"] = "untested"
    if normalized["mockEnabled"]:
        normalized["status"] = "mock"
        normalized["testStatus"] = "mock"
    elif not normalized["enabled"]:
        normalized["status"] = "disabled"
    elif normalized["status"] != "verified" or normalized["testStatus"] != "verified":
        normalized["status"] = "draft"
    return normalized


def _release_model_module_binding(models: Any, normalized: dict[str, Any]) -> None:
    """Keep one current model binding for each application module.

    Models remain registered and can be rebound later; only the previous stable
    application-module pointer is cleared when a new model takes its place.
    """

    application_module = str(normalized.get("applicationModule") or "").strip()
    if application_module != "memory_extraction":
        return
    for model in models:
        if (
            str(model.get("id") or "") != str(normalized.get("id") or "")
            and str(model.get("applicationModule") or "") == application_module
        ):
            model["applicationModule"] = ""


def _normalize_system_param(param: dict[str, Any]) -> dict[str, str]:
    normalized = {field: str(param.get(field) or "").strip() for field in SYSTEM_PARAM_FIELDS}
    if not normalized["id"] or not normalized["name"]:
        raise ValueError("system param id and name are required.")
    if not normalized["category"]:
        normalized["category"] = "system"
    if normalized["id"] in SYSTEM_PARAM_INTEGER_RANGES:
        try:
            value = int(normalized["value"])
        except ValueError as exc:
            raise ValueError(f"system_param_must_be_integer:{normalized['id']}") from exc
        minimum, maximum = SYSTEM_PARAM_INTEGER_RANGES[normalized["id"]]
        if value < minimum or value > maximum:
            raise ValueError(f"system_param_out_of_range:{normalized['id']}:{minimum}:{maximum}")
        normalized["value"] = str(value)
    return normalized


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        values = value.replace("，", ",").replace("、", ",").split(",")
    else:
        values = []
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _camel_to_snake(value: str) -> str:
    chars: list[str] = []
    for char in value:
        if char.isupper():
            chars.append("_")
            chars.append(char.lower())
        else:
            chars.append(char)
    return "".join(chars).lstrip("_")


def _mask_connection_secret(connection: dict[str, Any]) -> dict[str, Any]:
    return {**connection, "password": MASKED_SECRET, "token": MASKED_SECRET if connection.get("token") else ""}


def _connection_for_output(connection: dict[str, Any], reveal_secret: bool = False) -> dict[str, Any]:
    if reveal_secret:
        result = dict(connection)
        password = str(result.get("password") or "")
        token = str(result.get("token") or "")
        if password and password != MASKED_SECRET:
            result["password"] = decrypt_secret(password)
        if token and token != MASKED_SECRET:
            result["token"] = decrypt_secret(token)
        return result
    return _mask_connection_secret(connection)


def _connection_secret(connection: dict[str, Any]) -> str:
    password = str(connection.get("password") or "").strip()
    token = str(connection.get("token") or "").strip()
    if password == MASKED_SECRET or token == MASKED_SECRET:
        return MASKED_SECRET
    return password if password and password != MASKED_SECRET else token


def _connection_secret_for_storage(connection: dict[str, Any]) -> str:
    secret = _connection_secret(connection)
    if secret == MASKED_SECRET:
        return MASKED_SECRET
    return encrypt_secret(secret)


def _connection_payload(connection: dict[str, Any]) -> dict[str, Any]:
    payload = {field: connection.get(field) for field in DATA_CONNECTION_FIELDS if field not in {"password", "token"}}
    payload["hasToken"] = bool(connection.get("token"))
    return payload


def _connection_from_row(row: sqlite3.Row, reveal_secret: bool = False) -> dict[str, Any]:
    payload = json.loads(row["payload"] or "{}")
    if not isinstance(payload, dict):
        payload = {}
    has_token = bool(payload.get("hasToken"))
    password = MASKED_SECRET
    token = MASKED_SECRET if has_token else ""
    if reveal_secret:
        secret = decrypt_secret(str(row["secret_value"] or ""))
        password = "" if has_token else secret
        token = secret if has_token else ""
    connection = {
        "id": row["connection_id"],
        "institution": row["institution"],
        "sourceName": payload.get("sourceName") or row["institution"],
        "sourceType": payload.get("sourceType") or "毓数QBI",
        "apiUrl": payload.get("apiUrl") or "",
        "loginUrl": payload.get("loginUrl") or "",
        "queryPageUrl": payload.get("queryPageUrl") or "",
        "metadataPageUrl": payload.get("metadataPageUrl") or "",
        "spaceId": payload.get("spaceId") or "",
        "crawlerMode": payload.get("crawlerMode") or "",
        "crawlerKey": payload.get("crawlerKey") or "",
        "crawlerProfileId": payload.get("crawlerProfileId") or "",
        "crawlerConfig": payload.get("crawlerConfig") if isinstance(payload.get("crawlerConfig"), dict) else {},
        "account": row["account"],
        "password": password,
        "token": token,
        "dataset": row["dataset"],
        "defaultDatabase": payload.get("defaultDatabase") or row["dataset"],
        "enabled": _normalize_bool(payload.get("enabled"), default=True),
        "mockEnabled": _normalize_bool(payload.get("mockEnabled"), default=False),
        "status": row["status"],
        "lastTestedAt": payload.get("lastTestedAt") or "",
        "testStatus": payload.get("testStatus") or "untested",
        "testMessage": payload.get("testMessage") or "",
    }
    return connection


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "启用"}


def _is_crawler_connection(connection: dict[str, Any]) -> bool:
    return bool(infer_crawler_mode(connection))


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, declaration: str) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if column_name in {row[1] for row in rows}:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {declaration}")
