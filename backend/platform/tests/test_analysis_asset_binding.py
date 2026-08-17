from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.platform.api.routes.assets import _bind_analysis_asset, _detail_query_from_execution
from backend.platform.assets.store import _validate_asset_schema


def _task(*, execution_mode: str = "selected_raw_csv") -> dict:
    return {
        "task_id": "task_1",
        "tenant_id": "tenant_demo",
        "user_id": "u_super_admin",
        "status": "review_required",
        "execution_id": "execution_1",
        "review": {"status": "needs_human_review", "publication_gate": "blocked"},
        "skill_results": [{
            "data": [{"period": "2026-08", "amount": 100}],
            "semantic_info": {"execution_mode": execution_mode, "publishable": False},
            "evidence": {
                "evidence_id": "evidence_1",
                "source_snapshot": {"snapshot_id": "snapshot_1"},
                "sql_executed": True,
                "executed_sql": "SELECT period, amount FROM governed_source",
            },
        }],
    }


class AnalysisAssetBindingTests(unittest.TestCase):
    def test_executed_query_allows_semicolon_in_leading_comment(self) -> None:
        sql = _detail_query_from_execution(
            '-- Selected tenant CSV; executed by the bounded read-only adapter.\n'
            'SELECT "period", SUM("amount") FROM "source" GROUP BY "period";'
        )

        self.assertEqual(sql, 'SELECT "period", SUM("amount") FROM "source" GROUP BY "period"')

    def test_review_required_real_execution_can_be_saved_as_review_candidate(self) -> None:
        task = _task()
        handler = SimpleNamespace(services=SimpleNamespace(
            task_repository=SimpleNamespace(get_task=lambda task_id: task),
        ))
        context = SimpleNamespace(tenant_id="tenant_demo", user_id="u_super_admin")
        item = {
            "analysisTaskId": "task_1",
            "fields": [
                {"fieldNameEn": "period", "fieldNameCn": "期间", "type": "string"},
                {"fieldNameEn": "amount", "fieldNameCn": "金额", "type": "decimal"},
            ],
        }

        bound = _bind_analysis_asset(handler, context, "topic_table", item)

        self.assertFalse(bound["publicationReady"])
        self.assertTrue(bound["reviewRequired"])
        self.assertEqual(bound["sql"], "SELECT period, amount FROM governed_source")
        self.assertEqual(bound["tenantBindingMode"], "analysis_task_scoped")
        _validate_asset_schema("topic_table", {
            **bound,
            "id": "topic_candidate",
            "name": "经营分析主题",
            "code": "topic_candidate",
            "description": "基于已执行证据生成的候选。",
        })

    def test_demo_execution_cannot_be_saved_as_review_candidate(self) -> None:
        task = _task(execution_mode="demo")
        handler = SimpleNamespace(services=SimpleNamespace(
            task_repository=SimpleNamespace(get_task=lambda task_id: task),
        ))
        context = SimpleNamespace(tenant_id="tenant_demo", user_id="u_super_admin")

        with self.assertRaisesRegex(ValueError, "executed_analysis_evidence_required_for_asset_candidate"):
            _bind_analysis_asset(handler, context, "topic_table", {
                "analysisTaskId": "task_1",
                "fields": [{"fieldNameEn": "period"}, {"fieldNameEn": "amount"}],
            })


if __name__ == "__main__":
    unittest.main()
