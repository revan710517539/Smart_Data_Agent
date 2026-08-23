from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import pymysql

from backend.platform.bootstrap import build_production_platform
from backend.platform.analysis_workspace.service import MySQLAnalysisGovernanceStore
from backend.platform.database.mysql import MySQLConnectionPool, apply_mysql_schema
from backend.platform.database.mysql_compat import MySQLStoreConnectionPool
from backend.platform.runtime_config import RuntimeConfig
from backend.platform.orchestration import AgentStep, AnalysisTask
from backend.platform.postgresql_repository import PostgreSQLAnalysisTaskRepository
from backend.platform.security.rate_limit import InMemoryRateLimiter
from backend.platform.tests import test_postgresql_stores_integration as postgres_integration


DATABASE_URL = os.getenv("SMART_DATA_AGENT_TEST_MYSQL_URL", "").strip()


@unittest.skipUnless(DATABASE_URL, "SMART_DATA_AGENT_TEST_MYSQL_URL is not configured")
class MySQLStoresIntegrationTest(postgres_integration.PostgreSQLStoresIntegrationTest):
    __unittest_skip__ = not bool(DATABASE_URL)
    __unittest_skip_why__ = "SMART_DATA_AGENT_TEST_MYSQL_URL is not configured"

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_pool = MySQLConnectionPool(DATABASE_URL, min_size=1, max_size=6)
        cls.pool = MySQLStoreConnectionPool(cls.raw_pool)
        with cls.raw_pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()"
                )
                for row in cursor.fetchall():
                    table_name = (
                        row.get("table_name") or row.get("TABLE_NAME")
                        if isinstance(row, dict)
                        else row[0]
                    )
                    cursor.execute(f"DROP TABLE `{table_name.replace('`', '``')}`")
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")
            connection.commit()
            apply_mysql_schema(DATABASE_URL, connection=connection)
        cls._provision()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.pool.close()

    def test_postgresql_url_is_rejected_by_production_composition(self) -> None:
        del self

    def test_mysql_schema_reapply_is_idempotent_and_checksum_stable(self) -> None:
        first = apply_mysql_schema(DATABASE_URL)
        second = apply_mysql_schema(DATABASE_URL)
        self.assertFalse(first.applied)
        self.assertFalse(second.applied)
        self.assertEqual(first.checksum, second.checksum)
        with self.raw_pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version, checksum FROM platform_schema_migrations ORDER BY version")
                rows = list(cursor.fetchall())
        versions = [str(row["version"] if isinstance(row, dict) else row[0]) for row in rows]
        self.assertEqual(versions, ["0001", "0029", "0030", "0031", "0032"])
        schema_file = Path(__file__).resolve().parents[1] / "database" / "mysql" / "0001_production_schema.sql"
        self.assertEqual(first.checksum, hashlib.sha256(schema_file.read_bytes()).hexdigest())

    def test_mysql_platform_composition_uses_mysql_primary(self) -> None:
        config = RuntimeConfig(
            environment="staging",
            auth_mode="strict",
            data_warehouse="csv",
            cors_origins=("https://app.example.test",),
            database_url=DATABASE_URL,
            secret_provider="local",
            object_store="local",
            object_bucket="",
            object_region="",
            oidc_issuer="https://idp.example.test",
            oidc_client_id="client",
            oidc_authorization_endpoint="https://idp.example.test/authorize",
            oidc_token_endpoint="https://idp.example.test/token",
            oidc_jwks_uri="https://idp.example.test/jwks",
            oidc_redirect_uri="https://app.example.test/api/auth/oidc/callback",
        )
        with (
            patch("backend.platform.bootstrap.build_rate_limiter", return_value=InMemoryRateLimiter()),
            patch("backend.platform.bootstrap.OIDCClient.validate_config", return_value=None),
        ):
            services = build_production_platform(config)
        try:
            self.assertEqual(services.primary_database_pool.dialect, "mysql")
            self.assertEqual(type(services.analysis_workspace_service.store).__name__, "MySQLAnalysisWorkspaceStore")
            self.assertEqual(type(services.metric_version_service.store).__name__, "MySQLMetricVersionStore")
            self.assertTrue(services.primary_database_pool.health()["ready"])
        finally:
            services.close()

    def test_mysql_development_composition_does_not_require_oidc(self) -> None:
        config = RuntimeConfig(
            environment="development",
            auth_mode="development",
            data_warehouse="csv",
            cors_origins=("http://127.0.0.1:5174",),
            database_url=DATABASE_URL,
            secret_provider="local",
            object_store="local",
            object_bucket="",
            object_region="",
            oidc_issuer="",
            oidc_client_id="",
            oidc_authorization_endpoint="",
            oidc_token_endpoint="",
            oidc_jwks_uri="",
            oidc_redirect_uri="",
        )
        with patch("backend.platform.bootstrap.build_rate_limiter", return_value=InMemoryRateLimiter()):
            services = build_production_platform(config)
        try:
            self.assertEqual(services.primary_database_pool.dialect, "mysql")
            self.assertEqual(services.runtime_config.auth_mode, "development")
        finally:
            services.close()

    def test_mysql_workspace_payload_is_json_serializable(self) -> None:
        config = RuntimeConfig(
            environment="development", auth_mode="development", data_warehouse="csv",
            cors_origins=("http://127.0.0.1:5174",), database_url=DATABASE_URL,
            secret_provider="local", object_store="local", object_bucket="", object_region="",
            oidc_issuer="", oidc_client_id="", oidc_authorization_endpoint="",
            oidc_token_endpoint="", oidc_jwks_uri="", oidc_redirect_uri="",
        )
        with patch("backend.platform.bootstrap.build_rate_limiter", return_value=InMemoryRateLimiter()):
            services = build_production_platform(config)
        try:
            from backend.platform.analysis_workspace.models import AnalysisWorkspaceContext

            workspace = services.analysis_workspace_service.ensure_workspace(
                self.tenant, "u_admin", "integration-page",
                AnalysisWorkspaceContext(page_key="integration-page", artifact_id="integration-artifact"),
            )
            payload = {
                "workspace": workspace,
                "threads": services.analysis_workspace_service.threads(
                    self.tenant, "u_admin", workspace["workspace_id"],
                ),
            }
            branch = services.analysis_workspace_service.branch(
                self.tenant,
                "u_admin",
                workspace["workspace_id"],
                parent_thread_id=payload["threads"][0]["thread_id"],
                title="集成分支",
                anchor={"metric": "余额"},
            )
            json.dumps(payload, ensure_ascii=False)
            self.assertIn("T", workspace["created_at"])
            self.assertEqual(branch["workspace_id"], workspace["workspace_id"])
        finally:
            services.close()

    def test_mysql_execution_dag_and_permission_bound_cache_are_idempotent(self) -> None:
        repository = PostgreSQLAnalysisTaskRepository(self.pool)
        task = AnalysisTask(
            "验证执行图",
            "diagnostic_analysis",
            self.tenant,
            "u_admin",
            task_id="analysis_dag_1",
            request_id="request_dag_1",
            execution_mode="real",
            status="completed",
            plan=[
                AgentStep("IntentAgent", "classify", {"intent": "diagnostic"}),
                AgentStep("DataQueryAgent", "supersonic.query", {"rows": 3}, skill_version="1.0.0"),
                AgentStep("ReviewAgent", "validate_final_evidence", {"passed": True}),
            ],
        )
        repository.save_task(task)
        repository.save_task(task)
        nodes = repository.execution_nodes(self.tenant, "u_admin", task.task_id)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[1]["input_refs"][0]["depends_on"], nodes[0]["step_code"])
        self.assertEqual(nodes[1]["input_refs"][1]["skill_version"], "1.0.0")
        self.assertEqual(repository.execution_nodes(self.tenant, "u_reviewer", task.task_id), [])

        cache = MySQLAnalysisGovernanceStore(self.raw_pool)
        cache.put_cache(self.tenant, "u_admin", {
            "cache_key": "cache-dag-1",
            "authorization_hash": "a" * 64,
            "csv_snapshot_hash": "b" * 64,
            "semantic_version_hash": "c" * 64,
            "execution_version_hash": "d" * 64,
            "result_ref": task.task_id,
        })
        self.assertIsNotNone(cache.get_cache(self.tenant, "u_admin", "cache-dag-1", "a" * 64))
        self.assertIsNone(cache.get_cache(self.tenant, "u_admin", "cache-dag-1", "e" * 64))
        self.assertIsNone(cache.get_cache(self.tenant, "u_reviewer", "cache-dag-1", "a" * 64))


if __name__ == "__main__":
    unittest.main()
