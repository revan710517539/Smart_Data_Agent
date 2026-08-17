from __future__ import annotations

import hashlib
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime, timezone

from backend.authz import PostgreSQLPolicyRepository, build_default_rbac_seed
from backend.authz.models import RoleAssignment
from backend.platform.application import PostgreSQLApplicationStore
from backend.platform.audit import PostgreSQLAuditEventStore
from backend.platform.assets import PostgreSQLDataAssetStore
from backend.platform.automation import PostgreSQLAutomationStore
from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool, apply_postgresql_schema
from backend.platform.ingestion import PostgreSQLAcquisitionStore
from backend.platform.knowledge import PostgreSQLKnowledgeStore
from backend.platform.governance import PostgreSQLCapabilityApprovalStore
from backend.platform.lineage import PostgreSQLLineageStore
from backend.platform.market import PostgreSQLMarketStore
from backend.platform.memory import MemoryRecord, PostgreSQLMemoryStore
from backend.platform.metrics import PostgreSQLMetricDictionaryStore
from backend.platform.postgresql_repository import PostgreSQLAnalysisTaskRepository
from backend.platform.orchestration import AnalysisTask
from backend.platform.reports import PostgreSQLReportStore
from backend.platform.settings import PostgreSQLSystemConfigStore
from backend.platform.security import PostgreSQLOIDCTransactionStore, PostgreSQLSessionStore
from backend.platform.security.rate_limit import InMemoryRateLimiter
from backend.platform.runtime_config import RuntimeConfig, RuntimeConfigurationError


DATABASE_URL = os.getenv("SMART_DATA_AGENT_TEST_POSTGRES_URL", "").strip()


@unittest.skipUnless(DATABASE_URL, "SMART_DATA_AGENT_TEST_POSTGRES_URL is not configured")
class PostgreSQLStoresIntegrationTest(unittest.TestCase):
    tenant = "tenant:integration"

    @classmethod
    def setUpClass(cls) -> None:
        import psycopg

        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
            connection.execute("CREATE SCHEMA public")
        cls.pool = PostgreSQLConnectionPool(DATABASE_URL, min_size=1, max_size=6)
        with cls.pool.connection() as connection:
            apply_postgresql_schema(DATABASE_URL, connection=connection)
        cls._provision()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.pool.close()

    @classmethod
    def _provision(cls) -> None:
        with cls.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.ensure_tenant(connection, cls.tenant, "集成测试机构")
            PostgreSQLIdentityResolver.ensure_tenant(connection, "__global__", "Global")
            for subject,email,name in (
                ("u_super_admin","super@example.test","超级管理员"),
                ("u_admin","admin@example.test","管理员"),
                ("u_reviewer","reviewer@example.test","复核员"),
                ("system","system@invalid.local","System"),
            ):
                PostgreSQLIdentityResolver.ensure_user(connection,subject,email=email,display_name=name)
            admin_key=PostgreSQLIdentityResolver.user_id(connection,"u_admin")
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO platform_org_units(tenant_id,org_code,org_name,org_type,path,status,created_by) VALUES (%s,'ROOT','集成测试机构','tenant_root','/ROOT','active',%s) RETURNING org_unit_id",(tenant_key,admin_key))
                root=_value(cursor.fetchone(),"org_unit_id",0)
                for subject in ("u_admin","u_reviewer"):
                    cursor.execute("INSERT INTO platform_user_tenant_memberships(tenant_id,user_id,org_unit_id,membership_status,joined_at) VALUES (%s,%s,%s,'active',now())",(tenant_key,PostgreSQLIdentityResolver.user_id(connection,subject),root))
            connection.commit()
        seed=build_default_rbac_seed(["integration"],())
        assignments=[*seed.assignments,
            RoleAssignment("u_admin",cls.tenant,seed.tenant_roles[0].admin_role_id,granted_by="u_super_admin"),
            RoleAssignment("u_reviewer",cls.tenant,seed.tenant_roles[0].admin_role_id,granted_by="u_super_admin")]
        PostgreSQLPolicyRepository(cls.pool).seed(seed.roles,assignments,seed.policies,seed.manageable_roles)

    def test_normalized_production_workflow(self) -> None:
        settings=PostgreSQLSystemConfigStore(self.pool)
        connection=settings.upsert_data_connection(self.tenant,{
            "id":"conn_prod","institution":"集成测试机构","sourceName":"受控经营库","sourceType":"PostgreSQL",
            "apiUrl":"postgresql://warehouse.invalid/analytics","account":"reader","password":"secret",
            "dataset":"loan_operation_mart","defaultDatabase":"analytics","enabled":True,"mockEnabled":False,
            "status":"verified","testStatus":"verified","testMessage":"verified",
        },updated_by="u_admin")
        self.assertEqual(connection["status"],"verified")

        assets=PostgreSQLDataAssetStore(self.pool)
        topic=assets.upsert_item(self.tenant,"topic_table",{
            "id":"topic_weekly","name":"周报主题表","code":"weekly_topic","description":"受控周报数据",
            "sql":"select tenant_id, sum(amount) as amount from loan_operation_mart where tenant_id = :tenant_id group by tenant_id",
            "fields":[{"fieldNameEn":"tenant_id","fieldNameCn":"租户","type":"string"},{"fieldNameEn":"amount","fieldNameCn":"金额","type":"decimal","isMetric":True}],
        },updated_by="u_admin",lifecycle_status="review")
        published=assets.review_item(self.tenant,"topic_table",topic["id"],decision="approved",reviewer_user_id="u_reviewer",expected_version=1)
        self.assertEqual(published["lifecycleStatus"],"active")

        acquisition=PostgreSQLAcquisitionStore(self.pool)
        source=acquisition.create_source(self.tenant,{"source_code":"ops","source_name":"经营系统","source_category":"smart_operation"},"u_admin")
        script=acquisition.create_script_version(self.tenant,{
            "script_code":"fetch_ops","script_name":"获取经营数据","runtime":"http","source_code":"GET https://warehouse.invalid/export",
            "input_schema":{},"output_schema":{"type":"array"},"dependency_lock":{},
        },"u_admin")
        script=acquisition.review_script_version(self.tenant,script["script_version_id"],"approved","u_reviewer")
        job=acquisition.create_job(self.tenant,{
            "source_system_id":source["source_system_id"],"script_version_id":script["script_version_id"],
            "connection_id":"conn_prod","target_dataset_id":"loan_operation_mart","topic_table_id":"weekly_topic",
            "job_code":"ops_daily","job_name":"经营数据每日获取","trigger_type":"manual","execution_mode":"offline","job_config":{},
        },"u_admin")
        acquisition_run=acquisition.queue_run(self.tenant,job["acquisition_job_id"],"run-1","manual","u_admin")
        artifact=acquisition.create_artifact(self.tenant,object_uri="s3://test/evidence.json",content_hash="a"*64,content_type="application/json",size_bytes=10,status="active",created_by="u_admin",artifact_type="json")
        acquisition.update_run(self.tenant,acquisition_run["acquisition_run_id"],status="succeeded",output_artifact_id=artifact["artifact_id"],rows_read=1,rows_written=1,source_snapshot={"snapshot_id":"s1"},quality_summary={"passed":True},finished_at=datetime.now(timezone.utc).isoformat())
        partition=acquisition.create_partition(self.tenant,dataset_id="loan_operation_mart",topic_table_id="weekly_topic",org_unit_id=None,partition_key={"date":"2026-07-10"},artifact_id=artifact["artifact_id"],source_version="v1",snapshot_at="2026-07-10T02:00:00Z",watermark_at="2026-07-10T02:00:00Z",row_count=1,data_hash="c"*64,freshness_status="fresh",acquisition_run_id=acquisition_run["acquisition_run_id"],created_by="u_admin")
        acquisition.save_quality_results(self.tenant,acquisition_run["acquisition_run_id"],[{"rule_code":"not_empty","status":"passed","score":1,"blocking":True,"observed_value":{"rows":1},"threshold":{"min":1}}],"u_admin",partition_id=partition["partition_id"])
        self.assertEqual(acquisition.latest_artifact(self.tenant,"weekly_topic",None)["artifact_id"],artifact["artifact_id"])

        analysis_repo=PostgreSQLAnalysisTaskRepository(self.pool)
        task=AnalysisTask("分析本周金额","simple_metric_query",self.tenant,"u_admin",task_id="analysis_1",request_id="req_1",execution_mode="real",status="completed",analysis_plan={"mode":"metric"},conclusions=["金额稳定"],trace_id="trace_1")
        analysis_repo.save_task(task)
        self.assertEqual(analysis_repo.get_task("analysis_1")["tenant_id"],self.tenant)
        metrics=PostgreSQLMetricDictionaryStore(self.pool)
        metric=metrics.upsert(self.tenant,{"metricId":"loan_amount","metricName":"放款金额","description":"实际发放本金","unit":"元","semanticStatus":"documentation","visibleInstitutions":["集成测试机构"]},updated_by="u_admin")
        self.assertEqual(metric["metricId"],"loan_amount")
        lineage=PostgreSQLLineageStore(self.pool)
        edge=lineage.record_edge(self.tenant,{"source_type":"dataset","source_id":"loan_operation_mart","target_type":"report","target_id":"weekly_main","edge_type":"derives","confidence":1},"u_admin")
        self.assertEqual(lineage.graph(self.tenant,"dataset","loan_operation_mart")["edges"][0]["lineage_edge_id"],edge["lineage_edge_id"])

        reports=PostgreSQLReportStore(self.pool)
        version=reports.save_weekly_report_version(self.tenant,{
            "id":"weekly_v1","reportId":"weekly_main","name":"集成测试周报","savedAt":"2026-07-10T10:00:00+08:00",
            "report":{"id":"weekly_main","institutionName":"集成测试机构","period":"2026-07-06 ~ 2026-07-10","sections":[{"id":"performance","name":"经营表现","blocks":[{"id":"amount","type":"table","title":"金额","rows":[{"金额":100}],"evidenceRef":{"verified":True,"evidence_id":"ev1","evidence_hash":"b"*64,"source_snapshot":{"snapshot_id":"s1"}}}]}]},"comments":[],
        },updated_by="u_admin")
        self.assertEqual(version["publicationStatus"],"ready")
        comment=reports.create_report_comment(self.tenant,"weekly_main",{"targetId":"amount_data","targetLabel":"金额","targetKind":"table","text":"请复核"},"u_admin",0,"comment-request-1")
        self.assertEqual(comment["comment"]["author"],"管理员")
        replied=reports.mutate_report_comment(self.tenant,"weekly_main",comment["comment"]["id"],"reply",{"text":"已复核"},"u_reviewer",1,"reply-request-1")
        self.assertEqual(replied["revision"],2)
        self.assertEqual(replied["comment"]["author"],"管理员")
        self.assertEqual(replied["comment"]["replies"][0]["author"],"复核员")
        learning=reports.create_learning_candidate(self.tenant,version["id"],"analysis_method",{"title":"周报分析法"},{"block_id":"amount"},0.9,"u_admin")
        reports.review_learning_candidate(self.tenant,learning["learning_candidate_id"],"approve","u_reviewer")
        self.assertEqual(reports.mark_learning_candidate_applied(self.tenant,learning["learning_candidate_id"])["status"],"applied")

        automation=PostgreSQLAutomationStore(self.pool)
        auto_task=automation.create_task(self.tenant,{"task_code":"integration","task_name":"集成任务","task_type":"custom","trigger_type":"manual","handler_ref":"integration.noop","task_config":{},"retry_policy":{}},"u_admin")
        auto_run=automation.enqueue_run(self.tenant,auto_task["automation_task_id"],"auto-1","manual",{},"u_admin")
        claimed=automation.claim_run("worker-integration")
        self.assertEqual(claimed[0]["automation_run_id"],auto_run["automation_run_id"])
        automation.record_step(self.tenant,auto_run["automation_run_id"],"execute",0,"succeeded")
        automation.finish_run(self.tenant,auto_run["automation_run_id"],status="succeeded",result_refs=[])
        subscription=automation.create_subscription(self.tenant,{"subscription_name":"站内提醒","event_types":["integration.done"],"channel_type":"in_app","channel_config":{}},"u_admin")
        event_key=automation.enqueue_outbox_event(self.tenant,"integration",auto_run["automation_run_id"],"integration.done",{"ok":True},created_by="u_admin")
        self.assertEqual(automation.expand_outbox_once(),1)
        delivery,_,_=automation.claim_delivery()
        automation.finish_delivery(self.tenant,delivery["delivery_id"],status="delivered",provider_message_id="inapp:1")
        self.assertEqual(automation.list_in_app_deliveries(self.tenant,"u_admin")[0]["subscription_id"],subscription["subscription_id"])
        self.assertEqual(automation.list_deliveries_for_outbox(self.tenant,event_key)[0]["status"],"delivered")
        callback=automation.record_provider_callback(self.tenant,provider="in_app",provider_event_id="callback-1",provider_message_id="inapp:1",event_type="delivered",payload_hash="d"*64,safe_payload={"status":"delivered"})
        self.assertEqual(callback["processing_status"],"processed")
        serial_task=automation.create_task(self.tenant,{"task_code":"serial","task_name":"串行任务","task_type":"custom","trigger_type":"manual","handler_ref":"integration.noop","task_config":{},"retry_policy":{},"max_concurrency":1},"u_admin")
        serial_runs=[automation.enqueue_run(self.tenant,serial_task["automation_task_id"],f"serial-{index}","manual",{},"u_admin") for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims=list(executor.map(lambda worker: automation.claim_run(worker),("worker-a","worker-b")))
        self.assertEqual(sum(item is not None for item in claims),1)
        claimed_serial=next(item for item in claims if item is not None)[0]
        automation.finish_run(self.tenant,claimed_serial["automation_run_id"],status="succeeded")
        self.assertIsNotNone(automation.claim_run("worker-c"))

        market=PostgreSQLMarketStore(self.pool)
        market_source_system=acquisition.create_source(self.tenant,{"source_code":"market_feed","source_name":"持牌市场源","source_category":"market","license_metadata":{"license_type":"licensed_feed"}},"u_admin")
        market_source=market.create_source(self.tenant,{"source_system_id":market_source_system["source_system_id"],"publisher":"市场发布方","acquisition_method":"licensed_feed","license_type":"licensed_feed"},"u_admin")
        entity=market.create_entity(self.tenant,{"entity_type":"institution","entity_code":"bank_a","entity_name":"竞品A","attributes":{"region":"华东"}},"u_admin")
        observation=market.create_observation(self.tenant,{"market_source_id":market_source["market_source_id"],"market_entity_id":entity["market_entity_id"],"metric_code":"rate","observed_at":"2026-07-10T02:00:00Z","value_numeric":2.5,"evidence_artifact_id":artifact["artifact_id"],"source_record_id":"market-1"},"u_admin")
        rule=market.create_rule(self.tenant,{"rule_name":"利率阈值","entity_selector":{"entity_ids":[entity["market_entity_id"]]},"metric_code":"rate","condition_expression":{"operator":"gt","threshold":2},"severity":"warning"},"u_admin")
        market_event=market.create_event(self.tenant,rule,market.latest_observations(self.tenant,"rate")[0],{"observation_id":observation["market_observation_id"]})
        self.assertEqual(market.update_event_status(self.tenant,market_event["market_event_id"],"resolved","u_reviewer")["status"],"resolved")
        cooldown_observations=[market.create_observation(self.tenant,{"market_source_id":market_source["market_source_id"],"market_entity_id":entity["market_entity_id"],"metric_code":"rate","observed_at":f"2026-07-10T0{hour}:00:00Z","value_numeric":2.5+hour/10,"evidence_artifact_id":artifact["artifact_id"],"source_record_id":f"market-{hour}"},"u_admin") for hour in (3,4)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            cooldown_events=list(executor.map(
                lambda item: market.create_event(self.tenant,rule,item,{"observation_id":item["market_observation_id"]}),
                cooldown_observations,
            ))
        self.assertEqual(sum(item is not None for item in cooldown_events),1)

        app=PostgreSQLApplicationStore(self.pool)
        app_result=app.run_action(self.tenant,"agent_workspace","create_todo",{"todo":{"title":"跟进经营指标","dueDate":"2026-07-11"}},"u_admin")
        self.assertEqual(len(app_result["module"]["state"]["todos"]),1)
        with ThreadPoolExecutor(max_workers=2) as executor:
            module_results=list(executor.map(
                lambda prompt: app.run_action(self.tenant,"platform_shell","select_quick_prompt",{"prompt":prompt},"u_reviewer"),
                ("问题A","问题B"),
            ))
        self.assertEqual(len(module_results),2)
        # Capacity smoke for the stated ~100-user deployment size.  A small
        # shared pool must queue bursts cleanly instead of leaking connections
        # or falling back to process-local state.
        with ThreadPoolExecutor(max_workers=20) as executor:
            hundred_reads=list(executor.map(
                lambda _: app.get_module(self.tenant,"agent_workspace","u_admin"),
                range(100),
            ))
        self.assertEqual(len(hundred_reads),100)
        self.assertTrue(all(item["tenant_id"] == self.tenant for item in hundred_reads))
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,self.tenant)
                reviewer_key=PostgreSQLIdentityResolver.user_id(connection,"u_reviewer")
                cursor.execute("SELECT COUNT(*) AS count FROM platform_application_module_state WHERE tenant_id=%s AND module_code='platform_shell' AND owner_user_id=%s AND state_key='state'",(tenant_key,reviewer_key))
                self.assertEqual(int(_value(cursor.fetchone(),"count",0)),1)

        knowledge=PostgreSQLKnowledgeStore(self.pool)
        document=knowledge.create_document(self.tenant,{"title":"指标口径","content":"金额指标采用 sum(amount)。","document_type":"manual","domains":["metric"]},"u_admin")
        knowledge.review_document(self.tenant,document["document_id"],"approve","u_reviewer")
        self.assertTrue(knowledge.search("金额",self.tenant))

        memory=PostgreSQLMemoryStore(self.pool)
        memory_record=MemoryRecord("memory_1","preference",self.tenant,"周报偏好",{"format":"concise"},confidence=0.9,verified_status="candidate",created_by="u_admin")
        self.assertTrue(memory.write(memory_record,force=True))
        memory.review(self.tenant,"memory_1","approve","u_reviewer")
        self.assertEqual(memory.search(self.tenant,statuses=("active",))[0].memory_id,"memory_1")

        approvals=PostgreSQLCapabilityApprovalStore(self.pool)
        input_hash=hashlib.sha256(b"input").hexdigest()
        approval=approvals.request(self.tenant,"skill","supersonic.query","execute",input_hash,"u_admin","integration")
        approvals.review(self.tenant,approval["approval_id"],"u_reviewer","approved")
        consumed=approvals.consume(approval["approval_id"],tenant_id=self.tenant,requested_by="u_admin",subject_type="skill",subject_id="supersonic.query",action="execute",input_hash=input_hash)
        self.assertEqual(consumed["status"],"consumed")
        audit=PostgreSQLAuditEventStore(self.pool)
        audit.write(self.tenant,"u_admin","create","integration","item-1",{"password":"must-redact","request_id":"req-1"})
        self.assertEqual(audit.list(self.tenant)[0]["detail"]["password"],"[REDACTED]")

        sessions=PostgreSQLSessionStore(self.pool)
        grant=sessions.issue("u_admin",self.tenant,(self.tenant,),access_ttl_seconds=300,idle_timeout_seconds=600,absolute_timeout_seconds=3600,user_agent_hash="e"*64,ip_prefix="127.0.0")
        sessions.validate_access(grant.access_jti,grant.device_session_id,"u_admin",self.tenant)
        rotated=sessions.rotate_refresh(grant.refresh_token,access_ttl_seconds=300)
        self.assertNotEqual(rotated.refresh_token,grant.refresh_token)
        self.assertTrue(sessions.revoke(access_jti=rotated.access_jti,reason="integration"))
        oidc=PostgreSQLOIDCTransactionStore(self.pool)
        transaction=oidc.create("https://app.example.test/callback")
        self.assertEqual(oidc.consume(transaction.state).transaction_id,transaction.transaction_id)

        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                if getattr(self.pool, "dialect", "postgresql") == "mysql":
                    cursor.execute("SELECT COUNT(*) AS count FROM information_schema.tables WHERE table_schema=DATABASE()")
                    expected_table_count = 106
                else:
                    cursor.execute("SELECT COUNT(*) AS count FROM information_schema.tables WHERE table_schema='public'")
                    expected_table_count = 99
                self.assertEqual(int(_value(cursor.fetchone(),"count",0)), expected_table_count)

    def test_postgresql_url_is_rejected_by_production_composition(self) -> None:
        from backend.platform.bootstrap import build_production_platform

        config=RuntimeConfig(
            environment="staging",auth_mode="strict",data_warehouse="postgres",cors_origins=("https://app.example.test",),
            database_url=DATABASE_URL,secret_provider="local",object_store="local",object_bucket="",object_region="",
            oidc_issuer="https://idp.example.test",oidc_client_id="client",oidc_authorization_endpoint="https://idp.example.test/authorize",
            oidc_token_endpoint="https://idp.example.test/token",oidc_jwks_uri="https://idp.example.test/jwks",
            oidc_redirect_uri="https://app.example.test/api/auth/oidc/callback",
        )
        with self.assertRaisesRegex(RuntimeConfigurationError, "must point to MySQL"):
            build_production_platform(config)


def _value(row, key: str, index: int):
    if isinstance(row,dict): return row[key]
    try: return row[key]
    except (TypeError,KeyError,IndexError): return row[index]


if __name__ == "__main__":
    unittest.main()
