from __future__ import annotations

import sqlite3
import hashlib
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.data_access import (
    CSVObjectDataWarehouse,
    DorisDataWarehouse,
    HiveDataWarehouse,
    JSONDataWarehouse,
    PostgreSQLDataWarehouse,
    SQLDataWarehouse,
)
from backend.platform.data_access.factory import load_sql_dataset_catalog
from backend.platform.metrics import InMemoryMetricDictionaryStore, MetricSemanticCatalog, MetricSemanticError
from backend.platform.orchestration.query_conditions import parse_query_conditions
from backend.platform.security import ManualSQLValidationError, validate_read_only_sql_candidate
from backend.platform.semantic import InMemorySupersonicClient, SemanticQueryRequest


class SemanticExecutionCorrectnessTest(unittest.TestCase):
    def test_voice_analysis_csv_mock_returns_ten_ranked_branches_and_immutable_snapshot(self) -> None:
        root = Path(__file__).resolve().parents[3]
        catalog = load_sql_dataset_catalog(root / "configs" / "data_sources" / "voice_analysis_csv_catalog.json")
        warehouse = CSVObjectDataWarehouse(catalog, environment="test")
        result = warehouse.query_matrix(
            "loan_operation_mart",
            "tenant:华兴银行",
            ("loan_amount", "drawdown_rate"),
            ("branch_name",),
            filters={"month": {"gte": "2026-07", "lte": "2026-07"}},
            limit=10,
        )
        self.assertEqual(len(result.rows), 10)
        self.assertEqual(result.rows[0]["branch_name"], "上海分行")
        self.assertGreater(result.totals["loan_amount"], 0)
        snapshot = warehouse.snapshot_info("loan_operation_mart")
        self.assertEqual(snapshot["snapshot_id"], "voice-analysis-csv-2026-07-v1")
        self.assertTrue(snapshot["immutable"])

    def test_doris_and_hive_adapters_pool_connections_and_parameterize_queries(self) -> None:
        class Cursor:
            def __init__(self):
                self.rows = []
                self.closed = False

            def execute(self, sql, parameters=()):
                calls.append((sql, tuple(parameters)))
                if "COUNT(*) FROM" in sql:
                    self.rows = [(2,)]
                elif "GROUP BY" in sql:
                    self.rows = [("A", 20.0), ("B", 10.0)]
                else:
                    self.rows = [(30.0,)]

            def fetchall(self):
                return list(self.rows)

            def fetchone(self):
                return self.rows[0]

            def close(self):
                self.closed = True

        class Connection:
            def __init__(self):
                self.closed = False
                self.rollbacks = 0

            def cursor(self):
                return Cursor()

            def rollback(self):
                self.rollbacks += 1

            def close(self):
                self.closed = True

        catalog = {
            "mart": {
                "source_table": "loan_fact",
                "tenant_column": "tenant_id",
                "allowed_metrics": ["loan_amount"],
                "allowed_dimensions": ["branch_name"],
                "metric_aggregation": {"loan_amount": "sum"},
            }
        }
        for adapter_class, url in (
            (DorisDataWarehouse, "doris://unused/db"),
            (HiveDataWarehouse, "hive://unused/default"),
        ):
            with self.subTest(adapter=adapter_class.__name__):
                calls: list[tuple[str, tuple]] = []
                connections: list[Connection] = []

                def factory():
                    connection = Connection()
                    connections.append(connection)
                    return connection

                warehouse = adapter_class(
                    url,
                    catalog,
                    min_pool_size=1,
                    max_pool_size=2,
                    connection_factory=factory,
                )
                result = warehouse.query_matrix("mart", "tenant_demo", ("loan_amount",), ("branch_name",))
                self.assertEqual(result.totals, {"loan_amount": 30.0})
                self.assertTrue(all("%s" in sql for sql, _ in calls))
                self.assertTrue(all(parameters[0] == "tenant_demo" for _, parameters in calls))
                self.assertEqual(connections[0].rollbacks, 1)
                warehouse.close()
                self.assertTrue(connections[0].closed)

    def test_immutable_csv_object_warehouse_is_hash_bound_and_uses_ratio_of_sums(self) -> None:
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "loan.csv"
            raw = (
                "tenant_id,branch_name,drawdown_rate,drawdown_amount,eligible_amount\n"
                "tenant_demo,A,0.5,50,100\n"
                "tenant_demo,B,0.2,20,100\n"
                "tenant_other,X,0.99,99,100\n"
            ).encode("utf-8")
            csv_path.write_bytes(raw)
            catalog = {
                "loan_operation_mart": {
                    "object_uri": str(csv_path),
                    "artifact_sha256": hashlib.sha256(raw).hexdigest(),
                    "snapshot_id": "csv-snap-v1",
                    "observed_at": "2026-07-10T00:00:00+00:00",
                    "allowed_metrics": ["drawdown_rate"],
                    "allowed_dimensions": ["branch_name"],
                    "field_types": {
                        "drawdown_rate": "float",
                        "drawdown_amount": "float",
                        "eligible_amount": "float",
                    },
                    "metric_aggregation": {
                        "drawdown_rate": {
                            "aggregation": "ratio",
                            "numerator": "drawdown_amount",
                            "denominator": "eligible_amount",
                            "multiplier": 1,
                        }
                    },
                }
            }
            warehouse = CSVObjectDataWarehouse(catalog, environment="test")
            result = warehouse.query_matrix(
                "loan_operation_mart",
                "tenant_demo",
                ("drawdown_rate",),
                ("branch_name",),
            )
            self.assertEqual(result.totals["drawdown_rate"], 0.35)
            self.assertEqual(result.metric_semantics["drawdown_rate"]["aggregation"], "ratio")
            semantic = InMemorySupersonicClient(warehouse).query(
                SemanticQueryRequest(
                    question="动支率",
                    tenant_id="tenant_demo",
                    user_id="u_admin",
                    dataset_id="loan_operation_mart",
                    metrics=("drawdown_rate",),
                    dimensions=("branch_name",),
                )
            )
            self.assertTrue(semantic.semantic_info["publishable"])
            self.assertFalse(semantic.semantic_info["sql_executed"])
            self.assertEqual(semantic.semantic_info["source_snapshot"]["artifact_sha256"], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError, "csv_object_hash_mismatch"):
                CSVObjectDataWarehouse(
                    {"loan_operation_mart": {**catalog["loan_operation_mart"], "artifact_sha256": "0" * 64}},
                    environment="test",
                )

    def test_metric_dictionary_definition_is_bound_to_plan_and_evidence(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        result = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="各分行放款金额和动支率",
        )
        definitions = result["analysis_plan"]["metric_definitions"]
        self.assertEqual([item["metric_code"] for item in definitions], ["loan_amount", "drawdown_rate"])
        self.assertEqual(definitions[1]["aggregation"], "ratio")
        self.assertEqual(definitions[1]["numerator"], "drawdown_amount")
        semantic = result["skill_results"][0]["semantic_info"]
        evidence = result["skill_results"][0]["evidence"]
        self.assertTrue(semantic["metric_definitions_bound"])
        self.assertEqual(semantic["metric_definition_versions"], {"loan_amount": "v1", "drawdown_rate": "v1"})
        self.assertEqual(evidence["metric_definition_versions"], semantic["metric_definition_versions"])

    def test_published_tenant_metric_cannot_change_reviewed_formula(self) -> None:
        store = InMemoryMetricDictionaryStore()
        store.upsert(
            "tenant_demo",
            {
                "metricId": "tenant_drawdown",
                "metricName": "动支率",
                "metricCode": "drawdown_rate",
                "datasetId": "loan_operation_mart",
                "aggregationType": "ratio",
                "numeratorField": "wrong_numerator",
                "denominatorField": "eligible_amount",
                "semanticStatus": "published",
                "semanticVersion": "tenant-v1",
            },
        )
        catalog = MetricSemanticCatalog.from_config_path(
            Path(__file__).resolve().parents[3] / "configs" / "analysis" / "metric_definitions.json",
            store,
        )
        with self.assertRaisesRegex(MetricSemanticError, "metric_semantic_formula_conflict"):
            catalog.resolve("tenant_demo", "loan_operation_mart", ("drawdown_rate",))

    def test_descriptive_metric_is_not_mistaken_for_executable_formula(self) -> None:
        store = InMemoryMetricDictionaryStore()
        saved = store.upsert(
            "tenant_demo",
            {
                "metricId": "M_TEXT",
                "metricName": "文本口径",
                "valueLogic": "DELETE FROM fact; 仅作为说明文本",
            },
        )
        self.assertEqual(saved["semanticStatus"], "documentation")
        with self.assertRaisesRegex(ValueError, "metric_semantic_metric_code_invalid"):
            store.upsert(
                "tenant_demo",
                {
                    "metricId": "M_BAD",
                    "metricName": "不完整可执行口径",
                    "semanticStatus": "published",
                    "aggregationType": "sum",
                    "semanticVersion": "v1",
                },
            )

    def test_postgresql_warehouse_uses_pool_read_only_paramstyle_and_closes(self) -> None:
        class Cursor:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return list(self.rows)

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class Connection:
            def __init__(self):
                self.calls = []

            def execute(self, sql, parameters=()):
                self.calls.append((sql, tuple(parameters)))
                if sql == "SELECT 1":
                    return Cursor([(1,)])
                if "COUNT(*) FROM" in sql:
                    return Cursor([(2,)])
                if "GROUP BY" in sql and "COUNT(*)" not in sql:
                    return Cursor([("A", 30.0), ("B", 20.0)])
                return Cursor([(50.0,)])

        class Pool:
            def __init__(self):
                self.connection = Connection()
                self.returned = 0
                self.closed = False

            def getconn(self):
                return self.connection

            def putconn(self, connection):
                self.returned += 1

            def close(self):
                self.closed = True

        pool = Pool()
        warehouse = PostgreSQLDataWarehouse(
            "postgresql+psycopg://db.example/analytics",
            {
                "mart": {
                    "source_table": "loan_fact",
                    "tenant_column": "tenant_id",
                    "allowed_metrics": ["loan_amount"],
                    "allowed_dimensions": ["branch_name"],
                    "metric_aggregation": {"loan_amount": "sum"},
                }
            },
            pool=pool,
            min_pool_size=2,
            max_pool_size=8,
        )
        result = warehouse.query_matrix(
            "mart", "tenant_demo", ("loan_amount",), ("branch_name",)
        )
        self.assertEqual(result.totals, {"loan_amount": 50.0})
        self.assertEqual(result.full_group_count, 2)
        generated_sql = "\n".join(call[0] for call in pool.connection.calls)
        self.assertIn("%s", generated_sql)
        self.assertNotIn("?", generated_sql)
        self.assertEqual(pool.returned, 1)
        self.assertTrue(warehouse.health()["ready"])
        self.assertEqual(pool.returned, 2)
        warehouse.close()
        self.assertTrue(pool.closed)

    def test_query_conditions_compile_time_topn_and_sort(self) -> None:
        conditions = parse_query_conditions(
            "近7天最低ROI前5",
            reference_date=date(2026, 7, 10),
        )
        self.assertEqual(conditions.limit, 5)
        self.assertEqual(conditions.sort_direction, "asc")
        self.assertEqual(conditions.time_range["start_date"], "2026-07-04")
        self.assertEqual(conditions.filters["month"], {"gte": "2026-07", "lte": "2026-07"})

    def test_json_matrix_executes_all_metrics_dimensions_and_separate_total(self) -> None:
        result = JSONDataWarehouse().query_matrix(
            dataset_id="loan_operation_mart",
            tenant_id="tenant_demo",
            metrics=("loan_amount", "drawdown_rate"),
            dimensions=("branch_name", "product_line"),
            filters={"month": {"gte": "2026-06", "lte": "2026-06"}},
            limit=1,
            sort_direction="desc",
        )
        self.assertEqual(result.metrics, ("loan_amount", "drawdown_rate"))
        self.assertEqual(result.dimensions, ("branch_name", "product_line"))
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.full_group_count, 3)
        self.assertEqual(result.totals["loan_amount"], 76_800_000)
        self.assertIn("drawdown_rate", result.rows[0])

    def test_empty_in_filter_returns_zero_rows_instead_of_dropping_filter(self) -> None:
        result = JSONDataWarehouse().query_matrix(
            dataset_id="loan_operation_mart",
            tenant_id="tenant_demo",
            metrics=("loan_amount",),
            dimensions=("branch_name",),
            filters={"branch_name": {"in": []}},
        )
        self.assertEqual(result.rows, [])
        self.assertEqual(result.totals, {"loan_amount": 0.0})

    def test_sql_matrix_executes_detail_total_and_full_group_count(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "warehouse.sqlite"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE fact(tenant_id TEXT, branch_name TEXT, product_line TEXT, loan_amount REAL, drawdown_rate REAL)"
            )
            connection.executemany(
                "INSERT INTO fact VALUES (?, ?, ?, ?, ?)",
                [
                    ("tenant_demo", "A", "经营贷", 10, 0.2),
                    ("tenant_demo", "B", "经营贷", 20, 0.4),
                    ("tenant_demo", "C", "消费贷", 30, 0.6),
                    ("tenant_other", "越权", "经营贷", 999, 1.0),
                ],
            )
            connection.commit()
            connection.close()
            warehouse = SQLDataWarehouse(
                lambda: sqlite3.connect(db_path),
                {
                    "loan_operation_mart": {
                        "source_table": "fact",
                        "tenant_column": "tenant_id",
                        "allowed_metrics": ["loan_amount", "drawdown_rate"],
                        "allowed_dimensions": ["branch_name", "product_line"],
                        "metric_aggregation": {"loan_amount": "sum", "drawdown_rate": "avg"},
                    }
                },
            )
            result = warehouse.query_matrix(
                "loan_operation_mart",
                "tenant_demo",
                ("loan_amount", "drawdown_rate"),
                ("branch_name", "product_line"),
                limit=1,
            )
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.full_group_count, 3)
        self.assertEqual(result.totals, {"loan_amount": 60.0, "drawdown_rate": 0.4})
        self.assertIn("-- complete totals query", result.sql)
        self.assertIn("-- complete group count query", result.sql)

    def test_sql_ratio_metric_uses_ratio_of_sums_and_emits_semantics(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ratio.sqlite"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE fact(tenant_id TEXT, branch_name TEXT, drawdown_amount REAL, eligible_amount REAL)"
            )
            connection.executemany(
                "INSERT INTO fact VALUES (?, ?, ?, ?)",
                [
                    ("tenant_demo", "A", 2, 10),
                    ("tenant_demo", "A", 36, 90),
                    ("tenant_demo", "B", 5, 10),
                    ("tenant_other", "越权", 999, 1),
                ],
            )
            connection.commit()
            connection.close()
            warehouse = SQLDataWarehouse(
                lambda: sqlite3.connect(db_path),
                {
                    "loan_operation_mart": {
                        "source_table": "fact",
                        "tenant_column": "tenant_id",
                        "allowed_metrics": ["drawdown_rate"],
                        "allowed_dimensions": ["branch_name"],
                        "metric_aggregation": {
                            "drawdown_rate": {
                                "aggregation": "ratio",
                                "numerator": "drawdown_amount",
                                "denominator": "eligible_amount",
                                "multiplier": 1,
                            }
                        },
                        "source_snapshot": {
                            "snapshot_id": "ingestion-run-001",
                            "observed_at": "2026-07-10T00:00:00+00:00",
                            "latest_partition": "2026-07",
                            "artifact_sha256": "a" * 64,
                            "immutable": True,
                        },
                    }
                },
            )
            result = warehouse.query_matrix(
                "loan_operation_mart",
                "tenant_demo",
                ("drawdown_rate",),
                ("branch_name",),
            )
            semantic = InMemorySupersonicClient(warehouse).query(
                SemanticQueryRequest(
                    question="各分行提款率",
                    tenant_id="tenant_demo",
                    user_id="u_admin",
                    dataset_id="loan_operation_mart",
                    metrics=("drawdown_rate",),
                    dimensions=("branch_name",),
                )
            )
        self.assertEqual(result.rows[0]["branch_name"], "B")
        self.assertEqual(result.rows[0]["drawdown_rate"], 0.5)
        self.assertEqual(result.rows[1]["drawdown_rate"], 0.38)
        self.assertEqual(result.totals["drawdown_rate"], 0.390909)
        self.assertEqual(
            result.metric_semantics["drawdown_rate"],
            {
                "aggregation": "ratio",
                "numerator": "drawdown_amount",
                "denominator": "eligible_amount",
                "multiplier": 1.0,
            },
        )
        self.assertIn('SUM("drawdown_amount")', result.sql)
        self.assertIn('NULLIF(SUM("eligible_amount"), 0)', result.sql)
        self.assertTrue(semantic.semantic_info["aggregation_semantics_complete"])
        self.assertTrue(semantic.semantic_info["publishable"])
        self.assertEqual(semantic.semantic_info["unsafe_rate_metrics"], [])
        self.assertEqual(
            semantic.semantic_info["metric_semantics"]["drawdown_rate"]["numerator"],
            "drawdown_amount",
        )

    def test_sql_ratio_metric_rejects_missing_or_unsafe_components(self) -> None:
        for definition in (
            {"aggregation": "ratio", "numerator": "drawdown_amount"},
            {
                "aggregation": "ratio",
                "numerator": "drawdown_amount; DROP TABLE fact",
                "denominator": "eligible_amount",
            },
        ):
            with self.subTest(definition=definition), self.assertRaises(ValueError):
                SQLDataWarehouse(
                    lambda: sqlite3.connect(":memory:"),
                    {
                        "mart": {
                            "source_table": "fact",
                            "allowed_metrics": ["drawdown_rate"],
                            "allowed_dimensions": ["branch_name"],
                            "metric_aggregation": {"drawdown_rate": definition},
                        }
                    },
                )

    def test_analysis_binds_all_execution_facts_and_blocks_mock_publication(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        response = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年6月各分行放款金额排名TOP1",
            page_context={"request_id": "multi-metric-1"},
        )
        result = response["skill_results"][0]
        mapping = result["semantic_info"]["schema_mapping"]
        self.assertEqual(mapping["metrics"], response["analysis_plan"]["metrics"])
        self.assertEqual(mapping["dimensions"], response["analysis_plan"]["dimensions"])
        self.assertEqual(result["semantic_info"]["totals"]["loan_amount"], 76_800_000)
        self.assertFalse(result["evidence"]["sql_executed"])
        self.assertTrue(result["evidence"]["execution_statement"].startswith("-- NOT EXECUTED AS SQL"))
        self.assertEqual(response["execution_id"], response["task_id"])
        self.assertEqual(response["review"]["publication_gate"], "blocked")

    def test_future_period_returns_no_data_and_needs_review(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        response = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年8月各分行放款金额排名TOP10",
        )
        result = response["skill_results"][0]
        self.assertEqual(result["data"], [])
        self.assertEqual(result["semantic_info"]["source_snapshot"]["latest_partition"], "2026-07")
        self.assertEqual(response["review"]["status"], "needs_human_review")

    def test_idempotency_and_manual_python_revision_create_new_execution(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        first = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年6月各分行放款金额排名TOP2",
            page_context={"request_id": "original-1"},
        )
        replay = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="this question must not replace the original",
            page_context={"request_id": "original-1"},
        )
        self.assertEqual(replay["task_id"], first["task_id"])
        self.assertTrue(replay["idempotent_replay"])

        edited_python = """def build_chart(data, context):
    return {"type": "table", "title": "人工修订", "series": [], "table_rows": data}
"""
        second = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年6月各分行放款金额排名TOP2",
            page_context={
                "request_id": "revision-2",
                "parent_task_id": first["task_id"],
                "edited_sql_script": first["skill_results"][0]["sql"],
                "edited_python_script": edited_python,
                "edited_analysis_plan": "人工说明，不冒充类型化计划",
            },
        )
        self.assertNotEqual(second["task_id"], first["task_id"])
        self.assertEqual(second["parent_execution_id"], first["execution_id"])
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["skill_results"][0]["python_script"], edited_python.strip())
        self.assertEqual(second["manual_edits"]["python"]["status"], "accepted_for_sandbox_execution")
        self.assertEqual(second["manual_edits"]["plan"]["status"], "annotation_only")

    def test_manual_sql_is_read_only_and_cannot_fall_back_to_mock(self) -> None:
        self.assertEqual(validate_read_only_sql_candidate("SELECT * FROM governed_view"), "SELECT * FROM governed_view")
        for value in ("DELETE FROM fact", "SELECT 1; SELECT 2", "SELECT * FROM fact -- bypass"):
            with self.subTest(value=value), self.assertRaises(ManualSQLValidationError):
                validate_read_only_sql_candidate(value)

        services = build_local_platform()
        self.addCleanup(services.close)
        first = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年6月各分行放款金额",
            page_context={"request_id": "manual-base"},
        )
        with self.assertRaisesRegex(RuntimeError, "manual_sql_requires_one_verified_tenant_connection"):
            run_analysis(
                services,
                user_id="u_admin",
                tenant_id="tenant_demo",
                question="2026年6月各分行放款金额",
                page_context={
                    "request_id": "manual-failed",
                    "parent_task_id": first["task_id"],
                    "edited_sql_script": "SELECT branch_name, SUM(loan_amount) FROM governed_view GROUP BY branch_name",
                },
            )
        failed = services.task_repository.get_task_by_request("tenant_demo", "manual-failed")
        self.assertEqual(failed["status"], "failed")


if __name__ == "__main__":
    unittest.main()
