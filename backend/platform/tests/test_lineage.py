from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform


class LineageTest(unittest.TestCase):
    def test_analysis_records_bidirectional_metric_dataset_query_evidence_lineage(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        task = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="各分行放款金额和动支率",
        )
        graph = services.lineage_store.graph(
            "tenant_demo",
            "dataset",
            "loan_operation_mart",
            direction="downstream",
            max_depth=4,
        )
        nodes = {(node["entity_type"], node["entity_id"]) for node in graph["nodes"]}
        self.assertIn(("analysis_task", task["task_id"]), nodes)
        self.assertTrue(any(node_type == "analysis_query" for node_type, _ in nodes))
        self.assertTrue(any(node_type == "analysis_evidence" for node_type, _ in nodes))
        metric_graph = services.lineage_store.graph(
            "tenant_demo",
            "metric_version",
            "loan_operation_mart:drawdown_rate:v1",
            direction="downstream",
            max_depth=3,
        )
        self.assertTrue(any(edge["edge_type"] == "aggregates" for edge in metric_graph["edges"]))
        upstream = services.lineage_store.graph(
            "tenant_demo",
            "analysis_task",
            task["task_id"],
            direction="upstream",
            max_depth=4,
        )
        self.assertIn(("dataset", "loan_operation_mart"), {(node["entity_type"], node["entity_id"]) for node in upstream["nodes"]})

    def test_sqlite_lineage_is_durable_and_tenant_isolated(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            first = build_local_platform(db_path)
            try:
                task = run_analysis(first, "u_admin", "tenant_demo", "各分行放款金额")
            finally:
                first.close()
            second = build_local_platform(db_path)
            try:
                graph = second.lineage_store.graph(
                    "tenant_demo", "analysis_task", task["task_id"], direction="upstream"
                )
                self.assertGreater(len(graph["edges"]), 0)
                other = second.lineage_store.graph(
                    "tenant_other", "analysis_task", task["task_id"], direction="upstream"
                )
                self.assertEqual(other["edges"], [])
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
