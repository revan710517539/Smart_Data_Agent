from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from openpyxl import Workbook

from backend.platform.api.asgi import SmartDataAgentASGI
from backend.platform.api.routes.assets import _bind_page_data_asset, read_page_data_rows_payload
from backend.platform.api.routes.customer_segment import (
    handle_customer_segment_list_confirm,
    handle_customer_segment_list_preview,
)
from backend.platform.application import InMemoryApplicationStore, SQLiteApplicationStore
from backend.platform.bootstrap import build_local_platform
from backend.platform.customer_segment import (
    confirm_customer_list,
    customer_ids_for_user,
    preview_customer_list,
)
from backend.platform.ingestion.csv_folder import CSVFolderSource


def _workbook_bytes(rows: list[tuple[object, ...]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _base64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


async def _asgi_json_request(
    app: SmartDataAgentASGI,
    method: str,
    path: str,
    *,
    query: str = "",
    payload: dict[str, object] | None = None,
    tenant_id: str = "tenant_demo",
    user_id: str = "u_super_admin",
) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else b""
    sent: list[dict[str, object]] = []
    received = False

    async def receive() -> dict[str, object]:
        nonlocal received
        if received:
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query.encode("ascii"),
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-user-id", user_id.encode("utf-8")),
                (b"x-tenant-id", tenant_id.encode("utf-8")),
            ],
            "client": ("127.0.0.1", 51000),
        },
        receive,
        send,
    )
    start = next(item for item in sent if item["type"] == "http.response.start")
    response = next(item for item in sent if item["type"] == "http.response.body")
    return int(start["status"]), json.loads(bytes(response.get("body") or b"{}").decode("utf-8"))


def _list_metadata(customer_count: int, suffix: str, owner: str) -> dict[str, object]:
    return {
        "artifactId": f"artifact_{suffix}",
        "contentHash": hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
        "sourceContentHash": hashlib.sha256(f"source:{suffix}".encode("utf-8")).hexdigest(),
        "fileName": f"{suffix}.xlsx",
        "customerCount": customer_count,
        "duplicateCount": 0,
        "blankCount": 0,
        "confirmedAt": "2026-08-23T00:00:00+00:00",
        "ownerUserId": owner,
    }


class _ObjectStore:
    def __init__(self) -> None:
        self.content: dict[str, bytes] = {}

    def put(self, tenant_id: str, content: bytes, suffix: str):
        content_hash = hashlib.sha256(content).hexdigest()
        object_uri = f"memory://{tenant_id}/{content_hash}{suffix}"
        self.content[object_uri] = content
        return SimpleNamespace(
            object_uri=object_uri,
            content_hash=content_hash,
            size_bytes=len(content),
        )


class _AcquisitionStore:
    def __init__(self) -> None:
        self.artifacts: dict[str, dict[str, object]] = {}

    def create_artifact(self, tenant_id: str, **payload):
        artifact_id = f"artifact_{len(self.artifacts) + 1}"
        artifact = {"artifact_id": artifact_id, "tenant_id": tenant_id, **payload}
        self.artifacts[artifact_id] = artifact
        return artifact


class _AcquisitionService:
    def __init__(self) -> None:
        self.object_store = _ObjectStore()
        self.store = _AcquisitionStore()
        self.csv_source = None

    def get_artifact_content(self, tenant_id: str, artifact_id: str):
        artifact = self.store.artifacts[artifact_id]
        if artifact["tenant_id"] != tenant_id:
            raise PermissionError("artifact_tenant_scope_mismatch")
        return artifact, self.object_store.content[str(artifact["object_uri"])]


class _Catalog:
    def __init__(self, table: dict, rows: list[dict[str, str]]) -> None:
        self.table = table
        self.rows = rows

    def table_assets(self) -> list[dict]:
        return [self.table]

    def read_rows_matching_values(self, relative_path: str, *, key_field: str, values: list[str], max_matches: int):
        del relative_path, max_matches
        requested = set(values)
        matched = [dict(row) for row in self.rows if str(row.get(key_field) or "").strip() in requested]
        return list(self.table["fields_by_code"]), matched


class _CsvSource:
    def __init__(self, catalog: _Catalog) -> None:
        self.catalog = catalog

    def for_tenant(self, tenant_id: str) -> _Catalog:
        if tenant_id != "tenant_a":
            raise PermissionError("tenant_scope_mismatch")
        return self.catalog


class CustomerSegmentAnalysisTest(unittest.TestCase):
    def test_preview_reads_a1_as_customer_id_and_deduplicates_only_column_a(self) -> None:
        content = _workbook_bytes([
            ("customer_no", "ignored header-like value"),
            ("0001", "ignored"),
            ("0001", None),
            ("0002", None),
            (None, "ignored"),
        ])

        preview = preview_customer_list("customers.xlsx", _base64(content))

        self.assertEqual(preview["customer_count"], 3)
        self.assertEqual(preview["duplicate_count"], 1)
        self.assertEqual(preview["blank_count"], 1)
        self.assertTrue(preview["other_columns_ignored"])

    def test_preview_rejects_wrong_file_type_and_invalid_a_column_value(self) -> None:
        content = _workbook_bytes([(1.25,)])
        with self.assertRaisesRegex(ValueError, "customer_segment_list_requires_xlsx"):
            preview_customer_list("customers.csv", _base64(content))
        with self.assertRaisesRegex(ValueError, "customer_segment_list_value_invalid:1"):
            preview_customer_list("customers.xlsx", _base64(content))

    def test_confirm_persists_normalized_artifact_and_isolates_users(self) -> None:
        services = SimpleNamespace(
            application_store=InMemoryApplicationStore(),
            data_acquisition_service=_AcquisitionService(),
        )
        first = _workbook_bytes([("0001",), ("0002",), ("0001",)])
        second = _workbook_bytes([("9001",)])
        first_result = confirm_customer_list(
            services,
            tenant_id="tenant_a",
            user_id="user_a",
            file_name="first.xlsx",
            content_base64=_base64(first),
            expected_content_hash=hashlib.sha256(first).hexdigest(),
        )
        confirm_customer_list(
            services,
            tenant_id="tenant_a",
            user_id="user_b",
            file_name="second.xlsx",
            content_base64=_base64(second),
            expected_content_hash=hashlib.sha256(second).hexdigest(),
        )

        first_metadata, first_ids = customer_ids_for_user(services, tenant_id="tenant_a", user_id="user_a")
        second_metadata, second_ids = customer_ids_for_user(services, tenant_id="tenant_a", user_id="user_b")
        self.assertEqual(first_result["customer_list"]["customerCount"], 2)
        self.assertEqual(first_metadata["ownerUserId"], "user_a")
        self.assertEqual(first_ids, ["0001", "0002"])
        self.assertEqual(second_metadata["ownerUserId"], "user_b")
        self.assertEqual(second_ids, ["9001"])

    def test_http_route_handlers_require_execute_and_audit_only_safe_counts(self) -> None:
        services = SimpleNamespace(
            application_store=InMemoryApplicationStore(),
            data_acquisition_service=_AcquisitionService(),
        )
        content = _workbook_bytes([("C001",), ("C002",), ("C001",)])

        class Handler:
            def __init__(self) -> None:
                self.services = services
                self.payload: dict[str, object] = {
                    "file_name": "customers.xlsx",
                    "content_base64": _base64(content),
                }
                self.permissions: list[str] = []
                self.response: dict[str, object] = {}
                self.audit: dict[str, object] | None = None

            def _read_json(self, *, max_bytes: int) -> dict[str, object]:
                self.assert_max_bytes = max_bytes
                return dict(self.payload)

            def _request_context(self, *, payload: dict[str, object]):
                self.assert_payload = payload
                return SimpleNamespace(tenant_id="tenant_a", user_id="user_a")

            def _require_application_permission(self, context: object, action: str) -> None:
                del context
                self.permissions.append(action)

            def _write_audit(self, context: object, event: str, target_type: str, **payload: object) -> None:
                del context
                self.audit = {"event": event, "target_type": target_type, **payload}

            def _send_json(self, payload: dict[str, object], *args: object, **kwargs: object) -> None:
                del args, kwargs
                self.response = payload

        handler = Handler()
        handle_customer_segment_list_preview(handler)
        preview = dict(handler.response["preview"])
        self.assertEqual(handler.permissions, ["execute"])
        self.assertEqual(preview["customer_count"], 2)
        self.assertEqual(preview["duplicate_count"], 1)

        handler.payload["expected_content_hash"] = preview["content_hash"]
        handle_customer_segment_list_confirm(handler)
        self.assertEqual(handler.permissions, ["execute", "execute"])
        self.assertEqual(handler.response["customer_list"]["customerCount"], 2)
        self.assertEqual(handler.response["customer_list"]["ownerUserId"], "user_a")
        self.assertEqual(handler.audit["event"], "customer_segment.list.confirm")
        audit_detail = handler.audit["detail"]
        self.assertEqual(audit_detail["customer_count"], 2)
        self.assertNotIn("customer_ids", audit_detail)
        self.assertNotIn("C001", str(audit_detail))

    def test_asgi_preview_confirm_and_restart_readback_use_real_runtime_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "runtime.sqlite"
            content = _workbook_bytes([("C001", "ignored"), ("C002",), ("C001",)])
            request_payload = {
                "file_name": "customers.xlsx",
                "content_base64": _base64(content),
            }
            services = build_local_platform(db_path=database_path)
            app = SmartDataAgentASGI(services, owns_services=False)
            try:
                preview_status, preview_response = asyncio.run(_asgi_json_request(
                    app,
                    "POST",
                    "/api/customer-segment/list/preview",
                    payload=request_payload,
                ))
                preview = preview_response["preview"]
                self.assertEqual(preview_status, 200)
                self.assertEqual(preview["customer_count"], 2)
                self.assertEqual(preview["duplicate_count"], 1)
                self.assertTrue(preview["other_columns_ignored"])

                confirm_status, confirm_response = asyncio.run(_asgi_json_request(
                    app,
                    "POST",
                    "/api/customer-segment/list/confirm",
                    payload={**request_payload, "expected_content_hash": preview["content_hash"]},
                ))
                self.assertEqual(confirm_status, 200)
                self.assertEqual(confirm_response["customer_list"]["customerCount"], 2)

                module_status, module_response = asyncio.run(_asgi_json_request(
                    app,
                    "GET",
                    "/api/application/module",
                    query="module_key=customer_segment_analysis",
                ))
                self.assertEqual(module_status, 200)
                self.assertEqual(module_response["state"]["customerSegmentList"]["customerCount"], 2)
            finally:
                services.close()

            rebuilt = build_local_platform(db_path=database_path)
            rebuilt_app = SmartDataAgentASGI(rebuilt, owns_services=False)
            try:
                readback_status, readback = asyncio.run(_asgi_json_request(
                    rebuilt_app,
                    "GET",
                    "/api/application/module",
                    query="module_key=customer_segment_analysis",
                ))
                metadata, customer_ids = customer_ids_for_user(
                    rebuilt,
                    tenant_id="tenant_demo",
                    user_id="u_super_admin",
                )
                self.assertEqual(readback_status, 200)
                self.assertEqual(readback["state"]["customerSegmentList"]["ownerUserId"], "u_super_admin")
                self.assertEqual(metadata["customerCount"], 2)
                self.assertEqual(customer_ids, ["C001", "C002"])
            finally:
                rebuilt.close()

    def test_asgi_workspace_applies_confirmed_list_to_every_page_asset(self) -> None:
        with TemporaryDirectory() as tmpdir:
            table = {
                "id": "customer_detail",
                "sourceKey": "customer_detail_source",
                "schemaFingerprint": "customer_schema_v1",
                "contentHash": "customer_content_v1",
                "relativePath": "customer_detail.csv",
                "tableNameEn": "customer_detail",
                "tableNameCn": "客户明细",
                "customerField": "customer_no",
                "fields": [
                    {"fieldNameEn": "customer_no", "fieldNameCn": "客户号", "type": "string", "isPrimaryKey": True},
                    {"fieldNameEn": "segment", "fieldNameCn": "客群", "type": "string"},
                    {"fieldNameEn": "loan_balance", "fieldNameCn": "贷款余额", "type": "decimal", "isMetric": True},
                ],
            }
            table["fields_by_code"] = {field["fieldNameEn"]: field for field in table["fields"]}
            page_assets = [
                {
                    "id": "page_customer_balance",
                    "name": "名单客户贷款余额",
                    "institutionScope": "customer_segment",
                    "targetPages": ["customer_segment_analysis"],
                    "sourceKey": table["sourceKey"],
                    "sourceTableId": table["id"],
                    "sourceTableName": table["tableNameCn"],
                    "sourceRelativePath": table["relativePath"],
                    "schemaFingerprint": table["schemaFingerprint"],
                    "contentHash": table["contentHash"],
                    "customerKeyField": "customer_no",
                    "metricFields": ["loan_balance"],
                    "dimensionFields": ["customer_no"],
                    "sourceFields": table["fields"],
                    "visualizationType": "table",
                    "updatedAt": "2026-08-23T00:00:00+00:00",
                },
                {
                    "id": "page_customer_segment",
                    "name": "名单客户客群分布",
                    "institutionScope": "customer_segment",
                    "targetPages": ["customer_segment_analysis"],
                    "sourceKey": table["sourceKey"],
                    "sourceTableId": table["id"],
                    "sourceTableName": table["tableNameCn"],
                    "sourceRelativePath": table["relativePath"],
                    "schemaFingerprint": table["schemaFingerprint"],
                    "contentHash": table["contentHash"],
                    "customerKeyField": "customer_no",
                    "metricFields": ["loan_balance"],
                    "dimensionFields": ["segment"],
                    "sourceFields": table["fields"],
                    "visualizationType": "column",
                    "updatedAt": "2026-08-23T00:00:00+00:00",
                },
            ]
            services = build_local_platform(db_path=Path(tmpdir) / "workspace.sqlite")
            services.data_acquisition_service.csv_source = _CsvSource(_Catalog(table, [
                {"customer_no": "C001", "segment": "A", "loan_balance": "10"},
                {"customer_no": "C002", "segment": "B", "loan_balance": "20"},
                {"customer_no": "C003", "segment": "C", "loan_balance": "30"},
            ]))
            for page_asset in page_assets:
                services.data_asset_store.upsert_item(
                    "tenant_a",
                    "page_data",
                    page_asset,
                    updated_by="u_super_admin",
                    lifecycle_status="active",
                )
            app = SmartDataAgentASGI(services, owns_services=False)
            try:
                content = _workbook_bytes([("C002",), ("C999",), ("C001",), ("C002",)])
                request_payload = {"file_name": "segment.xlsx", "content_base64": _base64(content)}
                preview_status, preview_response = asyncio.run(_asgi_json_request(
                    app,
                    "POST",
                    "/api/customer-segment/list/preview",
                    payload=request_payload,
                    tenant_id="tenant_a",
                ))
                self.assertEqual(preview_status, 200)
                confirm_status, _ = asyncio.run(_asgi_json_request(
                    app,
                    "POST",
                    "/api/customer-segment/list/confirm",
                    payload={**request_payload, "expected_content_hash": preview_response["preview"]["content_hash"]},
                    tenant_id="tenant_a",
                ))
                self.assertEqual(confirm_status, 200)

                workspace_status, workspace = asyncio.run(_asgi_json_request(
                    app,
                    "GET",
                    "/api/data-assets/page-data/workspace",
                    query="page_code=customer_segment_analysis",
                    tenant_id="tenant_a",
                ))
                self.assertEqual(workspace_status, 200)
                self.assertEqual({item["id"] for item in workspace["assets"]}, {item["id"] for item in page_assets})
                self.assertEqual(workspace["row_errors"], {})
                for page_asset in page_assets:
                    projection = workspace["rows"][page_asset["id"]]
                    self.assertEqual(projection["customer_segment"]["customer_count"], 3)
                    self.assertEqual(projection["customer_segment"]["matched_count"], 2)
                    self.assertNotIn("C003", {row.get("customer_no") for row in projection["rows"]})
                self.assertEqual(
                    [row["customer_no"] for row in workspace["rows"]["page_customer_balance"]["rows"]],
                    ["C002", "C999", "C001"],
                )
            finally:
                services.close()

    def test_sqlite_customer_lists_are_persistent_and_user_scoped(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "application.sqlite"
            store = SQLiteApplicationStore(path)
            store.run_action(
                "tenant_a",
                "customer_segment_analysis",
                "set_customer_segment_list",
                {"customerList": _list_metadata(2, "first", "user_a")},
                actor_user_id="user_a",
            )
            store.run_action(
                "tenant_a",
                "customer_segment_analysis",
                "set_customer_segment_list",
                {"customerList": _list_metadata(1, "second", "user_b")},
                actor_user_id="user_b",
            )
            store.close()

            reopened = SQLiteApplicationStore(path)
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.get_module("tenant_a", "customer_segment_analysis", actor_user_id="user_a")["state"]["customerSegmentList"]["customerCount"], 2)
            self.assertEqual(reopened.get_module("tenant_a", "customer_segment_analysis", actor_user_id="user_b")["state"]["customerSegmentList"]["customerCount"], 1)
            self.assertIsNone(reopened.get_module("tenant_a", "customer_segment_analysis", actor_user_id="user_c")["state"]["customerSegmentList"])

    def test_customer_match_scans_past_first_fifty_thousand_rows(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source = CSVFolderSource(Path(tmpdir))
            path = Path(tmpdir) / "detail.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                stream.write("customer_no,loan_balance\n")
                for index in range(50_001):
                    stream.write(f"C{index:05d},{index}\n")

            _, rows = source.read_rows_matching_values(
                "detail.csv",
                key_field="customer_no",
                values=["C50000"],
            )

            self.assertEqual(rows, [{"customer_no": "C50000", "loan_balance": "50000"}])

    def test_customer_page_data_uses_list_as_left_side_and_excludes_other_customers(self) -> None:
        table = {
            "id": "customer_detail",
            "sourceKey": "customer_detail_source",
            "schemaFingerprint": "customer_schema_v1",
            "contentHash": "customer_content_v1",
            "relativePath": "customer_detail.csv",
            "tableNameEn": "customer_detail",
            "tableNameCn": "客户明细",
            "customerField": "customer_no",
            "fields": [
                {"fieldNameEn": "customer_no", "fieldNameCn": "客户号", "type": "string", "isPrimaryKey": True},
                {"fieldNameEn": "segment", "fieldNameCn": "客群", "type": "string"},
                {"fieldNameEn": "loan_balance", "fieldNameCn": "贷款余额", "type": "decimal", "isMetric": True},
            ],
        }
        table["fields_by_code"] = {field["fieldNameEn"]: field for field in table["fields"]}
        page_data = {
            "id": "page_customer_balance",
            "name": "名单客户贷款余额",
            "institutionScope": "customer_segment",
            "targetPages": ["customer_segment_analysis"],
            "sourceKey": table["sourceKey"],
            "schemaFingerprint": table["schemaFingerprint"],
            "customerKeyField": "customer_no",
            "metricFields": ["loan_balance"],
            "dimensionFields": ["customer_no"],
            "sourceFields": table["fields"],
            "visualizationType": "table",
        }
        acquisition = _AcquisitionService()
        acquisition.csv_source = _CsvSource(_Catalog(table, [
            {"customer_no": "C001", "segment": "A", "loan_balance": "10"},
            {"customer_no": "C002", "segment": "B", "loan_balance": "20"},
            {"customer_no": "C003", "segment": "C", "loan_balance": "30"},
        ]))
        stored = acquisition.object_store.put("tenant_a", b"C002\nC999\nC001\n", ".txt")
        artifact = acquisition.store.create_artifact(
            "tenant_a",
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            content_type="text/plain",
            size_bytes=stored.size_bytes,
            status="active",
            created_by="user_a",
            artifact_type="other",
        )
        applications = InMemoryApplicationStore()
        applications.run_action(
            "tenant_a",
            "customer_segment_analysis",
            "set_customer_segment_list",
            {"customerList": {
                **_list_metadata(3, "projection", "user_a"),
                "artifactId": artifact["artifact_id"],
                "contentHash": artifact["content_hash"],
            }},
            actor_user_id="user_a",
        )
        services = SimpleNamespace(
            application_store=applications,
            data_acquisition_service=acquisition,
        )

        result = read_page_data_rows_payload(
            services,
            tenant_id="tenant_a",
            user_id="user_a",
            page_data_id=page_data["id"],
            consumer="customer_segment_analysis",
            bundle={"page_data": [page_data], "raw_tables": [table]},
            page_data=page_data,
        )

        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["customer_segment"]["customer_count"], 3)
        self.assertEqual(result["customer_segment"]["matched_count"], 2)
        self.assertEqual(result["rows"], [
            {"customer_no": "C002", "loan_balance": "20"},
            {"customer_no": "C999", "loan_balance": ""},
            {"customer_no": "C001", "loan_balance": "10"},
        ])
        self.assertNotIn("C003", {row["customer_no"] for row in result["rows"]})

    def test_page_data_binding_accepts_only_customer_number_as_sole_primary_key(self) -> None:
        customer_table = {
            "id": "customer_detail",
            "sourceKey": "customer_source",
            "schemaFingerprint": "schema_v1",
            "contentHash": "content_v1",
            "relativePath": "customer.csv",
            "tableNameEn": "customer_detail",
            "tableNameCn": "客户明细",
            "fields": [
                {"fieldNameEn": "customer_no", "fieldNameCn": "客户号", "type": "string", "isPrimaryKey": True},
                {"fieldNameEn": "loan_balance", "fieldNameCn": "贷款余额", "type": "decimal", "isMetric": True},
            ],
        }
        handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_CsvSource(_Catalog(customer_table, []))),
        ))
        item = {
            "id": "page_customer",
            "name": "客户余额",
            "institutionScope": "customer_segment",
            "targetPages": ["customer_segment_analysis"],
            "sourceKey": "customer_source",
            "schemaFingerprint": "schema_v1",
            "metricFields": ["loan_balance"],
            "dimensionFields": ["customer_no"],
            "visualizationType": "table",
        }
        bound = _bind_page_data_asset(handler, SimpleNamespace(tenant_id="tenant_a"), item)
        self.assertEqual(bound["customerKeyField"], "customer_no")

        non_customer_table = {
            **customer_table,
            "sourceKey": "order_source",
            "fields": [
                {"fieldNameEn": "order_no", "fieldNameCn": "订单号", "type": "string", "isPrimaryKey": True},
                customer_table["fields"][1],
            ],
        }
        rejected_handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_CsvSource(_Catalog(non_customer_table, []))),
        ))
        with self.assertRaisesRegex(PermissionError, "customer_segment_detail_table_required"):
            _bind_page_data_asset(rejected_handler, SimpleNamespace(tenant_id="tenant_a"), {**item, "sourceKey": "order_source"})

        composite_table = {
            **customer_table,
            "sourceKey": "composite_source",
            "fields": [
                customer_table["fields"][0],
                {"fieldNameEn": "snapshot_date", "fieldNameCn": "快照日期", "type": "date", "isPrimaryKey": True},
                customer_table["fields"][1],
            ],
        }
        composite_handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_CsvSource(_Catalog(composite_table, []))),
        ))
        with self.assertRaisesRegex(PermissionError, "customer_segment_detail_table_required"):
            _bind_page_data_asset(composite_handler, SimpleNamespace(tenant_id="tenant_a"), {**item, "sourceKey": "composite_source"})

    def test_page_data_binding_uses_raw_table_metadata_overlay_for_customer_key(self) -> None:
        raw_table = {
            "id": "customer_detail",
            "sourceKey": "customer_source",
            "schemaFingerprint": "schema_v1",
            "contentHash": "content_v1",
            "relativePath": "customer.csv",
            "tableNameEn": "customer_detail",
            "tableNameCn": "客户明细",
            "fields": [
                {"fieldNameEn": "field_1", "fieldNameCn": "field_1", "type": "string"},
                {"fieldNameEn": "loan_balance", "fieldNameCn": "贷款余额", "type": "decimal", "isMetric": True},
            ],
        }
        overlay = {
            "id": "overlay-1",
            "metadataOverlayVersion": 1,
            "sourceKey": "customer_source",
            "schemaFingerprint": "schema_v1",
            "fields": [
                {"fieldNameEn": "field_1", "fieldNameCn": "客户号", "type": "string", "semanticRole": "dimension", "isPrimaryKey": True},
                {"fieldNameEn": "loan_balance", "fieldNameCn": "贷款余额", "type": "decimal", "semanticRole": "metric", "isMetric": True},
            ],
        }
        item = {
            "id": "page_customer",
            "name": "客户余额",
            "institutionScope": "customer_segment",
            "targetPages": ["customer_segment_analysis"],
            "sourceKey": "customer_source",
            "schemaFingerprint": "schema_v1",
            "metricFields": ["loan_balance"],
            "dimensionFields": ["field_1"],
            "visualizationType": "table",
        }
        rejected_handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_CsvSource(_Catalog(raw_table, []))),
        ))
        with self.assertRaisesRegex(PermissionError, "customer_segment_detail_table_required"):
            _bind_page_data_asset(rejected_handler, SimpleNamespace(tenant_id="tenant_a"), item)

        overlay_handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_CsvSource(_Catalog(raw_table, []))),
            data_asset_store=SimpleNamespace(list_bundle=lambda _tenant_id: {"raw_tables": [overlay]}),
        ))
        bound = _bind_page_data_asset(overlay_handler, SimpleNamespace(tenant_id="tenant_a"), item)
        self.assertEqual(bound["customerKeyField"], "field_1")


if __name__ == "__main__":
    unittest.main()
