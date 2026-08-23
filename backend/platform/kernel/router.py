from __future__ import annotations

from typing import Any

from backend.platform.orchestration.planning import AnalysisPlanningCatalog
from backend.platform.kernel.models import CapabilityPack, RouteDecision
from backend.platform.tenancy import ExecutionContext


class IntentRouter:
    """Route from question + page context + pack index. Does not execute skills."""

    def __init__(self, planning_catalog: AnalysisPlanningCatalog) -> None:
        self.planning_catalog = planning_catalog

    def route(self, context: ExecutionContext, question: str, pack: CapabilityPack) -> RouteDecision:
        base = self.planning_catalog.select(question)
        dataset_id = base.dataset_id
        metrics = tuple(base.metrics)
        dimensions = tuple(base.dimensions)
        chart_types = tuple(base.chart_types)
        matched: list[str] = []
        normalized = (question or "").casefold()
        page_hint = context.page_context.get("asset_context") if isinstance(context.page_context, dict) else {}
        selected_tables = page_hint.get("selected_data_tables") if isinstance(page_hint, dict) else []
        page_locked = bool(selected_tables)
        for entry in pack.entries:
            trigger = entry.get("trigger") if isinstance(entry.get("trigger"), dict) else {}
            if str(entry.get("kind") or "") not in {"procedure", "memory"}:
                continue
            if str(entry.get("status") or "") != "active":
                continue
            dataset = str(trigger.get("dataset_id") or "").strip()
            intent = str(trigger.get("intent_rule_id") or "").strip()
            terms = trigger.get("terms") if isinstance(trigger.get("terms"), (list, tuple)) else ()
            term_hit = any(str(term).casefold() in normalized for term in terms if str(term).strip())
            if dataset and dataset == dataset_id:
                matched.append(str(entry["capability_id"]))
            elif intent and intent == base.rule_id:
                matched.append(str(entry["capability_id"]))
            elif term_hit:
                matched.append(str(entry["capability_id"]))
                if dataset and not page_locked:
                    dataset_id = dataset
                trigger_metrics = trigger.get("metrics") if isinstance(trigger.get("metrics"), (list, tuple)) else ()
                trigger_dims = trigger.get("dimensions") if isinstance(trigger.get("dimensions"), (list, tuple)) else ()
                if trigger_metrics and not page_locked:
                    metrics = tuple(str(item) for item in trigger_metrics if str(item).strip())
                if trigger_dims and not page_locked:
                    dimensions = tuple(str(item) for item in trigger_dims if str(item).strip())
        return RouteDecision(
            intent_rule_id=base.rule_id,
            task_type=base.task_type,
            dataset_id=dataset_id,
            metrics=metrics,
            dimensions=dimensions,
            chart_types=chart_types,
            capability_ids=tuple(dict.fromkeys(matched)),
            planning_source="runtime_router",
        )
