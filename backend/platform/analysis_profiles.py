from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.platform.memory import MemoryRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = PROJECT_ROOT / "configs" / "analysis" / "institution_analysis_profiles.json"
SOURCE_PATH = PROJECT_ROOT / "configs" / "analysis" / "loan_analysis_sources.json"
# Data-asset history requires an already provisioned external user identity in
# persistent stores. Candidate import is still system-owned by its lifecycle
# and evidence fields; using the stable super-admin subject only supplies the
# auditable foreign key and does not publish or approve the candidates.
IMPORT_ACTOR = "u_super_admin"

_METHODS = {
    "descriptive": {
        "label": "描述性分析",
        "base": "topic-descriptive",
        "executable": "data.analysis.descriptive",
        "format": "总体 / 结构 / 趋势 / 极值 / 异常 / 口径边界",
    },
    "attribution": {
        "label": "归因分析",
        "base": "topic-attribution",
        "executable": "data.analysis.attribution",
        "format": "变化 / 基线 / 贡献拆解 / 机制证据 / 反证 / 动作",
    },
    "predictive": {
        "label": "预测分析",
        "base": "topic-predictive",
        "executable": "data.analysis.predictive",
        "format": "预测基线 / 区间 / 假设 / 失效条件 / 监控",
    },
}


def load_analysis_profiles(path: str | Path = PROFILE_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(payload.get("schemaVersion") or 0) != 1:
        raise ValueError("institution_analysis_profile_schema_unsupported")
    institutions = payload.get("institutions")
    if not isinstance(institutions, list) or len(institutions) != 11:
        raise ValueError("institution_analysis_profile_count_invalid")
    tenant_ids = [str(item.get("tenantId") or "") for item in institutions if isinstance(item, dict)]
    if len(set(tenant_ids)) != 11 or any(not tenant_id.startswith("tenant:") for tenant_id in tenant_ids):
        raise ValueError("institution_analysis_profile_tenant_invalid")
    return payload


def seed_loan_analysis_candidates(
    data_asset_store: Any,
    memory_store: Any,
    *,
    import_actor: str = IMPORT_ACTOR,
) -> dict[str, int]:
    """Merge institution methods into canonical topic Skills and scoped Memory.

    Institution differences belong to Memory, not to another descriptive,
    attribution or predictive Skill.  Existing institution-named copies are
    archived after their references have been attached to the canonical Skill.
    """

    payload = load_analysis_profiles()
    evidence_hash = hashlib.sha256(PROFILE_PATH.read_bytes() + SOURCE_PATH.read_bytes()).hexdigest()
    skill_count = 0
    archived_count = 0
    memory_count = 0
    for profile in payload["institutions"]:
        tenant_id = str(profile["tenantId"])
        slug = str(profile["slug"])
        data_asset_store.seed_missing_defaults(tenant_id, updated_by=import_actor)
        institution_memory_ids = [
            f"mem_method_{slug}_{kind}"
            for kind in (
                "business_context",
                "descriptive_focus",
                "attribution_evidence",
                "predictive_assumptions",
                "expression_guardrails",
            )
        ]
        common_memory_ids = [f"mem_method_common_{item['kind']}" for item in payload["commonMemories"]]
        for record in _institution_memories(profile, evidence_hash, import_actor=import_actor):
            if not _memory_exists(memory_store, tenant_id, record.memory_id):
                memory_store.write(record)
                memory_count += 1
        for record in _common_memories(
            tenant_id,
            payload["commonMemories"],
            evidence_hash,
            import_actor=import_actor,
        ):
            if not _memory_exists(memory_store, tenant_id, record.memory_id):
                memory_store.write(record)
                memory_count += 1
        expected_memory_ids = [*institution_memory_ids, *common_memory_ids]
        for kind, method in _METHODS.items():
            base_skill_id = str(method["base"])
            base_skill = data_asset_store.get_item(tenant_id, "analysis_skill", base_skill_id)
            if base_skill is None:
                raise RuntimeError(f"production_base_skill_missing:{tenant_id}:{base_skill_id}")
            legacy_skill_id = f"institution.{slug}.{kind}"
            legacy_skill = data_asset_store.get_item(tenant_id, "analysis_skill", legacy_skill_id)
            merged_memory_refs = _unique_strings([
                *(base_skill.get("memoryRefs") or []),
                *expected_memory_ids,
                *((legacy_skill or {}).get("memoryRefs") or []),
            ])
            if merged_memory_refs != _unique_strings(base_skill.get("memoryRefs") or []):
                data_asset_store.upsert_item(
                    tenant_id,
                    "analysis_skill",
                    {**base_skill, "memoryRefs": merged_memory_refs},
                    updated_by=import_actor,
                    lifecycle_status="active",
                )
                skill_count += 1
            if legacy_skill is not None and data_asset_store.delete_item(
                tenant_id, "analysis_skill", legacy_skill_id
            ):
                archived_count += 1
    return {
        "skills_merged": skill_count,
        "institution_skills_archived": archived_count,
        "memories_created": memory_count,
    }


def prepare_loan_analysis_capabilities(
    data_asset_store: Any,
    memory_store: Any,
    *,
    import_actor: str,
) -> dict[str, int]:
    """Idempotently prepare canonical Skills plus governed institution Memory."""

    payload = load_analysis_profiles()
    created = seed_loan_analysis_candidates(
        data_asset_store,
        memory_store,
        import_actor=import_actor,
    )
    verified = verify_loan_analysis_capabilities(data_asset_store, memory_store)
    return {**created, **verified}


def verify_loan_analysis_capabilities(data_asset_store: Any, memory_store: Any) -> dict[str, int]:
    """Fail closed if canonical Skills, Memory, or de-duplication are incomplete."""

    payload = load_analysis_profiles()
    base_skill_ids = {
        "scene-analysis-intent",
        "scene-chart-followup",
        "scene-page-rail",
        "scene-textbox-voice",
        "scene-self-analysis",
        "topic-descriptive",
        "topic-attribution",
        "topic-predictive",
    }
    skill_count = 0
    memory_count = 0
    for profile in payload["institutions"]:
        tenant_id = str(profile["tenantId"])
        slug = str(profile["slug"])
        for skill_id in base_skill_ids:
            item = data_asset_store.get_item(tenant_id, "analysis_skill", skill_id)
            if not item or str(item.get("lifecycleStatus") or "") != "active":
                raise RuntimeError(f"production_base_skill_missing:{tenant_id}:{skill_id}")
        expected_memory_refs = {
            *(f"mem_method_{slug}_{kind}" for kind in (
                "business_context",
                "descriptive_focus",
                "attribution_evidence",
                "predictive_assumptions",
                "expression_guardrails",
            )),
            *(f"mem_method_common_{item['kind']}" for item in payload["commonMemories"]),
        }
        for kind, method in _METHODS.items():
            skill_id = str(method["base"])
            item = data_asset_store.get_item(tenant_id, "analysis_skill", skill_id)
            if not item or str(item.get("lifecycleStatus") or "") != "active":
                raise RuntimeError(f"production_canonical_skill_missing:{tenant_id}:{skill_id}")
            if str(item.get("name") or "") != str(method["label"]):
                raise RuntimeError(f"production_canonical_skill_name_invalid:{tenant_id}:{skill_id}")
            if not expected_memory_refs.issubset(set(_unique_strings(item.get("memoryRefs") or []))):
                raise RuntimeError(f"production_canonical_skill_memory_incomplete:{tenant_id}:{skill_id}")
            duplicate_id = f"institution.{slug}.{kind}"
            if data_asset_store.get_item(tenant_id, "analysis_skill", duplicate_id) is not None:
                raise RuntimeError(f"production_institution_skill_duplicate:{tenant_id}:{duplicate_id}")
            skill_count += 1
        for memory_id in expected_memory_refs:
            try:
                item = memory_store.get(tenant_id, memory_id)
            except KeyError as exc:
                raise RuntimeError(f"production_memory_candidate_missing:{tenant_id}:{memory_id}") from exc
            if str(item.get("status") or item.get("verified_status") or "") not in {"candidate", "review", "active"}:
                raise RuntimeError(f"production_memory_candidate_invalid:{tenant_id}:{memory_id}")
            memory_count += 1
    return {
        "base_skills_verified": len(base_skill_ids) * len(payload["institutions"]),
        "canonical_topic_skills_verified": skill_count,
        "institution_skill_duplicates": 0,
        "memories_verified": memory_count,
    }


def _unique_strings(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _memory_exists(memory_store: Any, tenant_id: str, memory_id: str) -> bool:
    try:
        return memory_store.get(tenant_id, memory_id) is not None
    except KeyError:
        return False


def _analysis_method_text(kind: str, profile: dict[str, Any]) -> str:
    if kind == "attribution":
        return f"先建立对比基线，再{profile['attribution']}；同时寻找反证，不把贡献或相关性直接写成因果。"
    if kind == "predictive":
        return f"先检查历史长度和口径连续性，再{profile['prediction']}；必须输出区间、假设和失效条件。"
    return f"围绕{profile['focus']}描述总量、结构、趋势、极值和异常，不越界解释原因。"


def _institution_memories(
    profile: dict[str, Any],
    evidence_hash: str,
    *,
    import_actor: str,
) -> list[MemoryRecord]:
    slug = str(profile["slug"])
    tenant_id = str(profile["tenantId"])
    institution = str(profile["institution"])
    values = {
        "business_context": str(profile["focus"]),
        "descriptive_focus": f"描述时优先覆盖{profile['focus']}，并同步披露样本和口径。",
        "attribution_evidence": str(profile["attribution"]),
        "predictive_assumptions": str(profile["prediction"]),
        "expression_guardrails": str(profile["guardrail"]),
    }
    return [
        _memory_record(
            tenant_id,
            f"mem_method_{slug}_{kind}",
            f"{institution}-{kind}",
            kind,
            value,
            evidence_hash,
            institution=institution,
            import_actor=import_actor,
        )
        for kind, value in values.items()
    ]


def _common_memories(
    tenant_id: str,
    items: list[dict[str, Any]],
    evidence_hash: str,
    *,
    import_actor: str,
) -> list[MemoryRecord]:
    return [
        _memory_record(
            tenant_id,
            f"mem_method_common_{item['kind']}",
            str(item["title"]),
            str(item["kind"]),
            str(item["content"]),
            evidence_hash,
            institution="common_reviewed_abstraction",
            import_actor=import_actor,
        )
        for item in items
    ]


def _memory_record(
    tenant_id: str,
    memory_id: str,
    title: str,
    profile_kind: str,
    value: str,
    evidence_hash: str,
    *,
    institution: str,
    import_actor: str,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        memory_type="analysis_case",
        tenant_id=tenant_id,
        subject=title,
        title=title,
        content={
            "profileKind": profile_kind,
            "institution": institution,
            "method": value,
            "sourcePolicy": "abstracted_no_raw_internal_content",
        },
        confidence=0.78,
        verified_status="candidate",
        subject_type="tenant",
        subject_id=tenant_id,
        evidence_type="method_source_registry",
        evidence_id="loan_analysis_sources_v1",
        evidence_hash=evidence_hash,
        created_by=import_actor,
    )
