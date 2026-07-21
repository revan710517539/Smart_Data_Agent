from __future__ import annotations

import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.platform.bootstrap import build_local_platform
from backend.platform.knowledge import KnowledgeDocument


class KnowledgeLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()

    def tearDown(self) -> None:
        self.services.close()

    def test_candidate_is_not_searchable_until_four_eyes_approval_and_citation_is_stable(self) -> None:
        document = self.services.knowledge_service.create_text_document(
            "tenant_demo",
            {
                "document_id": "kd_growth_rule",
                "title": "经营增长质量规则",
                "content": "规模增长必须同时校验转化率和M1逾期率，不能只看放款金额。",
                "document_type": "business_rule",
                "domains": ["loan", "risk"],
                "tags": ["增长质量", "M1逾期率"],
            },
            "u_creator",
        )
        self.assertEqual(document["status"], "review")
        self.assertEqual(self.services.knowledge_store.search("增长质量", tenant_id="tenant_demo"), [])
        with self.assertRaises(PermissionError):
            self.services.knowledge_service.review_document("tenant_demo", "kd_growth_rule", "approve", "u_creator")

        published = self.services.knowledge_service.review_document(
            "tenant_demo", "kd_growth_rule", "approve", "u_reviewer"
        )
        self.assertEqual(published["status"], "active")
        hit = self.services.knowledge_store.search("增长质量 M1逾期率", tenant_id="tenant_demo")[0]
        self.assertEqual(hit.document.doc_id, "kd_growth_rule")
        self.assertTrue(hit.chunk_id)
        first = self.services.knowledge_store.create_citation(
            "tenant_demo", hit, "analysis_task", "task_1", "u_analyst"
        )
        second = self.services.knowledge_store.create_citation(
            "tenant_demo", hit, "analysis_task", "task_1", "u_analyst"
        )
        self.assertEqual(first["citation_id"], second["citation_id"])
        self.assertEqual(len(first["quote_hash"]), 64)

    def test_text_file_is_scanned_parsed_chunked_and_staged_for_review(self) -> None:
        result = self.services.knowledge_service.upload_document(
            "tenant_demo",
            {
                "document_id": "kd_uploaded_manual",
                "file_name": "经营手册.md",
                "title": "经营手册",
                "content_base64": base64.b64encode("经营贷续贷需要关注行业风险和动支节奏。".encode()).decode(),
                "document_type": "manual",
            },
            "u_creator",
        )
        self.assertEqual(result["scan"]["status"], "clean")
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["document"]["status"], "review")
        self.assertEqual(result["artifact"]["status"], "active")
        self.assertEqual(result["attachment"]["processing_status"], "ready")
        self.assertEqual(self.services.knowledge_store.search("续贷", tenant_id="tenant_demo"), [])
        self.services.knowledge_service.review_document(
            "tenant_demo", "kd_uploaded_manual", "approve", "u_reviewer"
        )
        hits = self.services.knowledge_store.search("行业风险 动支节奏", tenant_id="tenant_demo")
        self.assertEqual(hits[0].document.doc_id, "kd_uploaded_manual")

    def test_infected_file_is_quarantined_and_never_creates_searchable_document(self) -> None:
        eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        result = self.services.knowledge_service.upload_document(
            "tenant_demo",
            {
                "document_id": "kd_infected",
                "file_name": "infected.txt",
                "content_base64": base64.b64encode(eicar).decode(),
            },
            "u_creator",
        )
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["artifact"]["status"], "quarantined")
        self.assertEqual(result["attachment"]["scan_status"], "infected")
        with self.assertRaises(KeyError):
            self.services.knowledge_store.get_document("tenant_demo", "kd_infected")

    def test_scanned_image_uses_configured_ocr_and_stays_unpublished_until_review(self) -> None:
        class OCR:
            def extract(self, content: bytes, content_type: str):
                self.last_content_type = content_type
                return "扫描件识别结果：经营贷需要关注还款来源。", "ocr:test-engine"

        ocr = OCR()
        self.services.knowledge_service.ocr_extractor = ocr
        image = b"\x89PNG\r\n\x1a\n" + b"scanned-document"
        result = self.services.knowledge_service.upload_document(
            "tenant_demo",
            {
                "document_id": "kd_scanned_image",
                "file_name": "扫描制度.png",
                "title": "扫描制度",
                "content_base64": base64.b64encode(image).decode(),
                "document_type": "policy",
            },
            "u_creator",
        )
        self.assertEqual(ocr.last_content_type, "image/png")
        self.assertEqual(result["attachment"]["processing_status"], "ready")
        self.assertEqual(result["document"]["status"], "review")
        self.assertEqual(self.services.knowledge_store.search("还款来源", tenant_id="tenant_demo"), [])
        self.services.knowledge_service.review_document(
            "tenant_demo", "kd_scanned_image", "approve", "u_reviewer"
        )
        self.assertEqual(
            self.services.knowledge_store.search("还款来源", tenant_id="tenant_demo")[0].document.doc_id,
            "kd_scanned_image",
        )

    def test_scanned_image_without_ocr_is_failed_not_left_processing(self) -> None:
        self.services.knowledge_service.ocr_extractor = None
        image = b"\x89PNG\r\n\x1a\n" + b"scanned-document"
        with self.assertRaisesRegex(RuntimeError, "ocr_provider_required"):
            self.services.knowledge_service.upload_document(
                "tenant_demo",
                {
                    "document_id": "kd_scanned_missing_ocr",
                    "file_name": "扫描制度.png",
                    "title": "扫描制度",
                    "content_base64": base64.b64encode(image).decode(),
                },
                "u_creator",
            )
        attachment = self.services.knowledge_store._conn.execute(
            "SELECT processing_status, processing_error FROM platform_file_attachments WHERE resource_id = ?",
            ("kd_scanned_missing_ocr",),
        ).fetchone()
        self.assertEqual(attachment["processing_status"], "failed")
        self.assertEqual(attachment["processing_error"], "ocr_provider_required_for_scanned_document")

    def test_report_image_is_stored_as_authorized_attachment_not_inline_base64(self) -> None:
        image = b"\x89PNG\r\n\x1a\n" + b"safe-image-payload"
        result = self.services.knowledge_service.upload_report_image(
            "tenant_demo",
            {
                "file_name": "经营趋势.png",
                "content_base64": base64.b64encode(image).decode(),
                "report_id": "shanghai",
                "block_id": "next_plan",
            },
            "u_admin",
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["attachment"]["resource_type"], "weekly_report_image")
        self.assertEqual(result["artifact"]["content_type"], "image/png")
        self.assertNotIn("content_base64", result)
        metadata, stored = self.services.knowledge_service.get_report_image_content(
            "tenant_demo", result["attachment"]["attachment_id"]
        )
        self.assertEqual(stored, image)
        self.assertEqual(metadata["artifact"]["content_hash"], result["artifact"]["content_hash"])
        with self.assertRaises(ValueError):
            self.services.knowledge_service.upload_report_image(
                "tenant_demo",
                {
                    "file_name": "伪造图片.png",
                    "content_base64": base64.b64encode(b"<svg onload=alert(1)>").decode(),
                    "report_id": "shanghai",
                    "block_id": "next_plan",
                },
                "u_admin",
            )

    def test_normalized_knowledge_survives_restart_without_legacy_overwrite(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            first = build_local_platform(db_path)
            try:
                first.knowledge_store.create_document(
                    "tenant_demo",
                    {
                        "document_id": "kd_persistent",
                        "title": "持久化知识",
                        "content": "持久化知识用于验证重启后仍保持版本和发布状态。",
                    },
                    "u_creator",
                )
                first.knowledge_store.review_document("tenant_demo", "kd_persistent", "approve", "u_reviewer")
            finally:
                first.close()
            second = build_local_platform(db_path)
            try:
                hits = second.knowledge_store.search("持久化知识", tenant_id="tenant_demo")
                self.assertEqual(hits[0].document.doc_id, "kd_persistent")
                self.assertEqual(hits[0].document.version_no, 1)
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
