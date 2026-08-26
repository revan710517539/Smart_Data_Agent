from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.authz import (
    AuthEnforcer,
    InMemoryPolicyRepository,
    OPERATING_TENANTS,
    SUPER_ADMIN_ROLE_ID,
    SUPER_ADMIN_USER_ID,
    PostgreSQLPolicyRepository,
    build_default_rbac_seed,
    normalize_tenant_id,
    reconcile_role_defaults,
    tenant_role_id,
)
from backend.authz.models import PermissionPolicy, Role, RoleAssignment, RoleLevel
from backend.authz.sqlite_repository import SQLitePolicyRepository
from backend.platform.access import AccessControlService, InMemoryUserDirectoryStore, PostgreSQLUserDirectoryStore, SQLiteUserDirectoryStore, default_user_profiles
from backend.platform.agents import AgentCatalog, AgentRuntime
from backend.platform.analysis_workspace import (
    AnalysisWorkspaceService,
    InMemoryAnalysisGovernanceStore,
    InMemoryAnalysisWorkspaceStore,
    MySQLAnalysisGovernanceStore,
    MySQLAnalysisWorkspaceStore,
)
from backend.platform.application import InMemoryApplicationStore, PostgreSQLApplicationStore, SQLiteApplicationStore
from backend.platform.assets import InMemoryDataAssetStore, PostgreSQLDataAssetStore, SQLiteDataAssetStore
from backend.platform.audit import InMemoryAuditEventStore, PostgreSQLAuditEventStore, SQLiteAuditEventStore
from backend.platform.automation import AutomationRuntime, InMemoryAutomationStore, PostgreSQLAutomationStore, SQLiteAutomationStore
from backend.platform.data_access import build_data_warehouse_from_env
from backend.platform.database import MySQLConnectionPool, MySQLStoreConnectionPool, apply_migrations, apply_mysql_schema
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
    TopicDataStore,
    TopicDataBatchService,
)
from backend.platform.ingestion.topic_metadata import CSVTopicMetadataService
from backend.platform.interaction_events import InMemoryInteractionEventStore, MySQLInteractionEventStore
from backend.platform.integrations.bridge_auth import InMemoryBridgeAuthStore, SQLiteBridgeAuthStore
from backend.platform.integrations.bridge_auth_postgresql import PostgreSQLBridgeAuthStore
from backend.platform.knowledge import InMemoryKnowledgeStore, KnowledgeDocument, KnowledgeService, PostgreSQLKnowledgeStore, SQLiteKnowledgeStore
from backend.platform.learning import SkillLearningService
from backend.platform.lineage import InMemoryLineageStore, PostgreSQLLineageStore, SQLiteLineageStore
from backend.platform.market import InMemoryMarketStore, MarketMonitoringService, PostgreSQLMarketStore, SQLiteMarketStore
from backend.platform.message_board import InMemoryMessageBoardStore, MessageBoardService, MySQLMessageBoardStore, SQLiteMessageBoardStore
from backend.platform.memory import InMemoryMemoryStore, MemoryService, PostgreSQLMemoryStore, SQLiteMemoryStore
from backend.platform.non_structured import ShardedJSONStore
from backend.platform.metrics import (
    InMemoryMetricDictionaryStore,
    InMemoryMetricVersionStore,
    MetricSemanticCatalog,
    MetricVersionService,
    MySQLMetricVersionStore,
    PostgreSQLMetricDictionaryStore,
    SQLiteMetricDictionaryStore,
)
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
    FallbackSupersonicClient,
    InMemorySupersonicClient,
    SemanticQueryService,
    SupersonicClient,
    SupersonicHTTPClient,
)
from backend.platform.settings import (
    InMemorySystemConfigStore,
    PostgreSQLSystemConfigStore,
    SQLiteSystemConfigStore,
)
from backend.platform.skills import SkillConfigCatalog, SkillExecutor, SkillRegistry
from backend.platform.skills.builtin import build_data_product_skills, build_supersonic_query_skill
from backend.platform.tenancy import TenantScopeService, build_tenant_scope_service


# The local development fallback must use the same human account as the
# product's sole global super administrator.  A synthetic admin identity made
# model selection and authorization diverge after a page refresh.
LOCAL_ANALYSIS_USER_ID = SUPER_ADMIN_USER_ID
LEGACY_TENANT_ID = "tenant_demo"
LEGACY_TENANT_ADMIN_ROLE_ID = "tenant_admin"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_RBAC_EXTENSION_MENU_OBJECTS = frozenset({
    "menu:self-analysis.analysis-config",
    "menu:data-assets.tools",
    "menu:settings.audit",
    "menu:settings.config",
    "skill:data.analysis.profile",
    "skill:data.analysis.descriptive",
    "skill:data.analysis.attribution",
    "skill:data.analysis.predictive",
    "skill:data.governance.assess",
    "skill:conclusion.generate",
    "skill:bi.report.generate",
})


def _prime_csv_catalog_in_background(csv_source: object) -> None:
    """Warm the delivered CSV catalog without extending API listener downtime."""

    thread = threading.Thread(
        target=getattr(csv_source, "prime_catalog"),
        name="smart-data-agent-csv-catalog-warmup",
        daemon=True,
    )
    thread.start()


@dataclass
class PlatformServices:
    runtime_config: RuntimeConfig
    agent_catalog: AgentCatalog
    skill_config_catalog: SkillConfigCatalog
    trace_recorder: TraceRecorder
    permission_broker: PermissionBroker
    approval_store: InMemoryCapabilityApprovalStore | SQLiteCapabilityApprovalStore
    bridge_auth_store: InMemoryBridgeAuthStore | SQLiteBridgeAuthStore | PostgreSQLBridgeAuthStore
    mcp_gateway: MCPGateway
    skill_registry: SkillRegistry
    skill_executor: SkillExecutor
    agent_runtime: AgentRuntime
    knowledge_store: InMemoryKnowledgeStore | SQLiteKnowledgeStore
    knowledge_service: KnowledgeService
    message_board_store: InMemoryMessageBoardStore | SQLiteMessageBoardStore | MySQLMessageBoardStore
    message_board_service: MessageBoardService
    data_asset_store: InMemoryDataAssetStore | SQLiteDataAssetStore
    data_acquisition_store: InMemoryAcquisitionStore | SQLiteAcquisitionStore
    data_acquisition_service: DataAcquisitionService
    topic_metadata_service: CSVTopicMetadataService
    topic_data_resolver: TopicDataResolver
    topic_data_store: TopicDataStore
    topic_data_batch_service: TopicDataBatchService
    automation_store: InMemoryAutomationStore | SQLiteAutomationStore
    automation_runtime: AutomationRuntime
    market_store: InMemoryMarketStore | SQLiteMarketStore
    market_service: MarketMonitoringService
    application_store: InMemoryApplicationStore | SQLiteApplicationStore
    memory_store: InMemoryMemoryStore | SQLiteMemoryStore
    memory_service: MemoryService
    learning_service: SkillLearningService
    metric_dictionary_store: InMemoryMetricDictionaryStore | SQLiteMetricDictionaryStore
    metric_version_service: MetricVersionService
    lineage_store: InMemoryLineageStore | SQLiteLineageStore
    system_config_store: InMemorySystemConfigStore | SQLiteSystemConfigStore
    report_store: InMemoryReportStore | SQLiteReportStore
    report_retention_service: ReportRetentionService
    daily_email_service: DailyEmailReportService
    operating_snapshot_service: OperatingSnapshotService
    audit_store: InMemoryAuditEventStore | SQLiteAuditEventStore
    interaction_event_store: InMemoryInteractionEventStore | MySQLInteractionEventStore
    access_service: AccessControlService
    tenant_scope_service: TenantScopeService
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
    analysis_workspace_service: AnalysisWorkspaceService
    analysis_governance_store: InMemoryAnalysisGovernanceStore | MySQLAnalysisGovernanceStore
    non_structured_store: ShardedJSONStore
    primary_database_pool: PostgreSQLConnectionPool | MySQLConnectionPool | MySQLStoreConnectionPool | None = None
    runtime_kernel: Any = None

    def close(self) -> None:
        policy_repository = self.permission_broker.enforcer.repository
        for resource in (
            policy_repository,
            self.approval_store,
            self.bridge_auth_store,
            self.task_repository,
            self.knowledge_store,
            self.message_board_store,
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
            self.tenant_scope_service,
            self.session_store,
            self.oidc_client,
            self.semantic_service,
            self.rate_limiter,
            self.skill_executor,
            self.runtime_kernel,
            self.primary_database_pool,
        ):
            close = getattr(resource, "close", None)
            if callable(close):
                close()


def build_local_platform(
    db_path: str | Path | None = None,
    *,
    topic_data_root: str | Path | None = None,
) -> PlatformServices:
    """Build a local runnable platform slice for tests and API adapters."""

    runtime_config = load_runtime_config()
    if runtime_config.is_production:
        raise RuntimeConfigurationError(
            "The embedded SQLite/local platform adapter is forbidden in production. "
            "Start the MySQL production runtime instead of build_local_platform()."
        )
    rate_limiter = build_rate_limiter(runtime_config.environment)
    mysql_pool: MySQLConnectionPool | None = None
    if runtime_config.database_url:
        min_size = max(1, min(int(os.getenv("SMART_DATA_AGENT_DB_POOL_MIN", "2")), 20))
        max_size = max(min_size, min(int(os.getenv("SMART_DATA_AGENT_DB_POOL_MAX", "20")), 100))
        mysql_pool = MySQLConnectionPool(
            runtime_config.database_url,
            min_size=min_size,
            max_size=max_size,
            compatible_versions=runtime_config.development_mysql_compatible_versions,
        )
        if runtime_config.auto_migrate:
            with mysql_pool.connection() as connection:
                apply_mysql_schema(
                    runtime_config.database_url,
                    connection=connection,
                    compatible_versions=runtime_config.development_mysql_compatible_versions,
                )
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
        bridge_auth_store = InMemoryBridgeAuthStore()
        message_board_store = InMemoryMessageBoardStore()
    else:
        apply_migrations(db_path)
        policy_repository = SQLitePolicyRepository(db_path, initialize=False)
        initialize_defaults = not policy_repository.list_roles()
        if initialize_defaults:
            policy_repository.seed(roles, assignments, policies, manageable_roles=manageable_roles)
        else:
            _reconcile_local_rbac_extensions(policy_repository, policies)
        reconcile_role_defaults(policy_repository)
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
        bridge_auth_store = SQLiteBridgeAuthStore(db_path)
        message_board_store = SQLiteMessageBoardStore(db_path, initialize=False)
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
    tenant_scope_service = build_tenant_scope_service(
        enforcer=enforcer,
        data_asset_store=data_asset_store,
        db_path=db_path if mysql_pool is None else None,
        relational_pool=MySQLStoreConnectionPool(mysql_pool) if mysql_pool is not None else None,
        raw_table_source=data_acquisition_service.csv_source,
    )
    # Each request primes only its authenticated institution's Data Crawler
    # directory.  Do not warm the shared crawler root here: that would scan
    # another institution's files before the user selects one.
    # A SQLite path denotes an isolated test/local adapter. Keep every
    # filesystem-backed write in that adapter's own directory as well; using
    # the repository Topic_Data root makes otherwise temporary test servers
    # race with each other and mutate developer/runtime snapshots.
    resolved_topic_data_root = (
        Path(topic_data_root)
        if topic_data_root is not None
        else (Path(db_path).expanduser().resolve().parent / "topic-data" if db_path is not None else PROJECT_ROOT / "Topic_Data")
    )
    topic_data_store = TopicDataStore(resolved_topic_data_root)
    topic_data_batch_service = TopicDataBatchService(data_acquisition_service.csv_source, topic_data_store, data_asset_store)
    topic_metadata_service = CSVTopicMetadataService(
        data_acquisition_store,
        data_acquisition_service.csv_source,
    )
    topic_data_resolver = TopicDataResolver(data_acquisition_service)
    knowledge_service = KnowledgeService(
        knowledge_store,
        data_acquisition_store,
        artifact_object_store,
        runtime_config.environment,
    )
    message_board_service = MessageBoardService(message_board_store, knowledge_store, user_directory_store)
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
                if tenant_id == LEGACY_TENANT_ID:
                    data_asset_store.seed_defaults(tenant_id)
                else:
                    data_asset_store.seed_missing_defaults(tenant_id)
            else:
                data_asset_store.seed_missing_defaults(tenant_id)
            purge_retired_samples = getattr(data_asset_store, "purge_retired_sample_assets", None)
            if callable(purge_retired_samples):
                purge_retired_samples(tenant_id)
            _ensure_topic_data_batch_task(automation_runtime, tenant_id, SUPER_ADMIN_USER_ID)
    base_supersonic_client, semantic_client_mode, semantic_fallback_mode, data_source_mode = build_supersonic_client_from_env()
    # Smart Data Agent is a CSV-only consumer.  Semantic execution is backed
    # by the configured Origin_Data/Topic_Data warehouse adapter, never by a
    # legacy tenant data-connection record.
    supersonic_client = base_supersonic_client
    semantic_routing_mode = "origin_topic_data"
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
    supersonic_spec, supersonic_handler = build_supersonic_query_skill(
        semantic_service,
        data_acquisition_service.csv_source,
    )
    skill_registry.register(supersonic_spec, supersonic_handler)
    for data_product_spec, data_product_handler in build_data_product_skills():
        skill_registry.register(data_product_spec, data_product_handler)
    skill_executor = SkillExecutor(
        skill_registry,
        permission_broker,
        trace_recorder,
        rate_limiter=rate_limiter,
        approval_store=approval_store,
    )
    agent_runtime = AgentRuntime(agent_catalog, skill_executor, trace_recorder)
    learning_service = SkillLearningService(
        audit_store,
        data_asset_store,
        memory_service,
        trace_recorder=trace_recorder,
    )

    workflow = AnalysisWorkflow(
        skill_executor,
        knowledge_store,
        memory_store,
        planning_catalog=AnalysisPlanningCatalog.from_config_path(PROJECT_ROOT / "configs" / "analysis" / "intent_rules.json"),
        agent_runtime=agent_runtime,
        learning_service=learning_service,
        metric_semantic_catalog=MetricSemanticCatalog.from_config_path(
            PROJECT_ROOT / "configs" / "analysis" / "metric_definitions.json",
            metric_dictionary_store,
        ),
    )

    analysis_workspace_service = AnalysisWorkspaceService(
        MySQLAnalysisWorkspaceStore(mysql_pool) if mysql_pool is not None else InMemoryAnalysisWorkspaceStore()
    )
    analysis_governance_store = (
        MySQLAnalysisGovernanceStore(mysql_pool) if mysql_pool is not None else InMemoryAnalysisGovernanceStore()
    )
    metric_version_service = MetricVersionService(
        MySQLMetricVersionStore(mysql_pool) if mysql_pool is not None else InMemoryMetricVersionStore()
    )
    non_structured_store = ShardedJSONStore(
        os.getenv(
            "SMART_DATA_AGENT_NON_STRUCTURED_ROOT",
            str(PROJECT_ROOT / "runtime" / "non_structured"),
        ),
        max_shard_bytes=int(os.getenv("SMART_DATA_AGENT_JSON_SHARD_MAX_BYTES", str(8 * 1024 * 1024))),
        max_documents=int(os.getenv("SMART_DATA_AGENT_JSON_SHARD_MAX_DOCUMENTS", "1000")),
    )
    interaction_event_store = MySQLInteractionEventStore(mysql_pool) if mysql_pool is not None else InMemoryInteractionEventStore()

    services = PlatformServices(
        runtime_config=runtime_config,
        agent_catalog=agent_catalog,
        skill_config_catalog=skill_config_catalog,
        trace_recorder=trace_recorder,
        permission_broker=permission_broker,
        approval_store=approval_store,
        bridge_auth_store=bridge_auth_store,
        mcp_gateway=mcp_gateway,
        skill_registry=skill_registry,
        skill_executor=skill_executor,
        agent_runtime=agent_runtime,
        knowledge_store=knowledge_store,
        knowledge_service=knowledge_service,
        message_board_store=message_board_store,
        message_board_service=message_board_service,
        data_asset_store=data_asset_store,
        data_acquisition_store=data_acquisition_store,
        data_acquisition_service=data_acquisition_service,
        topic_metadata_service=topic_metadata_service,
        topic_data_resolver=topic_data_resolver,
        topic_data_store=topic_data_store,
        topic_data_batch_service=topic_data_batch_service,
        automation_store=automation_store,
        automation_runtime=automation_runtime,
        market_store=market_store,
        market_service=market_service,
        application_store=application_store,
        memory_store=memory_store,
        memory_service=memory_service,
        learning_service=learning_service,
        metric_dictionary_store=metric_dictionary_store,
        metric_version_service=metric_version_service,
        lineage_store=lineage_store,
        system_config_store=system_config_store,
        report_store=report_store,
        report_retention_service=report_retention_service,
        daily_email_service=daily_email_service,
        operating_snapshot_service=operating_snapshot_service,
        audit_store=audit_store,
        interaction_event_store=interaction_event_store,
        access_service=access_service,
        tenant_scope_service=tenant_scope_service,
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
        analysis_workspace_service=analysis_workspace_service,
        analysis_governance_store=analysis_governance_store,
        non_structured_store=non_structured_store,
        primary_database_pool=mysql_pool,
    )
    _bind_runtime_kernel(services)
    automation_runtime.platform_services = services
    if runtime_config.environment in {"development", "test"} and db_path is not None:
        for tenant_id in [normalize_tenant_id(tenant) for tenant in OPERATING_TENANTS] + [LEGACY_TENANT_ID]:
            _ensure_topic_data_batch_task(automation_runtime, tenant_id, SUPER_ADMIN_USER_ID)
    return services


def build_production_platform(runtime_config: RuntimeConfig | None = None) -> PlatformServices:
    """Build a persistent runtime on the sole supported MySQL primary."""

    runtime_config = runtime_config or load_runtime_config()
    if (
        runtime_config.development_mysql_compatible_versions
        and runtime_config.environment not in {"development", "test"}
    ):
        raise RuntimeConfigurationError(
            "Development MySQL compatibility versions are forbidden outside development/test"
        )
    if runtime_config.environment == "test":
        raise RuntimeConfigurationError("Test runtimes must opt into an isolated adapter explicitly")
    if not runtime_config.database_url:
        raise RuntimeConfigurationError("SMART_DATA_AGENT_DATABASE_URL is required")
    if not runtime_config.database_url.lower().startswith(("mysql://", "mysql+pymysql://")):
        raise RuntimeConfigurationError("SMART_DATA_AGENT_DATABASE_URL must point to MySQL")
    return _build_mysql_production_platform(runtime_config)


def _build_mysql_production_platform(runtime_config: RuntimeConfig) -> PlatformServices:
    """Compose existing domain Stores over the verified MySQL DB-API adapter."""

    min_size = max(1, min(int(os.getenv("SMART_DATA_AGENT_DB_POOL_MIN", "2")), 20))
    max_size = max(min_size, min(int(os.getenv("SMART_DATA_AGENT_DB_POOL_MAX", "20")), 100))
    raw_pool = MySQLConnectionPool(
        runtime_config.database_url,
        min_size=min_size,
        max_size=max_size,
        compatible_versions=runtime_config.development_mysql_compatible_versions,
    )
    pool = MySQLStoreConnectionPool(raw_pool)
    try:
        if runtime_config.auto_migrate:
            with raw_pool.connection() as connection:
                apply_mysql_schema(
                    runtime_config.database_url,
                    connection=connection,
                    compatible_versions=runtime_config.development_mysql_compatible_versions,
                )

        policy_repository = PostgreSQLPolicyRepository(pool)
        reconcile_role_defaults(policy_repository)
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
        bridge_auth_store = PostgreSQLBridgeAuthStore(pool)
        message_board_store = MySQLMessageBoardStore(raw_pool)

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
        if runtime_config.auth_mode == "strict":
            oidc_client.validate_config()
        artifact_object_store = _build_artifact_object_store(runtime_config, None)
        data_acquisition_service = DataAcquisitionService(
            data_acquisition_store,
            artifact_object_store,
            system_config_store,
            task_repository,
            data_asset_store=data_asset_store,
        )
        tenant_scope_service = build_tenant_scope_service(
            enforcer=enforcer,
            data_asset_store=data_asset_store,
            relational_pool=pool,
            raw_table_source=data_acquisition_service.csv_source,
        )
        _prime_csv_catalog_in_background(data_acquisition_service.csv_source)
        topic_data_store = TopicDataStore(PROJECT_ROOT / "Topic_Data")
        topic_data_batch_service = TopicDataBatchService(data_acquisition_service.csv_source, topic_data_store, data_asset_store)
        topic_metadata_service = CSVTopicMetadataService(
            data_acquisition_store,
            data_acquisition_service.csv_source,
        )
        topic_data_resolver = TopicDataResolver(data_acquisition_service)
        knowledge_service = KnowledgeService(
            knowledge_store,
            data_acquisition_store,
            artifact_object_store,
            runtime_config.environment,
        )
        message_board_service = MessageBoardService(message_board_store, knowledge_store, user_directory_store)
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
        )
        data_acquisition_service.automation_runtime = automation_runtime
        base_client, semantic_client_mode, semantic_fallback_mode, data_source_mode = build_supersonic_client_from_env()
        # Keep the production execution boundary consistent with the local
        # CSV-only product: configured warehouses are selected at startup,
        # not from the retired tenant data-connection control plane.
        supersonic_client = base_client
        semantic_routing_mode = "origin_topic_data"
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
        supersonic_spec, supersonic_handler = build_supersonic_query_skill(
            semantic_service,
            data_acquisition_service.csv_source,
        )
        skill_registry.register(supersonic_spec, supersonic_handler)
        for data_product_spec, data_product_handler in build_data_product_skills():
            skill_registry.register(data_product_spec, data_product_handler)
        skill_executor = SkillExecutor(
            skill_registry,
            permission_broker,
            trace_recorder,
            rate_limiter=rate_limiter,
            approval_store=approval_store,
        )
        agent_runtime = AgentRuntime(agent_catalog, skill_executor, trace_recorder)
        learning_service = SkillLearningService(
            audit_store,
            data_asset_store,
            memory_service,
            trace_recorder=trace_recorder,
        )
        workflow = AnalysisWorkflow(
            skill_executor,
            knowledge_store,
            memory_store,
            planning_catalog=AnalysisPlanningCatalog.from_config_path(PROJECT_ROOT / "configs" / "analysis" / "intent_rules.json"),
            agent_runtime=agent_runtime,
            learning_service=learning_service,
            metric_semantic_catalog=MetricSemanticCatalog.from_config_path(
                PROJECT_ROOT / "configs" / "analysis" / "metric_definitions.json",
                metric_dictionary_store,
            ),
        )
        analysis_workspace_service = AnalysisWorkspaceService(MySQLAnalysisWorkspaceStore(raw_pool))
        analysis_governance_store = MySQLAnalysisGovernanceStore(raw_pool)
        metric_version_service = MetricVersionService(MySQLMetricVersionStore(raw_pool))
        interaction_event_store = MySQLInteractionEventStore(raw_pool)
        non_structured_store = ShardedJSONStore(
            os.getenv(
                "SMART_DATA_AGENT_NON_STRUCTURED_ROOT",
                str(PROJECT_ROOT / "runtime" / "non_structured"),
            ),
            max_shard_bytes=int(os.getenv("SMART_DATA_AGENT_JSON_SHARD_MAX_BYTES", str(8 * 1024 * 1024))),
            max_documents=int(os.getenv("SMART_DATA_AGENT_JSON_SHARD_MAX_DOCUMENTS", "1000")),
        )
        services = PlatformServices(
            runtime_config=runtime_config,
            agent_catalog=agent_catalog,
            skill_config_catalog=skill_config_catalog,
            trace_recorder=trace_recorder,
            permission_broker=permission_broker,
            approval_store=approval_store,
            bridge_auth_store=bridge_auth_store,
            mcp_gateway=mcp_gateway,
            skill_registry=skill_registry,
            skill_executor=skill_executor,
            agent_runtime=agent_runtime,
            knowledge_store=knowledge_store,
            knowledge_service=knowledge_service,
            message_board_store=message_board_store,
            message_board_service=message_board_service,
            data_asset_store=data_asset_store,
            data_acquisition_store=data_acquisition_store,
            data_acquisition_service=data_acquisition_service,
            topic_metadata_service=topic_metadata_service,
            topic_data_resolver=topic_data_resolver,
            topic_data_store=topic_data_store,
            topic_data_batch_service=topic_data_batch_service,
            automation_store=automation_store,
            automation_runtime=automation_runtime,
            market_store=market_store,
            market_service=market_service,
            application_store=application_store,
            memory_store=memory_store,
            memory_service=memory_service,
            learning_service=learning_service,
            metric_dictionary_store=metric_dictionary_store,
            metric_version_service=metric_version_service,
            lineage_store=lineage_store,
            system_config_store=system_config_store,
            report_store=report_store,
            report_retention_service=report_retention_service,
            daily_email_service=daily_email_service,
            operating_snapshot_service=operating_snapshot_service,
            audit_store=audit_store,
            interaction_event_store=interaction_event_store,
            access_service=access_service,
            tenant_scope_service=tenant_scope_service,
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
            analysis_workspace_service=analysis_workspace_service,
            analysis_governance_store=analysis_governance_store,
            non_structured_store=non_structured_store,
            primary_database_pool=pool,
        )
        _bind_runtime_kernel(services, relational_pool=raw_pool)
        automation_runtime.platform_services = services
        if runtime_config.environment in {"development", "test"}:
            for tenant_id in [normalize_tenant_id(tenant) for tenant in OPERATING_TENANTS] + [LEGACY_TENANT_ID]:
                try:
                    data_asset_store.seed_missing_defaults(tenant_id, updated_by=SUPER_ADMIN_USER_ID)
                except Exception:
                    pass
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
    # A MySQL-backed development runtime must keep attachment bytes across API
    # restarts just like its structured metadata. Production still requires the
    # configured S3/OSS adapter above.
    return LocalArtifactObjectStore(PROJECT_ROOT / "runtime" / "artifacts")


def _register_automation_handlers(
    runtime: AutomationRuntime,
    data_acquisition_service: DataAcquisitionService,
    report_store: InMemoryReportStore | SQLiteReportStore,
    data_asset_store: InMemoryDataAssetStore | SQLiteDataAssetStore,
    application_store: InMemoryApplicationStore | SQLiteApplicationStore,
    market_service: MarketMonitoringService,
) -> None:
    from backend.platform.api.routes.data_crawler_schedule import data_crawler_dispatch_handler

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

    def topic_data_batch_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        services = getattr(runtime, "platform_services", None)
        if services is None:
            raise RuntimeError("automation_platform_services_not_bound")
        return services.topic_data_batch_service.run(tenant_id, str(context["actor_user_id"]))

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

    def metric_subscription_handler(
        tenant_id: str,
        config: dict,
        trigger_payload: dict,
        context: dict,
    ) -> dict:
        from backend.platform.automation.metric_subscription import collect_metric_snapshot

        services = getattr(runtime, "platform_services", None)
        if services is None:
            raise RuntimeError("automation_platform_services_not_bound")
        configured_metrics = config.get("metrics") if isinstance(config.get("metrics"), list) else []
        metrics = [dict(metric) for metric in configured_metrics if isinstance(metric, dict)]
        if not metrics and isinstance(config.get("metric"), dict):  # Compatibility with existing one-metric tasks.
            metrics = [dict(config["metric"])]
        if not metrics:
            raise ValueError("metric_subscription_metrics_required")
        snapshots = [collect_metric_snapshot(services, tenant_id, str(context["actor_user_id"]), metric) for metric in metrics]
        subscription_id = str(config.get("subscription_id") or "").strip()
        if not subscription_id:
            raise ValueError("metric_subscription_id_required")
        run_id = str(context["automation_run_id"])
        runtime.store.enqueue_outbox_event(
            tenant_id,
            "metric_subscription",
            subscription_id,
            "metric.daily.snapshot.ready",
            {"snapshots": snapshots, "message_template": config.get("message_template") if isinstance(config.get("message_template"), dict) else {}},
            event_key=f"metric-subscription:{subscription_id}:{run_id}",
            created_by=str(context["actor_user_id"]),
        )
        return {"subscription_id": subscription_id, "metric_count": len(snapshots), "snapshots": snapshots}

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
    runtime.register_handler("analysis.run", analysis_handler)
    runtime.register_handler("topic-data.refresh", topic_data_batch_handler)
    runtime.register_handler("analysis.monitor", metric_monitor_handler)
    runtime.register_handler("metric.subscription.snapshot", metric_subscription_handler)
    runtime.register_handler("report.weekly_learning", report_learning_handler)
    runtime.register_handler("market.evaluate", market_evaluate_handler)
    runtime.register_handler("memory.extract", memory_extraction_handler)
    runtime.register_handler("data_crawler.dispatch", data_crawler_dispatch_handler)


def _bind_runtime_kernel(services: PlatformServices, *, relational_pool: Any | None = None) -> None:
    from backend.platform.analysis_profiles import (
        load_analysis_profiles,
        load_relational_tenant_codes_by_institution,
        prepare_loan_analysis_capabilities,
        remap_analysis_profile_tenants,
        verify_loan_analysis_capabilities,
    )
    from backend.platform.kernel.jobs import register_runtime_jobs
    from backend.platform.kernel.kernel import build_runtime_kernel

    capability_import_actor = os.getenv(
        "SMART_DATA_AGENT_CAPABILITY_IMPORT_ACTOR",
        "system" if services.runtime_config.is_production else SUPER_ADMIN_USER_ID,
    ).strip()
    if not capability_import_actor:
        raise RuntimeConfigurationError("SMART_DATA_AGENT_CAPABILITY_IMPORT_ACTOR must not be empty")
    capability_mode = os.getenv(
        "SMART_DATA_AGENT_CAPABILITY_MODE",
        "verify" if services.runtime_config.is_production else "seed",
    ).strip().lower()
    analysis_profiles = load_analysis_profiles()
    if relational_pool is not None:
        with relational_pool.connection() as connection:
            tenant_codes_by_institution = load_relational_tenant_codes_by_institution(connection)
        profile_institutions = {
            str(profile.get("institution") or "").strip()
            for profile in analysis_profiles["institutions"]
            if str(profile.get("institution") or "").strip()
        }
        missing_institutions = sorted(profile_institutions - tenant_codes_by_institution.keys())
        if missing_institutions:
            raise RuntimeConfigurationError(
                "Production capability tenant catalog is incomplete: " + ", ".join(missing_institutions)
            )
        analysis_profiles = remap_analysis_profile_tenants(
            analysis_profiles,
            tenant_codes_by_institution,
        )
    elif services.runtime_config.is_production:
        raise RuntimeConfigurationError("Production capability lifecycle requires relational tenant catalog")
    if capability_mode == "seed":
        prepare_loan_analysis_capabilities(
            services.data_asset_store,
            services.memory_store,
            import_actor=capability_import_actor,
            profiles=analysis_profiles,
        )
    elif capability_mode == "verify":
        verify_loan_analysis_capabilities(
            services.data_asset_store,
            services.memory_store,
            profiles=analysis_profiles,
        )
    else:
        raise RuntimeConfigurationError("SMART_DATA_AGENT_CAPABILITY_MODE must be seed or verify")
    kernel = build_runtime_kernel(services)
    services.runtime_kernel = kernel
    services.workflow.runtime_kernel = kernel
    register_runtime_jobs(services.automation_runtime, kernel)


def _ensure_topic_data_batch_task(runtime: AutomationRuntime, tenant_id: str, owner_user_id: str) -> None:
    """Idempotently provision the user-requested daily Origin→Topic batch."""

    task_code = "system.topic-data.daily-refresh"
    existing = runtime.store.get_task_by_code(tenant_id, task_code)
    definition = {
        "task_code": task_code,
        "task_name": "主题数据每日定时加工",
        "task_type": "acquisition",
        "trigger_type": "schedule",
        "schedule_expression": "0 2 * * *",
        "handler_ref": "topic-data.refresh",
        "task_config": {"schedule_timezone": "Asia/Shanghai", "source": "Data_Crawler/<机构名>", "target": "Topic_Data/<机构名>"},
        "retry_policy": {"max_attempts": 3, "base_delay_seconds": 600, "fixed_delay": True},
        "timeout_seconds": 3_600,
        "max_concurrency": 1,
    }
    if existing is None:
        runtime.create_task(tenant_id, definition, owner_user_id)
        return
    if (
        str(existing.get("handler_ref") or "") != definition["handler_ref"]
        or str(existing.get("schedule_expression") or "") != definition["schedule_expression"]
        or dict(existing.get("task_config") or {}) != definition["task_config"]
    ):
        runtime.update_task(
            tenant_id,
            str(existing["automation_task_id"]),
            {**definition, "status": "active"},
            owner_user_id,
            # A newly created SQLite task legitimately starts at revision 0.
            # Treating that value as falsy made the local bootstrap submit
            # revision 1, which is rejected before the service can start.
            int(existing.get("lock_version", 0)),
        )
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
    """Add only newly introduced system menu/skill grants to an existing local DB.

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
        ("u_chenlei", "三峡银行", "操作员"),
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
                PermissionPolicy(role_id, tenant_id, "skill:data.analysis.profile", "execute"),
                PermissionPolicy(role_id, tenant_id, "skill:data.analysis.descriptive", "execute"),
                PermissionPolicy(role_id, tenant_id, "skill:data.analysis.attribution", "execute"),
                PermissionPolicy(role_id, tenant_id, "skill:data.analysis.predictive", "execute"),
                PermissionPolicy(role_id, tenant_id, "skill:data.governance.assess", "execute"),
                PermissionPolicy(role_id, tenant_id, "skill:conclusion.generate", "execute"),
                PermissionPolicy(role_id, tenant_id, "skill:bi.report.generate", "execute"),
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
