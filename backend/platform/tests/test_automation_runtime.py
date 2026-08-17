from __future__ import annotations

import hashlib
import unittest
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.bootstrap import build_local_platform
from backend.platform.api.routes.analysis import (
    _resolve_metric_preset_source,
    _selected_table_requires_semantic_registration,
    handle_analysis_run_async,
    run_analysis,
)
from backend.platform.automation.runtime import _public_handler_failure
from backend.platform.data_access.factory import UnconfiguredDataWarehouse
from backend.platform.semantic import InMemorySupersonicClient
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class AutomationRuntimeTest(unittest.TestCase):
    def test_metric_preset_uses_only_published_metric_with_current_table_mapping(self) -> None:
        class MetricStore:
            @staticmethod
            def list(_tenant_id: str) -> list[dict]:
                return [{
                    "metricId": "metric_loan_amount",
                    "metricName": "放款金额",
                    "metricCode": "loan_amount",
                    "datasetId": "loan_operation_mart",
                    "semanticStatus": "published",
                }]

        preset = _resolve_metric_preset_source(
            MetricStore(),
            "tenant_a",
            "本月各分行放款金额",
            [{"id": "topic_loan", "datasetId": "loan_operation_mart", "metricCodes": ["loan_amount"]}],
        )

        self.assertEqual(preset["status"], "resolved")
        self.assertEqual(preset["selected_table"]["id"], "topic_loan")
        self.assertEqual(preset["metrics"][0]["metric_name"], "放款金额")

    def test_metric_preset_never_selects_unmapped_or_documentation_metric(self) -> None:
        class MetricStore:
            @staticmethod
            def list(_tenant_id: str) -> list[dict]:
                return [{
                    "metricId": "metric_loan_amount",
                    "metricName": "放款金额",
                    "metricCode": "loan_amount",
                    "datasetId": "loan_operation_mart",
                    "semanticStatus": "documentation",
                }]

        preset = _resolve_metric_preset_source(
            MetricStore(),
            "tenant_a",
            "本月各分行放款金额",
            [{"id": "other_table", "datasetId": "other_mart", "metricCodes": ["other_metric"]}],
        )

        self.assertEqual(preset["status"], "no_executable_mapping")
        self.assertNotIn("selected_table", preset)

    def test_authorized_raw_table_uses_bounded_temporary_semantics(self) -> None:
        self.assertFalse(_selected_table_requires_semantic_registration({
            "selected_data_tables": [{
                "id": "csv_current_delivery",
                "tableNameCn": "当前 CSV",
                "relativePath": "当前 CSV.csv",
                "fields": [{"fieldNameEn": "field_1", "fieldNameCn": "金额", "type": "decimal"}],
            }],
        }))
        self.assertTrue(_selected_table_requires_semantic_registration({
            "selected_data_tables": [{"id": "csv_current_delivery", "tableNameCn": "缺少来源的 CSV"}],
        }))
        self.assertFalse(_selected_table_requires_semantic_registration({
            "selected_data_tables": [{"id": "topic_loan", "datasetId": "loan_operation_mart"}],
        }))

    def setUp(self) -> None:
        self.services = build_local_platform()
        attach_governed_test_warehouse(self.services)

    def tearDown(self) -> None:
        self.services.close()

    def test_missing_production_table_has_stable_non_retryable_guidance(self) -> None:
        code, message, retryable = _public_handler_failure(ValueError("analysis_production_data_table_required"))
        self.assertEqual(code, "analysis_production_data_table_required")
        self.assertIn("点击“+”", message)
        self.assertFalse(retryable)

    def test_self_analysis_page_requires_explicit_production_table_when_semantic_source_is_unconfigured(self) -> None:
        self.services.semantic_service.client = InMemorySupersonicClient(UnconfiguredDataWarehouse())
        self.services.data_source_mode = "production_data_source_not_configured"
        with self.assertRaisesRegex(ValueError, "analysis_production_data_table_required"):
            run_analysis(
                self.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="分析当前数据",
                page_context={"route": "self-analysis/query"},
            )

    def test_manual_analysis_task_is_idempotently_queued_and_worker_persists_result(self) -> None:
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "scheduled_branch_analysis",
                "task_name": "机构经营分析",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "task_config": {"question": "2026年6月各分行放款金额排名TOP10"},
                "retry_policy": {"max_attempts": 2, "base_delay_seconds": 1},
                "timeout_seconds": 30,
            },
            "u_super_admin",
        )
        first = self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-analysis-1"
        )
        second = self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-analysis-1"
        )
        self.assertEqual(first["automation_run_id"], second["automation_run_id"])
        completed = self.services.automation_runtime.run_once("worker-test")
        self.assertIsNotNone(completed)
        assert completed is not None
        self.assertEqual(completed["status"], "succeeded")
        self.assertTrue(any(ref["type"] == "task" for ref in completed["result_refs"]))
        progress = self.services.automation_store.list_steps("tenant_demo", completed["automation_run_id"])
        progress_by_code = {step["step_code"]: step for step in progress}
        self.assertEqual(progress_by_code["context_understanding"]["status"], "succeeded")
        self.assertEqual(progress_by_code["data_query"]["status"], "succeeded")
        self.assertEqual(progress_by_code["result_finalize"]["status"], "succeeded")
        data_ref = progress_by_code["data_query"]["output_refs"][0]
        self.assertGreater(data_ref["row_count"], 0)
        self.assertTrue(data_ref["partial_task_id"].startswith("task_"))

    def test_async_analysis_reconciles_retry_policy_for_legacy_lock_version_zero(self) -> None:
        task_code = "system.analysis." + hashlib.sha256(b"u_super_admin").hexdigest()[:20]
        legacy = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": task_code,
                "task_name": "历史异步智能分析",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "retry_policy": {"max_attempts": 1},
                "timeout_seconds": 900,
                "max_concurrency": 2,
            },
            "u_super_admin",
        )
        self.assertEqual(legacy["lock_version"], 0)

        class FakeHandler:
            services = self.services
            headers = {"Idempotency-Key": "legacy-lock-version-request"}
            response = None

            def _read_json(inner_self):
                return {"question": "本月各分行放款金额排名", "page_context": {}}

            def _request_context(inner_self, payload):
                return SimpleNamespace(tenant_id="tenant_demo", user_id="u_super_admin")

            def _write_audit(inner_self, *args, **kwargs):
                return None

            def _send_json(inner_self, payload, status=200):
                inner_self.response = (payload, status)

        handler = FakeHandler()
        handle_analysis_run_async(handler)

        refreshed = self.services.automation_store.get_task("tenant_demo", legacy["automation_task_id"])
        self.assertEqual(refreshed["retry_policy"], {"max_attempts": 3, "base_delay_seconds": 2})
        self.assertEqual(refreshed["lock_version"], 1)
        self.assertEqual(handler.response[1], 202)

    def test_async_analysis_resumes_paused_system_task_before_enqueue(self) -> None:
        task_code = "system.analysis." + hashlib.sha256(b"u_super_admin").hexdigest()[:20]
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": task_code,
                "task_name": "异步智能分析",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 2},
                "timeout_seconds": 900,
                "max_concurrency": 2,
            },
            "u_super_admin",
        )
        paused = self.services.automation_runtime.update_task(
            "tenant_demo",
            task["automation_task_id"],
            {"status": "paused"},
            "u_super_admin",
            task["lock_version"],
        )

        class FakeHandler:
            services = self.services
            headers = {"Idempotency-Key": "resume-paused-analysis"}
            response = None

            def _read_json(inner_self):
                return {"question": "分析这个数据", "page_context": {}}

            def _request_context(inner_self, payload):
                return SimpleNamespace(tenant_id="tenant_demo", user_id="u_super_admin")

            def _write_audit(inner_self, *args, **kwargs):
                return None

            def _send_json(inner_self, payload, status=200, **kwargs):
                inner_self.response = (payload, status)

        handler = FakeHandler()
        handle_analysis_run_async(handler)

        refreshed = self.services.automation_store.get_task("tenant_demo", task["automation_task_id"])
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(refreshed["status"], "active")
        self.assertEqual(refreshed["lock_version"], paused["lock_version"] + 1)
        self.assertEqual(handler.response[1], 202)
        self.assertEqual(handler.response[0]["run"]["status"], "queued")

    def test_async_analysis_keeps_disabled_system_task_fail_closed(self) -> None:
        task_code = "system.analysis." + hashlib.sha256(b"u_super_admin").hexdigest()[:20]
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": task_code,
                "task_name": "异步智能分析",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 2},
                "timeout_seconds": 900,
                "max_concurrency": 2,
            },
            "u_super_admin",
        )
        disabled = self.services.automation_runtime.update_task(
            "tenant_demo",
            task["automation_task_id"],
            {"status": "disabled"},
            "u_super_admin",
            task["lock_version"],
        )

        class FakeHandler:
            services = self.services
            headers = {"Idempotency-Key": "reject-disabled-analysis"}
            response = None

            def _read_json(inner_self):
                return {"question": "分析这个数据", "page_context": {}}

            def _request_context(inner_self, payload):
                return SimpleNamespace(tenant_id="tenant_demo", user_id="u_super_admin")

            def _write_audit(inner_self, *args, **kwargs):
                return None

            def _send_json(inner_self, payload, status=200, **kwargs):
                inner_self.response = (payload, status)

        handler = FakeHandler()
        handle_analysis_run_async(handler)

        refreshed = self.services.automation_store.get_task("tenant_demo", task["automation_task_id"])
        self.assertEqual(refreshed["status"], "disabled")
        self.assertEqual(refreshed["lock_version"], disabled["lock_version"])
        self.assertEqual(handler.response[1], 400)
        self.assertEqual(handler.response[0]["error"], "analysis_automation_disabled")
        self.assertIn("管理员停用", handler.response[0]["message"])

    def test_unregistered_handler_is_rejected_and_failure_reaches_terminal_state(self) -> None:
        with self.assertRaises(ValueError):
            self.services.automation_runtime.create_task(
                "tenant_demo",
                {
                    "task_code": "unsafe_handler",
                    "task_name": "不受信任处理器",
                    "task_type": "custom",
                    "trigger_type": "manual",
                    "handler_ref": "python.eval",
                },
                "u_super_admin",
            )
        self.services.automation_runtime.register_handler(
            "test.fail",
            lambda tenant_id, config, payload, context: (_ for _ in ()).throw(RuntimeError("secret provider detail")),
        )
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "known_failure",
                "task_name": "已注册失败任务",
                "task_type": "custom",
                "trigger_type": "manual",
                "handler_ref": "test.fail",
                "retry_policy": {"max_attempts": 1},
            },
            "u_super_admin",
        )
        self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-failure"
        )
        failed = self.services.automation_runtime.run_once("worker-test")
        assert failed is not None
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "automation_handler_failed")
        self.assertNotIn("secret provider detail", failed["error_summary"])

    def test_analysis_query_permission_failure_is_actionable_without_leaking_exception(self) -> None:
        self.services.automation_runtime.register_handler(
            "test.permission",
            lambda tenant_id, config, payload, context: (_ for _ in ()).throw(
                PermissionError("Permission denied: skill:supersonic.query:execute")
            ),
        )
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "permission_failure",
                "task_name": "权限失败任务",
                "task_type": "custom",
                "trigger_type": "manual",
                "handler_ref": "test.permission",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 1},
            },
            "u_super_admin",
        )
        self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-permission-failure"
        )

        failed = self.services.automation_runtime.run_once("worker-test")

        assert failed is not None
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempt_no"], 1)
        self.assertEqual(failed["error_code"], "analysis_query_permission_denied")
        self.assertIn("执行智能分析", failed["error_summary"])
        self.assertNotIn("supersonic.query", failed["error_summary"])

    def test_stale_selected_data_asset_is_not_reported_as_a_role_permission_failure(self) -> None:
        self.services.automation_runtime.register_handler(
            "test.stale_asset",
            lambda tenant_id, config, payload, context: (_ for _ in ()).throw(
                PermissionError("selected_data_asset_not_published_or_not_authorized")
            ),
        )
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "stale_selected_data_asset",
                "task_name": "已更新数据表分析",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "test.stale_asset",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 1},
            },
            "u_super_admin",
        )
        self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-stale-selected-data-asset"
        )

        failed = self.services.automation_runtime.run_once("worker-test")

        assert failed is not None
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "analysis_selected_data_asset_unavailable")
        self.assertIn("重新选择数据表", failed["error_summary"])
        self.assertNotIn("权限", failed["error_summary"])

    def test_stale_model_selection_is_not_reported_as_a_role_permission_failure(self) -> None:
        self.services.automation_runtime.register_handler(
            "test.stale_model",
            lambda tenant_id, config, payload, context: (_ for _ in ()).throw(
                PermissionError("selected_submodel_not_enabled_for_application_module")
            ),
        )
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "stale_model_selection",
                "task_name": "已更新模型分析",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "test.stale_model",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 1},
            },
            "u_super_admin",
        )
        self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-stale-model-selection"
        )

        failed = self.services.automation_runtime.run_once("worker-test")

        assert failed is not None
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "analysis_selected_model_unavailable")
        self.assertIn("默认模型", failed["error_summary"])
        self.assertNotIn("权限", failed["error_summary"])

    def test_transient_handler_failure_is_retried_and_then_succeeds(self) -> None:
        attempts: list[int] = []

        def transient_handler(tenant_id, config, payload, context):
            attempts.append(int(context["attempt_no"]))
            if context["attempt_no"] == 1:
                raise ConnectionError("provider connection reset with private detail")
            return {"task_id": "recovered_task"}

        self.services.automation_runtime.register_handler("test.transient", transient_handler)
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "transient_failure",
                "task_name": "瞬时失败恢复任务",
                "task_type": "custom",
                "trigger_type": "manual",
                "handler_ref": "test.transient",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 1},
            },
            "u_super_admin",
        )
        run = self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-transient"
        )
        waiting = self.services.automation_runtime.run_once("worker-test")
        assert waiting is not None
        self.assertEqual(waiting["status"], "retry_wait")
        self.assertEqual(waiting["error_code"], "automation_transient_failure")
        self.assertNotIn("private detail", waiting["error_summary"])
        with self.services.automation_store._conn:
            self.services.automation_store._conn.execute(
                "UPDATE platform_automation_task_runs SET next_retry_at = '2000-01-01T00:00:00+00:00' WHERE automation_run_id = ?",
                (run["automation_run_id"],),
            )
        recovered = self.services.automation_runtime.run_once("worker-test")
        assert recovered is not None
        self.assertEqual(recovered["status"], "succeeded")
        self.assertEqual(recovered["attempt_no"], 2)
        self.assertEqual(attempts, [1, 2])

    def test_analysis_retry_uses_a_new_request_id_after_a_persisted_failed_attempt(self) -> None:
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "analysis_retry_idempotency",
                "task_name": "分析重试幂等任务",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "retry_policy": {"max_attempts": 3, "base_delay_seconds": 1},
            },
            "u_super_admin",
        )
        run = self.services.automation_runtime.trigger(
            "tenant_demo",
            task["automation_task_id"],
            "u_super_admin",
            "idem-analysis-retry",
            {"question": "2026年7月各分行放款金额排名", "request_id": "analysis-retry-request"},
        )
        original_run = self.services.workflow.run
        workflow_attempts = 0

        def flaky_workflow(*args, **kwargs):
            nonlocal workflow_attempts
            workflow_attempts += 1
            if workflow_attempts == 1:
                raise RuntimeError("semantic dependency reset")
            return original_run(*args, **kwargs)

        with patch.object(self.services.workflow, "run", side_effect=flaky_workflow):
            waiting = self.services.automation_runtime.run_once("worker-test")
            assert waiting is not None
            self.assertEqual(waiting["status"], "retry_wait")
            failed_task = self.services.task_repository.get_task_by_request(
                "tenant_demo", "analysis-retry-request"
            )
            assert failed_task is not None
            self.assertEqual(failed_task["status"], "failed")
            with self.services.automation_store._conn:
                self.services.automation_store._conn.execute(
                    "UPDATE platform_automation_task_runs SET next_retry_at = '2000-01-01T00:00:00+00:00' WHERE automation_run_id = ?",
                    (run["automation_run_id"],),
                )
            recovered = self.services.automation_runtime.run_once("worker-test")

        assert recovered is not None
        self.assertEqual(recovered["status"], "succeeded")
        recovered_task = self.services.task_repository.get_task_by_request(
            "tenant_demo", "analysis-retry-request:attempt:2"
        )
        assert recovered_task is not None
        self.assertEqual(recovered_task["status"], "completed")
        self.assertNotEqual(recovered_task["task_id"], failed_task["task_id"])

    def test_scheduled_task_due_time_is_advanced_and_not_duplicated(self) -> None:
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "hourly_analysis",
                "task_name": "每小时分析",
                "task_type": "analysis",
                "trigger_type": "schedule",
                "schedule_expression": "0 * * * *",
                "handler_ref": "analysis.run",
                "task_config": {"question": "放款金额是多少"},
            },
            "u_super_admin",
        )
        with self.services.automation_store._conn:
            self.services.automation_store._conn.execute(
                "UPDATE platform_automation_tasks SET next_run_at = '2026-01-01T00:00:00+00:00' WHERE tenant_id = ? AND automation_task_id = ?",
                ("tenant_demo", task["automation_task_id"]),
            )
        first = self.services.automation_store.enqueue_due_tasks("2026-01-01T00:00:01+00:00")
        second = self.services.automation_store.enqueue_due_tasks("2026-01-01T00:00:01+00:00")
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        refreshed = self.services.automation_store.get_task("tenant_demo", task["automation_task_id"])
        self.assertGreater(refreshed["next_run_at"], "2026-01-01T00:00:01+00:00")

    def test_outbox_expands_to_encrypted_in_app_subscription_and_delivers_once(self) -> None:
        subscription = self.services.automation_store.create_subscription(
            "tenant_demo",
            {
                "subscription_name": "任务成功提醒",
                "event_types": ["automation.run.succeeded"],
                "channel_type": "in_app",
                "channel_config": {"private_setting": "must_not_be_returned"},
            },
            "u_super_admin",
        )
        self.assertEqual(subscription["channel_config"], {"configured": True})
        raw = self.services.automation_store._conn.execute(
            "SELECT channel_config_secret FROM platform_subscriptions WHERE tenant_id = ? AND subscription_id = ?",
            ("tenant_demo", subscription["subscription_id"]),
        ).fetchone()[0]
        self.assertNotIn("must_not_be_returned", raw)

        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "notify_success",
                "task_name": "成功通知任务",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "task_config": {"question": "2026年6月放款金额是多少"},
            },
            "u_super_admin",
        )
        self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-notify"
        )
        self.services.automation_runtime.run_once("worker-test")
        self.services.automation_runtime.process_notifications_once()
        self.services.automation_runtime.process_notifications_once()
        deliveries = self.services.automation_store.list_in_app_deliveries("tenant_demo", "u_super_admin")
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["status"], "delivered")
        self.assertEqual(deliveries[0]["event_type"], "automation.run.succeeded")

    def test_webhook_subscription_requires_https(self) -> None:
        with self.assertRaises(ValueError):
            self.services.automation_store.create_subscription(
                "tenant_demo",
                {
                    "subscription_name": "不安全Webhook",
                    "event_types": ["automation.run.failed"],
                    "channel_type": "webhook",
                    "channel_config": {"url": "http://127.0.0.1/hook"},
                },
                "u_super_admin",
            )

    def test_subscription_is_server_owned_versioned_and_soft_disabled(self) -> None:
        created = self.services.automation_store.create_subscription(
            "tenant_demo",
            {
                "subscription_id": "client_spoofed_id",
                "subscription_name": "经营提醒",
                "event_types": ["automation.run.failed"],
                "channel_type": "in_app",
                "channel_config": {},
            },
            "u_super_admin",
        )
        self.assertNotEqual(created["subscription_id"], "client_spoofed_id")
        self.assertEqual(created["owner_user_id"], "u_super_admin")
        self.assertEqual(created["lock_version"], 1)
        with self.assertRaises(PermissionError):
            self.services.automation_store.update_subscription(
                "tenant_demo", created["subscription_id"], {"status": "paused"}, "u_operator", 1
            )
        updated = self.services.automation_store.update_subscription(
            "tenant_demo",
            created["subscription_id"],
            {"subscription_name": "经营失败提醒", "status": "paused"},
            "u_super_admin",
            1,
        )
        self.assertEqual(updated["status"], "paused")
        self.assertEqual(updated["lock_version"], 2)
        with self.assertRaisesRegex(ValueError, "revision_conflict"):
            self.services.automation_store.update_subscription(
                "tenant_demo", created["subscription_id"], {"status": "active"}, "u_super_admin", 1
            )
        disabled = self.services.automation_store.disable_subscription(
            "tenant_demo", created["subscription_id"], "u_super_admin", 2
        )
        self.assertEqual(disabled["status"], "disabled")
        self.assertEqual(disabled["lock_version"], 3)
        self.assertEqual(self.services.automation_store.list_subscriptions("tenant_demo", "u_super_admin"), [])

    def test_provider_callback_is_idempotent_and_updates_delivery_receipt(self) -> None:
        subscription = self.services.automation_store.create_subscription(
            "tenant_demo",
            {
                "subscription_name": "邮件回执",
                "event_types": ["report.daily.queued"],
                "channel_type": "email",
                "channel_config": {"recipient": "owner@example.com"},
            },
            "u_super_admin",
        )
        now = "2026-07-10T00:00:00+00:00"
        with self.services.automation_store._conn:
            self.services.automation_store._conn.execute(
                """
                INSERT INTO platform_outbox_events(
                    tenant_id, outbox_event_id, aggregate_type, aggregate_id,
                    event_type, payload, status, available_at, created_at, updated_at
                ) VALUES ('tenant_demo', 'oe_callback', 'report', 'report_1',
                          'report.daily.queued', '{}', 'published', ?, ?, ?)
                """,
                (now, now, now),
            )
            self.services.automation_store._conn.execute(
                """
                INSERT INTO platform_notification_deliveries(
                    tenant_id, delivery_id, subscription_id, outbox_event_id,
                    channel_type, status, idempotency_key, provider_message_id,
                    created_at, updated_at
                ) VALUES ('tenant_demo', 'delivery_callback', ?, 'oe_callback',
                          'email', 'sending', 'callback-idempotency', 'provider-message-1', ?, ?)
                """,
                (subscription["subscription_id"], now, now),
            )
        first = self.services.automation_store.record_provider_callback(
            "tenant_demo",
            provider="smtp-provider",
            provider_event_id="provider-event-1",
            provider_message_id="provider-message-1",
            event_type="delivered",
            payload_hash="a" * 64,
            safe_payload={"occurred_at": now},
        )
        replay = self.services.automation_store.record_provider_callback(
            "tenant_demo",
            provider="smtp-provider",
            provider_event_id="provider-event-1",
            provider_message_id="provider-message-1",
            event_type="delivered",
            payload_hash="a" * 64,
            safe_payload={"occurred_at": now},
        )
        self.assertEqual(first["callback_id"], replay["callback_id"])
        delivery = self.services.automation_store._conn.execute(
            "SELECT status, delivered_at FROM platform_notification_deliveries WHERE delivery_id = 'delivery_callback'"
        ).fetchone()
        self.assertEqual(delivery["status"], "delivered")
        self.assertTrue(delivery["delivered_at"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.services.automation_store.record_provider_callback(
                "tenant_demo",
                provider="smtp-provider",
                provider_event_id="provider-event-1",
                provider_message_id="provider-message-1",
                event_type="delivered",
                payload_hash="b" * 64,
                safe_payload={},
            )

    def test_owner_can_cancel_queued_run_and_terminal_state_cannot_be_overwritten(self) -> None:
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "cancel_queued",
                "task_name": "可取消任务",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "task_config": {"question": "放款金额是多少"},
            },
            "u_super_admin",
        )
        run = self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-cancel-queued"
        )
        with self.assertRaises(PermissionError):
            self.services.automation_store.cancel_run("tenant_demo", run["automation_run_id"], "u_operator")
        cancelled = self.services.automation_store.cancel_run("tenant_demo", run["automation_run_id"], "u_super_admin")
        self.assertEqual(cancelled["status"], "cancelled")
        still_cancelled = self.services.automation_store.finish_run(
            "tenant_demo", run["automation_run_id"], status="succeeded", result_refs=[{"type": "fake", "id": "x"}]
        )
        self.assertEqual(still_cancelled["status"], "cancelled")
        self.assertEqual(still_cancelled["result_refs"], [])

    def test_running_handler_observes_cooperative_cancellation(self) -> None:
        entered = Event()

        def cancellable_handler(tenant_id, config, payload, context):
            entered.set()
            while not context["is_cancelled"]():
                entered.wait(0.01)
            return {"task_id": "must_not_publish"}

        self.services.automation_runtime.register_handler("test.cancellable", cancellable_handler)
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "cancel_running",
                "task_name": "运行中取消任务",
                "task_type": "custom",
                "trigger_type": "manual",
                "handler_ref": "test.cancellable",
                "retry_policy": {"max_attempts": 1},
            },
            "u_super_admin",
        )
        run = self.services.automation_runtime.trigger(
            "tenant_demo", task["automation_task_id"], "u_super_admin", "idem-cancel-running"
        )
        result_holder = []
        worker = Thread(target=lambda: result_holder.append(self.services.automation_runtime.run_once("cancel-worker")))
        worker.start()
        self.assertTrue(entered.wait(2))
        self.services.automation_store.cancel_run("tenant_demo", run["automation_run_id"], "u_super_admin")
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result_holder[0]["status"], "cancelled")
        self.assertEqual(result_holder[0]["result_refs"], [])

    def test_system_task_can_be_resolved_by_stable_code(self) -> None:
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "stable.code",
                "task_name": "稳定任务",
                "task_type": "custom",
                "trigger_type": "manual",
                "handler_ref": "market.evaluate",
            },
            "u_super_admin",
        )
        found = self.services.automation_store.get_task_by_code("tenant_demo", "stable.code")
        self.assertEqual(found["automation_task_id"], task["automation_task_id"])

    def test_task_definition_update_is_owner_scoped_and_optimistically_locked(self) -> None:
        task = self.services.automation_runtime.create_task(
            "tenant_demo",
            {
                "task_code": "owned.definition",
                "task_name": "待更新任务",
                "task_type": "analysis",
                "trigger_type": "manual",
                "handler_ref": "analysis.run",
                "task_config": {"question": "放款金额是多少"},
            },
            "u_super_admin",
        )
        with self.assertRaises(PermissionError):
            self.services.automation_runtime.update_task(
                "tenant_demo", task["automation_task_id"], {"status": "paused"}, "u_operator", 0
            )
        updated = self.services.automation_runtime.update_task(
            "tenant_demo",
            task["automation_task_id"],
            {
                "task_name": "已暂停任务",
                "status": "paused",
                "task_config": {"question": "余额变化是多少"},
            },
            "u_super_admin",
            0,
        )
        self.assertEqual(updated["status"], "paused")
        self.assertEqual(updated["lock_version"], 1)
        with self.assertRaisesRegex(ValueError, "revision_conflict"):
            self.services.automation_runtime.update_task(
                "tenant_demo", task["automation_task_id"], {"status": "active"}, "u_super_admin", 0
            )

    def test_cancelled_analysis_is_persisted_as_cancelled_and_not_publishable(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "analysis_cancelled"):
            run_analysis(
                self.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="放款金额是多少",
                page_context={"request_id": "cancelled-analysis-request"},
                cancellation_check=lambda: True,
            )
        task = self.services.task_repository.get_task_by_request("tenant_demo", "cancelled-analysis-request")
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["review"]["publication_gate"], "blocked")


if __name__ == "__main__":
    unittest.main()
