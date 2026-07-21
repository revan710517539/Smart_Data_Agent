from __future__ import annotations

import hashlib
import unittest

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform


class MemoryLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()

    def tearDown(self) -> None:
        self.services.close()

    def test_preference_candidate_requires_four_eyes_and_active_subject_scope(self) -> None:
        candidate = self.services.memory_service.create_candidate(
            "tenant_demo",
            {
                "memory_id": "mem_preference",
                "memory_type": "preference",
                "subject_type": "user",
                "title": "图表偏好",
                "content": {"preferred_chart": "line", "reason": "关注时间趋势"},
                "confidence": 0.9,
            },
            "u_creator",
        )
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(self.services.memory_service.list_active("tenant_demo", "u_creator"), [])
        with self.assertRaises(PermissionError):
            self.services.memory_service.review_candidate(
                "tenant_demo", "mem_preference", "approve", "u_creator"
            )
        active = self.services.memory_service.review_candidate(
            "tenant_demo", "mem_preference", "approve", "u_reviewer"
        )
        self.assertEqual(active["status"], "active")
        self.assertEqual(len(self.services.memory_service.list_active("tenant_demo", "u_creator")), 1)
        self.assertEqual(self.services.memory_service.list_active("tenant_demo", "u_other"), [])

    def test_business_fact_cannot_be_approved_without_evidence(self) -> None:
        self.services.memory_service.create_candidate(
            "tenant_demo",
            {
                "memory_id": "mem_fact_without_evidence",
                "memory_type": "business_fact",
                "subject_type": "tenant",
                "title": "无证据事实",
                "content": {"fact": "某机构增长最快"},
                "confidence": 0.9,
            },
            "u_creator",
        )
        with self.assertRaises(ValueError):
            self.services.memory_service.review_candidate(
                "tenant_demo", "mem_fact_without_evidence", "approve", "u_reviewer"
            )

    def test_analysis_candidate_is_not_recalled_until_reviewed(self) -> None:
        first = run_analysis(
            self.services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年6月各分行放款金额排名TOP10",
        )
        self.assertEqual(first["analysis_plan"]["memory_policy"], "active_only")
        self.assertEqual(first["analysis_plan"]["memory_refs"], [])
        candidates = self.services.memory_store.search(
            "tenant_demo", memory_type="analysis_case", statuses=("candidate",)
        )
        self.assertEqual(len(candidates), 1)
        candidate = self.services.memory_store.get("tenant_demo", candidates[0].memory_id)
        self.assertEqual(candidate["evidence_count"], 1)

        second = run_analysis(
            self.services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年6月消费贷放款金额是多少",
        )
        self.assertEqual(second["analysis_plan"]["memory_refs"], [])
        self.services.memory_service.review_candidate(
            "tenant_demo", candidates[0].memory_id, "approve", "u_reviewer"
        )
        third = run_analysis(
            self.services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="2026年6月经营贷放款金额是多少",
        )
        self.assertEqual(third["analysis_plan"]["memory_refs"][0]["memory_id"], candidates[0].memory_id)

    def test_duplicate_content_is_rejected_and_superseding_candidate_retires_old_record(self) -> None:
        evidence_hash = hashlib.sha256(b"evidence").hexdigest()
        payload = {
            "memory_type": "business_fact",
            "subject_type": "tenant",
            "title": "经营事实",
            "content": {"fact": "A"},
            "confidence": 0.9,
            "evidence": {
                "evidence_type": "analysis_evidence",
                "evidence_id": "ev_1",
                "evidence_hash": evidence_hash,
            },
        }
        first = self.services.memory_service.create_candidate(
            "tenant_demo", {**payload, "memory_id": "mem_old"}, "u_creator"
        )
        with self.assertRaises(ValueError):
            self.services.memory_service.create_candidate(
                "tenant_demo", {**payload, "memory_id": "mem_duplicate"}, "u_creator"
            )
        self.services.memory_service.review_candidate(
            "tenant_demo", first["memory_id"], "approve", "u_reviewer"
        )
        replacement = self.services.memory_service.create_candidate(
            "tenant_demo",
            {
                **payload,
                "memory_id": "mem_new",
                "content": {"fact": "B"},
                "supersedes_memory_id": "mem_old",
                "evidence": {**payload["evidence"], "evidence_id": "ev_2"},
            },
            "u_creator",
        )
        self.services.memory_service.review_candidate(
            "tenant_demo", replacement["memory_id"], "approve", "u_reviewer"
        )
        self.assertEqual(self.services.memory_store.get("tenant_demo", "mem_old")["status"], "superseded")
        self.assertEqual(self.services.memory_store.get("tenant_demo", "mem_new")["status"], "active")


if __name__ == "__main__":
    unittest.main()
