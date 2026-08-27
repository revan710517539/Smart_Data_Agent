from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from backend.platform.bootstrap import _seed_metric_dictionary_if_empty
from backend.platform.metrics import PostgreSQLMetricDictionaryStore


class ProductionMetricDictionarySeedTests(unittest.TestCase):
    def test_relational_empty_dictionary_is_seeded(self) -> None:
        store = Mock(spec=PostgreSQLMetricDictionaryStore)
        store.list.return_value = []
        metrics = [{"metricId": "m1", "metricName": "指标一"}]

        with patch("backend.platform.bootstrap.load_default_metric_dictionary", return_value=metrics):
            _seed_metric_dictionary_if_empty(
                store,
                None,
                tenant_ids=["tenant:shizuishan", "tenant:other"],
                force=True,
            )

        self.assertEqual(store.seed_if_empty.call_count, 2)
        store.seed_if_empty.assert_any_call("tenant:shizuishan", metrics, updated_by="u_super_admin")
        store.seed_if_empty.assert_any_call("tenant:other", metrics, updated_by="u_super_admin")

    def test_relational_existing_dictionary_is_not_replaced(self) -> None:
        store = Mock(spec=PostgreSQLMetricDictionaryStore)

        with patch("backend.platform.bootstrap.load_default_metric_dictionary") as load_defaults:
            load_defaults.return_value = [{"metricId": "m1"}]
            _seed_metric_dictionary_if_empty(store, None, tenant_ids=["tenant:shizuishan"], force=True)

        store.seed_if_empty.assert_called_once_with(
            "tenant:shizuishan",
            [{"metricId": "m1"}],
            updated_by="u_super_admin",
        )
        store.replace_all.assert_not_called()

    def test_relational_read_error_is_not_treated_as_empty(self) -> None:
        store = Mock(spec=PostgreSQLMetricDictionaryStore)
        store.seed_if_empty.side_effect = RuntimeError("database unavailable")

        with patch("backend.platform.bootstrap.load_default_metric_dictionary", return_value=[{"metricId": "m1"}]):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                _seed_metric_dictionary_if_empty(store, None, tenant_ids=["tenant:shizuishan"], force=True)

        store.replace_all.assert_not_called()

    def test_explicit_empty_catalog_does_not_fall_back_to_operating_tenant(self) -> None:
        store = Mock(spec=PostgreSQLMetricDictionaryStore)

        with patch("backend.platform.bootstrap.load_default_metric_dictionary", return_value=[{"metricId": "m1"}]):
            _seed_metric_dictionary_if_empty(store, None, tenant_ids=[], force=True)

        store.seed_if_empty.assert_not_called()

    def test_local_seed_remains_disabled_without_opt_in(self) -> None:
        store = Mock()
        with patch.dict(os.environ, {"SMART_DATA_AGENT_SEED_METRIC_DICTIONARY": "0"}):
            _seed_metric_dictionary_if_empty(store, None)
        store.list.assert_not_called()


if __name__ == "__main__":
    unittest.main()
