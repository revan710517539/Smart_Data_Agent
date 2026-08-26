from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.platform.ingestion.csv_folder import CSVFolderSource
from backend.platform.knowledge import InMemoryKnowledgeStore
from backend.platform.intelligent_analysis.contracts import (
    ANALYSIS_RESOLUTION_KEY,
    AnalysisContractError,
    bind_plan_field_contract,
    normalize_query_output_contract,
    processing_output_error,
    resolve_analysis_table_reference,
)
from backend.platform.intelligent_analysis.uploaded_source import classify_uploaded_source
from backend.platform.memory import InMemoryMemoryStore
from backend.platform.orchestration.workflow import AnalysisWorkflow
from backend.platform.api.routes.analysis import _build_asset_context, _preflight_analysis_page_context
from backend.platform.skills.builtin.supersonic_query import build_supersonic_query_skill
from backend.platform.skills.models import SkillRequest, SkillResult
from backend.platform.tenancy import ExecutionContext


def _field(code: str, label: str, field_type: str = "string") -> dict:
    return {
        "fieldNameEn": code,
        "fieldNameCn": label,
        "type": field_type,
        "isMetric": field_type in {"integer", "decimal"},
    }


def _table(**overrides) -> dict:
    table = {
        "id": "current_id",
        "assetId": "raw:employee-report-stable",
        "kind": "raw",
        "tableNameEn": "employee_report",
        "tableNameCn": "员工维度报表",
        "sourceKey": "employee-report",
        "relativePath": "20260807_180009_员工维度报表.csv",
        "contentHash": "a" * 64,
        "schemaFingerprint": "schema-v2",
        "fields": [_field("department", "部门"), _field("balance", "余额", "decimal")],
    }
    table.update(overrides)
    return table


HISTORICAL_FIXTURE = Path(__file__).parent / "fixtures" / "analysis" / "huaxing_historical_failures.json"


def _historical_failure_fixture() -> dict:
    return json.loads(HISTORICAL_FIXTURE.read_text(encoding="utf-8"))


class AnalysisContractTest(unittest.TestCase):
    def test_huaxing_redacted_historical_asset_failure_rebinds_by_stable_evidence(self) -> None:
        fixture = _historical_failure_fixture()["asset_reference_failure"]
        common = {
            "assetId": "",
            "kind": "raw",
            "relativePath": fixture["relative_path"],
            "contentHash": f"sha256-prefix:{fixture['content_hash_prefix']}",
            "schemaFingerprint": fixture["schema_fingerprint"],
            "fields": fixture["fields"],
        }
        requested = {**common, "id": fixture["legacy_id"], "sourceKey": fixture["legacy_source_key"]}
        current = {**common, "id": fixture["current_id"], "sourceKey": fixture["current_source_key"]}

        resolved = resolve_analysis_table_reference(requested, [current], tenant_id=fixture["tenant_id"])

        self.assertEqual(resolved.strategy, "path_content_hash")
        self.assertEqual(resolved.table["id"], fixture["current_id"])
        self.assertTrue(resolved.table[ANALYSIS_RESOLUTION_KEY]["serverAuthorized"])

    def test_huaxing_redacted_historical_field_failure_uses_canonical_alias_contract(self) -> None:
        fixture = _historical_failure_fixture()["field_contract_failure"]
        table = _table(fields=fixture["table_fields"])
        plan = bind_plan_field_contract(fixture["analysis_plan"], table)
        with self.assertRaises(AnalysisContractError) as missing_alias:
            normalize_query_output_contract(plan, {
                "data": [fixture["legacy_query_row"]],
                "semantic_info": {"schema_mapping": {}},
            })
        self.assertEqual(missing_alias.exception.stage, "query_output")
        self.assertEqual(
            missing_alias.exception.public_details()["missingFields"][0]["displayName"],
            "当日在贷余额",
        )

        normalized = normalize_query_output_contract(plan, {
            "data": [fixture["legacy_query_row"]],
            "semantic_info": {"schema_mapping": {"field_aliases": fixture["field_aliases"]}},
        })
        self.assertEqual(normalized["data"][0]["loan_balance_current"], 100.0)

    def test_task_start_force_refreshes_and_rebinds_preflight_asset_version(self) -> None:
        first = _table(id="delivery_v1", contentHash="1" * 64, assetVersion="1" * 16)
        second = _table(id="delivery_v2", contentHash="2" * 64, assetVersion="2" * 16)

        class Catalog:
            current = first
            force_calls = 0

            def table_assets(self, *, force: bool = False):
                self.force_calls += int(force)
                return [dict(self.current)]

        catalog = Catalog()
        services = SimpleNamespace(
            data_asset_store=SimpleNamespace(list_published_bundle=lambda _tenant_id: {
                "raw_tables": [], "topic_tables": [], "page_data": [], "intents": [],
                "analysis_experiences": [], "behavior_habits": [], "knowledge_files": [],
            }),
            data_acquisition_service=SimpleNamespace(
                csv_source=SimpleNamespace(for_tenant=lambda _tenant_id: catalog),
            ),
            metric_dictionary_store=None,
            lineage_store=None,
        )
        preflight = _preflight_analysis_page_context(
            services,
            "tenant:华兴银行",
            "分析余额",
            {"selected_data_tables": [first]},
            user_id="user",
        )
        self.assertEqual(preflight["selected_data_tables"][0]["id"], "delivery_v1")
        catalog.current = second

        at_task_start = _build_asset_context(
            services,
            "tenant:华兴银行",
            "分析余额",
            preflight,
            user_id="user",
        )

        self.assertEqual(at_task_start["selected_data_tables"][0]["id"], "delivery_v2")
        self.assertGreaterEqual(catalog.force_calls, 2)
    def test_stable_asset_id_precedes_changed_runtime_identifiers(self) -> None:
        requested = _table(
            id="old_id",
            sourceKey="old-dynamic-source-key",
            relativePath="20260801_180009_员工维度报表.csv",
            contentHash="b" * 64,
        )
        current = _table(id="new_id", sourceKey="new-dynamic-source-key")

        resolved = resolve_analysis_table_reference(requested, [current], tenant_id="tenant:华兴银行")

        self.assertEqual(resolved.strategy, "asset_id")
        self.assertEqual(resolved.table["id"], "new_id")
        self.assertEqual(resolved.table[ANALYSIS_RESOLUTION_KEY]["assetId"], "raw:employee-report-stable")
        self.assertTrue(resolved.version_changed)

    def test_stale_source_key_rebinds_to_current_version(self) -> None:
        requested = _table(
            assetId="",
            id="old_id",
            relativePath="20260801_180009_员工维度报表.csv",
            contentHash="b" * 64,
            schemaFingerprint="schema-v1",
        )
        resolved = resolve_analysis_table_reference(requested, [_table()], tenant_id="tenant:华兴银行")

        self.assertEqual(resolved.strategy, "source_key")
        self.assertEqual(resolved.table["id"], "current_id")
        self.assertEqual(resolved.table[ANALYSIS_RESOLUTION_KEY]["tenantId"], "tenant:华兴银行")
        self.assertTrue(resolved.table[ANALYSIS_RESOLUTION_KEY]["serverAuthorized"])

    def test_schema_change_reports_missing_canonical_fields(self) -> None:
        requested = _table(
            schemaFingerprint="schema-v1",
            fields="department(部门:string), balance(当日在贷余额:decimal)",
            fieldLabels={"department": "部门", "balance": "当日在贷余额"},
        )
        current = _table(fields=[_field("department", "部门")])

        with self.assertRaises(AnalysisContractError) as raised:
            resolve_analysis_table_reference(requested, [current], tenant_id="tenant:华兴银行")

        self.assertEqual(raised.exception.code, "analysis_table_schema_changed")
        self.assertEqual(raised.exception.stage, "asset_resolution")
        self.assertEqual(raised.exception.public_details()["missingFields"][0]["canonicalId"], "balance")

    def test_schema_change_rejects_type_and_physical_name_changes_but_allows_additive_fields(self) -> None:
        requested = _table(schemaFingerprint="schema-v1")
        type_changed = _table(
            schemaFingerprint="schema-v2",
            fields=[_field("department", "部门"), _field("balance", "余额", "string")],
        )
        with self.assertRaises(AnalysisContractError) as raised_type:
            resolve_analysis_table_reference(requested, [type_changed], tenant_id="tenant:华兴银行")
        self.assertEqual(raised_type.exception.public_details()["fieldDifferences"][0]["change"], "field_type_changed")

        physical_changed = _table(
            schemaFingerprint="schema-v3",
            fields=[_field("department", "部门"), _field("balance", "当日在贷余额", "decimal")],
        )
        with self.assertRaises(AnalysisContractError) as raised_physical:
            resolve_analysis_table_reference(requested, [physical_changed], tenant_id="tenant:华兴银行")
        self.assertEqual(raised_physical.exception.public_details()["fieldDifferences"][0]["change"], "physical_name_changed")

        additive = _table(
            schemaFingerprint="schema-v4",
            fields=[*requested["fields"], _field("employee_count", "员工数", "integer")],
        )
        resolved = resolve_analysis_table_reference(requested, [additive], tenant_id="tenant:华兴银行")
        self.assertEqual(resolved.table["schemaFingerprint"], "schema-v4")

    def test_title_only_and_cross_tenant_references_fail_closed(self) -> None:
        with self.assertRaisesRegex(AnalysisContractError, "analysis_table_unavailable"):
            resolve_analysis_table_reference(
                {"id": "old", "kind": "raw", "name": "员工维度报表"},
                [_table()],
                tenant_id="tenant:华兴银行",
            )

    def test_exact_content_evidence_precedes_compatible_code_and_ambiguity_fails_closed(self) -> None:
        requested = _table(id="old", sourceKey="", code="employee_report")
        wrong_code_match = _table(
            id="wrong",
            sourceKey="wrong-source",
            code="employee_report",
            relativePath="other.csv",
            contentHash="b" * 64,
        )
        exact_content_match = _table(
            id="exact",
            sourceKey="exact-source",
            code="other_code",
        )
        resolved = resolve_analysis_table_reference(
            requested,
            [wrong_code_match, exact_content_match],
            tenant_id="tenant:华兴银行",
        )
        self.assertEqual(resolved.strategy, "path_content_hash")
        self.assertEqual(resolved.table["id"], "exact")

        with self.assertRaisesRegex(AnalysisContractError, "analysis_table_unavailable"):
            resolve_analysis_table_reference(
                {**requested, "relativePath": "unknown.csv"},
                [
                    {**exact_content_match, "id": "duplicate-a", "relativePath": "a.csv"},
                    {**exact_content_match, "id": "duplicate-b", "relativePath": "b.csv"},
                ],
                tenant_id="tenant:华兴银行",
            )

    def test_raw_table_content_hash_alone_cannot_cross_relative_paths(self) -> None:
        requested = _table(
            assetId="",
            id="old",
            sourceKey="",
            relativePath="archive/员工维度报表.csv",
        )
        same_bytes_different_path = _table(
            assetId="",
            id="current",
            sourceKey="",
            relativePath="current/员工维度报表.csv",
        )

        with self.assertRaisesRegex(AnalysisContractError, "analysis_table_unavailable"):
            resolve_analysis_table_reference(
                requested,
                [same_bytes_different_path],
                tenant_id="tenant:华兴银行",
            )

    def test_retired_and_foreign_catalog_entries_have_distinct_errors(self) -> None:
        with self.assertRaisesRegex(AnalysisContractError, "analysis_table_retired"):
            resolve_analysis_table_reference(
                _table(),
                [{**_table(), "lifecycleStatus": "retired"}],
                tenant_id="tenant:华兴银行",
            )
        with self.assertRaisesRegex(AnalysisContractError, "analysis_table_tenant_mismatch"):
            resolve_analysis_table_reference(
                _table(),
                [{**_table(), "tenantId": "tenant:其他银行"}],
                tenant_id="tenant:华兴银行",
            )
        with self.assertRaisesRegex(AnalysisContractError, "analysis_table_tenant_mismatch"):
            resolve_analysis_table_reference(
                {**_table(), "tenantId": "tenant:其他银行"},
                [_table()],
                tenant_id="tenant:华兴银行",
            )

    def test_query_alias_is_normalized_only_when_provider_declares_it(self) -> None:
        plan = bind_plan_field_contract(
            {"dimensions": ["department"], "metrics": ["balance"], "metric_definitions": []},
            _table(),
        )
        output = normalize_query_output_contract(
            plan,
            {
                "data": [{"department": "零售部", "total_balance": 10}],
                "semantic_info": {"schema_mapping": {"field_aliases": {"balance": "total_balance"}}},
            },
        )
        self.assertEqual(output["data"][0]["balance"], 10)
        self.assertEqual(
            output["semantic_info"]["schema_mapping"]["normalized_aliases"],
            {"balance": "total_balance"},
        )

    def test_missing_query_and_processing_fields_report_exact_stage(self) -> None:
        plan = bind_plan_field_contract(
            {"dimensions": ["department"], "metrics": ["balance"], "metric_definitions": []},
            _table(),
        )
        with self.assertRaises(AnalysisContractError) as query_error:
            normalize_query_output_contract(
                plan,
                {"data": [{"department": "零售部", "total_balance": 10}], "semantic_info": {}},
            )
        self.assertEqual(query_error.exception.stage, "query_output")
        self.assertEqual(query_error.exception.public_details()["availableFields"], ["department", "total_balance"])

        processing_error = processing_output_error(plan, [{"department": "零售部"}], ["balance"])
        self.assertEqual(processing_error.stage, "data_processing_output")
        self.assertEqual(processing_error.public_details()["missingFields"][0]["displayName"], "余额")

    def test_empty_query_result_still_validates_declared_output_fields(self) -> None:
        plan = bind_plan_field_contract(
            {"dimensions": ["department"], "metrics": ["balance"], "metric_definitions": []},
            _table(),
        )
        normalized = normalize_query_output_contract(
            plan,
            {
                "data": [],
                "semantic_info": {
                    "schema_mapping": {"output_fields": ["department", "balance"]},
                },
            },
        )
        self.assertEqual(
            normalized["semantic_info"]["schema_mapping"]["output_fields"],
            ["balance", "department"],
        )

        with self.assertRaises(AnalysisContractError) as missing_output:
            normalize_query_output_contract(
                plan,
                {
                    "data": [],
                    "semantic_info": {"schema_mapping": {"output_fields": ["department"]}},
                },
            )
        self.assertEqual(missing_output.exception.stage, "query_output")
        self.assertEqual(
            missing_output.exception.public_details()["missingFields"][0]["canonicalId"],
            "balance",
        )

    def test_uploaded_schema_fingerprint_is_independent_from_row_content(self) -> None:
        first = classify_uploaded_source("员工.csv", "部门,余额\n零售部,10\n".encode(), "text/csv")
        second = classify_uploaded_source("员工.csv", "部门,余额\n公司部,20\n".encode(), "text/csv")

        self.assertNotEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(first["table"]["schemaFingerprint"], second["table"]["schemaFingerprint"])

    def test_pinned_task_reads_exact_delivery_after_catalog_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / "20260807_180009_员工维度报表.csv"
            old_path.write_text("部门,余额\n零售部,10\n", encoding="utf-8")
            tenant_source = CSVFolderSource(root)
            old_table = tenant_source.table_assets(force=True)[0]
            selected = resolve_analysis_table_reference(old_table, [old_table], tenant_id="tenant:华兴银行").table

            (root / "20260808_180009_员工维度报表.csv").write_text(
                "部门,余额\n公司部,99\n",
                encoding="utf-8",
            )
            latest = tenant_source.table_assets(force=True)[0]
            self.assertNotEqual(latest["contentHash"], old_table["contentHash"])

            metric = next(field["fieldNameEn"] for field in old_table["fields"] if field["isMetric"])
            dimension = next(field["fieldNameEn"] for field in old_table["fields"] if not field["isMetric"])
            _spec, handler = build_supersonic_query_skill(
                SimpleNamespace(),
                SimpleNamespace(for_tenant=lambda _tenant_id: tenant_source),
            )
            result = handler(
                SkillRequest(
                    skill_id="supersonic.query",
                    context=ExecutionContext(user_id="user", tenant_id="tenant:华兴银行"),
                    inputs={
                        "question": "分析余额",
                        "dataset_id": old_table["tableNameEn"],
                        "metrics": [metric],
                        "dimensions": [dimension],
                        "filters": {},
                        "limit": 20,
                        "sort_direction": "desc",
                        "context": {"analysis_plan": {"metrics": [metric]}, "selected_raw_table": selected},
                    },
                )
            )

            self.assertEqual(result.output["semantic_info"]["source_snapshot"]["content_hash"], old_table["contentHash"])
            self.assertEqual(result.output["data"][0][metric], 10.0)

            old_path.write_text("部门,余额\n零售部,11\n", encoding="utf-8")
            with self.assertRaisesRegex(AnalysisContractError, "analysis_table_version_outdated"):
                handler(
                    SkillRequest(
                        skill_id="supersonic.query",
                        context=ExecutionContext(user_id="user", tenant_id="tenant:华兴银行"),
                        inputs={
                            "question": "分析余额",
                            "dataset_id": old_table["tableNameEn"],
                            "metrics": [metric],
                            "dimensions": [dimension],
                            "filters": {},
                            "limit": 20,
                            "sort_direction": "desc",
                            "context": {"analysis_plan": {"metrics": [metric]}, "selected_raw_table": selected},
                        },
                    )
                )

    def test_model_sql_field_failure_retries_once_without_model_sql(self) -> None:
        class Executor:
            def __init__(self) -> None:
                self.calls: list[SkillRequest] = []

            def execute(self, request: SkillRequest) -> SkillResult:
                self.calls.append(request)
                retry = len(self.calls) == 2
                row = {
                    "branch_name": "华东分行",
                    "product_line": "经营贷",
                    "drawdown_rate": 0.6,
                    ("loan_amount" if retry else "total_balance"): 100,
                }
                return SkillResult(
                    skill_id=request.skill_id,
                    output={
                        "sql": "SELECT governed fields",
                        "parameters": {},
                        "data": [row],
                        "chart_spec": {"type": "column", "x": "branch_name", "y": "loan_amount"},
                        "semantic_info": {
                            "policy_enforced_at_source": True,
                            "schema_mapping": {},
                            "totals": {"loan_amount": 100, "drawdown_rate": 0.6},
                        },
                    },
                )

        executor = Executor()
        knowledge = InMemoryKnowledgeStore()
        memory = InMemoryMemoryStore()
        self.addCleanup(knowledge.close)
        self.addCleanup(memory.close)
        workflow = AnalysisWorkflow(executor, knowledge, memory)
        task = workflow.run(
            ExecutionContext(user_id="user", tenant_id="tenant:华兴银行", page_context={}),
            "分析贷款余额",
            planning_hook=lambda _plan: {"sql": "SELECT total_balance FROM governed_view"},
        )

        self.assertEqual(len(executor.calls), 2)
        first_context = executor.calls[0].inputs["context"]
        retry_context = executor.calls[1].inputs["context"]
        self.assertTrue(first_context["model_sql_candidate"])
        self.assertEqual(retry_context["model_sql_candidate"], "")
        self.assertEqual(retry_context["field_contract_retry"], 1)
        self.assertEqual(
            task.skill_results[0]["semantic_info"]["field_contract_recovery"]["attempts"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
