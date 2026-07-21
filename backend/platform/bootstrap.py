from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from backend.authz import (
    AuthEnforcer,
    InMemoryPolicyRepository,
    OPERATING_TENANTS,
    SUPER_ADMIN_ROLE_ID,
    SUPER_ADMIN_USER_ID,
    PostgreSQLPolicyRepository,
    build_default_rbac_seed,
    normalize_tenant_id,
    tenant_role_id,
)
from backend.authz.models import PermissionPolicy, Role, RoleAssignment, RoleLevel
from backend.authz.sqlite_repository import SQLitePolicyRepository
from backend.platform.access import AccessControlService, InMemoryUserDirectoryStore, PostgreSQLUserDirectoryStore, SQLiteUserDirectoryStore, default_user_profiles
from backend.platform.agents import AgentCatalog, AgentRuntime
from backend.platform.application import InMemoryApplicationStore, PostgreSQLApplicationStore, SQLiteApplicationStore
from backend.platform.assets import InMemoryDataAssetStore, PostgreSQLDataAssetStore, SQLiteDataAssetStore
from backend.platform.audit import InMemoryAuditEventStore, PostgreSQLAuditEventStore, SQLiteAuditEventStore
from backend.platform.automation import AutomationRuntime, InMemoryAutomationStore, PostgreSQLAutomationStore, SQLiteAutomationStore
from backend.platform.data_access import build_data_warehouse_from_env
from backend.platform.database import apply_migrations
from backend.platform.database.postgresql import PostgreSQLConnectionPool, apply_postgresql_schema
from backend.platform.governance import (
    InMemoryCapabilityApprovalStore,
    PermissionBroker,
    PostgreSQLCapabilityApprovalStore,
    SQLiteCapabilityApprovalStore,
)
from backend.platform.ingestion import (
    DataAcquisitionService,
    InMemoryAcquisitionStore,
    LocalArtifactObjectStore,
    PostgreSQLAcquisitionStore,
    S3ArtifactObjectStore,
    SQLiteAcquisitionStore,
    TopicDataResolver,
)
from backend.platform.crawler_engine.metadata import TopicMetadataService
from backend.platform.crawler_engine import CrawlerEngine
from backend.platform.crawler_engine.playwright_transport import PlaywrightCrawlerTransport
from backend.platform.crawler_engine.systems.qifu_focuspro_sios import QIFU_BUSINESS_SANDBOX_PROFILE_ID, QIFU_FUNNEL_PROFILE_ID
from backend.platform.crawler_engine.systems.qifu_focuspro_sios.auto_login import ensure_business_sandbox_login_session
from backend.platform.crawler_engine.systems.qifu_yushu import (
    YUSHU_MY_QUERIES_PROFILE_ID,
    sync_my_queries_to_raw_tables,
)
from backend.platform.crawler_engine.tool_assets import ensure_crawler_tools
from backend.platform.knowledge import InMemoryKnowledgeStore, KnowledgeDocument, KnowledgeService, PostgreSQLKnowledgeStore, SQLiteKnowledgeStore
from backend.platform.lineage import InMemoryLineageStore, PostgreSQLLineageStore, SQLiteLineageStore
from backend.platform.market import InMemoryMarketStore, MarketMonitoringService, PostgreSQLMarketStore, SQLiteMarketStore
from backend.platform.memory import InMemoryMemoryStore, MemoryService, PostgreSQLMemoryStore, SQLiteMemoryStore
from backend.platform.metrics import InMemoryMetricDictionaryStore, MetricSemanticCatalog, PostgreSQLMetricDictionaryStore, SQLiteMetricDictionaryStore
from backend.platform.metrics.defaults import load_default_metric_dictionary
from backend.platform.mcp import MCPGateway, register_local_mcp_handlers
from backend.platform.observability import TraceRecorder
from backend.platform.operating_snapshots import OperatingSnapshotService
from backend.platform.orchestration import AnalysisPlanningCatalog, AnalysisWorkflow
from backend.platform.repository import AnalysisTaskRepository, InMemoryAnalysisTaskRepository, SQLiteAnalysisTaskRepository
from backend.platform.postgresql_repository import PostgreSQLAnalysisTaskRepository
from backend.platform.reports import DailyEmailReportService, InMemoryReportStore, PostgreSQLReportStore, ReportRetentionService, SQLiteReportStore
from backend.platform.runtime_config import RuntimeConfig, RuntimeConfigurationError, load_runtime_config
from backend.platform.security import (
    InMemoryOIDCTransactionStore,
    InMemorySessionStore,
    OIDCClient,
    PostgreSQLOIDCTransactionStore,
    PostgreSQLSessionStore,
    SQLiteOIDCTransactionStore,
    SQLiteSessionStore,
    build_rate_limiter,
)
from backend.platform.semantic import (
    ConfiguredConnectionSupersonicClient,
    FallbackSupersonicClient,
    InMemorySupersonicClient,
    SemanticQueryService,
    SupersonicClient,
    SupersonicHTTPClient,
)
from backend.platform.settings import InMemorySystemConfigStore, PostgreSQLSystemConfigStore, SQLiteSystemConfigStore
from backend.platform.skills import SkillConfigCatalog, SkillExecutor, SkillRegistry
from backend.platform.skills.builtin import build_supersonic_query_skill


LOCAL_ANALYSIS_USER_ID = "u_admin"
LEGACY_TENANT_ID = "tenant_demo"
LEGACY_TENANT_ADMIN_ROLE_ID = "tenant_admin"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_RBAC_EXTENSION_MENU_OBJECTS = frozenset({
    "menu:self-analysis.analysis-config",
    "menu:data-assets.tools",
})


@dataclass
class PlatformServices:
    runtime_config: RuntimeConfig
    agent_catalog: AgentCatalog
    skill_config_catalog: SkillConfigCatalog
    trace_recorder: TraceRecorder
    permission_broker: PermissionBroker
    approval_store: InMemoryCapabilityApprovalStore | SQLiteCapabilityApprovalStore
    mcp_gateway: MCPGateway
    skill_registry: SkillRegistry
    skill_executor: SkillExecutor
    agent_runtime: AgentRuntime
    knowledge_store: InMemoryKnowledgeStore | SQLiteKnowledgeStore
    knowledge_service: KnowledgeService
    data_asset_store: InMemoryDataAssetStore | SQLiteDataAssetStore
    data_acquisition_store: InMemoryAcquisitionStore | SQLiteAcquisitionStore
    data_acquisition_service: DataAcquisitionService
    topic_metadata_service: TopicMetadataService
    topic_data_resolver: TopicDataResolver
    automation_store: InMemoryAutomationStore | SQLiteAutomationStore
    automation_runtime: AutomationRuntime
    market_store: InMemoryMarketStore | SQLiteMarketStore
    market_service: MarketMonitoringService
    application_store: InMemoryApplicationStore | SQLiteApplicationStore
    memory_store: InMemoryMemoryStore | SQLiteMemoryStore
    memory_service: MemoryService
    metric_dictionary_store: InMemoryMetricDictionaryStore | SQLiteMetricDictionaryStore
    lineage_store: InMemoryLineageStore | SQLiteLineageStore
    system_config_store: InMemorySystemConfigStore | SQLiteSystemConfigStore
    report_store: InMemoryReportStore | SQLiteReportStore
    report_retention_service: ReportRetentionService
    daily_email_service: DailyEmailReportService
    operating_snapshot_service: OperatingSnapshotService
    audit_store: InMemoryAuditEventStore | SQLiteAuditEventStore
    access_service: AccessControlService
    session_store: InMemorySessionStore | SQLiteSessionStore
    oidc_client: OIDCClient
    rate_limiter: object
    semantic_service: SemanticQueryService
    workflow: AnalysisWorkflow
    task_repository: AnalysisTaskRepository
    semantic_client_mode: str
    semantic_routing_mode: str
    semantic_fallback_mode: str
    data_source_mode: str
    primary_database_pool: PostgreSQLConnectionPool | None = None

    def close(self) -> None:
        policy_repository = self.permission_broker.enforcer.repository
        for resource in (
            policy_repository,
            self.approval_store,
            self.task_repository,
            self.knowledge_store,
            self.data_asset_store,
            self.data_acquisition_store,
            self.data_acquisition_service,
            self.automation_runtime,
            self.automation_store,
            self.market_store,
            self.application_store,
            self.memory_store,
            self.metric_dictionary_store,
            self.lineage_store,
            self.system_config_store,
            self.report_store,
            self.audit_store,
            self.access_service,
            self.session_store,
            self.oidc_client,
            self.semantic_service,
            self.rate_limiter,
            self.primary_database_pool,
        ):
            close = getattr(resource, "close", None)
            if callable(close):
                close()


def build_local_platform(db_path: str | Path | None = None) -> PlatformServices:
    """Build a local runnable platform slice for tests and API adapters."""

    runtime_config = load_runtime_config()
    if runtime_config.is_production:
        raise RuntimeConfigurationError(
            "The embedded SQLite/local platform adapter is forbidden in production. "
            "Start the PostgreSQL production runtime instead of build_local_platform()."
        )
    rate_limiter = build_rate_limiter(runtime_config.environment)
    roles, assignments, policies, manageable_roles = build_local_authz_seed()
    knowledge_documents = [
        KnowledgeDocument(
            doc_id="kd_metric_loan_amount",
            title="loan amount metric definition",
            content="loan_amount means disbursed principal amount for consumer loan and business loan. 放款金额用于衡量消费贷和经营贷实际发放本金。",
            tenant_id=LEGACY_TENANT_ID,
            domains=("loan", "metric"),
            tags=("loan_amount", "semantic", "放款金额"),
            owner_user_id=SUPER_ADMIN_USER_ID,
        )
    ]

    initialize_defaults = db_path is None
    if db_path is None:
        policy_repository = InMemoryPolicyRepository(roles, assignments, policies, manageable_roles=manageable_roles)
        task_repository: AnalysisTaskRepository = InMemoryAnalysisTaskRepository()
        knowledge_store = InMemoryKnowledgeStore(knowledge_documents)
        data_asset_store = InMemoryDataAssetStore(
            seed_defaults=runtime_config.environment in {"development", "test"},
        )
        data_acquisition_store = InMemoryAcquisitionStore()
        automation_store = InMemoryAutomationStore(data_acquisition_store)
        market_store = InMemoryMarketStore(data_acquisition_store)
        application_store = InMemoryApplicationStore()
        memory_store = InMemoryMemoryStore()
        metric_dictionary_store = InMemoryMetricDictionaryStore()
        lineage_store = InMemoryLineageStore()
        system_config_store = InMemorySystemConfigStore()
        report_store = InMemoryReportStore()
        audit_store = InMemoryAuditEventStore()
        user_directory_store = InMemoryUserDirectoryStore(default_user_profiles())
        session_store = InMemorySessionStore()
        oidc_transaction_store = InMemoryOIDCTransactionStore()
        approval_store = InMemoryCapabilityApprovalStore()
    else:
        apply_migrations(db_path)
        policy_repository = SQLitePolicyRepository(db_path, initialize=False)
        initialize_defaults = not policy_repository.list_roles()
        if initialize_defaults:
            policy_repository.seed(roles, assignments, policies, manageable_roles=manageable_roles)
        else:
            _reconcile_local_rbac_extensions(policy_repository, policies)
        task_repository = SQLiteAnalysisTaskRepository(db_path, initialize=False)
        knowledge_store = SQLiteKnowledgeStore(
            db_path,
            knowledge_documents if initialize_defaults else None,
            initialize=False,
        )
        data_asset_store = SQLiteDataAssetStore(db_path, initialize=False)
        data_acquisition_store = SQLiteAcquisitionStore(db_path, initialize=False)
        automation_store = SQLiteAutomationStore(db_path, initialize=False)
        market_store = SQLiteMarketStore(db_path, initialize=False)
        application_store = SQLiteApplicationStore(db_path, initialize=False)
        memory_store = SQLiteMemoryStore(db_path, initialize=False)
        metric_dictionary_store = SQLiteMetricDictionaryStore(db_path, initialize=False)
        lineage_store = SQLiteLineageStore(db_path)
        system_config_store = SQLiteSystemConfigStore(db_path, initialize=False)
        report_store = SQLiteReportStore(db_path, initialize=False)
        audit_store = SQLiteAuditEventStore(db_path, initialize=False)
        user_directory_store = SQLiteUserDirectoryStore(
            db_path,
            default_user_profiles() if initialize_defaults else None,
            initialize=False,
        )
        session_store = SQLiteSessionStore(db_path)
        oidc_transaction_store = SQLiteOIDCTransactionStore(db_path)
        approval_store = SQLiteCapabilityApprovalStore(db_path)
    enforcer = AuthEnforcer(policy_repository)
    trace_recorder = TraceRecorder()
    permission_broker = PermissionBroker(enforcer)
    agent_catalog = AgentCatalog.from_config_dir(PROJECT_ROOT / "configs" / "agent_groups")
    mcp_gateway = MCPGateway(
        permission_broker,
        trace_recorder,
        agent_catalog=agent_catalog,
        approval_store=approval_store,
    )
    access_service = AccessControlService(user_directory_store, policy_repository, permission_broker)
    oidc_client = OIDCClient(oidc_transaction_store)
    artifact_object_store = _build_artifact_object_store(runtime_config, db_path)
    data_acquisition_service = DataAcquisitionService(
        data_acquisition_store,
        artifact_object_store,
        system_config_store,
        task_repository,
        data_asset_store=data_asset_store,
    )
    topic_metadata_service = TopicMetadataService(
        data_acquisition_store,
        system_config_store,
        artifact_object_store,
        lineage_store,
        data_acquisition_service.crawler_engine,
    )
    topic_data_resolver = TopicDataResolver(data_acquisition_service)
    knowledge_service = KnowledgeService(
        knowledge_store,
        data_acquisition_store,
        artifact_object_store,
        runtime_config.environment,
    )
    memory_service = MemoryService(memory_store)
    market_service = MarketMonitoringService(market_store)
    automation_runtime = AutomationRuntime(
        automation_store,
        artifact_content_resolver=data_acquisition_service.get_artifact_content,
    )
    daily_email_service = DailyEmailReportService(
        report_store,
        data_acquisition_store,
        artifact_object_store,
        automation_store,
    )
    report_retention_service = ReportRetentionService(report_store, system_config_store)
    _register_automation_handlers(
        automation_runtime,
        data_acquisition_service,
        report_store,
        data_asset_store,
        application_store,
        market_service,
        system_config_store,
    )
    data_acquisition_service.automation_runtime = automation_runtime
    if initialize_defaults:
        _seed_metric_dictionary_if_empty(metric_dictionary_store, db_path)
        _seed_system_integrations_if_empty(system_config_store)
    if runtime_config.environment in {"development", "test"}:
        _seed_system_integrations_if_empty(system_config_store)
    if runtime_config.environment in {"development", "test"} and db_path is not None:
        for tenant_id in [normalize_tenant_id(tenant) for tenant in OPERATING_TENANTS] + [LEGACY_TENANT_ID]:
            bundle = data_asset_store.list_bundle(tenant_id)
            if not bundle.get("raw_tables"):
                data_asset_store.seed_defaults(tenant_id)
            else:
                data_asset_store.seed_missing_defaults(tenant_id)
            ensure_crawler_tools(data_asset_store, tenant_id)
    base_supersonic_client, semantic_client_mode, semantic_fallback_mode, data_source_mode = build_supersonic_client_from_env()
    supersonic_client = ConfiguredConnectionSupersonicClient(system_config_store, base_supersonic_client)
    semantic_routing_mode = "tenant_connection_registry"
    semantic_service = SemanticQueryService(supersonic_client, trace_recorder, permission_broker)
    operating_snapshot_service = OperatingSnapshotService(semantic_service)
    register_local_mcp_handlers(
        mcp_gateway,
        knowledge_store,
        semantic_service,
        PROJECT_ROOT / "configs" / "mcp_servers",
    )

    skill_config_catalog = SkillConfigCatalog.from_config_dir(PROJECT_ROOT / "configs" / "skills")
    skill_registry = SkillRegistry()
    for configured_skill in skill_config_catalog.list():
        skill_registry.declare(configured_skill)
    supersonic_spec, supersonic_handler = build_supersonic_query_skill(semantic_service)
    skill_registry.register(supersonic_spec, supersonic_handler)
    skill_executor = SkillExecutor(
        skill_registry,
        permission_broker,
        trace_recorder,
        rate_limiter=rate_limiter,
        approval_store=approval_store,
    )
    agent_runtime = AgentRuntime(agent_catalog, skill_executor, trace_recorder)

    workflow = AnalysisWorkflow(
        skill_executor,
        knowledge_store,
        memory_store,
        planning_catalog=AnalysisPlanningCatalog.from_config_path(PROJECT_ROOT / "configs" / "analysis" / "intent_rules.json"),
        agent_runtime=agent_runtime,
        metric_semantic_catalog=MetricSemanticCatalog.from_config_path(
            PROJECT_ROOT / "configs" / "analysis" / "metric_definitions.json",
            metric_dictionary_store,
        ),
    )

    services = PlatformServices(
        runtime_config=runtime_config,
        agent_catalog=agent_catalog,
        skill_config_catalog=skill_config_catalog,
        trace_recorder=trace_recorder,
        permission_broker=permission_broker,
        approval_store=approval_store,
        mcp_gateway=mcp_gateway,
        skill_registry=skill_registry,
        skill_executor=skill_executor,
        agent_runtime=agent_runtime,
        knowledge_store=knowledge_store,
        knowledge_service=knowledge_service,
        data_asset_store=data_asset_store,
        data_acquisition_store=data_acquisition_store,
        data_acquisition_service=data_acquisition_service,
        topic_metadata_service=topic_metadata_service,
        topic_data_resolver=topic_data_resolver,
        automation_store=automation_store,
        automation_runtime=automation_runtime,
        market_store=market_store,
        market_service=market_service,
        application_store=application_store,
        memory_store=memory_store,
        memory_service=memory_service,
        metric_dictionary_store=metric_dictionary_store,
        lineage_store=lineage_store,
        system_config_store=system_config_store,
        report_store=report_store,
        report_retention_service=report_retention_service,
        daily_email_service=daily_email_service,
        operating_snapshot_service=operating_snapshot_service,
        audit_store=audit_store,
        access_service=access_service,
        session_store=session_store,
        oidc_client=oidc_client,
        rate_limiter=rate_limiter,
        semantic_service=semantic_service,
        workflow=workflow,
        task_repository=task_repository,
        semantic_client_mode=semantic_client_mode,
        semantic_routing_mode=semantic_routing_mode,
        semantic_fallback_mode=semantic_fallback_mode,
        data_source_mode=data_source_mode,
    )
    automation_runtime.platform_services = services
    return services


def build_production_platform(runtime_config: RuntimeConfig | None = None) -> PlatformServices:
    """Build the PostgreSQL-primary runtime without implicit tenants, users or demo data."""

    runtime_config = runtime_config or load_runtime_config()
    if runtime_config.environment not in {"staging", "production"}:
        raise RuntimeConfigurationError("PostgreSQL production runtime requires staging or production environment")
    if not runtime_config.database_url:
        raise RuntimeConfigurationError("SMART_DATA_AGENT_DATABASE_URL is required")
    min_size = max(1, min(int(os.getenv("SMART_DATA_AGENT_DB_POOL_MIN", "2")), 20))
    max_size = max(min_size, min(int(os.getenv("SMART_DATA_AGENT_DB_POOL_MAX", "20")), 100))
    pool = PostgreSQLConnectionPool(runtime_config.database_url, min_size=min_size, max_size=max_size)
    try:
        if os.getenv("SMART_DATA_AGENT_AUTO_MIGRATE", "true").strip().lower() not in {"0", "false", "no"}:
            with pool.connection() as connection:
                apply_postgresql_schema(runtime_config.database_url, connection=connection)

        policy_repository = PostgreSQLPolicyRepository(pool)
        task_repository: AnalysisTaskRepository = PostgreSQLAnalysisTaskRepository(pool)
        knowledge_store = PostgreSQLKnowledgeStore(pool)
        data_asset_store = PostgreSQLDataAssetStore(pool)
        data_acquisition_store = PostgreSQLAcquisitionStore(pool)
        automation_store = PostgreSQLAutomationStore(pool)
        market_store = PostgreSQLMarketStore(pool)
        application_store = PostgreSQLApplicationStore(pool)
        memory_store = PostgreSQLMemoryStore(pool)
        metric_dictionary_store = PostgreSQLMetricDictionaryStore(pool)
        lineage_store = PostgreSQLLineageStore(pool)
        system_config_store = PostgreSQLSystemConfigStore(pool)
        report_store = PostgreSQLReportStore(pool)
        audit_store = PostgreSQLAuditEventStore(pool)
        user_directory_store = PostgreSQLUserDirectoryStore(pool)
        session_store = PostgreSQLSessionStore(pool)
        oidc_transaction_store = PostgreSQLOIDCTransactionStore(pool)
        approval_store = PostgreSQLCapabilityApprovalStore(pool)

        rate_limiter = build_rate_limiter(runtime_config.environment)
        enforcer = AuthEnforcer(policy_repository)
        trace_recorder = TraceRecorder()
        permission_broker = PermissionBroker(enforcer)
        agent_catalog = AgentCatalog.from_config_dir(PROJECT_ROOT / "configs" / "agent_groups")
        mcp_gateway = MCPGateway(
            permission_broker,
            trace_recorder,
            agent_catalog=agent_catalog,
            approval_store=approval_store,
        )
        access_service = AccessControlService(user_directory_store, policy_repository, permission_broker)
        oidc_client = OIDCClient(oidc_transaction_store)
        oidc_client.validate_config()
        artifact_object_store = _build_artifact_object_store(runtime_config, None)
        data_acquisition_service = DataAcquisitionService(
            data_acquisition_store,
            artifact_object_store,
            system_config_store,
            task_repository,
            data_asset_store=data_asset_store,
        )
        topic_metadata_service = TopicMetadataService(
            data_acquisition_store,
            system_config_store,
            artifact_object_store,
            lineage_store,
            data_acquisition_service.crawler_engine,
        )
        topic_data_resolver = TopicDataResolver(data_acquisition_service)
        knowledge_service = KnowledgeService(
            knowledge_store,
            data_acquisition_store,
            artifact_object_store,
            runtime_config.environment,
        )
        memory_service = MemoryService(memory_store)
        market_service = MarketMonitoringService(market_store)
        automation_runtime = AutomationRuntime(
            automation_store,
            artifact_content_resolver=data_acquisition_service.get_artifact_content,
        )
        daily_email_service = DailyEmailReportService(
            report_store,
            data_acquisition_store,
            artifact_object_store,
            automation_store,
        )
        report_retention_service = ReportRetentionService(report_store, system_config_store)
        _register_automation_handlers(
            automation_runtime,
            data_acquisition_service,
            report_store,
            data_asset_store,
            application_store,
            market_service,
            system_config_store,
        )
        data_acquisition_service.automation_runtime = automation_runtime
        base_client, semantic_client_mode, semantic_fallback_mode, data_source_mode = build_supersonic_client_from_env()
        supersonic_client = ConfiguredConnectionSupersonicClient(system_config_store, base_client)
        semantic_routing_mode = "tenant_connection_registry"
        semantic_service = SemanticQueryService(supersonic_client, trace_recorder, permission_broker)
        operating_snapshot_service = OperatingSnapshotService(semantic_service)
        register_local_mcp_handlers(
            mcp_gateway,
            knowledge_store,
            semantic_service,
            PROJECT_ROOT / "configs" / "mcp_servers",
        )

        skill_config_catalog = SkillConfigCatalog.from_config_dir(PROJECT_ROOT / "configs" / "skills")
        skill_registry = SkillRegistry()
        for configured_skill in skill_config_catalog.list():
            skill_registry.declare(configured_skill)
        supersonic_spec, supersonic_handler = build_supersonic_query_skill(semantic_service)
        skill_registry.register(supersonic_spec, supersonic_handler)
        skill_executor = SkillExecutor(
            skill_registry,
            permission_broker,
            trace_recorder,
            rate_limiter=rate_limiter,
            approval_store=approval_store,
        )
        agent_runtime = AgentRuntime(agent_catalog, skill_executor, trace_recorder)
        workflow = AnalysisWorkflow(
            skill_executor,
            knowledge_store,
            memory_store,
            planning_catalog=AnalysisPlanningCatalog.from_config_path(PROJECT_ROOT / "configs" / "analysis" / "intent_rules.json"),
            agent_runtime=agent_runtime,
            metric_semantic_catalog=MetricSemanticCatalog.from_config_path(
                PROJECT_ROOT / "configs" / "analysis" / "metric_definitions.json",
                metric_dictionary_store,
            ),
        )
        services = PlatformServices(
            runtime_config=runtime_config,
            agent_catalog=agent_catalog,
            skill_config_catalog=skill_config_catalog,
            trace_recorder=trace_recorder,
            permission_broker=permission_broker,
            approval_store=approval_store,
            mcp_gateway=mcp_gateway,
            skill_registry=skill_registry,
            skill_executor=skill_executor,
            agent_runtime=agent_runtime,
            knowledge_store=knowledge_store,
            knowledge_service=knowledge_service,
            data_asset_store=data_asset_store,
            data_acquisition_store=data_acquisition_store,
            data_acquisition_service=data_acquisition_service,
            topic_metadata_service=topic_metadata_service,
            topic_data_resolver=topic_data_resolver,
            automation_store=automation_store,
            automation_runtime=automation_runtime,
            market_store=market_store,
            market_service=market_service,
            application_store=application_store,
            memory_store=memory_store,
            memory_service=memory_service,
            metric_dictionary_store=metric_dictionary_store,
            lineage_store=lineage_store,
            system_config_store=system_config_store,
            report_store=report_store,
            report_retention_service=report_retention_service,
            daily_email_service=daily_email_service,
            operating_snapshot_service=operating_snapshot_service,
            audit_store=audit_store,
            access_service=access_service,
            session_store=session_store,
            oidc_client=oidc_client,
            rate_limiter=rate_limiter,
            semantic_service=semantic_service,
            workflow=workflow,
            task_repository=task_repository,
            semantic_client_mode=semantic_client_mode,
            semantic_routing_mode=semantic_routing_mode,
            semantic_fallback_mode=semantic_fallback_mode,
            data_source_mode=data_source_mode,
            primary_database_pool=pool,
        )
        automation_runtime.platform_services = services
        return services
    except BaseException:
        pool.close()
        raise


def _build_artifact_object_store(runtime_config: RuntimeConfig, db_path: str | Path | None):
    adapter = os.getenv("SMART_DATA_AGENT_OBJECT_STORE", "local").strip().lower()
    if adapter in {"s3", "oss", "s3_compatible"}:
        return S3ArtifactObjectStore(
            os.getenv("SMART_DATA_AGENT_OBJECT_BUCKET", ""),
            region=os.getenv("SMART_DATA_AGENT_OBJECT_REGION", ""),
            endpoint_url=os.getenv("SMART_DATA_AGENT_OBJECT_ENDPOINT", "").strip() or None,
            prefix=os.getenv("SMART_DATA_AGENT_OBJECT_PREFIX", "smart-data-agent"),
            kms_key_id=os.getenv("SMART_DATA_AGENT_OBJECT_KMS_KEY_ID", "").strip() or None,
        )
    if adapter != "local":
        raise RuntimeConfigurationError(f"Unsupported SMART_DATA_AGENT_OBJECT_STORE: {adapter}")
    if runtime_config.is_production:
        raise RuntimeConfigurationError("Local artifact storage is forbidden in production")
    configured_object_root = os.getenv("SMART_DATA_AGENT_OBJECT_ROOT", "").strip()
    if configured_object_root:
        return LocalArtifactObjectStore(configured_object_root)
    if db_path is not None:
        database_path = Path(db_path).resolve()
        return LocalArtifactObjectStore(database_path.parent / f".{database_path.stem}_artifacts")
    return LocalArtifactObjectStore()


def _register_automation_handlers(
    runtime: AutomationRuntime,
    data_acquisition_service: DataAcquisitionService,
    report_store: InMemoryReportStore | SQLiteReportStore,
    data_asset_store: InMemoryDataAssetStore | SQLiteDataAssetStore,
    application_store: InMemoryApplicationStore | SQLiteApplicationStore,
    market_service: MarketMonitoringService,
    system_config_store: InMemorySystemConfigStore | SQLiteSystemConfigStore,
) -> None:
    def acquisition_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        job_id = str(config.get("acquisition_job_id") or "").strip()
        if not job_id:
            raise ValueError("acquisition_job_id_required")
        return data_acquisition_service.run_job(
            tenant_id,
            job_id,
            str(context["actor_user_id"]),
            f"automation:{context['automation_run_id']}",
            org_unit_id=str(trigger_payload.get("org_unit_id") or config.get("org_unit_id") or "") or None,
            input_cursor={
                **(trigger_payload.get("input_cursor") if isinstance(trigger_payload.get("input_cursor"), dict) else {}),
                "keep_latest_n": int(config.get("keep_latest_n") or 3),
                "operation_type": "data_query",
            },
        )

    def crawler_connection_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        connection_id = str(trigger_payload.get("connection_id") or config.get("connection_id") or "").strip()
        if not connection_id:
            raise ValueError("connection_id_required")
        connection = system_config_store.get_data_connection(tenant_id, connection_id, reveal_secret=True)
        if connection is None:
            raise KeyError("data_connection_not_found")
        crawler_config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
        profile_id = str(connection.get("crawlerProfileId") or "")
        page_url = str(connection.get("queryPageUrl") or connection.get("apiUrl") or "").strip()
        crawler_engine = None
        if profile_id in {QIFU_BUSINESS_SANDBOX_PROFILE_ID, QIFU_FUNNEL_PROFILE_ID}:
            _allow_registered_crawler_proxy_host(page_url)
            state_value = str(crawler_config.get("storageStatePath") or "").strip()
            state_path = Path(state_value) if state_value else PROJECT_ROOT / ".crawler-sessions" / f"{connection_id}.json"
            if not state_path.is_absolute():
                state_path = PROJECT_ROOT / state_path
            ensure_business_sandbox_login_session(
                connection=connection,
                page_url=page_url,
                storage_state=state_path,
                browser_channel=str(crawler_config.get("browserChannel") or "chrome"),
            )
            crawler_engine = CrawlerEngine(transport=PlaywrightCrawlerTransport())
        elif profile_id == YUSHU_MY_QUERIES_PROFILE_ID:
            _allow_registered_crawler_proxy_host(page_url)
            state_value = str(crawler_config.get("storageStatePath") or "").strip()
            state_path = Path(state_value) if state_value else PROJECT_ROOT / ".crawler-sessions" / f"{connection_id}.json"
            if not state_path.is_absolute():
                state_path = PROJECT_ROOT / state_path
            return sync_my_queries_to_raw_tables(
                data_asset_store=data_asset_store,
                tenant_id=tenant_id,
                actor_user_id=str(context["actor_user_id"]),
                connection=connection,
                page_url=page_url,
                storage_state=state_path,
                browser_channel=str(crawler_config.get("browserChannel") or "chrome"),
            )
        return data_acquisition_service.run_verified_crawler(
            tenant_id,
            connection_id,
            str(context["actor_user_id"]),
            f"automation:{context['automation_run_id']}",
            crawler_engine=crawler_engine,
        )

    def analysis_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        from backend.platform.api.routes.analysis import run_analysis

        question = str(trigger_payload.get("question") or config.get("question") or "").strip()
        if not question:
            raise ValueError("analysis_question_required")
        services = getattr(runtime, "platform_services", None)
        if services is None:
            raise RuntimeError("automation_platform_services_not_bound")
        run_id = str(context["automation_run_id"])
        request_id = str(trigger_payload.get("request_id") or f"automation:{run_id}")[:88]
        if int(context.get("attempt_no") or 1) > 1:
            existing = services.task_repository.get_task_by_request(tenant_id, request_id)
            if existing and str(existing.get("status") or "") not in {"completed", "review_required"}:
                request_id = f"{request_id}:attempt:{int(context['attempt_no'])}"

        def report_progress(
            step_code: str,
            sequence_no: int,
            status: str,
            label: str,
            detail: str,
            refs: dict[str, object] | None = None,
        ) -> None:
            runtime.store.record_step(
                tenant_id,
                run_id,
                step_code,
                sequence_no,
                status,
                output_refs=[{"label": label, "detail": detail, **(refs or {})}],
            )

        return run_analysis(
            services,
            user_id=str(context["actor_user_id"]),
            tenant_id=tenant_id,
            question=question,
            page_context={
                **(config.get("page_context") if isinstance(config.get("page_context"), dict) else {}),
                **(trigger_payload.get("page_context") if isinstance(trigger_payload.get("page_context"), dict) else {}),
                "request_id": request_id,
            },
            cancellation_check=context.get("is_cancelled"),
            progress_callback=report_progress,
        )

    def metric_monitor_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        from backend.platform.automation.metric_monitor import run_metric_monitor

        services = getattr(runtime, "platform_services", None)
        if services is None:
            raise RuntimeError("automation_platform_services_not_bound")
        run_id = str(context["automation_run_id"])

        def report_progress(
            step_code: str,
            sequence_no: int,
            status: str,
            label: str,
            detail: str,
            refs: dict[str, object] | None = None,
        ) -> None:
            runtime.store.record_step(
                tenant_id,
                run_id,
                step_code,
                sequence_no,
                status,
                output_refs=[{"label": label, "detail": detail, **(refs or {})}],
            )

        return run_metric_monitor(
            services,
            tenant_id=tenant_id,
            user_id=str(context["actor_user_id"]),
            config=config,
            trigger_payload=trigger_payload,
            request_id=str(trigger_payload.get("request_id") or f"automation:{run_id}")[:88],
            cancellation_check=context.get("is_cancelled"),
            progress_callback=report_progress,
        )

    def report_learning_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        from backend.platform.reports import WeeklyReportLearningEngine

        version_id = str(trigger_payload.get("version_id") or config.get("version_id") or "").strip()
        if not version_id:
            raise ValueError("weekly_report_version_id_required")
        result = WeeklyReportLearningEngine(report_store, data_asset_store, application_store).analyze_version(
            tenant_id,
            version_id,
            str(context["actor_user_id"]),
            force=bool(trigger_payload.get("force", config.get("force", False))),
        )
        return {"version_id": version_id, "task_id": result.get("id"), "status": result.get("status")}

    def market_evaluate_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        rule_id = str(trigger_payload.get("market_rule_id") or config.get("market_rule_id") or "").strip() or None
        return market_service.evaluate(tenant_id, rule_id)

    def memory_extraction_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        from backend.platform.memory.extraction import run_memory_extraction

        services = getattr(runtime, "platform_services", None)
        if services is None:
            raise RuntimeError("automation_platform_services_not_bound")
        return run_memory_extraction(
            services,
            tenant_id,
            str(context["actor_user_id"]),
            {**config, **trigger_payload},
        )

    runtime.register_handler("acquisition.run", acquisition_handler)
    runtime.register_handler("crawler.connection.run", crawler_connection_handler)
    runtime.register_handler("analysis.run", analysis_handler)
    runtime.register_handler("analysis.monitor", metric_monitor_handler)
    runtime.register_handler("report.weekly_learning", report_learning_handler)
    runtime.register_handler("market.evaluate", market_evaluate_handler)
    runtime.register_handler("memory.extract", memory_extraction_handler)


def _allow_registered_crawler_proxy_host(page_url: str) -> None:
    """Permit the exact approved crawler host when a local proxy resolves it privately."""

    host = str(urlsplit(page_url).hostname or "").strip().lower()
    if not host:
        raise ValueError("crawler_target_hostname_required")
    current = [item.strip() for item in os.getenv("SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS", "").split(",") if item.strip()]
    if host not in current:
        current.append(host)
        os.environ["SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS"] = ",".join(current)
    allowed = [item.strip() for item in os.getenv("SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS", "").split(",") if item.strip()]
    if allowed and host not in allowed:
        allowed.append(host)
        os.environ["SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS"] = ",".join(allowed)


def _seed_metric_dictionary_if_empty(
    metric_dictionary_store: InMemoryMetricDictionaryStore | SQLiteMetricDictionaryStore,
    db_path: str | Path | None,
) -> None:
    if not _should_seed_default_metric_dictionary(db_path):
        return
    metrics = load_default_metric_dictionary()
    if not metrics:
        return
    tenant_id = normalize_tenant_id(OPERATING_TENANTS[0])
    try:
        existing = metric_dictionary_store.list(tenant_id)
    except Exception:
        existing = []
    if not existing:
        metric_dictionary_store.replace_all(
            tenant_id,
            metrics,
            updated_by=SUPER_ADMIN_USER_ID,
        )
    if isinstance(metric_dictionary_store, SQLiteMetricDictionaryStore):
        _dedupe_seed_metric_dictionary(metric_dictionary_store, tenant_id, {str(metric["metricId"]) for metric in metrics})


def _should_seed_default_metric_dictionary(db_path: str | Path | None) -> bool:
    env_value = os.getenv("SMART_DATA_AGENT_SEED_METRIC_DICTIONARY", "").strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    if env_value in {"0", "false", "no", "off"}:
        return False
    return db_path is not None and Path(db_path).name == ".smart_data_agent.sqlite"


def _dedupe_seed_metric_dictionary(
    metric_dictionary_store: SQLiteMetricDictionaryStore,
    owner_tenant_id: str,
    metric_ids: set[str],
) -> None:
    if not metric_ids:
        return
    placeholders = ",".join("?" for _ in metric_ids)
    sorted_metric_ids = sorted(metric_ids)
    params = [owner_tenant_id, SUPER_ADMIN_USER_ID, *sorted_metric_ids, *sorted_metric_ids]
    with metric_dictionary_store._conn:
        metric_dictionary_store._conn.execute(
            f"""
            DELETE FROM platform_metric_visibility
            WHERE owner_tenant_id IN (
                SELECT tenant_id
                FROM platform_metric_dictionary
                WHERE tenant_id <> ?
                  AND created_by = ?
                  AND metric_id IN ({placeholders})
            )
              AND metric_id IN ({placeholders})
            """,
            tuple(params),
        )
        params = [owner_tenant_id, SUPER_ADMIN_USER_ID, *sorted_metric_ids]
        metric_dictionary_store._conn.execute(
            f"""
            DELETE FROM platform_metric_dictionary
            WHERE tenant_id <> ?
              AND created_by = ?
              AND metric_id IN ({placeholders})
            """,
            tuple(params),
        )


def _seed_system_integrations_if_empty(system_config_store: InMemorySystemConfigStore | SQLiteSystemConfigStore) -> None:
    tenant_ids = [normalize_tenant_id(tenant) for tenant in OPERATING_TENANTS] + [LEGACY_TENANT_ID]
    model_api_key = os.getenv("ZETATECHS_API_KEY", "").strip()
    model_is_demo = not model_api_key
    default_models = [
        {
            "id": "model_business_analysis_relay",
            "name": "经营分析大模型",
            "modelName": "中转站",
            "key": os.getenv("ZETATECHS_BUSINESS_MODEL_API_BASE", "https://zetatechs.com/api/v1/business-analysis"),
            "value": model_api_key or "zetatechs-demo-key",
            "applicationModule": "intelligent_analysis_reasoning",
            "availableModels": [] if model_is_demo else ["qwen-plus", "deepseek-v3", "gpt-4o-mini"],
            "enabledModels": [] if model_is_demo else ["qwen-plus"],
            "testStatus": "mock" if model_is_demo else "untested",
            "status": "draft" if model_is_demo else "available",
        },
        {
            "id": "model_sql_generation_relay",
            "name": "SQL生成模型",
            "modelName": "中转站",
            "key": os.getenv("ZETATECHS_SQL_MODEL_API_BASE", "https://zetatechs.com/api/v1/sql-agent"),
            "value": model_api_key or "zetatechs-demo-key",
            "applicationModule": "weekly_report_conclusion_regeneration",
            "availableModels": [] if model_is_demo else ["qwen-plus", "deepseek-v3", "gpt-4o-mini"],
            "enabledModels": [] if model_is_demo else ["qwen-plus"],
            "testStatus": "mock" if model_is_demo else "untested",
            "status": "draft" if model_is_demo else "available",
        },
    ]
    speech_api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    default_speech = {
        "id": "speech_fun_asr",
        "name": "阿里云 Fun-ASR",
        "provider": "aliyun_fun_asr",
        "source": "阿里云",
        "apiBase": os.getenv("DASHSCOPE_API_BASE", "https://ws-nvbkaw0atdgdbvv7.cn-beijing.maas.aliyuncs.com/api/v1"),
        "apiKey": speech_api_key or "dashscope-demo-key",
        "testStatus": "untested" if speech_api_key else "mock",
        "status": "available" if speech_api_key else "draft",
    }
    for tenant_id in tenant_ids:
        try:
            if not system_config_store.list_models(tenant_id):
                for model in default_models:
                    system_config_store.upsert_model(tenant_id, model, updated_by=SUPER_ADMIN_USER_ID)
            speech_integrations = system_config_store.list_speech_integrations(tenant_id, reveal_secret=True)
            if not speech_integrations:
                system_config_store.upsert_speech_integration(tenant_id, default_speech, updated_by=SUPER_ADMIN_USER_ID)
            elif speech_api_key:
                for integration in speech_integrations:
                    existing_key = str(integration.get("apiKey") or "").strip().lower()
                    if integration.get("id") != "speech_fun_asr" or existing_key not in {"dashscope-demo-key", "demo-key", "demo"}:
                        continue
                    system_config_store.upsert_speech_integration(
                        tenant_id,
                        {
                            **integration,
                            "apiBase": default_speech["apiBase"],
                            "apiKey": speech_api_key,
                            "testStatus": "untested",
                            "testMessage": "已从本地安全环境升级为真实凭证，保存并启用后可直接使用；测试仅用于排查。",
                            "testResponse": "",
                            "lastTestedAt": "",
                            "status": "available",
                        },
                        updated_by=SUPER_ADMIN_USER_ID,
                    )
        except Exception:
            continue


def build_local_authz_seed() -> tuple[list[Role], list[RoleAssignment], list[PermissionPolicy], dict[str, set[str]]]:
    seed = build_default_rbac_seed(OPERATING_TENANTS)
    roles = list(seed.roles)
    assignments = list(seed.assignments)
    policies = list(seed.policies)
    manageable_roles = {role_id: set(role_ids) for role_id, role_ids in seed.manageable_roles.items()}

    assignments.extend(_default_user_role_assignments())

    roles.append(Role(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "tenant_admin", RoleLevel.TENANT_ADMIN, True))
    assignments.append(RoleAssignment(LOCAL_ANALYSIS_USER_ID, LEGACY_TENANT_ID, LEGACY_TENANT_ADMIN_ROLE_ID))
    assignments.append(RoleAssignment("u_reviewer", LEGACY_TENANT_ID, LEGACY_TENANT_ADMIN_ROLE_ID))
    policies.extend(
        [
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "menu:*", "read"),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "approval:*", "manage", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "metric:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "metric:*", "create", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "asset:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "asset:*", "create", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "asset:*", "manage", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "knowledge:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "knowledge:*", "create", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "knowledge:*", "manage", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "memory:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "memory:*", "create", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "memory:*", "manage", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "automation:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "automation:*", "create", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "automation:*", "manage", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "notification:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "notification:*", "create", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "market:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "market:*", "create", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "market:*", "manage", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "application:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "application:*", "execute", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "system_config:*", "read", attrs={"tenant_id": LEGACY_TENANT_ID}),
            PermissionPolicy(LEGACY_TENANT_ADMIN_ROLE_ID, LEGACY_TENANT_ID, "system_config:*", "manage", attrs={"tenant_id": LEGACY_TENANT_ID}),
            *_platform_runtime_policies(
                LEGACY_TENANT_ADMIN_ROLE_ID,
                LEGACY_TENANT_ID,
                can_query=True,
                can_manage_knowledge=True,
                can_report=True,
            ),
        ]
    )
    return roles, assignments, policies, manageable_roles


def _reconcile_local_rbac_extensions(
    repository: SQLitePolicyRepository,
    default_policies: list[PermissionPolicy],
) -> None:
    """Add only newly introduced system-menu grants to an existing local DB.

    Existing role assignments and custom permission choices remain untouched.
    This is deliberately narrower than reseeding the default policy set.
    """

    system_role_ids = {role.role_id for role in repository.list_roles() if role.is_system}
    missing_candidates = [
        policy
        for policy in default_policies
        if policy.role_id in system_role_ids and policy.obj in LOCAL_RBAC_EXTENSION_MENU_OBJECTS
    ]
    if missing_candidates:
        repository.seed([], [], missing_candidates)


def _default_user_role_assignments() -> list[RoleAssignment]:
    grants = [
        *((LOCAL_ANALYSIS_USER_ID, tenant_name, "管理员") for tenant_name in OPERATING_TENANTS),
        ("u_lina", "华兴银行", "管理员"),
        ("u_wangqiang", "广州银行", "管理员"),
        ("u_zhaomin", "郑州银行", "操作员"),
        ("u_liuyang", "南京银行", "操作员"),
        ("u_chenlei", "三峡银行", "周报分析岗"),
    ]
    return [
        RoleAssignment(
            user_id,
            normalize_tenant_id(tenant_name),
            tenant_role_id(normalize_tenant_id(tenant_name), role_name),
            granted_by="u_super_admin",
        )
        for user_id, tenant_name, role_name in grants
    ]


def _platform_runtime_policies(
    role_id: str,
    tenant_id: str,
    *,
    can_query: bool = False,
    can_manage_knowledge: bool = False,
    can_report: bool = False,
) -> list[PermissionPolicy]:
    policies: list[PermissionPolicy] = []
    if can_query:
        policies.extend(
            [
                PermissionPolicy(role_id, tenant_id, "skill:supersonic.query", "execute"),
                PermissionPolicy(role_id, tenant_id, "mcp:database.query", "execute"),
                PermissionPolicy(role_id, tenant_id, "mcp:database.schema", "execute"),
                PermissionPolicy(role_id, tenant_id, "mcp:knowledge.search", "execute"),
            ]
        )
    if can_manage_knowledge:
        policies.append(PermissionPolicy(role_id, tenant_id, "mcp:knowledge.ingest", "execute"))
    if can_report:
        policies.extend(
            [
                PermissionPolicy(role_id, tenant_id, "report:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(role_id, tenant_id, "report:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(role_id, tenant_id, "report:*", "manage", attrs={"tenant_id": tenant_id}),
            ]
        )
    return policies


def build_supersonic_client_from_env() -> tuple[SupersonicClient, str, str, str]:
    warehouse, data_source_mode = build_data_warehouse_from_env()
    local_client = InMemorySupersonicClient(warehouse)
    endpoint = os.getenv("SMART_DATA_AGENT_SUPERSONIC_URL", "").strip()
    if not endpoint:
        return local_client, "local", "not_applicable", data_source_mode
    timeout_seconds = float(os.getenv("SMART_DATA_AGENT_SUPERSONIC_TIMEOUT", "8"))
    retries = int(os.getenv("SMART_DATA_AGENT_SUPERSONIC_RETRIES", "1"))
    http_client = SupersonicHTTPClient(
        endpoint=endpoint,
        api_key=os.getenv("SMART_DATA_AGENT_SUPERSONIC_API_KEY"),
        timeout_seconds=timeout_seconds,
        retries=retries,
    )
    fallback_mode = os.getenv("SMART_DATA_AGENT_SUPERSONIC_FALLBACK_MODE", "disabled").strip().lower()
    if fallback_mode in {"local", "enabled", "local_mock"}:
        return (
            FallbackSupersonicClient(http_client, local_client),
            "http",
            "explicit_local",
            f"remote_semantic_with_explicit_{data_source_mode}_fallback",
        )
    return http_client, "http", "disabled", "remote_semantic"
