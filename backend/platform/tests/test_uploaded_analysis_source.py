from __future__ import annotations

import io
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.intelligent_analysis.uploaded_source import (
    MEDIA_UNSUPPORTED_MESSAGE,
    classify_uploaded_source,
    is_uploaded_analysis_table,
    resolve_uploaded_analysis_sources,
)
from backend.platform.orchestration.workflow import _build_temporary_raw_table_plan
from backend.platform.skills.builtin.supersonic_query import build_supersonic_query_skill
from backend.platform.skills.models import SkillRequest
from backend.platform.tenancy import ExecutionContext


def _xlsx_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class UploadedAnalysisSourceTest(unittest.TestCase):
    def test_excel_with_numbers_is_data_source(self) -> None:
        content = _xlsx_bytes(["机构", "放款金额"], [["三峡银行", 1200], ["广州银行", 800]])
        result = classify_uploaded_source("漏损统计报表.xlsx", content)
        self.assertEqual(result["classification"], "data_source")
        self.assertTrue(is_uploaded_analysis_table(result["table"]))
        self.assertGreaterEqual(int(result["table"]["rowCount"]), 2)
        self.assertTrue(any(field.get("isMetric") for field in result["table"]["fields"]))

    def test_excel_without_numbers_is_text_document(self) -> None:
        content = _xlsx_bytes(["说明", "备注"], [["经营概述", "本月平稳"], ["风险提示", "关注逾期"]])
        result = classify_uploaded_source("经营说明.xlsx", content)
        self.assertEqual(result["classification"], "text_document")
        self.assertIn("经营概述", result["extracted_text"])

    def test_video_is_unsupported(self) -> None:
        result = classify_uploaded_source("纪要.mp4", b"fake-video-bytes", "video/mp4")
        self.assertEqual(result["classification"], "unsupported_media")
        self.assertEqual(result["message"], MEDIA_UNSUPPORTED_MESSAGE)

    def test_plain_text_is_document(self) -> None:
        result = classify_uploaded_source("纪要.txt", "本月放款整体平稳，需关注逾期。".encode("utf-8"))
        self.assertEqual(result["classification"], "text_document")
        self.assertIn("逾期", result["extracted_text"])

    def test_media_only_files_block_analysis(self) -> None:
        sources = resolve_uploaded_analysis_sources({
            "files": [{"name": "会议.mp4", "type": "video/mp4", "classification": "unsupported_media"}],
        })
        self.assertTrue(sources.media_blocked)

    def test_uploaded_table_query_does_not_use_system_catalog(self) -> None:
        content = _xlsx_bytes(["月份", "漏损金额"], [["2026-07", 15], ["2026-08", 21]])
        table = classify_uploaded_source("漏损统计.xlsx", content)["table"]
        plan = _build_temporary_raw_table_plan({}, table, "分析一下上面的数据")

        class UnexpectedSemanticService:
            def query(self, _request):  # pragma: no cover
                raise AssertionError("uploaded file must not query semantic catalog")

        class UnexpectedCsvSource:
            def for_tenant(self, _tenant_id):  # pragma: no cover
                raise AssertionError("uploaded file must not browse tenant raw tables")

        _, handler = build_supersonic_query_skill(UnexpectedSemanticService(), UnexpectedCsvSource())
        result = handler(SkillRequest(
            skill_id="supersonic.query",
            context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant:华兴银行"),
            inputs={
                "question": "分析一下上面的数据",
                "dataset_id": plan["dataset_id"],
                "metrics": plan["metrics"],
                "dimensions": plan["dimensions"],
                "limit": 50,
                "context": {"analysis_plan": plan, "selected_raw_table": table},
            },
        ))
        self.assertEqual(result.output["semantic_info"]["data_source"], "uploaded_file")
        self.assertEqual(result.output["semantic_info"]["execution_mode"], "uploaded_file")
        self.assertEqual(len(result.output["data"]), 2)
        self.assertFalse(result.output["semantic_info"]["publishable"])

    def test_run_analysis_uses_uploaded_excel_instead_of_system_tables(self) -> None:
        content = _xlsx_bytes(["机构", "放款金额"], [["三峡银行", 100], ["广州银行", 40]])
        classified = classify_uploaded_source("漏损统计报表.xlsx", content)
        with tempfile.TemporaryDirectory() as temp_dir:
            tenant_dir = Path(temp_dir) / "华兴银行"
            tenant_dir.mkdir()
            (tenant_dir / "系统表.csv").write_text("机构,放款金额\n系统行,1\n", encoding="utf-8")
            with patch.dict(environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": temp_dir}):
                services = build_local_platform()
            try:
                with patch(
                    "backend.platform.intelligent_analysis.engine.call_model_text_completion",
                    return_value={"status": "failed", "error_code": "test_model_disabled"},
                ):
                    response = run_analysis(
                        services,
                        user_id="u_super_admin",
                        tenant_id="tenant:华兴银行",
                        question="分析一下上面的数据",
                        page_context={
                            "route": "self-analysis/query",
                            "files": [{
                                "name": "漏损统计报表.xlsx",
                                "classification": "data_source",
                                "contentHash": classified["content_hash"],
                                "parsedTable": classified["table"],
                            }],
                            "analysis_policy": {"resultDelivery": "data_first"},
                        },
                    )
            finally:
                services.close()
        semantic = response["skill_results"][0]["semantic_info"]
        self.assertEqual(semantic["data_source"], "uploaded_file")
        self.assertTrue(response["asset_context"]["uploaded_data_source"])
        self.assertEqual(len(response["skill_results"][0]["data"]), 2)
        self.assertNotEqual(response["analysis_plan"]["dataset_id"], "csv_system")

    def test_run_analysis_summarizes_text_document_into_text_chart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tenant_dir = Path(temp_dir) / "华兴银行"
            tenant_dir.mkdir()
            (tenant_dir / "系统表.csv").write_text("机构,放款金额\n系统行,1\n", encoding="utf-8")
            with patch.dict(environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": temp_dir}):
                services = build_local_platform()
            try:
                with patch(
                    "backend.platform.intelligent_analysis.uploaded_source.call_model_text_completion",
                    return_value={"status": "connected", "response_text": "文档认为本月经营平稳。"},
                ), patch(
                    "backend.platform.intelligent_analysis.engine.call_model_text_completion",
                    return_value={"status": "failed", "error_code": "test_model_disabled"},
                ):
                    response = run_analysis(
                        services,
                        user_id="u_super_admin",
                        tenant_id="tenant:华兴银行",
                        question="总结一下这份材料",
                        page_context={
                            "route": "self-analysis/query",
                            "files": [{
                                "name": "经营纪要.txt",
                                "classification": "text_document",
                                "extractedText": "本月经营平稳，逾期略有下降。",
                            }],
                            "analysis_policy": {"resultDelivery": "data_first"},
                        },
                    )
            finally:
                services.close()
        self.assertTrue(response["asset_context"]["uploaded_document_summary"])
        self.assertEqual(response["skill_results"][0]["semantic_info"]["execution_mode"], "uploaded_document_summary")
        self.assertEqual(response["skill_results"][0]["visualization_spec"]["chart_type"], "text")
        self.assertIn("经营平稳", response["intelligent_analysis"]["analysis_summary"])

    def test_run_analysis_rejects_video_only_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tenant_dir = Path(temp_dir) / "华兴银行"
            tenant_dir.mkdir()
            with patch.dict(environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": temp_dir}):
                services = build_local_platform()
            try:
                with self.assertRaises(ValueError) as raised:
                    run_analysis(
                        services,
                        user_id="u_super_admin",
                        tenant_id="tenant:华兴银行",
                        question="分析这个视频",
                        page_context={
                            "route": "self-analysis/query",
                            "files": [{"name": "会议.mp4", "type": "video/mp4", "classification": "unsupported_media"}],
                        },
                    )
            finally:
                services.close()
        self.assertEqual(str(raised.exception), "analysis_uploaded_media_unsupported")


if __name__ == "__main__":
    unittest.main()
