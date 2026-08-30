from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.platform.api.routes.application import _bind_visual_report_payload, _prepare_visual_report_upsert_payload
from backend.platform.api.routes.assets import handle_data_assets_get
from backend.platform.application import InMemoryApplicationStore
from backend.platform.visualization_config import normalize_chart_style, normalize_table_metric_enhancements


class _Catalog:
    def table_assets(self) -> list[dict]:
        return [
            {
                "id": "raw_loans",
                "sourceKey": "source_loans",
                "schemaFingerprint": "schema_current",
                "tableNameEn": "loan_fact",
                "tableNameCn": "贷款事实表",
                "fields": [
                    {"fieldNameEn": "branch", "fieldNameCn": "机构", "type": "string"},
                    {"fieldNameEn": "balance", "fieldNameCn": "余额", "type": "decimal", "isMetric": True},
                ],
            }
        ]


class _EmptyCsvSource:
    def for_tenant(self, tenant_id: str) -> SimpleNamespace:
        del tenant_id
        return SimpleNamespace(table_assets=lambda: [])


class _CsvSource:
    def for_tenant(self, tenant_id: str) -> _Catalog:
        if tenant_id != "tenant_a":
            raise AssertionError("unexpected tenant")
        return _Catalog()


class _RotatedCatalog(_Catalog):
    def table_assets(self) -> list[dict]:
        asset = super().table_assets()[0]
        return [{**asset, "id": "raw_loans_20260816"}]


class _RotatedCsvSource(_CsvSource):
    def for_tenant(self, tenant_id: str) -> _Catalog:
        if tenant_id != "tenant_a":
            raise AssertionError("unexpected tenant")
        return _RotatedCatalog()


class _LogicalTitleCatalog(_Catalog):
    def table_assets(self) -> list[dict]:
        asset = super().table_assets()[0]
        return [{
            **asset,
            "id": "csv_new_delivery_hash",
            "sourceKey": "source_loans_current",
            "tableNameCn": "标品双周会周度sql_2026-05-06",
            "tableNameEn": "csv_newhash12ab",
            "fileName": "标品双周会周度sql_2026-05-06.csv",
            "relativePath": "华兴银行/标品双周会周度sql_2026-05-06.csv",
        }]


class _LogicalTitleCsvSource(_CsvSource):
    def for_tenant(self, tenant_id: str) -> _Catalog:
        if tenant_id != "tenant_a":
            raise AssertionError("unexpected tenant")
        return _LogicalTitleCatalog()


class _VisualizationCatalog(_Catalog):
    catalog_ready = True


class VisualReportsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = {
            "id": "visual_report_1",
            "title": "支行余额看板",
            "cards": [
                {
                    "id": "chart_1",
                    "title": "余额明细",
                    "type": "table",
                    "dataset": {"id": "raw_loans", "kind": "raw", "name": "伪造名称", "rows": [{"secret": "never store"}]},
                    "config": {
                        "metricFields": ["balance"],
                        "dimensionFields": ["branch"],
                        "metricRankings": [{"metricField": "balance", "direction": "desc"}],
                        "metricFormats": [
                            {"metricField": "balance", "percent": True, "decimalPlaces": 3},
                            {"metricField": "missing", "percent": True, "decimalPlaces": 99},
                        ],
                        "metricProgress": [{
                            "metricField": "balance",
                            "denominatorRules": [{"id": "denominator-1", "field": "branch", "operator": "not_in", "values": ["总行", "忽略"]}],
                            "color": "#2ca66f",
                            "colorEnd": "#77bb99",
                            "colorMode": "gradient",
                            "associationRules": [{
                                "id": "association-1",
                                "source": "metric",
                                "operator": "gt",
                                "threshold": 0,
                                "targetField": "balance",
                                "style": "value",
                                "color": "#116644",
                                "replacementValue": "有效",
                            }],
                        }],
                        "calculatedColumns": [{"id": "calculated-1", "name": "折算余额", "position": 2, "expression": "[balance] / 2"}],
                        "tableStyle": {
                            "templateId": "excel-navy",
                            "headerBackground": "#245680",
                            "headerTextColor": "#ffffff",
                            "headerBorderColor": "not-a-color",
                            "bodyBackground": "#ffffff",
                            "alternateRowBackground": "#eef5fb",
                            "bodyTextColor": "#26394a",
                            "borderColor": "#b8d0e6",
                            "accentColor": "#e3b341",
                            "totalBackground": "#245680",
                            "totalTextColor": "#ffffff",
                            "fontFamily": "humanist",
                            "density": "compact",
                            "bandedRows": True,
                            "emphasizeFirstColumn": True,
                        },
                        "chartStyle": {
                            "templateId": "chart-cloud-blue",
                            "backgroundColor": "#f8fafd",
                            "plotBackgroundColor": "#ffffff",
                            "textColor": "#273142",
                            "mutedTextColor": "#737c89",
                            "gridColor": "#e6eaf0",
                            "axisColor": "#c9d0da",
                            "palette": ["#3370ff", "#38a7a0"],
                            "fontFamily": "humanist",
                            "chartHeight": "expanded",
                            "lineWidth": 2.2,
                            "pointRadius": 2.6,
                            "barRadius": 5,
                            "barWidth": "wide",
                            "areaOpacity": 0.12,
                        },
                    },
                }
            ],
            "destinations": ["mine"],
        }

    def test_column_max_progress_mode_persists_without_row_selector(self) -> None:
        rankings, progress, calculated = normalize_table_metric_enhancements(
            {
                "metricProgress": [
                    {
                        "metricField": "balance",
                        "denominatorMode": "column_max",
                        "denominatorRules": [],
                        "color": "#5a9bd5",
                        "colorEnd": "#d7e8f6",
                        "colorMode": "gradient",
                        "associationRules": [],
                    },
                    {
                        "metricField": "missing",
                        "denominatorMode": "column_max",
                        "denominatorRules": [],
                    },
                ]
            },
            ["balance"],
            ["branch"],
        )

        self.assertEqual(rankings, [])
        self.assertEqual(calculated, [])
        self.assertEqual(progress, [{
            "metricField": "balance",
            "denominatorMode": "column_max",
            "denominatorRules": [],
            "color": "#5A9BD5",
            "colorEnd": "#D7E8F6",
            "colorMode": "gradient",
            "associationRules": [],
        }])

    def test_invalid_progress_mode_without_row_selector_fails_closed(self) -> None:
        _, progress, _ = normalize_table_metric_enhancements(
            {"metricProgress": [{"metricField": "balance", "denominatorMode": "unknown", "denominatorRules": []}]},
            ["balance"],
            ["branch"],
        )
        self.assertEqual(progress, [])

    def test_reverse_gradient_progress_mode_is_preserved(self) -> None:
        _, progress, _ = normalize_table_metric_enhancements(
            {
                "metricProgress": [{
                    "metricField": "balance",
                    "denominatorMode": "column_max",
                    "denominatorRules": [],
                    "color": "#b7ebd7",
                    "colorEnd": "#00a870",
                    "colorMode": "reverse_gradient",
                    "associationRules": [],
                }]
            },
            ["balance"],
            ["branch"],
        )

        self.assertEqual(progress[0]["colorMode"], "reverse_gradient")

    def test_chart_style_normalization_is_bounded_and_data_free(self) -> None:
        style = normalize_chart_style({
            "templateId": "custom-chart",
            "palette": ["#123456", "invalid", "#abcdef"],
            "fontFamily": "unknown",
            "chartHeight": "expanded",
            "lineWidth": 99,
            "areaOpacity": -2,
            "rows": [{"secret": "never store"}],
        })
        self.assertEqual(style["palette"], ["#123456", "#ABCDEF"])
        self.assertEqual(style["fontFamily"], "system")
        self.assertEqual(style["chartHeight"], "expanded")
        self.assertEqual(style["lineWidth"], 4.0)
        self.assertEqual(style["areaOpacity"], 0.0)
        self.assertNotIn("rows", style)

    def test_route_rebinds_dataset_to_current_tenant_catalog(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(list_published_bundle=lambda tenant_id: {"topic_tables": []}),
                data_acquisition_service=SimpleNamespace(csv_source=_CsvSource()),
            )
        )
        bound = _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": self.report})
        dataset = bound["report"]["cards"][0]["dataset"]
        self.assertEqual(dataset["name"], "贷款事实表")
        self.assertEqual(dataset["schemaFingerprint"], "schema_current")
        self.assertNotIn("rows", dataset)

    def test_store_bounds_config_and_filters_reports_by_owner(self) -> None:
        store = InMemoryApplicationStore()
        saved = store.run_action(
            "tenant_a",
            "self_analysis",
            "upsert_visual_report",
            {"report": self.report},
            actor_user_id="u_owner",
        )["result"]["report"]
        self.assertEqual(saved["ownerUserId"], "u_owner")
        self.assertEqual(saved["cards"][0]["type"], "table")
        self.assertNotIn("rows", saved["cards"][0]["dataset"])
        self.assertEqual(saved["cards"][0]["config"]["metricRankings"][0]["direction"], "desc")
        self.assertEqual(saved["cards"][0]["config"]["metricFormats"], [{"metricField": "balance", "percent": True, "decimalPlaces": 3}])
        self.assertEqual(saved["cards"][0]["config"]["metricProgress"][0]["denominatorRules"][0]["values"], ["总行"])
        self.assertEqual(saved["cards"][0]["config"]["metricProgress"][0]["denominatorRules"][0]["operator"], "in")
        self.assertEqual(saved["cards"][0]["config"]["metricProgress"][0]["colorEnd"], "#77BB99")
        self.assertEqual(saved["cards"][0]["config"]["metricProgress"][0]["associationRules"][0]["replacementValue"], "有效")
        self.assertEqual(saved["cards"][0]["config"]["calculatedColumns"][0]["expression"], "[balance] / 2")
        self.assertEqual(saved["cards"][0]["config"]["tableStyle"]["templateId"], "excel-navy")
        self.assertEqual(saved["cards"][0]["config"]["tableStyle"]["headerBackground"], "#245680")
        self.assertEqual(saved["cards"][0]["config"]["tableStyle"]["headerBorderColor"], "#DCE7DF")
        self.assertEqual(saved["cards"][0]["config"]["tableStyle"]["fontFamily"], "humanist")
        self.assertTrue(saved["cards"][0]["config"]["tableStyle"]["emphasizeFirstColumn"])
        self.assertEqual(saved["cards"][0]["config"]["chartStyle"]["templateId"], "chart-cloud-blue")
        self.assertEqual(saved["cards"][0]["config"]["chartStyle"]["palette"], ["#3370FF", "#38A7A0"])
        self.assertEqual(saved["cards"][0]["config"]["chartStyle"]["chartHeight"], "expanded")
        owner_state = store.get_module("tenant_a", "self_analysis", actor_user_id="u_owner")["state"]
        other_state = store.get_module("tenant_a", "self_analysis", actor_user_id="u_other")["state"]
        self.assertEqual([report["id"] for report in owner_state["visualReports"]], ["visual_report_1"])
        self.assertEqual(other_state["visualReports"], [])
        store.run_action(
            "tenant_a",
            "self_analysis",
            "upsert_visual_report",
            {"report": {**self.report, "id": "visual_report_weekly", "destinations": ["mine", "weekly"]}},
            actor_user_id="u_owner",
        )
        shared = store.get_module("tenant_a", "self_analysis", actor_user_id="u_other")["state"]
        self.assertIn("visual_report_weekly", [report["id"] for report in shared["visualReports"]])
        store.run_action(
            "tenant_a",
            "self_analysis",
            "upsert_visual_report",
            {"report": {**self.report, "id": "visual_report_weekly", "destinations": ["mine"]}},
            actor_user_id="u_owner",
        )
        with self.assertRaisesRegex(PermissionError, "visual_report_owner_required"):
            store.run_action(
                "tenant_a",
                "self_analysis",
                "delete_visual_report",
                {"reportId": "visual_report_1"},
                actor_user_id="u_other",
            )

    def test_removing_weekly_destination_skips_dataset_rebind(self) -> None:
        store = InMemoryApplicationStore()
        saved = store.run_action(
            "tenant_a",
            "self_analysis",
            "upsert_visual_report",
            {"report": {**self.report, "id": "visual_report_weekly", "destinations": ["mine", "weekly"]}},
            actor_user_id="u_owner",
        )["result"]["report"]
        handler = SimpleNamespace(
            services=SimpleNamespace(
                application_store=store,
                permission_broker=SimpleNamespace(enforcer=SimpleNamespace(can_manage_shared_visual=lambda *_args: False)),
                data_asset_store=SimpleNamespace(list_published_bundle=lambda _tenant_id: {"topic_tables": [], "page_data": []}),
                data_acquisition_service=SimpleNamespace(csv_source=_EmptyCsvSource()),
            )
        )
        context = SimpleNamespace(user_id="u_owner", tenant_id="tenant_a")
        with self.assertRaisesRegex(PermissionError, "visual_report_dataset_unavailable"):
            _bind_visual_report_payload(handler, context, {"report": saved})

        prepared = _prepare_visual_report_upsert_payload(
            handler,
            context,
            {"report": {**saved, "destinations": ["mine"], "cards": [{**saved["cards"][0], "dataset": {"id": "missing", "kind": "raw"}}]}},
        )
        unpublished = store.run_action(
            "tenant_a",
            "self_analysis",
            "upsert_visual_report",
            prepared,
            actor_user_id="u_owner",
        )["result"]["report"]
        self.assertEqual(unpublished["id"], "visual_report_weekly")
        self.assertNotIn("weekly", unpublished["destinations"])
        other_state = store.get_module("tenant_a", "self_analysis", actor_user_id="u_other")["state"]
        self.assertNotIn("visual_report_weekly", [report["id"] for report in other_state["visualReports"]])

    def test_reediting_existing_report_updates_original_id_without_new_version(self) -> None:
        store = InMemoryApplicationStore()
        first = store.run_action(
            "tenant_a",
            "self_analysis",
            "upsert_visual_report",
            {"report": self.report},
            actor_user_id="u_owner",
        )["result"]["report"]
        edited = store.run_action(
            "tenant_a",
            "self_analysis",
            "upsert_visual_report",
            {"report": {**first, "title": "支行余额看板（二次加工）"}},
            actor_user_id="u_owner",
        )["result"]["report"]
        reports = store.get_module("tenant_a", "self_analysis", actor_user_id="u_owner")["state"]["visualReports"]

        self.assertEqual(edited["id"], first["id"])
        self.assertEqual(edited["createdAt"], first["createdAt"])
        self.assertEqual(edited["title"], "支行余额看板（二次加工）")
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["id"], "visual_report_1")

    def test_route_rebinds_rotated_delivery_by_logical_title_without_source_key(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(list_published_bundle=lambda tenant_id: {"topic_tables": []}),
                data_acquisition_service=SimpleNamespace(csv_source=_LogicalTitleCsvSource()),
            )
        )
        report = {
            **self.report,
            "cards": [{
                **self.report["cards"][0],
                "dataset": {
                    "id": "csv_old_delivery_hash",
                    "kind": "raw",
                    "name": "标品双周会周度sql_2026-08-14",
                    "code": "csv_oldhash12ab",
                    "fields": [
                        {"fieldNameEn": "branch", "fieldNameCn": "机构", "type": "string"},
                        {"fieldNameEn": "balance", "fieldNameCn": "余额", "type": "decimal"},
                    ],
                },
            }],
        }
        bound = _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})
        dataset = bound["report"]["cards"][0]["dataset"]
        self.assertEqual(dataset["id"], "csv_new_delivery_hash")
        self.assertEqual(dataset["sourceKey"], "source_loans_current")
        self.assertEqual(dataset["name"], "标品双周会周度sql_2026-05-06")

    def test_route_rebinds_rotated_delivery_by_stable_source_key(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(list_published_bundle=lambda tenant_id: {"topic_tables": []}),
                data_acquisition_service=SimpleNamespace(csv_source=_RotatedCsvSource()),
            )
        )
        report = {
            **self.report,
            "cards": [{
                **self.report["cards"][0],
                "dataset": {
                    "id": "raw_loans_previous_delivery",
                    "kind": "raw",
                    "sourceKey": "source_loans",
                    "schemaFingerprint": "schema_current",
                },
            }],
        }
        bound = _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})
        self.assertEqual(bound["report"]["cards"][0]["dataset"]["id"], "raw_loans_20260816")

    def test_route_binds_only_published_multi_page_data_identity(self) -> None:
        page_data = {
            "id": "page_data_multi_1",
            "name": "跨机构余额页面数据",
            "institutionScope": "multi_institution",
            "relationshipGroupId": "relationship_multi_1",
            "sourceKey": "relationship_multi_1",
            "schemaFingerprint": "page-schema-1",
            "sourceFields": [
                {"fieldNameEn": "__institution_name", "fieldNameCn": "机构", "type": "string"},
                {"fieldNameEn": "balance", "fieldNameCn": "余额", "type": "decimal", "isMetric": True},
            ],
        }
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(list_published_bundle=lambda _tenant_id: {"topic_tables": [], "page_data": [page_data]}),
                data_acquisition_service=SimpleNamespace(csv_source=_CsvSource()),
            )
        )
        report = {
            **self.report,
            "cards": [{
                **self.report["cards"][0],
                "dataset": {
                    "id": "page_data_multi_1",
                    "kind": "page_data",
                    "relationshipGroupId": "relationship_multi_1",
                    "schemaFingerprint": "page-schema-1",
                    "rows": [{"secret": "must_not_store"}],
                },
            }],
        }
        bound = _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})
        dataset = bound["report"]["cards"][0]["dataset"]
        self.assertEqual(dataset["kind"], "page_data")
        self.assertEqual(dataset["relationshipGroupId"], "relationship_multi_1")
        self.assertEqual(dataset["schemaFingerprint"], "page-schema-1")
        self.assertNotIn("rows", dataset)

        single_store = SimpleNamespace(list_published_bundle=lambda _tenant_id: {
            "topic_tables": [],
            "page_data": [{**page_data, "institutionScope": "single_institution"}],
        })
        handler.services.data_asset_store = single_store
        with self.assertRaisesRegex(PermissionError, "visual_report_dataset_unavailable"):
            _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})

    def test_route_rejects_changed_schema_for_stable_source(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(list_published_bundle=lambda tenant_id: {"topic_tables": []}),
                data_acquisition_service=SimpleNamespace(csv_source=_RotatedCsvSource()),
            )
        )
        report = {
            **self.report,
            "cards": [{
                **self.report["cards"][0],
                "dataset": {
                    "id": "raw_loans_previous_delivery",
                    "kind": "raw",
                    "sourceKey": "source_loans",
                    "schemaFingerprint": "schema_stale",
                },
            }],
        }
        with self.assertRaisesRegex(PermissionError, "visual_report_dataset_schema_changed"):
            _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})

    def test_unknown_dataset_fails_closed(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(list_published_bundle=lambda tenant_id: {"topic_tables": []}),
                data_acquisition_service=SimpleNamespace(csv_source=_CsvSource()),
            )
        )
        report = {**self.report, "cards": [{**self.report["cards"][0], "dataset": {"id": "missing", "kind": "raw"}}]}
        with self.assertRaisesRegex(PermissionError, "visual_report_dataset_unavailable"):
            _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})

    def test_visualization_scope_returns_only_chart_catalog(self) -> None:
        response: dict = {}
        review_topic = {
            "id": "topic_review", "name": "评审中主题", "code": "topic_review",
            "fields": [], "lifecycleStatus": "review",
        }
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(
                    list_bundle=lambda tenant_id: {
                        "raw_tables": [], "intents": [{"id": "must_not_leak"}],
                        "topic_tables": [
                            review_topic,
                            {"id": "topic_no_data", "lifecycleStatus": "active"},
                            {"id": "topic_rejected", "lifecycleStatus": "rejected"},
                        ],
                    },
                    list_raw_table_external_references=lambda tenant_id: {},
                ),
                data_acquisition_service=SimpleNamespace(
                    csv_source=SimpleNamespace(for_tenant=lambda tenant_id: _VisualizationCatalog()),
                ),
                topic_data_store=SimpleNamespace(
                    topic_table_snapshots=lambda tenant_id, ids: {
                        "topic_review": {"reference_type": "topic", "reference_id": "topic_review", "has_data": True, "row_count": 4},
                    },
                ),
            ),
            _request_context=lambda params: SimpleNamespace(tenant_id="tenant_a"),
            _require_asset_permission=lambda context, action: None,
            _send_json=lambda payload, *args, **kwargs: response.update(payload),
        )
        handle_data_assets_get(handler, "scope=visualization")
        self.assertEqual(response["source_mode"], "visualization_catalog")
        self.assertEqual([item["id"] for item in response["raw_tables"]], ["raw_loans"])
        self.assertEqual([item["id"] for item in response["topic_tables"]], ["topic_review"])
        self.assertEqual(response["topic_tables"][0]["dataSnapshot"]["row_count"], 4)
        self.assertEqual(response["intents"], [])
        self.assertEqual(response["relationships"], [])

    def test_visual_report_accepts_review_topic_with_snapshot(self) -> None:
        topic = {
            "id": "topic_review", "name": "评审中主题", "code": "topic_review",
            "fields": [{"fieldNameEn": "balance", "fieldNameCn": "余额"}],
            "lifecycleStatus": "review", "schemaVersion": "topic-schema-1",
        }
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(list_bundle=lambda tenant_id: {"topic_tables": [topic]}),
                topic_data_store=SimpleNamespace(
                    topic_table_snapshots=lambda tenant_id, ids: {
                        "topic_review": {"reference_type": "topic", "reference_id": "topic_review", "has_data": True, "row_count": 4},
                    },
                ),
                data_acquisition_service=SimpleNamespace(csv_source=_CsvSource()),
            ),
        )
        report = {
            **self.report,
            "cards": [{
                **self.report["cards"][0],
                "dataset": {"id": "topic_review", "kind": "topic", "schemaFingerprint": "topic-schema-1"},
            }],
        }
        bound = _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})
        self.assertEqual(bound["report"]["cards"][0]["dataset"]["id"], "topic_review")
        self.assertEqual(bound["report"]["cards"][0]["dataset"]["name"], "评审中主题")

    def test_visual_report_rejects_topic_without_snapshot(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                data_asset_store=SimpleNamespace(
                    list_bundle=lambda tenant_id: {
                        "topic_tables": [{"id": "topic_empty", "lifecycleStatus": "review"}],
                    },
                ),
                topic_data_store=SimpleNamespace(topic_table_snapshots=lambda tenant_id, ids: {}),
                data_acquisition_service=SimpleNamespace(csv_source=_CsvSource()),
            ),
        )
        report = {
            **self.report,
            "cards": [{**self.report["cards"][0], "dataset": {"id": "topic_empty", "kind": "topic"}}],
        }
        with self.assertRaisesRegex(PermissionError, "visual_report_dataset_unavailable"):
            _bind_visual_report_payload(handler, SimpleNamespace(tenant_id="tenant_a"), {"report": report})


if __name__ == "__main__":
    unittest.main()
