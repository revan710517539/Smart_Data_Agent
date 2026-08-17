from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.api.routes.metrics import (
    _duplicate_metric_names,
    _prepare_metric_import,
    handle_metric_dictionary_import,
)


class MetricDictionaryImportTest(unittest.TestCase):
    def test_duplicate_names_include_existing_and_conflicting_workbook_names_in_source_order(self) -> None:
        rows = [
            {"metricName": "新增余额", "definition": "余额定义一"},
            {"metricName": "动支率"},
            {"metricName": "新增余额", "definition": "余额定义二"},
            {"metricName": "在贷余额"},
        ]

        self.assertEqual(
            _duplicate_metric_names(rows, {"动支率"}),
            ["新增余额", "动支率"],
        )

    def test_unique_workbook_names_are_accepted(self) -> None:
        self.assertEqual(
            _duplicate_metric_names([{"metricName": "新增余额"}, {"metricName": "动支率"}], set()),
            [],
        )

    def test_identical_workbook_rows_are_imported_once_with_skip_receipt(self) -> None:
        repeated = {
            "metricName": "2段客户信息校验未通过人数",
            "definition": "",
            "valueLogic": "todo_type=CUST_UPDATE_INFO",
            "sourceTable": "target_btl.t_todo_info表",
        }

        accepted, conflicts, skipped_names, skipped_count = _prepare_metric_import(
            [repeated, dict(repeated)],
            set(),
        )

        self.assertEqual(accepted, [repeated])
        self.assertEqual(conflicts, [])
        self.assertEqual(skipped_names, ["2段客户信息校验未通过人数"])
        self.assertEqual(skipped_count, 1)

    def test_identical_workbook_row_still_conflicts_with_existing_dictionary(self) -> None:
        row = {"metricName": "动支率", "definition": "动支人数/授信人数"}

        accepted, conflicts, skipped_names, skipped_count = _prepare_metric_import(
            [row, dict(row)],
            {"动支率"},
        )

        self.assertEqual(accepted, [row])
        self.assertEqual(conflicts, ["动支率"])
        self.assertEqual(skipped_names, ["动支率"])
        self.assertEqual(skipped_count, 1)

    def test_import_endpoint_returns_exact_duplicate_skip_receipt(self) -> None:
        repeated = {
            "metricName": "2段客户信息校验未通过人数",
            "definition": "",
            "valueLogic": "todo_type=CUST_UPDATE_INFO",
            "sourceTable": "target_btl.t_todo_info表",
        }

        class Store:
            def __init__(self) -> None:
                self.saved: list[dict[str, object]] = []

            def list(self, tenant_id: str) -> list[dict[str, object]]:
                return []

            def upsert(self, tenant_id: str, metric: dict[str, object], updated_by: str) -> dict[str, object]:
                self.saved.append(metric)
                return metric

        store = Store()
        repository = SimpleNamespace(get_user_roles=lambda user_id, tenant_id: [], get_role=lambda role_id: None)
        handler = SimpleNamespace()
        handler.services = SimpleNamespace(
            metric_dictionary_store=store,
            permission_broker=SimpleNamespace(enforcer=SimpleNamespace(repository=repository)),
        )
        handler._read_json = lambda max_bytes: {"file_name": "metrics.xlsx", "file_content_base64": "ignored"}
        handler._request_context = lambda payload: SimpleNamespace(tenant_id="tenant:test", user_id="u_admin")
        handler._require_metric_permission = lambda context, action: None
        handler._write_audit = lambda *args, **kwargs: None
        response: dict[str, object] = {}
        handler._send_json = lambda payload: response.update(payload)

        with patch(
            "backend.platform.api.routes.metrics.parse_metric_workbook",
            return_value=[repeated, dict(repeated)],
        ):
            handle_metric_dictionary_import(handler)

        self.assertEqual(len(store.saved), 1)
        self.assertEqual(response["created_count"], 1)
        self.assertEqual(response["skipped_count"], 1)
        self.assertEqual(response["skipped_names"], ["2段客户信息校验未通过人数"])


if __name__ == "__main__":
    unittest.main()
