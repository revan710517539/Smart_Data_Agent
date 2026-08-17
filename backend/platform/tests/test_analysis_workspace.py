from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.api.routes.analysis import _analysis_cache_context, _cache_snapshot_matches
from backend.platform.analysis_workspace.models import AnalysisWorkspaceContext
from backend.platform.analysis_workspace.service import (
    AnalysisWorkspaceService,
    InMemoryAnalysisGovernanceStore,
    InMemoryAnalysisWorkspaceStore,
    build_trusted_manifest,
    safe_cache_key,
    verify_trusted_manifest,
)
from backend.platform.analysis_workspace.visualization import VisualizationPlanner
from backend.platform.bootstrap import build_local_platform
from backend.platform.api.routes.analysis import run_analysis


class AnalysisWorkspaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryAnalysisWorkspaceStore()
        self.service = AnalysisWorkspaceService(self.store)
        self.context = AnalysisWorkspaceContext(
            page_key="dashboard",
            artifact_id="report-1",
            dataset_snapshot={"sha256": "a" * 64},
            metric_versions=({"metric_id": "m1", "version": 2},),
            allowed_actions=("branch", "merge"),
        )

    def test_workspace_root_branch_turn_and_merge_are_persistent(self) -> None:
        workspace = self.service.ensure_workspace("tenant-a", "user-a", "dashboard", self.context)
        root = self.service.threads("tenant-a", "user-a", workspace["workspace_id"])[0]
        branch = self.service.branch(
            "tenant-a", "user-a", workspace["workspace_id"],
            parent_thread_id=root["thread_id"], title="指标追问", anchor={"metric": "m1"},
        )
        turn = self.service.append_turn(
            "tenant-a", "user-a", branch["thread_id"],
            {"question": "为什么下降", "answer": "渠道贡献下降", "status": "completed", "evidence_refs": [{"id": "e1"}]},
        )
        self.assertEqual(turn["turn_no"], 1)
        merged = self.service.merge(
            "tenant-a", "user-a", root["thread_id"], [branch["thread_id"]],
            question="合并分支结论", answer="总体下降由渠道贡献下降驱动", evidence_refs=[{"id": "e1"}],
        )
        self.assertEqual(merged["turn"]["turn_no"], 1)
        threads = self.service.threads("tenant-a", "user-a", workspace["workspace_id"])
        self.assertEqual(next(item for item in threads if item["thread_id"] == branch["thread_id"])["status"], "merged")

    def test_cross_user_and_cross_workspace_operations_fail_closed(self) -> None:
        first = self.service.ensure_workspace("tenant-a", "user-a", "dashboard", self.context)
        second = self.service.ensure_workspace("tenant-a", "user-a", "dashboard:other", AnalysisWorkspaceContext(page_key="dashboard"))
        first_root = self.service.threads("tenant-a", "user-a", first["workspace_id"])[0]
        second_root = self.service.threads("tenant-a", "user-a", second["workspace_id"])[0]
        with self.assertRaisesRegex(PermissionError, "not_owned"):
            self.service.workspace("tenant-a", "user-b", first["workspace_id"])
        with self.assertRaisesRegex(PermissionError, "workspace_mismatch"):
            self.service.merge("tenant-a", "user-a", first_root["thread_id"], [second_root["thread_id"]], question="合并", answer="不允许", evidence_refs=[])

    def test_trust_manifest_and_cache_key_bind_governance_inputs(self) -> None:
        manifest = build_trusted_manifest(
            tenant_id="tenant-a", artifact_id="a1", dataset_snapshot={"sha": "1"}, metric_versions=[{"m": 1}],
            sql="SELECT 1", result=[{"v": 1}], visualization={"type": "kpi"}, skill_versions=[{"s": 2}],
            model_version="model-1", authorization_snapshot={"policy": 1}, evidence_refs=[{"e": 1}], evaluation={"status": "passed"},
        )
        self.assertEqual(len(manifest["manifest_hash"]), 64)
        self.assertTrue(verify_trusted_manifest(manifest))
        self.assertFalse(verify_trusted_manifest({**manifest, "result_hash": "tampered"}))
        first = safe_cache_key(tenant_id="tenant-a", authorization_snapshot={"p": 1}, institution_ids=["b", "a"], csv_snapshot={"s": 1}, semantic_versions=[{"m": 1}], filters={}, time_grain="month", skill_versions=[], model_version="m", code_version="c")
        second = safe_cache_key(tenant_id="tenant-a", authorization_snapshot={"p": 2}, institution_ids=["a", "b"], csv_snapshot={"s": 1}, semantic_versions=[{"m": 1}], filters={}, time_grain="month", skill_versions=[], model_version="m", code_version="c")
        self.assertNotEqual(first, second)

    def test_cache_key_binds_question_and_cache_rechecks_authorization(self) -> None:
        first = safe_cache_key(tenant_id="tenant-a", question="余额趋势", authorization_snapshot={"p": 1}, institution_ids=["a"], csv_snapshot={"s": 1}, semantic_versions=[{"m": 1}], filters={}, time_grain="month", skill_versions=[], model_version="m", code_version="c")
        second = safe_cache_key(tenant_id="tenant-a", question="风险趋势", authorization_snapshot={"p": 1}, institution_ids=["a"], csv_snapshot={"s": 1}, semantic_versions=[{"m": 1}], filters={}, time_grain="month", skill_versions=[], model_version="m", code_version="c")
        self.assertNotEqual(first, second)
        store = InMemoryAnalysisGovernanceStore()
        store.put_cache("tenant-a", "user-a", {"cache_key": first, "authorization_hash": "a", "csv_snapshot_hash": "b", "semantic_version_hash": "c", "execution_version_hash": "d", "result_ref": "task-1"})
        self.assertIsNotNone(store.get_cache("tenant-a", "user-a", first, "a"))
        self.assertIsNone(store.get_cache("tenant-a", "user-a", first, "changed"))
        self.assertIsNone(store.get_cache("tenant-a", "user-b", first, "a"))

    def test_analysis_cache_requires_versioned_code_and_verified_csv_snapshot(self) -> None:
        services = build_local_platform()
        table = {
            "id": "table-1",
            "relativePath": "tenant_demo/topic/data.csv",
            "contentHash": "a" * 64,
            "schemaFingerprint": "schema-v1",
            "schemaVersion": "1",
        }
        with patch.dict("os.environ", {"SMART_DATA_AGENT_CODE_VERSION": ""}, clear=False):
            self.assertIsNone(_analysis_cache_context(
                services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="余额趋势",
                requested_context={},
                asset_context={"selected_data_tables": [table]},
                selected_model=None,
            ))
        with patch.dict("os.environ", {"SMART_DATA_AGENT_CODE_VERSION": "test-commit"}, clear=False):
            context = _analysis_cache_context(
                services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="余额趋势",
                requested_context={"filters": {"year": 2026}},
                asset_context={"selected_data_tables": [table]},
                selected_model=None,
            )
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(len(context["authorization_hash"]), 64)
        valid_task = SimpleNamespace(
            status="completed",
            skill_results=[{"semantic_info": {"source_snapshot": {
                "content_hash": "a" * 64,
                "schema_fingerprint": "schema-v1",
            }}}],
        )
        stale_task = SimpleNamespace(
            status="completed",
            skill_results=[{"semantic_info": {"source_snapshot": {
                "content_hash": "b" * 64,
                "schema_fingerprint": "schema-v1",
            }}}],
        )
        self.assertTrue(_cache_snapshot_matches(context, valid_task))
        self.assertFalse(_cache_snapshot_matches(context, stale_task))

    def test_execution_nodes_expose_ordered_dag_without_cross_user_access(self) -> None:
        services = build_local_platform()
        try:
            from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse

            attach_governed_test_warehouse(services)
            task = run_analysis(services, "u_super_admin", "tenant_demo", "各分行放款金额")
            nodes = services.task_repository.execution_nodes(
                "tenant_demo", "u_super_admin", task["task_id"]
            )
            self.assertGreaterEqual(len(nodes), 4)
            self.assertEqual(nodes[0]["input_refs"], [])
            self.assertEqual(nodes[1]["input_refs"][0]["depends_on"], nodes[0]["step_code"])
            self.assertTrue(all(node["status"] == "succeeded" for node in nodes))
            self.assertEqual(
                services.task_repository.execution_nodes("tenant_demo", "u_reviewer", task["task_id"]),
                [],
            )
        finally:
            services.close()

    def test_analysis_run_persists_exactly_one_bound_workspace_turn(self) -> None:
        services = build_local_platform()
        try:
            from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse

            attach_governed_test_warehouse(services)
            workspace = services.analysis_workspace_service.ensure_workspace(
                "tenant_demo",
                "u_super_admin",
                "dashboard",
                AnalysisWorkspaceContext(page_key="dashboard"),
            )
            root = services.analysis_workspace_service.threads(
                "tenant_demo", "u_super_admin", workspace["workspace_id"]
            )[0]
            result = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "各分行放款金额",
                page_context={
                    "workspace_id": workspace["workspace_id"],
                    "thread_id": root["thread_id"],
                },
            )
            self.assertEqual(result["workspace_turn"]["turn_no"], 1)
            threads = services.analysis_workspace_service.threads(
                "tenant_demo", "u_super_admin", workspace["workspace_id"]
            )
            self.assertEqual(len(threads[0]["turns"]), 1)
            self.assertEqual(
                threads[0]["turns"][0]["execution_plan"]["task_id"],
                result["task_id"],
            )
            with self.assertRaisesRegex(PermissionError, "not_owned"):
                run_analysis(
                    services,
                    "u_reviewer",
                    "tenant_demo",
                    "各分行放款金额",
                    page_context={
                        "workspace_id": workspace["workspace_id"],
                        "thread_id": root["thread_id"],
                    },
                )
        finally:
            services.close()


class VisualizationPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = VisualizationPlanner()

    def test_selects_trend_scatter_funnel_pivot_and_safe_table(self) -> None:
        trend = self.planner.plan(question="月度趋势", rows=[{"month": "2026-01", "value": 1}, {"month": "2026-02", "value": 2}], dimensions=["month"], metrics=["value"])
        self.assertEqual(trend.chart_type, "line")
        scatter = self.planner.plan(question="两个指标相关性", rows=[{"x": 1, "y": 2}, {"x": 2, "y": 4}], dimensions=[], metrics=["x", "y"])
        self.assertEqual(scatter.chart_type, "scatter")
        funnel = self.planner.plan(question="申请转化漏斗", rows=[{"stage": "申请", "value": 10}, {"stage": "审批", "value": 5}], dimensions=["stage"], metrics=["value"])
        self.assertEqual(funnel.chart_type, "funnel")
        pivot = self.planner.plan(question="多维汇总", rows=[{"branch": f"b{i%4}", "month": f"2026-{i%12+1:02d}", "a": i, "b": i * 2} for i in range(120)], dimensions=["branch", "month"], metrics=["a", "b"])
        self.assertEqual(pivot.chart_type, "pivot")
        table = self.planner.plan(question="明细", rows=[{"name": "a"}], dimensions=["name"], metrics=[])
        self.assertEqual(table.chart_type, "table")
        treemap = self.planner.plan(question="分析区域层级贡献", rows=[{"region": "华东", "value": 10}, {"region": "华南", "value": 8}], dimensions=["region"], metrics=["value"])
        self.assertEqual(treemap.chart_type, "treemap")

    def test_explicit_user_chart_request_wins_only_when_compatible(self) -> None:
        rows = [{"month": "2026-01", "value": 1}, {"month": "2026-02", "value": 2}]
        requested_table = self.planner.plan(question="月度趋势", rows=rows, dimensions=["month"], metrics=["value"], requested_chart_types=["table"])
        self.assertEqual(requested_table.chart_type, "table")
        incompatible_scatter = self.planner.plan(question="月度趋势", rows=rows, dimensions=["month"], metrics=["value"], requested_chart_types=["scatter"])
        self.assertEqual(incompatible_scatter.chart_type, "line")
        self.assertIn("安全回退", incompatible_scatter.reason)


if __name__ == "__main__":
    unittest.main()
