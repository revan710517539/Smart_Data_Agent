from __future__ import annotations

import unittest

from backend.platform.bootstrap import build_local_platform
from backend.platform.kernel.isolation import merge_pack_entries
from backend.platform.kernel.models import Capability
from backend.platform.kernel.promotion import promote_common_capabilities
from backend.platform.tenancy import ExecutionContext


class UnifiedRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()

    def tearDown(self) -> None:
        self.services.close()

    def test_kernel_is_bound_on_local_platform(self) -> None:
        kernel = self.services.runtime_kernel
        self.assertIsNotNone(kernel)
        self.assertTrue(any(name.startswith("learning.") or name == "capability.promote" for name in self.services.automation_runtime.list_handlers()))

    def test_account_capabilities_are_isolated(self) -> None:
        kernel = self.services.runtime_kernel
        alice = Capability(
            capability_id="proc.weekly_defaults",
            kind="procedure",
            runtime_type="procedure",
            tenant_id="tenant_demo",
            owner_scope="user",
            owner_id="u_alice",
            title="Alice weekly defaults",
            status="active",
            trigger={"dataset_id": "loan_operation_mart", "terms": ["周报"]},
            body={"steps": ["select_sandbox", "profile"]},
        )
        bob = Capability(
            capability_id="proc.weekly_defaults",
            kind="procedure",
            runtime_type="procedure",
            tenant_id="tenant_demo",
            owner_scope="user",
            owner_id="u_bob",
            title="Bob weekly defaults",
            status="active",
            trigger={"dataset_id": "risk_operation_mart"},
            body={"steps": ["select_risk"]},
        )
        kernel.store.upsert("u_alice", alice)
        kernel.store.upsert("u_bob", bob)
        with self.assertRaisesRegex(PermissionError, "capability_account_isolation"):
            kernel.store.upsert("u_bob", alice)
        alice_visible = kernel.store.list_visible("tenant_demo", "u_alice")
        bob_visible = kernel.store.list_visible("tenant_demo", "u_bob")
        self.assertEqual({item.owner_id for item in alice_visible if item.owner_scope == "user"}, {"u_alice"})
        self.assertEqual({item.owner_id for item in bob_visible if item.owner_scope == "user"}, {"u_bob"})
        self.assertNotEqual(alice_visible[0].trigger.get("dataset_id"), bob_visible[0].trigger.get("dataset_id"))

    def test_user_pack_overrides_tenant_procedure(self) -> None:
        merged = merge_pack_entries(
            [
                {"capability_id": "proc.weekly_defaults", "owner_scope": "tenant", "title": "shared"},
                {"capability_id": "proc.weekly_defaults", "owner_scope": "user", "title": "mine"},
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "mine")

    def test_shared_capability_scopes_require_exact_membership(self) -> None:
        kernel = self.services.runtime_kernel
        for scope, owner_id in (
            ("role", "role:analyst"),
            ("org", "org:branch-a"),
            ("tenant", "tenant_demo"),
            ("platform", "platform"),
        ):
            kernel.store.upsert(
                "u_super_admin",
                Capability(
                    capability_id=f"proc.scope.{scope}",
                    kind="procedure",
                    runtime_type="procedure",
                    tenant_id="tenant_demo",
                    owner_scope=scope,
                    owner_id=owner_id,
                    status="active",
                ),
            )
        default_ids = {item.capability_id for item in kernel.store.list_visible("tenant_demo", "u_alice")}
        self.assertNotIn("proc.scope.role", default_ids)
        self.assertNotIn("proc.scope.org", default_ids)
        self.assertIn("proc.scope.tenant", default_ids)
        self.assertIn("proc.scope.platform", default_ids)
        scoped_ids = {
            item.capability_id
            for item in kernel.store.list_visible(
                "tenant_demo",
                "u_alice",
                role_ids=("role:analyst",),
                org_ids=("org:branch-a",),
            )
        }
        self.assertIn("proc.scope.role", scoped_ids)
        self.assertIn("proc.scope.org", scoped_ids)

    def test_bind_request_compiles_pack_and_route(self) -> None:
        kernel = self.services.runtime_kernel
        context = ExecutionContext("u_super_admin", "tenant_demo", page_context={"question": "放款金额"})
        pack = kernel.bind_request(context)
        self.assertTrue(pack.snapshot_id.startswith("pack_"))
        self.assertGreater(len(pack.entries), 0)
        self.assertEqual(context.page_context["pack_snapshot_id"], pack.snapshot_id)
        self.assertIn("runtime_route", context.page_context)
        self.assertTrue(any(item["capability_id"] == "supersonic.query" for item in pack.entries))
        self.assertEqual(self.services.skill_registry.runtime_status("knowledge.search")["status"], "healthy")
        persisted = kernel.store.get_pack("tenant_demo", "u_super_admin", pack.snapshot_id)
        self.assertEqual(persisted["content_hash"][:24], pack.snapshot_id.removeprefix("pack_"))
        self.assertEqual(persisted["entry_count"], len(pack.entries))
        with self.assertRaisesRegex(PermissionError, "capability_pack_account_isolation"):
            kernel.store.get_pack("tenant_demo", "u_other", pack.snapshot_id)

    def test_executor_rejects_draft_provider_on_analysis_path(self) -> None:
        kernel = self.services.runtime_kernel
        context = ExecutionContext("u_super_admin", "tenant_demo")
        pack = kernel.loader.compile(context)
        from backend.platform.kernel.models import CapabilityPack

        poisoned = CapabilityPack(
            snapshot_id=pack.snapshot_id,
            tenant_id=pack.tenant_id,
            user_id=pack.user_id,
            compiled_at=pack.compiled_at,
            entries=pack.entries
            + (
                {
                    "capability_id": "hermes.draft",
                    "kind": "draft",
                    "runtime_type": "draft_provider",
                    "owner_scope": "user",
                    "owner_id": context.user_id,
                    "status": "active",
                    "trigger": {},
                },
            ),
        )
        with self.assertRaisesRegex(PermissionError, "draft_provider_forbidden"):
            kernel.executor.execute(context, "hermes.draft", {}, pack=poisoned)

    def test_event_bus_isolates_listener_failures(self) -> None:
        kernel = self.services.runtime_kernel
        seen: list[str] = []

        def boom(_event: str, _payload: dict) -> None:
            raise RuntimeError("listener_should_not_break_publish")

        def ok(event: str, _payload: dict) -> None:
            seen.append(event)

        kernel.event_bus.subscribe("runtime.test", boom)
        kernel.event_bus.subscribe("runtime.test", ok)
        kernel.event_bus.publish("runtime.test", {"ok": True})
        self.assertEqual(seen, ["runtime.test"])

    def test_promotion_requires_k_anonymity(self) -> None:
        kernel = self.services.runtime_kernel
        trigger = {"dataset_id": "loan_operation_mart", "intent_rule_id": "default"}
        body = {"steps": ["profile", "conclude"]}
        for user_id in ("u_a", "u_b"):
            kernel.store.upsert(
                user_id,
                Capability(
                    capability_id="proc.shared_pattern",
                    kind="procedure",
                    runtime_type="procedure",
                    tenant_id="tenant_demo",
                    owner_scope="user",
                    owner_id=user_id,
                    status="active",
                    trigger=trigger,
                    body=body,
                ),
            )
        too_few = promote_common_capabilities(kernel.store, "tenant_demo", "u_super_admin", min_accounts=3)
        self.assertEqual(too_few["promoted"], [])
        kernel.store.upsert(
            "u_c",
            Capability(
                capability_id="proc.shared_pattern",
                kind="procedure",
                runtime_type="procedure",
                tenant_id="tenant_demo",
                owner_scope="user",
                owner_id="u_c",
                status="active",
                trigger=trigger,
                body=body,
            ),
        )
        promoted = kernel.promote("tenant_demo", "u_super_admin", min_accounts=3)
        self.assertTrue(promoted["promoted"])
        common = kernel.store.get("tenant_demo", "tenant", "tenant_demo", promoted["promoted"][0])
        self.assertIsNotNone(common)
        self.assertEqual(common.status, "review")
        self.assertNotIn("u_a", str(common.body))
        self.assertEqual(common.trigger.get("source_account_count"), 3)

    def test_analysis_payload_includes_runtime_fields(self) -> None:
        from backend.platform.api.routes.analysis import run_analysis
        from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse

        attach_governed_test_warehouse(self.services)
        payload = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="放款金额按机构看一看",
        )
        self.assertTrue(str(payload.get("pack_snapshot_id") or "").startswith("pack_"))
        self.assertTrue(str(payload.get("episode_id") or "").startswith("ep_"))
        self.assertIn("planning_source", payload)
        runs = self.services.automation_runtime.store.list_runs("tenant_demo")
        learning_tasks = {
            str(self.services.automation_runtime.store.get_task_by_code("tenant_demo", code)["automation_task_id"])
            for code in ("system.runtime.learning.observe", "system.runtime.learning.draft")
        }
        queued_learning = {
            str(run["automation_task_id"])
            for run in runs
            if run["status"] == "queued" and str(run["automation_task_id"]) in learning_tasks
        }
        self.assertEqual(queued_learning, learning_tasks)

    def test_default_hermes_attachment_is_off(self) -> None:
        status = self.services.runtime_kernel.hermes_status()
        self.assertEqual(status["mode"], "off")
        self.assertFalse(status["configured"])
        self.assertTrue(status["ready"])

    def test_local_distiller_writes_account_candidate_via_job(self) -> None:
        runtime = self.services.automation_runtime
        result = runtime._handlers["learning.draft"](
            "tenant_demo",
            {},
            {
                "user_id": "u_alice",
                "episode": {
                    "dataset_id": "loan_operation_mart",
                    "metrics": ["loan_amount"],
                    "dimensions": ["branch_name"],
                    "steps": ["supersonic.query"],
                },
            },
            {"actor_user_id": "u_alice"},
        )
        self.assertEqual(result["owner_id"], "u_alice")
        self.assertEqual(result["status"], "candidate")
        stored = self.services.runtime_kernel.store.get("tenant_demo", "user", "u_alice", result["capability_id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.owner_id, "u_alice")
        self.assertIsNone(self.services.runtime_kernel.store.get("tenant_demo", "user", "u_bob", result["capability_id"]))

    def test_delivery_contract_uses_account_schedule(self) -> None:
        kernel = self.services.runtime_kernel
        kernel.store.upsert(
            "u_alice",
            Capability(
                capability_id="proc.morning_sandbox",
                kind="procedure",
                runtime_type="procedure",
                tenant_id="tenant_demo",
                owner_scope="user",
                owner_id="u_alice",
                title="晨间沙盘",
                status="active",
                trigger={"dataset_id": "loan_operation_mart", "schedule": "0 9 * * 1-5", "question": "经营沙盘"},
                body={"steps": ["supersonic.query"]},
            ),
        )
        synced = kernel.sync_delivery("tenant_demo", "u_alice")
        self.assertTrue(synced["ensured"])
        task = self.services.automation_runtime.store.get_task_by_code("tenant_demo", synced["ensured"][0])
        self.assertEqual(task["handler_ref"], "delivery.fulfill")
        self.assertEqual(task["trigger_type"], "schedule")
        self.assertEqual(task["task_config"]["owner_user_id"], "u_alice")
        others = kernel.sync_delivery("tenant_demo", "u_bob")
        self.assertEqual(others["ensured"], [])

    def test_hermes_failure_falls_back_to_local_distiller(self) -> None:
        from backend.platform.kernel.draft_provider import CompositeDraftProvider, HermesDraftProvider
        from backend.platform.kernel.hermes_endpoint import HermesEndpoint

        endpoint = HermesEndpoint(
            mode="cli",
            binary="/tmp/missing-hermes",
            home="/tmp/sda-hermes-home",
            profile="default",
            endpoint="",
            timeout_seconds=5,
            extra_args=(),
        )
        provider = CompositeDraftProvider(HermesDraftProvider(endpoint))
        drafted = provider.draft({"episode": {"dataset_id": "loan_operation_mart", "metrics": ["loan_amount"]}})
        self.assertEqual(drafted["provider"], "local_distiller")
        self.assertEqual(drafted.get("fallback_from"), "hermes")


if __name__ == "__main__":
    unittest.main()
