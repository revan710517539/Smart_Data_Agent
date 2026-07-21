from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from backend.platform.bootstrap import build_local_platform
from backend.platform.crawler_engine import (
    CrawlerEngine,
    CrawlerOperation,
    CrawlerProfileCollection,
    CrawlerProfileContext,
    CrawlerProfileDescriptor,
    CrawlerProfileRegistry,
    CrawlerRequest,
    CrawlerResult,
    SQLDecomposer,
    build_crawler_url_identity,
    get_default_crawler_profile_registry,
)
from backend.platform.crawler_engine.policy import validate_browser_script, validate_repair_candidate
from backend.platform.crawler_engine.diagnostics import classify_exception
from backend.platform.crawler_engine.playwright_transport import PlaywrightCrawlerTransport
from backend.platform.crawler_engine.playwright_transport import _storage_state_path
from backend.platform.crawler_engine.systems.qifu_focuspro_sios import (
    QIFU_BUSINESS_SANDBOX_PROFILE_ID,
    QIFU_FUNNEL_PROFILE_ID,
)
from backend.platform.crawler_engine.systems.qifu_focuspro_sios.business_sandbox_collector import (
    collect_business_sandbox,
)
from backend.platform.crawler_engine.systems.qifu_focuspro_sios.collector import collect_funnel_analysis
from backend.platform.ingestion.repair import ModelAcquisitionRepairGenerator
from backend.platform.ingestion.sandbox import RestrictedRowTransformSandbox
from backend.platform.settings.store import InMemorySystemConfigStore


class CrawlerEngineTest(unittest.TestCase):
    def test_verified_profile_crawler_writes_csv_artifact(self) -> None:
        class SuccessfulTransport:
            name = "test-success"

            def execute(self, request):
                self.request = request
                return CrawlerResult(
                    status="succeeded",
                    rows=({"机构": "华兴银行", "指标": "申请量", "值": 12},),
                    source_snapshot={"snapshot_id": "snapshot-test", "observed_at": "2026-07-16T00:00:00+00:00"},
                )

        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(Path(tmpdir) / "crawler.sqlite")
            try:
                connection = services.system_config_store.upsert_data_connection(
                    "tenant_demo",
                    {
                        "id": "focuspro_funnel",
                        "institution": "华兴银行",
                        "sourceName": "FocusPro漏斗分析",
                        "sourceType": "智运平台（页面爬虫）",
                        "apiUrl": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/funnelAnalysis",
                        "loginUrl": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/funnelAnalysis",
                        "queryPageUrl": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/funnelAnalysis",
                        "account": "reader",
                        "password": "secret",
                        "dataset": "focuspro_funnel",
                        "enabled": True,
                        "mockEnabled": False,
                        "status": "verified",
                        "testStatus": "verified",
                    },
                )
                self.assertEqual(connection["crawlerProfileId"], QIFU_FUNNEL_PROFILE_ID)
                services.data_acquisition_service.crawler_engine = CrawlerEngine(transport=SuccessfulTransport())
                with (
                    patch("backend.platform.crawler_engine.engine.validate_outbound_url"),
                    patch.dict(
                        "os.environ",
                        {"SMART_DATA_AGENT_CRAWLER_EXPORT_ROOT": str(Path(tmpdir) / "operational")},
                    ),
                ):
                    result = services.data_acquisition_service.run_verified_crawler(
                        "tenant_demo", "focuspro_funnel", "u_admin", "automation:test-crawler"
                    )
                self.assertEqual(result["status"], "succeeded")
                self.assertEqual(result["row_count"], 1)
                self.assertTrue(result["artifact_id"].startswith("da_"))
                raw_asset = result["raw_table_asset"]
                self.assertEqual(raw_asset["artifactId"], result["artifact_id"])
                self.assertTrue(raw_asset["fileName"].endswith(".csv"))
                self.assertEqual(raw_asset["rowCount"], 1)
                self.assertEqual(raw_asset["usageScenario"], "FocusPro漏斗分析")
                self.assertEqual(raw_asset["relatedIntent"], "经营分析 / 漏斗转化与流失归因")
                self.assertEqual([field["fieldNameCn"] for field in raw_asset["fields"]], ["机构", "指标", "值"])
                self.assertEqual([field["fieldNameEn"] for field in raw_asset["fields"]], ["field_001", "field_002", "field_003"])
                stored_raw = [
                    item
                    for item in services.data_asset_store.list_bundle("tenant_demo")["raw_tables"]
                    if item.get("artifactId") == result["artifact_id"]
                ]
                self.assertEqual(len(stored_raw), 1)
                self.assertEqual(stored_raw[0]["lifecycleStatus"], "active")
                csv_files = list(services.data_acquisition_service.object_store.root.rglob("*.csv"))
                self.assertEqual(len(csv_files), 1)
                self.assertIn("申请量", csv_files[0].read_text(encoding="utf-8-sig"))
                task = services.automation_runtime.create_task(
                    "tenant_demo",
                    {
                        "task_code": "scheduled_focuspro_funnel",
                        "task_name": "定时采集FocusPro漏斗",
                        "task_type": "acquisition",
                        "trigger_type": "manual",
                        "handler_ref": "crawler.connection.run",
                        "task_config": {"connection_id": "focuspro_funnel"},
                        "retry_policy": {"max_attempts": 1},
                    },
                    "u_admin",
                )
                services.automation_runtime.trigger(
                    "tenant_demo", task["automation_task_id"], "u_admin", "crawler-automation-run"
                )
                with (
                    patch("backend.platform.crawler_engine.engine.validate_outbound_url"),
                    patch.dict(
                        "os.environ",
                        {"SMART_DATA_AGENT_CRAWLER_EXPORT_ROOT": str(Path(tmpdir) / "operational")},
                    ),
                ):
                    completed = services.automation_runtime.run_once("crawler-worker")
                self.assertEqual(completed["status"], "succeeded")
                self.assertTrue(any(ref["type"] == "artifact" for ref in completed["result_refs"]))
                stored_raw_after_retry = [
                    item
                    for item in services.data_asset_store.list_bundle("tenant_demo")["raw_tables"]
                    if item.get("artifactId") == result["artifact_id"]
                ]
                self.assertEqual(len(stored_raw_after_retry), 1)
            finally:
                services.close()

    def test_each_registered_url_has_a_stable_crawler_identity(self) -> None:
        first = build_crawler_url_identity(
            {
                "sourceType": "智运平台（页面爬虫）",
                "queryPageUrl": "https://EXAMPLE.com/report/?b=2&a=1#/dashboard",
            }
        )
        second = build_crawler_url_identity(
            {
                "sourceType": "智运平台（页面爬虫）",
                "queryPageUrl": "https://example.com/report?a=1&b=2#/dashboard",
            }
        )
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first.mode, "page")

    def test_same_institution_can_register_multiple_page_connections(self) -> None:
        store = InMemorySystemConfigStore()
        for suffix in ("funnel", "customers"):
            store.upsert_data_connection(
                "tenant_demo",
                {
                    "id": f"page_{suffix}",
                    "institution": "华兴银行",
                    "sourceName": f"华兴{suffix}",
                    "sourceType": "智运平台（页面爬虫）",
                    "loginUrl": "https://example.com/login",
                    "queryPageUrl": f"https://example.com/{suffix}",
                    "account": "reader",
                    "password": "secret",
                    "dataset": f"dataset_{suffix}",
                    "enabled": True,
                },
            )
        connections = store.list_data_connections("tenant_demo")
        self.assertEqual(len(connections), 2)
        self.assertEqual({item["institution"] for item in connections}, {"华兴银行"})
        self.assertEqual(len({item["crawlerKey"] for item in connections}), 2)

    def test_business_sandbox_url_maps_to_independent_profile(self) -> None:
        identity = build_crawler_url_identity(
            {
                "sourceType": "智运平台（页面爬虫）",
                "queryPageUrl": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/businessSandbox",
            }
        )
        self.assertIsNotNone(identity)
        self.assertEqual(identity.profile_id, QIFU_BUSINESS_SANDBOX_PROFILE_ID)

    def test_sql_page_crawler_requires_readonly_sql_for_data_query(self) -> None:
        with patch("backend.platform.crawler_engine.engine.validate_outbound_url"):
            with self.assertRaisesRegex(ValueError, "sql_crawler_readonly_sql_required"):
                CrawlerEngine().execute(
                    CrawlerRequest(
                        tenant_id="tenant_demo",
                        operation_type=CrawlerOperation.DATA_QUERY,
                        idempotency_key="sql-url-test",
                        connection={
                            "sourceType": "毓数平台（SQL爬虫）",
                            "loginUrl": "https://example.com/login",
                            "queryPageUrl": "https://example.com/sql",
                        },
                        script={"version": 1, "steps": [{"action": "goto", "url": "${query_page_url}"}]},
                    )
                )

    def test_url_crawler_session_state_is_isolated_by_tenant_and_url(self) -> None:
        request = CrawlerRequest(
            tenant_id="tenant_demo",
            operation_type=CrawlerOperation.CONNECTIVITY_TEST,
            idempotency_key="session-path-test",
            connection={},
        )
        connection = {
            "sourceType": "智运平台（页面爬虫）",
            "queryPageUrl": "https://example.com/funnel",
        }
        path = _storage_state_path(request, connection, {})
        self.assertIn("tenant_demo", path)
        self.assertTrue(path.endswith(".json"))
        self.assertIn(build_crawler_url_identity(connection).crawler_key, path)

    def test_crawler_rate_limit_is_classified_as_retryable(self) -> None:
        error_code, retryable = classify_exception(RuntimeError("/lost/queryEnum:BBTL5022"))
        self.assertEqual(str(error_code), "RATE_LIMITED")
        self.assertTrue(retryable)

    def test_browser_script_accepts_manual_login_and_registered_system_collection(self) -> None:
        script = validate_browser_script(
            {
                "version": 1,
                "steps": [
                    {
                        "action": "wait_for_url",
                        "url_contains": "#/sios/funnelAnalysis",
                        "manual": True,
                        "timeout_ms": 900_000,
                    },
                    {
                        "action": "collect_system",
                        "profile_id": QIFU_FUNNEL_PROFILE_ID,
                        "traversal_mode": "independent",
                        "timeout_ms": 900_000,
                    },
                ],
            }
        )
        self.assertEqual(script["steps"][0]["action"], "wait_for_url")
        self.assertEqual(script["steps"][1]["profile_id"], QIFU_FUNNEL_PROFILE_ID)

    def test_collect_system_requires_a_profile_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "browser_crawler_profile_id_required"):
            validate_browser_script({"version": 1, "steps": [{"action": "collect_system"}]})

    def test_default_profile_registry_manages_qifu_without_transport_coupling(self) -> None:
        descriptors = get_default_crawler_profile_registry().list_profiles()
        self.assertEqual(
            [item.profile_id for item in descriptors],
            [QIFU_BUSINESS_SANDBOX_PROFILE_ID, QIFU_FUNNEL_PROFILE_ID],
        )
        self.assertEqual(descriptors[0].system_id, "qifu_focuspro_sios")
        self.assertEqual(
            get_default_crawler_profile_registry().get("collect_funnel_analysis").descriptor.profile_id,
            QIFU_FUNNEL_PROFILE_ID,
        )
        self.assertEqual(
            [item["profile_id"] for item in CrawlerEngine().list_crawler_profiles()],
            [QIFU_BUSINESS_SANDBOX_PROFILE_ID, QIFU_FUNNEL_PROFILE_ID],
        )

    def test_transport_dispatches_independent_profiles_through_registry(self) -> None:
        registry = CrawlerProfileRegistry()
        alpha = _FakeCrawlerProfile("alpha_system.orders.v1", "alpha_system", "alpha")
        beta = _FakeCrawlerProfile("beta_system.customers.v1", "beta_system", "beta")
        registry.register(alpha)
        registry.register(beta)
        transport = PlaywrightCrawlerTransport(profile_registry=registry)
        request = CrawlerRequest(
            tenant_id="tenant_demo",
            operation_type=CrawlerOperation.DATA_QUERY,
            idempotency_key="profile-dispatch-test",
            connection={},
        )

        result = transport._run_step(
            object(),
            "collect_system",
            {"action": "collect_system", "profile_id": beta.descriptor.profile_id},
            request,
            {},
        )

        self.assertIsInstance(result, CrawlerProfileCollection)
        self.assertEqual(result.rows[0]["owner"], "beta")
        self.assertEqual(result.metadata["crawler_profile"]["system_id"], "beta_system")
        self.assertEqual([item.system_id for item in registry.list_profiles()], ["alpha_system", "beta_system"])

    def test_profile_registry_rejects_duplicate_and_unknown_profiles(self) -> None:
        registry = CrawlerProfileRegistry()
        profile = _FakeCrawlerProfile("alpha_system.orders.v1", "alpha_system", "alpha")
        registry.register(profile, aliases=("legacy_alpha_orders",))
        with self.assertRaisesRegex(ValueError, "crawler_profile_already_registered"):
            registry.register(profile)
        with self.assertRaisesRegex(ValueError, "crawler_profile_not_registered"):
            registry.get("missing_system.profile.v1")

    def test_profile_registry_enforces_supported_operation(self) -> None:
        registry = CrawlerProfileRegistry()
        profile = _FakeCrawlerProfile("alpha_system.orders.v1", "alpha_system", "alpha")
        registry.register(profile)
        request = CrawlerRequest(
            tenant_id="tenant_demo",
            operation_type=CrawlerOperation.METADATA_QUERY,
            idempotency_key="profile-operation-test",
            connection={},
        )
        with self.assertRaisesRegex(ValueError, "crawler_profile_operation_not_supported"):
            registry.collect(
                profile.descriptor.profile_id,
                CrawlerProfileContext(page=object(), request=request, connection={}, step={}),
            )

    def test_funnel_collection_flattens_filter_metrics_trends_and_loss_details(self) -> None:
        page = _FakeFunnelPage()
        result = collect_funnel_analysis(
            page,
            {
                "traversal_mode": "independent",
                "include_totals": False,
                "max_combinations": 20,
                "staff_search_terms": [],
                "statistical_dates": [],
                "lost_scenes": ["COMPLETE"],
            },
        )
        record_types = {row.get("record_type") for row in result.rows}
        self.assertTrue(
            {
                "filter_option",
                "main_item",
                "sub_summary",
                "sub_item",
                "trend_point",
                "lost_total",
                "lost_item",
                "lost_reason",
                "limit_distribution",
                "rate_distribution",
            }.issubset(record_types)
        )
        self.assertEqual(result.metadata["combination_count"], 2)
        self.assertTrue(all("Authorization" not in row.get("raw_json", "") for row in result.rows))

    def test_business_sandbox_collection_flattens_all_sections_and_trends(self) -> None:
        page = _FakeBusinessSandboxPage()
        result = collect_business_sandbox(
            page,
            {
                "traversal_mode": "cartesian",
                "include_totals": False,
                "max_combinations": 20,
                "request_delay_ms": 0,
                "batch_concurrency": 1,
            },
        )
        record_types = {row.get("record_type") for row in result.rows}
        self.assertTrue(
            {"filter_option", "section_summary", "section_metric", "trend_point"}.issubset(record_types)
        )
        self.assertEqual(result.metadata["combination_count"], 2)
        self.assertEqual(result.metadata["section_count"], 4)
        self.assertEqual(result.metadata["trend_request_count"], 2)
        self.assertTrue(any(row.get("third_org_code") == "O3" for row in result.rows))
        self.assertTrue(all("Authorization" not in row.get("raw_json", "") for row in result.rows))

    def test_business_sandbox_current_mode_collects_one_default_page_state(self) -> None:
        page = _FakeBusinessSandboxPage()
        result = collect_business_sandbox(
            page,
            {
                "traversal_mode": "current",
                "include_totals": True,
                "max_combinations": 20,
                "request_delay_ms": 0,
                "batch_concurrency": 1,
            },
        )
        metric_rows = [
            row
            for row in result.rows
            if row.get("record_type") in {"section_summary", "section_metric"}
        ]
        self.assertEqual(result.metadata["traversal_mode"], "current")
        self.assertEqual(result.metadata["combination_count"], 1)
        self.assertEqual(result.metadata["section_count"], 2)
        self.assertEqual(result.metadata["detail_section_count"], 1)
        self.assertEqual(result.metadata["request_delay_min_ms"], 0)
        self.assertEqual(result.metadata["request_delay_max_ms"], 0)
        self.assertTrue(metric_rows)
        detail_rows = [row for row in result.rows if row.get("record_type") == "detail_metric"]
        self.assertEqual(len(detail_rows), 1)
        self.assertEqual(detail_rows[0]["crawl_page"], "经营明细")
        self.assertEqual(detail_rows[0]["metric_name"], "完件人数")
        self.assertEqual(detail_rows[0]["metric_value"], "50")
        self.assertEqual(detail_rows[0]["comparison_value"], "39")
        self.assertEqual({row.get("product_code") for row in metric_rows}, {"P1"})
        self.assertEqual({row.get("date_range") for row in metric_rows}, {"MONTH"})
        self.assertEqual({row.get("second_org_code") for row in metric_rows}, {""})

    def test_business_sandbox_checkpoint_reuses_completed_batches(self) -> None:
        with TemporaryDirectory() as tmpdir:
            step = {
                "traversal_mode": "cartesian",
                "include_totals": False,
                "max_combinations": 20,
                "request_delay_ms": 0,
                "batch_concurrency": 1,
                "batch_size": 1,
                "checkpoint_path": str(Path(tmpdir) / "business.jsonl"),
                "checkpoint_run_key": "checkpoint-test",
            }
            first_page = _FakeBusinessSandboxPage()
            first = collect_business_sandbox(first_page, step)
            second_page = _FakeBusinessSandboxPage()
            second = collect_business_sandbox(second_page, step)
            self.assertEqual(first.rows, second.rows)
            self.assertEqual(second.metadata["resumed_from_combination"], 2)
            self.assertEqual(second_page.call_counts.get("/sandbox/business/querySubItem", 0), 0)
            self.assertEqual(second_page.call_counts.get("/sandbox/business/queryTrendChart", 0), 0)

    def test_business_sandbox_success_idempotently_updates_csv_asset_connection_and_task(self) -> None:
        class SuccessfulTransport:
            name = "business-success"

            def execute(self, request):
                return CrawlerResult(
                    status="succeeded",
                    rows=(
                        {
                            "second_org_name": "总行",
                            "section_code": "PERFORMANCE_TRACKING",
                            "metric_name": "在贷余额",
                            "metric_value": "18218538.75",
                        },
                    ),
                    metadata={"page_name": "经营沙盘", "profile": QIFU_BUSINESS_SANDBOX_PROFILE_ID},
                    source_snapshot={"snapshot_id": "business-snapshot", "observed_at": "2026-07-16T20:00:00+00:00"},
                )

        with TemporaryDirectory() as tmpdir:
            export_root = Path(tmpdir) / "智能运营"
            services = build_local_platform(Path(tmpdir) / "crawler.sqlite")
            try:
                created = services.data_acquisition_service.ensure_crawler_connection(
                    "tenant_demo",
                    {
                        "id": "focuspro_business",
                        "institution": "华兴银行",
                        "sourceName": "FocusPro经营沙盘",
                        "sourceType": "智运平台（页面爬虫）",
                        "apiUrl": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/businessSandbox",
                        "loginUrl": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/businessSandbox",
                        "queryPageUrl": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/businessSandbox",
                        "account": "reader",
                        "password": "secret",
                        "dataset": "channel_operation_mart",
                        "enabled": True,
                        "mockEnabled": False,
                        "crawlerConfig": {"traversalMode": "current", "headless": False},
                    },
                    "u_admin",
                )
                self.assertEqual(created["crawlerProfileId"], QIFU_BUSINESS_SANDBOX_PROFILE_ID)
                services.data_acquisition_service.crawler_engine = CrawlerEngine(transport=SuccessfulTransport())
                with (
                    patch("backend.platform.crawler_engine.engine.validate_outbound_url"),
                    patch.dict("os.environ", {"SMART_DATA_AGENT_CRAWLER_EXPORT_ROOT": str(export_root)}),
                ):
                    first = services.data_acquisition_service.validate_and_run_crawler(
                        "tenant_demo", "focuspro_business", "u_admin", "business:first"
                    )
                    second = services.data_acquisition_service.run_verified_crawler(
                        "tenant_demo", "focuspro_business", "u_admin", "business:second"
                    )
                self.assertEqual(first["connection"]["testStatus"], "verified")
                self.assertEqual(first["raw_table_asset"]["id"], second["raw_table_asset"]["id"])
                self.assertEqual(first["automation_task"]["automation_task_id"], second["automation_task"]["automation_task_id"])
                self.assertIn("页面默认机构", first["automation_task"]["task_config"]["description"])
                self.assertEqual(first["automation_task"]["retry_policy"]["base_delay_seconds"], 1_800)
                self.assertEqual(len(services.automation_store.list_tasks("tenant_demo")), 1)
                matching_assets = [
                    item
                    for item in services.data_asset_store.list_bundle("tenant_demo")["raw_tables"]
                    if item.get("crawlerProfileId") == QIFU_BUSINESS_SANDBOX_PROFILE_ID
                ]
                self.assertEqual(len(matching_assets), 1)
                self.assertEqual(matching_assets[0]["rowCount"], 1)
                self.assertEqual(matching_assets[0]["tableNameCn"], "华兴银行经营沙盘 CSV原始数据")
                field_types = {
                    field["fieldNameCn"]: field["type"] for field in matching_assets[0]["fields"]
                }
                self.assertEqual(field_types["metric_value"], "decimal")
                self.assertEqual(
                    [path.name for path in export_root.glob("*.csv")],
                    ["华兴银行经营沙盘2026-07-17.csv"],
                )
                self.assertIn("在贷余额", Path(second["csv_path"]).read_text(encoding="utf-8-sig"))
                round_trip = services.system_config_store.get_data_connection(
                    "tenant_demo", "focuspro_business", reveal_secret=True
                )
                self.assertEqual(round_trip["crawlerConfig"]["traversalMode"], "current")
                self.assertFalse(round_trip["crawlerConfig"]["headless"])
                legacy_update = {key: value for key, value in round_trip.items() if key != "crawlerConfig"}
                legacy_update["sourceName"] = "FocusPro经营沙盘（已编辑）"
                services.system_config_store.upsert_data_connection(
                    "tenant_demo", legacy_update, updated_by="u_admin"
                )
                preserved = services.system_config_store.get_data_connection(
                    "tenant_demo", "focuspro_business", reveal_secret=True
                )
                self.assertEqual(preserved["crawlerConfig"]["traversalMode"], "current")
            finally:
                services.close()

    def test_sql_decomposition_covers_cte_join_aggregate_and_parameters(self) -> None:
        result = SQLDecomposer().parse(
            """
            WITH base AS (
              SELECT a.org_id, a.amount, b.branch_name
              FROM core.loan_fact a
              LEFT JOIN dim.branch b ON a.org_id = b.org_id
              WHERE a.biz_date = :biz_date
            )
            SELECT branch_name, SUM(amount) AS total
            FROM base GROUP BY branch_name ORDER BY total DESC
            """
        )
        self.assertEqual([item.qualified_name for item in result.raw_tables], ["core.loan_fact", "dim.branch"])
        self.assertEqual(result.ctes, ("base",))
        self.assertEqual(result.joins[0].join_type, "left")
        self.assertIn("biz_date", result.parameters)
        self.assertTrue(any(field.aggregate == "SUM" for field in result.fields))
        self.assertEqual(len(result.query_hash), 64)

    def test_sql_decomposition_rejects_write_multi_statement_and_dangerous_function(self) -> None:
        for sql in (
            "DELETE FROM core.loan_fact",
            "SELECT 1; SELECT 2",
            "SELECT pg_read_file('/etc/passwd')",
        ):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                SQLDecomposer().parse(sql)

    def test_browser_repair_only_changes_selector_wait_or_navigation_fields(self) -> None:
        original = json.dumps(
            {
                "version": 1,
                "readonly_sql": "SELECT amount FROM core.loan_fact",
                "steps": [
                    {"action": "goto", "url": "https://example.com/login"},
                    {"action": "click", "selector": "#old"},
                ],
            }
        )
        candidate = json.dumps(
            {
                "version": 1,
                "readonly_sql": "SELECT amount FROM core.loan_fact",
                "steps": [
                    {"action": "goto", "url": "https://example.com/sign-in"},
                    {"action": "click", "selector": "#new"},
                ],
            }
        )
        with patch("backend.platform.crawler_engine.policy.validate_outbound_url"):
            self.assertIn("#new", validate_repair_candidate(original, candidate))
        changed_sql = candidate.replace("SELECT amount", "SELECT customer_id")
        with patch("backend.platform.crawler_engine.policy.validate_outbound_url"), self.assertRaises(ValueError):
            validate_repair_candidate(original, changed_sql)

    def test_stub_transport_passes_gate_without_claiming_real_connectivity(self) -> None:
        script = validate_browser_script(
            {
                "version": 1,
                "steps": [{"action": "goto", "url": "${query_page_url}"}],
            }
        )
        with patch("backend.platform.crawler_engine.engine.validate_outbound_url"):
            result = CrawlerEngine().execute(
                CrawlerRequest(
                    tenant_id="tenant_demo",
                    operation_type=CrawlerOperation.CONNECTIVITY_TEST,
                    idempotency_key="test-1",
                    connection={
                        "loginUrl": "https://example.com/login",
                        "queryPageUrl": "https://example.com/query",
                    },
                    script=script,
                )
            )
        self.assertEqual(result.status, "not_configured")
        self.assertEqual(result.diagnostics["transport"], "stub")

    def test_repair_model_is_strictly_routed_by_application_module(self) -> None:
        model_store = Mock()
        model_store.list_models.return_value = [
            {"id": "general", "name": "general", "status": "available", "testStatus": "connected"},
            {
                "id": "Clawer_Fix",
                "name": "Clawer_Fix",
                "status": "available",
                "testStatus": "connected",
                "applicationModule": "crawler_exception_optimization",
                "key": "https://model.example/v1",
                "value": "secret",
            },
        ]
        generator = ModelAcquisitionRepairGenerator(model_store, RestrictedRowTransformSandbox())
        source = json.dumps({"version": 1, "steps": [{"action": "click", "selector": "#old"}]})
        candidate = json.dumps({"version": 1, "steps": [{"action": "click", "selector": "#new"}]})
        completion = {
            "status": "connected",
            "response_text": json.dumps({"candidate_source_code": candidate}),
            "model_id": "Clawer_Fix",
        }
        with patch("backend.platform.ingestion.repair.call_model_text_completion", return_value=completion) as call:
            result = generator.generate(
                "tenant_demo",
                {"runtime": "browser", "source_code": source},
                {"error_code": "PAGE_CHANGED"},
            )
        self.assertEqual(call.call_args.args[0]["id"], "Clawer_Fix")
        self.assertEqual(result["model_call"]["routing_key"], "crawler_exception_optimization")

        model_store.list_models.return_value = [
            {"id": "general", "name": "general", "status": "available", "testStatus": "connected"}
        ]
        skipped = generator.generate(
            "tenant_demo",
            {"runtime": "browser", "source_code": source},
            {"error_code": "PAGE_CHANGED"},
        )
        self.assertEqual(skipped["model_call"]["error_code"], "model_application_module_not_ready")

    def test_topic_metadata_refresh_projects_sql_inferred_raw_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(Path(tmpdir) / "platform.sqlite")
            try:
                services.data_asset_store.upsert_item(
                    "tenant_demo",
                    "topic_table",
                    {
                        "id": "topic_crawler_test",
                        "name": "爬虫测试主题",
                        "code": "topic_crawler_test",
                        "description": "test",
                        "sql": "SELECT a.org_id, a.amount FROM core.loan_fact a WHERE a.tenant_id = :tenant_id AND a.org_id = :org_id AND a.biz_date = :biz_date",
                        "fields": [
                            {"fieldNameEn": "org_id", "fieldNameCn": "机构", "type": "string", "explanation": "机构编码"},
                            {"fieldNameEn": "amount", "fieldNameCn": "金额", "type": "decimal", "explanation": "金额"},
                        ],
                        "fieldExplanations": "",
                        "applicableScene": "智能分析",
                        "relatedIntent": "",
                        "relatedExperience": "",
                        "quickDisplay": False,
                        "reportReference": "",
                        "source": "毓数",
                        "updatedAt": "2026-07-10",
                    },
                    updated_by="u_admin",
                    lifecycle_status="active",
                )
                services.system_config_store.upsert_data_connection(
                    "tenant_demo",
                    {
                        "id": "crawler_conn",
                        "institution": "华兴银行",
                        "sourceName": "毓数爬虫",
                        "sourceType": "毓数平台（爬虫）",
                        "apiUrl": "https://example.com/query",
                        "loginUrl": "https://example.com/login",
                        "queryPageUrl": "https://example.com/query",
                        "metadataPageUrl": "https://example.com/metadata",
                        "spaceId": "huaxing",
                        "account": "reader",
                        "password": "secret",
                        "dataset": "yushu_crawler_mart",
                        "defaultDatabase": "core",
                        "enabled": True,
                        "mockEnabled": False,
                        "status": "draft",
                        "testStatus": "untested",
                    },
                )
                with patch("backend.platform.crawler_engine.engine.validate_outbound_url"):
                    result = services.topic_metadata_service.refresh(
                        "tenant_demo",
                        "topic_crawler_test",
                        "u_admin",
                        connection_id="crawler_conn",
                    )
                self.assertEqual(result["transport_status"], "not_configured")
                status = services.topic_metadata_service.status("tenant_demo", "topic_crawler_test")
                self.assertEqual(status["status"], "partial")
                self.assertEqual(status["raw_tables"][0]["dataset_code"], "core.loan_fact")
                self.assertEqual(status["raw_tables"][0]["field_count"], 2)
            finally:
                services.close()


class _FakeCrawlerProfile:
    def __init__(self, profile_id: str, system_id: str, owner: str) -> None:
        self.owner = owner
        self.descriptor = CrawlerProfileDescriptor(
            profile_id=profile_id,
            system_id=system_id,
            display_name=f"{owner} crawler",
            version=1,
            supported_operations=("data_query",),
            maintainer=f"crawler_engine.systems.{system_id}",
        )

    def collect(self, _context: object) -> CrawlerProfileCollection:
        return CrawlerProfileCollection(rows=({"owner": self.owner},), metadata={"source": self.owner})


class _FakeFunnelPage:
    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    def evaluate(self, _source: str, request: dict[str, object]) -> dict[str, object]:
        path = request["path"]
        payload = request["payload"]
        if path == "/lost/queryEnum":
            return {
                "orgCodeList": [{"code": "O2", "name": "二级", "children": [{"code": "O3", "name": "三级"}]}],
                "productList": [{"code": "P1", "name": "产品"}],
                "dateRange": [{"code": "ALL", "name": "全部"}],
                "channelList": [],
                "roleList": [],
            }
        if path == "/lost/querySubItemType":
            return {"subItemTypeList": ["STAGE1"]}
        if path == "/lost/queryMainItem":
            return {"mainItem": [{"type": "M1", "name": "主指标", "value": "10"}]}
        if path == "/lost/querySubItem":
            return {
                "titleItem": [{"name": "转化率", "value": "50%"}],
                "contentItem": [{"type": "S1", "name": "节点", "value": "5"}],
            }
        if path == "/lost/queryTrendChart":
            item_type = payload["itemType"]
            return {
                "chartMap": {
                    item_type: {
                        "itemName": "趋势",
                        "unitName": "人",
                        "itemList": [{"dateRecord": "2026-07-16", "value": "5"}],
                    }
                }
            }
        if path == "/lost/queryLost":
            return {
                "totalLostRate": "10%",
                "lostList": [{"type": "L1", "name": "漏损", "value": "10%"}],
            }
        if path == "/lost/queryLostDetail":
            return {
                "lostReasonList": [{"reason": "原因", "count": "1", "rate": "100%"}],
                "limitDistribution": [{"range": "0-1", "value": "1"}],
                "intRateDistribution": [{"range": "1%-2%", "value": "1"}],
            }
        raise AssertionError(f"unexpected path: {path}")


class _FakeBusinessSandboxPage:
    url = "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/businessSandbox"

    def __init__(self) -> None:
        self.call_counts: dict[str, int] = {}

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    def evaluate(self, _source: str, request: dict[str, object]) -> dict[str, object]:
        path = request["path"]
        payload = request["payload"]
        self.call_counts[path] = self.call_counts.get(path, 0) + 1
        if path == "/sandbox/detail/queryEnum":
            return {
                "orgCodeList": [
                    {"code": "O2", "name": "二级机构", "children": [{"code": "O3", "name": "三级机构"}]}
                ],
                "productList": [{"code": "P1", "name": "经营贷"}],
                "dateRange": [{"code": "MONTH", "name": "月"}],
            }
        if path == "/sandbox/business/querySubItemType":
            return {
                "subItemTypeList": [
                    {"code": "PERFORMANCE_TRACKING", "name": "业绩追踪"},
                    {"code": "APPLICATION_BUSINESS", "name": "申请业务"},
                ]
            }
        if path == "/sandbox/detail/querySubItemType":
            return {
                "subItemTypeList": [
                    {
                        "code": "COMPLETE_GROUP",
                        "name": "完件业务",
                        "children": [
                            {
                                "code": "COMPLETE",
                                "name": "完件业务表格分析",
                                "metrics": [
                                    {
                                        "name": "完件人数",
                                        "type": "complete_num",
                                        "checked": True,
                                        "category": "fix",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        if path == "/sandbox/business/querySubItem":
            if payload["subItemType"] == "PERFORMANCE_TRACKING":
                return {
                    "titleItem": [],
                    "contentItem": [
                        {"type": "BALANCE", "name": "在贷余额", "value": "18218538.75", "unitName": "元"}
                    ],
                }
            return {
                "titleItem": [{"name": "申请总量", "value": "20"}],
                "contentItem": [
                    {
                        "type": "APPLICATION_COUNT",
                        "name": "申请量",
                        "value": "20",
                        "children": [{"type": "APPROVED", "name": "通过量", "value": "12"}],
                    }
                ],
            }
        if path == "/sandbox/business/queryTrendChart":
            return {
                "BALANCE": {
                    "itemName": "在贷余额",
                    "unitName": "元",
                    "itemList": [
                        {"dateRecord": "2026-07-16", "value": "18000000"},
                        {"dateRecord": "2026-07-17", "value": "18218538.75"},
                    ],
                }
            }
        if path == "/sandbox/detail/querySubItem":
            requested = payload.get("orgCode") or ["000"]
            return {
                "rows": [
                    {
                        "dimension_code": requested[0],
                        "metrics_values": [
                            {
                                "type": "complete_num",
                                "name": "完件人数",
                                "curMonth": "50",
                                "lastMonth": "39",
                                "value": "",
                            }
                        ],
                    }
                ]
            }
        if path == "/sandbox/detail/queryTrendChart":
            return {
                "complete_num": {
                    "itemList": [
                        {"dateRecord": "2026-07-16", "value": "48"},
                        {"dateRecord": "2026-07-17", "value": "50"},
                    ]
                }
            }
        raise AssertionError(f"unexpected path: {path}")


if __name__ == "__main__":
    unittest.main()
