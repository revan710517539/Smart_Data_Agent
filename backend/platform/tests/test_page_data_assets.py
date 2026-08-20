from __future__ import annotations

import unittest
from http import HTTPStatus
from types import SimpleNamespace

from backend.platform.api.routes.assets import (
    MULTI_INSTITUTION_DIMENSION,
    _bind_page_data_asset,
    _bind_table_relationship_asset,
    _join_institution_rows,
    _multi_institution_candidates,
    _multi_page_data_source_tables,
    _page_data_source_table,
    _project_page_data_rows,
    read_page_data_rows_payload,
    read_page_data_workspace_payload,
)
from backend.platform.api.routes.application import handle_application_action_post
from backend.platform.application import InMemoryApplicationStore
from backend.platform.application.postgresql_store import _shared_page_layout_module
from backend.platform.assets import InMemoryDataAssetStore
from backend.platform.assets.store import _validate_asset_schema


class _Catalog:
    def __init__(self, tables: list[dict], rows: dict[str, list[dict[str, str]]] | None = None) -> None:
        self._tables = tables
        self._rows = rows or {}

    def table_assets(self) -> list[dict]:
        return self._tables

    def read_rows(self, relative_path: str, *, max_rows: int = 50_000):
        rows = [dict(row) for row in self._rows.get(relative_path, [])[:max_rows]]
        headers = list(rows[0]) if rows else []
        return headers, rows


class _CsvSource:
    def __init__(self, catalog: _Catalog) -> None:
        self._catalog = catalog

    def for_tenant(self, tenant_id: str) -> _Catalog:
        if tenant_id != "tenant_a":
            return _Catalog([])
        return self._catalog


class _MultiCsvSource:
    def __init__(self, catalogs: dict[str, _Catalog]) -> None:
        self._catalogs = catalogs

    def for_tenant(self, tenant_id: str) -> _Catalog:
        return self._catalogs.get(tenant_id, _Catalog([]))


class _TrackingMultiCsvSource(_MultiCsvSource):
    def __init__(self, catalogs: dict[str, _Catalog]) -> None:
        super().__init__(catalogs)
        self.requested_tenants: list[str] = []

    def for_tenant(self, tenant_id: str) -> _Catalog:
        self.requested_tenants.append(tenant_id)
        return super().for_tenant(tenant_id)


class _Lineage:
    def __init__(self, edges: list[dict]) -> None:
        self._edges = edges

    def list_edges(self, tenant_id: str) -> list[dict]:
        del tenant_id
        return self._edges


class _Enforcer:
    def __init__(self, denied: set[str] | None = None) -> None:
        self.denied = denied or set()
        self.requested_tenants: list[str] = []

    def enforce(self, user_id: str, tenant_id: str, resource: str, action: str) -> bool:
        del user_id, resource, action
        self.requested_tenants.append(tenant_id)
        return tenant_id not in self.denied


class _LayoutEnforcer:
    def __init__(self, super_admin: bool) -> None:
        self.super_admin = super_admin

    def has_super_admin_role(self, user_id: str, tenant_id: str) -> bool:
        del user_id, tenant_id
        return self.super_admin


class _ApplicationHandler:
    def __init__(self, *, super_admin: bool) -> None:
        self.headers: dict[str, str] = {}
        self.payload = {"module_key": "dashboard", "action": "set_page_data_layout", "payload": {"assetIds": ["multi_1"]}}
        self.response: tuple[dict, HTTPStatus] | None = None
        self.services = SimpleNamespace(
            application_store=InMemoryApplicationStore(),
            data_asset_store=SimpleNamespace(list_published_bundle=lambda _tenant_id: {"page_data": [{
                "id": "multi_1",
                "institutionScope": "multi_institution",
                "targetPages": ["dashboard"],
            }]}),
            permission_broker=SimpleNamespace(enforcer=_LayoutEnforcer(super_admin)),
        )

    def _read_json(self) -> dict:
        return self.payload

    def _request_context(self, *, payload: dict) -> SimpleNamespace:
        del payload
        return SimpleNamespace(tenant_id="tenant:a", user_id="u_editor")

    def _require_application_permission(self, context: SimpleNamespace, action: str) -> None:
        del context, action

    def _write_audit(self, *args, **kwargs) -> None:
        del args, kwargs

    def _send_json(self, body: dict, status: HTTPStatus = HTTPStatus.OK, **kwargs) -> None:
        del kwargs
        self.response = (body, status)


class PageDataAssetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.table = {
            "id": "csv_table_1",
            "sourceKey": "source_1",
            "schemaFingerprint": "schema_1",
            "contentHash": "content_1",
            "relativePath": "reports/weekly.csv",
            "tableNameEn": "weekly_report",
            "tableNameCn": "经营周报底表",
            "fields": [
                {"fieldNameEn": "report_date", "fieldNameCn": "日期", "type": "string", "isTime": True},
                {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "isMetric": True},
            ],
        }
        self.asset = {
            "id": "page_data_1",
            "name": "周报放款趋势",
            "sourceKey": "source_1",
            "sourceTableName": "伪造名称",
            "schemaFingerprint": "schema_1",
            "sourceFields": self.table["fields"],
            "institutionScope": "single_institution",
            "targetPages": ["weekly_report"],
            "metricFields": ["loan_amount"],
            "dimensionFields": ["report_date"],
            "visualizationType": "line",
        }

    def _handler(self):
        source = _CsvSource(_Catalog([self.table]))
        return SimpleNamespace(
            services=SimpleNamespace(
                data_acquisition_service=SimpleNamespace(csv_source=source),
            ),
        )

    def _multi_handler(self, *, second_schema: str = "schema_1", include_relationship: bool = True, denied: set[str] | None = None):
        second = {
            **self.table,
            "id": "csv_table_2",
            "sourceKey": "source_2",
            "relativePath": "reports/weekly_b.csv",
            "schemaFingerprint": second_schema,
        }
        edge = {
            "source_type": "raw_table",
            "source_id": "tenant:a::source_1",
            "target_type": "raw_table",
            "target_id": "tenant:b::source_2",
            "metadata": {
                "relationshipScope": "multi_institution",
                "sourceTenantId": "tenant:a",
                "sourceSourceKey": "source_1",
                "targetTenantId": "tenant:b",
                "targetSourceKey": "source_2",
            },
        }
        return SimpleNamespace(
            services=SimpleNamespace(
                data_acquisition_service=SimpleNamespace(csv_source=_MultiCsvSource({
                    "tenant:a": _Catalog([self.table]),
                    "tenant:b": _Catalog([second]),
                })),
                lineage_store=_Lineage([edge] if include_relationship else []),
                access_service=SimpleNamespace(session_for_user=lambda *_args, **_kwargs: {
                    "institutions": ["a", "b"],
                    "institution": "a",
                }),
                permission_broker=SimpleNamespace(enforcer=_Enforcer(denied)),
            ),
        )

    def test_schema_requires_existing_disjoint_metric_and_dimension_fields(self) -> None:
        _validate_asset_schema("page_data", self.asset)
        with self.assertRaisesRegex(ValueError, "page_data_metric_dimension_overlap"):
            _validate_asset_schema("page_data", {**self.asset, "dimensionFields": ["loan_amount"]})
        with self.assertRaisesRegex(ValueError, "page_data_metric_fields_invalid"):
            _validate_asset_schema("page_data", {**self.asset, "metricFields": ["unknown_field"]})

    def test_binding_uses_authoritative_current_tenant_catalog_metadata(self) -> None:
        bound = _bind_page_data_asset(self._handler(), SimpleNamespace(tenant_id="tenant_a"), self.asset)
        self.assertEqual(bound["sourceTableName"], "经营周报底表")
        self.assertEqual(bound["sourceRelativePath"], "reports/weekly.csv")
        self.assertEqual(bound["contentHash"], "content_1")
        self.assertEqual(bound["sourceFields"], self.table["fields"])

    def test_replaced_schema_fails_closed(self) -> None:
        with self.assertRaisesRegex(PermissionError, "page_data_source_schema_changed"):
            _page_data_source_table(self._handler(), "tenant_a", {**self.asset, "schemaFingerprint": "stale"})

    def test_original_csv_headers_are_projected_to_stable_field_codes(self) -> None:
        rows = _project_page_data_rows(
            self.table,
            [{"日期": "2026-08-01", "放款金额": "125.5"}],
            ["report_date", "loan_amount"],
        )
        self.assertEqual(rows, [{"report_date": "2026-08-01", "loan_amount": "125.5"}])

    def test_active_page_data_is_published_and_layout_order_is_persisted(self) -> None:
        assets = InMemoryDataAssetStore(seed_defaults=False)
        saved = assets.upsert_item("tenant_a", "page_data", self.asset, updated_by="u_admin", lifecycle_status="active")
        self.assertEqual([item["id"] for item in assets.list_published_bundle("tenant_a")["page_data"]], [saved["id"]])

        applications = InMemoryApplicationStore()
        response = applications.run_action(
            "tenant_a",
            "weekly_report",
            "set_page_data_layout",
            {"assetIds": [saved["id"]]},
            actor_user_id="u_admin",
        )
        self.assertEqual(response["module"]["state"]["pageDataLayout"], [saved["id"]])
        noted = applications.run_action(
            "tenant_a",
            "weekly_report",
            "set_page_data_layout",
            {
                "assetIds": [saved["id"]],
                "notes": [{"id": "note_1", "sourceAssetId": saved["id"], "noteTitle": "结论", "noteBody": "放款金额上升", "config": {}}],
            },
            actor_user_id="u_admin",
        )
        self.assertEqual(noted["module"]["state"]["pageDataNotes"][0]["sourceAssetId"], saved["id"])
        self.assertEqual(noted["module"]["state"]["pageDataNotes"][0]["noteTitle"], "结论")
        sticky = applications.run_action(
            "tenant_a",
            "weekly_report",
            "set_page_sticky_note",
            {
                "note": {
                    "visible": True,
                    "items": [
                        {"id": "p1", "type": "paragraph", "text": "周报便签", "html": "<strong>周报便签</strong><script>alert(1)</script>"},
                        {"id": "img1", "type": "image", "src": "/api/attachments/content?attachment_id=a1", "name": "截图", "attachmentId": "a1", "width": 320, "height": 180},
                    ],
                }
            },
            actor_user_id="u_admin",
        )
        self.assertTrue(sticky["module"]["state"]["pageStickyNote"]["visible"])
        self.assertEqual(sticky["module"]["state"]["pageStickyNote"]["items"][0]["text"], "周报便签")
        self.assertEqual(sticky["module"]["state"]["pageStickyNote"]["items"][0]["html"], "<strong>周报便签</strong>alert(1)")
        self.assertEqual(sticky["module"]["state"]["pageStickyNote"]["items"][1]["type"], "image")
        analysis_note = applications.run_action(
            "tenant_a",
            "self_analysis",
            "set_page_sticky_note",
            {
                "surface": "visual_report:rpt_1",
                "note": {"visible": True, "items": [{"id": "p1", "type": "paragraph", "text": "报表便签"}]},
            },
            actor_user_id="u_admin",
        )
        self.assertEqual(analysis_note["module"]["state"]["stickyNotes"]["visual_report:rpt_1"]["items"][0]["text"], "报表便签")
        viewer_notes = applications.run_action(
            "tenant_a",
            "weekly_report",
            "set_page_data_notes",
            {
                "notes": [{"id": "note_viewer", "sourceAssetId": saved["id"], "type": "text", "noteTitle": "查看即可写", "noteBody": "", "config": {}}],
            },
            actor_user_id="u_viewer",
        )
        self.assertEqual(viewer_notes["module"]["state"]["pageDataNotes"][-1]["noteTitle"], "查看即可写")
        with self.assertRaisesRegex(ValueError, "page_data_layout_invalid"):
            applications.run_action(
                "tenant_a",
                "weekly_report",
                "set_page_data_layout",
                {"assetIds": [saved["id"], saved["id"]]},
                actor_user_id="u_admin",
            )

    def test_multi_institution_candidates_require_explicit_relationship_and_identical_schema(self) -> None:
        context = SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin")
        candidates = _multi_institution_candidates(self._multi_handler(), context)
        self.assertEqual(len(candidates), 1)
        self.assertEqual([source["tenantId"] for source in candidates[0]["sources"]], ["tenant:a", "tenant:b"])
        self.assertEqual(_multi_institution_candidates(self._multi_handler(include_relationship=False), context), [])
        self.assertEqual(_multi_institution_candidates(self._multi_handler(second_schema="schema_2"), context), [])

    def test_multi_institution_binding_uses_authoritative_relationship_sources(self) -> None:
        context = SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin")
        handler = self._multi_handler()
        candidate = _multi_institution_candidates(handler, context)[0]
        bound = _bind_page_data_asset(handler, context, {
            "id": "page_data_multi_1",
            "name": "多机构放款趋势",
            "institutionScope": "multi_institution",
            "relationshipGroupId": candidate["id"],
            "sourceKey": candidate["id"],
            "sourceTableName": "不可信名称",
            "schemaFingerprint": "不可信结构",
            "sourceFields": [],
            "targetPages": ["dashboard"],
            "metricFields": ["loan_amount"],
            "dimensionFields": ["report_date"],
            "visualizationType": "line",
        })
        self.assertEqual(bound["relationshipGroupId"], candidate["id"])
        self.assertEqual(bound["targetPages"], ["dashboard"])
        self.assertEqual(bound["dimensionFields"], [MULTI_INSTITUTION_DIMENSION, "report_date"])
        self.assertEqual(len(bound["institutionSources"]), 2)
        _validate_asset_schema("page_data", bound)

    def test_multi_institution_source_read_rechecks_authorization_and_schema(self) -> None:
        context = SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin")
        handler = self._multi_handler()
        candidate = _multi_institution_candidates(handler, context)[0]
        page_data = {
            "schemaFingerprint": candidate["schemaFingerprint"],
            "institutionSources": candidate["sources"],
        }
        self.assertEqual(len(_multi_page_data_source_tables(handler, context, page_data)), 2)
        with self.assertRaisesRegex(PermissionError, "multi_institution_page_data_sources_unavailable"):
            _multi_page_data_source_tables(self._multi_handler(denied={"tenant:b"}), context, page_data)
        with self.assertRaisesRegex(PermissionError, "multi_institution_page_data_source_schema_changed"):
            _multi_page_data_source_tables(self._multi_handler(second_schema="schema_2"), context, page_data)

    def test_table_relationship_rebinds_labels_and_supports_multiple_tables_per_institution(self) -> None:
        table_a_detail = {
            **self.table,
            "id": "csv_table_a_detail",
            "sourceKey": "source_a_detail",
            "relativePath": "reports/detail.csv",
            "tableNameCn": "放款明细",
            "fields": [
                {"fieldNameEn": "report_date", "fieldNameCn": "日期", "type": "string", "isPrimaryKey": True},
                {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "isMetric": True},
            ],
        }
        table_b = {**self.table, "id": "csv_table_b", "sourceKey": "source_b", "relativePath": "reports/b.csv"}
        store = InMemoryDataAssetStore(seed_defaults=False)
        handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_MultiCsvSource({
                "tenant:a": _Catalog([self.table, table_a_detail]),
                "tenant:b": _Catalog([table_b]),
            })),
            data_asset_store=store,
            lineage_store=_Lineage([]),
            access_service=SimpleNamespace(session_for_user=lambda *_args, **_kwargs: {"institutions": ["a", "b"], "institution": "a"}),
            permission_broker=SimpleNamespace(enforcer=_Enforcer()),
        ))
        context = SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin")
        requested = {
            "id": "relationship_1",
            "name": "多机构信贷关系",
            "relationshipScope": "multi_institution",
            "nodes": [
                {"id": "a_main", "tenantId": "tenant:a", "institutionName": "伪造A", "sourceKey": "source_1", "schemaFingerprint": "schema_1", "position": {"x": 10, "y": 10}},
                {"id": "a_detail", "tenantId": "tenant:a", "institutionName": "伪造A", "sourceKey": "source_a_detail", "schemaFingerprint": "schema_1", "position": {"x": 300, "y": 10}},
                {"id": "b_main", "tenantId": "tenant:b", "institutionName": "伪造B", "sourceKey": "source_b", "schemaFingerprint": "schema_1", "position": {"x": 600, "y": 10}},
            ],
            "edges": [
                {"id": "local", "sourceNodeId": "a_main", "sourceField": "report_date", "targetNodeId": "a_detail", "targetField": "report_date"},
                {"id": "cross", "sourceNodeId": "a_main", "sourceField": "report_date", "targetNodeId": "b_main", "targetField": "report_date"},
            ],
        }
        bound = _bind_table_relationship_asset(handler, context, requested)
        self.assertEqual([node["institutionName"] for node in bound["nodes"]], ["a", "a", "b"])
        self.assertEqual(bound["institutionCount"], 2)
        self.assertEqual(bound["tableCount"], 3)
        saved = store.upsert_item("tenant:a", "table_relationship", bound, updated_by="u_super_admin", lifecycle_status="active")
        candidates = _multi_institution_candidates(handler, context)
        self.assertEqual(candidates[0]["id"], saved["id"])
        self.assertEqual(candidates[0]["institutionCount"], 2)
        self.assertEqual(len(candidates[0]["sources"]), 3)
        self.assertIn("loan_amount", [field["fieldNameEn"] for field in candidates[0]["fields"]])

    def test_table_relationship_save_scans_only_referenced_tenants(self) -> None:
        table_b = {**self.table, "id": "csv_table_b", "sourceKey": "source_b", "relativePath": "reports/b.csv"}
        table_c = {**self.table, "id": "csv_table_c", "sourceKey": "source_c", "relativePath": "reports/c.csv"}
        csv_source = _TrackingMultiCsvSource({
            "tenant:a": _Catalog([self.table]),
            "tenant:b": _Catalog([table_b]),
            "tenant:c": _Catalog([table_c]),
        })
        enforcer = _Enforcer()
        handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=csv_source),
            data_asset_store=InMemoryDataAssetStore(seed_defaults=False),
            lineage_store=_Lineage([]),
            access_service=SimpleNamespace(session_for_user=lambda *_args, **_kwargs: {"institutions": ["a", "b", "c"], "institution": "a"}),
            permission_broker=SimpleNamespace(enforcer=enforcer),
        ))
        bound = _bind_table_relationship_asset(
            handler,
            SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin"),
            {
                "name": "仅扫描已选机构",
                "nodes": [
                    {"id": "a", "tenantId": "tenant:a", "sourceKey": "source_1", "schemaFingerprint": "schema_1"},
                    {"id": "b", "tenantId": "tenant:b", "sourceKey": "source_b", "schemaFingerprint": "schema_1"},
                ],
                "edges": [{"sourceNodeId": "a", "sourceField": "report_date", "targetNodeId": "b", "targetField": "report_date"}],
            },
        )
        self.assertEqual(bound["institutionCount"], 2)
        self.assertEqual(csv_source.requested_tenants, ["tenant:a", "tenant:b"])
        self.assertNotIn("tenant:c", csv_source.requested_tenants)
        self.assertEqual(set(enforcer.requested_tenants), {"tenant:a", "tenant:b"})

    def test_table_relationship_rejects_non_primary_key_and_disconnected_local_tables(self) -> None:
        handler = self._multi_handler()
        handler.services.data_asset_store = InMemoryDataAssetStore(seed_defaults=False)
        context = SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin")
        requested = {
            "name": "错误关系",
            "relationshipScope": "multi_institution",
            "nodes": [
                {"id": "a", "tenantId": "tenant:a", "sourceKey": "source_1", "schemaFingerprint": "schema_1"},
                {"id": "b", "tenantId": "tenant:b", "sourceKey": "source_2", "schemaFingerprint": "schema_1"},
            ],
            "edges": [{"id": "bad", "sourceNodeId": "a", "sourceField": "loan_amount", "targetNodeId": "b", "targetField": "loan_amount"}],
        }
        with self.assertRaisesRegex(ValueError, "table_relationship_edge_primary_key_required"):
            _bind_table_relationship_asset(handler, context, requested)

    def test_same_institution_relationship_is_server_tagged_single_and_not_a_multi_page_candidate(self) -> None:
        fields = [
            {"fieldNameEn": "report_date", "fieldNameCn": "日期", "type": "string", "isPrimaryKey": True},
            {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "isMetric": True},
        ]
        first = {**self.table, "fields": fields}
        second = {
            **first,
            "id": "csv_table_a_detail",
            "sourceKey": "source_a_detail",
            "relativePath": "reports/detail.csv",
        }
        store = InMemoryDataAssetStore(seed_defaults=False)
        handler = SimpleNamespace(services=SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_MultiCsvSource({"tenant:a": _Catalog([first, second])})),
            data_asset_store=store,
            lineage_store=_Lineage([]),
            access_service=SimpleNamespace(session_for_user=lambda *_args, **_kwargs: {"institutions": ["a"], "institution": "a"}),
            permission_broker=SimpleNamespace(enforcer=_Enforcer()),
        ))
        context = SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin")
        bound = _bind_table_relationship_asset(handler, context, {
            "id": "relationship_single",
            "name": "本机构多表关系",
            "relationshipScope": "multi_institution",
            "nodes": [
                {"id": "main", "tenantId": "tenant:a", "sourceKey": "source_1", "schemaFingerprint": "schema_1"},
                {"id": "detail", "tenantId": "tenant:a", "sourceKey": "source_a_detail", "schemaFingerprint": "schema_1"},
            ],
            "edges": [{"sourceNodeId": "main", "sourceField": "report_date", "targetNodeId": "detail", "targetField": "report_date"}],
        })
        self.assertEqual(bound["relationshipScope"], "single_institution")
        store.upsert_item("tenant:a", "table_relationship", bound, updated_by="u_super_admin", lifecycle_status="active")
        self.assertEqual(_multi_institution_candidates(handler, context), [])

    def test_join_institution_rows_uses_configured_primary_key(self) -> None:
        left = {**self.table, "fields": [{"fieldNameEn": "id", "fieldNameCn": "编号", "type": "string"}, {"fieldNameEn": "loan_amount", "fieldNameCn": "金额", "type": "decimal"}]}
        right = {**self.table, "fields": [{"fieldNameEn": "id", "fieldNameCn": "编号", "type": "string"}, {"fieldNameEn": "risk", "fieldNameCn": "风险", "type": "string"}]}
        rows = _join_institution_rows(
            [
                ({"nodeId": "left"}, left, [{"编号": "1", "金额": "100"}, {"编号": "2", "金额": "200"}]),
                ({"nodeId": "right"}, right, [{"编号": "1", "风险": "低"}]),
            ],
            [{"sourceNodeId": "left", "sourceField": "id", "targetNodeId": "right", "targetField": "id"}],
        )
        self.assertEqual(rows, [{"id": "1", "risk": "低", "loan_amount": "100"}])

    def test_analytical_consumers_read_only_governed_multi_page_data(self) -> None:
        fields = [
            {"fieldNameEn": "report_date", "fieldNameCn": "日期", "type": "string", "isPrimaryKey": True},
            {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "isMetric": True},
        ]
        table_a = {**self.table, "fields": fields}
        table_b = {
            **table_a,
            "id": "csv_table_b",
            "sourceKey": "source_b",
            "relativePath": "reports/weekly_b.csv",
        }
        store = InMemoryDataAssetStore(seed_defaults=False)
        services = SimpleNamespace(
            data_acquisition_service=SimpleNamespace(csv_source=_MultiCsvSource({
                "tenant:a": _Catalog([table_a], {table_a["relativePath"]: [{"日期": "2026-08-01", "放款金额": "100"}]}),
                "tenant:b": _Catalog([table_b], {table_b["relativePath"]: [{"日期": "2026-08-01", "放款金额": "200"}]}),
            })),
            data_asset_store=store,
            lineage_store=_Lineage([]),
            access_service=SimpleNamespace(session_for_user=lambda *_args, **_kwargs: {"institutions": ["a", "b"], "institution": "a"}),
            permission_broker=SimpleNamespace(enforcer=_Enforcer()),
        )
        handler = SimpleNamespace(services=services)
        context = SimpleNamespace(tenant_id="tenant:a", user_id="u_super_admin")
        relationship = _bind_table_relationship_asset(handler, context, {
            "id": "relationship_multi_read",
            "name": "跨机构放款关系",
            "nodes": [
                {"id": "a", "tenantId": "tenant:a", "sourceKey": "source_1", "schemaFingerprint": "schema_1"},
                {"id": "b", "tenantId": "tenant:b", "sourceKey": "source_b", "schemaFingerprint": "schema_1"},
            ],
            "edges": [{"id": "cross", "sourceNodeId": "a", "sourceField": "report_date", "targetNodeId": "b", "targetField": "report_date"}],
        })
        store.upsert_item("tenant:a", "table_relationship", relationship, updated_by="u_super_admin", lifecycle_status="active")
        candidate = _multi_institution_candidates(handler, context)[0]
        page_data = _bind_page_data_asset(handler, context, {
            "id": "page_data_multi_read",
            "name": "跨机构放款页面数据",
            "institutionScope": "multi_institution",
            "relationshipGroupId": candidate["id"],
            "sourceKey": candidate["id"],
            "schemaFingerprint": candidate["schemaFingerprint"],
            "sourceFields": [],
            "targetPages": ["dashboard"],
            "metricFields": ["loan_amount"],
            "dimensionFields": ["report_date"],
            "visualizationType": "line",
        })
        store.upsert_item("tenant:a", "page_data", page_data, updated_by="u_super_admin", lifecycle_status="active")

        for consumer in ("self_analysis", "visual_report", "my_reports"):
            payload = read_page_data_rows_payload(
                services,
                tenant_id="tenant:a",
                user_id="u_super_admin",
                page_data_id="page_data_multi_read",
                consumer=consumer,
            )
            self.assertEqual(payload["relationship_group_id"], "relationship_multi_read")
            self.assertEqual(payload["schema_fingerprint"], candidate["schemaFingerprint"])
            self.assertEqual(
                payload["rows"],
                [
                    {"__institution_name": "a", "report_date": "2026-08-01", "loan_amount": "100"},
                    {"__institution_name": "b", "report_date": "2026-08-01", "loan_amount": "200"},
                ],
            )

        single = store.upsert_item("tenant:a", "page_data", self.asset, updated_by="u_super_admin", lifecycle_status="active")
        with self.assertRaisesRegex(PermissionError, "page_data_scope_unavailable_for_analysis"):
            read_page_data_rows_payload(
                services,
                tenant_id="tenant:a",
                user_id="u_super_admin",
                page_data_id=str(single["id"]),
                consumer="self_analysis",
            )

    def test_page_data_workspace_returns_assets_layout_and_rows_together(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        bound = _bind_page_data_asset(self._handler(), SimpleNamespace(tenant_id="tenant_a"), self.asset)
        saved = store.upsert_item("tenant_a", "page_data", bound, updated_by="u_admin", lifecycle_status="active")
        applications = InMemoryApplicationStore()
        applications.run_action(
            "tenant_a",
            "weekly_report",
            "set_page_data_layout",
            {"assetIds": [saved["id"]]},
            actor_user_id="u_admin",
        )
        catalog = _Catalog([self.table], {self.table["relativePath"]: [{"日期": "2026-08-01", "放款金额": "125.5"}]})
        payload = read_page_data_workspace_payload(
            SimpleNamespace(
                data_asset_store=store,
                application_store=applications,
                data_acquisition_service=SimpleNamespace(csv_source=_CsvSource(catalog)),
            ),
            tenant_id="tenant_a",
            user_id="u_admin",
            page_code="weekly_report",
        )
        self.assertEqual(payload["layout"], [saved["id"]])
        self.assertEqual(payload["assets"][0]["id"], saved["id"])
        self.assertEqual(payload["rows"][saved["id"]]["row_count"], 1)
        self.assertEqual(payload["rows"][saved["id"]]["rows"][0]["loan_amount"], "125.5")

    def test_dashboard_layout_action_requires_super_admin(self) -> None:
        denied = _ApplicationHandler(super_admin=False)
        handle_application_action_post(denied)
        self.assertEqual(denied.response[1], HTTPStatus.FORBIDDEN)
        self.assertEqual(denied.services.application_store.get_module("tenant:a", "dashboard", "u_editor")["state"]["pageDataLayout"], [])

        allowed = _ApplicationHandler(super_admin=True)
        handle_application_action_post(allowed)
        self.assertEqual(allowed.response[1], HTTPStatus.OK)
        self.assertEqual(allowed.response[0]["module"]["state"]["pageDataLayout"], ["multi_1"])

    def test_postgresql_shared_state_contract_is_limited_to_page_layout_modules(self) -> None:
        self.assertTrue(_shared_page_layout_module("dashboard"))
        self.assertTrue(_shared_page_layout_module("institution_supervision"))
        self.assertFalse(_shared_page_layout_module("weekly_report"))


if __name__ == "__main__":
    unittest.main()
