from __future__ import annotations

from typing import Any

from backend.platform.kernel.events import EventBus
from backend.platform.kernel.executor import UnifiedExecutor
from backend.platform.kernel.loader import CapabilityLoader
from backend.platform.kernel.model_gateway import ModelGateway
from backend.platform.kernel.models import CapabilityPack, Episode, new_id
from backend.platform.kernel.promotion import promote_common_capabilities
from backend.platform.kernel.router import IntentRouter
from backend.platform.kernel.store import InMemoryAccountCapabilityStore
from backend.platform.tenancy import ExecutionContext


class RuntimeKernel:
    """The single in-process runtime: pack, route, execute, emit, learn, promote."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        store: Any,
        loader: CapabilityLoader,
        router: IntentRouter,
        executor: UnifiedExecutor,
        model_gateway: ModelGateway,
        learning_service: Any | None = None,
        draft_provider: Any | None = None,
        automation_runtime: Any | None = None,
        platform_services: Any | None = None,
        hermes_endpoint: Any | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.store = store
        self.loader = loader
        self.router = router
        self.executor = executor
        self.model_gateway = model_gateway
        self.learning_service = learning_service
        self.draft_provider = draft_provider
        self.automation_runtime = automation_runtime
        self.platform_services = platform_services
        self.hermes_endpoint = hermes_endpoint
        self._disposers = [
            event_bus.subscribe("episode.completed", self._on_episode_completed),
        ]

    def close(self) -> None:
        for dispose in self._disposers:
            dispose()
        close = getattr(self.store, "close", None)
        if callable(close):
            close()

    def bind_request(self, context: ExecutionContext) -> CapabilityPack:
        pack = self.loader.compile(context)
        episode = Episode(
            episode_id=str(context.page_context.get("episode_id") or new_id("ep")),
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            session_id=str(context.page_context.get("runtime_session_id") or ""),
            parent_episode_id=str(context.page_context.get("parent_execution_id") or "") or None,
            pack_snapshot_id=pack.snapshot_id,
            question=str(context.page_context.get("analysis_planning_question") or ""),
        )
        self.store.save_episode(
            {
                "episode_id": episode.episode_id,
                "tenant_id": episode.tenant_id,
                "user_id": episode.user_id,
                "session_id": episode.session_id,
                "parent_episode_id": episode.parent_episode_id,
                "pack_snapshot_id": episode.pack_snapshot_id,
                "status": "running",
            }
        )
        route = self.router.route(context, episode.question or str(context.page_context.get("question") or ""), pack)
        from backend.platform.kernel.scene import apply_analysis_scene

        existing_scene = context.page_context.get("analysis_scene") if isinstance(context.page_context.get("analysis_scene"), dict) else {}
        if not str(existing_scene.get("surface") or "").strip():
            catalog = [
                {
                    "id": str((entry.get("trigger") or {}).get("skill_id") or str(entry.get("capability_id") or "").split(":", 1)[-1]),
                    "name": entry.get("title") or "",
                    "description": entry.get("description") or "",
                    "category": (entry.get("trigger") or {}).get("category") or "",
                    "enabled": True,
                    "updatedBy": "development_seed",
                }
                for entry in pack.entries
                if str(entry.get("capability_id") or "").startswith("analysis_skill:")
            ]
            context.page_context.update(
                apply_analysis_scene(
                    episode.question or str(context.page_context.get("question") or ""),
                    dict(context.page_context),
                    catalog,
                )
            )
        scene = context.page_context.get("analysis_scene") if isinstance(context.page_context.get("analysis_scene"), dict) else {}
        scene_caps = tuple(
            f"analysis_skill:{skill_id}"
            for skill_id in (scene.get("skill_ids") or [])
            if str(skill_id).strip()
        )
        if scene_caps:
            route.capability_ids = tuple(dict.fromkeys((*scene_caps, *route.capability_ids)))
        context.page_context["capability_pack"] = {
            "snapshot_id": pack.snapshot_id,
            "entries": [item for item in pack.entries if item.get("kind") in {"procedure", "memory", "plugin"} or item.get("implemented")],
            "entry_count": len(pack.entries),
        }
        context.page_context["pack_snapshot_id"] = pack.snapshot_id
        context.page_context["episode_id"] = episode.episode_id
        context.page_context["runtime_route"] = {
            "intent_rule_id": route.intent_rule_id,
            "task_type": route.task_type,
            "dataset_id": route.dataset_id,
            "metrics": list(route.metrics),
            "dimensions": list(route.dimensions),
            "chart_types": list(route.chart_types),
            "capability_ids": list(route.capability_ids),
            "planning_source": route.planning_source,
        }
        self.event_bus.publish(
            "capability.pack.compiled",
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "snapshot_id": pack.snapshot_id,
                "entry_count": len(pack.entries),
                "episode_id": episode.episode_id,
            },
        )
        self.event_bus.publish(
            "router.decided",
            {"tenant_id": context.tenant_id, "user_id": context.user_id, "route": context.page_context["runtime_route"]},
        )
        return pack

    def finish_request(self, context: ExecutionContext, task: Any, *, status: str) -> None:
        episode_id = str(context.page_context.get("episode_id") or "")
        pack_id = str(context.page_context.get("pack_snapshot_id") or "")
        route = context.page_context.get("runtime_route") if isinstance(context.page_context.get("runtime_route"), dict) else {}
        self.store.save_episode(
            {
                "episode_id": episode_id or new_id("ep"),
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "pack_snapshot_id": pack_id,
                "status": status,
                "task_id": getattr(task, "task_id", ""),
            }
        )
        eval_payload = {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "episode_id": episode_id,
            "status": status,
            "review_status": (getattr(task, "review", None) or {}).get("status") if task is not None else "",
        }
        self.store.record_eval(eval_payload)
        self.event_bus.publish(
            "episode.completed",
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "episode_id": episode_id,
                "status": status,
                "task": task,
                "route": route,
            },
        )
        try:
            self.sync_delivery(context.tenant_id, context.user_id)
        except Exception:
            pass

    def public_analysis_fields(self, context: ExecutionContext) -> dict[str, Any]:
        route = context.page_context.get("runtime_route") if isinstance(context.page_context.get("runtime_route"), dict) else {}
        return {
            "pack_snapshot_id": context.page_context.get("pack_snapshot_id") or "",
            "episode_id": context.page_context.get("episode_id") or "",
            "applied_capabilities": list(route.get("capability_ids") or []),
            "planning_source": route.get("planning_source") or "",
            "analysis_scene": context.page_context.get("analysis_scene") if isinstance(context.page_context.get("analysis_scene"), dict) else {},
        }

    def hermes_status(self) -> dict[str, object]:
        endpoint = self.hermes_endpoint
        if endpoint is None:
            return {"ready": True, "mode": "off", "configured": False}
        return endpoint.public_status()

    def sync_delivery(self, tenant_id: str, user_id: str) -> dict[str, Any]:
        from backend.platform.kernel.delivery import sync_delivery_contracts

        procedures = self.store.list_visible(tenant_id, user_id, statuses=("active",))
        return sync_delivery_contracts(self.automation_runtime, tenant_id, user_id, procedures)

    def promote(self, tenant_id: str, actor_user_id: str, min_accounts: int = 3) -> dict[str, Any]:
        result = promote_common_capabilities(self.store, tenant_id, actor_user_id, min_accounts=min_accounts)
        self.event_bus.publish("capability.promoted", {"tenant_id": tenant_id, **result})
        return result

    def _on_episode_completed(self, event_type: str, payload: dict[str, Any]) -> None:
        del event_type
        task = payload.get("task")
        if self.automation_runtime is None or task is None:
            return
        tenant_id = str(payload.get("tenant_id") or "")
        user_id = str(payload.get("user_id") or "")
        episode_id = str(payload.get("episode_id") or "")
        episode = _desensitized_episode(task, payload.get("route") or {})
        from backend.authz import SUPER_ADMIN_USER_ID
        from backend.platform.kernel.jobs import ensure_runtime_learning_tasks

        ensure_runtime_learning_tasks(self.automation_runtime, [tenant_id], SUPER_ADMIN_USER_ID)
        for task_code, trigger_payload in (
            (
                "system.runtime.learning.observe",
                {
                    "user_id": user_id,
                    "episode_id": episode_id,
                    "event_id": f"episode:{episode_id}",
                    "action": "analysis.completed",
                    "target_type": "runtime_episode",
                },
            ),
            (
                "system.runtime.learning.draft",
                {"user_id": user_id, "episode_id": episode_id, "episode": episode},
            ),
        ):
            automation_task = self.automation_runtime.store.get_task_by_code(tenant_id, task_code)
            if automation_task is None:
                continue
            self.automation_runtime.trigger(
                tenant_id,
                str(automation_task["automation_task_id"]),
                user_id,
                f"{task_code}:{episode_id}",
                trigger_payload,
            )


def build_runtime_kernel(services: Any) -> RuntimeKernel:
    event_bus = EventBus()
    pool = getattr(services, "primary_database_pool", None)
    if pool is not None:
        from backend.platform.kernel.mysql_store import MySQLAccountCapabilityStore

        store = MySQLAccountCapabilityStore(pool)
    else:
        store = InMemoryAccountCapabilityStore()
    loader = CapabilityLoader(
        services.skill_registry,
        store,
        mcp_gateway=services.mcp_gateway,
        memory_store=services.memory_store,
        data_asset_store=getattr(services, "data_asset_store", None),
    )
    router = IntentRouter(services.workflow.planning_catalog)
    model_gateway = ModelGateway(event_bus)
    from backend.platform.kernel.draft_provider import CompositeDraftProvider, HermesDraftProvider
    from backend.platform.kernel.hermes_endpoint import HermesEndpointError, load_hermes_endpoint

    try:
        hermes_endpoint = load_hermes_endpoint()
    except HermesEndpointError:
        hermes_endpoint = load_hermes_endpoint({"SMART_DATA_AGENT_HERMES_MODE": "off"})
    draft_provider = CompositeDraftProvider(HermesDraftProvider(hermes_endpoint))
    executor = UnifiedExecutor(
        services.skill_executor,
        mcp_gateway=services.mcp_gateway,
        lineage_store=services.lineage_store,
        knowledge_store=services.knowledge_store,
        memory_store=services.memory_store,
        model_gateway=model_gateway,
        event_bus=event_bus,
        draft_provider=draft_provider,
    )
    kernel = RuntimeKernel(
        event_bus=event_bus,
        store=store,
        loader=loader,
        router=router,
        executor=executor,
        model_gateway=model_gateway,
        learning_service=services.learning_service,
        draft_provider=draft_provider,
        automation_runtime=services.automation_runtime,
        platform_services=services,
        hermes_endpoint=hermes_endpoint,
    )
    _register_knowledge_handlers(services)
    return kernel


def _register_knowledge_handlers(services: Any) -> None:
    registry = services.skill_registry
    from backend.platform.skills.models import SkillRequest, SkillResult

    def _maybe_register(skill_id: str, handler) -> None:
        try:
            spec = registry.get(skill_id)
        except KeyError:
            return
        status = registry.runtime_status(skill_id)
        if status.get("implemented"):
            return
        registry.register(spec, handler)

    def knowledge_search(request: SkillRequest) -> SkillResult:
        query = str(request.inputs.get("query") or request.inputs.get("question") or "")
        hits = services.knowledge_store.search(query, tenant_id=request.context.tenant_id)
        return SkillResult(skill_id="knowledge.search", output={"hits": [str(getattr(hit.document, "doc_id", "")) for hit in hits]})

    def memory_search(request: SkillRequest) -> SkillResult:
        records = services.memory_store.search(request.context.tenant_id, statuses=("active",), limit=20)
        visible = [
            record
            for record in records
            if getattr(record, "subject_type", "tenant") != "user" or getattr(record, "subject_id", "") == request.context.user_id
        ]
        return SkillResult(skill_id="memory.search", output={"memories": [getattr(item, "memory_id", "") for item in visible]})

    def graph_query(request: SkillRequest) -> SkillResult:
        graph = services.lineage_store.graph(
            request.context.tenant_id,
            str(request.inputs.get("entity_type") or "metric"),
            str(request.inputs.get("entity_id") or request.inputs.get("metric_id") or ""),
        )
        return SkillResult(skill_id="graph.query_metric_lineage", output=graph if isinstance(graph, dict) else {"graph": graph})

    _maybe_register("knowledge.search", knowledge_search)
    _maybe_register("memory.search", memory_search)
    _maybe_register("graph.query_metric_lineage", graph_query)


def _desensitized_episode(task: Any, route: dict[str, Any]) -> dict[str, Any]:
    plan = getattr(task, "analysis_plan", None)
    if not isinstance(plan, dict):
        plan = {}
    return {
        "task_type": getattr(task, "task_type", ""),
        "status": getattr(task, "status", ""),
        "dataset_id": plan.get("dataset_id") or route.get("dataset_id") or "",
        "intent_rule_id": plan.get("intent_rule_id") or route.get("intent_rule_id") or "",
        "metrics": list(plan.get("metrics") or route.get("metrics") or []),
        "dimensions": list(plan.get("dimensions") or route.get("dimensions") or []),
        "steps": [getattr(step, "action", "") for step in (getattr(task, "plan", None) or [])][:12],
        "review_status": (getattr(task, "review", None) or {}).get("status") if isinstance(getattr(task, "review", None), dict) else "",
    }
