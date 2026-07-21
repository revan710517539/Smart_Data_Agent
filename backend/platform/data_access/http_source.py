from __future__ import annotations

import base64
import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request

import certifi

from backend.platform.security import safe_urlopen, validate_outbound_url


class HTTPJSONSourceClient:
    """Client for the platform HTTP data-source contract.

    A source exposes ``GET /datasets`` and ``POST /query`` below its configured
    API base. Responses are bounded JSON objects. Redirects, DNS targets and
    credentials are governed by the shared egress policy.
    """

    def __init__(self, connection: dict[str, Any], timeout_seconds: float = 10.0) -> None:
        self.connection = dict(connection)
        self.api_url = str(connection.get("apiUrl") or "").strip()
        if not self.api_url:
            raise ValueError("Configured HTTP data source is missing apiUrl.")
        validate_outbound_url(self.api_url)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))

    def list_datasets(self) -> list[dict[str, Any]]:
        payload = self._request_json(self._endpoint("/datasets"), method="GET")
        value = payload.get("datasets") if "datasets" in payload else payload.get("data")
        if isinstance(value, dict):
            return [
                {"dataset_id": str(dataset_id), **(item if isinstance(item, dict) else {})}
                for dataset_id, item in value.items()
            ]
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        return []

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(self._endpoint("/query"), method="POST", body=payload)

    def _request_json(
        self,
        url: str,
        *,
        method: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = self._headers()
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with safe_urlopen(
                request,
                timeout=self.timeout_seconds,
                context=ssl.create_default_context(cafile=certifi.where()),
            ) as response:
                raw = response.read(2_000_000)
        except HTTPError as exc:
            raise RuntimeError(f"data_source_http_{exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("data_source_unreachable") from exc
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError("data_source_invalid_json")
        return decoded

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "SmartDataAgent/1.0 data-source"}
        token = str(self.connection.get("token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
            return headers
        account = str(self.connection.get("account") or "").strip()
        password = str(self.connection.get("password") or "").strip()
        credential = base64.b64encode(f"{account}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {credential}"
        return headers

    def _endpoint(self, suffix: str) -> str:
        parsed = urlparse(self.api_url)
        path = parsed.path.rstrip("/")
        next_path = path if path.endswith(suffix) else f"{path}{suffix}" if path else suffix
        return urlunparse((parsed.scheme, parsed.netloc, next_path, "", "", ""))

