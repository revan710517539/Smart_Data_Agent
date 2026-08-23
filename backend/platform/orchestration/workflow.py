from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable
from uuid import uuid4

from backend.platform.knowledge import InMemoryKnowledgeStore
from backend.platform.knowledge.models import KnowledgeHit
from backend.platform.memory import InMemoryMemoryStore, MemoryRecord
from backend.platform.metrics import MetricSemanticCatalog
from backend.platform.data_processing import PythonSandbox
from backend.platform.agents import AgentRuntime
from backend.platform.skills import SkillExecutor, SkillRequest
from backend.platform.tenancy import ExecutionContext

from .planning import AnalysisIntentRule, AnalysisPlanningCatalog
from .state import AgentStep, AnalysisTask, TaskType


class AnalysisWorkflowError(RuntimeError):
    def __init__(self, task: AnalysisTask, code: str = "analysis_execution_failed") -> None:
        super().__init__(code)
        self.task = task
        self.code = code


class AnalysisWorkflow:
    """Governed analysis orchestration.

    This is still deterministic for local reliability, but it now separates
    intent routing, analysis planning, skill execution, review, and memory write.
    That keeps the current UI stable while giving the backend a replaceable
    Agent orchestration boundary.
    """

    def __init__(
        self,
        skill_executor: SkillExecutor,
        knowledge_store: InMemoryKnowledgeStore,
        memory_store: InMemoryMemoryStore,
        planning_catalog: AnalysisPlanningCatalog | None = None,
        python_sandbox: PythonSandbox | None = None,
        agent_runtime: AgentRuntime | None = None,
        learning_service: Any | None = None,
        metric_semantic_catalog: MetricSemanticCatalog | None = None,
    ) -> None:
        self.skill_executor = skill_executor
        self.knowledge_store = knowledge_store
        self.memory_store = memory_store
        self.planning_catalog = planning_catalog or AnalysisPlanningCatalog.default()
        self.python_sandbox = python_sandbox or PythonSandbox()
        self.agent_runtime = agent_runtime
        self.learning_service = learning_service
        self.metric_semantic_catalog = metric_semantic_catalog
        self.runtime_kernel: Any | None = None

    def create_task(self, context: ExecutionContext, question: str) -> AnalysisTask:
        intent_rule = self._select_intent_rule(context, question)
        return AnalysisTask(
            question=question,
            task_type=intent_rule.task_type,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            request_id=str(context.page_context.get("request_id") or f"req_{uuid4().hex[:16]}"),
            revision=max(1, int(context.page_context.get("revision") or 1)),
            parent_execution_id=str(context.page_context.get("parent_execution_id") or "") or None,
            status="running",
        )

    def run(
        self,
        context: ExecutionContext,
        question: str,
        task: AnalysisTask | None = None,
        planning_hook: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> AnalysisTask:
        planning_question = str(context.page_context.get("analysis_planning_question") or question).strip() or question
        intent_rule = self._select_intent_rule(context, planning_question)
        task_type = intent_rule.task_type
        task = task or self.create_task(context, question)
        if self.agent_runtime:
            task.agent_group_run = self.agent_runtime.begin_group("analysis_execution")
            self.agent_runtime.require_operation("planner", "knowledge.search")

        knowledge_hits = self.knowledge_store.search(question, tenant_id=context.tenant_id)
        active_memories = self.memory_store.search(
            context.tenant_id,
            statuses=("active",),
            limit=20,
        )
        visible_memories = [
            memory
            for memory in active_memories
            if memory.subject_type == "tenant"
            or (memory.subject_type == "user" and memory.subject_id == context.user_id)
        ][:10]
        task.knowledge_refs = []
        create_citation = getattr(self.knowledge_store, "create_citation", None)
        for hit in knowledge_hits:
            citation = (
                create_citation(
                    context.tenant_id,
                    hit,
                    "analysis_task",
                    task.execution_id,
                    context.user_id,
                )
                if callable(create_citation) and hit.chunk_id
                else {}
            )
            task.knowledge_refs.append(
                {
                    "doc_id": hit.document.doc_id,
                    "title": hit.document.title,
                    "version_no": hit.document.version_no,
                    "chunk_id": hit.chunk_id,
                    "locator": hit.locator,
                    "score": hit.score,
                    "citation_id": citation.get("citation_id"),
                    "quote_hash": citation.get("quote_hash"),
                }
            )
        task.analysis_plan = self._build_analysis_plan(
            intent_rule,
            knowledge_hits,
            visible_memories,
            planning_question,
            tenant_id=context.tenant_id,
        )
        task.analysis_plan = _apply_page_analysis_context(task.analysis_plan, context.page_context)
        selected_raw_table = _selected_raw_table(context.page_context)
        if selected_raw_table is not None:
            task.analysis_plan = _build_temporary_raw_table_plan(
                task.analysis_plan,
                selected_raw_table,
                planning_question,
            )
        if self.learning_service is not None:
            learned_skills = self.learning_service.resolve_analysis_skills(
                context,
                question,
                task.analysis_plan,
            )
            if learned_skills:
                task.analysis_plan = self._apply_learned_skill_context(task.analysis_plan, learned_skills)
        model_planning_step: AgentStep | None = None
        if callable(planning_hook):
            model_planning = planning_hook(dict(task.analysis_plan))
            if isinstance(model_planning, dict) and model_planning:
                task.analysis_plan = self._apply_model_planning(task.analysis_plan, model_planning)
                context.page_context["model_planning"] = dict(model_planning)
                context.page_context["model_sql_candidate"] = str(model_planning.get("sql") or "")
                context.page_context["model_python_script"] = str(model_planning.get("python_script") or "")
                context.page_context["model_data_processing_python"] = str(model_planning.get("data_processing_python") or "")
                model_planning_step = AgentStep(
                    "SelectedModelPlanner",
                    "model.plan",
                    {
                        "planning_source": model_planning.get("planning_source"),
                        "planning_status": (model_planning.get("planning_invocation") or {}).get("status"),
                        "validation_errors": list(model_planning.get("validation_errors") or []),
                    },
                )
        if self.agent_runtime:
            self.agent_runtime.complete_gate(
                task.agent_group_run,
                "plan_compiled",
                bool(task.analysis_plan.get("dataset_id") and task.analysis_plan.get("metrics")),
                {"dataset_id": task.analysis_plan.get("dataset_id")},
            )
        task.plan.append(
            AgentStep(
                "PlannerAgent",
                "plan",
                {
                    "task_type": task.task_type,
                    "dataset_id": task.analysis_plan["dataset_id"],
                    "metrics": task.analysis_plan["metrics"],
                    "dimensions": task.analysis_plan["dimensions"],
                    "chart_types": task.analysis_plan["chart_types"],
                },
            )
        )
        if model_planning_step:
            task.plan.append(model_planning_step)
        task.plan.append(AgentStep("KnowledgeAgent", "search", {"hit_count": len(knowledge_hits)}))
        task.plan.append(
            AgentStep(
                "MemoryAgent",
                "recall_active",
                {"memory_count": len(visible_memories), "candidate_memory_used": False},
            )
        )
        if task.analysis_plan.get("applied_learning_skills"):
            task.plan.append(
                AgentStep(
                    "SkillLearningAgent",
                    "apply_reviewed_procedural_skills",
                    {
                        "skill_ids": [
                            item["skill_id"]
                            for item in task.analysis_plan["applied_learning_skills"]
                        ],
                        "activation_policy": "active_only_before_request",
                    },
                )
            )

        skill_request = SkillRequest(
                skill_id="supersonic.query",
                context=context,
                inputs={
                    "question": question,
                    "dataset_id": task.analysis_plan["dataset_id"],
                    "metrics": tuple(task.analysis_plan["metrics"]),
                    "dimensions": tuple(task.analysis_plan["dimensions"]),
                    "filters": task.analysis_plan["filters"],
                    "limit": task.analysis_plan["limit"],
                    "sort_direction": task.analysis_plan["sort"]["direction"],
                    "context": {
                        "analysis_plan": task.analysis_plan,
                        "task_type": task_type,
                        "selected_raw_table": selected_raw_table or {},
                        "connection_id": str(
                            context.page_context.get("connection_id")
                            or context.page_context.get("selected_connection_id")
                            or ""
                        ),
                        "manual_sql_candidate": str(context.page_context.get("manual_sql_candidate") or ""),
                        "model_sql_candidate": str(context.page_context.get("model_sql_candidate") or ""),
                        "query_revision": task.revision,
                    },
                },
            )
        result = self._execute_product_skill("data_query", skill_request)
        if self.agent_runtime:
            semantic_info = result.output.get("semantic_info", {})
            self.agent_runtime.complete_gate(
                task.agent_group_run,
                "permission_enforced",
                bool(isinstance(semantic_info, dict) and semantic_info.get("policy_enforced_at_source")),
                {"policy_enforced_at_source": semantic_info.get("policy_enforced_at_source") if isinstance(semantic_info, dict) else False},
            )
        enriched_result = self._render_visualization(task.analysis_plan, result.output, context.page_context)
        task.skill_results.append(enriched_result)
        task.plan.append(AgentStep("DataQueryAgent", "supersonic.query", {"row_count": len(enriched_result["data"])}))
        task.plan.append(
            AgentStep(
                "VisualizationAgent",
                "python.render",
                {
                    "chart_type": enriched_result.get("visualization_artifact", {}).get("type"),
                    "point_count": len(enriched_result.get("visualization_artifact", {}).get("series", [])),
                },
            )
        )

        task.conclusions.append(self._summarize(task_type, task.analysis_plan, enriched_result))
        task.plan.append(AgentStep("InsightAgent", "summarize", {"conclusion_count": len(task.conclusions)}))
        task.review = {"status": "pending_final_review", "checks": {}}
        return task

    def enrich_with_data_product_skills(
        self,
        context: ExecutionContext,
        task: AnalysisTask,
        question: str,
    ) -> AnalysisTask:
        """Run the stable analysis/conclusion/BI/governance skill chain."""

        if not task.skill_results:
            return task
        method_kinds = _analysis_method_kinds(context.page_context)
        method_skill_ids = tuple(
            f"data.analysis.{kind}"
            for kind in method_kinds
            if kind in {"descriptive", "attribution", "predictive"}
        )
        required_skill_ids = (
            "data.analysis.profile",
            *method_skill_ids,
            "data.governance.assess",
            "conclusion.generate",
            "bi.report.generate",
        )
        missing_permissions = [
            skill_id
            for skill_id in required_skill_ids
            if not self.skill_executor.permission_broker.check_resource(
                context,
                f"skill:{skill_id}",
                "execute",
            )
        ]
        if missing_permissions:
            # The Hermes-style product-skill chain is an additive capability.
            # Existing custom roles keep their previous access contract instead
            # of failing an analysis or silently receiving broader permissions.
            task.plan.append(
                AgentStep(
                    "SkillAuthorizationAgent",
                    "skip_optional_data_product_skills",
                    {"missing_skill_permissions": missing_permissions},
                )
            )
            return task
        result = dict(task.skill_results[0])
        rows = result.get("data") if isinstance(result.get("data"), list) else []
        semantic_info = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
        learned = [
            item
            for item in task.analysis_plan.get("applied_learning_skills", [])
            if isinstance(item, dict)
        ]
        profile_result = self._execute_product_skill(
            "data_analysis",
            SkillRequest(
                skill_id="data.analysis.profile",
                context=context,
                inputs={
                    "data": rows,
                    "metrics": list(task.analysis_plan.get("metrics") or []),
                    "dimensions": list(task.analysis_plan.get("dimensions") or []),
                },
            ),
        )
        profile = dict(profile_result.output["analysis_profile"])
        analysis_methods: list[dict[str, Any]] = []
        for method_skill_id in method_skill_ids:
            method_result = self._execute_product_skill(
                "data_analysis",
                SkillRequest(
                    skill_id=method_skill_id,
                    context=context,
                    inputs={
                        "data": rows,
                        "analysis_plan": task.analysis_plan,
                        "semantic_info": semantic_info,
                    },
                ),
            )
            analysis_methods.append(dict(method_result.output["analysis_method"]))
        governance_result = self._execute_product_skill(
            "data_governance",
            SkillRequest(
                skill_id="data.governance.assess",
                context=context,
                inputs={
                    "data": rows,
                    "dataset_id": str(task.analysis_plan.get("dataset_id") or ""),
                    "semantic_info": semantic_info,
                },
            ),
        )
        governance = dict(governance_result.output["governance_assessment"])
        conclusion_result = self._execute_product_skill(
            "conclusion",
            SkillRequest(
                skill_id="conclusion.generate",
                context=context,
                inputs={
                    "question": question,
                    "analysis_plan": task.analysis_plan,
                    "analysis_profile": profile,
                    "governance_assessment": governance,
                    "learned_guidance": learned,
                },
            ),
        )
        conclusions = list(conclusion_result.output["conclusions"])
        report_result = self._execute_product_skill(
            "bi_report",
            SkillRequest(
                skill_id="bi.report.generate",
                context=context,
                inputs={
                    "question": question,
                    "analysis_plan": task.analysis_plan,
                    "analysis_profile": profile,
                    "governance_assessment": governance,
                    "chart_spec": dict(result.get("chart_spec") or {}),
                    "conclusions": conclusions,
                },
            ),
        )
        task.skill_results[0] = {
            **result,
            "analysis_profile": profile,
            "analysis_methods": analysis_methods,
            "governance_assessment": governance,
            "conclusion_contract": conclusion_result.output["conclusion_contract"],
            "bi_report_spec": report_result.output["report_spec"],
        }
        task.conclusions.extend(conclusions)
        task.plan.extend(
            [
                AgentStep("DataAnalysisAgent", "data.analysis.profile", {"profile_hash": profile["profile_hash"]}),
                *[
                    AgentStep(
                        "DataAnalysisAgent",
                        str(method.get("skill_id") or ""),
                        {
                            "kind": method.get("kind"),
                            "claim_level": (method.get("evidence_boundary") or {}).get("claim_level"),
                        },
                    )
                    for method in analysis_methods
                ],
                AgentStep(
                    "DataGovernanceAgent",
                    "data.governance.assess",
                    {
                        "quality_score": governance["quality_score"],
                        "issue_count": len(governance["issues"]),
                    },
                ),
                AgentStep(
                    "ConclusionAgent",
                    "conclusion.generate",
                    {"conclusion_count": len(conclusions), "learned_skill_count": len(learned)},
                ),
                AgentStep(
                    "BIReportAgent",
                    "bi.report.generate",
                    {"content_hash": report_result.output["report_spec"]["content_hash"]},
                ),
            ]
        )
        return task

    def _execute_product_skill(self, agent_id: str, request: SkillRequest):
        if self.runtime_kernel is not None:
            if self.agent_runtime:
                self.agent_runtime.require_operation(agent_id, request.skill_id)
            envelope = self.runtime_kernel.executor.execute(
                request.context,
                request.skill_id,
                request.inputs,
                agent_id=agent_id,
                approval_id=request.approval_id,
            )
            from backend.platform.skills import SkillResult

            return SkillResult(
                skill_id=request.skill_id,
                output=dict(envelope.get("output") or {}),
                audit={"runtime_entry": "unified_executor"},
            )
        if self.agent_runtime:
            return self.agent_runtime.execute_skill(agent_id, request)
        return self.skill_executor.execute(request)

    def _select_intent_rule(self, context: ExecutionContext, question: str) -> AnalysisIntentRule:
        base = self.planning_catalog.select(question)
        page_hint = _analysis_plan_hint(context.page_context)
        if page_hint is not None:
            return AnalysisIntentRule(
                rule_id=f"page_context:{page_hint['dataset_id']}",
                task_type=base.task_type,
                terms=(),
                dataset_id=page_hint["dataset_id"],
                metrics=tuple(page_hint["metrics"]),
                dimensions=tuple(page_hint["dimensions"]),
                chart_types=tuple(page_hint["chart_types"] or base.chart_types),
                analysis_angles=tuple(page_hint["analysis_angles"] or base.analysis_angles),
            )
        runtime_route = context.page_context.get("runtime_route") if isinstance(context.page_context, dict) else {}
        if (
            isinstance(runtime_route, dict)
            and runtime_route.get("capability_ids")
            and runtime_route.get("dataset_id")
            and runtime_route.get("metrics")
        ):
            return AnalysisIntentRule(
                rule_id=str(runtime_route.get("intent_rule_id") or base.rule_id),
                task_type=base.task_type,
                terms=(),
                dataset_id=str(runtime_route["dataset_id"]),
                metrics=tuple(str(item) for item in runtime_route.get("metrics") or () if str(item).strip()),
                dimensions=tuple(str(item) for item in runtime_route.get("dimensions") or () if str(item).strip()) or base.dimensions,
                chart_types=tuple(str(item) for item in runtime_route.get("chart_types") or () if str(item).strip()) or base.chart_types,
                analysis_angles=base.analysis_angles,
            )
        asset_context = context.page_context.get("asset_context")
        tables = asset_context.get("selected_data_tables") if isinstance(asset_context, dict) else []
        selected = next(
            (table for table in (tables or []) if isinstance(table, dict) and str(table.get("datasetId") or "").strip()),
            None,
        )
        if not isinstance(selected, dict):
            return base
        dataset_id = str(selected.get("datasetId") or "").strip()
        metric_codes = _string_values(selected.get("metricCodes"))
        dimensions = _string_values(selected.get("dimensionCodes"))
        if not dataset_id or not metric_codes or not dimensions:
            return base
        definitions = (
            self.metric_semantic_catalog.list_definitions(dataset_id)
            if self.metric_semantic_catalog
            else []
        )
        normalized_question = question.casefold()
        matched_metrics = [
            str(definition.get("metric_code") or "")
            for definition in definitions
            if str(definition.get("metric_code") or "") in metric_codes
            and _metric_matches_question(definition, normalized_question)
        ]
        default_metrics = [metric for metric in _string_values(selected.get("defaultMetrics")) if metric in metric_codes]
        selected_metrics = list(dict.fromkeys(matched_metrics or default_metrics or metric_codes[:2]))
        field_labels = {
            str(field.get("fieldNameEn") or ""): str(field.get("fieldNameCn") or "")
            for field in (selected.get("fields") or [])
            if isinstance(field, dict)
        }
        matched_dimensions = [
            dimension
            for dimension in dimensions
            if _dimension_matches_question(dimension, field_labels.get(dimension, ""), normalized_question)
        ]
        default_dimensions = [dimension for dimension in _string_values(selected.get("defaultDimensions")) if dimension in dimensions]
        selected_dimensions = list(dict.fromkeys(matched_dimensions or default_dimensions or dimensions[:2]))
        return AnalysisIntentRule(
            rule_id=f"selected_asset:{selected.get('id') or dataset_id}",
            task_type=base.task_type,
            terms=(),
            dataset_id=dataset_id,
            metrics=tuple(selected_metrics),
            dimensions=tuple(selected_dimensions),
            chart_types=tuple(_normalized_chart_types(selected.get("chartTypes")) or base.chart_types),
            analysis_angles=tuple(_string_values(selected.get("analysisAngles")) or base.analysis_angles),
        )

    def finalize(self, context: ExecutionContext, task: AnalysisTask, intelligent_analysis: dict) -> AnalysisTask:
        """Review the final evidence and only then persist a memory candidate."""

        output = task.skill_results[0] if task.skill_results else {}
        task.review = self._review_result(task.analysis_plan, output, intelligent_analysis)
        semantic_info = output.get("semantic_info", {}) if isinstance(output.get("semantic_info"), dict) else {}
        task.execution_mode = _task_execution_mode(semantic_info)
        task.status = "completed" if task.review.get("status") == "passed" else "review_required"
        if self.agent_runtime and task.agent_group_run:
            evidence = output.get("evidence", {}) if isinstance(output.get("evidence"), dict) else {}
            self.agent_runtime.complete_gate(
                task.agent_group_run,
                "evidence_bound",
                bool(evidence.get("evidence_id")),
                {"evidence_id": evidence.get("evidence_id")},
            )
            self.agent_runtime.complete_gate(
                task.agent_group_run,
                "final_review_passed",
                task.review.get("status") == "passed",
                {"review_status": task.review.get("status")},
            )
            task.agent_group_state = self.agent_runtime.snapshot(task.agent_group_run)
        task.plan.append(AgentStep("ReviewAgent", "validate_final_evidence", task.review))
        evidence = output.get("evidence", {}) if isinstance(output.get("evidence"), dict) else {}
        evidence_hash = hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        self.memory_store.write(
            MemoryRecord(
                memory_id=f"mem_{uuid4().hex[:12]}",
                memory_type="analysis_case",
                tenant_id=context.tenant_id,
                subject=task.question,
                content={
                    "memoryTopic": task.question,
                    "memoryAction": task.task_type,
                    "task_type": task.task_type,
                    "analysis_plan": task.analysis_plan,
                    "used_skills": ["supersonic.query"],
                    "knowledge_refs": task.knowledge_refs,
                    "conclusions": task.conclusions,
                    "review": task.review,
                },
                source_trace_id=str(context.page_context.get("trace_id") or "") or None,
                created_by=context.user_id,
                confidence=0.86 if task.review.get("status") == "passed" else 0.62,
                verified_status="candidate",
                subject_type="tenant",
                subject_id=context.tenant_id,
                title=f"分析案例：{task.question[:120]}",
                evidence_type="analysis_evidence",
                evidence_id=str(evidence.get("evidence_id") or task.execution_id),
                evidence_hash=evidence_hash,
            )
        )
        if self.learning_service is not None:
            try:
                learning_result = self.learning_service.observe_analysis_result(context, task)
                task.plan.append(
                    AgentStep(
                        "SkillLearningAgent",
                        "observe_analysis_result",
                        learning_result,
                    )
                )
            except Exception as exc:
                # A learning candidate must never make an otherwise valid
                # analysis fail or change its publication decision.
                task.plan.append(
                    AgentStep(
                        "SkillLearningAgent",
                        "observe_analysis_result",
                        {"observed": False, "error_code": type(exc).__name__},
                    )
                )
        return task

    @staticmethod
    def _apply_learned_skill_context(
        plan: dict[str, Any],
        learned_skills: list[dict[str, Any]],
    ) -> dict[str, Any]:
        analysis_angles = list(plan.get("analysis_angles") or [])
        chart_types = list(plan.get("chart_types") or [])
        for skill in learned_skills:
            analysis_angles.extend(
                angle
                for angle in skill.get("analysisAngles", [])
                if angle not in analysis_angles
            )
            chart_types.extend(
                chart_type
                for chart_type in skill.get("chartTypes", [])
                if chart_type not in chart_types
            )
        return {
            **plan,
            "analysis_angles": analysis_angles[:20],
            "chart_types": chart_types[:8],
            "applied_learning_skills": learned_skills,
            "learning_policy": {
                "source": "reviewed_user_operations",
                "activation": "request_boundary",
                "permission_changes": False,
                "metric_override": False,
            },
        }

    def _build_analysis_plan(
        self,
        intent_rule,
        knowledge_hits: list[KnowledgeHit],
        active_memories: list[MemoryRecord],
        question: str,
        *,
        tenant_id: str,
    ) -> dict:
        from .query_conditions import parse_query_conditions

        conditions = parse_query_conditions(question)
        metric_definitions = (
            self.metric_semantic_catalog.resolve(
                tenant_id,
                intent_rule.dataset_id,
                tuple(intent_rule.metrics),
            )
            if self.metric_semantic_catalog
            else []
        )
        return {
            "intent_rule_id": intent_rule.rule_id,
            "dataset_id": intent_rule.dataset_id,
            "metrics": list(intent_rule.metrics),
            "metric_definitions": metric_definitions,
            "dimensions": list(intent_rule.dimensions),
            "filters": {"tenant_id": "__context_tenant__", **conditions.filters},
            "time_range": conditions.time_range,
            "limit": conditions.limit,
            "sort": {"metric": intent_rule.metrics[0], "direction": conditions.sort_direction},
            "chart_types": list(intent_rule.chart_types),
            "analysis_angles": list(intent_rule.analysis_angles),
            "knowledge_ref_count": len(knowledge_hits),
            "memory_refs": [
                {
                    "memory_id": memory.memory_id,
                    "memory_type": memory.memory_type,
                    "title": memory.title or memory.subject,
                    "content": memory.content,
                    "confidence": memory.confidence,
                }
                for memory in active_memories
            ],
            "memory_policy": "active_only",
            "business_focus": self.planning_catalog.business_focus,
        }

    @staticmethod
    def _summarize(task_type: TaskType, analysis_plan: dict, output: dict) -> str:
        data = output.get("data", []) if isinstance(output.get("data"), list) else []
        semantic_info = output.get("semantic_info", {}) if isinstance(output.get("semantic_info"), dict) else {}
        totals = semantic_info.get("totals", {}) if isinstance(semantic_info.get("totals"), dict) else {}
        primary_metric = str((analysis_plan.get("metrics") or ["metric_value"])[0])
        total = float(totals.get(primary_metric) or 0)
        metrics = "、".join(analysis_plan.get("metrics", []))
        dimensions = "、".join(analysis_plan.get("dimensions", []))
        if task_type == "diagnostic_analysis":
            return f"本轮归因分析采用 {dimensions} 维度，围绕 {metrics} 观察异常来源；完整汇总中的 {primary_metric} 为 {total:,.2f}。"
        return f"本轮分析采用 {dimensions} 维度和 {metrics} 指标，返回 {len(data)} 行明细；完整汇总中的 {primary_metric} 为 {total:,.2f}。"

    @staticmethod
    def _review_result(analysis_plan: dict, output: dict, intelligent_analysis: dict | None = None) -> dict:
        data = output.get("data", [])
        semantic_info = output.get("semantic_info", {})
        visualization_artifact = output.get("visualization_artifact", {})
        processing_artifact = output.get("data_processing_artifact", {}) if isinstance(output.get("data_processing_artifact"), dict) else {}
        evidence = output.get("evidence", {}) if isinstance(output.get("evidence"), dict) else {}
        mapping = semantic_info.get("schema_mapping", {}) if isinstance(semantic_info.get("schema_mapping"), dict) else {}
        mapped_metrics = set(mapping.get("metrics") or ([mapping.get("metric")] if mapping.get("metric") else []))
        mapped_dimensions = set(mapping.get("dimensions") or ([mapping.get("dimension")] if mapping.get("dimension") else []))
        required_metrics = set(analysis_plan.get("metrics", []))
        required_dimensions = set(analysis_plan.get("dimensions", []))
        planned_chart_types = set(_normalized_chart_types(analysis_plan.get("chart_types")))
        output_chart_types = _normalized_chart_types([output.get("chart_spec", {}).get("type")])
        conclusion_coverage = (
            intelligent_analysis.get("conclusion_coverage", {})
            if isinstance(intelligent_analysis, dict) and isinstance(intelligent_analysis.get("conclusion_coverage"), dict)
            else {}
        )
        checks = {
            "has_data": bool(data),
            "has_sql": bool(output.get("sql")),
            "all_metrics_executed": required_metrics.issubset(mapped_metrics),
            "all_dimensions_executed": required_dimensions.issubset(mapped_dimensions),
            "summary_complete": bool(semantic_info.get("summary_complete")),
            "chart_aligned": bool(output_chart_types and output_chart_types[0] in planned_chart_types),
            "python_visualization_ready": bool(visualization_artifact.get("series")),
            "python_data_processing_ready": bool(output.get("data_processing_artifact", {}).get("output_row_count") is not None),
            "python_row_count_preserved": processing_artifact.get("input_row_count") == processing_artifact.get("output_row_count"),
            "python_totals_reconciled": processing_artifact.get("totals") == semantic_info.get("totals"),
            "python_required_fields_preserved": processing_artifact.get("required_fields_preserved") is True,
            "metric_definitions_bound": bool(semantic_info.get("metric_definitions_bound")),
            "conclusion_coverage_complete": bool(
                isinstance(intelligent_analysis, dict)
                and required_metrics.issubset(set(conclusion_coverage.get("metrics_covered") or []))
                and required_metrics.issubset(set(conclusion_coverage.get("extrema_covered_metrics") or []))
                and required_metrics.issubset(set(conclusion_coverage.get("anomaly_checked_metrics") or []))
                and required_dimensions.issubset(set(conclusion_coverage.get("dimensions_covered") or []))
                and conclusion_coverage.get("all_groups_returned") is True
            ),
            "final_analysis_present": isinstance(intelligent_analysis, dict) and bool(intelligent_analysis.get("possible_conclusions")),
            "evidence_bound": bool(
                evidence.get("evidence_id")
                and (
                    (evidence.get("sql_executed") and evidence.get("executed_sql_sha256"))
                    or (not evidence.get("sql_executed") and evidence.get("execution_statement"))
                )
            ),
        }
        passed = all(checks.values())
        publication_blockers: list[str] = []
        if not semantic_info.get("publishable", False):
            publication_blockers.append("data_source_or_evidence_not_publishable")
        if not semantic_info.get("aggregation_semantics_complete", False):
            publication_blockers.append("metric_aggregation_semantics_incomplete")
        return {
            "status": "passed" if passed else "needs_human_review",
            "checks": checks,
            "publication_gate": "allowed" if passed and not publication_blockers else "blocked",
            "publication_blockers": publication_blockers,
        }

    def _render_visualization(self, analysis_plan: dict, output: dict, page_context: dict | None = None) -> dict:
        chart_spec = output.get("chart_spec", {})
        planned_chart_types = _normalized_chart_types(analysis_plan.get("chart_types")) or ["column"]
        rendered_chart_types = _normalized_chart_types([chart_spec.get("type")])
        script = (
            str((page_context or {}).get("manual_python_script") or "")
            or str((page_context or {}).get("model_python_script") or "")
            or self._build_visualization_script()
        )
        context = {
            "chart_type": rendered_chart_types[0] if rendered_chart_types else planned_chart_types[0],
            "x": chart_spec.get("x") or (analysis_plan.get("dimensions") or ["dimension_value"])[0],
            "y": chart_spec.get("y") or "metric_value",
            "title": chart_spec.get("title") or "可视化分析",
            "analysis_angles": analysis_plan.get("analysis_angles", []),
            "business_focus": analysis_plan.get("business_focus", ""),
        }
        semantic_info = output.get("semantic_info") if isinstance(output.get("semantic_info"), dict) else {}
        processing_context = {
            "dataset_id": analysis_plan.get("dataset_id"),
            "metrics": list(analysis_plan.get("metrics") or []),
            "dimensions": list(analysis_plan.get("dimensions") or []),
            "totals": dict(semantic_info.get("totals") or {}),
            "metric_definitions_bound": bool(semantic_info.get("metric_definitions_bound")),
            "metric_definition_versions": dict(semantic_info.get("metric_definition_versions") or {}),
        }
        processing_script = (
            str((page_context or {}).get("manual_data_processing_python") or "")
            or str((page_context or {}).get("model_data_processing_python") or "")
            or self._build_data_processing_script()
        )
        source_rows = output.get("data", []) if isinstance(output.get("data"), list) else []
        fallback_reason = ""
        try:
            processing_result = self.python_sandbox.process_data(processing_script, source_rows, processing_context)
            _validate_processed_rows(source_rows, processing_result.rows, [*processing_context["dimensions"], *processing_context["metrics"]])
        except Exception:
            fallback_script = self._build_data_processing_script()
            if processing_script == fallback_script:
                raise
            fallback_reason = "model_data_processing_integrity_rejected"
            processing_result = self.python_sandbox.process_data(fallback_script, source_rows, processing_context)
            _validate_processed_rows(source_rows, processing_result.rows, [*processing_context["dimensions"], *processing_context["metrics"]])
        visualization_fallback_reason = ""
        try:
            result = self.python_sandbox.render_chart(script, processing_result.rows, context)
        except Exception:
            fallback_script = self._build_visualization_script()
            if script == fallback_script:
                raise
            visualization_fallback_reason = "model_visualization_runtime_rejected"
            result = self.python_sandbox.render_chart(fallback_script, processing_result.rows, context)
        enriched = dict(output)
        enriched["data"] = processing_result.rows
        enriched["data_processing_python_script"] = processing_result.script
        enriched["data_processing_artifact"] = {
            **processing_result.quality,
            "input_row_count": len(source_rows),
            "output_row_count": len(processing_result.rows),
            "required_fields_preserved": True,
            "metric_definitions_bound": processing_context["metric_definitions_bound"],
            "metric_definition_versions": processing_context["metric_definition_versions"],
            "totals": processing_context["totals"],
            "fallback_reason": fallback_reason,
        }
        enriched["python_script"] = result.script
        enriched["visualization_artifact"] = {
            **result.artifact,
            "fallback_reason": visualization_fallback_reason,
        }
        return enriched

    @staticmethod
    def _apply_model_planning(base_plan: dict[str, Any], model_planning: dict[str, Any]) -> dict[str, Any]:
        """Apply only model choices that remain inside the server-owned semantic plan."""

        plan = dict(base_plan)
        base_metrics = [str(item) for item in base_plan.get("metrics") or []]
        base_dimensions = [str(item) for item in base_plan.get("dimensions") or []]
        allowed_metrics = set(base_metrics)
        allowed_dimensions = set(base_dimensions)
        requested_metrics = [str(item) for item in model_planning.get("metrics") or [] if str(item) in allowed_metrics]
        requested_dimensions = [str(item) for item in model_planning.get("dimensions") or [] if str(item) in allowed_dimensions]
        # Server-bound metrics and dimensions are mandatory evidence obligations.
        # The model may prioritize their order, but must never drop an item that
        # the governed intent/asset binder selected from the user's question.
        metrics = list(dict.fromkeys([*requested_metrics, *base_metrics]))
        dimensions = list(dict.fromkeys([*requested_dimensions, *base_dimensions]))
        if metrics:
            plan["metrics"] = metrics
            metric_set = set(metrics)
            definitions = [
                item
                for item in plan.get("metric_definitions") or []
                if isinstance(item, dict)
                and str(item.get("metric_code") or item.get("metric_id") or item.get("id") or item.get("code") or "") in metric_set
            ]
            if definitions:
                plan["metric_definitions"] = definitions
        if dimensions:
            plan["dimensions"] = dimensions
        try:
            plan["limit"] = max(1, min(int(model_planning.get("limit") or plan.get("limit") or 50), 500))
        except (TypeError, ValueError):
            plan["limit"] = max(1, min(int(plan.get("limit") or 50), 500))
        sort = dict(plan.get("sort") or {})
        sort["metric"] = str((plan.get("metrics") or [sort.get("metric") or "metric_value"])[0])
        sort["direction"] = "asc" if str(model_planning.get("sort_direction") or "").lower() == "asc" else "desc"
        plan["sort"] = sort
        approach = [str(item).strip() for item in model_planning.get("analysis_approach") or [] if str(item).strip()]
        if approach:
            plan["analysis_angles"] = approach[:12]
        chart_types = _normalized_chart_types([
            item.get("type")
            for item in model_planning.get("visualization_suggestions") or []
            if isinstance(item, dict)
        ])
        if chart_types:
            plan["chart_types"] = list(dict.fromkeys(chart_types))[:3]
        plan["model_planning"] = {
            key: model_planning.get(key)
            for key in (
                "planning_source",
                "metrics",
                "dimensions",
                "limit",
                "sort_direction",
                "sql",
                "python_script",
                "data_processing_python",
                "visualization_python",
                "analysis_approach",
                "metric_scenarios",
                "visualization_suggestions",
                "validation_errors",
                "planning_invocation",
            )
        }
        return plan

    @staticmethod
    def _build_data_processing_script() -> str:
        return '''def process_data(data, context):
    processed = [dict(row) for row in data]
    return {
        "rows": processed,
        "quality": {
            "input_row_count": len(data),
            "output_row_count": len(processed),
            "metric_definitions_bound": bool(context.get("metric_definitions_bound", False)),
            "metric_definition_versions": context.get("metric_definition_versions", {}),
            "totals": context.get("totals", {}),
        },
    }
'''

    @staticmethod
    def _build_visualization_script() -> str:
        return '''def build_chart(data, context):
    x_field = context.get("x", "dimension_value")
    y_field = context.get("y", "metric_value")
    points = [
        {
            "name": str(row.get(x_field, "")),
            "value": float(row.get(y_field, 0) or 0),
            "metric_id": str(row.get("metric_id", "")),
            "raw": row,
        }
        for row in data
    ]
    return {
        "type": context.get("chart_type", "column"),
        "title": context.get("title", "可视化分析"),
        "x": x_field,
        "y": y_field,
        "series": points,
        "table_rows": data[:20],
        "analysis_angles": list(context.get("analysis_angles", [])),
        "business_focus": str(context.get("business_focus", "")),
        "runtime": "local_python_sandbox",
    }
'''


def _string_values(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _selected_raw_table(page_context: dict[str, Any]) -> dict[str, Any] | None:
    asset_context = page_context.get("asset_context") if isinstance(page_context, dict) else None
    selected = asset_context.get("selected_data_tables") if isinstance(asset_context, dict) else []
    raw_tables = [
        table
        for table in selected or []
        if isinstance(table, dict)
        and not str(table.get("datasetId") or "").strip()
        and str(table.get("relativePath") or "").strip()
    ]
    if not raw_tables:
        return None
    if len(raw_tables) != 1 or len([table for table in selected or [] if isinstance(table, dict)]) != 1:
        raise ValueError("analysis_selected_raw_table_requires_single_source")
    return raw_tables[0]


def _build_temporary_raw_table_plan(
    base_plan: dict[str, Any],
    table: dict[str, Any],
    question: str,
) -> dict[str, Any]:
    fields = [field for field in table.get("fields") or [] if isinstance(field, dict)]
    normalized_question = str(question or "").casefold()
    normalized_fields = [
        {
            "code": str(field.get("fieldNameEn") or "").strip(),
            "name": str(field.get("fieldNameCn") or field.get("fieldNameEn") or "").strip(),
            "type": str(field.get("type") or "string").strip().lower(),
            "is_time": bool(field.get("isTime")) or str(field.get("type") or "").lower() in {"date", "datetime"},
        }
        for field in fields
        if str(field.get("fieldNameEn") or "").strip()
    ]
    numeric = [field for field in normalized_fields if field["type"] in {"integer", "decimal", "number", "float"}]
    non_numeric = [field for field in normalized_fields if field not in numeric]
    matched_numeric = [
        field for field in numeric
        if any(token and token.casefold() in normalized_question for token in (field["code"], field["name"]))
    ]
    matched_dimensions = [
        field for field in non_numeric
        if any(token and token.casefold() in normalized_question for token in (field["code"], field["name"]))
    ]
    metrics = (matched_numeric or numeric)[:20]
    synthetic_count = not metrics
    if synthetic_count:
        metrics = [{"code": "row_count", "name": "记录数", "type": "integer", "is_time": False}]
    preferred_dimensions = [*matched_dimensions, *[field for field in non_numeric if field["is_time"]], *non_numeric]
    dimensions = list({field["code"]: field for field in preferred_dimensions}.values())[:4]
    dataset_id = str(table.get("tableNameEn") or table.get("code") or table.get("id") or "selected_raw_csv").strip()
    version = str(table.get("schemaVersion") or table.get("schemaFingerprint") or table.get("contentHash") or "temporary")[:64]
    grain = "、".join(field["name"] for field in dimensions) or "整张原始表"
    definitions = []
    for metric in metrics:
        label = metric["name"]
        aggregation = "count" if metric["code"] == "row_count" else "avg" if any(token in label for token in ("率", "比例", "均值", "平均", "户均")) else "sum"
        definitions.append({
            "metric_code": metric["code"],
            "metric_name": label,
            "dataset_id": dataset_id,
            "aggregation": aggregation,
            "numerator": "",
            "denominator": "",
            "multiplier": 1,
            "unit": "%" if "率" in label else "",
            "grain": grain,
            "version": version,
            "source": "temporary_table_schema",
        })
    plan = dict(base_plan)
    plan.update({
        "dataset_id": dataset_id,
        "metrics": [metric["code"] for metric in metrics],
        "metric_definitions": definitions,
        "dimensions": [field["code"] for field in dimensions],
        "filters": {"tenant_id": "__context_tenant__"},
        "limit": min(max(1, int(base_plan.get("limit") or 50)), 500),
        "sort": {"metric": metrics[0]["code"], "direction": "desc"},
        "chart_types": ["line", "table"] if any(field["is_time"] for field in dimensions) else ["column", "table"],
        "analysis_angles": [
            "仅使用用户本次上传的文件作为数据源，不调度系统数据表"
            if str(table.get("relativePath") or "").startswith("upload://")
            else "仅使用用户明确选择的当前机构原始 CSV",
            "指标口径由字段类型确定性生成并标记为临时口径",
            "临时口径不写回指标字典，需用户结合业务定义复核",
        ],
        "business_focus": f"分析用户选择的原始表“{table.get('tableNameCn') or table.get('name') or dataset_id}”",
        "temporary_metric_semantics": True,
        "temporary_metric_source": "uploaded_file" if str(table.get("relativePath") or "").startswith("upload://") else "selected_raw_csv",
        "synthetic_row_count_metric": synthetic_count,
    })
    return plan


def _normalized_chart_types(value: Any) -> list[str]:
    aliases = {"bar": "column", "radar": "table", "pie": "table"}
    allowed = {"column", "line", "table"}
    normalized = [aliases.get(item.lower(), item.lower()) for item in _string_values(value)]
    return list(dict.fromkeys(item for item in normalized if item in allowed))


def _analysis_plan_hint(page_context: Any) -> dict[str, Any] | None:
    """Accept a bounded page-owned semantic hint; execution still enforces catalog and tenant access."""

    payload = page_context.get("analysis_plan_hint") if isinstance(page_context, dict) else None
    if not isinstance(payload, dict):
        return None
    dataset_id = str(payload.get("dataset_id") or "").strip()[:240]
    metrics = _string_values(payload.get("metrics"))[:20]
    dimensions = _string_values(payload.get("dimensions"))[:20]
    if not dataset_id or not metrics or not dimensions:
        return None
    return {
        "dataset_id": dataset_id,
        "metrics": metrics,
        "dimensions": dimensions,
        "chart_types": _normalized_chart_types(payload.get("chart_types"))[:8],
        "analysis_angles": _string_values(payload.get("analysis_angles"))[:20],
    }


def _apply_page_analysis_context(plan: dict[str, Any], page_context: Any) -> dict[str, Any]:
    """Bind visible page filters without allowing the browser to change tenant scope."""

    if not isinstance(page_context, dict):
        return plan
    preferences = page_context.get("visualization_preferences")
    if isinstance(preferences, dict):
        requested_metrics = _string_values(preferences.get("metrics"))
        requested_dimensions = _string_values(preferences.get("dimensions"))
        current_metrics = _string_values(plan.get("metrics"))
        current_dimensions = _string_values(plan.get("dimensions"))
        safe_metrics = [item for item in requested_metrics if item in current_metrics]
        safe_dimensions = [item for item in requested_dimensions if item in current_dimensions]
        if safe_metrics or safe_dimensions:
            plan = {
                **plan,
                "metrics": [*safe_metrics, *[item for item in current_metrics if item not in safe_metrics]],
                "dimensions": [*safe_dimensions, *[item for item in current_dimensions if item not in safe_dimensions]],
                "visualization_preference_binding": {"source": "user_question", "safe_existing_fields_only": True},
            }
    raw_filters = page_context.get("filters")
    if not isinstance(raw_filters, dict):
        return plan
    allowed = {
        "product_line", "branch_name", "month", "customer_segment", "channel", "stat_date", "stat_week"
    }
    filters = {
        str(key): value
        for key, value in raw_filters.items()
        if str(key) in allowed and value not in (None, "", "all", "全部", "全部分行")
        and isinstance(value, (str, int, float, bool))
    }
    if not filters:
        return plan
    return {
        **plan,
        "filters": {**dict(plan.get("filters") or {}), **filters},
        "page_filter_binding": {
            "source": "authenticated_page_context",
            "filters": filters,
            "tenant_override_allowed": False,
        },
    }


def _analysis_method_kinds(page_context: dict[str, Any]) -> tuple[str, ...]:
    scene = page_context.get("analysis_scene") if isinstance(page_context.get("analysis_scene"), dict) else {}
    kinds = [
        str(item).strip()
        for item in scene.get("analysis_kinds") or []
        if str(item).strip() in {"descriptive", "attribution", "predictive"}
    ]
    if not kinds:
        skill_ids = {
            str(item.get("id") or "").strip()
            for item in page_context.get("analysis_context_skills") or []
            if isinstance(item, dict)
        }
        mapping = {
            "topic-descriptive": "descriptive",
            "topic-attribution": "attribution",
            "topic-predictive": "predictive",
        }
        kinds = [kind for skill_id, kind in mapping.items() if skill_id in skill_ids]
    return tuple(dict.fromkeys(kinds or ["descriptive"]))


def _task_execution_mode(semantic_info: dict[str, Any]) -> str:
    """Map adapter-specific modes onto the persisted task execution contract."""

    mode = str(semantic_info.get("execution_mode") or "").strip().lower()
    if mode in {"real", "mock", "degraded"}:
        return mode
    data_source = str(semantic_info.get("data_source") or "").strip().lower()
    if "mock" in mode or "mock" in data_source:
        return "mock"
    if mode or data_source:
        return "real"
    return "degraded"


def _metric_matches_question(definition: dict[str, Any], normalized_question: str) -> bool:
    code = str(definition.get("metric_code") or "").strip().casefold()
    name = str(definition.get("metric_name") or "").strip().casefold()
    short_name = name.split("（", 1)[0].split("(", 1)[0].strip()
    if any(token and token in normalized_question for token in (code, name, short_name)):
        return True
    governed_patterns = {
        "completion_order_count": r"完件(?:笔数|[\d,.万亿]+\s*笔)",
        "credit_approved_order_count": r"授信(?:通过|成功)(?!率)[\d,.\s万亿]*(?:笔|人|客户)?",
        "drawdown_success_order_count": r"动支成功[\d,.\s万亿]*(?:笔|人|客户)?",
        "drawdown_application_order_count": r"动支申请[\d,.\s万亿]*(?:笔|人|客户)?",
    }
    pattern = governed_patterns.get(code)
    return bool(pattern and re.search(pattern, normalized_question))


def _dimension_matches_question(code: str, label: str, normalized_question: str) -> bool:
    normalized_code = code.strip().casefold()
    normalized_label = label.strip().casefold()
    aliases = {normalized_code, normalized_label}
    for suffix in ("名称", "编码", "编号", "代码", "日期", "月份"):
        if normalized_label.endswith(suffix) and len(normalized_label) > len(suffix):
            aliases.add(normalized_label[: -len(suffix)])
    return any(alias and alias in normalized_question for alias in aliases)


def _validate_processed_rows(
    source_rows: list[dict[str, Any]],
    processed_rows: list[dict[str, Any]],
    required_fields: list[str],
) -> None:
    if len(source_rows) != len(processed_rows):
        raise ValueError("data_processing_row_count_changed")
    fields = list(dict.fromkeys(field for field in required_fields if field))
    if any(any(field not in row for field in fields) for row in processed_rows):
        raise ValueError("data_processing_required_field_missing")
    source_projection = sorted(
        json.dumps({field: row.get(field) for field in fields}, ensure_ascii=False, sort_keys=True, default=str)
        for row in source_rows
    )
    processed_projection = sorted(
        json.dumps({field: row.get(field) for field in fields}, ensure_ascii=False, sort_keys=True, default=str)
        for row in processed_rows
    )
    if source_projection != processed_projection:
        raise ValueError("data_processing_governed_value_changed")
