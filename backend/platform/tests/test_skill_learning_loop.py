from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.platform.api.server import create_server
from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.skills import SkillRequest
from backend.platform.tenancy import ExecutionContext


class SkillLearningLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()
        self.context = ExecutionContext("u_super_admin", "tenant_demo")

    def tearDown(self) -> None:
        self.services.close()

    def test_four_data_product_skills_are_implemented_and_evidence_bound(self) -> None:
        statuses = {
            item["skill_id"]: item
            for item in self.services.skill_registry.list_runtime_statuses()
        }
        for skill_id in (
            "data.analysis.profile",
            "data.governance.assess",
            "conclusion.generate",
            "bi.report.generate",
        ):
            self.assertEqual(statuses[skill_id]["status"], "healthy")

        rows = [
            {"branch_name": "上海分行", "loan_amount": 100.0},
            {"branch_name": "南京分行", "loan_amount": 80.0},
        ]
        profile = self.services.skill_executor.execute(
            SkillRequest(
                "data.analysis.profile",
                self.context,
                {"data": rows, "metrics": ["loan_amount"], "dimensions": ["branch_name"]},
            )
        ).output["analysis_profile"]
        governance = self.services.skill_executor.execute(
            SkillRequest(
                "data.governance.assess",
                self.context,
                {
                    "data": rows,
                    "dataset_id": "loan_operation_mart",
                    "semantic_info": {"execution_mode": "real", "publishable": True},
                },
            )
        ).output["governance_assessment"]
        conclusions = self.services.skill_executor.execute(
            SkillRequest(
                "conclusion.generate",
                self.context,
                {
                    "question": "分析机构放款",
                    "analysis_plan": {
                        "dataset_id": "loan_operation_mart",
                        "metrics": ["loan_amount"],
                        "dimensions": ["branch_name"],
                    },
                    "analysis_profile": profile,
                    "governance_assessment": governance,
                    "learned_guidance": [],
                },
            )
        ).output
        report = self.services.skill_executor.execute(
            SkillRequest(
                "bi.report.generate",
                self.context,
                {
                    "question": "分析机构放款",
                    "analysis_plan": {
                        "dataset_id": "loan_operation_mart",
                        "metrics": ["loan_amount"],
                        "dimensions": ["branch_name"],
                    },
                    "analysis_profile": profile,
                    "governance_assessment": governance,
                    "chart_spec": {"type": "column"},
                    "conclusions": conclusions["conclusions"],
                },
            )
        ).output["report_spec"]

        self.assertEqual(profile["metrics"]["loan_amount"]["sum"], 180.0)
        self.assertEqual(governance["quality_score"], 1.0)
        self.assertEqual(conclusions["conclusion_contract"]["primary_metric"], "loan_amount")
        self.assertFalse(report["published"])
        self.assertEqual(report["evidence"]["profile_hash"], profile["profile_hash"])

    def test_repeated_operation_creates_review_candidate_then_applies_after_review(self) -> None:
        candidate_id = ""
        memory_candidate_id = ""
        for index in range(3):
            event = self.services.audit_store.write(
                "tenant_demo",
                "u_super_admin",
                "application.select_bank",
                "application_module",
                "dashboard",
                {"selection": {"selectedBank": "上海分行"}, "sequence": index},
                "",
            )
            result = self.services.learning_service.observe_operation(event)
            candidate_id = str(result.get("candidate_id") or candidate_id)
            memory_candidate_id = str(
                result.get("memory_candidate_id") or memory_candidate_id
            )

        self.assertEqual(candidate_id, "scene-weekly-report")
        self.assertTrue(memory_candidate_id.startswith("learned-memory-"))
        candidate = self.services.data_asset_store.get_item(
            "tenant_demo", "analysis_skill", candidate_id
        )
        self.assertEqual(candidate["lifecycleStatus"], "review")
        self.assertTrue(candidate["memoryRefs"])
        self.assertEqual(candidate["name"], "周报分析")
        self.assertEqual(candidate["learningEvolution"]["strategy"], "reuse_patch")
        self.assertTrue(candidate["learningGuardrails"]["fourEyes"])
        self.assertNotIn("targetId", candidate["learningTrigger"])
        self.assertTrue(candidate["learningTrigger"]["targetFingerprint"])
        memory_candidate = self.services.memory_store.get(
            "tenant_demo", memory_candidate_id
        )
        self.assertEqual(memory_candidate["status"], "candidate")
        self.assertEqual(memory_candidate["memory_type"], "behavior_habit")
        serialized_memory = json.dumps(memory_candidate["content"], ensure_ascii=False)
        self.assertNotIn("上海分行", serialized_memory)
        self.assertNotIn("selectedBank", serialized_memory)

        active = self.services.data_asset_store.review_item(
            "tenant_demo",
            "analysis_skill",
            candidate_id,
            decision="approved",
            reviewer_user_id="u_reviewer",
            expected_version=candidate["assetVersion"],
        )
        self.assertEqual(active["lifecycleStatus"], "active")
        active_memory = self.services.memory_service.review_candidate(
            "tenant_demo",
            memory_candidate_id,
            "approve",
            "u_reviewer",
        )
        self.assertEqual(active_memory["status"], "active")

        next_event = self.services.audit_store.write(
            "tenant_demo",
            "u_super_admin",
            "application.select_bank",
            "application_module",
            "dashboard",
            {"selection": {"selectedBank": "上海分行"}},
            "",
        )
        applied = self.services.learning_service.observe_operation(next_event)
        self.assertEqual(applied["applied_skill_ids"], [candidate_id])
        self.assertEqual(applied["applied_memory_ids"], [memory_candidate_id])
        learning_events = self.services.audit_store.list("tenant_demo", limit=20)
        self.assertTrue(
            any(
                event["action"] == "learning.skill.applied"
                and event["target_id"] == candidate_id
                for event in learning_events
            )
        )
        self.assertTrue(
            any(
                event["action"] == "learning.memory.applied"
                and event["target_id"] == memory_candidate_id
                for event in learning_events
            )
        )
        learning_summary = self.services.learning_service.summary(
            "tenant_demo", "u_super_admin"
        )
        self.assertEqual(learning_summary["counts"]["memory_active"], 1)
        self.assertEqual(
            learning_summary["generated_memories"][0]["memory_id"],
            memory_candidate_id,
        )

    def test_http_page_actions_feed_the_governed_learning_loop(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                for _ in range(3):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", port, timeout=5
                    )
                    connection.request(
                        "POST",
                        "/api/application/action",
                        body=json.dumps(
                            {
                                "module_key": "dashboard",
                                "action": "select_bank",
                                "payload": {"selectedBank": "上海分行"},
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "X-User-Id": "u_super_admin",
                            "X-Tenant-Id": "tenant_demo",
                        },
                    )
                    response = connection.getresponse()
                    response.read()
                    connection.close()
                    self.assertEqual(response.status, 200)

                evolved_scenes = [
                    skill
                    for skill in server.services.data_asset_store.list_bundle(
                        "tenant_demo"
                    )["analysis_skills"]
                    if (skill.get("learningEvolution") or {}).get("kind")
                    == "operation_workflow"
                ]
                generated_memories = [
                    memory
                    for memory in server.services.memory_service.list_candidates(
                        "tenant_demo"
                    )
                    if (memory.get("content") or {}).get("learning_origin")
                    == "smart_data_agent.hermes_learning"
                ]
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(len(evolved_scenes), 1)
        self.assertEqual(evolved_scenes[0]["lifecycleStatus"], "review")
        self.assertEqual(len(generated_memories), 1)
        self.assertEqual(generated_memories[0]["status"], "candidate")
        serialized = json.dumps(generated_memories[0]["content"], ensure_ascii=False)
        self.assertNotIn("上海分行", serialized)

    def test_successful_analysis_trajectory_generates_skill_and_next_request_loads_it(self) -> None:
        plan = {
            "intent_rule_id": "branch_rank",
            "dataset_id": "loan_operation_mart",
            "metrics": ["loan_amount", "drawdown_rate"],
            "dimensions": ["branch_name", "product_line"],
            "chart_types": ["column", "table"],
        }
        candidate_id = ""
        for index in range(2):
            task = SimpleNamespace(
                task_id=f"task_{index}",
                execution_id=f"exec_{index}",
                analysis_plan=dict(plan),
                review={"status": "passed", "publication_gate": "allowed", "checks": {}},
            )
            result = self.services.learning_service.observe_analysis_result(self.context, task)
            candidate_id = str(result.get("candidate_id") or candidate_id)

        self.assertEqual(candidate_id, "scene-weekly-report")
        candidate = self.services.data_asset_store.get_item(
            "tenant_demo", "analysis_skill", candidate_id
        )
        self.assertEqual(candidate["lifecycleStatus"], "review")
        self.assertEqual(candidate["learningTrigger"]["datasetId"], "loan_operation_mart")
        self.assertTrue(candidate["memoryRefs"])
        self.assertEqual(candidate["name"], "周报分析")
        self.assertEqual(candidate["learningEvolution"]["strategy"], "reuse_patch")

        self.services.data_asset_store.review_item(
            "tenant_demo",
            "analysis_skill",
            candidate_id,
            decision="approved",
            reviewer_user_id="u_reviewer",
            expected_version=candidate["assetVersion"],
        )
        matched = self.services.learning_service.resolve_analysis_skills(
            self.context,
            "再次分析机构放款",
            plan,
        )
        self.assertEqual([item["skill_id"] for item in matched], [candidate_id])
        self.assertIn("经营判断", matched[0]["viewpointStrategy"])

    def test_reviewed_scene_patch_applies_on_the_next_matching_request(self) -> None:
        plan = {
            "intent_rule_id": "branch_rank",
            "dataset_id": "loan_operation_mart",
            "metrics": ["loan_amount"],
            "dimensions": ["branch_name"],
            "chart_types": ["column"],
        }
        for index in range(2):
            self.services.learning_service.observe_analysis_result(
                self.context,
                SimpleNamespace(
                    task_id=f"workflow_{index}",
                    execution_id=f"workflow_exec_{index}",
                    analysis_plan=dict(plan),
                    review={"status": "passed", "publication_gate": "allowed", "checks": {}},
                ),
            )
        candidate = self.services.data_asset_store.get_item(
            "tenant_demo", "analysis_skill", "scene-weekly-report"
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["lifecycleStatus"], "review")
        self.services.data_asset_store.review_item(
            "tenant_demo",
            "analysis_skill",
            candidate["id"],
            decision="approved",
            reviewer_user_id="u_reviewer",
            expected_version=candidate["assetVersion"],
        )

        matched = self.services.learning_service.resolve_analysis_skills(
            self.context,
            "再次分析机构放款",
            plan,
        )
        self.assertEqual([item["skill_id"] for item in matched], [candidate["id"]])
        self.assertEqual(matched[0]["analysisAngles"][0], "先核对指标和时间口径")

    def test_failed_application_proposes_reviewed_improvement_without_replacing_active_version(self) -> None:
        plan = {
            "intent_rule_id": "risk_diagnostic",
            "dataset_id": "risk_operation_mart",
            "metrics": ["m1_overdue_rate"],
            "dimensions": ["product_line"],
            "chart_types": ["line"],
        }
        candidate_id = ""
        for index in range(2):
            result = self.services.learning_service.observe_analysis_result(
                self.context,
                SimpleNamespace(
                    task_id=f"risk_{index}",
                    execution_id=f"risk_exec_{index}",
                    analysis_plan=dict(plan),
                    review={"status": "passed", "publication_gate": "allowed", "checks": {}},
                ),
            )
            candidate_id = str(result.get("candidate_id") or candidate_id)
        candidate = self.services.data_asset_store.get_item(
            "tenant_demo", "analysis_skill", candidate_id
        )
        active = self.services.data_asset_store.review_item(
            "tenant_demo",
            "analysis_skill",
            candidate_id,
            decision="approved",
            reviewer_user_id="u_reviewer",
            expected_version=candidate["assetVersion"],
        )

        failed_plan = {
            **plan,
            "applied_learning_skills": [{"skill_id": candidate_id}],
        }
        result = self.services.learning_service.observe_analysis_result(
            self.context,
            SimpleNamespace(
                task_id="risk_failed",
                execution_id="risk_failed_exec",
                analysis_plan=failed_plan,
                review={
                    "status": "review_required",
                    "publication_gate": "blocked",
                    "checks": {"evidence_bound": False},
                },
            ),
        )
        self.assertEqual(result["improvement_ids"], [candidate_id])
        proposed = self.services.data_asset_store.get_item(
            "tenant_demo", "analysis_skill", candidate_id
        )
        self.assertEqual(proposed["lifecycleStatus"], "review")
        self.assertEqual(proposed["learningEvolution"]["parentVersion"], active["assetVersion"])
        published = self.services.data_asset_store.list_published_bundle("tenant_demo")
        still_active = next(skill for skill in published["analysis_skills"] if skill["id"] == candidate_id)
        self.assertEqual(still_active["assetVersion"], active["assetVersion"])


if __name__ == "__main__":
    unittest.main()
