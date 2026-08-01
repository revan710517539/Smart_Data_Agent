from __future__ import annotations

import base64
import json
import ssl
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request

import certifi

from backend.platform.security import EgressPolicyError, safe_urlopen, validate_outbound_url

# This is a production connection-check adapter, not a pytest module.  The
# historical filename is kept to avoid changing imports used by the settings
# API, while explicitly opting out of pytest discovery.
__test__ = False


def test_data_connection(connection: dict[str, Any]) -> dict[str, Any]:
    result = _test_data_connection(connection)
    return {**result, "tested_at": datetime.now(timezone.utc).isoformat()}


def _test_data_connection(connection: dict[str, Any]) -> dict[str, Any]:
    """Validate the exact connection supplied by the user.

    HTTP sources implement the small adapter contract ``GET /datasets`` and
    ``POST /query`` relative to ``apiUrl``.  The previous implementation tested
    an unrelated process-wide mock warehouse, which could mark a broken saved
    connection as healthy.
    """

    mock_enabled = _normalize_bool(connection.get("mockEnabled"), default=False)
    dataset = str(connection.get("dataset") or "").strip()
    connection_id = str(connection.get("id") or "").strip()
    institution = str(connection.get("institution") or "").strip()
    api_url = str(connection.get("apiUrl") or "").strip()
    source_type = str(connection.get("sourceType") or "http_json").strip()
    if not dataset and not mock_enabled:
        raise ValueError("connection dataset is required.")

    if mock_enabled:
        metric = "metric_value"
        dimension = "institution"
        sample_rows = _mock_sample_rows(institution, dimension, metric)
        return {
            "connection_id": connection_id,
            "institution": institution,
            "dataset": dataset or "mock_generated_dataset",
            "status": "mock",
            "callable": True,
            "verified": False,
            "execution_mode": "mock",
            "data_source_mode": "explicit_mock",
            "matched_dataset": None,
            "available_datasets": [],
            "sample": {
                "metric": metric,
                "dimension": dimension,
                "row_count": len(sample_rows),
                "rows": sample_rows,
            },
            "message": "Mock 模式仅生成界面样例，未验证任何真实数据连接。",
        }
    if not api_url:
        return _failed_result(connection_id, institution, dataset, "endpoint_required", "真实连接必须配置 API 地址，不能使用进程默认数据仓库代替测试。")

    try:
        validate_outbound_url(api_url)
        headers = _authorization_headers(connection)
        catalog_payload = _request_json(_endpoint(api_url, "/datasets"), headers, method="GET")
        available_datasets = _datasets_from_payload(catalog_payload)
    except EgressPolicyError:
        return _failed_result(connection_id, institution, dataset, "egress_policy_rejected", "数据源地址不符合服务端出站安全策略。")
    except Exception:
        return _failed_result(connection_id, institution, dataset, "connection_failed", "无法认证或读取数据源目录，请通过 request_id 查询服务端日志。")

    data_source_mode = f"configured_http:{source_type}"
    matched = _find_dataset(dataset, available_datasets)
    if matched is None:
        return {
            "connection_id": connection_id,
            "institution": institution,
            "dataset": dataset,
            "status": "not_found",
            "callable": False,
            "verified": False,
            "data_source_mode": data_source_mode,
            "matched_dataset": None,
            "available_datasets": _compact_datasets(available_datasets),
            "message": "已连接用户配置的数据源，但目录中未找到目标数据集。",
        }

    try:
        query_payload = _request_json(
            _endpoint(api_url, "/query"),
            headers,
            method="POST",
            body={
                "dataset_id": str(matched["dataset_id"]),
                "tenant_id": str(connection.get("tenant_id") or ""),
                "limit": 3,
                "mode": "connection_test",
            },
        )
        sample_rows = _rows_from_payload(query_payload)[:3]
    except EgressPolicyError:
        return _failed_result(connection_id, institution, dataset, "egress_policy_rejected", "数据源查询地址不符合服务端出站安全策略。")
    except Exception:
        return {
            "connection_id": connection_id,
            "institution": institution,
            "dataset": dataset,
            "status": "query_failed",
            "callable": False,
            "verified": False,
            "data_source_mode": data_source_mode,
            "matched_dataset": _compact_dataset(matched),
            "available_datasets": _compact_datasets(available_datasets),
            "message": "数据集目录可识别，但真实样例查询失败，请通过 request_id 查询服务端日志。",
        }

    return {
        "connection_id": connection_id,
        "institution": institution,
        "dataset": dataset,
        "status": "verified",
        "callable": True,
        "verified": True,
        "execution_mode": "real",
        "data_source_mode": data_source_mode,
        "matched_dataset": _compact_dataset(matched),
        "available_datasets": _compact_datasets(available_datasets),
        "sample": {
            "row_count": len(sample_rows),
            "rows": sample_rows,
        },
        "message": "已使用当前连接的地址和凭证完成目录读取及真实样例查询。",
    }


def _failed_result(connection_id: str, institution: str, dataset: str, status: str, message: str) -> dict[str, Any]:
    return {
        "connection_id": connection_id,
        "institution": institution,
        "dataset": dataset,
        "status": status,
        "callable": False,
        "verified": False,
        "execution_mode": "real",
        "data_source_mode": "configured_connection",
        "matched_dataset": None,
        "available_datasets": [],
        "message": message,
    }


def _authorization_headers(connection: dict[str, Any]) -> dict[str, str]:
    token = str(connection.get("token") or "").strip()
    account = str(connection.get("account") or "").strip()
    password = str(connection.get("password") or "").strip()
    headers = {"Accept": "application/json", "User-Agent": "SmartDataAgent/1.0 connection-test"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif account or password:
        credential = base64.b64encode(f"{account}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {credential}"
    return headers


def _request_json(
    url: str,
    headers: dict[str, str],
    *,
    method: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, method=method, headers=request_headers)
    try:
        with safe_urlopen(
            request,
            timeout=8,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            raw = response.read(256_000)
    except HTTPError as exc:
        raise RuntimeError(f"provider_http_{exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("provider_unreachable") from exc
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("provider_invalid_json")
    return payload


def _endpoint(api_url: str, suffix: str) -> str:
    parsed = urlparse(api_url)
    path = parsed.path.rstrip("/")
    if path.endswith(suffix):
        next_path = path
    else:
        next_path = f"{path}{suffix}" if path else suffix
    return urlunparse((parsed.scheme, parsed.netloc, next_path, "", "", ""))


def _datasets_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("datasets") if "datasets" in payload else payload.get("data")
    if isinstance(value, dict):
        return [
            {"dataset_id": str(dataset_id), **(item if isinstance(item, dict) else {})}
            for dataset_id, item in value.items()
        ]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("rows")
    if value is None and isinstance(payload.get("data"), dict):
        value = payload["data"].get("rows")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _find_dataset(dataset: str, available_datasets: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = _normalize_match_value(dataset)
    for item in available_datasets:
        candidates = {
            item.get("dataset_id"),
            item.get("label"),
            item.get("source_table"),
        }
        if target in {_normalize_match_value(value) for value in candidates if value}:
            return item
    return None


def _compact_datasets(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_compact_dataset(item) for item in datasets]


def _compact_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": str(dataset.get("dataset_id") or ""),
        "label": str(dataset.get("label") or dataset.get("dataset_id") or ""),
        "source_table": str(dataset.get("source_table") or ""),
        "metric_count": len(dataset.get("allowed_metrics") or []),
        "dimension_count": len(dataset.get("allowed_dimensions") or []),
    }


def _mock_sample_rows(institution: str, dimension: str, metric: str) -> list[dict[str, Any]]:
    base_dimension = institution or "模拟机构"
    return [
        {dimension: base_dimension, metric: 1280, "metric_value": 1280, "data_mode": "mock"},
        {dimension: f"{base_dimension}-对照组", metric: 960, "metric_value": 960, "data_mode": "mock"},
        {dimension: f"{base_dimension}-增长组", metric: 1420, "metric_value": 1420, "data_mode": "mock"},
    ]


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "启用", "mock"}


def _normalize_match_value(value: Any) -> str:
    return str(value or "").strip().lower()


test_data_connection.__test__ = False
