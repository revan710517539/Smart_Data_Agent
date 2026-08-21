import http.client
import base64
import hashlib
import hmac
import json
import sqlite3
import re
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib import request as urllib_request
from urllib.parse import quote
from unittest.mock import patch

from backend.platform.api.routes import run_analysis
from backend.platform.api.routes.analysis import _resolve_selected_model
from backend.platform.api.routes import DELETE_ROUTE_HANDLERS, GET_ROUTE_HANDLERS, POST_ROUTE_HANDLERS, PUT_ROUTE_HANDLERS
from backend.platform.api.router import API_ROUTE_REGISTRY
from backend.platform.api.server import create_server
from backend.platform.application import ApplicationActionUnavailable, SQLiteApplicationStore, UnsupportedApplicationAction
from backend.platform.bootstrap import build_local_platform, build_supersonic_client_from_env
from backend.authz import SUPER_ADMIN_ROLE_ID, normalize_tenant_id, tenant_role_id
from backend.authz.models import PermissionPolicy, Role, RoleAssignment, RoleLevel
from backend.platform.data_access import JSONDataWarehouse, SQLDataWarehouse
from backend.platform.data_processing import PythonSandbox
from backend.platform.governance import approval_input_hash
from backend.platform.security import make_session_token, verify_session_token
from backend.platform.security.secrets import SecretConfigurationError, decrypt_secret, encrypt_secret
from backend.platform.mcp import MCPGateway, MCPServerSpec, MCPToolCall, MCPToolResult
from backend.platform.semantic import (
    FallbackSupersonicClient,
    InMemorySupersonicClient,
    SemanticQueryRequest,
    SupersonicHTTPClient,
)
from backend.platform.tenancy import ExecutionContext
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse, build_governed_test_warehouse

TEST_DEVELOPMENT_LOGIN_PASSWORD = "test-only-explicit-login-secret"


def _stateful_test_token(server, user_id: str, tenant_id: str, tenant_ids: tuple[str, ...] | None = None) -> str:
    grant = server.services.session_store.issue(
        user_id,
        tenant_id,
        tenant_ids or (tenant_id,),
        access_ttl_seconds=300,
        idle_timeout_seconds=600,
        absolute_timeout_seconds=3600,
    )
    return make_session_token(
        user_id,
        tenant_id,
        tenant_ids=grant.tenant_ids,
        secret="test-secret",
        ttl_seconds=grant.access_expires_at - grant.issued_at,
        issued_at=grant.issued_at,
        session_id=grant.access_jti,
        device_session_id=grant.device_session_id,
    )


class FakeSupersonicHandler(BaseHTTPRequestHandler):
    last_payload: dict | None = None

    def do_POST(self) -> None:
        content_length = int(self.headers.get("content-length") or "0")
        FakeSupersonicHandler.last_payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        response = {
            "result": {
                "sql": "select branch_name, sum(loan_amount) as metric_value from remote_semantic where tenant_id = :tenant_id group by branch_name",
                "parameters": {"tenant_id": FakeSupersonicHandler.last_payload["tenant_id"]},
                "rows": [{"branch_name": "远程分行", "metric_value": 99}],
                "chartSpec": {"type": "bar", "x": "branch_name", "y": "metric_value"},
                "semanticInfo": {"dataset_id": "remote_semantic", "policy_enforced_at_source": True},
            }
        }
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


class BrokenSupersonicClient:
    def query(self, request: SemanticQueryRequest):
        raise RuntimeError("remote semantic service down")


class PlatformWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.login_password_environment = patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD": TEST_DEVELOPMENT_LOGIN_PASSWORD},
        )
        self.login_password_environment.start()
        self.services = build_local_platform()
        attach_governed_test_warehouse(self.services)

    def tearDown(self) -> None:
        try:
            self.services.close()
        finally:
            self.login_password_environment.stop()

    def approved_mcp_call(self, subject_id: str, arguments: dict, user_id: str = "u_super_admin") -> str:
        approval = self.services.approval_store.request(
            "tenant_demo",
            "mcp",
            subject_id,
            "execute",
            approval_input_hash(arguments),
            user_id,
        )
        self.services.approval_store.review(
            "tenant_demo", approval["approval_id"], "u_reviewer", "approved"
        )
        return approval["approval_id"]

    def test_analysis_uses_governed_skill_and_semantic_layer(self) -> None:
        response = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="2026年6月各分行放款金额是多少",
        )

        self.assertEqual(response["task_type"], "simple_metric_query")
        self.assertEqual(response["plan"][0]["agent"], "PlannerAgent")
        plan_agents = [step["agent"] for step in response["plan"]]
        self.assertIn("MemoryAgent", plan_agents)
        self.assertIn("DataQueryAgent", plan_agents)
        self.assertIn("VisualizationAgent", plan_agents)
        self.assertIn("sql", response["skill_results"][0])
        self.assertIn("parameters", response["skill_results"][0])
        self.assertIn("semantic_info", response["skill_results"][0])
        self.assertIn("python_script", response["skill_results"][0])
        self.assertEqual(response["skill_results"][0]["visualization_artifact"]["runtime"], "local_python_sandbox")
        self.assertTrue(response["skill_results"][0]["visualization_artifact"]["series"])
        self.assertEqual(response["skill_results"][0]["semantic_info"]["data_source"], "governed_test_warehouse")
        self.assertIn("metric_access", response["skill_results"][0]["semantic_info"])
        self.assertIn("analysis_plan", response)
        self.assertEqual(response["analysis_plan"]["metrics"][0], "loan_amount")
        self.assertNotIn("tenant_demo", response["skill_results"][0]["sql"])
        self.assertEqual(response["skill_results"][0]["parameters"]["tenant_id"], "tenant_demo")
        self.assertEqual(response["knowledge_refs"][0]["doc_id"], "kd_metric_loan_amount")
        self.assertTrue(response["conclusions"])
        self.assertEqual(response["review"]["status"], "passed")
        self.assertTrue(response["review"]["checks"]["python_visualization_ready"])
        self.assertIsNotNone(self.services.task_repository.get_task(response["task_id"]))

        memory_records = self.services.memory_store.search("tenant_demo", memory_type="analysis_case")
        self.assertEqual(len(memory_records), 1)
        runtime_summary = self.services.task_repository.runtime_summary()
        self.assertEqual(runtime_summary["ok_count"], 1)
        self.assertEqual(runtime_summary["last_status"], "ok")

        span_names = [span.name for span in self.services.trace_recorder.spans()]
        self.assertIn("api.analysis.start", span_names)
        self.assertIn("skill.execute.start", span_names)
        self.assertIn("supersonic.schema_mapping", span_names)
        self.assertIn("supersonic.sql_execution", span_names)
        self.assertIn("api.analysis.finish", span_names)

    def test_analysis_preserves_selected_model_context(self) -> None:
        self.services.system_config_store.upsert_model(
            "tenant_demo",
            {
                "id": "model_test",
                "name": "测试分析模型",
                "modelName": "finance-test-model",
                "key": "https://example.local/v1",
                "value": "demo-key",
                "status": "available",
            },
            updated_by="u_super_admin",
        )
        response = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="2026年7月各分行放款金额排名TOP10",
            page_context={
                "selected_model": {
                    "id": "model_test",
                    "name": "客户端伪造名称",
                    "key": "https://attacker.invalid/v1",
                    "value": "client-secret-must-be-ignored",
                }
            },
        )

        self.assertEqual(
            response["intelligent_analysis"]["context"]["model"]["name"],
            "测试分析模型",
        )
        self.assertNotIn("value", response["skill_results"][0]["intelligent_analysis"]["context"]["model"])
        self.assertEqual(
            response["skill_results"][0]["intelligent_analysis"]["context"]["model"]["modelName"],
            "finance-test-model",
        )
        self.assertEqual(response["intelligent_analysis"]["model_invocation"]["status"], "mock")
        model_calls = self.services.task_repository.model_calls("tenant_demo")
        self.assertEqual(len(model_calls), 2)
        self.assertEqual({item["subject_type"] for item in model_calls}, {"analysis_planning", "analysis_task"})
        self.assertTrue(all(item["model_integration_id"] == "model_test" for item in model_calls))
        self.assertTrue(all(item["status"] == "degraded" for item in model_calls))
        self.assertTrue(all(len(item["request_hash"]) == 64 for item in model_calls))
        self.assertNotIn("client-secret-must-be-ignored", json.dumps(model_calls))
        self.assertNotIn("attacker.invalid", json.dumps(model_calls))

    def test_analysis_resolves_registered_submodel_without_trusting_client_connection(self) -> None:
        self.services.system_config_store.upsert_model(
            "tenant_demo",
            {
                "id": "model_gpt_relay",
                "name": "GPT",
                "modelName": "中转站",
                "key": "https://relay.example/v1",
                "value": "stored-secret",
                "availableModels": ["gpt-5.4", "gpt-5.5"],
                "enabledModels": ["gpt-5.4", "gpt-5.5"],
                "status": "available",
            },
            updated_by="u_super_admin",
        )
        resolved = _resolve_selected_model(
            self.services,
            "tenant_demo",
            {
                "selected_model": {
                    "id": "model_gpt_relay::gpt-5.5",
                    "selectedModelName": "gpt-5.5",
                    "key": "https://attacker.invalid/v1",
                    "value": "client-secret",
                }
            },
        )
        self.assertEqual(resolved["id"], "model_gpt_relay")
        self.assertEqual(resolved["enabledModels"], ["gpt-5.5"])
        self.assertEqual(resolved["availableModels"], ["gpt-5.5"])
        self.assertEqual(resolved["selectedModelName"], "gpt-5.5")
        self.assertTrue(resolved["strictModelSelection"])
        self.assertEqual(resolved["key"], "https://relay.example/v1")
        self.assertEqual(resolved["value"], "stored-secret")
        with self.assertRaises(PermissionError):
            _resolve_selected_model(
                self.services,
                "tenant_demo",
                {"selected_model": {"id": "model_gpt_relay", "selectedModelName": "gpt-unregistered"}},
            )

    def test_application_module_allows_multiple_models_and_validates_selection(self) -> None:
        first = {
            "id": "model_direct_client_choice", "name": "客户端选择模型", "modelName": "中转站",
            "key": "https://first.example/v1", "value": "first-secret",
            "availableModels": ["first-model"], "enabledModels": ["first-model"],
            "testStatus": "connected", "status": "available",
        }
        routed = {
            "id": "model_application_route", "name": "应用模块模型", "modelName": "中转站",
            "key": "https://routed.example/v1", "value": "routed-secret",
            "availableModels": ["routed-model"], "enabledModels": ["routed-model"],
            "applicationModule": "intelligent_analysis_reasoning",
            "testStatus": "connected", "status": "available",
        }
        self.services.system_config_store.upsert_model("account:u_super_admin", first, updated_by="u_super_admin")
        self.services.system_config_store.upsert_model("account:u_super_admin", routed, updated_by="u_super_admin")
        resolved = _resolve_selected_model(
            self.services,
            "account:u_super_admin",
            {
                "model_application_module": "intelligent_analysis_reasoning",
                "selected_model": {"id": "model_direct_client_choice"},
            },
            user_id="u_super_admin",
        )
        self.assertEqual(resolved["id"], "model_application_route")
        self.assertEqual(resolved["value"], "routed-secret")

        self.services.system_config_store.upsert_model(
            "account:u_super_admin",
            {**first, "applicationModule": "intelligent_analysis_reasoning"},
            updated_by="u_super_admin",
        )
        listed = {item["id"]: item for item in self.services.system_config_store.list_models("account:u_super_admin")}
        self.assertEqual(listed["model_direct_client_choice"]["applicationModule"], "intelligent_analysis_reasoning")
        self.assertEqual(listed["model_application_route"]["applicationModule"], "intelligent_analysis_reasoning")

        selected = _resolve_selected_model(
            self.services,
            "tenant_demo",
            {
                "model_application_module": "intelligent_analysis_reasoning",
                "model_application_selection": {
                    "integrationId": "model_direct_client_choice",
                    "selectedModelName": "first-model",
                },
            },
            user_id="u_super_admin",
        )
        self.assertEqual(selected["id"], "model_direct_client_choice")
        self.assertEqual(selected["selectedModelName"], "first-model")
        self.assertTrue(selected["strictModelSelection"])

        with self.assertRaises(PermissionError):
            _resolve_selected_model(
                self.services,
                "tenant_demo",
                {
                    "model_application_module": "intelligent_analysis_reasoning",
                    "model_application_selection": {
                        "integrationId": "missing-model",
                        "selectedModelName": "first-model",
                    },
                },
                user_id="u_super_admin",
            )
        with self.assertRaises(PermissionError):
            _resolve_selected_model(
                self.services,
                "tenant_demo",
                {
                    "model_application_module": "intelligent_analysis_reasoning",
                    "model_application_selection": {
                        "integrationId": "model_direct_client_choice",
                        "selectedModelName": "disabled-model",
                    },
                },
                user_id="u_super_admin",
            )

    def test_analysis_history_delete_is_owner_scoped_and_removes_trace(self) -> None:
        response = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="本月各分行放款金额排名TOP10",
        )
        task_id = response["task_id"]
        trace_id = response["trace_id"]
        self.assertTrue(self.services.task_repository.trace_spans(trace_id))
        self.assertFalse(self.services.task_repository.delete_task("tenant_demo", "u_other", task_id))
        self.assertIsNotNone(self.services.task_repository.get_task(task_id))
        self.assertTrue(self.services.task_repository.delete_task("tenant_demo", "u_super_admin", task_id))
        self.assertIsNone(self.services.task_repository.get_task(task_id))
        self.assertEqual(self.services.task_repository.trace_spans(trace_id), [])

    def test_default_asset_catalog_excludes_retired_demo_shortcuts(self) -> None:
        bundle = self.services.data_asset_store.list_bundle("tenant_demo")
        shortcuts = [item for item in bundle["analysis_shortcuts"] if item.get("visible")]
        self.assertEqual(shortcuts, [])
        self.assertFalse(any("mock" in str(item.get("id") or "") for item in bundle["topic_tables"]))

    def test_model_call_audit_is_durable_and_contains_no_prompt_or_secret(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/platform.sqlite"
            services = build_local_platform(db_path=db_path)
            attach_governed_test_warehouse(services)
            services.system_config_store.upsert_model(
                "tenant_demo",
                {
                    "id": "model_audit",
                    "name": "审计模型",
                    "modelName": "finance-audit-model",
                    "key": "https://example.local/v1",
                    "value": "demo-key",
                    "availableModels": ["finance-audit-model"],
                    "enabledModels": ["finance-audit-model"],
                    "status": "available",
                },
                updated_by="u_super_admin",
            )
            response = run_analysis(
                services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="这是不可写入审计明文的敏感经营问题",
                page_context={"selected_model": {"id": "model_audit"}},
            )
            services.close()

            rebuilt = build_local_platform(db_path=db_path)
            try:
                model_calls = rebuilt.task_repository.model_calls("tenant_demo")
            finally:
                rebuilt.close()

        self.assertEqual(len(model_calls), 2)
        self.assertTrue(all(item["analysis_task_id"] == response["task_id"] for item in model_calls))
        self.assertTrue(all(item["provider_model_name"] == "finance-audit-model" for item in model_calls))
        self.assertEqual({item["subject_type"] for item in model_calls}, {"analysis_planning", "analysis_task"})
        audit_json = json.dumps(model_calls, ensure_ascii=False)
        self.assertNotIn("敏感经营问题", audit_json)
        self.assertNotIn("demo-key", audit_json)
        self.assertNotIn("example.local", audit_json)

    def test_analysis_preserves_context_skills_and_conversation(self) -> None:
        response = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="请按周报分析做归因分析",
            page_context={
                "analysis_context_skills": [
                    {"id": "weekly-report", "name": "周报分析", "category": "场景", "description": "按周报结构输出。"},
                    {"id": "attribution", "name": "归因分析", "category": "主题", "description": "拆解指标变化贡献。"},
                    {"id": "context-compression", "name": "上下文压缩", "category": "模式", "description": "压缩长会话。"},
                ],
                "conversation_session": {
                    "session_id": "session_test",
                    "turn_count": 3,
                    "compression_enabled": True,
                    "turns": [
                        {"role": "user", "content": "先看余额"},
                        {"role": "assistant", "content": "已返回余额分析"},
                        {"role": "user", "content": "继续归因"},
                    ],
                },
            },
        )

        context = response["intelligent_analysis"]["context"]
        self.assertEqual(
            [skill["name"] for skill in context["skills"]],
            ["周报分析", "归因分析", "上下文压缩"],
        )
        self.assertEqual(context["conversation"]["session_id"], "session_test")
        self.assertTrue(context["conversation"]["compression_enabled"])
        self.assertEqual(context["skills"][0]["analysisMethod"], "先核对报告周期和指标口径，再按规模、转化、风险和机构贡献形成证据链。")
        self.assertGreaterEqual(len(context["skills"][0]["memories"]), 1)
        self.assertEqual(context["plugins"][0]["name"], "财务分析师")
        executed_sql = response["skill_results"][0]["sql"]
        evidence = response["skill_results"][0]["evidence"]
        self.assertNotIn("周报分析 + 归因分析 + 上下文压缩", executed_sql)
        self.assertFalse(evidence["sql_executed"])
        self.assertEqual(evidence["executed_sql"], "")
        self.assertEqual(evidence["execution_statement"], executed_sql)
        self.assertEqual(evidence["executed_sql_sha256"], "")

    def test_realtime_voice_silence_analysis_preserves_full_context(self) -> None:
        self.services.system_config_store.upsert_model(
            "tenant_demo",
            {
                "id": "model_test",
                "name": "Deepseek",
                "modelName": "中转站",
                "key": "https://example.local/v1",
                "value": "demo-key",
                "availableModels": ["deepseek-v4-flash"],
                "enabledModels": ["deepseek-v4-flash"],
                "status": "available",
            },
            updated_by="u_super_admin",
        )
        response = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="郑州银行2026年7月放款波动用周报分析解释一下",
            page_context={
                "analysis_trigger": "realtime_voice_silence",
                "analysis_policy": {
                    "engine": "IntelligentAnalysisEngine",
                    "multiRoleDebate": "reuse_weekly_learning_memory_chain_when_writing_back_experience",
                    "timeDecay": "preserve_knowledge_memory_weighting_and_do_not_override_current_fact_data",
                },
                "selected_model": {
                    "id": "model_test",
                    "name": "Deepseek",
                    "modelName": "deepseek-v4-flash",
                    "status": "available",
                },
                "analysis_context_skills": [
                    {"id": "weekly-report", "name": "周报分析", "category": "场景", "description": "按周报结构输出。"},
                    {"id": "context-compression", "name": "上下文压缩", "category": "模式", "description": "压缩长会话。"},
                ],
                "selected_data_tables": [
                    {
                        "id": "topic_weekly_branch_rank",
                        "kind": "topic",
                        "name": "客户端名称不得作为事实源",
                        "code": "weekly_branch_loan_rank",
                        "sql": "SELECT untrusted_client_sql",
                        "fields": "untrusted_client_fields",
                    }
                ],
                "files": [
                    {"id": "file_metric_note", "name": "指标口径说明.md", "contentPreview": "放款口径说明"}
                ],
                "conversation_session": {
                    "session_id": "voice_session_test",
                    "turn_count": 2,
                    "compression_enabled": True,
                    "turns": [
                        {"role": "user", "content": "先看周报"},
                        {"role": "assistant", "content": "已返回周报分析"},
                    ],
                },
            },
        )

        intelligent = response["intelligent_analysis"]
        context = intelligent["context"]
        self.assertEqual(context["analysis_trigger"], "realtime_voice_silence")
        self.assertEqual(context["skills"][0]["name"], "周报分析")
        self.assertEqual(context["files"][0]["name"], "指标口径说明.md")
        self.assertEqual(context["conversation"]["session_id"], "voice_session_test")
        self.assertEqual(context["policy"]["engine"], "IntelligentAnalysisEngine")
        self.assertTrue(intelligent["visualization_suggestions"])
        self.assertIn("分行放款排名分析", intelligent["suggested_sql"])
        self.assertNotIn("untrusted_client_sql", intelligent["suggested_sql"])
        selected_table_context = response["asset_context"]["selected_data_tables"][0]
        self.assertEqual(selected_table_context["name"], "分行放款排名分析")
        self.assertTrue(selected_table_context.get("applicableScene") or selected_table_context.get("description"))
        self.assertTrue(selected_table_context["fields"])
        self.assertTrue(selected_table_context["fields"][0].get("explanation"))
        metric_context = response["asset_context"]["metric_dictionary_definitions"]
        self.assertTrue(any(item.get("definition") and item.get("valueLogic") for item in metric_context))
        self.assertEqual(
            response["skill_results"][0]["evidence"]["execution_statement"],
            response["skill_results"][0]["sql"],
        )
        self.assertIn("实时语音 5 秒静默自动触发", "；".join(intelligent["analysis_approach"]))

    def test_governed_test_warehouse_executes_tenant_scoped_aggregation(self) -> None:
        warehouse = build_governed_test_warehouse()
        result = warehouse.query(
            dataset_id="loan_operation_mart",
            tenant_id="tenant_demo",
            metric="loan_amount",
            dimension="product_line",
            filters={"tenant_id": "__context_tenant__"},
            limit=20,
        )

        self.assertEqual(result.dataset_id, "loan_operation_mart")
        self.assertEqual(result.metric, "loan_amount")
        self.assertEqual(result.aggregation, "sum")
        self.assertTrue(result.rows)
        self.assertIn("product_line", result.rows[0])
        self.assertIn("metric_value", result.rows[0])

    def test_sql_data_warehouse_executes_tenant_scoped_query(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/warehouse.sqlite"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE loan_fact (
                        tenant_id TEXT NOT NULL,
                        branch_name TEXT NOT NULL,
                        product_line TEXT NOT NULL,
                        loan_amount REAL NOT NULL
                    )
                    """
                )
                connection.executemany(
                    "INSERT INTO loan_fact(tenant_id, branch_name, product_line, loan_amount) VALUES (?, ?, ?, ?)",
                    [
                        ("tenant_demo", "上海分行", "消费贷", 12),
                        ("tenant_demo", "上海分行", "消费贷", 8),
                        ("tenant_demo", "南京分行", "经营贷", 30),
                        ("tenant_other", "上海分行", "消费贷", 999),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            warehouse = SQLDataWarehouse(
                lambda: sqlite3.connect(db_path),
                {
                    "loan_fact": {
                        "label": "贷款事实表",
                        "source_table": "loan_fact",
                        "tenant_column": "tenant_id",
                        "allowed_metrics": ["loan_amount"],
                        "allowed_dimensions": ["branch_name", "product_line"],
                        "metric_aggregation": {"loan_amount": "sum"},
                    }
                },
            )
            result = warehouse.query(
                dataset_id="loan_fact",
                tenant_id="tenant_demo",
                metric="loan_amount",
                dimension="branch_name",
                filters={"product_line": "消费贷"},
            )

        self.assertEqual(result.rows, [{"branch_name": "上海分行", "metric_value": 20.0, "metric_id": "loan_amount"}])
        with self.assertRaises(ValueError):
            SQLDataWarehouse(
                lambda: sqlite3.connect(":memory:"),
                {
                    "unsafe": {
                        "source_table": "loan_fact;drop_table",
                        "allowed_metrics": ["loan_amount"],
                        "allowed_dimensions": ["branch_name"],
                    }
                },
            )

    def test_sqlite_configured_warehouse_runs_through_semantic_workflow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            warehouse_db_path = f"{tmpdir}/warehouse.sqlite"
            catalog_path = f"{tmpdir}/warehouse_catalog.json"
            connection = sqlite3.connect(warehouse_db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE loan_operation_fact (
                        tenant_id TEXT NOT NULL,
                        branch_name TEXT NOT NULL,
                        product_line TEXT NOT NULL,
                        month TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        customer_segment TEXT NOT NULL,
                        loan_amount REAL NOT NULL,
                        drawdown_rate REAL NOT NULL,
                        drawdown_amount REAL NOT NULL,
                        eligible_amount REAL NOT NULL
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO loan_operation_fact(
                        tenant_id, branch_name, product_line, month, channel,
                        customer_segment, loan_amount, drawdown_rate,
                        drawdown_amount, eligible_amount
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("tenant_demo", "上海分行", "经营贷", "2026-07", "客户经理", "小微商户", 120, 0.42, 42, 100),
                        ("tenant_demo", "深圳分行", "消费贷", "2026-07", "手机银行", "年轻白领", 80, 0.36, 18, 50),
                        ("tenant_other", "越权分行", "经营贷", "2026-07", "客户经理", "小微商户", 9999, 0.99, 99, 100),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            with open(catalog_path, "w", encoding="utf-8") as catalog_file:
                json.dump(
                    {
                        "datasets": {
                            "loan_operation_mart": {
                                "label": "贷款经营事实表",
                                "source_table": "loan_operation_fact",
                                "tenant_column": "tenant_id",
                                "allowed_metrics": ["loan_amount", "drawdown_rate"],
                                "allowed_dimensions": ["branch_name", "product_line", "month", "channel", "customer_segment"],
                                "metric_aggregation": {
                                    "loan_amount": "sum",
                                    "drawdown_rate": {
                                        "aggregation": "ratio",
                                        "numerator": "drawdown_amount",
                                        "denominator": "eligible_amount",
                                        "multiplier": 1,
                                    },
                                },
                            }
                        }
                    },
                    catalog_file,
                    ensure_ascii=False,
                )

            with patch.dict(
                "os.environ",
                {
                    "SMART_DATA_AGENT_DATA_WAREHOUSE": "sqlite",
                    "SMART_DATA_AGENT_SQLITE_WAREHOUSE_PATH": warehouse_db_path,
                    "SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG": catalog_path,
                    "SMART_DATA_AGENT_SUPERSONIC_URL": "",
                },
            ):
                services = build_local_platform(db_path=f"{tmpdir}/platform.sqlite")
                try:
                    response = run_analysis(
                        services,
                        user_id="u_super_admin",
                        tenant_id="tenant_demo",
                        question="2026年7月各分行放款金额排名TOP10",
                    )
                finally:
                    services.close()

        first_result = response["skill_results"][0]
        self.assertEqual(first_result["semantic_info"]["data_source"], "sqlite_dbapi_warehouse")
        self.assertIn('"loan_operation_fact"', first_result["sql"])
        self.assertIn("values", first_result["parameters"])
        self.assertEqual({row["branch_name"] for row in first_result["data"]}, {"上海分行", "深圳分行"})
        self.assertNotIn("越权分行", {row["branch_name"] for row in first_result["data"]})

    def test_python_sandbox_executes_controlled_visualization_script(self) -> None:
        sandbox = PythonSandbox()
        script = '''def build_chart(data, context):
    x_field = context.get("x", "branch_name")
    y_field = context.get("y", "metric_value")
    return {
        "type": context.get("chart_type", "bar"),
        "series": [
            {"name": str(row.get(x_field, "")), "value": float(row.get(y_field, 0) or 0)}
            for row in data
        ],
        "table_rows": data[:20],
    }
'''

        result = sandbox.render_chart(
            script,
            [{"branch_name": "上海分行", "metric_value": 12}],
            {"x": "branch_name", "y": "metric_value", "chart_type": "bar"},
        )

        self.assertEqual(result.artifact["series"][0]["name"], "上海分行")
        self.assertEqual(result.artifact["series"][0]["value"], 12)

        with self.assertRaises(ValueError):
            sandbox.render_chart("import os\ndef build_chart(data, context):\n    return {}", [], {})

        with self.assertRaises(ValueError):
            sandbox.render_chart("def build_chart(data, context, extra=None):\n    return {}", [], {})

        with self.assertRaises(ValueError):
            sandbox.render_chart("def build_chart(data, context):\n    return {}", [{}] * (sandbox.max_rows + 1), {})

        with self.assertRaises(ValueError):
            sandbox.render_chart("def build_chart(data, context):\n    return {'pid': __import__('os').getpid()}", [], {})

    def test_diagnostic_question_builds_risk_analysis_plan(self) -> None:
        response = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="消费贷和经营贷的逾期率为什么波动",
        )

        self.assertEqual(response["task_type"], "diagnostic_analysis")
        self.assertEqual(response["analysis_plan"]["intent_rule_id"], "risk_diagnostic")
        self.assertEqual(response["analysis_plan"]["dataset_id"], "risk_operation_mart")
        self.assertIn("m1_overdue_rate", response["analysis_plan"]["metrics"])
        self.assertEqual(response["skill_results"][0]["chart_spec"]["type"], "bar")

    def test_operating_tenant_context_is_authorized_and_persisted(self) -> None:
        tenant_id = normalize_tenant_id("华兴银行")
        response = run_analysis(
            self.services,
            user_id="u_lina",
            tenant_id=tenant_id,
            question="2026年6月各分行放款金额排名TOP10",
            page_context={"selected_institution": "华兴银行"},
        )

        self.assertEqual(response["tenant_id"], tenant_id)
        self.assertEqual(response["skill_results"][0]["parameters"]["tenant_id"], tenant_id)
        self.assertIsNotNone(self.services.task_repository.get_task(response["task_id"]))
        self.assertEqual(len(self.services.memory_store.search(tenant_id, memory_type="analysis_case")), 1)

    def test_skill_permission_is_checked_before_query(self) -> None:
        with self.assertRaises(PermissionError):
            run_analysis(
                self.services,
                user_id="u_no_access",
                tenant_id="tenant_other",
                question="本周放款金额是多少",
            )
        runtime_summary = self.services.task_repository.runtime_summary()
        self.assertEqual(runtime_summary["error_count"], 1)
        self.assertEqual(runtime_summary["last_status"], "error")

    def test_sqlite_backed_platform_persists_tasks(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(db_path=f"{tmpdir}/platform.sqlite")
            attach_governed_test_warehouse(services)
            try:
                response = run_analysis(
                    services,
                    user_id="u_super_admin",
                    tenant_id="tenant_demo",
                    question="2026年6月各分行放款金额是多少",
                )

                stored = services.task_repository.get_task(response["task_id"])
                memory_records = services.memory_store.search("tenant_demo", memory_type="analysis_case")
                knowledge_hits = services.knowledge_store.search("放款金额", tenant_id="tenant_demo")
            finally:
                services.close()

            self.assertIsNotNone(stored)
            self.assertEqual(stored["analysis_plan"]["dataset_id"], "loan_operation_mart")
            self.assertEqual(stored["review"]["status"], "passed")
            self.assertEqual(memory_records[0].source_trace_id, response["trace_id"])
            self.assertEqual(knowledge_hits[0].document.doc_id, "kd_metric_loan_amount")

    def test_sqlite_backed_platform_keeps_existing_authz_rows_on_rebuild(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/platform.sqlite"
            services = build_local_platform(db_path=db_path)
            repository = services.permission_broker.enforcer.repository
            custom_role_id = "role:tenant_demo:custom_keep"
            try:
                repository.seed(
                    roles=[Role(custom_role_id, "tenant_demo", "自定义保留角色", RoleLevel.OPERATOR, False, created_by="u_super_admin")],
                    assignments=[RoleAssignment("u_custom_keep", "tenant_demo", custom_role_id, granted_by="u_super_admin")],
                    policies=[PermissionPolicy(custom_role_id, "tenant_demo", "metric:*", "read", attrs={"tenant_id": "tenant_demo"})],
                )
                policy_count_before = repository._conn.execute("SELECT COUNT(*) FROM auth_permission_policies").fetchone()[0]
            finally:
                services.close()

            rebuilt = build_local_platform(db_path=db_path)
            rebuilt_repository = rebuilt.permission_broker.enforcer.repository
            try:
                policy_count_after = rebuilt_repository._conn.execute("SELECT COUNT(*) FROM auth_permission_policies").fetchone()[0]
                preserved_role = rebuilt_repository.get_role(custom_role_id)
                can_read_metric = rebuilt.permission_broker.enforcer.enforce(
                    "u_custom_keep",
                    "tenant_demo",
                    "metric:any",
                    "read",
                    {"tenant_id": "tenant_demo"},
                )
            finally:
                rebuilt.close()

            self.assertEqual(policy_count_after, policy_count_before)
            self.assertIsNotNone(preserved_role)
            self.assertTrue(can_read_metric)

    def test_sqlite_rebuild_adds_only_new_system_menu_grants(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/platform.sqlite"
            services = build_local_platform(db_path=db_path)
            repository = services.permission_broker.enforcer.repository
            tenant_id = normalize_tenant_id("华兴银行")
            admin_role_id = tenant_role_id(tenant_id, "管理员")
            try:
                with repository._conn:
                    repository._conn.execute(
                        "DELETE FROM auth_permission_policies WHERE role_id = ? AND obj IN (?, ?, ?)",
                        (
                            admin_role_id,
                            "menu:self-analysis.analysis-config",
                            "menu:data-assets.tools",
                            "menu:dashboard",
                        ),
                    )
            finally:
                services.close()

            rebuilt = build_local_platform(db_path=db_path)
            try:
                enforcer = rebuilt.permission_broker.enforcer
                self.assertTrue(enforcer.enforce("u_lina", tenant_id, "menu:self-analysis.analysis-config", "read"))
                self.assertTrue(enforcer.enforce("u_lina", tenant_id, "menu:data-assets.tools", "read"))
                self.assertFalse(enforcer.enforce("u_lina", tenant_id, "menu:dashboard", "read"))
            finally:
                rebuilt.close()

    def test_local_development_admin_can_execute_analysis_for_operating_tenant(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(db_path=f"{tmpdir}/platform.sqlite")
            attach_governed_test_warehouse(services)
            try:
                tenant_id = normalize_tenant_id("华兴银行")
                self.assertTrue(
                    services.permission_broker.enforcer.enforce(
                        "u_super_admin",
                        tenant_id,
                        "skill:supersonic.query",
                        "execute",
                    )
                )
                response = run_analysis(
                    services,
                    user_id="u_super_admin",
                    tenant_id=tenant_id,
                question="2026年7月各分行放款金额排名TOP10",
                    page_context={"analysis_policy": {"resultDelivery": "data_first"}},
                )
                self.assertGreater(len(response["skill_results"][0]["data"]), 0)
            finally:
                services.close()

    def test_sqlite_backed_platform_does_not_restore_revoked_roles_on_rebuild(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/platform.sqlite"
            services = build_local_platform(db_path=db_path)
            repository = services.permission_broker.enforcer.repository
            try:
                self.assertTrue(repository.list_user_assignments("u_super_admin"))
                repository.delete_user_assignments("u_super_admin")
                self.assertEqual(repository.list_user_assignments("u_super_admin"), [])
            finally:
                services.close()

            rebuilt = build_local_platform(db_path=db_path)
            rebuilt_repository = rebuilt.permission_broker.enforcer.repository
            try:
                assignments_after_restart = rebuilt_repository.list_user_assignments("u_super_admin")
                can_read_metric = rebuilt.permission_broker.enforcer.enforce(
                    "u_super_admin",
                    "tenant_demo",
                    "metric:any",
                    "read",
                    {"tenant_id": "tenant_demo"},
                )
            finally:
                rebuilt.close()

            self.assertEqual(assignments_after_restart, [])
            self.assertFalse(can_read_metric)

    def test_http_api_runs_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            attach_governed_test_warehouse(server.services)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                body = json.dumps(
                    {
                        "question": "线上渠道获客成本和ROI月度变化",
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                conn.request(
                    "POST",
                    "/api/analysis/run",
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                health_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                health_conn.request("GET", "/api/health")
                health_response = health_conn.getresponse()
                health_payload = json.loads(health_response.read().decode("utf-8"))
                routes_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                routes_conn.request("GET", "/api/routes")
                routes_response = routes_conn.getresponse()
                routes_payload = json.loads(routes_response.read().decode("utf-8"))
                metrics_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                metrics_conn.request("GET", "/api/metrics")
                metrics_response = metrics_conn.getresponse()
                metrics_payload = metrics_response.read().decode("utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["analysis_plan"]["dataset_id"], "channel_operation_mart")
            self.assertIn("parameters", payload["skill_results"][0])
            self.assertTrue(payload["trace_id"].startswith("trace_"))
            self.assertEqual(health_response.status, 200)
            self.assertEqual(health_payload["runtime"]["ok_count"], 1)
            self.assertEqual(health_payload["semantic_client_mode"], "local")
            self.assertEqual(health_payload["data_source_mode"], "governed_test_warehouse")
            self.assertEqual(routes_response.status, 200)
            self.assertTrue(API_ROUTE_REGISTRY.has_route("POST", "/api/analysis/run"))
            self.assertIn("/api/analysis/run", {route["path"] for route in routes_payload["routes"]})
            self.assertEqual(metrics_response.status, 200)
            self.assertIn('smart_data_agent_analysis_requests_total{status="ok"} 1', metrics_payload)
            self.assertIn("smart_data_agent_analysis_latency_avg_ms", metrics_payload)

    def test_api_route_catalog_covers_server_and_frontend_service_paths(self) -> None:
        registered_paths = {str(route["path"]) for route in API_ROUTE_REGISTRY.list_routes()}
        server_text = Path("backend/platform/api/server.py").read_text(encoding="utf-8")
        server_paths = set(re.findall(r'parsed_path\.path\s*(?:==|!=)\s*"([^"]+)"', server_text))
        frontend_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in Path("src/app/services").glob("*.ts")
        )
        frontend_paths = {
            path
            for path in re.findall(r"/api/[A-Za-z0-9_./-]+", frontend_text)
            if not path.endswith("/")
        }

        self.assertFalse(server_paths - registered_paths)
        self.assertFalse(frontend_paths - registered_paths)
        self.assertEqual(len(API_ROUTE_REGISTRY.list_routes()), len(API_ROUTE_REGISTRY.openapi_summary()["routes"]))

    def test_api_route_catalog_matches_handler_tables(self) -> None:
        registered_routes = {(str(route["method"]), str(route["path"])) for route in API_ROUTE_REGISTRY.list_routes()}
        handler_routes = {
            ("GET", "/api/health"),
            ("GET", "/api/live"),
            ("GET", "/api/ready"),
            ("GET", "/api/metrics"),
            ("GET", "/api/routes"),
            ("GET", "/api/openapi.json"),
            *(("GET", path) for path in GET_ROUTE_HANDLERS),
            *(("POST", path) for path in POST_ROUTE_HANDLERS),
            *(("PUT", path) for path in PUT_ROUTE_HANDLERS),
            *(("DELETE", path) for path in DELETE_ROUTE_HANDLERS),
        }

        self.assertEqual(handler_routes, registered_routes)

    def test_application_store_persists_module_actions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/application.sqlite"
            store = SQLiteApplicationStore(db_path)
            try:
                with self.assertRaises(ApplicationActionUnavailable):
                    store.run_action(
                        "tenant_demo",
                        "business_sandbox",
                        "run_simulation",
                        payload={"params": {"rateAdjust": 1, "creditLimit": 2, "approvalRate": 3, "pushRate": 4}},
                        actor_user_id="u_super_admin",
                    )
                store.run_action(
                    "tenant_demo",
                    "dashboard",
                    "select_bank",
                    payload={"selectedBank": "杭州分行", "selectedProduct": "consumer"},
                    actor_user_id="u_super_admin",
                )
                store.run_action(
                    "tenant_demo",
                    "self_analysis",
                    "upload_knowledge_file",
                    payload={"id": "file_quality", "name": "quality.json", "type": "application/json", "size": 321, "lastModified": 123},
                    actor_user_id="u_super_admin",
                )
            finally:
                store.close()

            reopened = SQLiteApplicationStore(db_path)
            try:
                sandbox = reopened.get_module("tenant_demo", "business_sandbox")
                dashboard = reopened.get_module("tenant_demo", "dashboard")
                self_analysis = reopened.get_module("tenant_demo", "self_analysis")
            finally:
                reopened.close()

        self.assertIsNone(sandbox["state"]["lastSimulation"])
        self.assertEqual(sandbox["actions"], [])
        self.assertEqual(dashboard["state"]["selectedBank"], "杭州分行")
        self.assertEqual(dashboard["state"]["selectedProduct"], "consumer")
        self.assertEqual(self_analysis["state"]["uploadedFiles"][0]["name"], "quality.json")
        self.assertEqual(self_analysis["state"]["uploadedFiles"][0]["size"], 321)

        with TemporaryDirectory() as tmpdir:
            store = SQLiteApplicationStore(f"{tmpdir}/application.sqlite")
            try:
                with self.assertRaises(UnsupportedApplicationAction):
                    store.run_action("tenant_demo", "dashboard", "unknown_success", actor_user_id="u_super_admin")
            finally:
                store.close()

    def test_agent_todos_are_scoped_to_current_user(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/application.sqlite"
            store = SQLiteApplicationStore(db_path)
            try:
                store.run_action(
                    "tenant_demo",
                    "agent_workspace",
                    "create_todo",
                    payload={
                        "todo": {
                            "id": "todo_user_a",
                            "title": "用户A待办",
                            "assignee": "u_user_a",
                            "ownerUserId": "u_user_a",
                            "createdBy": "u_user_a",
                        }
                    },
                    actor_user_id="u_user_a",
                )
                store.run_action(
                    "tenant_demo",
                    "agent_workspace",
                    "create_todo",
                    payload={
                        "todo": {
                            "id": "todo_user_b",
                            "title": "用户B待办",
                            "assignee": "u_user_b",
                            "ownerUserId": "u_user_b",
                            "createdBy": "u_user_b",
                        }
                    },
                    actor_user_id="u_user_b",
                )
                user_a_module = store.get_module("tenant_demo", "agent_workspace", actor_user_id="u_user_a")
                user_b_module = store.get_module("tenant_demo", "agent_workspace", actor_user_id="u_user_b")
            finally:
                store.close()

        self.assertEqual([todo["title"] for todo in user_a_module["state"]["todos"]], ["用户A待办"])
        self.assertEqual([todo["title"] for todo in user_b_module["state"]["todos"]], ["用户B待办"])

    def test_agent_tasks_are_created_updated_and_scoped_to_current_user(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/application.sqlite"
            store = SQLiteApplicationStore(db_path)
            try:
                store.run_action(
                    "tenant_demo",
                    "agent_workspace",
                    "create_task",
                    payload={
                        "ownerUserId": "u_user_a",
                        "task": {
                            "id": "task_user_a",
                            "name": "用户A触发洞察",
                            "category": "insight",
                            "type": "任务触发洞察",
                            "schedule": "指标触发",
                            "status": "alert",
                        }
                    },
                    actor_user_id="u_user_a",
                )
                store.run_action(
                    "tenant_demo",
                    "agent_workspace",
                    "create_task",
                    payload={
                        "task": {
                            "id": "task_user_b",
                            "name": "用户B自动化任务",
                            "category": "automation",
                            "type": "定时任务",
                            "schedule": "每日 09:00",
                            "ownerUserId": "u_user_b",
                            "createdBy": "u_user_b",
                        }
                    },
                    actor_user_id="u_user_b",
                )
                store.run_action(
                    "tenant_demo",
                    "agent_workspace",
                    "update_task",
                    payload={
                        "task": {
                            "id": "task_user_a",
                            "name": "用户A触发洞察已修改",
                            "category": "insight",
                            "type": "任务触发洞察",
                            "schedule": "异常触发",
                            "status": "completed",
                            "result": "已形成跟进结论",
                            "ownerUserId": "u_user_a",
                            "createdBy": "u_user_a",
                        }
                    },
                    actor_user_id="u_user_a",
                )
                user_a_module = store.get_module("tenant_demo", "agent_workspace", actor_user_id="u_user_a")
                user_b_module = store.get_module("tenant_demo", "agent_workspace", actor_user_id="u_user_b")
            finally:
                store.close()

        self.assertEqual([task["name"] for task in user_a_module["state"]["createdTasks"]], ["用户A触发洞察已修改"])
        self.assertEqual(user_a_module["state"]["createdTasks"][0]["category"], "insight")
        self.assertEqual(user_a_module["state"]["createdTasks"][0]["status"], "completed")
        self.assertEqual([task["name"] for task in user_b_module["state"]["createdTasks"]], ["用户B自动化任务"])
        self.assertEqual(user_b_module["state"]["createdTasks"][0]["category"], "automation")

    def test_http_application_action_does_not_fake_unimplemented_agent_success(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/api.sqlite"
            server = create_server("127.0.0.1", 0, db_path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                action_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                action_conn.request(
                    "POST",
                    "/api/application/action",
                    body=json.dumps(
                        {
                            "module_key": "platform_shell",
                            "action": "ask_agent",
                            "payload": {"question": "风险预警", "selectedInstitution": "上海分行"},
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                action_response = action_conn.getresponse()
                action_payload = json.loads(action_response.read().decode("utf-8"))

                module_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                module_conn.request(
                    "GET",
                    "/api/application/module?module_key=platform_shell",
                    headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"},
                )
                module_response = module_conn.getresponse()
                module_payload = json.loads(module_response.read().decode("utf-8"))

                audit_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                audit_conn.request(
                    "GET",
                    "/api/audit-logs?tenant_id=tenant_demo&user_id=u_super_admin",
                    headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"},
                )
                audit_response = audit_conn.getresponse()
                audit_payload = json.loads(audit_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            with closing(sqlite3.connect(db_path)) as conn:
                action_count = conn.execute(
                    "SELECT count(*) FROM platform_application_actions WHERE tenant_id = ? AND module_key = ?",
                    ("tenant_demo", "platform_shell"),
                ).fetchone()[0]

        self.assertEqual(action_response.status, 501)
        self.assertEqual(action_payload["error"], "application_action_not_implemented")
        self.assertEqual(module_response.status, 200)
        self.assertEqual(module_payload["state"]["agentMessages"], [])
        self.assertEqual(action_count, 0)
        self.assertEqual(audit_response.status, 200)
        self.assertNotIn("application.ask_agent", {log["action"] for log in audit_payload["logs"]})

    def test_http_api_rejects_invalid_or_oversized_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                invalid_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                invalid_conn.request(
                    "POST",
                    "/api/analysis/run",
                    body=b"{invalid",
                    headers={"Content-Type": "application/json"},
                )
                invalid_response = invalid_conn.getresponse()
                invalid_payload = json.loads(invalid_response.read().decode("utf-8"))

                oversized_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                oversized_conn.putrequest("POST", "/api/analysis/run")
                oversized_conn.putheader("Content-Type", "application/json")
                oversized_conn.putheader("Content-Length", str(600 * 1024))
                oversized_conn.endheaders()
                oversized_response = oversized_conn.getresponse()
                oversized_payload = json.loads(oversized_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(invalid_response.status, 400)
            self.assertEqual(invalid_payload["error"], "invalid_json")
            self.assertEqual(oversized_response.status, 413)
            self.assertEqual(oversized_payload["error"], "request_body_too_large")

    def test_http_data_asset_raw_file_upload_creates_tenant_artifact(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                content = "customer_id,stat_date,amount\nC001,2026-07-17,128.50\n".encode("utf-8")
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request(
                    "POST",
                    "/api/data-assets/raw-file",
                    body=json.dumps(
                        {
                            "file_name": "loan_source.csv",
                            "content_base64": base64.b64encode(content).decode("ascii"),
                        }
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_reviewer",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                artifact, stored_content = server.services.data_acquisition_service.get_artifact_content(
                    "tenant_demo", payload["file"]["artifact_id"]
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["file"]["file_name"], "loan_source.csv")
            self.assertEqual(payload["file"]["content_type"], "text/csv; charset=utf-8")
            self.assertEqual(artifact["artifact_type"], "other")
            self.assertEqual(stored_content, content)

    def test_http_data_asset_ids_status_and_reviews_are_server_governed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                candidate = {
                    "id": "client_spoofed_id",
                    "name": "Governed topic",
                    "code": "governed_topic",
                    "description": "A tenant-scoped reviewed topic.",
                    "sql": "SELECT branch_name, SUM(loan_amount) AS loan_amount FROM loan_fact WHERE tenant_id = :tenant_id GROUP BY branch_name",
                    "fields": [
                        {"fieldNameEn": "branch_name", "fieldNameCn": "Branch", "type": "string"},
                        {"fieldNameEn": "loan_amount", "fieldNameCn": "Amount", "type": "decimal"},
                    ],
                    "lifecycleStatus": "active",
                    "reviewedBy": "client_spoofed_reviewer",
                    "assetVersion": 999,
                }
                create_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                create_conn.request(
                    "POST",
                    "/api/data-assets/item",
                    body=json.dumps({"item_type": "topic_table", "item": candidate}).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_reviewer",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                create_response = create_conn.getresponse()
                create_payload = json.loads(create_response.read().decode("utf-8"))
                saved = create_payload["item"]

                same_reviewer_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                same_reviewer_conn.request(
                    "POST",
                    "/api/data-assets/item/review",
                    body=json.dumps(
                        {
                            "item_type": "topic_table",
                            "item_id": saved["id"],
                            "expected_version": saved["assetVersion"],
                            "decision": "approved",
                        }
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_reviewer",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                same_reviewer_response = same_reviewer_conn.getresponse()
                same_reviewer_payload = json.loads(same_reviewer_response.read().decode("utf-8"))

                review_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                review_conn.request(
                    "POST",
                    "/api/data-assets/item/review",
                    body=json.dumps(
                        {
                            "item_type": "topic_table",
                            "item_id": saved["id"],
                            "expected_version": saved["assetVersion"],
                            "decision": "approved",
                            "comments": "schema and tenant filter verified",
                        }
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                review_response = review_conn.getresponse()
                review_payload = json.loads(review_response.read().decode("utf-8"))

                skill_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                skill_conn.request(
                    "POST",
                    "/api/data-assets/item",
                    body=json.dumps(
                        {
                            "item_type": "analysis_skill",
                            "item": {
                                "name": "即时生效测试主题",
                                "category": "主题",
                                "description": "验证运行配置保存后立即进入生效版本。",
                                "memoryRefs": [],
                                "toolRefs": [],
                                "analysisMethod": "先核对口径。",
                                "documentAbstraction": "抽取指标和时间。",
                                "outputFormat": "结论 / 证据",
                                "viewpointStrategy": "结论必须绑定证据。",
                                "recommendedSkillIds": [],
                                "enabled": True,
                                "sortOrder": 999,
                            },
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                skill_response = skill_conn.getresponse()
                skill_payload = json.loads(skill_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(create_response.status, 200)
        self.assertNotEqual(saved["id"], "client_spoofed_id")
        self.assertEqual(saved["lifecycleStatus"], "review")
        self.assertEqual(saved["submittedBy"], "u_reviewer")
        self.assertEqual(saved["assetVersion"], 1)
        self.assertEqual(saved["reviewedBy"], "")
        self.assertEqual(same_reviewer_response.status, 403)
        self.assertEqual(same_reviewer_payload["error"], "permission_denied")
        self.assertEqual(review_response.status, 200)
        self.assertEqual(review_payload["item"]["lifecycleStatus"], "active")
        self.assertEqual(review_payload["item"]["reviewedBy"], "u_super_admin")
        self.assertEqual(skill_response.status, 200)
        self.assertEqual(skill_payload["item"]["lifecycleStatus"], "active")

    def test_runtime_asset_catalog_keeps_last_published_skill_visible_during_review(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_AUTH_MODE": "strict", "SMART_DATA_AGENT_AUTH_SECRET": "test-secret"},
        ):
            with TemporaryDirectory() as tmpdir:
                server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
                weekly_skill = server.services.data_asset_store.get_item(
                    "tenant_demo", "analysis_skill", "scene-weekly-report"
                )
                self.assertIsNotNone(weekly_skill)
                server.services.data_asset_store.upsert_item(
                    "tenant_demo",
                    "analysis_skill",
                    {**weekly_skill, "description": "待审核的新周报分析方案。"},
                    updated_by="u_super_admin",
                    lifecycle_status="review",
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    token = _stateful_test_token(server, "u_super_admin", "tenant_demo")
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                    connection.request(
                        "GET",
                        "/api/data-assets?scope=runtime",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

        runtime_weekly = next(
            item for item in payload["analysis_skills"] if item["id"] == "scene-weekly-report"
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["source_mode"], "runtime_published")
        self.assertEqual(runtime_weekly["lifecycleStatus"], "active")
        self.assertNotEqual(runtime_weekly["description"], "待审核的新周报分析方案。")

    def test_http_navigation_is_filtered_by_menu_permissions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            repository = server.services.permission_broker.enforcer.repository
            repository.seed(
                roles=[Role("role:tenant_demo:nav_limited", "tenant_demo", "导航受限角色", RoleLevel.OPERATOR)],
                assignments=[RoleAssignment("u_nav", "tenant_demo", "role:tenant_demo:nav_limited")],
                policies=[
                    PermissionPolicy("role:tenant_demo:nav_limited", "tenant_demo", "menu:self-analysis.smart-analysis", "read"),
                    PermissionPolicy("role:tenant_demo:nav_limited", "tenant_demo", "menu:settings.audit", "read"),
                    PermissionPolicy("role:tenant_demo:nav_limited", "tenant_demo", "menu:settings.config", "read"),
                ],
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "GET",
                    "/api/navigation",
                    headers={"X-User-Id": "u_nav", "X-Tenant-Id": "tenant_demo"},
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            self.assertIn("self-analysis", payload["menu_keys"])
            self.assertIn("self-analysis.smart-analysis", payload["menu_keys"])
            self.assertIn("settings", payload["menu_keys"])
            self.assertIn("settings.audit", payload["menu_keys"])
            self.assertIn("settings.config", payload["menu_keys"])
            self.assertNotIn("dashboard", payload["menu_keys"])
            self.assertNotIn("self-analysis.my-reports", payload["menu_keys"])
            self.assertNotIn("settings.users", payload["menu_keys"])

    def test_super_admin_navigation_includes_dashboard_and_opt_in_menus(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "GET",
                    "/api/navigation?tenant_id=tenant_demo&user_id=u_super_admin",
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertIn("dashboard", payload["menu_keys"])
        self.assertIn("market-customer", payload["menu_keys"])
        self.assertIn("task-workbench", payload["menu_keys"])
        self.assertIn("notifications", payload["menu_keys"])

    def test_tenant_admin_navigation_keeps_all_system_management_pages_visible(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "GET",
                    f"/api/navigation?tenant_id={quote(tenant_id)}&user_id=u_lina",
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertIn("settings.users", payload["menu_keys"])
        self.assertIn("settings.roles", payload["menu_keys"])
        self.assertIn("settings.audit", payload["menu_keys"])
        self.assertIn("settings.config", payload["menu_keys"])
        self.assertNotIn("dashboard", payload["menu_keys"])
        self.assertNotIn("market-customer", payload["menu_keys"])
        self.assertNotIn("task-workbench.todos", payload["menu_keys"])
        self.assertNotIn("notifications", payload["menu_keys"])

    def test_http_access_user_upsert_persists_profile_and_role_assignment(self) -> None:
        tenant_id = normalize_tenant_id("华兴银行")
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps(
                    {
                        "user": {
                            "id": "u_access_case",
                            "name": "测试用户",
                            "department": "华兴银行",
                            "email": "access-case@bank.com",
                            "status": "active",
                            "lastLogin": "未登录",
                        "tenantRoles": [{"tenant": "仅用于显示", "tenantId": tenant_id, "role": "操作员"}],
                        },
                        "user_id": "u_super_admin",
                        "tenant_id": tenant_id,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                save_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                save_conn.request(
                    "POST",
                    "/api/access/user",
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                    },
                )
                save_response = save_conn.getresponse()
                save_payload = json.loads(save_response.read().decode("utf-8"))

                list_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                list_conn.request(
                    "GET",
                    f"/api/access/users?user_id=u_super_admin&tenant_id={quote(tenant_id)}",
                )
                list_response = list_conn.getresponse()
                list_payload = json.loads(list_response.read().decode("utf-8"))

                can_read_metric = server.services.permission_broker.enforcer.enforce(
                    "u_access_case",
                    tenant_id,
                    "metric:any",
                    "read",
                    {"tenant_id": tenant_id},
                )

                delete_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                delete_conn.request(
                    "DELETE",
                    f"/api/access/user?user_id=u_super_admin&tenant_id={quote(tenant_id)}&target_user_id=u_access_case",
                )
                delete_response = delete_conn.getresponse()
                delete_payload = json.loads(delete_response.read().decode("utf-8"))

                can_read_after_delete = server.services.permission_broker.enforcer.enforce(
                    "u_access_case",
                    tenant_id,
                    "metric:any",
                    "read",
                    {"tenant_id": tenant_id},
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(save_response.status, 200)
            self.assertEqual(save_payload["user"]["id"], "u_access_case")
            self.assertEqual(
                save_payload["user"]["tenantRoles"],
                [{"tenant": "华兴银行", "tenantId": tenant_id, "role": "操作员"}],
            )
            self.assertEqual(list_response.status, 200)
            self.assertIn("u_access_case", {user["id"] for user in list_payload["users"]})
            self.assertTrue(can_read_metric)
            self.assertEqual(delete_response.status, 200)
            self.assertTrue(delete_payload["deleted"])
            self.assertFalse(can_read_after_delete)

    def test_http_access_user_upsert_allows_one_user_to_administer_multiple_institutions(self) -> None:
        primary_tenant_id = normalize_tenant_id("华兴银行")
        secondary_tenant_id = normalize_tenant_id("广州银行")
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps(
                    {
                        "user": {
                            "id": "u_multi_institution_admin",
                            "name": "多机构管理员",
                            "department": "华兴银行",
                            "email": "multi-institution-admin@bank.com",
                            "status": "active",
                            "lastLogin": "未登录",
                            "tenantRoles": [
                                {"tenant": "华兴银行", "role": "管理员"},
                                {"tenant": "广州银行", "role": "管理员"},
                            ],
                        },
                        "user_id": "u_super_admin",
                        "tenant_id": primary_tenant_id,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("POST", "/api/access/user", body=body, headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))

                can_manage_primary = server.services.permission_broker.enforcer.enforce(
                    "u_multi_institution_admin", primary_tenant_id, "role:*", "manage", {"tenant_id": primary_tenant_id},
                )
                can_manage_secondary = server.services.permission_broker.enforcer.enforce(
                    "u_multi_institution_admin", secondary_tenant_id, "role:*", "manage", {"tenant_id": secondary_tenant_id},
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertEqual(
            payload["user"]["tenantRoles"],
            [
                {"tenant": "华兴银行", "tenantId": primary_tenant_id, "role": "管理员"},
                {"tenant": "广州银行", "tenantId": secondary_tenant_id, "role": "管理员"},
            ],
        )
        self.assertTrue(can_manage_primary)
        self.assertTrue(can_manage_secondary)

    def test_http_access_user_upsert_returns_actionable_role_validation(self) -> None:
        tenant_id = normalize_tenant_id("华兴银行")
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request(
                    "POST",
                    "/api/access/user",
                    body=json.dumps(
                        {
                            "user_id": "u_super_admin",
                            "tenant_id": tenant_id,
                            "user": {
                                "id": "",
                                "name": "校验用户",
                                "department": "华兴银行",
                                "email": "validation-user@example.com",
                                "status": "active",
                                "lastLogin": "未登录",
                                "tenantRoles": [
                                    {"tenant": "华兴银行", "tenantId": tenant_id, "role": "不存在的角色"},
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                self.assertIsNone(server.services.access_service.user_store.get_profile("u_validation_user"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"], "access_user_role_not_found")
        self.assertEqual(payload["message"], "角色不存在，请检查：华兴银行 · 不存在的角色")

    def test_http_access_user_create_rejects_existing_email_without_overwriting_account(self) -> None:
        tenant_id = normalize_tenant_id("华兴银行")
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request(
                    "POST",
                    "/api/access/user",
                    body=json.dumps(
                        {
                            "user_id": "u_super_admin",
                            "tenant_id": tenant_id,
                            "user": {
                                "id": "",
                                "name": "不应覆盖管理员",
                                "department": "华兴银行",
                                "email": "xujingbo-jk@qifu.com",
                                "status": "active",
                                "lastLogin": "未登录",
                                "tenantRoles": [
                                    {"tenant": "华兴银行", "tenantId": tenant_id, "role": "操作员"},
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                profile = server.services.access_service.user_store.get_profile("u_super_admin")
                assignments = server.services.permission_broker.enforcer.repository.list_user_assignments(
                    "u_super_admin"
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"], "access_user_email_conflict")
        self.assertEqual(payload["message"], "该邮箱已绑定其他用户，请检查邮箱或编辑已有用户。")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "胥京波")
        self.assertTrue(any(assignment.role_id == SUPER_ADMIN_ROLE_ID for assignment in assignments))

    def test_access_role_policy_save_rewrites_rbac_policies(self) -> None:
        tenant_id = normalize_tenant_id("华兴银行")
        permission = {
            "id": tenant_id,
            "institution": "华兴银行",
            "adminMenus": ["经营周报", "系统管理"],
            "adminDataScopes": ["指标字典"],
            "operatorSuperMenus": [],
            "operatorSuperDataScopes": [],
            "operatorAdminMenus": ["经营周报"],
            "operatorAdminDataScopes": ["指标字典"],
            "manageableRoles": ["操作员"],
            "customRoles": [],
            "updatedBy": "测试",
            "updatedAt": "刚刚",
        }

        saved = self.services.access_service.save_role_permission(
            ExecutionContext(user_id="u_super_admin", tenant_id=tenant_id),
            permission,
        )
        repository = self.services.permission_broker.enforcer.repository
        repository.seed(
            roles=[],
            assignments=[RoleAssignment("u_hx_operator_policy", tenant_id, tenant_role_id(tenant_id, "操作员"))],
            policies=[],
        )

        can_read_weekly = self.services.permission_broker.enforcer.enforce(
            "u_hx_operator_policy",
            tenant_id,
            "menu:business-analysis.weekly-report",
            "read",
            {"tenant_id": tenant_id},
        )
        can_read_dashboard = self.services.permission_broker.enforcer.enforce(
            "u_hx_operator_policy",
            tenant_id,
            "menu:dashboard",
            "read",
            {"tenant_id": tenant_id},
        )
        can_read_metric = self.services.permission_broker.enforcer.enforce(
            "u_hx_operator_policy",
            tenant_id,
            "metric:any",
            "read",
            {"tenant_id": tenant_id},
        )
        manageable_names = {
            repository.get_role(role_id).name
            for role_id in repository.get_manageable_role_ids(tenant_role_id(tenant_id, "管理员"))
            if repository.get_role(role_id)
        }

        self.assertEqual(saved["institution"], "华兴银行")
        self.assertTrue(can_read_weekly)
        self.assertFalse(can_read_dashboard)
        self.assertTrue(can_read_metric)
        self.assertIn("操作员", manageable_names)
        self.assertNotIn("周报分析岗", manageable_names)

    def test_access_role_policy_save_creates_custom_role_configs(self) -> None:
        tenant_id = normalize_tenant_id("华兴银行")
        permission = {
            "id": tenant_id,
            "institution": "华兴银行",
            "roleConfigs": [
                {
                    "roleId": tenant_role_id(tenant_id, "管理员"),
                    "name": "管理员",
                    "roleType": "admin",
                    "isSystem": True,
                    "menus": ["用户管理", "角色权限", "指标字典"],
                    "dataScopes": ["指标字典"],
                    "manageableRoles": ["操作员", "自定义审批岗"],
                },
                {
                    "roleId": tenant_role_id(tenant_id, "操作员"),
                    "name": "操作员",
                    "roleType": "operator",
                    "isSystem": True,
                    "menus": ["指标字典"],
                    "dataScopes": ["指标字典"],
                    "manageableRoles": [],
                },
                {
                    "roleId": tenant_role_id(tenant_id, "自定义审批岗"),
                    "name": "自定义审批岗",
                    "roleType": "custom",
                    "isSystem": False,
                    "menus": ["智能分析"],
                    "dataScopes": ["指标字典"],
                    "manageableRoles": [],
                },
            ],
        }

        saved = self.services.access_service.save_role_permission(
            ExecutionContext(user_id="u_super_admin", tenant_id=tenant_id),
            permission,
        )
        repository = self.services.permission_broker.enforcer.repository
        custom_role_id = tenant_role_id(tenant_id, "自定义审批岗")
        repository.seed(
            roles=[],
            assignments=[RoleAssignment("u_custom_role_config", tenant_id, custom_role_id)],
            policies=[],
        )

        custom_role = repository.get_role(custom_role_id)
        can_read_smart_analysis = self.services.permission_broker.enforcer.enforce(
            "u_custom_role_config",
            tenant_id,
            "menu:self-analysis.smart-analysis",
            "read",
            {"tenant_id": tenant_id},
        )
        can_manage_roles = self.services.permission_broker.enforcer.enforce(
            "u_custom_role_config",
            tenant_id,
            "role:*",
            "manage",
            {"tenant_id": tenant_id},
        )

        self.assertIsNotNone(custom_role)
        self.assertIn("自定义审批岗", {role["name"] for role in saved["roleConfigs"]})
        self.assertTrue(can_read_smart_analysis)
        self.assertFalse(can_manage_roles)

    def test_operator_runtime_capabilities_are_minimal(self) -> None:
        tenant_id = normalize_tenant_id("郑州银行")
        broker = self.services.permission_broker
        context = ExecutionContext(user_id="u_zhaomin", tenant_id=tenant_id)

        self.assertTrue(broker.check_resource(context, "skill:supersonic.query", "execute"))
        self.assertTrue(broker.check_resource(context, "mcp:database.query", "execute"))
        self.assertTrue(broker.check_resource(context, "mcp:knowledge.search", "execute"))
        self.assertFalse(broker.check_resource(context, "mcp:knowledge.ingest", "execute"))
        self.assertFalse(broker.check_resource(context, "report:*", "create"))
        self.assertFalse(broker.check_resource(context, "role:*", "manage"))

    def test_http_api_strict_auth_requires_signed_token(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_AUTH_MODE": "strict", "SMART_DATA_AGENT_AUTH_SECRET": "test-secret"},
        ):
            with TemporaryDirectory() as tmpdir:
                server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "POST",
                        "/api/analysis/run",
                        body=json.dumps({"question": "本周放款金额是多少"}, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    response = conn.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

            self.assertEqual(response.status, 401)
            self.assertEqual(payload["error"], "authentication_required")

    def test_strict_mode_rejects_email_login_and_public_registration(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_AUTH_MODE": "strict", "SMART_DATA_AGENT_AUTH_SECRET": "test-secret"},
        ):
            with TemporaryDirectory() as tmpdir:
                server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    login_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    login_conn.request(
                        "POST",
                        "/api/auth/login",
                        body=json.dumps({"email": "lina@bank.com", "password": TEST_DEVELOPMENT_LOGIN_PASSWORD}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    login_response = login_conn.getresponse()
                    login_payload = json.loads(login_response.read().decode("utf-8"))

                    register_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    register_conn.request(
                        "POST",
                        "/api/auth/register",
                        body=json.dumps({"name": "攻击者", "email": "attacker@example.com", "institution": "郑州银行"}, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    register_response = register_conn.getresponse()
                    register_payload = json.loads(register_response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

        self.assertEqual(login_response.status, 403)
        self.assertEqual(login_payload["error"], "external_identity_required")
        self.assertEqual(register_response.status, 403)
        self.assertEqual(register_payload["error"], "public_registration_disabled")

    def test_http_api_strict_auth_uses_signed_context_over_body_spoofing(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_AUTH_MODE": "strict", "SMART_DATA_AGENT_AUTH_SECRET": "test-secret"},
        ):
            with TemporaryDirectory() as tmpdir:
                server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
                attach_governed_test_warehouse(server.services)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    token = _stateful_test_token(server, "u_super_admin", "tenant_demo")
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "POST",
                        "/api/analysis/run",
                        body=json.dumps(
                            {
                                "question": "2026年7月放款金额是多少",
                                "user_id": "attacker",
                                "tenant_id": normalize_tenant_id("广州银行"),
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                    )
                    response = conn.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["tenant_id"], "tenant_demo")
            self.assertEqual(payload["user_id"], "u_super_admin")
            self.assertEqual(payload["skill_results"][0]["parameters"]["tenant_id"], "tenant_demo")

    def test_http_api_strict_auth_allows_signed_tenant_selection_only(self) -> None:
        huaxing_tenant = normalize_tenant_id("华兴银行")
        guangzhou_tenant = normalize_tenant_id("广州银行")
        unauthorized_tenant = normalize_tenant_id("南京银行")
        with patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_AUTH_MODE": "strict", "SMART_DATA_AGENT_AUTH_SECRET": "test-secret"},
        ):
            with TemporaryDirectory() as tmpdir:
                server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    token = _stateful_test_token(
                        server,
                        "u_super_admin",
                        huaxing_tenant,
                        tenant_ids=(huaxing_tenant, guangzhou_tenant),
                    )
                    allowed_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    allowed_conn.request(
                        "GET",
                        "/api/navigation",
                        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": quote(guangzhou_tenant)},
                    )
                    allowed_response = allowed_conn.getresponse()
                    allowed_payload = json.loads(allowed_response.read().decode("utf-8"))

                    denied_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    denied_conn.request(
                        "GET",
                        "/api/navigation",
                        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": quote(unauthorized_tenant)},
                    )
                    denied_response = denied_conn.getresponse()
                    denied_payload = json.loads(denied_response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

        self.assertEqual(allowed_response.status, 200)
        self.assertEqual(allowed_payload["tenant_id"], guangzhou_tenant)
        self.assertEqual(denied_response.status, 401)
        self.assertEqual(denied_payload["error"], "authentication_required")

    def test_http_tenants_lists_backend_operating_tenants(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/tenants")
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertIn({"id": normalize_tenant_id("郑州银行"), "name": "郑州银行", "status": "active"}, payload["tenants"])
        self.assertGreaterEqual(payload["count"], 10)

    def test_auth_login_and_register_return_session_context(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                login_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                login_conn.request(
                    "POST",
                    "/api/auth/login",
                    body=json.dumps({"email": "lina@bank.com", "password": TEST_DEVELOPMENT_LOGIN_PASSWORD}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                login_response = login_conn.getresponse()
                login_payload = json.loads(login_response.read().decode("utf-8"))
                login_cookie_header = login_response.getheader("Set-Cookie") or ""

                super_login_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                super_login_conn.request(
                    "POST",
                    "/api/auth/login",
                    body=json.dumps({"email": "xujingbo-jk@qifu.com", "password": TEST_DEVELOPMENT_LOGIN_PASSWORD, "institution": "华兴银行"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                super_login_response = super_login_conn.getresponse()
                super_login_payload = json.loads(super_login_response.read().decode("utf-8"))

                register_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                register_conn.request(
                    "POST",
                    "/api/auth/register",
                    body=json.dumps(
                        {
                            "name": "测试操作员",
                            "email": "operator@example.com",
                            "institution": "郑州银行",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                register_response = register_conn.getresponse()
                register_payload = json.loads(register_response.read().decode("utf-8"))
                register_cookie_header = register_response.getheader("Set-Cookie") or ""
                register_cookie = register_cookie_header.split(";", 1)[0]

                nav_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                nav_conn.request(
                    "GET",
                    "/api/navigation",
                    headers={"Cookie": register_cookie},
                )
                nav_response = nav_conn.getresponse()
                nav_payload = json.loads(nav_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(login_response.status, 200)
        self.assertEqual(login_payload["user"]["id"], "u_lina")
        self.assertEqual(login_payload["institutions"], ["华兴银行"])
        self.assertEqual(login_payload["tenant_id"], normalize_tenant_id("华兴银行"))
        self.assertNotIn("token", login_payload)
        login_cookie = SimpleCookie()
        login_cookie.load(login_cookie_header)
        self.assertTrue(login_cookie["sda_session"]["httponly"])
        self.assertEqual(verify_session_token(login_cookie["sda_session"].value).user_id, "u_lina")
        self.assertEqual(super_login_response.status, 200)
        self.assertEqual(super_login_payload["user"]["id"], "u_super_admin")
        self.assertEqual(super_login_payload["user"]["name"], "胥京波")
        self.assertEqual(super_login_payload["user"]["email"], "xujingbo-jk@qifu.com")
        self.assertTrue(super_login_payload["is_super_admin"])

        self.assertEqual(register_response.status, 201)
        self.assertEqual(
            register_payload["user"]["tenantRoles"],
            [{"tenant": "郑州银行", "tenantId": normalize_tenant_id("郑州银行"), "role": "操作员"}],
        )
        self.assertEqual(register_payload["institutions"], ["郑州银行"])
        self.assertEqual(register_payload["tenant_id"], normalize_tenant_id("郑州银行"))
        self.assertEqual(nav_response.status, 200)
        self.assertEqual(nav_payload["user_id"], "u_operator")
        self.assertEqual(nav_payload["tenant_id"], normalize_tenant_id("郑州银行"))
        self.assertNotIn("settings.users", nav_payload["menu_keys"])

    def test_access_user_grants_support_multi_tenant_and_multiple_institution_admins(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                multi_role_user = {
                    "id": "",
                    "name": "多机构操作员",
                    "department": "运营中心",
                    "status": "active",
                    "lastLogin": "未登录",
                    "email": "multi-operator@example.com",
                    "tenantRoles": [
                        {"tenant": "郑州银行", "role": "操作员"},
                        {"tenant": "南京银行", "role": "操作员"},
                    ],
                }
                multi_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                multi_conn.request(
                    "POST",
                    "/api/access/user",
                    body=json.dumps(
                        {
                            "user_id": "u_super_admin",
                            "tenant_id": normalize_tenant_id("华兴银行"),
                            "user": multi_role_user,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                multi_response = multi_conn.getresponse()
                multi_payload = json.loads(multi_response.read().decode("utf-8"))

                duplicate_admin_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                duplicate_admin_conn.request(
                    "POST",
                    "/api/access/user",
                    body=json.dumps(
                        {
                            "user_id": "u_super_admin",
                            "tenant_id": normalize_tenant_id("华兴银行"),
                            "user": {
                                **multi_role_user,
                                "id": "",
                                "email": "second-admin@example.com",
                                "name": "第二管理员",
                                "tenantRoles": [{"tenant": "华兴银行", "role": "管理员"}],
                            },
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                duplicate_admin_response = duplicate_admin_conn.getresponse()
                duplicate_admin_payload = json.loads(duplicate_admin_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(multi_response.status, 200)
        self.assertEqual(
            multi_payload["user"]["tenantRoles"],
            [
                {"tenant": "郑州银行", "tenantId": normalize_tenant_id("郑州银行"), "role": "操作员"},
                {"tenant": "南京银行", "tenantId": normalize_tenant_id("南京银行"), "role": "操作员"},
            ],
        )
        self.assertEqual(duplicate_admin_response.status, 200)
        self.assertEqual(
            duplicate_admin_payload["user"]["tenantRoles"],
            [{"tenant": "华兴银行", "tenantId": normalize_tenant_id("华兴银行"), "role": "管理员"}],
        )

    def test_http_metric_dictionary_is_tenant_scoped(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")
                metric = {
                    "metricId": "M90000",
                    "metricName": "测试指标",
                    "definition": "测试口径",
                    "valueLogic": "test_field",
                    "sourceTable": "test_table",
                    "dimension": "机构",
                    "description": "消费贷场景下用于验证指标字典持久化。经营贷场景下用于验证租户隔离。",
                    "applicationScene": "",
                    "systemSource": "",
                    "statTime": "",
                    "referenceDocument": "",
                }
                put_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                put_conn.request(
                    "PUT",
                    "/api/metric-dictionary",
                    body=json.dumps(
                        {
                            "user_id": "u_lina",
                            "tenant_id": tenant_id,
                            "metrics": [metric],
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                put_response = put_conn.getresponse()
                put_payload = json.loads(put_response.read().decode("utf-8"))

                duplicate_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                duplicate_conn.request(
                    "POST",
                    "/api/metric-dictionary",
                    body=json.dumps(
                        {
                            "user_id": "u_lina",
                            "tenant_id": tenant_id,
                            "metric": {**metric, "metricId": "M90001"},
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                duplicate_response = duplicate_conn.getresponse()
                duplicate_payload = json.loads(duplicate_response.read().decode("utf-8"))

                shared_metric_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                shared_metric_conn.request(
                    "POST",
                    "/api/metric-dictionary",
                    body=json.dumps(
                        {
                            "user_id": "u_super_admin",
                            "tenant_id": tenant_id,
                            "metric": {
                                **metric,
                                "metricId": "M90002",
                                "metricName": "跨机构可见指标",
                                "visibleInstitutions": ["广州银行"],
                            },
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                shared_metric_response = shared_metric_conn.getresponse()
                shared_metric_payload = json.loads(shared_metric_response.read().decode("utf-8"))

                get_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                get_conn.request("GET", f"/api/metric-dictionary?tenant_id={quote(tenant_id)}&user_id=u_lina")
                get_response = get_conn.getresponse()
                get_payload = json.loads(get_response.read().decode("utf-8"))

                other_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                other_conn.request(
                    "GET",
                    f"/api/metric-dictionary?tenant_id={quote(normalize_tenant_id('广州银行'))}&user_id=u_wangqiang",
                )
                other_response = other_conn.getresponse()
                other_payload = json.loads(other_response.read().decode("utf-8"))

                shared_visible_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                shared_visible_conn.request(
                    "GET",
                    f"/api/metric-dictionary?tenant_id={quote(normalize_tenant_id('广州银行'))}&user_id=u_wangqiang",
                )
                shared_visible_response = shared_visible_conn.getresponse()
                shared_visible_payload = json.loads(shared_visible_response.read().decode("utf-8"))

                denied_delete_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                denied_delete_conn.request(
                    "DELETE",
                    f"/api/metric-dictionary?tenant_id={quote(tenant_id)}&user_id=u_zhaomin&metric_id=M90000",
                )
                denied_delete_response = denied_delete_conn.getresponse()
                denied_delete_payload = json.loads(denied_delete_response.read().decode("utf-8"))

                delete_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                delete_conn.request(
                    "DELETE",
                    f"/api/metric-dictionary?tenant_id={quote(tenant_id)}&user_id=u_lina&metric_id=M90000",
                )
                delete_response = delete_conn.getresponse()
                delete_payload = json.loads(delete_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(put_response.status, 200)
            self.assertEqual(put_payload["count"], 1)
            self.assertEqual(duplicate_response.status, 400)
            self.assertEqual(duplicate_payload["error"], "invalid_request")
            self.assertEqual(shared_metric_response.status, 200)
            self.assertEqual(shared_metric_payload["metric"]["visibleInstitutions"], ["广州银行"])
            self.assertEqual(get_response.status, 200)
            self.assertIn("M90000", {metric["metricId"] for metric in get_payload["metrics"]})
            self.assertEqual(other_response.status, 200)
            # A visibility rule is not a cross-tenant data-asset grant. The
            # left navigation tenant is the hard boundary for the system's
            # metric dictionary and self-analysis picker.
            self.assertEqual(other_payload["metrics"], [])
            self.assertEqual(shared_visible_response.status, 200)
            self.assertEqual(shared_visible_payload["metrics"], [])
            self.assertEqual(denied_delete_response.status, 403)
            self.assertEqual(denied_delete_payload["error"], "permission_denied")
            self.assertEqual(delete_response.status, 200)
            self.assertTrue(delete_payload["deleted"])

    def test_metric_visibility_rows_drive_sqlite_lookup(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/api.sqlite"
            server = create_server("127.0.0.1", 0, db_path)
            tenant_id = normalize_tenant_id("华兴银行")
            try:
                saved = server.services.metric_dictionary_store.upsert(
                    tenant_id,
                    {
                        "metricId": "M_VISIBILITY",
                        "metricName": "角色可见指标",
                        "definition": "验证可见性明细表",
                        "visibleInstitutions": ["广州银行"],
                        "visibleRoles": ["管理员"],
                    },
                    updated_by="u_super_admin",
                )
                visible_rows = server.services.metric_dictionary_store._conn.execute(
                    """
                    SELECT owner_tenant_id, metric_id, visible_tenant_id, visible_role_name
                    FROM platform_metric_visibility
                    WHERE owner_tenant_id = ? AND metric_id = ?
                    """,
                    (tenant_id, "M_VISIBILITY"),
                ).fetchall()
                visible_for_admin = server.services.metric_dictionary_store.list_visible(
                    normalize_tenant_id("广州银行"),
                    {"管理员"},
                    "u_wangqiang",
                )
                hidden_for_operator = server.services.metric_dictionary_store.list_visible(
                    normalize_tenant_id("广州银行"),
                    {"操作员"},
                    "u_other",
                )
            finally:
                server.server_close()

        self.assertEqual(saved["metricId"], "M_VISIBILITY")
        self.assertEqual(len(visible_rows), 1)
        self.assertEqual(visible_rows[0]["visible_tenant_id"], normalize_tenant_id("广州银行"))
        self.assertEqual(visible_rows[0]["visible_role_name"], "管理员")
        self.assertEqual([metric["metricId"] for metric in visible_for_admin], ["M_VISIBILITY"])
        self.assertEqual(hidden_for_operator, [])

    def test_http_system_config_shares_account_models_across_institutions_and_masks_secrets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")
                other_tenant_id = normalize_tenant_id("广州银行")
                model = {
                    "id": "model_test",
                    "name": "测试模型",
                    "modelName": "中转站",
                    "key": "test_llm",
                    "value": "bank-test",
                    "status": "available",
                }
                speech_integration = {
                    "id": "speech_test",
                    "name": "阿里云 Fun-ASR 测试",
                    "provider": "aliyun_fun_asr",
                    "apiBase": "https://example.local/api/v1",
                    "apiKey": "dashscope-demo-key",
                    "applicationModule": "realtime_voice_input",
                    "workspaceId": "ws-test",
                    "region": "cn-beijing",
                    "modelName": "fun-asr-realtime",
                    "status": "available",
                }

                model_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                model_conn.request(
                    "POST",
                    "/api/system-config/model",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "model": model},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                model_response = model_conn.getresponse()
                model_payload = json.loads(model_response.read().decode("utf-8"))

                speech_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                speech_conn.request(
                    "POST",
                    "/api/system-config/speech-integration",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "speech_integration": speech_integration},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                speech_response = speech_conn.getresponse()
                speech_payload = json.loads(speech_response.read().decode("utf-8"))

                speech_test_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                speech_test_conn.request(
                    "POST",
                    "/api/system-config/speech-integration/test",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "integration_id": "speech_test"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                speech_test_response = speech_test_conn.getresponse()
                speech_test_payload = json.loads(speech_test_response.read().decode("utf-8"))

                updated_model = {
                    **model,
                    "key": "test_llm_updated",
                    "value": "zetatechs-demo-key",
                }
                update_model_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                update_model_conn.request(
                    "POST",
                    "/api/system-config/model",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "model": updated_model},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                update_model_response = update_model_conn.getresponse()
                update_model_payload = json.loads(update_model_response.read().decode("utf-8"))

                model_test_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                model_test_conn.request(
                    "POST",
                    "/api/system-config/model/test",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "model_id": "model_test"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                model_test_response = model_test_conn.getresponse()
                model_test_payload = json.loads(model_test_response.read().decode("utf-8"))

                get_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                get_conn.request("GET", f"/api/system-config?tenant_id={quote(tenant_id)}&user_id=u_super_admin")
                get_response = get_conn.getresponse()
                get_payload = json.loads(get_response.read().decode("utf-8"))

                audit_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                audit_conn.request("GET", f"/api/audit-logs?tenant_id={quote(tenant_id)}&user_id=u_super_admin")
                audit_response = audit_conn.getresponse()
                audit_payload = json.loads(audit_response.read().decode("utf-8"))

                other_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                other_conn.request("GET", f"/api/system-config?tenant_id={quote(other_tenant_id)}&user_id=u_super_admin")
                other_response = other_conn.getresponse()
                other_payload = json.loads(other_response.read().decode("utf-8"))

                delete_model_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                delete_model_conn.request(
                    "DELETE",
                    f"/api/system-config/model?tenant_id={quote(tenant_id)}&user_id=u_super_admin&model_id=model_test",
                )
                delete_model_response = delete_model_conn.getresponse()
                delete_model_payload = json.loads(delete_model_response.read().decode("utf-8"))

                delete_speech_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                delete_speech_conn.request(
                    "DELETE",
                    f"/api/system-config/speech-integration?tenant_id={quote(tenant_id)}&user_id=u_super_admin&integration_id=speech_test",
                )
                delete_speech_response = delete_speech_conn.getresponse()
                delete_speech_payload = json.loads(delete_speech_response.read().decode("utf-8"))

            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(model_response.status, 200)
            self.assertEqual(model_payload["model"]["id"], "model_test")
            self.assertEqual(model_payload["model"]["value"], "******")
            self.assertEqual(update_model_response.status, 200)
            self.assertEqual(update_model_payload["model"]["key"], "test_llm_updated")
            self.assertEqual(update_model_payload["model"]["value"], "******")
            self.assertEqual(update_model_payload["model"]["modelName"], "中转站")
            self.assertEqual(model_test_response.status, 200)
            self.assertFalse(model_test_payload["result"]["callable"])
            self.assertEqual(model_test_payload["result"]["status"], "mock")
            self.assertEqual(model_test_payload["result"]["available_models"], [])
            self.assertEqual(speech_response.status, 200)
            self.assertEqual(speech_payload["speech_integration"]["id"], "speech_test")
            self.assertEqual(speech_payload["speech_integration"]["apiKey"], "******")
            self.assertEqual(speech_payload["speech_integration"]["applicationModule"], "global_voice_model")
            self.assertNotIn("workspaceId", speech_payload["speech_integration"])
            self.assertNotIn("region", speech_payload["speech_integration"])
            self.assertNotIn("modelName", speech_payload["speech_integration"])
            self.assertEqual(speech_test_response.status, 200)
            self.assertFalse(speech_test_payload["result"]["callable"])
            self.assertEqual(speech_test_payload["result"]["status"], "mock")
            self.assertIn("api-ws/v1/inference", speech_test_payload["result"]["endpoint"])
            self.assertEqual(get_response.status, 200)
            self.assertEqual(get_payload["config_scope"], "account:u_super_admin")
            get_model = next(model for model in get_payload["models"] if model["id"] == "model_test")
            get_speech = next(integration for integration in get_payload["speech_integrations"] if integration["id"] == "speech_test")
            self.assertEqual(get_model["key"], "test_llm_updated")
            self.assertEqual(get_model["value"], "******")
            self.assertEqual(get_model["modelName"], "中转站")
            self.assertEqual(get_model["testStatus"], "mock")
            self.assertEqual(get_model["status"], "available")
            self.assertEqual(get_model["availableModels"], [])
            self.assertEqual(get_speech["provider"], "aliyun_fun_asr")
            self.assertEqual(get_speech["apiKey"], "******")
            self.assertEqual(get_speech["testStatus"], "mock")
            self.assertEqual(get_speech["status"], "available")
            self.assertEqual(get_speech["applicationModule"], "global_voice_model")
            self.assertNotIn("workspaceId", get_speech)
            self.assertNotIn("region", get_speech)
            self.assertNotIn("modelName", get_speech)
            self.assertNotIn("dashscope-demo-key", json.dumps(get_payload, ensure_ascii=False))
            self.assertNotIn("zetatechs-demo-key", json.dumps(get_payload, ensure_ascii=False))
            self.assertEqual(audit_response.status, 200)
            self.assertIn("system.model.test", {log["action"] for log in audit_payload["logs"]})
            self.assertIn("system.speech.test", {log["action"] for log in audit_payload["logs"]})
            self.assertIn("system.model.upsert", {log["action"] for log in audit_payload["logs"]})
            self.assertIn("system.speech.upsert", {log["action"] for log in audit_payload["logs"]})
            self.assertEqual(other_response.status, 200)
            self.assertEqual(other_payload["config_scope"], "account:u_super_admin")
            self.assertIn("model_test", {model["id"] for model in other_payload["models"]})
            other_model = next(model for model in other_payload["models"] if model["id"] == "model_test")
            self.assertEqual(other_model["value"], "******")
            self.assertIn("speech_test", {integration["id"] for integration in other_payload["speech_integrations"]})
            self.assertEqual(delete_model_response.status, 200)
            self.assertTrue(delete_model_payload["deleted"])
            self.assertEqual(delete_speech_response.status, 200)
            self.assertTrue(delete_speech_payload["deleted"])

    def test_http_system_config_does_not_leak_rows_owned_in_another_tenant(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            store = server.services.system_config_store
            tenant_id = normalize_tenant_id("华兴银行")
            other_tenant_id = normalize_tenant_id("郑州银行")
            account_scope = "account:u_super_admin"
            with store._conn:
                store._conn.execute("DELETE FROM platform_model_integrations WHERE tenant_id = ?", (account_scope,))
                store._conn.execute("DELETE FROM platform_speech_integrations WHERE tenant_id = ?", (account_scope,))
            store.upsert_model(
                tenant_id,
                {
                    "id": "legacy_model_owned_by_account",
                    "name": "历史账号模型",
                    "modelName": "中转站",
                    "key": "https://legacy.example/v1",
                    "value": "legacy-secret",
                    "status": "available",
                },
                updated_by="u_super_admin",
            )
            store.upsert_speech_integration(
                tenant_id,
                {
                    "id": "legacy_speech_owned_by_account",
                    "name": "历史语音模型",
                    "provider": "aliyun_fun_asr",
                    "apiBase": "https://legacy-asr.example/api/v1",
                    "apiKey": "legacy-asr-secret",
                    "status": "available",
                },
                updated_by="u_super_admin",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", f"/api/system-config?tenant_id={quote(other_tenant_id)}&user_id=u_super_admin")
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["config_scope"], "account:u_super_admin")
        self.assertNotIn("legacy_model_owned_by_account", {model["id"] for model in payload["models"]})
        self.assertNotIn("legacy_speech_owned_by_account", {integration["id"] for integration in payload["speech_integrations"]})
        self.assertNotIn("legacy-secret", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("legacy-asr-secret", json.dumps(payload, ensure_ascii=False))

    def test_transient_model_test_failure_preserves_last_known_good_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")
                model = {
                    "id": "model_preserve_options",
                    "name": "保留选项测试模型",
                    "modelName": "中转站",
                    "key": "https://relay.example.invalid/v1",
                    "value": "bad-key",
                    "availableModels": ["qwen-plus", "deepseek-v3"],
                    "enabledModels": ["qwen-plus"],
                    "testStatus": "connected",
                    "lastTestedAt": "2026-07-08T00:00:00+00:00",
                    "testResponse": "previous-ok",
                    "status": "available",
                }
                model_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                model_conn.request(
                    "POST",
                    "/api/system-config/model",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "model": model},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(model_conn.getresponse().status, 200)

                with patch(
                    "backend.platform.api.routes.settings.test_model_integration",
                    return_value={
                        "model_id": "model_preserve_options",
                        "model_name": "保留选项测试模型",
                        "source": "中转站",
                        "callable": False,
                        "status": "failed",
                        "message": "模型接入测试失败",
                        "available_models": [],
                        "response_preview": "",
                        "tested_at": "2026-07-09T00:00:00+00:00",
                        "error_code": "request_timeout",
                        "transient": True,
                    },
                ):
                    test_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    test_conn.request(
                        "POST",
                        "/api/system-config/model/test",
                        body=json.dumps(
                            {"user_id": "u_super_admin", "tenant_id": tenant_id, "model_id": "model_preserve_options"},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    test_payload = json.loads(test_conn.getresponse().read().decode("utf-8"))

                saved_model = test_payload["model"]
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertTrue(test_payload["result"]["preserved_last_known_good"])
        self.assertEqual(saved_model["testStatus"], "connected")
        self.assertEqual(saved_model["status"], "available")
        self.assertEqual(saved_model["lastTestedAt"], "2026-07-08T00:00:00+00:00")
        self.assertEqual(saved_model["testResponse"], "previous-ok")
        self.assertEqual(saved_model["availableModels"], ["qwen-plus", "deepseek-v3"])
        self.assertEqual(saved_model["enabledModels"], ["qwen-plus"])

    def test_first_failed_model_test_keeps_saved_integration_draft(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")
                model = {
                    "id": "model_dns_failure",
                    "name": "DNS 失败模型",
                    "modelName": "中转站",
                    "key": "https://relay.example.invalid/v1",
                    "value": "configured-key",
                    "applicationModule": "global_text_model",
                    "status": "available",
                }
                save_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                save_conn.request(
                    "POST",
                    "/api/system-config/model",
                    body=json.dumps({"user_id": "u_super_admin", "tenant_id": tenant_id, "model": model}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(save_conn.getresponse().status, 200)
                with patch(
                    "backend.platform.api.routes.settings.test_model_integration",
                    return_value={
                        "model_id": "model_dns_failure",
                        "model_name": "DNS 失败模型",
                        "source": "中转站",
                        "callable": False,
                        "status": "failed",
                        "message": "服务器无法解析模型地址域名",
                        "available_models": [],
                        "response_preview": "",
                        "tested_at": "2026-08-07T00:00:00+00:00",
                        "error_code": "dns_resolution_failed",
                        "transient": False,
                    },
                ):
                    test_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    test_conn.request(
                        "POST",
                        "/api/system-config/model/test",
                        body=json.dumps({"user_id": "u_super_admin", "tenant_id": tenant_id, "model_id": "model_dns_failure"}, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    response = test_conn.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["model"]["status"], "draft")
        self.assertEqual(payload["model"]["testStatus"], "failed")

    def test_model_integrations_allow_same_api_address_but_require_unique_name(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")

                def save_model(model: dict[str, Any]) -> tuple[int, dict[str, Any]]:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "POST",
                        "/api/system-config/model",
                        body=json.dumps(
                            {"user_id": "u_super_admin", "tenant_id": tenant_id, "model": model},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    response = conn.getresponse()
                    return response.status, json.loads(response.read().decode("utf-8"))

                first_status, first_payload = save_model({
                    "id": "model_same_endpoint_gpt",
                    "name": "GPT",
                    "modelName": "中转站",
                    "key": "http://www.flaiverse.com:32520/",
                    "value": "real-key-1",
                    "availableModels": ["gpt-5.5"],
                    "enabledModels": ["gpt-5.5"],
                    "status": "available",
                })
                second_status, second_payload = save_model({
                    "id": "model_same_endpoint_claude",
                    "name": "Claude",
                    "modelName": "中转站",
                    "key": "http://www.flaiverse.com:32520/",
                    "value": "real-key-2",
                    "availableModels": ["claude-sonnet-4-6"],
                    "enabledModels": ["claude-sonnet-4-6"],
                    "status": "available",
                })
                duplicate_status, duplicate_payload = save_model({
                    "id": "model_duplicate_name",
                    "name": " GPT ",
                    "modelName": "中转站",
                    "key": "https://api.zetatechs.com",
                    "value": "real-key-3",
                    "availableModels": ["deepseek-v4-flash"],
                    "enabledModels": ["deepseek-v4-flash"],
                    "status": "available",
                })

                get_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                get_conn.request("GET", f"/api/system-config?tenant_id={quote(tenant_id)}&user_id=u_super_admin")
                get_payload = json.loads(get_conn.getresponse().read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(first_status, 200)
        self.assertEqual(first_payload["model"]["name"], "GPT")
        self.assertEqual(second_status, 200)
        self.assertEqual(second_payload["model"]["key"], "http://www.flaiverse.com:32520/")
        self.assertEqual(duplicate_status, 400)
        self.assertEqual(duplicate_payload["message"], "模型名称已存在，请使用不同的模型名称。")
        self.assertEqual(
            {model["name"] for model in get_payload["models"] if model["id"] in {"model_same_endpoint_gpt", "model_same_endpoint_claude"}},
            {"GPT", "Claude"},
        )

    def test_successful_model_test_preserves_enabled_models(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("华兴银行")
                model = {
                    "id": "model_preserve_enabled_success",
                    "name": "GPT",
                    "modelName": "中转站",
                    "key": "https://relay.example.invalid/v1",
                    "value": "real-key",
                    "availableModels": ["gpt-5.5", "codex-auto-review"],
                    "enabledModels": ["gpt-5.5", "codex-auto-review"],
                    "status": "available",
                }
                model_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                model_conn.request(
                    "POST",
                    "/api/system-config/model",
                    body=json.dumps(
                        {"user_id": "u_super_admin", "tenant_id": tenant_id, "model": model},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(model_conn.getresponse().status, 200)

                with patch(
                    "backend.platform.api.routes.settings.test_model_integration",
                    return_value={
                        "model_id": "model_preserve_enabled_success",
                        "model_name": "GPT",
                        "source": "中转站",
                        "callable": True,
                        "status": "connected",
                        "message": "模型接入测试成功",
                        "available_models": ["codex-auto-review", "gpt-5.5", "gpt-5.6-sol"],
                        "response_preview": "ok",
                        "tested_at": "2026-07-09T00:00:00+00:00",
                        "used_model": "codex-auto-review",
                    },
                ):
                    test_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    test_conn.request(
                        "POST",
                        "/api/system-config/model/test",
                        body=json.dumps(
                            {"user_id": "u_super_admin", "tenant_id": tenant_id, "model_id": "model_preserve_enabled_success"},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    test_payload = json.loads(test_conn.getresponse().read().decode("utf-8"))

                saved_model = test_payload["model"]
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(saved_model["testStatus"], "connected")
        self.assertEqual(saved_model["availableModels"], ["codex-auto-review", "gpt-5.5", "gpt-5.6-sol"])
        self.assertEqual(saved_model["enabledModels"], ["gpt-5.5", "codex-auto-review"])

    def test_http_report_analysis_results_are_tenant_scoped(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            attach_governed_test_warehouse(server.services)
            analysis = run_analysis(
                server.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="2026年6月各分行放款金额排名TOP10",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                result = {
                    "id": "analysis_report_case",
                    "title": "测试保存分析",
                    "query": "本月各分行放款金额排名TOP10",
                    "plan": "按机构分析",
                    "summary": "上海分行贡献较高。",
                    "visualTypes": {"primary": "bar", "secondary": "table"},
                    "savedAt": "2026-07-05 10:00:00",
                    "analysisTaskId": analysis["task_id"],
                    "visualizations": [{
                        "id": "primary",
                        "key": "primary",
                        "title": "主分析视图 · 条形图",
                        "type": "bar",
                        "config": {
                            "metricFields": ["amount"],
                            "dimensionFields": ["branch"],
                            "filters": {},
                            "filterGroups": [],
                            "sumFilteredRows": False,
                            "comboLineFields": [],
                        },
                    }],
                    "rows": [{"branch": "上海分行", "amount": 1200, "completion": "90%", "conversion": "18%"}],
                }
                save_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                save_conn.request(
                    "POST",
                    "/api/reports/analysis-result",
                    body=json.dumps({"result": result}, ensure_ascii=False).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                save_response = save_conn.getresponse()
                save_payload = json.loads(save_response.read().decode("utf-8"))

                list_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                list_conn.request(
                    "GET",
                    "/api/reports/analysis-results",
                    headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"},
                )
                list_response = list_conn.getresponse()
                list_payload = json.loads(list_response.read().decode("utf-8"))

                other_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                other_conn.request(
                    "GET",
                    f"/api/reports/analysis-results?tenant_id={quote(normalize_tenant_id('广州银行'))}&user_id=u_super_admin",
                )
                other_response = other_conn.getresponse()
                other_payload = json.loads(other_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(save_response.status, 200)
            self.assertEqual(save_payload["result"]["id"], "analysis_report_case")
            self.assertEqual(list_response.status, 200)
            self.assertEqual(list_payload["count"], 1)
            self.assertEqual(list_payload["results"][0]["summary"], "上海分行贡献较高。")
            self.assertEqual(list_payload["results"][0]["visualizations"][0]["config"]["metricFields"], ["amount"])
            self.assertEqual(other_response.status, 200)
            self.assertEqual(other_payload["results"], [])

    def test_http_report_comments_are_persisted_by_report(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                comments = [
                    {
                        "id": "comment_case",
                        "targetId": "block_a",
                        "targetLabel": "业绩与业务波动",
                        "selectedText": "放款金额",
                        "author": "当前用户",
                        "time": "刚刚",
                        "text": "请补充机构拆解。",
                        "status": "resolved",
                        "resolvedAt": "2026/07/07 19:40",
                        "resolvedBy": "u_super_admin",
                        "resolvedReason": "manual",
                        "targetKind": "paragraph",
                        "replies": [
                            {"id": "reply_case", "author": "当前用户", "time": "刚刚", "text": "已补充。"}
                        ],
                    }
                ]
                put_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                put_conn.request(
                    "PUT",
                    "/api/reports/comments",
                    body=json.dumps(
                        {"report_id": "report_weekly_demo", "comments": comments},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                put_response = put_conn.getresponse()
                put_payload = json.loads(put_response.read().decode("utf-8"))

                get_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                get_conn.request(
                    "GET",
                    "/api/reports/comments?report_id=report_weekly_demo",
                    headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"},
                )
                get_response = get_conn.getresponse()
                get_payload = json.loads(get_response.read().decode("utf-8"))

                empty_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                empty_conn.request(
                    "GET",
                    "/api/reports/comments?report_id=another_report",
                    headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"},
                )
                empty_response = empty_conn.getresponse()
                empty_payload = json.loads(empty_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(put_response.status, 200)
            self.assertEqual(put_payload["count"], 1)
            self.assertEqual(get_response.status, 200)
            self.assertEqual(get_payload["comments"][0]["text"], "请补充机构拆解。")
            self.assertEqual(get_payload["comments"][0]["status"], "resolved")
            self.assertEqual(get_payload["comments"][0]["resolvedAt"], "2026/07/07 19:40")
            self.assertEqual(get_payload["comments"][0]["resolvedBy"], "u_super_admin")
            self.assertEqual(get_payload["comments"][0]["resolvedReason"], "manual")
            self.assertEqual(get_payload["comments"][0]["targetKind"], "paragraph")
            self.assertEqual(get_payload["comments"][0]["replies"][0]["text"], "已补充。")
            self.assertEqual(empty_response.status, 200)
            self.assertEqual(empty_payload["comments"], [])

    def test_secret_envelope_requires_key_in_strict_mode(self) -> None:
        with patch.dict("os.environ", {"SMART_DATA_AGENT_AUTH_MODE": "strict"}, clear=True):
            with self.assertRaises(SecretConfigurationError):
                encrypt_secret("raw-secret")

    def test_kms_command_secret_provider_round_trips(self) -> None:
        with TemporaryDirectory() as tmpdir:
            command_path = Path(tmpdir) / "kms_command.py"
            command_path.write_text(
                """
import base64
import sys

action = sys.argv[1]
payload = sys.stdin.read()
if action == "encrypt":
    print("kms:" + base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii"))
elif action == "decrypt":
    print(base64.urlsafe_b64decode(payload.removeprefix("kms:").encode("ascii")).decode("utf-8"))
else:
    raise SystemExit(2)
""".strip(),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "SMART_DATA_AGENT_SECRET_PROVIDER": "kms",
                    "SMART_DATA_AGENT_KMS_COMMAND": f"python3 {command_path}",
                },
            ):
                envelope = encrypt_secret("raw-secret")
                clear_text = decrypt_secret(envelope)

        self.assertTrue(envelope.startswith("kms:"))
        self.assertEqual(clear_text, "raw-secret")

    def test_metric_access_filters_authorized_metrics_before_query(self) -> None:
        repository = self.services.permission_broker.enforcer.repository
        repository.seed(
            roles=[Role("role:tenant_demo:loan_amount_only", "tenant_demo", "放款只读", RoleLevel.OPERATOR)],
            assignments=[RoleAssignment("u_metric_limited", "tenant_demo", "role:tenant_demo:loan_amount_only")],
            policies=[
                PermissionPolicy(
                    "role:tenant_demo:loan_amount_only",
                    "tenant_demo",
                    "skill:supersonic.query",
                    "execute",
                ),
                PermissionPolicy(
                    "role:tenant_demo:loan_amount_only",
                    "tenant_demo",
                    "metric:*",
                    "read",
                    attrs={
                        "tenant_id": "tenant_demo",
                        "metric_ids": ["loan_amount", "drawdown_rate"],
                        "fields": ["branch_name", "product_line", "loan_amount", "drawdown_rate", "metric_value", "metric_id"],
                    },
                ),
            ],
        )

        allowed = run_analysis(
            self.services,
            user_id="u_metric_limited",
            tenant_id="tenant_demo",
            question="2026年6月各分行放款金额排名TOP10",
        )
        with self.assertRaises(PermissionError):
            run_analysis(
                self.services,
                user_id="u_metric_limited",
                tenant_id="tenant_demo",
                question="消费贷和经营贷的逾期率对比趋势",
            )

        self.assertTrue(allowed["skill_results"][0]["data"])
        self.assertEqual(
            allowed["skill_results"][0]["semantic_info"]["metric_access"]["allowed_metric_ids"],
            ["drawdown_rate", "loan_amount"],
        )

    def test_supersonic_http_client_translates_remote_response(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSupersonicHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_address[1]}/semantic/query"
            with patch(
                "backend.platform.semantic.supersonic_client.safe_urlopen",
                side_effect=lambda http_request, timeout, context: urllib_request.urlopen(http_request, timeout=timeout),
            ):
                client = SupersonicHTTPClient(endpoint=endpoint, timeout_seconds=2, retries=0)
                result = client.query(
                    SemanticQueryRequest(
                        question="远程语义查询",
                        tenant_id="tenant_demo",
                        user_id="u_super_admin",
                        dataset_id="loan_operation_mart",
                        metrics=("loan_amount",),
                        dimensions=("branch_name",),
                    )
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(FakeSupersonicHandler.last_payload["metrics"], ["loan_amount"])
        self.assertEqual(result.data[0]["branch_name"], "远程分行")
        self.assertEqual(result.parameters["tenant_id"], "tenant_demo")
        self.assertEqual(result.semantic_info["supersonic_client"], "http")

    def test_supersonic_client_falls_back_to_local_when_remote_fails(self) -> None:
        client = FallbackSupersonicClient(
            BrokenSupersonicClient(),
            InMemorySupersonicClient(build_governed_test_warehouse()),
        )
        result = client.query(
            SemanticQueryRequest(
                question="本周放款金额是多少",
                tenant_id="tenant_demo",
                user_id="u_super_admin",
                dataset_id="loan_operation_mart",
                metrics=("loan_amount",),
                dimensions=("branch_name",),
            )
        )

        self.assertTrue(result.semantic_info["fallback"])
        self.assertEqual(result.semantic_info["supersonic_client"], "fallback")
        self.assertEqual(result.semantic_info["fallback_reason"], "primary_semantic_service_unavailable")
        self.assertTrue(result.data)

    def test_analysis_runtime_summary_counts_fallback(self) -> None:
        self.services.semantic_service.client = FallbackSupersonicClient(
            BrokenSupersonicClient(),
            InMemorySupersonicClient(build_governed_test_warehouse()),
        )
        response = run_analysis(
            self.services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="本周放款金额是多少",
        )
        runtime_summary = self.services.task_repository.runtime_summary()

        self.assertTrue(response["skill_results"][0]["semantic_info"]["fallback"])
        self.assertEqual(runtime_summary["fallback_count"], 1)
        self.assertEqual(runtime_summary["ok_count"], 1)

    def test_remote_semantic_defaults_to_fail_closed_without_local_fallback(self) -> None:
        with patch(
            "backend.platform.bootstrap.build_data_warehouse_from_env",
            return_value=(build_governed_test_warehouse(), "governed_test_warehouse"),
        ), patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_SUPERSONIC_URL": "http://127.0.0.1:9/semantic/query",
                "SMART_DATA_AGENT_SUPERSONIC_FALLBACK_MODE": "",
            },
        ):
            client, client_mode, fallback_mode, data_source_mode = build_supersonic_client_from_env()

        self.assertIsInstance(client, SupersonicHTTPClient)
        self.assertEqual(client_mode, "http")
        self.assertEqual(fallback_mode, "disabled")
        self.assertEqual(data_source_mode, "remote_semantic")

    def test_remote_semantic_uses_local_fallback_only_when_explicit(self) -> None:
        with patch(
            "backend.platform.bootstrap.build_data_warehouse_from_env",
            return_value=(build_governed_test_warehouse(), "governed_test_warehouse"),
        ), patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_SUPERSONIC_URL": "http://127.0.0.1:9/semantic/query",
                "SMART_DATA_AGENT_SUPERSONIC_FALLBACK_MODE": "local",
            },
        ):
            client, client_mode, fallback_mode, data_source_mode = build_supersonic_client_from_env()

        self.assertIsInstance(client, FallbackSupersonicClient)
        self.assertEqual(client_mode, "http")
        self.assertEqual(fallback_mode, "explicit_local")
        self.assertIn("explicit_governed_test_warehouse_fallback", data_source_mode)

    def test_mcp_gateway_sanitizes_results_and_checks_permission(self) -> None:
        gateway = MCPGateway(
            self.services.permission_broker,
            self.services.trace_recorder,
            approval_store=self.services.approval_store,
        )
        gateway.register_server(
            MCPServerSpec(
                server_id="database",
                name="Database MCP Server",
                server_type="database",
                endpoint="mcp://database",
                exposed_tools=("query",),
                risk_level="high",
            ),
            {
                "query": lambda call: MCPToolResult(
                    server_id=call.server_id,
                    tool_name=call.tool_name,
                    output={"rows": [{"metric_value": 1}], "password": "raw-secret", "api_token": "raw-token"},
                )
            },
        )

        arguments = {"sql": "select 1"}
        approval_id = self.approved_mcp_call("database.query", arguments)
        result = gateway.call(
            MCPToolCall(
                server_id="database",
                tool_name="query",
                context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant_demo"),
                arguments=arguments,
                agent_id="data_query",
                approval_id=approval_id,
            )
        )

        self.assertEqual(result.output["password"], "***")
        self.assertEqual(result.output["api_token"], "***")
        self.assertEqual(result.output["rows"], [{"metric_value": 1}])

    def test_local_mcp_registry_uses_governed_runtime_handlers(self) -> None:
        servers = {server["server_id"]: server for server in self.services.mcp_gateway.list_servers()}
        tools = {tool["resource"] for tool in self.services.mcp_gateway.list_tools()}
        schema_approval_id = self.approved_mcp_call("database.schema", {})
        schema_result = self.services.mcp_gateway.call(
            MCPToolCall(
                server_id="database",
                tool_name="schema",
                context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant_demo"),
                agent_id="data_query",
                approval_id=schema_approval_id,
            )
        )
        ingest_result = self.services.mcp_gateway.call(
            MCPToolCall(
                server_id="knowledge",
                tool_name="ingest",
                context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant_demo"),
                agent_id="planner",
                arguments={
                    "doc_id": "kd_mcp_case",
                    "title": "MCP知识写入",
                    "content": "通过MCP写入的机构经营知识。",
                    "tags": ["MCP知识"],
                },
            )
        )
        search_result = self.services.mcp_gateway.call(
            MCPToolCall(
                server_id="knowledge",
                tool_name="search",
                context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant_demo"),
                arguments={"query": "MCP知识"},
                agent_id="planner",
            )
        )

        self.assertIn("database", servers)
        self.assertIn("knowledge", servers)
        self.assertIn("mcp:database.query", tools)
        self.assertIn("mcp:knowledge.search", tools)
        self.assertTrue(schema_result.output["datasets"])
        self.assertEqual(ingest_result.output["doc_id"], "kd_mcp_case")
        self.assertEqual(ingest_result.output["status"], "review")
        self.assertEqual(search_result.output["hits"], [])
        self.services.knowledge_store.review_document("tenant_demo", "kd_mcp_case", "approve", "u_reviewer")
        published_search = self.services.mcp_gateway.call(
            MCPToolCall(
                server_id="knowledge",
                tool_name="search",
                context=ExecutionContext(user_id="u_super_admin", tenant_id="tenant_demo"),
                arguments={"query": "MCP知识"},
                agent_id="planner",
            )
        )
        self.assertEqual(published_search.output["hits"][0]["doc_id"], "kd_mcp_case")
        self.assertTrue(published_search.output["hits"][0]["chunk_id"])

    def test_http_mcp_api_lists_and_calls_governed_tools(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            attach_governed_test_warehouse(server.services)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                mcp_arguments = {
                    "dataset_id": "loan_operation_mart",
                    "metric": "loan_amount",
                    "dimension": "branch_name",
                }
                approval = server.services.approval_store.request(
                    "tenant_demo",
                    "mcp",
                    "database.query",
                    "execute",
                    approval_input_hash(mcp_arguments),
                    "u_super_admin",
                )
                server.services.approval_store.review(
                    "tenant_demo", approval["approval_id"], "u_reviewer", "approved"
                )
                servers_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                servers_conn.request("GET", "/api/mcp/servers", headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"})
                servers_response = servers_conn.getresponse()
                servers_payload = json.loads(servers_response.read().decode("utf-8"))

                tools_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                tools_conn.request("GET", "/api/mcp/tools", headers={"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"})
                tools_response = tools_conn.getresponse()
                tools_payload = json.loads(tools_response.read().decode("utf-8"))

                call_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                call_conn.request(
                    "POST",
                    "/api/mcp/call",
                    body=json.dumps(
                        {
                            "server_id": "database",
                            "tool_name": "query",
                            "agent_id": "data_query",
                            "arguments": mcp_arguments,
                            "approval_id": approval["approval_id"],
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-User-Id": "u_super_admin",
                        "X-Tenant-Id": "tenant_demo",
                    },
                )
                call_response = call_conn.getresponse()
                call_payload = json.loads(call_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(servers_response.status, 200)
        self.assertIn("database", {server["server_id"] for server in servers_payload["servers"]})
        self.assertEqual(tools_response.status, 200)
        self.assertIn("mcp:database.query", {tool["resource"] for tool in tools_payload["tools"]})
        self.assertEqual(call_response.status, 200)
        self.assertTrue(call_payload["output"]["rows"])
        self.assertIn("semantic_info", call_payload["output"])

    def test_mcp_streamable_http_initialize_list_call_and_origin_guard(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                base_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "X-User-Id": "u_super_admin",
                    "X-Tenant-Id": "tenant_demo",
                }

                initialize_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                initialize_conn.request(
                    "POST",
                    "/mcp",
                    body=json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "clientInfo": {"name": "test-client", "version": "1.0"},
                            },
                        }
                    ),
                    headers={**base_headers, "Mcp-Method": "initialize"},
                )
                initialize_response = initialize_conn.getresponse()
                initialize_payload = json.loads(initialize_response.read().decode("utf-8"))

                list_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                list_conn.request(
                    "POST",
                    "/mcp",
                    body=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                    headers={
                        **base_headers,
                        "Mcp-Method": "tools/list",
                        "MCP-Protocol-Version": "2025-11-25",
                    },
                )
                list_response = list_conn.getresponse()
                list_payload = json.loads(list_response.read().decode("utf-8"))

                call_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                call_conn.request(
                    "POST",
                    "/mcp",
                    body=json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {
                                "name": "knowledge.search",
                                "arguments": {"query": "loan amount", "limit": 3},
                                "_meta": {"io.smart-data-agent/agent-id": "planner"},
                            },
                        }
                    ),
                    headers={
                        **base_headers,
                        "Mcp-Method": "tools/call",
                        "Mcp-Name": "knowledge.search",
                        "MCP-Protocol-Version": "2025-11-25",
                    },
                )
                call_response = call_conn.getresponse()
                call_payload = json.loads(call_response.read().decode("utf-8"))

                get_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                get_conn.request("GET", "/mcp", headers={"Accept": "text/event-stream"})
                get_response = get_conn.getresponse()
                get_response.read()

                origin_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                origin_conn.request(
                    "POST",
                    "/mcp",
                    body=json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"}),
                    headers={
                        **base_headers,
                        "Origin": "https://evil.example",
                        "Mcp-Method": "ping",
                        "MCP-Protocol-Version": "2025-11-25",
                    },
                )
                origin_response = origin_conn.getresponse()
                origin_payload = json.loads(origin_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(initialize_response.status, 200)
        self.assertEqual(initialize_payload["result"]["protocolVersion"], "2025-11-25")
        self.assertIn("tools", initialize_payload["result"]["capabilities"])
        self.assertEqual(list_response.status, 200)
        tools = {item["name"]: item for item in list_payload["result"]["tools"]}
        self.assertIn("database.query", tools)
        self.assertIn("knowledge.search", tools)
        self.assertEqual(tools["knowledge.search"]["inputSchema"]["type"], "object")
        self.assertEqual(call_response.status, 200)
        self.assertFalse(call_payload["result"]["isError"])
        self.assertTrue(call_payload["result"]["structuredContent"]["hits"])
        self.assertEqual(get_response.status, 405)
        self.assertEqual(origin_response.status, 403)
        self.assertEqual(origin_payload["error"]["code"], -32001)

    def test_http_mcp_tools_are_filtered_by_current_permissions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                tenant_id = normalize_tenant_id("郑州银行")
                tools_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                tools_conn.request(
                    "GET",
                    "/api/mcp/tools",
                    headers={"X-User-Id": "u_zhaomin", "X-Tenant-Id": quote(tenant_id)},
                )
                tools_response = tools_conn.getresponse()
                tools_payload = json.loads(tools_response.read().decode("utf-8"))

                servers_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                servers_conn.request(
                    "GET",
                    "/api/mcp/servers",
                    headers={"X-User-Id": "u_zhaomin", "X-Tenant-Id": quote(tenant_id)},
                )
                servers_response = servers_conn.getresponse()
                servers_payload = json.loads(servers_response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        resources = {tool["resource"] for tool in tools_payload["tools"]}
        knowledge_server = next(server for server in servers_payload["servers"] if server["server_id"] == "knowledge")
        self.assertEqual(tools_response.status, 200)
        self.assertIn("mcp:database.query", resources)
        self.assertIn("mcp:knowledge.search", resources)
        self.assertNotIn("mcp:knowledge.ingest", resources)
        self.assertEqual(knowledge_server["exposed_tools"], ["search"])

    def test_http_notification_provider_callback_requires_hmac_and_stores_only_safe_summary(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ", {"SMART_DATA_AGENT_PROVIDER_CALLBACK_SECRET_SMTP_PROVIDER": "callback-secret"}
        ):
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps(
                    {
                        "provider": "smtp-provider",
                        "tenant_id": "tenant_demo",
                        "provider_event_id": "evt-http-1",
                        "provider_message_id": "unknown-message",
                        "event_type": "delivered",
                        "occurred_at": "2026-07-10T00:00:00Z",
                        "sensitive_body": "must-not-be-persisted",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                signature = hmac.new(b"callback-secret", body, hashlib.sha256).hexdigest()
                callback_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                callback_conn.request(
                    "POST",
                    "/api/provider-callbacks/notification",
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Provider-Signature": f"sha256={signature}",
                    },
                )
                callback_response = callback_conn.getresponse()
                callback_payload = json.loads(callback_response.read().decode("utf-8"))

                invalid_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                invalid_conn.request(
                    "POST",
                    "/api/provider-callbacks/notification",
                    body=body.replace(b"evt-http-1", b"evt-http-2"),
                    headers={"Content-Type": "application/json", "X-Provider-Signature": "sha256=bad"},
                )
                invalid_response = invalid_conn.getresponse()
                invalid_response.read()
                stored = server.services.automation_store._conn.execute(
                    "SELECT safe_payload, payload_hash, signature_valid FROM platform_provider_callbacks WHERE callback_id = ?",
                    (callback_payload["callback_id"],),
                ).fetchone()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(callback_response.status, 202)
        self.assertEqual(callback_payload["processing_status"], "ignored")
        self.assertEqual(invalid_response.status, 401)
        self.assertEqual(len(stored["payload_hash"]), 64)
        self.assertEqual(stored["signature_valid"], 1)
        self.assertNotIn("must-not-be-persisted", stored["safe_payload"])


if __name__ == "__main__":
    unittest.main()
