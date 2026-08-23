from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.platform.audit.store import sanitize_audit_detail
from backend.platform.tenancy import ExecutionContext


LEARNING_ORIGIN = "smart_data_agent.hermes_learning"
MAX_SKILL_BYTES = 15 * 1024
ANALYSIS_PATTERN_THRESHOLD = 2
OPERATION_PATTERN_THRESHOLD = 3
# Built-in semantic catalog ids used by default routing. They are not a
# tenant's uploaded table and must not become a "learned" Skill source.
_SAMPLE_ANALYSIS_DATASETS = frozenset({
    "loan_operation_mart",
    "risk_operation_mart",
})

_LEARNABLE_OPERATION_PREFIXES = (
    "application.",
    "weekly_report.",
    "data_asset.raw_file.",
    "automation.run.",
)
_IGNORED_ACTION_PREFIXES = (
    "learning.",
    "access.",
    "system.",
    "memory.",
    "approval.",
    "data_asset.item.",
)
_FORBIDDEN_SKILL_CONTENT = (
    "password",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "access_token",
    "refresh_token",
    "private_key",
    "rm -rf",
    "drop table",
    "os.system",
    "subprocess",
    "eval(",
    "exec(",
)


class SkillLearningService:
    """Hermes-inspired procedural learning over existing governed stores.

    Audit events are the source trajectory, analysis_skill assets are the
    versioned procedural memory, and the existing four-eyes review activates a
    candidate. No learned skill can execute code or relax permissions.
    """

    def __init__(
        self,
        audit_store: Any,
        data_asset_store: Any,
        memory_service: Any | None = None,
        *,
        trace_recorder: Any | None = None,
    ) -> None:
        self.audit_store = audit_store
        self.data_asset_store = data_asset_store
        self.memory_service = memory_service
        self.trace_recorder = trace_recorder

    def observe_operation(self, event: dict[str, Any]) -> dict[str, Any]:
        action = str(event.get("action") or "").strip()
        if not self._is_learnable_operation(action):
            return {
                "observed": False,
                "applied_skill_ids": [],
                "applied_memory_ids": [],
                "candidate_id": None,
                "memory_candidate_id": None,
            }
        tenant_id = str(event.get("tenant_id") or "")
        actor_user_id = str(event.get("actor_user_id") or "")
        target_type = str(event.get("target_type") or "")
        target_id = str(event.get("target_id") or "")
        applied = self._match_operation_skills(
            tenant_id,
            actor_user_id,
            action,
            target_type,
            target_id,
        )
        applied_memories = self._match_operation_memories(
            tenant_id,
            actor_user_id,
            action,
            target_type,
            target_id,
        )
        for skill in applied:
            self._write_learning_audit(
                tenant_id,
                actor_user_id,
                "learning.skill.applied",
                "analysis_skill",
                str(skill.get("id") or ""),
                {
                    "skill_version": skill.get("assetVersion"),
                    "learning_kind": "operation_workflow",
                    "source_event_id": event.get("event_id"),
                    "source_action": action,
                },
            )
        for memory in applied_memories:
            self._write_learning_audit(
                tenant_id,
                actor_user_id,
                "learning.memory.applied",
                "memory",
                str(memory.get("memory_id") or ""),
                {
                    "memory_type": memory.get("memory_type"),
                    "learning_kind": "operation_behavior",
                    "source_event_id": event.get("event_id"),
                    "source_action": action,
                },
            )
        memory_candidate = self._maybe_create_operation_memory_candidate(event)
        candidate = self._maybe_create_operation_candidate(event)
        return {
            "observed": True,
            "applied_skill_ids": [str(skill.get("id") or "") for skill in applied],
            "applied_memory_ids": [
                str(memory.get("memory_id") or "") for memory in applied_memories
            ],
            "candidate_id": str(candidate.get("id") or "") if candidate else None,
            "memory_candidate_id": (
                str(memory_candidate.get("memory_id") or "")
                if memory_candidate
                else None
            ),
        }

    def resolve_analysis_skills(
        self,
        context: ExecutionContext,
        question: str,
        analysis_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        del question  # Raw questions are deliberately not persisted or required for matching.
        published = self.data_asset_store.list_published_bundle(context.tenant_id)
        skills = published.get("analysis_skills", [])
        matched: list[dict[str, Any]] = []
        for skill in skills:
            if not self._is_learned_skill(skill, kind="analysis_procedure"):
                continue
            owner_user_id = self._learning_owner_user_id(skill)
            if owner_user_id and owner_user_id != context.user_id:
                continue
            trigger = skill.get("learningTrigger") if isinstance(skill.get("learningTrigger"), dict) else {}
            if str(trigger.get("datasetId") or "") not in {"", str(analysis_plan.get("dataset_id") or "")}:
                continue
            if str(trigger.get("intentRuleId") or "") not in {"", str(analysis_plan.get("intent_rule_id") or "")}:
                continue
            matched.append(self._safe_skill_context(skill))
        for skill in matched:
            self._write_learning_audit(
                context.tenant_id,
                context.user_id,
                "learning.skill.applied",
                "analysis_skill",
                str(skill["skill_id"]),
                {
                    "skill_version": skill["version"],
                    "learning_kind": "analysis_procedure",
                    "dataset_id": analysis_plan.get("dataset_id"),
                    "intent_rule_id": analysis_plan.get("intent_rule_id"),
                },
            )
        return matched

    def observe_analysis_result(
        self,
        context: ExecutionContext,
        task: Any,
    ) -> dict[str, Any]:
        plan = dict(getattr(task, "analysis_plan", {}) or {})
        review = dict(getattr(task, "review", {}) or {})
        applied = [
            str(item.get("skill_id") or "")
            for item in plan.get("applied_learning_skills", [])
            if isinstance(item, dict) and str(item.get("skill_id") or "")
        ]
        pattern = {
            "intent_rule_id": str(plan.get("intent_rule_id") or ""),
            "dataset_id": str(plan.get("dataset_id") or ""),
            "metrics": _strings(plan.get("metrics"))[:12],
            "dimensions": _strings(plan.get("dimensions"))[:12],
            "chart_types": _strings(plan.get("chart_types"))[:8],
            "procedure_steps": _strings(plan.get("procedure_steps"))[:20],
            "methodology": str(plan.get("methodology") or "").strip()[:2000],
            "evidence_memory_ids": _strings(plan.get("evidence_memory_ids"))[:8],
        }
        fingerprint = _stable_hash(
            {
                "user_id": context.user_id,
                "intent_rule_id": pattern["intent_rule_id"],
                "dataset_id": pattern["dataset_id"],
            }
        )[:20]
        status = str(review.get("status") or "")
        event = self._write_learning_audit(
            context.tenant_id,
            context.user_id,
            "learning.analysis.observed",
            "analysis_task",
            str(getattr(task, "task_id", "") or getattr(task, "execution_id", "")),
            {
                "pattern_fingerprint": fingerprint,
                "pattern": pattern,
                "review_status": status,
                "publication_gate": review.get("publication_gate"),
                "applied_skill_ids": applied,
            },
        )
        if status != "passed":
            proposals = [
                self._propose_skill_improvement(context, skill_id, pattern, review)
                for skill_id in applied
            ]
            return {
                "observed": True,
                "event_id": event.get("event_id"),
                "candidate_id": None,
                "improvement_ids": [proposal["id"] for proposal in proposals if proposal],
            }

        matching_events = [
            item
            for item in self.audit_store.list(context.tenant_id, limit=200)
            if item.get("action") == "learning.analysis.observed"
            and item.get("actor_user_id") == context.user_id
            and (item.get("detail") or {}).get("pattern_fingerprint") == fingerprint
            and (item.get("detail") or {}).get("review_status") == "passed"
        ]
        candidate = None
        if len(matching_events) >= ANALYSIS_PATTERN_THRESHOLD:
            candidate = self._create_analysis_candidate(
                context,
                fingerprint,
                pattern,
                matching_events,
            )
        return {
            "observed": True,
            "event_id": event.get("event_id"),
            "candidate_id": str(candidate.get("id") or "") if candidate else None,
            "improvement_ids": [],
        }

    def summary(self, tenant_id: str, actor_user_id: str) -> dict[str, Any]:
        bundle = self.data_asset_store.list_bundle(tenant_id)
        generated = [
            skill
            for skill in bundle.get("analysis_skills", [])
            if self._is_generated_skill(skill)
            and str(skill.get("ownerUserId") or "") in {"", actor_user_id}
        ]
        recent = [
            event
            for event in self.audit_store.list(tenant_id, limit=200)
            if str(event.get("action") or "").startswith("learning.")
            and str(event.get("actor_user_id") or "") == actor_user_id
        ]
        generated_memories = self._generated_memory_summaries(tenant_id, actor_user_id)
        return {
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "architecture": "hermes_inspired_governed_learning",
            "write_policy": "candidate_then_four_eyes_review",
            "generated_skills": generated,
            "generated_memories": generated_memories,
            "counts": {
                "generated": len(generated),
                "review": sum(skill.get("lifecycleStatus") == "review" for skill in generated),
                "active": sum(skill.get("lifecycleStatus") == "active" for skill in generated),
                "generated_memories": len(generated_memories),
                "memory_review": sum(
                    memory.get("status") in {"candidate", "review"}
                    for memory in generated_memories
                ),
                "memory_active": sum(
                    memory.get("status") == "active" for memory in generated_memories
                ),
                "recent_learning_events": len(recent),
                "recent_applications": sum(
                    event.get("action")
                    in {"learning.skill.applied", "learning.memory.applied"}
                    for event in recent
                ),
            },
            "recent_events": recent[:30],
        }

    def _maybe_create_operation_memory_candidate(
        self,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.memory_service is None:
            return None
        tenant_id = str(event.get("tenant_id") or "")
        actor_user_id = str(event.get("actor_user_id") or "")
        action = str(event.get("action") or "")
        target_type = str(event.get("target_type") or "")
        target_id = str(event.get("target_id") or "")
        target_fingerprint = _stable_hash(target_id)[:16] if target_id else ""
        fingerprint = _stable_hash(
            {
                "user_id": actor_user_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
            }
        )[:20]
        matching = [
            item
            for item in self.audit_store.list(tenant_id, limit=200)
            if item.get("actor_user_id") == actor_user_id
            and item.get("action") == action
            and item.get("target_type") == target_type
            and str(item.get("target_id") or "") == target_id
        ]
        if len(matching) < OPERATION_PATTERN_THRESHOLD:
            return None
        memory_id = f"learned-memory-{fingerprint}"
        if self._memory_exists(tenant_id, memory_id):
            return None
        evidence_ids = [str(item.get("event_id") or "") for item in matching[:10]]
        target_fingerprint = _stable_hash(target_id)[:16] if target_id else ""
        evidence_hash = _stable_hash(
            {
                "event_ids": evidence_ids,
                "action": action,
                "target_type": target_type,
                "target_fingerprint": target_fingerprint,
            }
        )
        template = self._reusable_scene_template(tenant_id, action=action)
        candidate = self.memory_service.create_candidate(
            tenant_id,
            {
                "memory_id": memory_id,
                "memory_type": "behavior_habit",
                "subject_type": "user",
                "subject_id": actor_user_id,
                "title": f"操作习惯：{_display_action(action)}",
                "content": {
                    "learning_origin": LEARNING_ORIGIN,
                    "learning_kind": "operation_behavior",
                    "action": action,
                    "target_type": target_type,
                    "target_fingerprint": target_fingerprint,
                    "observation_count": len(matching),
                    "procedure_skill_id": str((template or {}).get("id") or f"learned-operation-{fingerprint}"),
                    "interpretation_policy": (
                        "仅记录重复操作习惯，不推断业务意图、客户属性或权限。"
                    ),
                },
                "confidence": min(0.95, 0.6 + len(matching) * 0.05),
                "weight": 1.0,
                "evidence": {
                    "evidence_type": "audit_event_group",
                    "evidence_id": fingerprint,
                    "evidence_hash": evidence_hash,
                },
            },
            actor_user_id,
        )
        self._write_learning_audit(
            tenant_id,
            actor_user_id,
            "learning.memory.candidate.created",
            "memory",
            memory_id,
            {
                "memory_type": "behavior_habit",
                "learning_kind": "operation_behavior",
                "evidence_fingerprint": fingerprint,
                "observation_count": len(matching),
            },
        )
        return candidate

    def _maybe_create_operation_candidate(self, event: dict[str, Any]) -> dict[str, Any] | None:
        tenant_id = str(event.get("tenant_id") or "")
        actor_user_id = str(event.get("actor_user_id") or "")
        action = str(event.get("action") or "")
        target_type = str(event.get("target_type") or "")
        target_id = str(event.get("target_id") or "")
        target_fingerprint = _stable_hash(target_id)[:16] if target_id else ""
        fingerprint = _stable_hash(
            {
                "user_id": actor_user_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
            }
        )[:20]
        matching = [
            item
            for item in self.audit_store.list(tenant_id, limit=200)
            if item.get("actor_user_id") == actor_user_id
            and item.get("action") == action
            and item.get("target_type") == target_type
            and str(item.get("target_id") or "") == target_id
        ]
        if len(matching) < OPERATION_PATTERN_THRESHOLD:
            return None
        template = self._reusable_scene_template(tenant_id, action=action)
        evidence_ids = [str(item.get("event_id") or "") for item in matching[:10]]
        memory_id = f"learned-memory-{fingerprint}"
        if not self._memory_exists(tenant_id, memory_id):
            return None
        if template is not None:
            return self._evolve_existing_scene(
                tenant_id,
                template,
                actor_user_id,
                kind="operation_workflow",
                trigger={
                    "action": action,
                    "targetType": target_type,
                    "targetFingerprint": target_fingerprint,
                },
                evidence={
                    "eventIds": evidence_ids,
                    "observationCount": len(matching),
                    "fingerprint": fingerprint,
                },
                memory_id=memory_id,
                summary=(
                    f"将连续 {len(matching)} 次同类操作抽象为可审计的操作顺序、"
                    "权限边界与结果校验；不保留原始目标值或业务正文。"
                ),
            )
        skill_id = f"learned-operation-{fingerprint}"
        if self.data_asset_store.get_item(tenant_id, "analysis_skill", skill_id):
            return None
        payload = {
            "id": skill_id,
            "name": f"操作流程：{_display_action(action)}（AI）",
            "category": "场景",
            "description": f"根据用户连续 {len(matching)} 次同类操作提炼的 AI 辅助流程。",
            "memoryRefs": [memory_id] if self._memory_exists(tenant_id, memory_id) else [],
            "toolRefs": [],
            "analysisMethod": f"执行 {action} 时沿用已确认的操作顺序、权限边界和结果校验，不跳过原业务处理。",
            "documentAbstraction": "仅提取操作编码、页面模块、目标类型、结果状态和审计引用，不复制业务正文或凭证。",
            "outputFormat": "操作确认 / 原业务结果 / 审计引用 / 异常提示",
            "viewpointStrategy": "学习层只补充程序性指导，不改变原操作参数，不替代人工选择。",
            "recommendedSkillIds": [],
            "enabled": True,
            "sortOrder": 900,
            "ownerUserId": actor_user_id,
            "learningOrigin": LEARNING_ORIGIN,
            "learningKind": "operation_workflow",
            "learningTrigger": {
                "action": action,
                "targetType": target_type,
                "targetFingerprint": target_fingerprint,
            },
            "learningEvidence": {
                "eventIds": evidence_ids,
                "observationCount": len(matching),
                "fingerprint": fingerprint,
            },
            "learningGuardrails": _guardrails(),
            "updatedAt": _utc_now(),
        }
        return self._persist_candidate(tenant_id, payload, actor_user_id)

    def _create_analysis_candidate(
        self,
        context: ExecutionContext,
        fingerprint: str,
        pattern: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        template = self._reusable_scene_template(
            context.tenant_id,
            dataset_id=str(pattern.get("dataset_id") or ""),
            intent_rule_id=str(pattern.get("intent_rule_id") or ""),
        )
        metrics = _strings(pattern.get("metrics"))
        dimensions = _strings(pattern.get("dimensions"))
        charts = _strings(pattern.get("chart_types"))
        observed_patterns = [
            dict((event.get("detail") or {}).get("pattern") or {})
            for event in events
            if isinstance((event.get("detail") or {}).get("pattern"), dict)
        ]
        source_memory_ids = _unique_strings([
            *(_strings(pattern.get("evidence_memory_ids"))),
            *(memory_id for observed in observed_patterns for memory_id in _strings(observed.get("evidence_memory_ids"))),
        ])[:20]
        procedure_steps = _unique_strings([
            *(_strings(pattern.get("procedure_steps"))),
            *(step for observed in observed_patterns for step in _strings(observed.get("procedure_steps"))),
        ])[:20]
        methodology = str(pattern.get("methodology") or "").strip()
        if not methodology:
            methodology = next((str(observed.get("methodology") or "").strip() for observed in observed_patterns if str(observed.get("methodology") or "").strip()), "")
        memory_id = self._ensure_analysis_memory_candidate(
            context,
            fingerprint,
            pattern,
            events,
            canonical_skill_id=str((template or {}).get("id") or ""),
            canonical_skill_name=str((template or {}).get("name") or "智能分析"),
        )
        if not memory_id:
            return None
        memory_ids = _unique_strings([memory_id, *source_memory_ids])
        evidence = {
            "eventIds": [str(item.get("event_id") or "") for item in events[:20]],
            "successfulObservationCount": len(events),
            "fingerprint": fingerprint,
        }
        trigger = {
            "intentRuleId": pattern.get("intent_rule_id"),
            "datasetId": pattern.get("dataset_id"),
        }
        if template is not None:
            return self._evolve_existing_scene(
                context.tenant_id,
                template,
                context.user_id,
                kind="analysis_procedure",
                trigger=trigger,
                evidence=evidence,
                memory_id=memory_id,
                additional_memory_ids=source_memory_ids,
                summary=(
                    "将审核通过的同类分析轨迹归纳为口径核对、结构拆解、"
                    "异常反证与结论边界四个稳定步骤；不保存原始提问或明细。"
                ),
                procedure={
                    "metrics": metrics,
                    "dimensions": dimensions,
                    "chartTypes": charts,
                    "analysisAngles": procedure_steps or [
                        "先核对指标和时间口径", "再做结构与趋势拆解", "对异常保留反证和治理边界",
                    ],
                    "sourceMethodology": methodology,
                },
            )
        if not _has_real_analysis_source(pattern):
            return None
        skill_id = f"learned-analysis-{fingerprint}"
        if self.data_asset_store.get_item(context.tenant_id, "analysis_skill", skill_id):
            return None
        payload = {
            "id": skill_id,
            "name": "智能分析（AI）",
            "category": "场景",
            "description": f"根据 {len(events)} 次审核通过的同类分析轨迹形成的 AI 辅助程序性 Skill。",
            "memoryRefs": memory_ids,
            "toolRefs": [],
            "analysisMethod": (
                f"优先核对数据集 {pattern.get('dataset_id') or '当前数据集'}；"
                f"围绕 {'、'.join(metrics) or '已选指标'}，按 {'、'.join(dimensions) or '已选维度'} "
                "完成口径确认、结构拆解、异常定位和反证检查。"
            ),
            "documentAbstraction": "提取分析意图、数据集、指标、维度、图表偏好、审核结果和证据引用，不保存原始问题或客户明细。",
            "outputFormat": "核心事实 / 结构与趋势 / 异常与反证 / 数据治理提示 / 经营动作",
            "viewpointStrategy": "事实先于解释；相关性不表述为因果；结论必须带口径、证据和适用边界。",
            "recommendedSkillIds": [],
            "enabled": True,
            "sortOrder": 800,
            "ownerUserId": context.user_id,
            "learningOrigin": LEARNING_ORIGIN,
            "learningKind": "analysis_procedure",
            "learningTrigger": trigger,
            "learnedProcedure": {
                "metrics": metrics,
                "dimensions": dimensions,
                "chartTypes": charts,
                "analysisAngles": procedure_steps or [
                    "先核对指标和时间口径", "再做结构与趋势拆解", "对异常保留反证和治理边界",
                ],
                "sourceMethodology": methodology,
            },
            "learningEvidence": evidence,
            "learningGuardrails": _guardrails(),
            "updatedAt": _utc_now(),
        }
        return self._persist_candidate(context.tenant_id, payload, context.user_id)

    def _reusable_scene_template(
        self,
        tenant_id: str,
        *,
        dataset_id: str = "",
        intent_rule_id: str = "",
        action: str = "",
    ) -> dict[str, Any] | None:
        """Choose a maintained scene before creating an AI-named candidate."""
        bundle = self.data_asset_store.list_published_bundle(tenant_id)
        available_memory_ids = {
            str(item.get("id") or "")
            for key in ("intents", "analysis_experiences", "behavior_habits")
            for item in bundle.get(key, [])
            if str(item.get("id") or "")
        }
        enabled_tool_ids = {
            str(item.get("id") or "")
            for item in bundle.get("external_tools", [])
            if bool(item.get("enabled")) and str(item.get("id") or "")
        }
        markers = " ".join((dataset_id, intent_rule_id, action)).casefold()

        def score(skill: dict[str, Any]) -> int:
            text = " ".join((str(skill.get("name") or ""), str(skill.get("description") or ""))).casefold()
            if any(token in markers for token in ("risk", "overdue", "m1", "逾期", "风险")):
                return 30 if "风险" in text or "risk" in text else 0
            if any(token in markers for token in ("weekly", "week", "周报", "branch_rank")):
                return 30 if "周报" in text or "weekly" in text else 0
            if any(token in markers for token in ("operation", "customer", "loan", "经营", "机构")):
                return 20 if "运营" in text or "日常" in text else 0
            return 0

        scenes = [
            skill
            for skill in bundle.get("analysis_skills", [])
            if str(skill.get("category") or "") == "场景"
            and bool(skill.get("enabled", True))
            and str(skill.get("id") or "") not in {
                "scene-analysis-intent",
                "scene-chart-followup",
                "scene-page-rail",
                "scene-textbox-voice",
                "scene-self-analysis",
                "topic-descriptive",
                "topic-attribution",
                "topic-predictive",
            }
            and not self._is_generated_skill(skill)
        ]
        scenes.sort(key=lambda skill: (-score(skill), int(skill.get("sortOrder") or 999), str(skill.get("name") or "")))
        for index, skill in enumerate(scenes):
            return {
                "id": str(skill.get("id") or ""),
                "name": str(skill.get("name") or "智能分析"),
                "memory_refs": [
                    reference
                    for reference in _strings(skill.get("memoryRefs"))
                    if reference in available_memory_ids
                ],
                "tool_refs": [
                    reference
                    for reference in _strings(skill.get("toolRefs"))
                    if reference in enabled_tool_ids
                ],
                "recommended_skill_ids": _strings(skill.get("recommendedSkillIds")),
                "related_scene_ids": [
                    str(candidate.get("id") or "")
                    for candidate in scenes[index + 1 :]
                    if score(candidate) > 0
                ][:3],
            }
        return None

    def _ensure_analysis_memory_candidate(
        self,
        context: ExecutionContext,
        fingerprint: str,
        pattern: dict[str, Any],
        events: list[dict[str, Any]],
        *,
        canonical_skill_id: str,
        canonical_skill_name: str,
    ) -> str:
        if self.memory_service is None:
            return ""
        memory_id = f"learned-analysis-memory-{fingerprint}"
        if self._memory_exists(context.tenant_id, memory_id):
            return memory_id
        evidence_ids = [str(item.get("event_id") or "") for item in events[:20]]
        evidence_hash = _stable_hash({"event_ids": evidence_ids, "pattern": pattern})
        self.memory_service.create_candidate(
            context.tenant_id,
            {
                "memory_id": memory_id,
                "memory_type": "analysis_case",
                "subject_type": "user",
                "subject_id": context.user_id,
                "title": f"分析方法记忆：{canonical_skill_name}",
                "content": {
                    "learning_origin": LEARNING_ORIGIN,
                    "learning_kind": "analysis_procedure",
                    "canonical_skill_id": canonical_skill_id,
                    "pattern": {
                        "intent_rule_id": str(pattern.get("intent_rule_id") or ""),
                        "dataset_id": str(pattern.get("dataset_id") or ""),
                        "metrics": _strings(pattern.get("metrics"))[:12],
                        "dimensions": _strings(pattern.get("dimensions"))[:12],
                    },
                    "observation_count": len(events),
                    "abstracted_procedure": [
                        "核对口径与数据范围",
                        "拆解结构、趋势与异常",
                        "保留反证、证据与适用边界",
                    ],
                    "interpretation_policy": "仅保存去标识化的程序性方法，不保存原始问题、客户明细或业务正文。",
                },
                "confidence": min(0.95, 0.6 + len(events) * 0.05),
                "weight": 1.0,
                "evidence": {
                    "evidence_type": "audit_event_group",
                    "evidence_id": fingerprint,
                    "evidence_hash": evidence_hash,
                },
            },
            context.user_id,
        )
        self._write_learning_audit(
            context.tenant_id,
            context.user_id,
            "learning.memory.candidate.created",
            "memory",
            memory_id,
            {
                "memory_type": "analysis_case",
                "learning_kind": "analysis_procedure",
                "evidence_fingerprint": fingerprint,
                "observation_count": len(events),
            },
        )
        return memory_id

    def _evolve_existing_scene(
        self,
        tenant_id: str,
        template: dict[str, Any],
        actor_user_id: str,
        *,
        kind: str,
        trigger: dict[str, Any],
        evidence: dict[str, Any],
        memory_id: str,
        additional_memory_ids: list[str] | None = None,
        summary: str,
        procedure: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        skill_id = str(template.get("id") or "")
        current = self.data_asset_store.get_item(tenant_id, "analysis_skill", skill_id)
        if not skill_id or current is None:
            return None
        if current.get("lifecycleStatus") == "review":
            return current
        active = next(
            (
                skill
                for skill in self.data_asset_store.list_published_bundle(tenant_id).get("analysis_skills", [])
                if str(skill.get("id") or "") == skill_id
            ),
            current,
        )
        memory_refs = _unique_strings([
            *_strings(template.get("memory_refs")),
            *([memory_id] if memory_id else []),
            *_strings(additional_memory_ids),
        ])
        payload = {
            **active,
            "memoryRefs": memory_refs,
            "toolRefs": _unique_strings(template.get("tool_refs")),
            "recommendedSkillIds": _unique_strings(template.get("recommended_skill_ids")),
            "learningTrigger": trigger,
            "learnedProcedure": procedure or dict(active.get("learnedProcedure") or {}),
            "learningEvidence": evidence,
            "learningGuardrails": _guardrails(),
            "learningEvolution": {
                "mode": "patch",
                "strategy": "reuse_patch" if not template.get("related_scene_ids") else "reuse_patch_fusion",
                "parentVersion": int(active.get("assetVersion") or 1),
                "kind": kind,
                "ownerUserId": actor_user_id,
                "canonicalSkillId": skill_id,
                "relatedCanonicalSkillIds": _strings(template.get("related_scene_ids")),
                "memoryCandidateId": memory_id,
                "sourceMemoryCandidateIds": _strings(additional_memory_ids),
                "summary": summary,
            },
            "updatedAt": _utc_now(),
        }
        for field in (
            "lifecycleStatus", "assetVersion", "schemaVersion", "lockVersion",
            "submittedBy", "reviewedBy", "reviewedAt", "publishedAt",
            "learningOrigin", "learningKind", "ownerUserId",
        ):
            payload.pop(field, None)
        return self._persist_candidate(tenant_id, payload, actor_user_id)

    def _propose_skill_improvement(
        self,
        context: ExecutionContext,
        skill_id: str,
        pattern: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any] | None:
        active = next(
            (
                skill
                for skill in self.data_asset_store.list_published_bundle(context.tenant_id).get("analysis_skills", [])
                if str(skill.get("id") or "") == skill_id
            ),
            None,
        )
        if not active or not self._is_learned_skill(active, kind="analysis_procedure"):
            return None
        if self._learning_owner_user_id(active) not in {"", context.user_id}:
            return None
        current = self.data_asset_store.get_item(context.tenant_id, "analysis_skill", skill_id)
        if current and current.get("lifecycleStatus") == "review":
            return None
        failed_checks = [
            str(key)
            for key, value in (review.get("checks") or {}).items()
            if value is False
        ]
        reason = "、".join(failed_checks) or str(review.get("publication_gate") or "最终复核未通过")
        payload = {
            **active,
            "viewpointStrategy": (
                str(active.get("viewpointStrategy") or "").rstrip("。")
                + f"；本次因 {reason} 未通过，下一版必须先修复该门禁再生成结论。"
            ),
            "learningEvolution": {
                "parentVersion": int(active.get("assetVersion") or 1),
                "reason": reason,
                "engine": "constraint_guided_reflection",
                "pattern": pattern,
                "kind": self._learning_kind(active),
                "ownerUserId": self._learning_owner_user_id(active),
                "canonicalSkillId": str(active.get("id") or ""),
            },
            "learningEvidence": {
                **dict(active.get("learningEvidence") or {}),
                "lastFailureReason": reason,
            },
            "updatedAt": _utc_now(),
        }
        for field in (
            "lifecycleStatus",
            "assetVersion",
            "schemaVersion",
            "lockVersion",
            "submittedBy",
            "reviewedBy",
            "reviewedAt",
            "publishedAt",
        ):
            payload.pop(field, None)
        return self._persist_candidate(context.tenant_id, payload, context.user_id)

    def _match_operation_skills(
        self,
        tenant_id: str,
        actor_user_id: str,
        action: str,
        target_type: str,
        target_id: str,
    ) -> list[dict[str, Any]]:
        published = self.data_asset_store.list_published_bundle(tenant_id)
        target_fingerprint = _stable_hash(target_id)[:16] if target_id else ""
        matched = []
        for skill in published.get("analysis_skills", []):
            if not self._is_learned_skill(skill, kind="operation_workflow"):
                continue
            if self._learning_owner_user_id(skill) not in {"", actor_user_id}:
                continue
            trigger = skill.get("learningTrigger") if isinstance(skill.get("learningTrigger"), dict) else {}
            if str(trigger.get("action") or "") != action:
                continue
            if str(trigger.get("targetType") or "") not in {"", target_type}:
                continue
            # Historical generated skills may still carry targetId. New
            # candidates use a one-way fingerprint so report/task identifiers
            # never become learned Skill content.
            if str(trigger.get("targetId") or "") not in {"", target_id}:
                continue
            if str(trigger.get("targetFingerprint") or "") not in {
                "",
                target_fingerprint,
            }:
                continue
            matched.append(skill)
        return matched

    def _match_operation_memories(
        self,
        tenant_id: str,
        actor_user_id: str,
        action: str,
        target_type: str,
        target_id: str,
    ) -> list[dict[str, Any]]:
        if self.memory_service is None:
            return []
        target_fingerprint = _stable_hash(target_id)[:16] if target_id else ""
        matched: list[dict[str, Any]] = []
        for memory in self.memory_service.list_active(tenant_id, actor_user_id):
            content = memory.get("content") if isinstance(memory.get("content"), dict) else {}
            if content.get("learning_origin") != LEARNING_ORIGIN:
                continue
            if content.get("learning_kind") != "operation_behavior":
                continue
            if str(content.get("action") or "") != action:
                continue
            if str(content.get("target_type") or "") not in {"", target_type}:
                continue
            if str(content.get("target_fingerprint") or "") not in {
                "",
                target_fingerprint,
            }:
                continue
            matched.append(memory)
        return matched

    def _generated_memory_summaries(
        self,
        tenant_id: str,
        actor_user_id: str,
    ) -> list[dict[str, Any]]:
        if self.memory_service is None:
            return []
        records = [
            *self.memory_service.list_candidates(tenant_id),
            *self.memory_service.list_active(tenant_id, actor_user_id),
        ]
        summaries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for memory in records:
            memory_id = str(memory.get("memory_id") or "")
            content = memory.get("content") if isinstance(memory.get("content"), dict) else {}
            if not memory_id or memory_id in seen:
                continue
            if str(memory.get("created_by") or "") != actor_user_id:
                continue
            if content.get("learning_origin") != LEARNING_ORIGIN:
                continue
            if content.get("learning_kind") != "operation_behavior":
                continue
            seen.add(memory_id)
            summaries.append(
                {
                    "memory_id": memory_id,
                    "memory_type": str(memory.get("memory_type") or ""),
                    "title": str(memory.get("title") or ""),
                    "status": str(memory.get("status") or ""),
                    "confidence": float(memory.get("confidence") or 0),
                    "learning_kind": "operation_behavior",
                    "action": str(content.get("action") or ""),
                    "observation_count": int(content.get("observation_count") or 0),
                }
            )
        return summaries

    def _memory_exists(self, tenant_id: str, memory_id: str) -> bool:
        if self.memory_service is None:
            return False
        try:
            self.memory_service.get(tenant_id, memory_id)
        except KeyError:
            return False
        return True

    def _persist_candidate(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any] | None:
        self._validate_candidate(payload)
        candidate = self.data_asset_store.upsert_item(
            tenant_id,
            "analysis_skill",
            payload,
            updated_by=actor_user_id,
            lifecycle_status="review",
        )
        self._write_learning_audit(
            tenant_id,
            actor_user_id,
            "learning.skill.candidate.created",
            "analysis_skill",
            str(candidate.get("id") or ""),
            {
                "asset_version": candidate.get("assetVersion"),
                "learning_kind": self._learning_kind(candidate),
                "evidence": candidate.get("learningEvidence"),
                "guardrails": candidate.get("learningGuardrails"),
            },
        )
        return candidate

    def _validate_candidate(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        if len(encoded) > MAX_SKILL_BYTES:
            raise ValueError("learned_skill_size_limit_exceeded")
        text = encoded.decode("utf-8").casefold()
        forbidden = next((token for token in _FORBIDDEN_SKILL_CONTENT if token in text), None)
        if forbidden:
            raise ValueError(f"learned_skill_forbidden_content:{forbidden}")
        evolution = payload.get("learningEvolution") if isinstance(payload.get("learningEvolution"), dict) else {}
        learning_origin = payload.get("learningOrigin")
        if not learning_origin and evolution:
            learning_origin = LEARNING_ORIGIN
        learning_kind = payload.get("learningKind") or evolution.get("kind")
        if learning_origin != LEARNING_ORIGIN:
            raise ValueError("learned_skill_origin_required")
        if learning_kind not in {"analysis_procedure", "operation_workflow"}:
            raise ValueError("learned_skill_kind_invalid")
        if not _strings(payload.get("memoryRefs")):
            raise ValueError("learned_skill_memory_required")
        evidence = payload.get("learningEvidence")
        if not isinstance(evidence, dict) or not evidence.get("eventIds"):
            raise ValueError("learned_skill_evidence_required")
        if learning_kind == "analysis_procedure":
            trigger = payload.get("learningTrigger")
            if not isinstance(trigger, dict) or not trigger.get("datasetId"):
                raise ValueError("learned_skill_analysis_trigger_required")

    @staticmethod
    def _safe_skill_context(skill: dict[str, Any]) -> dict[str, Any]:
        procedure = skill.get("learnedProcedure") if isinstance(skill.get("learnedProcedure"), dict) else {}
        return {
            "skill_id": str(skill.get("id") or ""),
            "version": int(skill.get("assetVersion") or 1),
            "name": str(skill.get("name") or ""),
            "analysisMethod": str(skill.get("analysisMethod") or ""),
            "outputFormat": str(skill.get("outputFormat") or ""),
            "viewpointStrategy": str(skill.get("viewpointStrategy") or ""),
            "analysisAngles": _strings(procedure.get("analysisAngles"))[:10],
            "chartTypes": _strings(procedure.get("chartTypes"))[:8],
            "evidenceFingerprint": str((skill.get("learningEvidence") or {}).get("fingerprint") or ""),
        }

    @staticmethod
    def _is_generated_skill(skill: dict[str, Any], *, kind: str | None = None) -> bool:
        if skill.get("learningOrigin") != LEARNING_ORIGIN:
            return False
        if kind and skill.get("learningKind") != kind:
            return False
        return bool(skill.get("enabled", True))

    @classmethod
    def _learning_kind(cls, skill: dict[str, Any]) -> str:
        if skill.get("learningOrigin") == LEARNING_ORIGIN:
            return str(skill.get("learningKind") or "")
        evolution = skill.get("learningEvolution") if isinstance(skill.get("learningEvolution"), dict) else {}
        return str(evolution.get("kind") or "")

    @classmethod
    def _learning_owner_user_id(cls, skill: dict[str, Any]) -> str:
        if skill.get("learningOrigin") == LEARNING_ORIGIN:
            return str(skill.get("ownerUserId") or "")
        evolution = skill.get("learningEvolution") if isinstance(skill.get("learningEvolution"), dict) else {}
        return str(evolution.get("ownerUserId") or "")

    @classmethod
    def _is_learned_skill(cls, skill: dict[str, Any], *, kind: str) -> bool:
        return cls._learning_kind(skill) == kind and bool(skill.get("enabled", True))

    @staticmethod
    def _is_learnable_operation(action: str) -> bool:
        if not action or action.startswith(_IGNORED_ACTION_PREFIXES):
            return False
        return action.startswith(_LEARNABLE_OPERATION_PREFIXES)

    def _write_learning_audit(
        self,
        tenant_id: str,
        actor_user_id: str,
        action: str,
        target_type: str,
        target_id: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        return self.audit_store.write(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=sanitize_audit_detail(detail),
            ip_address="",
        )


def _has_real_analysis_source(pattern: dict[str, Any]) -> bool:
    """Reject default semantic-mart ids that are not a tenant-owned table."""

    dataset_id = str(pattern.get("dataset_id") or "").strip()
    intent_rule_id = str(pattern.get("intent_rule_id") or "").strip()
    if intent_rule_id.startswith("selected_asset:"):
        return True
    if not dataset_id or dataset_id in _SAMPLE_ANALYSIS_DATASETS:
        return False
    return True


def _guardrails() -> dict[str, Any]:
    return {
        "requiresReview": True,
        "fourEyes": True,
        "maxBytes": MAX_SKILL_BYTES,
        "arbitraryCode": False,
        "permissionChanges": False,
        "midConversationActivation": False,
        "sourceContentPolicy": "audit_metadata_only",
    }


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique_strings(value: Any) -> list[str]:
    return list(dict.fromkeys(_strings(value)))


def _display_action(action: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "", action)[:120]
    return value or "用户操作"


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
