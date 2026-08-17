from __future__ import annotations

import unittest

from backend.platform.bootstrap import build_local_platform
from backend.platform.governance import approval_input_hash
from backend.platform.mcp import MCPToolCall
from backend.platform.skills import SkillRequest
from backend.platform.tenancy import ExecutionContext
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class AgentSkillMCPGovernanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()
        attach_governed_test_warehouse(self.services)

    def tearDown(self) -> None:
        self.services.close()

    def test_configured_skills_are_not_misreported_as_implemented(self) -> None:
        statuses = {item["skill_id"]: item for item in self.services.skill_registry.list_runtime_statuses()}
        self.assertEqual(statuses["supersonic.query"]["status"], "healthy")
        self.assertEqual(statuses["model.train"]["status"], "configured_unimplemented")
        with self.assertRaisesRegex(RuntimeError, "skill_unavailable:model.train"):
            self.services.skill_executor.execute(
                SkillRequest(
                    skill_id="model.train",
                    context=ExecutionContext("u_super_admin", "tenant_demo"),
                    inputs={},
                    agent_id="training_validation",
                    approval_id="approval-not-enough-without-handler",
                )
            )

    def test_agent_runtime_enforces_allowed_skill_and_ordered_stage_gates(self) -> None:
        runtime = self.services.agent_runtime
        with self.assertRaisesRegex(PermissionError, "agent_skill_not_allowed"):
            runtime.require_operation("review", "supersonic.query")
        run = runtime.begin_group("analysis_execution")
        with self.assertRaisesRegex(RuntimeError, "agent_gate_out_of_order"):
            runtime.complete_gate(run, "permission_enforced", True)
        runtime.complete_gate(run, "plan_compiled", True)
        runtime.complete_gate(run, "permission_enforced", True)
        runtime.complete_gate(run, "evidence_bound", True)
        runtime.complete_gate(run, "final_review_passed", True)
        self.assertEqual(runtime.snapshot(run)["status"], "completed")

    def test_mcp_requires_declared_agent_and_uses_semantic_permission_path(self) -> None:
        context = ExecutionContext("u_super_admin", "tenant_demo")
        with self.assertRaisesRegex(PermissionError, "mcp_agent_identity_required"):
            self.services.mcp_gateway.call(
                MCPToolCall("database", "query", context, {"dataset_id": "loan_operation_mart"})
            )
        with self.assertRaisesRegex(PermissionError, "mcp_agent_not_allowed"):
            self.services.mcp_gateway.call(
                MCPToolCall(
                    "database",
                    "query",
                    context,
                    {"dataset_id": "loan_operation_mart"},
                    agent_id="review",
                )
            )
        arguments = {
            "dataset_id": "loan_operation_mart",
            "metrics": ["loan_amount", "drawdown_rate"],
            "dimensions": ["branch_name", "product_line"],
            "filters": {"month": {"eq": "2026-06"}},
        }
        approval = self.services.approval_store.request(
            "tenant_demo",
            "mcp",
            "database.query",
            "execute",
            approval_input_hash(arguments),
            "u_super_admin",
        )
        self.services.approval_store.review(
            "tenant_demo", approval["approval_id"], "u_reviewer", "approved"
        )
        result = self.services.mcp_gateway.call(
            MCPToolCall(
                "database",
                "query",
                context,
                arguments,
                agent_id="data_query",
                approval_id=approval["approval_id"],
            )
        )
        self.assertTrue(result.output["semantic_info"]["policy_enforced_at_source"])
        self.assertEqual(result.output["semantic_info"]["schema_mapping"]["metrics"], ["loan_amount", "drawdown_rate"])
        self.assertNotIn("password", result.output)


if __name__ == "__main__":
    unittest.main()
