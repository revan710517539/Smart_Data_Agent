from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from backend.platform.bootstrap import build_local_platform
from backend.platform.ingestion.repair import ModelAcquisitionRepairGenerator
from backend.platform.ingestion.sandbox import RestrictedRowTransformSandbox


def _verified_connection(connection_id: str = "conn_yushu") -> dict:
    return {
        "id": connection_id,
        "institution": "华兴银行",
        "sourceName": "毓数/智能运营",
        "sourceType": "yushu",
        "apiUrl": "https://data.example.com/api",
        "account": "reader",
        "password": "secret",
        "dataset": "loan_operation_mart",
        "enabled": True,
        "mockEnabled": False,
        "status": "verified",
        "testStatus": "verified",
    }


class DataAcquisitionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()
        self.service = self.services.data_acquisition_service
        self.services.system_config_store.upsert_data_connection("tenant_demo", _verified_connection())
        self.source = self.service.create_source(
            "tenant_demo",
            {
                "source_code": "yushu_operation",
                "source_name": "毓数智能运营系统",
                "source_category": "yushu",
            },
            "u_creator",
        )
        self.version = self.service.create_script_version(
            "tenant_demo",
            {
                "script_code": "pull_loan_operation",
                "script_name": "获取经营主题数据",
                "runtime": "http",
                "source_code": json.dumps(
                    {
                        "query": {
                            "metrics": ["loan_amount"],
                            "dimensions": ["branch_name"],
                            "limit": 1000,
                        }
                    },
                    ensure_ascii=False,
                ),
                "output_schema": {"required": ["branch_name", "loan_amount"]},
            },
            "u_creator",
        )
        self.service.review_script_version(
            "tenant_demo",
            self.version["script_version_id"],
            "approved",
            "u_reviewer",
        )
        self.job = self.service.create_job(
            "tenant_demo",
            {
                "job_code": "job_loan_operation",
                "job_name": "经营主题离线采集",
                "source_system_id": self.source["source_system_id"],
                "script_version_id": self.version["script_version_id"],
                "connection_id": "conn_yushu",
                "target_dataset_id": "loan_operation_mart",
                "topic_table_id": "topic_weekly_branch_rank",
                "trigger_type": "manual",
                "execution_mode": "offline",
                "job_config": {
                    "quality_rules": {
                        "min_rows": 1,
                        "required_columns": ["branch_name", "loan_amount"],
                        "unique_by": ["branch_name"],
                        "max_null_ratio": 0.2,
                    },
                    "freshness_sla_seconds": 3600,
                },
            },
            "u_creator",
        )

    def tearDown(self) -> None:
        self.services.close()

    def _source_response(self, rows: list[dict], *, applied_filters: dict | None = None) -> dict:
        return {
            "result": {
                "rows": rows,
                "output_cursor": {"last_id": "42"},
                "semantic_info": {
                    "applied_filters": applied_filters or {
                        "tenant_id": "tenant_demo",
                        "org_unit_id": "org_shanghai",
                    },
                    "source_snapshot": {
                        "snapshot_id": "snapshot-2026-07-10-01",
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "source_version": "partition-20260710",
                    },
                },
            }
        }

    def test_real_yushu_run_materializes_verified_latest_csv_and_is_idempotent(self) -> None:
        source_client = Mock()
        source_client.query.return_value = self._source_response(
            [
                {"branch_name": "上海分行", "loan_amount": 1280},
                {"branch_name": "广州分行", "loan_amount": 960},
            ]
        )
        with patch("backend.platform.ingestion.service.HTTPJSONSourceClient", return_value=source_client):
            first = self.service.run_job(
                "tenant_demo",
                self.job["acquisition_job_id"],
                "u_creator",
                "idem-1",
                org_unit_id="org_shanghai",
            )
            second = self.service.run_job(
                "tenant_demo",
                self.job["acquisition_job_id"],
                "u_creator",
                "idem-1",
                org_unit_id="org_shanghai",
            )

        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(first["acquisition_run_id"], second["acquisition_run_id"])
        source_client.query.assert_called_once()
        sent = source_client.query.call_args.args[0]
        self.assertEqual(sent["filters"]["tenant_id"], "tenant_demo")
        self.assertEqual(sent["filters"]["org_unit_id"], "org_shanghai")
        latest = self.service.getLatestCsvByTopicTable(
            "topic_weekly_branch_rank",
            "org_shanghai",
            "tenant_demo",
        )
        self.assertEqual(latest["row_count"], 2)
        self.assertIn("上海分行", latest["content"])
        self.assertEqual(len(latest["content_hash"]), 64)
        with self.assertRaises(KeyError):
            self.service.latest_csv("tenant_other", "topic_weekly_branch_rank", "org_shanghai")

    def test_source_must_confirm_tenant_and_org_filters(self) -> None:
        source_client = Mock()
        source_client.query.return_value = self._source_response(
            [{"branch_name": "越权机构", "loan_amount": 999}],
            applied_filters={"tenant_id": "tenant_demo"},
        )
        with patch("backend.platform.ingestion.service.HTTPJSONSourceClient", return_value=source_client):
            run = self.service.run_job(
                "tenant_demo",
                self.job["acquisition_job_id"],
                "u_creator",
                "idem-policy",
                org_unit_id="org_shanghai",
            )
        self.assertEqual(run["status"], "repair_review")
        self.assertEqual(run["error_code"], "source_governance_rejected")
        self.assertEqual(len(self.service.bundle("tenant_demo")["repair_proposals"]), 1)

    def test_llm_repair_candidate_is_validated_hidden_and_requires_four_eyes(self) -> None:
        repaired_source = json.dumps(
            {
                "query": {
                    "metrics": ["loan_amount"],
                    "dimensions": ["branch_name"],
                    "limit": 100,
                }
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        class RepairGenerator:
            def generate(self, tenant_id, failed_version, diagnosis):
                return {
                    "candidate_source_code": repaired_source,
                    "model_call": {
                        "status": "connected",
                        "model_id": "repair-model",
                        "request_hash": "a" * 64,
                        "response_hash": "b" * 64,
                    },
                }

        self.service.repair_generator = RepairGenerator()
        source_client = Mock()
        source_client.query.return_value = self._source_response(
            [{"branch_name": "越权机构", "loan_amount": 999}],
            applied_filters={"tenant_id": "tenant_demo"},
        )
        with patch("backend.platform.ingestion.service.HTTPJSONSourceClient", return_value=source_client):
            run = self.service.run_job(
                "tenant_demo",
                self.job["acquisition_job_id"],
                "u_creator",
                "idem-llm-repair",
                org_unit_id="org_shanghai",
            )
        proposal = run["repair_proposal"]
        self.assertEqual(proposal["generation_method"], "llm")
        self.assertEqual(proposal["review_status"], "pending")
        self.assertNotIn("candidate_source_code", proposal)
        stored = self.services.data_acquisition_store.get_repair_proposal(
            "tenant_demo", proposal["repair_proposal_id"], reveal_candidate=True
        )
        self.assertEqual(stored["candidate_source_code"], repaired_source)
        self.assertEqual(stored["diagnosis"]["model_call"]["model_id"], "repair-model")
        model_calls = self.services.task_repository.model_calls("tenant_demo")
        self.assertEqual(model_calls[0]["subject_type"], "acquisition_repair_proposal")
        self.assertEqual(model_calls[0]["subject_id"], proposal["repair_proposal_id"])
        applied = self.service.review_repair_proposal(
            "tenant_demo", proposal["repair_proposal_id"], "approved", "u_reviewer"
        )
        self.assertEqual(applied["review_status"], "applied")
        self.assertTrue(applied["applied_script_version_id"])

    def test_tenant_system_param_limits_source_query_and_rows(self) -> None:
        self.services.system_config_store.upsert_system_param(
            "tenant_demo",
            {
                "id": "acquisition_max_rows",
                "name": "单次采集最大行数",
                "value": "1",
                "category": "data",
                "description": "test override",
            },
            updated_by="u_admin",
        )
        source_client = Mock()
        source_client.query.return_value = self._source_response(
            [
                {"branch_name": "上海分行", "loan_amount": 1280},
                {"branch_name": "广州分行", "loan_amount": 960},
            ]
        )
        with patch("backend.platform.ingestion.service.HTTPJSONSourceClient", return_value=source_client):
            run = self.service.run_job(
                "tenant_demo",
                self.job["acquisition_job_id"],
                "u_creator",
                "idem-param-limit",
                org_unit_id="org_shanghai",
            )
        self.assertEqual(source_client.query.call_args.args[0]["limit"], 1)
        self.assertEqual(run["status"], "repair_review")
        self.assertEqual(run["error_code"], "source_row_limit_exceeded")

    def test_quality_failure_quarantines_artifact_and_never_becomes_latest(self) -> None:
        source_client = Mock()
        source_client.query.return_value = self._source_response([{"branch_name": "上海分行"}])
        with patch("backend.platform.ingestion.service.HTTPJSONSourceClient", return_value=source_client):
            run = self.service.run_job(
                "tenant_demo",
                self.job["acquisition_job_id"],
                "u_creator",
                "idem-quality",
                org_unit_id="org_shanghai",
            )
        self.assertEqual(run["status"], "repair_review")
        self.assertEqual(run["error_code"], "quality_gate_failed")
        artifact = self.services.data_acquisition_store.get_artifact("tenant_demo", run["output_artifact_id"])
        self.assertEqual(artifact["status"], "quarantined")
        with self.assertRaises(KeyError):
            self.service.latest_csv("tenant_demo", "topic_weekly_branch_rank", "org_shanghai")

    def test_script_review_requires_four_eyes_and_pending_versions_are_unique(self) -> None:
        pending_a = self.service.create_script_version(
            "tenant_demo",
            {
                "script_code": "pending_script",
                "script_name": "待审批脚本",
                "runtime": "http",
                "source_code": '{"query": {}}',
            },
            "u_owner",
        )
        pending_b = self.service.create_script_version(
            "tenant_demo",
            {
                "script_code": "pending_script",
                "script_name": "待审批脚本二版",
                "runtime": "http",
                "source_code": '{"query": {"limit": 10}}',
            },
            "u_owner",
        )
        self.assertEqual((pending_a["version_no"], pending_b["version_no"]), (1, 2))
        with self.assertRaises(PermissionError):
            self.service.review_script_version(
                "tenant_demo",
                pending_a["script_version_id"],
                "approved",
                "u_owner",
            )

    def test_market_source_requires_license_evidence(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_source(
                "tenant_demo",
                {
                    "source_code": "market_unlicensed",
                    "source_name": "无许可市场源",
                    "source_category": "market",
                },
                "u_creator",
            )
        source = self.service.create_source(
            "tenant_demo",
            {
                "source_code": "market_licensed",
                "source_name": "持牌市场数据",
                "source_category": "market",
                "license_metadata": {"license_type": "licensed_feed", "contract_ref": "contract-2026-01"},
            },
            "u_creator",
        )
        self.assertEqual(source["source_category"], "market")

    def test_csv_source_repair_requires_file_update(self) -> None:
        model_store = Mock()
        generator = ModelAcquisitionRepairGenerator(model_store, RestrictedRowTransformSandbox())
        result = generator.generate(
            "tenant_demo",
            {"runtime": "sql", "source_code": "SELECT * FROM loan_fact"},
            {"error_code": "source_execution_failed"},
        )
        self.assertIsNone(result["candidate_source_code"])
        self.assertEqual(result["model_call"]["error_code"], "csv_source_repair_requires_file_update")


if __name__ == "__main__":
    unittest.main()
