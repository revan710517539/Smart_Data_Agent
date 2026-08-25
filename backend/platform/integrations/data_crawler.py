from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from backend.platform.ingestion.csv_folder import tenant_directory_name


@dataclass(frozen=True)
class DataCrawlerEndpoint:
    tenant_id: str
    base_url: str
    institution_id: str
    institution_directory: str
    token: str


def endpoint_for_tenant(tenant_id: str) -> DataCrawlerEndpoint:
    raw = os.getenv("SMART_DATA_AGENT_DATA_CRAWLER_ENDPOINTS", "").strip()
    if not raw:
        raise RuntimeError("data_crawler_endpoint_not_configured")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("data_crawler_endpoints_invalid_json") from exc
    item = payload.get(tenant_id) if isinstance(payload, dict) else None
    if not isinstance(item, dict):
        raise PermissionError("data_crawler_tenant_binding_missing")
    base_url = str(item.get("baseUrl") or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("data_crawler_base_url_invalid")
    institution_id = str(item.get("institutionId") or "").strip()
    institution_directory = str(item.get("institutionDirectory") or "").strip()
    token = str(item.get("token") or "").strip()
    if not institution_id or not institution_directory or len(token) < 16:
        raise ValueError("data_crawler_tenant_binding_incomplete")
    if institution_directory != tenant_directory_name(tenant_id):
        raise ValueError("data_crawler_tenant_directory_mismatch")
    return DataCrawlerEndpoint(tenant_id, base_url, institution_id, institution_directory, token)


class DataCrawlerClient:
    def __init__(self, endpoint: DataCrawlerEndpoint, timeout_seconds: int = 20) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = max(1, min(int(timeout_seconds), 120))

    def list_bindings(self) -> dict[str, Any]:
        return self._request("GET", "sql-bindings")

    def binding(self, sql_id: str) -> dict[str, Any]:
        return self._request("GET", f"sql-bindings/{quote(sql_id, safe='')}")

    def claim(self, sql_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"control-claims/{quote(sql_id, safe='')}", payload)

    def release(self, sql_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"control-claims/{quote(sql_id, safe='')}")

    def execute(self, sql_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "executions", {**payload, "sqlId": sql_id})

    def execution(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"executions/{quote(run_id, safe='')}")

    def _request(self, method: str, suffix: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = (
            f"{self.endpoint.base_url}/api/sda/v1/institutions/"
            f"{quote(self.endpoint.institution_id, safe='')}/{suffix}"
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.endpoint.token}",
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except Exception:
                detail = "data_crawler_http_error"
            raise RuntimeError(str(detail or "data_crawler_http_error")) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError("data_crawler_unavailable") from exc
        if not isinstance(result, dict):
            raise RuntimeError("data_crawler_response_invalid")
        if str(result.get("institutionId") or "") != self.endpoint.institution_id:
            raise PermissionError("data_crawler_institution_mismatch")
        return result


def client_for_tenant(tenant_id: str) -> DataCrawlerClient:
    return DataCrawlerClient(endpoint_for_tenant(tenant_id))
