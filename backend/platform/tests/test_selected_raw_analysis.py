from __future__ import annotations

import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.ingestion.csv_folder import CSVFolderSource
from backend.platform.orchestration.workflow import _build_temporary_raw_table_plan
from backend.platform.skills.builtin.supersonic_query import build_supersonic_query_skill
from backend.platform.skills.models import SkillRequest
from backend.platform.tenancy import ExecutionContext


class SelectedRawAnalysisTest(unittest.TestCase):
    def test_governed_multi_page_data_executes_without_cross_tenant_raw_catalog(self) -> None:
        class UnexpectedSemanticService:
            def query(self, _request):  # pragma: no cover - must not be called.
                raise AssertionError("governed page data must not fall back to semantic service")

        class UnexpectedCsvSource:
            def for_tenant(self, _tenant_id):  # pragma: no cover - must not be called.
                raise AssertionError("page data execution must not browse tenant raw tables")

        selected = {
            "id": "page_data_multi_1",
            "kind": "page_data",
            "tableNameEn": "page_data_page_data_multi_1",
            "tableNameCn": "跨机构放款页面数据",
            "relativePath": "page-data://page_data_multi_1",
            "sourceKey": "relationship_multi_1",
            "relationshipGroupId": "relationship_multi_1",
            "schemaFingerprint": "page-schema-1",
            "fields": [
                {"fieldNameEn": "__institution_name", "fieldNameCn": "机构", "type": "string"},
                {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "isMetric": True},
            ],
            "previewRows": [
                {"__institution_name": "华兴银行", "loan_amount": "100"},
                {"__institution_name": "广州银行", "loan_amount": "200"},
            ],
        }
        plan = _build_temporary_raw_table_plan({}, selected, "按机构分析放款金额")
        _, handler = build_supersonic_query_skill(UnexpectedSemanticService(), UnexpectedCsvSource())
        result = handler(SkillRequest(
            skill_id="supersonic.query",
            context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant:华兴银行"),
            inputs={
                "question": "按机构分析放款金额",
                "dataset_id": plan["dataset_id"],
                "metrics": plan["metrics"],
                "dimensions": plan["dimensions"],
                "limit": 50,
                "context": {"analysis_plan": plan, "selected_raw_table": selected},
            },
        ))
        semantic = result.output["semantic_info"]
        self.assertEqual(semantic["data_source"], "governed_multi_institution_page_data")
        self.assertEqual(semantic["execution_mode"], "selected_multi_page_data")
        self.assertTrue(semantic["publishable"])
        self.assertEqual(semantic["source_snapshot"]["page_data_id"], "page_data_multi_1")
        self.assertEqual(semantic["source_snapshot"]["relationship_group_id"], "relationship_multi_1")
        self.assertEqual(len(result.output["data"]), 2)

    def test_selected_csv_executes_with_temporary_schema_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tenant_dir = Path(temp_dir) / "华兴银行"
            tenant_dir.mkdir()
            (tenant_dir / "经营数据.csv").write_text(
                "日期,总完件,通过率,户均\n2026-05-01,10,50%,10\n2026-05-02,20,75%,20\n",
                encoding="utf-8",
            )
            csv_source = CSVFolderSource(temp_dir)
            table = csv_source.for_tenant("tenant:华兴银行").table_assets()[0]
            plan = _build_temporary_raw_table_plan({}, table, "分析一下这个数据")

            self.assertEqual(plan["dataset_id"], table["tableNameEn"])
            self.assertEqual(plan["metrics"], ["field_2", "field_3", "field_4"])
            self.assertEqual(plan["dimensions"], ["field_1"])
            self.assertEqual(
                [definition["aggregation"] for definition in plan["metric_definitions"]],
                ["sum", "avg", "avg"],
            )
            self.assertTrue(all(
                definition["source"] == "temporary_table_schema"
                for definition in plan["metric_definitions"]
            ))

            class UnexpectedSemanticService:
                def query(self, _request):  # pragma: no cover - must not be called.
                    raise AssertionError("selected CSV must not fall back to semantic service")

            _, handler = build_supersonic_query_skill(UnexpectedSemanticService(), csv_source)
            result = handler(SkillRequest(
                skill_id="supersonic.query",
                context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant:华兴银行"),
                inputs={
                    "question": "分析一下这个数据",
                    "dataset_id": plan["dataset_id"],
                    "metrics": plan["metrics"],
                    "dimensions": plan["dimensions"],
                    "filters": plan["filters"],
                    "limit": 50,
                    "sort_direction": "desc",
                    "context": {
                        "analysis_plan": plan,
                        "selected_raw_table": table,
                    },
                },
            ))

            self.assertEqual(len(result.output["data"]), 2)
            self.assertEqual(result.output["semantic_info"]["data_source"], "tenant_selected_raw_csv")
            self.assertEqual(result.output["semantic_info"]["execution_mode"], "selected_raw_csv")
            self.assertFalse(result.output["semantic_info"]["publishable"])
            self.assertEqual(
                result.output["semantic_info"]["schema_mapping"]["field_labels"],
                {
                    "field_1": "日期",
                    "field_2": "总完件",
                    "field_3": "通过率",
                    "field_4": "户均",
                },
            )
            self.assertEqual(result.output["semantic_info"]["totals"]["field_2"], 30)
            self.assertEqual(result.output["semantic_info"]["totals"]["field_3"], 0.625)
            self.assertEqual(result.output["semantic_info"]["totals"]["field_4"], 15)
            self.assertTrue(result.output["semantic_info"]["source_snapshot"]["content_hash"])
            self.assertIn("temporary_table_schema", str(result.output["semantic_info"]["metric_semantics"]))

            with self.assertRaisesRegex(PermissionError, "selected_csv_not_published_or_not_authorized"):
                handler(SkillRequest(
                    skill_id="supersonic.query",
                    context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant:广州银行"),
                    inputs={
                        "question": "分析一下这个数据",
                        "dataset_id": plan["dataset_id"],
                        "metrics": plan["metrics"],
                        "dimensions": plan["dimensions"],
                        "context": {
                            "analysis_plan": plan,
                            "selected_raw_table": table,
                        },
                    },
                ))

    def test_run_analysis_uses_selected_csv_instead_of_default_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tenant_dir = Path(temp_dir) / "华兴银行"
            tenant_dir.mkdir()
            (tenant_dir / "经营数据.csv").write_text(
                "日期,总完件,通过率,户均\n2026-05-01,10,50%,10\n2026-05-02,20,75%,20\n",
                encoding="utf-8",
            )
            with patch.dict(environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": temp_dir}):
                services = build_local_platform()
            try:
                table = services.data_acquisition_service.csv_source.for_tenant("tenant:华兴银行").table_assets()[0]
                with patch(
                    "backend.platform.intelligent_analysis.engine.call_model_text_completion",
                    return_value={"status": "failed", "error_code": "test_model_disabled"},
                ):
                    response = run_analysis(
                        services,
                        user_id="u_super_admin",
                        tenant_id="tenant:华兴银行",
                        question="分析一下这个数据",
                        page_context={
                            "route": "self-analysis/query",
                            "selected_data_tables": [{"id": table["id"], "code": table["tableNameEn"]}],
                            "analysis_policy": {"resultDelivery": "data_first"},
                        },
                    )
            finally:
                services.close()

            self.assertEqual(response["status"], "review_required")
            self.assertEqual(response["execution_mode"], "real")
            self.assertEqual(response["analysis_plan"]["dataset_id"], table["tableNameEn"])
            self.assertTrue(response["analysis_plan"]["temporary_metric_semantics"])
            self.assertTrue(response["skill_results"][0]["data"])
            semantic_info = response["skill_results"][0]["semantic_info"]
            self.assertEqual(semantic_info["data_source"], "tenant_selected_raw_csv")
            self.assertEqual(semantic_info["schema_mapping"]["field_labels"]["field_1"], "日期")
            self.assertEqual(semantic_info["schema_mapping"]["field_labels"]["field_2"], "总完件")
            self.assertEqual(semantic_info["source_snapshot"]["table_id"], table["id"])
            self.assertFalse(response["skill_results"][0]["evidence"]["publishable"])


if __name__ == "__main__":
    unittest.main()
