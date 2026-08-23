from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.api.routes.analysis import (
    _analysis_cache_context,
    _cache_snapshot_matches,
    _inherit_chart_follow_up_context,
    _visual_analysis_scope,
    run_analysis,
)
from backend.platform.intelligent_analysis.engine import IntelligentAnalysisEngine, IntelligentAnalysisRequest
from backend.platform.analysis_workspace.models import AnalysisWorkspaceContext
from backend.platform.analysis_workspace.service import (
    AnalysisWorkspaceService,
    InMemoryAnalysisGovernanceStore,
    InMemoryAnalysisWorkspaceStore,
    build_trusted_manifest,
    provenance_dataset_snapshot,
    provenance_metric_versions,
    safe_cache_key,
    verify_trusted_manifest,
)
from backend.platform.analysis_workspace.visualization import VisualizationPlanner
from backend.platform.bootstrap import build_local_platform


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

    def test_new_root_thread_keeps_previous_turns_across_reensure(self) -> None:
        workspace = self.service.ensure_workspace("tenant-a", "user-a", "self-analysis", AnalysisWorkspaceContext(page_key="self-analysis"))
        root = self.service.threads("tenant-a", "user-a", workspace["workspace_id"])[0]
        self.service.append_turn(
            "tenant-a", "user-a", root["thread_id"],
            {"question": "分析一下这个数据", "answer": "经营贷逾期上行", "status": "completed"},
        )
        fresh = self.service.branch(
            "tenant-a", "user-a", workspace["workspace_id"],
            parent_thread_id=None, title="新分析", anchor={"command": "new"},
        )
        self.assertIsNone(fresh["parent_thread_id"])
        restored = self.service.ensure_workspace("tenant-a", "user-a", "self-analysis", AnalysisWorkspaceContext(page_key="self-analysis"))
        threads = self.service.threads("tenant-a", "user-a", restored["workspace_id"])
        self.assertEqual(restored["workspace_id"], workspace["workspace_id"])
        self.assertEqual(len(threads), 2)
        self.assertEqual(next(item for item in threads if item["thread_id"] == root["thread_id"])["turns"][0]["answer"], "经营贷逾期上行")
        self.assertEqual(next(item for item in threads if item["thread_id"] == fresh["thread_id"])["turns"], [])

    def test_new_presentation_session_starts_empty_and_preserves_prior_conclusion(self) -> None:
        first = self.service.ensure_workspace(
            "tenant-a", "user-a", "dashboard:analysis_session_first", AnalysisWorkspaceContext(page_key="dashboard")
        )
        first_root = self.service.threads("tenant-a", "user-a", first["workspace_id"])[0]
        self.service.append_turn(
            "tenant-a", "user-a", first_root["thread_id"],
            {"question": "为什么五月份降下来了", "answer": "结论已存档", "status": "completed"},
        )

        second = self.service.ensure_workspace(
            "tenant-a", "user-a", "dashboard:analysis_session_second", AnalysisWorkspaceContext(page_key="dashboard")
        )
        second_threads = self.service.threads("tenant-a", "user-a", second["workspace_id"])
        archived_threads = self.service.threads("tenant-a", "user-a", first["workspace_id"])

        self.assertNotEqual(first["workspace_id"], second["workspace_id"])
        self.assertEqual(second_threads[0]["turns"], [])
        self.assertEqual(archived_threads[0]["turns"][0]["answer"], "结论已存档")

    def test_archive_thread_hides_history_but_keeps_last_root(self) -> None:
        workspace = self.service.ensure_workspace("tenant-a", "user-a", "self-analysis", AnalysisWorkspaceContext(page_key="self-analysis"))
        root = self.service.threads("tenant-a", "user-a", workspace["workspace_id"])[0]
        branch = self.service.branch(
            "tenant-a", "user-a", workspace["workspace_id"],
            parent_thread_id=root["thread_id"], title="主分析视图 · 条形图", anchor={},
        )
        archived = self.service.archive_thread("tenant-a", "user-a", branch["thread_id"])
        self.assertEqual(archived["status"], "archived")
        with self.assertRaisesRegex(ValueError, "last_active"):
            self.service.archive_thread("tenant-a", "user-a", root["thread_id"])
        remaining = [item for item in self.service.threads("tenant-a", "user-a", workspace["workspace_id"]) if item["status"] != "archived"]
        self.assertEqual([item["thread_id"] for item in remaining], [root["thread_id"]])

    def test_same_page_key_is_isolated_per_user(self) -> None:
        first = self.service.ensure_workspace("tenant-a", "user-a", "self-analysis", AnalysisWorkspaceContext(page_key="self-analysis"))
        second = self.service.ensure_workspace("tenant-a", "user-b", "self-analysis", AnalysisWorkspaceContext(page_key="self-analysis"))
        self.assertNotEqual(first["workspace_id"], second["workspace_id"])
        self.assertEqual(first["workspace_key"], "self-analysis")
        self.assertEqual(second["workspace_key"], "self-analysis:user-b")
        self.service.append_turn(
            "tenant-a", "user-a", self.service.threads("tenant-a", "user-a", first["workspace_id"])[0]["thread_id"],
            {"question": "owner question", "answer": "owner answer", "status": "completed"},
        )
        other_threads = self.service.threads("tenant-a", "user-b", second["workspace_id"])
        self.assertEqual(other_threads[0]["turns"], [])

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

    def test_provenance_helpers_normalize_snapshot_and_metric_versions(self) -> None:
        snapshot = provenance_dataset_snapshot(
            {"snapshot_id": "snap-1", "artifact_sha256": "a" * 64, "immutable": True},
            {"contentHash": "b" * 64, "schemaFingerprint": "schema-v2"},
        )
        self.assertEqual(snapshot["version"], "snap-1")
        self.assertEqual(snapshot["schema_fingerprint"], "schema-v2")
        self.assertEqual(snapshot["content_hash"], "a" * 64)
        derived = provenance_dataset_snapshot(
            {"id": "csv_overdue"},
            schema_material={"metrics": ["m1_overdue_rate"], "dimensions": ["product_line"]},
            content_material=[{"product_line": "经营贷", "m1_overdue_rate": 0.0145}],
        )
        self.assertTrue(derived.get("version"))
        self.assertTrue(derived.get("schema_fingerprint"))
        self.assertTrue(derived.get("content_hash"))
        versions = provenance_metric_versions(
            {"m1_overdue_rate": "v3"},
            [{"metricCode": "loan_amount", "semanticVersion": "v2"}],
            {"m2": "temporary"},
            [{"metric_id": "m3", "version": "table-field"}],
        )
        self.assertEqual(versions[0], {"metric_id": "m1_overdue_rate", "version": "v3"})
        self.assertEqual(versions[1], {"metric_id": "loan_amount", "version": "v2"})
        self.assertEqual(len(versions), 2)

    def test_warehouse_analysis_records_snapshot_without_inventing_metric_versions(self) -> None:
        services = build_local_platform()
        try:
            from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse

            attach_governed_test_warehouse(services)
            result = run_analysis(services, "u_super_admin", "tenant_demo", "各分行放款金额")
            manifest = result["skill_results"][0]["trusted_manifest"]
            snapshot = manifest["dataset_snapshot"]
            self.assertTrue(snapshot.get("version") or snapshot.get("snapshot_id"))
            self.assertTrue(snapshot.get("schema_fingerprint"))
            self.assertFalse(any(str(item.get("version") or "") in {"temporary", "table-field"} for item in manifest["metric_versions"]))
        finally:
            services.close()

    def test_embedded_follow_up_records_selected_table_snapshot(self) -> None:
        services = build_local_platform()
        try:
            result = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "分析一下这个数据",
                page_context={
                    "visual_analysis_scope": "chart",
                    "chart_bound_source": True,
                    "analysis_policy": {"resultFormat": "brief_visual"},
                    "selected_data_point": {
                        "targetType": "chart",
                        "targetId": "chart-1",
                        "values": {
                            "chart_bound_source": True,
                            "visual_rows": [{"product_line": "经营贷", "m1_overdue_rate": 0.0145}],
                            "selected_data_tables": [{
                                "id": "csv_overdue",
                                "kind": "raw",
                                "code": "csv_overdue",
                                "contentHash": "c" * 64,
                                "schemaFingerprint": "schema-overdue",
                                "assetVersion": "12",
                                "metricCodes": ["m1_overdue_rate"],
                            }],
                            "dataset_snapshot": {"id": "csv_overdue", "content_hash": "c" * 64, "schema_fingerprint": "schema-overdue"},
                        },
                    },
                },
            )
            manifest = result["skill_results"][0]["trusted_manifest"]
            snapshot = manifest["dataset_snapshot"]
            self.assertEqual(snapshot.get("content_hash") or snapshot.get("version"), "c" * 64)
            self.assertEqual(snapshot.get("schema_fingerprint"), "schema-overdue")
            self.assertEqual(manifest["metric_versions"], [])
        finally:
            services.close()

    def test_embedded_follow_up_derives_snapshot_when_table_hashes_missing(self) -> None:
        services = build_local_platform()
        try:
            result = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "分析一下这个数据",
                page_context={
                    "visual_analysis_scope": "chart",
                    "chart_bound_source": True,
                    "analysis_policy": {"resultFormat": "brief_visual"},
                    "selected_data_point": {
                        "targetType": "chart",
                        "targetId": "chart-1",
                        "values": {
                            "chart_bound_source": True,
                            "visual_rows": [{"product_line": "经营贷", "month": "2026-06", "m1_overdue_rate": 0.0145}],
                            "selected_data_tables": [{
                                "id": "csv_overdue",
                                "kind": "raw",
                                "code": "csv_overdue",
                                "fields": "product_line(产品线:string), month(月份:string), m1_overdue_rate(M1逾期率:decimal)",
                                "fieldLabels": {"product_line": "产品线", "month": "月份", "m1_overdue_rate": "M1逾期率"},
                            }],
                        },
                    },
                },
            )
            manifest = result["skill_results"][0]["trusted_manifest"]
            snapshot = manifest["dataset_snapshot"]
            self.assertTrue(snapshot.get("version") or snapshot.get("content_hash"))
            self.assertTrue(snapshot.get("schema_fingerprint"))
            self.assertEqual(manifest["metric_versions"], [])
        finally:
            services.close()

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

    def test_chart_follow_up_inherits_parent_tables_and_plan(self) -> None:
        inherited = _inherit_chart_follow_up_context(
            {
                "selected_data_point": {
                    "targetType": "chart",
                    "targetId": "task-1:primary",
                    "values": {"analysis_task_id": "task-1", "chart_bound_source": True},
                }
            },
            {
                "task_id": "task-1",
                "analysis_plan": {
                    "dataset_id": "custom_mart",
                    "metrics": ["loan_balance"],
                    "dimensions": ["month"],
                    "chart_types": ["column"],
                },
                "skill_results": [{
                    "intelligent_analysis": {
                        "context": {
                            "asset_context": {
                                "selected_data_tables": [{
                                    "id": "topic_chart_source",
                                    "code": "chart_source",
                                    "datasetId": "custom_mart",
                                }],
                            }
                        }
                    }
                }],
            },
        )
        self.assertEqual(inherited["selected_data_tables"][0]["id"], "topic_chart_source")
        self.assertEqual(inherited["analysis_plan_hint"]["dataset_id"], "custom_mart")
        self.assertEqual(inherited["analysis_plan_hint"]["metrics"], ["loan_balance"])
        from_point = _inherit_chart_follow_up_context(
            {
                "selected_data_point": {
                    "values": {
                        "selected_data_tables": [{"id": "csv_chart", "code": "csv_chart"}],
                    }
                }
            },
            None,
        )
        self.assertEqual(from_point["selected_data_tables"][0]["id"], "csv_chart")
        self.assertNotIn("analysis_plan_hint", from_point)
        complete = _inherit_chart_follow_up_context(
            {
                "selected_data_tables": [{
                    "id": "topic_ready",
                    "datasetId": "custom_mart",
                    "metricCodes": ["loan_balance"],
                    "dimensionCodes": ["month"],
                }]
            },
            {
                "analysis_plan": {
                    "dataset_id": "other_mart",
                    "metrics": ["loan_amount"],
                    "dimensions": ["branch_name"],
                }
            },
        )
        self.assertEqual(complete["selected_data_tables"][0]["id"], "topic_ready")
        self.assertNotIn("analysis_plan_hint", complete)
        csv_bound = _inherit_chart_follow_up_context(
            {
                "chart_bound_source": True,
                "selected_data_point": {
                    "targetType": "chart",
                    "values": {
                        "question": "按客群分析贷款余额",
                        "chart_bound_source": True,
                        "analysis_task_id": "task-1",
                    },
                },
            },
            {
                "analysis_plan": {
                    "dataset_id": "csv_88477a04ee48",
                    "metrics": ["field_2"],
                    "dimensions": ["field_1"],
                },
                "skill_results": [{
                    "intelligent_analysis": {
                        "context": {
                            "asset_context": {
                                "selected_data_tables": [{
                                    "id": "csv_88477a04ee489135224dac6a",
                                    "relativePath": "csv/yushu/data.csv",
                                }],
                            }
                        }
                    }
                }],
            },
        )
        self.assertEqual(csv_bound["selected_data_tables"][0]["id"], "csv_88477a04ee489135224dac6a")
        self.assertNotIn("analysis_plan_hint", csv_bound)
        self.assertEqual(csv_bound["follow_up_source_question"], "按客群分析贷款余额")
        governed = _inherit_chart_follow_up_context(
            {"chart_bound_source": True, "selected_data_point": {"targetType": "chart", "values": {"chart_bound_source": True}}},
            {"analysis_plan": {"dataset_id": "loan_operation_mart", "metrics": ["loan_amount"], "dimensions": ["branch_name"]}},
        )
        self.assertEqual(governed["analysis_plan_hint"]["dataset_id"], "loan_operation_mart")

    def test_chart_follow_up_binds_parent_task_from_selected_data_point(self) -> None:
        services = build_local_platform()
        try:
            from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse

            attach_governed_test_warehouse(services)
            first = run_analysis(services, "u_super_admin", "tenant_demo", "各分行放款金额")
            second = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "你好呀",
                page_context={
                    "selected_data_point": {
                        "targetType": "chart",
                        "targetId": f"{first['task_id']}:primary",
                        "label": "主分析视图·条形图",
                        "values": {
                            "analysis_task_id": first["task_id"],
                            "chart_bound_source": True,
                        },
                    }
                },
            )
            self.assertEqual(second["parent_execution_id"], first["execution_id"])
            self.assertEqual(second["revision"], 2)
            self.assertEqual(second["analysis_plan"]["dataset_id"], first["analysis_plan"]["dataset_id"])
            self.assertEqual(second["analysis_plan"]["metrics"], first["analysis_plan"]["metrics"])
        finally:
            services.close()

    def test_visual_follow_up_reuses_parent_chart_rows_without_reselecting_tables(self) -> None:
        services = build_local_platform()
        try:
            from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse

            attach_governed_test_warehouse(services)
            first = run_analysis(services, "u_super_admin", "tenant_demo", "各分行放款金额")
            self.assertTrue(first["skill_results"][0]["data"])
            second = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "分析一下",
                page_context={
                    "chart_bound_source": True,
                    "selected_data_point": {
                        "targetType": "chart",
                        "targetId": f"{first['task_id']}:primary",
                        "label": "主分析视图·条形图",
                        "values": {
                            "analysis_task_id": first["task_id"],
                            "chart_bound_source": True,
                            "question": first["question"],
                        },
                    },
                },
            )
            self.assertEqual(second["parent_execution_id"], first["execution_id"])
            self.assertEqual(second["skill_results"][0]["data"], first["skill_results"][0]["data"])
            self.assertNotEqual(second["task_id"], first["task_id"])
        finally:
            services.close()

    def test_page_visual_analysis_unions_all_chart_rows(self) -> None:
        self.assertEqual(_visual_analysis_scope({"visual_analysis_scope": "page", "chart_bound_source": True}), "page")
        self.assertEqual(_visual_analysis_scope({"selected_data_point": {"targetType": "chart", "values": {"chart_bound_source": True}}}), "chart")
        services = build_local_platform()
        try:
            result = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "分析一下",
                page_context={
                    "visual_analysis_scope": "page",
                    "visual_analysis_sources": [
                        {"id": "c1", "label": "放款图", "rows": [{"branch": "A", "loan_balance": 1}]},
                        {"id": "c2", "label": "风险图", "rows": [{"branch": "B", "loan_balance": 2}]},
                    ],
                },
            )
            data = result["skill_results"][0]["data"]
            self.assertEqual(len(data), 2)
            self.assertEqual({row["_visual_source"] for row in data}, {"放款图", "风险图"})
            self.assertTrue(result["skill_results"][0]["semantic_info"]["page_visual_union"])
        finally:
            services.close()

    def test_page_scope_ignores_stale_chart_follow_up_point(self) -> None:
        services = build_local_platform()
        try:
            from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse

            attach_governed_test_warehouse(services)
            first = run_analysis(services, "u_super_admin", "tenant_demo", "各分行放款金额")
            result = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "分析一下",
                page_context={
                    "visual_analysis_scope": "page",
                    "selected_data_point": {
                        "targetType": "chart",
                        "targetId": f"{first['task_id']}:primary",
                        "values": {
                            "analysis_task_id": first["task_id"],
                            "chart_bound_source": True,
                            "visual_rows": [{"only": "chart"}],
                        },
                    },
                    "visual_analysis_sources": [
                        {"id": "c1", "label": "图1", "rows": [{"branch": "A"}]},
                        {"id": "c2", "label": "图2", "rows": [{"branch": "B"}]},
                    ],
                },
            )
            data = result["skill_results"][0]["data"]
            self.assertEqual(len(data), 2)
            self.assertFalse(result.get("parent_execution_id"))
            self.assertEqual({row["_visual_source"] for row in data}, {"图1", "图2"})
        finally:
            services.close()

    def test_chart_scope_uses_embedded_rows_when_catalog_unavailable(self) -> None:
        services = build_local_platform()
        try:
            result = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "分析一下",
                page_context={
                    "visual_analysis_scope": "chart",
                    "chart_bound_source": True,
                    "selected_data_point": {
                        "targetType": "chart",
                        "targetId": "page-data:1",
                        "label": "页面图",
                        "values": {
                            "chart_bound_source": True,
                            "question": "页面图",
                            "visual_rows": [{"branch": "A", "value": 9}],
                            "selected_data_tables": [{"id": "missing_page_data", "kind": "page_data", "code": "page_data_1"}],
                        },
                    },
                },
            )
            self.assertEqual(result["skill_results"][0]["data"][0]["branch"], "A")
            self.assertEqual(result["skill_results"][0]["data"][0]["value"], 9)
        finally:
            services.close()

    def test_rail_concise_follow_up_returns_short_summary_and_runtime_chain(self) -> None:
        services = build_local_platform()
        try:
            result = run_analysis(
                services,
                "u_super_admin",
                "tenant_demo",
                "分析一下这个数据",
                page_context={
                    "visual_analysis_scope": "chart",
                    "chart_bound_source": True,
                    "analysis_policy": {"resultFormat": "concise_visual", "resultDelivery": "planned_analysis"},
                    "selected_data_point": {
                        "targetType": "chart",
                        "targetId": "chart-1",
                        "values": {
                            "chart_bound_source": True,
                            "question": "经营贷逾期",
                            "visual_rows": [
                                {"product_line": "经营贷", "month": "2026-03", "m1_overdue_rate": 0.0118, "loan_balance": 1.88e9},
                                {"product_line": "经营贷", "month": "2026-06", "m1_overdue_rate": 0.0145, "loan_balance": 1.37e9},
                                {"product_line": "消费贷", "month": "2026-05", "m1_overdue_rate": 0.0096, "loan_balance": 1.21e9},
                                {"product_line": "消费贷", "month": "2026-06", "m1_overdue_rate": 0.0109, "loan_balance": 1.21e9},
                            ],
                        },
                    },
                },
            )
            summary = str(result["intelligent_analysis"]["analysis_summary"])
            self.assertLessEqual(len(summary), 400)
            self.assertNotIn("经营建议", summary)
            self.assertNotIn("核心结论：", summary)
            self.assertNotIn("证据：", summary)
            self.assertIn("经营贷", summary)
            self.assertIn("M1逾期率", summary)
            spec = result["skill_results"][0]["visualization_spec"]
            self.assertTrue(spec.get("chart_type"))
            self.assertTrue(spec.get("x") or spec.get("y"))
            invocation = result["intelligent_analysis"]["model_invocation"]
            self.assertEqual(invocation.get("status"), "skipped")
            self.assertIn("未选择模型", invocation.get("message", ""))
            runtime = result["intelligent_analysis"]["runtime_chain"]
            self.assertEqual(runtime["engine"], "IntelligentAnalysisEngine")
            self.assertEqual(runtime["dataset_scope"], "chart")
            self.assertEqual([item["code"] for item in runtime["stages"]], [
                "scene_intent", "analysis_plan", "skill_dispatch", "memory_fusion", "evidence_query", "result_synthesis",
            ])
        finally:
            services.close()

    def test_brief_conclusions_describe_trend_without_essay(self) -> None:
        engine = IntelligentAnalysisEngine()
        payload = engine.analyze(
            IntelligentAnalysisRequest(
                question="分析一下这个数据",
                tenant_id="tenant_demo",
                user_id="u_super_admin",
                context_policy={"resultFormat": "brief_visual"},
                surface_context={"visual_analysis_scope": "chart"},
                query_result={"data": [
                    {"product_line": "经营贷", "month": "2026-03", "m1_overdue_rate": 0.0118},
                    {"product_line": "经营贷", "month": "2026-06", "m1_overdue_rate": 0.0145},
                ]},
            ),
            {},
        )
        summary = str(payload["analysis_summary"])
        self.assertLessEqual(len(summary), 280)
        self.assertIn("经营贷", summary)
        self.assertNotIn("原因边界", summary)


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
