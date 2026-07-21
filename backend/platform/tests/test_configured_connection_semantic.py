from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.platform.semantic import (
    ConfiguredConnectionSupersonicClient,
    SemanticQueryRequest,
    SemanticQueryResult,
)
from backend.platform.settings import InMemorySystemConfigStore


class _FallbackClient:
    def query(self, request: SemanticQueryRequest) -> SemanticQueryResult:
        return SemanticQueryResult(
            sql="select branch_name, sum(loan_amount) as metric_value from local_mock",
            data=[{"branch_name": "样例机构", "metric_value": 1}],
            chart_spec={"type": "bar", "x": "branch_name", "y": "metric_value"},
            semantic_info={
                "dataset_id": request.dataset_id,
                "data_source": "json_mock:test",
                "policy_enforced_at_source": True,
                "applied_filters": dict(request.filters),
            },
        )


def _connection(connection_id: str, tenant_id: str = "tenant_demo") -> dict:
    del tenant_id
    return {
        "id": connection_id,
        "institution": "华兴银行",
        "sourceName": "毓数智能运营",
        "sourceType": "毓数QBI",
        "apiUrl": "https://data.example.com/api",
        "account": "reader",
        "password": "secret",
        "dataset": "loan_operation_mart",
        "enabled": True,
        "mockEnabled": False,
        "status": "verified",
        "testStatus": "verified",
    }


def _request(connection_id: str = "") -> SemanticQueryRequest:
    return SemanticQueryRequest(
        question="按机构分析放款金额",
        tenant_id="tenant_demo",
        user_id="u_admin",
        dataset_id="loan_operation_mart",
        metrics=("loan_amount",),
        dimensions=("branch_name",),
        filters={"tenant_id": "tenant_demo"},
        context={
            "connection_id": connection_id,
            "authorization": {"row_filter": {"tenant_id": "tenant_demo"}},
        },
    )


class ConfiguredConnectionSemanticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemorySystemConfigStore()
        self.client = ConfiguredConnectionSupersonicClient(self.store, _FallbackClient())

    def test_unique_verified_tenant_connection_executes_real_query(self) -> None:
        self.store.upsert_data_connection("tenant_demo", _connection("conn_yushu"))
        source = Mock()
        source.query.return_value = {
            "result": {
                "rows": [{"branch_name": "上海分行", "metric_value": 1280}],
                "sql": "select branch_name, sum(loan_amount) as metric_value from governed_view",
                "query_id": "provider-query-1",
                "semantic_info": {
                    "applied_filters": {"tenant_id": "tenant_demo"},
                    "totals": {"loan_amount": 1280},
                    "source_snapshot": {
                        "snapshot_id": "partition-2026-07-10",
                        "observed_at": "2026-07-10T02:00:00Z",
                        "immutable": True,
                    },
                    "metric_semantics": {
                        "loan_amount": {"aggregation": "sum", "version": "v1"},
                    },
                },
            }
        }
        with patch(
            "backend.platform.semantic.configured_client.HTTPJSONSourceClient",
            return_value=source,
        ) as source_class:
            result = self.client.query(_request())

        source_class.assert_called_once()
        sent = source.query.call_args.args[0]
        self.assertEqual(sent["tenant_id"], "tenant_demo")
        self.assertEqual(sent["filters"], {"tenant_id": "tenant_demo"})
        self.assertEqual(result.data[0]["metric_value"], 1280)
        self.assertEqual(result.semantic_info["connection_id"], "conn_yushu")
        self.assertEqual(result.semantic_info["execution_mode"], "real")
        self.assertTrue(result.semantic_info["publishable"])
        self.assertTrue(result.semantic_info["policy_enforced_at_source"])

    def test_provider_must_confirm_all_required_row_filters(self) -> None:
        self.store.upsert_data_connection("tenant_demo", _connection("conn_yushu"))
        source = Mock()
        source.query.return_value = {
            "rows": [{"branch_name": "越权机构", "metric_value": 999}],
            "semantic_info": {"applied_filters": {}},
        }
        with patch(
            "backend.platform.semantic.configured_client.HTTPJSONSourceClient",
            return_value=source,
        ), self.assertRaises(PermissionError):
            self.client.query(_request())

    def test_explicit_unverified_or_cross_tenant_connection_fails_closed(self) -> None:
        self.store.upsert_data_connection("tenant_other", _connection("conn_other"))
        with self.assertRaises(PermissionError):
            self.client.query(_request("conn_other"))

    def test_ambiguous_connections_do_not_choose_arbitrarily(self) -> None:
        self.store.upsert_data_connection("tenant_demo", _connection("conn_a"))
        self.store.upsert_data_connection("tenant_demo", _connection("conn_b"))
        result = self.client.query(_request())
        self.assertEqual(result.semantic_info["connection_selection"], "no_verified_tenant_connection")
        self.assertEqual(result.semantic_info["execution_mode"], "mock")
        self.assertFalse(result.semantic_info["publishable"])

    def test_model_sql_candidate_is_ignored_without_one_verified_connection(self) -> None:
        request = _request()
        request.context["model_sql_candidate"] = "select * from governed_view"
        result = self.client.query(request)
        self.assertEqual(result.semantic_info["connection_selection"], "no_verified_tenant_connection")
        self.assertNotIn("model_sql_applied", result.semantic_info)

    def test_model_sql_candidate_requires_provider_catalog_and_tenant_policy_confirmation(self) -> None:
        self.store.upsert_data_connection("tenant_demo", _connection("conn_yushu"))
        request = _request()
        request.context["model_sql_candidate"] = "select branch_name from governed_view"
        source = Mock()
        source.query.return_value = {
            "result": {
                "rows": [{"branch_name": "上海分行", "metric_value": 1}],
                "sql": "select branch_name from governed_view where tenant_id = :tenant_id",
                "semantic_info": {
                    "applied_filters": {"tenant_id": "tenant_demo"},
                    "catalog_validated": True,
                    "tenant_policy_injected": True,
                    "totals": {"loan_amount": 1},
                    "source_snapshot": {
                        "snapshot_id": "partition-model-sql",
                        "observed_at": "2026-07-11T01:00:00Z",
                        "immutable": True,
                    },
                    "metric_semantics": {"loan_amount": {"aggregation": "sum"}},
                },
            }
        }
        with patch("backend.platform.semantic.configured_client.HTTPJSONSourceClient", return_value=source):
            result = self.client.query(request)
        sent = source.query.call_args.args[0]
        self.assertEqual(sent["sql_candidate_source"], "selected_model")
        self.assertEqual(sent["manual_sql_candidate"], request.context["model_sql_candidate"])
        self.assertTrue(result.semantic_info["model_sql_applied"])
        self.assertFalse(result.semantic_info["manual_sql_applied"])


if __name__ == "__main__":
    unittest.main()
