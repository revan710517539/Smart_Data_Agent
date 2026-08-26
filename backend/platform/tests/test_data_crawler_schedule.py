from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from backend.platform.api.routes.data_crawler_schedule import (
    _cron,
    _binding_for_table,
    _configuration_binding_for_table,
    _existing_task_for_binding,
    _optional_status_endpoint,
    _refresh_execution_parameters,
    _resolve_temporal_parameters,
    _schedule_statuses,
    _select_refresh_binding,
    _sql_title_key,
    _task_code,
    _task_definition,
    handle_data_crawler_schedule_refresh,
    handle_data_crawler_schedule_test,
)
from backend.platform.integrations.data_crawler import endpoint_for_tenant
from backend.platform.api.support import send_route_exception


class DataCrawlerScheduleContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoints = {
            "tenant:华兴银行": {
                "baseUrl": "http://127.0.0.1:8795",
                "institutionId": "huaxing",
                "institutionDirectory": "华兴银行",
                "token": "huaxing-token-1234567890",
            },
            "tenant:郑州银行": {
                "baseUrl": "http://data-crawler:8795",
                "institutionId": "zhengzhou",
                "institutionDirectory": "郑州银行",
                "token": "zhengzhou-token-1234567890",
            },
            "tenant:南京银行": {
                "baseUrl": "http://data-crawler:8795",
                "institutionId": "nanjing",
                "institutionDirectory": "南京银行",
                "token": "nanjing-token-1234567890",
            },
            "tenant:广州银行": {
                "baseUrl": "http://data-crawler:8795",
                "institutionId": "guangzhou",
                "institutionDirectory": "广州银行",
                "token": "guangzhou-token-1234567890",
            },
        }

    def test_tenant_endpoint_binding_is_exact_and_never_falls_back(self) -> None:
        with mock.patch.dict(os.environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ENDPOINTS": json.dumps(self.endpoints, ensure_ascii=False)}):
            for tenant_id, institution_id, directory in (
                ("tenant:华兴银行", "huaxing", "华兴银行"),
                ("tenant:南京银行", "nanjing", "南京银行"),
                ("tenant:广州银行", "guangzhou", "广州银行"),
            ):
                with self.subTest(tenant_id=tenant_id):
                    endpoint = endpoint_for_tenant(tenant_id)
                    self.assertEqual(endpoint.institution_id, institution_id)
                    self.assertEqual(endpoint.institution_directory, directory)
            with self.assertRaisesRegex(PermissionError, "binding_missing"):
                endpoint_for_tenant("tenant:石嘴山银行")

    def test_endpoint_rejects_english_institution_id_as_a_filesystem_directory(self) -> None:
        bindings = {**self.endpoints}
        bindings["tenant:华兴银行"] = {**bindings["tenant:华兴银行"], "institutionDirectory": "huaxing"}
        with mock.patch.dict(os.environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ENDPOINTS": json.dumps(bindings, ensure_ascii=False)}):
            with self.assertRaisesRegex(ValueError, "tenant_directory_mismatch"):
                endpoint_for_tenant("tenant:华兴银行")

    def test_status_projection_is_unavailable_when_endpoint_is_not_configured(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(_optional_status_endpoint("tenant:华兴银行"))

    def test_status_projection_is_unavailable_when_tenant_binding_is_missing(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"SMART_DATA_AGENT_DATA_CRAWLER_ENDPOINTS": json.dumps(self.endpoints, ensure_ascii=False)},
            clear=True,
        ):
            self.assertIsNone(_optional_status_endpoint("tenant:石嘴山银行"))

    def test_status_projection_keeps_invalid_endpoint_configuration_fail_closed(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"SMART_DATA_AGENT_DATA_CRAWLER_ENDPOINTS": "not-json"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid_json"):
                _optional_status_endpoint("tenant:华兴银行")

    def test_unconfigured_crawler_endpoint_returns_actionable_service_unavailable(self) -> None:
        sent: dict[str, object] = {}
        handler = SimpleNamespace(
            headers={"X-Request-Id": "req_schedule_refresh"},
            _send_json=lambda payload, status, headers=None: sent.update(
                payload=payload, status=status, response_headers=headers or {}
            ),
        )

        send_route_exception(handler, RuntimeError("data_crawler_endpoint_not_configured"))

        self.assertEqual(int(sent["status"]), 503)
        self.assertEqual(sent["payload"]["error"], "data_crawler_endpoint_not_configured")
        self.assertIn("尚未配置 Data Crawler 连接", sent["payload"]["message"])

    def test_disabled_crawler_integration_returns_actionable_service_unavailable(self) -> None:
        sent: dict[str, object] = {}
        handler = SimpleNamespace(
            headers={},
            _send_json=lambda payload, status, headers=None: sent.update(payload=payload, status=status),
        )

        send_route_exception(handler, RuntimeError("当前机构未启用 SDA 集成"))

        self.assertEqual(int(sent["status"]), 503)
        self.assertEqual(sent["payload"]["error"], "data_crawler_integration_disabled")
        self.assertIn("尚未启用 SDA 集成", sent["payload"]["message"])

    def test_binding_uses_exact_delivery_path_then_checks_current_digest(self) -> None:
        current_digest = "a" * 64
        stale_same_digest = {
            "institutionId": "huaxing",
            "sqlId": "sql_stale",
            "latestDelivery": {
                "path": "华兴银行/日报_2026-08-24.csv",
                "sha256": current_digest,
            },
        }
        current = {
            "institutionId": "huaxing",
            "sqlId": "sql_current",
            "latestDelivery": {
                "path": "华兴银行/日报_2026-08-25.csv",
                "sha256": current_digest,
            },
        }

        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行", institution_id="huaxing")

            @staticmethod
            def list_bindings() -> dict[str, object]:
                return {"items": [stale_same_digest, current]}

        binding = _binding_for_table(
            Client(),
            {
                "relativePath": "日报_2026-08-25.csv",
                "contentHash": current_digest,
            },
        )
        self.assertEqual(binding["sqlId"], "sql_current")

    def test_table_lineage_rejects_a_different_saved_or_client_sql_id(self) -> None:
        digest = "b" * 64
        bound = {
            "institutionId": "huaxing",
            "sqlId": "sql_bound",
            "latestDelivery": {
                "path": "华兴银行/日报_2026-08-24.csv",
                "sha256": digest,
            },
        }

        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行", institution_id="huaxing")

            @staticmethod
            def binding(sql_id: str) -> dict[str, object]:
                if sql_id != "sql_bound":
                    raise AssertionError("table lineage must select its own SQL")
                return bound

        with self.assertRaisesRegex(PermissionError, "override_forbidden"):
            _binding_for_table(
                Client(),
                {"relativePath": "日报_2026-08-25.csv", "contentHash": digest, "sqlId": "sql_bound"},
                "sql_other",
            )

    def test_opening_configuration_does_not_validate_a_changing_csv_digest(self) -> None:
        stale_digest = "a" * 64
        current_digest = "b" * 64
        binding = {
            "institutionId": "huaxing",
            "sqlId": "sql_daily",
            "latestDelivery": {
                "path": "华兴银行/日报.csv",
                "sha256": stale_digest,
            },
        }

        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行", institution_id="huaxing")

            @staticmethod
            def binding(_sql_id: str) -> dict[str, object]:
                return binding

        displayed = _configuration_binding_for_table(
            Client(),
            {"relativePath": "日报.csv", "contentHash": current_digest, "sqlId": "sql_daily"},
            "sql_daily",
        )
        self.assertEqual(displayed["sqlId"], "sql_daily")
        executable = _binding_for_table(
            Client(),
            {"relativePath": "日报.csv", "contentHash": current_digest, "sqlId": "sql_daily"},
            "sql_daily",
        )
        self.assertEqual(executable["sqlId"], "sql_daily")

    def test_biweekly_uses_weekly_cron_and_keeps_anchor_in_task_config(self) -> None:
        binding = {
            "institutionId": "huaxing",
            "sqlId": "sql_daily",
            "sqlName": "日报",
            "parameters": [{"name": "today", "type": "date"}],
        }
        definition = _task_definition(
            "source-key",
            {"tableNameCn": "日报", "contentHash": "a" * 64},
            binding,
            {
                "recurrence": "biweekly",
                "time": "09:30",
                "weekday": 1,
                "biweeklyAnchor": "2026-08-24",
                "parameterBindings": {"today": "execution_date"},
            },
        )
        self.assertEqual(_cron("biweekly", "09:30", 1, 1), ("schedule", "30 9 * * 1"))
        self.assertEqual(definition["task_config"]["biweekly_anchor"], "2026-08-24")

    def test_execution_datetime_drives_weekly_cron_and_anchor(self) -> None:
        binding = {
            "institutionId": "huaxing",
            "sqlId": "sql_daily",
            "sqlName": "日报",
            "parameters": [{"name": "today", "type": "date"}],
        }
        definition = _task_definition(
            "source-key",
            {"tableNameCn": "日报", "contentHash": "a" * 64},
            binding,
            {
                "recurrence": "weekly",
                "executionAt": "2026-08-27T14:35",
                "parameterBindings": {"today": "reference"},
            },
        )
        self.assertEqual(definition["schedule_expression"], "35 14 * * 4")
        self.assertEqual(definition["task_config"]["execution_at"], "2026-08-27T14:35")
        self.assertEqual(definition["task_config"]["biweekly_anchor"], "2026-08-27")

    def test_task_identity_is_stable_across_dated_delivery_source_keys(self) -> None:
        binding = {
            "institutionId": "huaxing",
            "sqlId": "sql_daily",
            "sqlName": "日报",
            "parameters": [],
        }
        first = _task_definition("source-2026-08-25", {"tableNameCn": "日报"}, binding, {"recurrence": "none"})
        second = _task_definition("source-2026-08-26", {"tableNameCn": "日报"}, binding, {"recurrence": "none"})

        self.assertEqual(first["task_code"], second["task_code"])
        self.assertEqual(first["task_code"], _task_code("huaxing", "sql_daily"))
        self.assertNotEqual(first["task_config"]["source_key"], second["task_config"]["source_key"])

    def test_existing_sql_task_survives_delivery_source_key_change(self) -> None:
        existing = {
            "automation_task_id": "task-old-source",
            "handler_ref": "data_crawler.dispatch",
            "status": "active",
            "trigger_type": "schedule",
            "task_config": {
                "source_key": "source-2026-08-25",
                "institution_id": "huaxing",
                "sql_id": "sql_daily",
            },
        }

        class Store:
            @staticmethod
            def get_task_by_code(_tenant_id: str, _task_code_value: str) -> None:
                return None

            @staticmethod
            def list_tasks(_tenant_id: str) -> list[dict[str, object]]:
                return [existing]

        selected = _existing_task_for_binding(
            Store(),
            "tenant:华兴银行",
            {"institutionId": "huaxing", "sqlId": "sql_daily"},
            "source-2026-08-26",
        )
        self.assertIs(selected, existing)

    def test_three_temporal_modes_resolve_date_month_and_datetime(self) -> None:
        reference = datetime(2026, 3, 31, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
        binding = {
            "parameters": [
                {"name": "start_date", "type": "date"},
                {"name": "end_date", "type": "date"},
                {"name": "start_month", "type": "month"},
                {"name": "end_month", "type": "month"},
                {"name": "snapshot_at", "type": "datetime"},
            ],
        }
        resolved = _resolve_temporal_parameters(
            binding,
            {"snapshot_at": "2026-01-02T03:04"},
            {
                "start_date": "before:7",
                "end_date": "reference",
                "start_month": "before:1",
                "end_month": "reference",
            },
            reference,
        )
        self.assertEqual(
            resolved,
            {
                "start_date": "2026-03-24",
                "end_date": "2026-03-31",
                "start_month": "2026-02",
                "end_month": "2026-03",
                "snapshot_at": "2026-01-02 03:04:00",
            },
        )

    def test_before_mode_requires_a_positive_n(self) -> None:
        with self.assertRaisesRegex(ValueError, "offset_invalid"):
            _resolve_temporal_parameters(
                {"parameters": [{"name": "start_date", "type": "date"}]},
                {},
                {"start_date": "before:0"},
                datetime(2026, 8, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

    def test_test_action_executes_exact_sql_without_creating_an_automation_task(self) -> None:
        class Handler:
            response: dict[str, object] | None = None

            @staticmethod
            def _read_json() -> dict[str, object]:
                return {
                    "source_key": "source-key",
                    "recurrence": "daily",
                    "executionAt": "2026-08-27T09:30",
                    "parameterBindings": {"today": "reference"},
                }

            @staticmethod
            def _request_context(**_kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(tenant_id="tenant:华兴银行", user_id="u_super_admin")

            @staticmethod
            def _require_asset_permission(_context: object, permission: str) -> None:
                if permission != "create":
                    raise AssertionError("one-shot SQL execution requires create permission")

            def _send_json(self, payload: dict[str, object]) -> None:
                self.response = payload

        handler = Handler()
        table = {"tableNameCn": "日报", "contentHash": "a" * 64, "sqlId": "sql_daily"}
        binding = {
            "institutionId": "huaxing",
            "sqlId": "sql_daily",
            "sqlName": "日报",
            "parameters": [{"name": "today", "type": "date"}],
        }
        client = SimpleNamespace(
            endpoint=SimpleNamespace(institution_id="huaxing"),
            execute=mock.Mock(
                return_value={
                    "runId": "run_test",
                    "status": "running",
                    "sqlId": "sql_daily",
                    "institutionId": "huaxing",
                }
            ),
        )
        with (
            mock.patch("backend.platform.api.routes.data_crawler_schedule._raw_table", return_value=(object(), table)),
            mock.patch("backend.platform.api.routes.data_crawler_schedule.client_for_tenant", return_value=client),
            mock.patch("backend.platform.api.routes.data_crawler_schedule._binding_for_table", return_value=binding),
        ):
            handle_data_crawler_schedule_test(handler)

        client.execute.assert_called_once()
        executed_sql_id, execution_payload = client.execute.call_args.args
        self.assertEqual(executed_sql_id, "sql_daily")
        self.assertEqual(execution_payload["parameterBindings"], {})
        self.assertEqual(execution_payload["timezone"], "Asia/Shanghai")
        self.assertEqual(set(execution_payload["parameters"]), {"today"})
        self.assertRegex(execution_payload["executionId"], r"^sda-test-[0-9a-f]{32}$")

        self.assertEqual(
            handler.response,
            {
                "tenant_id": "tenant:华兴银行",
                "connected": True,
                "institution_id": "huaxing",
                "sql_id": "sql_daily",
                "parameter_count": 1,
                "receipt_sha256": "a" * 64,
                "run": {
                    "runId": "run_test",
                    "status": "running",
                    "sqlId": "sql_daily",
                    "institutionId": "huaxing",
                },
            },
        )

    def test_refresh_only_reloads_the_table_binding_and_never_executes_sql(self) -> None:
        permissions: list[str] = []

        class Handler:
            response: dict[str, object] | None = None

            @staticmethod
            def _read_json() -> dict[str, object]:
                return {"source_key": "source-key"}

            @staticmethod
            def _request_context(**_kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(tenant_id="tenant:华兴银行", user_id="u_super_admin")

            @staticmethod
            def _require_asset_permission(_context: object, permission: str) -> None:
                permissions.append(permission)

            def _send_json(self, payload: dict[str, object]) -> None:
                self.response = payload

        handler = Handler()
        table = {"sqlId": "sql_daily", "tableNameCn": "日报", "contentHash": "a" * 64}
        binding = {
            "institutionId": "huaxing",
            "sqlId": "sql_daily",
            "sqlName": "日报",
            "parameters": [{"name": "today", "type": "date"}],
        }
        client = SimpleNamespace(
            endpoint=SimpleNamespace(institution_id="huaxing", institution_directory="华兴银行"),
            execute=mock.Mock(side_effect=AssertionError("refresh must not execute SQL")),
        )
        with (
            mock.patch("backend.platform.api.routes.data_crawler_schedule._raw_table", return_value=(object(), table)),
            mock.patch("backend.platform.api.routes.data_crawler_schedule.client_for_tenant", return_value=client),
            mock.patch("backend.platform.api.routes.data_crawler_schedule._select_refresh_binding", return_value=binding),
        ):
            handle_data_crawler_schedule_refresh(handler)

        self.assertEqual(permissions, ["read"])
        client.execute.assert_not_called()
        self.assertEqual(handler.response, {
            "tenant_id": "tenant:华兴银行",
            "source_key": "source-key",
            "binding": binding,
            "refreshed": True,
        })

    def test_non_time_parameter_fails_closed_in_current_phase(self) -> None:
        with self.assertRaisesRegex(ValueError, "non_temporal"):
            _task_definition(
                "source-key",
                {"tableNameCn": "客户表", "contentHash": "b" * 64},
                {
                    "institutionId": "huaxing",
                    "sqlId": "sql_customer",
                    "sqlName": "客户查询",
                    "parameters": [{"name": "user_no", "type": "text"}],
                },
                {"recurrence": "none"},
            )

    def test_schedule_statuses_only_expose_active_same_institution_schedules(self) -> None:
        def task(sql_id: str, *, institution_id: str = "huaxing", status: str = "active", trigger_type: str = "schedule") -> dict[str, object]:
            return {
                "handler_ref": "data_crawler.dispatch",
                "status": status,
                "trigger_type": trigger_type,
                "schedule_expression": "0 9 * * *",
                "next_run_at": "2026-08-26T09:00:00+08:00",
                "task_config": {
                    "source_key": "stale-delivery-source-key",
                    "sql_id": sql_id,
                    "institution_id": institution_id,
                    "recurrence": "daily",
                },
            }

        statuses = _schedule_statuses(
            [
                task("sql_scheduled"),
                task("sql_manual", trigger_type="manual"),
                task("sql_disabled", status="disabled"),
                task("sql_other_institution", institution_id="nanjing"),
                task("sql_not_in_catalog"),
                {**task("sql_other_handler"), "handler_ref": "analysis.run"},
            ],
            {
                "sql_scheduled": "current-delivery-source-key",
                "sql_manual": "manual-source",
                "sql_disabled": "disabled-source",
                "sql_other_institution": "other-institution-source",
                "sql_other_handler": "other-handler-source",
            },
            "huaxing",
        )

        self.assertEqual(
            statuses,
            {
                "current-delivery-source-key": {
                    "scheduled": True,
                    "recurrence": "daily",
                    "schedule_expression": "0 9 * * *",
                    "next_run_at": "2026-08-26T09:00:00+08:00",
                }
            },
        )


    def test_refresh_binding_matches_table_title_when_receipt_is_missing(self) -> None:
        items = [
            {"institutionId": "zhengzhou", "sqlId": "sql_flow", "sqlName": "双周报流量与审批转化"},
            {"institutionId": "zhengzhou", "sqlId": "sql_other", "sqlName": "经营日报"},
        ]

        class Client:
            endpoint = SimpleNamespace(institution_directory="郑州银行", institution_id="zhengzhou")

            @staticmethod
            def list_bindings() -> dict[str, object]:
                return {"items": items}

            @staticmethod
            def binding(sql_id: str) -> dict[str, object]:
                return next(item for item in items if item["sqlId"] == sql_id)

        binding = _select_refresh_binding(
            Client(),
            {"tableNameCn": "双周报流量与审批转化_2026-08-14", "fileName": "20260814_130518_双周报流量与审批转化.csv"},
        )
        self.assertEqual(binding["sqlId"], "sql_flow")
        self.assertEqual(_sql_title_key("事件发生口径转化-经营贷_2026-08-14"), _sql_title_key("事件发生口径转化-经营贷"))

    def test_ambiguous_legacy_name_fails_closed_and_cannot_be_overridden(self) -> None:
        items = [
            {"institutionId": "huaxing", "sqlId": "sql_a", "sqlName": "同名报表"},
            {"institutionId": "huaxing", "sqlId": "sql_b", "sqlName": "同名报表"},
        ]

        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行", institution_id="huaxing")

            @staticmethod
            def list_bindings() -> dict[str, object]:
                return {"items": items}

            @staticmethod
            def binding(sql_id: str) -> dict[str, object]:
                return next(item for item in items if item["sqlId"] == sql_id)

        table = {"tableNameCn": "同名报表_2026-08-26", "relativePath": "同名报表_2026-08-26.csv"}
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            _select_refresh_binding(Client(), table)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            _select_refresh_binding(Client(), table, "sql_b")

    def test_single_unrelated_sql_is_never_used_as_a_fallback(self) -> None:
        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行", institution_id="huaxing")

            @staticmethod
            def list_bindings() -> dict[str, object]:
                return {"items": [{"institutionId": "huaxing", "sqlId": "sql_other", "sqlName": "另一张表"}]}

        self.assertEqual(
            _configuration_binding_for_table(
                Client(),
                {"tableNameCn": "目标日报_2026-08-26", "relativePath": "目标日报_2026-08-26.csv"},
            ),
            {},
        )

    def test_manifest_sql_id_wins_without_listing_or_name_matching(self) -> None:
        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行", institution_id="huaxing")

            @staticmethod
            def binding(sql_id: str) -> dict[str, object]:
                return {"institutionId": "huaxing", "sqlId": sql_id, "sqlName": "权威脚本", "parameters": []}

            @staticmethod
            def list_bindings() -> dict[str, object]:
                raise AssertionError("manifest SQL ID must avoid catalog guessing")

        binding = _configuration_binding_for_table(
            Client(),
            {"sqlId": "sql_manifest", "tableNameCn": "任意展示名称"},
        )
        self.assertEqual(binding["sqlId"], "sql_manifest")

    def test_manifest_sql_id_rejects_a_foreign_institution_binding(self) -> None:
        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行", institution_id="huaxing")

            @staticmethod
            def binding(sql_id: str) -> dict[str, object]:
                return {"institutionId": "nanjing", "sqlId": sql_id, "sqlName": "串机构脚本"}

        with self.assertRaisesRegex(PermissionError, "institution_mismatch"):
            _binding_for_table(Client(), {"sqlId": "sql_foreign"})

    def test_refresh_execution_uses_reference_day_for_today(self) -> None:
        binding = {
            "parameters": [{"name": "today", "type": "date"}],
        }
        resolved = _refresh_execution_parameters(binding)
        self.assertRegex(resolved["today"], r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
