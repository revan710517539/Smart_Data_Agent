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
    _optional_status_endpoint,
    _resolve_temporal_parameters,
    _schedule_statuses,
    _task_definition,
    handle_data_crawler_schedule_test,
)
from backend.platform.integrations.data_crawler import endpoint_for_tenant


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
            endpoint = SimpleNamespace(institution_directory="华兴银行")

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

    def test_saved_sql_binding_rejects_a_stale_delivery_even_when_hash_is_equal(self) -> None:
        digest = "b" * 64
        stale = {
            "institutionId": "huaxing",
            "sqlId": "sql_stale",
            "latestDelivery": {
                "path": "华兴银行/日报_2026-08-24.csv",
                "sha256": digest,
            },
        }

        class Client:
            endpoint = SimpleNamespace(institution_directory="华兴银行")

            @staticmethod
            def binding(_sql_id: str) -> dict[str, object]:
                return stale

        with self.assertRaisesRegex(PermissionError, "receipt_mismatch"):
            _binding_for_table(
                Client(),
                {"relativePath": "日报_2026-08-25.csv", "contentHash": digest},
                "sql_stale",
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
            endpoint = SimpleNamespace(institution_directory="华兴银行")

            @staticmethod
            def binding(_sql_id: str) -> dict[str, object]:
                return binding

        displayed = _configuration_binding_for_table(
            Client(),
            {"relativePath": "日报.csv", "contentHash": current_digest},
            "sql_daily",
        )
        self.assertEqual(displayed["sqlId"], "sql_daily")
        with self.assertRaisesRegex(PermissionError, "receipt_mismatch"):
            _binding_for_table(
                Client(),
                {"relativePath": "日报.csv", "contentHash": current_digest},
                "sql_daily",
            )

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

    def test_connectivity_test_validates_without_creating_or_updating_a_task(self) -> None:
        class Handler:
            response: dict[str, object] | None = None

            @staticmethod
            def _read_json() -> dict[str, object]:
                return {
                    "source_key": "source-key",
                    "sqlId": "sql_daily",
                    "recurrence": "daily",
                    "executionAt": "2026-08-27T09:30",
                    "parameterBindings": {"today": "reference"},
                }

            @staticmethod
            def _request_context(**_kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(tenant_id="tenant:华兴银行", user_id="u_super_admin")

            @staticmethod
            def _require_asset_permission(_context: object, permission: str) -> None:
                if permission != "read":
                    raise AssertionError("connectivity test must remain read-only")

            def _send_json(self, payload: dict[str, object]) -> None:
                self.response = payload

        handler = Handler()
        table = {"tableNameCn": "日报", "contentHash": "a" * 64}
        binding = {
            "institutionId": "huaxing",
            "sqlId": "sql_daily",
            "sqlName": "日报",
            "parameters": [{"name": "today", "type": "date"}],
        }
        client = SimpleNamespace(endpoint=SimpleNamespace(institution_id="huaxing"))
        with (
            mock.patch("backend.platform.api.routes.data_crawler_schedule._raw_table", return_value=(object(), table)),
            mock.patch("backend.platform.api.routes.data_crawler_schedule.client_for_tenant", return_value=client),
            mock.patch("backend.platform.api.routes.data_crawler_schedule._binding_for_table", return_value=binding),
        ):
            handle_data_crawler_schedule_test(handler)

        self.assertEqual(
            handler.response,
            {
                "tenant_id": "tenant:华兴银行",
                "connected": True,
                "institution_id": "huaxing",
                "sql_id": "sql_daily",
                "parameter_count": 1,
                "receipt_sha256": "a" * 64,
            },
        )

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
        def task(source_key: str, *, institution_id: str = "huaxing", status: str = "active", trigger_type: str = "schedule") -> dict[str, object]:
            return {
                "handler_ref": "data_crawler.dispatch",
                "status": status,
                "trigger_type": trigger_type,
                "schedule_expression": "0 9 * * *",
                "next_run_at": "2026-08-26T09:00:00+08:00",
                "task_config": {
                    "source_key": source_key,
                    "institution_id": institution_id,
                    "recurrence": "daily",
                },
            }

        statuses = _schedule_statuses(
            [
                task("scheduled"),
                task("manual", trigger_type="manual"),
                task("disabled", status="disabled"),
                task("other-institution", institution_id="nanjing"),
                task("not-in-catalog"),
                {**task("other-handler"), "handler_ref": "analysis.run"},
            ],
            {"scheduled", "manual", "disabled", "other-institution", "other-handler"},
            "huaxing",
        )

        self.assertEqual(
            statuses,
            {
                "scheduled": {
                    "scheduled": True,
                    "recurrence": "daily",
                    "schedule_expression": "0 9 * * *",
                    "next_run_at": "2026-08-26T09:00:00+08:00",
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
