from __future__ import annotations

import csv
import hashlib
import io
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .json_warehouse import JSONDataWarehouse


ObjectReader = Callable[[str, dict[str, Any]], bytes]


class CSVObjectDataWarehouse(JSONDataWarehouse):
    """Immutable CSV/object-storage analytical adapter.

    Every dataset is catalog-governed and must carry a content SHA-256. S3/OSS
    objects additionally require a version ID so a later overwrite cannot alter
    historical evidence.
    """

    data_source_name = "csv_object_warehouse"

    def __init__(
        self,
        dataset_catalog: dict[str, dict[str, Any]],
        *,
        environment: str = "development",
        object_reader: ObjectReader | None = None,
        max_object_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.path = Path("<catalog-backed-csv-object>")
        self.environment = environment
        self.object_reader = object_reader or self._default_object_reader
        self.max_object_bytes = max(1, min(int(max_object_bytes), 500 * 1024 * 1024))
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._datasets = {
            dataset_id: self._load_dataset(dataset_id, payload)
            for dataset_id, payload in dataset_catalog.items()
        }
        self._payload = {"version": "catalog", "datasets": self._datasets}

    def snapshot_info(self, dataset_id: str) -> dict[str, Any]:
        snapshot = self._snapshots.get(dataset_id)
        return dict(snapshot) if snapshot else {}

    def list_datasets(self) -> list[dict[str, Any]]:
        datasets = super().list_datasets()
        for item in datasets:
            item["source"] = "immutable_csv_object"
            item["source_snapshot"] = self.snapshot_info(str(item["dataset_id"]))
        return datasets

    def _load_dataset(self, dataset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        object_uri = str(payload.get("object_uri") or payload.get("path") or "").strip()
        expected_hash = str(payload.get("artifact_sha256") or "").strip().lower()
        observed_at = str(payload.get("observed_at") or "").strip()
        snapshot_id = str(payload.get("snapshot_id") or "").strip()
        if not object_uri or len(expected_hash) != 64 or not observed_at or not snapshot_id:
            raise ValueError(f"csv_dataset_immutable_evidence_required:{dataset_id}")
        raw = self.object_reader(object_uri, payload)
        if len(raw) > self.max_object_bytes:
            raise ValueError(f"csv_object_too_large:{dataset_id}")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"csv_object_hash_mismatch:{dataset_id}")
        rows = self._parse_rows(raw, dict(payload.get("field_types") or {}), dataset_id)
        allowed_metrics = [str(item) for item in payload.get("allowed_metrics", [])]
        allowed_dimensions = [str(item) for item in payload.get("allowed_dimensions", [])]
        required = set(allowed_metrics) | set(allowed_dimensions) | {str(payload.get("tenant_column") or "tenant_id")}
        if any(not required.issubset(row) for row in rows):
            raise ValueError(f"csv_dataset_schema_mismatch:{dataset_id}")
        tenant_column = str(payload.get("tenant_column") or "tenant_id")
        if tenant_column != "tenant_id":
            for row in rows:
                row["tenant_id"] = row.pop(tenant_column)
        parsed = urlparse(object_uri)
        if parsed.scheme in {"s3", "oss"} and not str(payload.get("version_id") or "").strip():
            raise ValueError(f"csv_object_version_required:{dataset_id}")
        self._snapshots[dataset_id] = {
            "snapshot_id": snapshot_id,
            "observed_at": observed_at,
            "latest_partition": str(payload.get("latest_partition") or ""),
            "artifact_sha256": actual_hash,
            "object_uri_hash": hashlib.sha256(object_uri.encode("utf-8")).hexdigest(),
            "object_version_id": str(payload.get("version_id") or ""),
            "immutable": True,
        }
        return {
            "label": str(payload.get("label") or dataset_id),
            "allowed_metrics": allowed_metrics,
            "allowed_dimensions": allowed_dimensions,
            "metric_aggregation": dict(payload.get("metric_aggregation") or {}),
            "rows": rows,
        }

    @staticmethod
    def _parse_rows(raw: bytes, field_types: dict[str, Any], dataset_id: str) -> list[dict[str, Any]]:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"csv_object_encoding_invalid:{dataset_id}") from exc
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"csv_header_invalid:{dataset_id}")
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(reader):
            if index >= 1_000_000:
                raise ValueError(f"csv_row_limit_exceeded:{dataset_id}")
            rows.append(
                {
                    str(key): _convert_csv_value(value, str(field_types.get(str(key)) or "string"))
                    for key, value in row.items()
                    if key is not None
                }
            )
        return rows

    def _default_object_reader(self, object_uri: str, payload: dict[str, Any]) -> bytes:
        parsed = urlparse(object_uri)
        if parsed.scheme in {"", "file"}:
            if self.environment in {"staging", "production"}:
                raise ValueError("local_csv_object_forbidden_in_production")
            path = Path(parsed.path if parsed.scheme == "file" else object_uri).expanduser().resolve()
            return path.read_bytes()
        if parsed.scheme not in {"s3", "oss"}:
            raise ValueError("unsupported_csv_object_scheme")
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - production dependency boundary.
            raise RuntimeError("boto3_not_installed") from exc
        client = boto3.client(
            "s3",
            region_name=str(payload.get("region") or os.getenv("SMART_DATA_AGENT_OBJECT_REGION") or "") or None,
            endpoint_url=str(payload.get("endpoint_url") or os.getenv("SMART_DATA_AGENT_OBJECT_ENDPOINT") or "") or None,
        )
        response = client.get_object(
            Bucket=parsed.netloc,
            Key=parsed.path.lstrip("/"),
            VersionId=str(payload.get("version_id") or ""),
        )
        body = response["Body"].read(self.max_object_bytes + 1)
        return bytes(body)


def _convert_csv_value(value: Any, field_type: str) -> Any:
    text = str(value or "").strip()
    normalized_type = field_type.strip().lower()
    if text == "":
        return None
    if normalized_type in {"int", "integer", "bigint"}:
        return int(text)
    if normalized_type in {"float", "double", "decimal", "number"}:
        return float(text)
    if normalized_type in {"bool", "boolean"}:
        if text.lower() not in {"true", "false", "1", "0"}:
            raise ValueError("csv_boolean_invalid")
        return text.lower() in {"true", "1"}
    return text
