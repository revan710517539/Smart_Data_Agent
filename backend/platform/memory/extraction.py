from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.platform.settings import call_model_text_completion, require_model_for_application


MEMORY_OUTPUT_TYPES = (
    "analysis_experience",
    "intent",
    "analysis_habit",
    "operation_habit",
    "reporting_habit",
)
ALLOWED_MEMORY_OUTPUTS = {*MEMORY_OUTPUT_TYPES, "user_behavior_habit"}
HABIT_OUTPUT_TYPES = {
    "analysis_habit": "分析习惯",
    "operation_habit": "运营习惯",
    "reporting_habit": "汇报习惯",
}
ALLOWED_MEMORY_SCRIPTS = {"memory.rule_based_extraction.v1"}
MEMORY_SOURCE_LIMIT = 50
MEMORY_PROMPT_PAYLOAD_LIMIT = 96_000


def run_memory_extraction(
    services: Any,
    tenant_id: str,
    actor_user_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    mode = str(config.get("execution_mode") or "llm").strip()
    if mode not in {"llm", "script"}:
        raise ValueError("invalid_memory_extraction_mode")
    output_types = [
        item
        for item in _string_list(config.get("output_types"))
        if item in ALLOWED_MEMORY_OUTPUTS
    ] or list(MEMORY_OUTPUT_TYPES)
    sources = _collect_sources(
        services,
        tenant_id,
        _string_list(config.get("source_ids")),
        source_kind=str(config.get("source_kind") or "").strip(),
    )
    if not sources:
        raise ValueError("memory_extraction_source_required")
    if bool(config.get("unextracted_only")):
        extracted_signatures = _extracted_source_signatures(services, tenant_id)
        sources = [source for source in sources if _source_signature(source) not in extracted_signatures]
        if not sources:
            return {
                "status": "no_new_sources",
                "execution_mode": mode,
                "source_ids": [],
                "created_review_assets": {item_type: [] for item_type in output_types},
                "created_count": 0,
                "model_invocation": None,
            }

    if mode == "llm":
        prompt = str(config.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("memory_extraction_prompt_required")
        model = require_model_for_application(
            services.system_config_store,
            tenant_id,
            "memory_extraction",
            user_id=actor_user_id,
        )
        completion = call_model_text_completion(
            model,
            _build_prompt(prompt, sources, output_types),
            max_tokens=3072,
        )
        if completion.get("status") != "connected" or not str(completion.get("response_text") or "").strip():
            raise RuntimeError(str(completion.get("error_code") or "memory_extraction_model_failed"))
        extracted = _parse_model_output(str(completion["response_text"]), sources)
        model_ref = {
            "model_id": completion.get("model_id"),
            "used_model": completion.get("used_model"),
            "request_hash": completion.get("request_hash"),
            "response_hash": completion.get("response_hash"),
        }
    else:
        script_ref = str(config.get("script_ref") or "").strip()
        if script_ref not in ALLOWED_MEMORY_SCRIPTS:
            raise ValueError("memory_extraction_script_not_registered")
        extracted = _rule_based_extract(sources)
        model_ref = None

    created: dict[str, list[str]] = {item_type: [] for item_type in output_types}
    known_items = _existing_memory_fingerprints(services, tenant_id)
    for item_type in output_types:
        for index, raw_item in enumerate(extracted.get(item_type, [])[:5]):
            item = _normalize_item(item_type, raw_item, sources, index)
            fingerprint = _memory_fingerprint(item_type, item)
            if fingerprint in known_items:
                continue
            known_items.add(fingerprint)
            storage_type = "user_behavior_habit" if item_type in HABIT_OUTPUT_TYPES else item_type
            saved = services.data_asset_store.upsert_item(
                tenant_id,
                storage_type,
                item,
                updated_by=actor_user_id,
                lifecycle_status="review",
            )
            created[item_type].append(str(saved.get("id") or item["id"]))
    return {
        "status": "succeeded",
        "execution_mode": mode,
        "source_ids": [source["id"] for source in sources],
        "created_review_assets": created,
        "created_count": sum(len(ids) for ids in created.values()),
        "model_invocation": model_ref,
    }


def _collect_sources(
    services: Any,
    tenant_id: str,
    requested_ids: list[str],
    *,
    source_kind: str = "",
) -> list[dict[str, str]]:
    bundle = services.data_asset_store.list_published_bundle(tenant_id)
    files = [item for item in bundle.get("knowledge_files", []) if isinstance(item, dict)]
    raw_tables = [] if source_kind == "knowledge_file" else [item for item in bundle.get("raw_tables", []) if isinstance(item, dict)]
    topic_tables = [] if source_kind == "knowledge_file" else [item for item in bundle.get("topic_tables", []) if isinstance(item, dict)]
    if requested_ids:
        requested = set(requested_ids)
        files = [item for item in files if str(item.get("id") or "") in requested]
        raw_tables = [item for item in raw_tables if str(item.get("id") or "") in requested]
        topic_tables = [item for item in topic_tables if str(item.get("id") or "") in requested]
    documents = services.knowledge_service.list_documents(tenant_id)
    sources: list[dict[str, str]] = []
    for item in files:
        source_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or source_id).strip()
        matching_document = next(
            (
                document
                for document in documents
                if str(document.get("document_id") or "") == source_id
                or str(document.get("title") or "").strip() == title
            ),
            None,
        )
        content = ""
        try:
            hits = services.knowledge_service.search(tenant_id, title, limit=1)
            content = str((hits[0] if hits else {}).get("content") or "")[:6000]
        except Exception:
            content = ""
        sources.append(
            {
                "id": source_id,
                "source_type": "knowledge_file",
                "title": title,
                "tags": str(item.get("tags") or "")[:1000],
                "owner": str(item.get("owner") or "")[:240],
                "version": str(item.get("assetVersion") or item.get("updated") or "")[:160],
                "document_id": str((matching_document or {}).get("document_id") or "")[:160],
                "content": content,
            }
        )
    for item in raw_tables:
        source_id = str(item.get("id") or "").strip()
        title = str(item.get("tableNameCn") or item.get("tableNameEn") or source_id).strip()
        fields = item.get("fields") if isinstance(item.get("fields"), list) else []
        sources.append(
            {
                "id": source_id,
                "source_type": "raw_table",
                "title": title,
                "tags": str(item.get("source") or "")[:1000],
                "owner": "数据资产",
                "version": str(item.get("assetVersion") or item.get("updatedAt") or "")[:160],
                "document_id": "",
                "content": json.dumps(
                    {
                        "table_name": item.get("tableNameEn"),
                        "description": item.get("description"),
                        "update_frequency": item.get("updateFrequency"),
                        "restrictions": item.get("restrictions"),
                        "fields": fields[:200],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )[:12_000],
            }
        )
    for item in topic_tables:
        source_id = str(item.get("id") or "").strip()
        title = str(item.get("name") or item.get("code") or source_id).strip()
        fields = item.get("fields") if isinstance(item.get("fields"), list) else []
        sources.append(
            {
                "id": source_id,
                "source_type": "topic_table",
                "title": title,
                "tags": str(item.get("applicableScene") or item.get("source") or "")[:1000],
                "owner": "数据资产",
                "version": str(item.get("assetVersion") or item.get("updatedAt") or "")[:160],
                "document_id": "",
                "content": json.dumps(
                    {
                        "topic_code": item.get("code"),
                        "description": item.get("description"),
                        "analysis_angles": item.get("analysisAngles"),
                        "chart_types": item.get("chartTypes"),
                        "fields": fields[:200],
                        "readonly_sql": str(item.get("sql") or "")[:12_000],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )[:18_000],
            }
        )
    return sources[:MEMORY_SOURCE_LIMIT]


def _build_prompt(instruction: str, sources: list[dict[str, str]], output_types: list[str]) -> str:
    payload = [
        {key: value for key, value in source.items() if key != "content" or value}
        for source in sources
    ]
    serialized_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized_payload) > MEMORY_PROMPT_PAYLOAD_LIMIT:
        raise ValueError("memory_extraction_input_too_large")
    return (
        "你是企业数据分析记忆提炼器。知识文件只能作为本次提炼输入，不能作为 Skill 记忆直接引用。\n"
        f"用户提炼要求：{instruction}\n"
        f"只输出以下目录：{json.dumps(output_types, ensure_ascii=False)}。\n"
        "返回严格 JSON 对象，键只能来自 analysis_experience、intent、analysis_habit、operation_habit、reporting_habit、user_behavior_habit；"
        "每个值都是对象数组。意图包含 scenario/purpose/description/keywords；分析经验包含 title/description/steps/evidence；"
        "三类习惯分别表示分析习惯、运营习惯、汇报习惯，包含 title/description/behaviorDetail/evidence。"
        "每类最多 5 条；没有足够本质、可复用且有证据的内容时返回空数组。"
        "只保留会改变后续判断、分析方法或运营动作的结论，删除背景复述、常识、套话、表层摘要和同义重复。"
        "标题和描述必须精炼，证据必须能回指输入来源。不要使用 Markdown 代码块，不要复述原文。\n"
        f"输入集合（知识文件）：{serialized_payload}"
    )


def _parse_model_output(response_text: str, sources: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    text = response_text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("memory_extraction_model_output_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("memory_extraction_model_output_must_be_object")
    return {
        item_type: [item for item in payload.get(item_type, []) if isinstance(item, dict)]
        if isinstance(payload.get(item_type), list)
        else []
        for item_type in ALLOWED_MEMORY_OUTPUTS
    }


def _rule_based_extract(sources: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    intents: list[dict[str, Any]] = []
    experiences: list[dict[str, Any]] = []
    analysis_habits: list[dict[str, Any]] = []
    operation_habits: list[dict[str, Any]] = []
    reporting_habits: list[dict[str, Any]] = []
    for source in sources:
        title = source["title"]
        tags = source["tags"] or title
        source_label = "知识文件" if source.get("source_type") == "knowledge_file" else "数据资产"
        evidence = f"来源{source_label}：{title}（{source['id']}）"
        intents.append(
            {
                "scenario": "知识文件提炼",
                "purpose": f"应用{title}",
                "description": f"在相关分析中识别并应用《{title}》沉淀的业务口径和关注点。",
                "keywords": tags,
                "examples": f"基于{title}开展分析",
            }
        )
        experiences.append(
            {
                "title": f"{title}分析经验",
                "steps": "先识别分析对象和时间范围，再核对指标口径，最后形成数据证据、业务解释和后续动作。",
                "description": evidence,
                "evidence": evidence,
            }
        )
        analysis_habits.append(
            {
                "title": f"{title}分析习惯",
                "habitType": "分析习惯",
                "description": f"分析相关主题时优先核对《{title}》中记录的口径、边界和例外条件。",
                "evidence": evidence,
            }
        )
        operation_habits.append(
            {
                "title": f"{title}运营习惯",
                "habitType": "运营习惯",
                "description": f"将《{title}》中可执行的边界、频率和异常条件落实到运营动作。",
                "evidence": evidence,
            }
        )
        reporting_habits.append(
            {
                "title": f"{title}汇报习惯",
                "habitType": "汇报习惯",
                "description": f"汇报《{title}》相关主题时只保留关键结论、证据和下一步动作。",
                "evidence": evidence,
            }
        )
    return {
        "intent": intents,
        "analysis_experience": experiences,
        "analysis_habit": analysis_habits,
        "operation_habit": operation_habits,
        "reporting_habit": reporting_habits,
        "user_behavior_habit": analysis_habits,
    }


def _normalize_item(
    item_type: str,
    raw_item: dict[str, Any],
    sources: list[dict[str, str]],
    index: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    source_ids = [source["id"] for source in sources]
    source_ref = ",".join(
        f"{source.get('source_type') or 'source'}:{source['id']}:v{source.get('version') or 'current'}"
        for source in sources
    )
    identity = json.dumps([item_type, source_ids, index, raw_item], ensure_ascii=False, sort_keys=True)
    item_id = f"mem_{item_type}_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:18]}"
    if item_type == "intent":
        return {
            "id": item_id,
            "scenario": str(raw_item.get("scenario") or "知识文件提炼")[:120],
            "purpose": str(raw_item.get("purpose") or "业务分析")[:160],
            "description": str(raw_item.get("description") or "从知识文件中提炼的分析意图。")[:2000],
            "keywords": str(raw_item.get("keywords") or "知识文件,分析")[:1200],
            "relatedTopic": str(raw_item.get("relatedTopic") or "")[:240],
            "relatedMetrics": str(raw_item.get("relatedMetrics") or "")[:1000],
            "relatedExperience": str(raw_item.get("relatedExperience") or "")[:240],
            "pageScope": str(raw_item.get("pageScope") or "智能分析,经营周报")[:500],
            "enabled": True,
            "examples": str(raw_item.get("examples") or "")[:1200],
            "sourceVersionId": source_ref,
            "updatedAt": now,
        }
    if item_type == "analysis_experience":
        title = str(raw_item.get("title") or raw_item.get("name") or "知识文件分析经验")[:200]
        return {
            "id": item_id,
            "title": title,
            "name": title,
            "description": str(raw_item.get("description") or "从知识文件中提炼的分析经验。")[:2000],
            "steps": str(raw_item.get("steps") or raw_item.get("analysisSteps") or "识别对象；核对口径；分析证据；形成建议。")[:3000],
            "analysisSteps": str(raw_item.get("steps") or raw_item.get("analysisSteps") or "")[:3000],
            "relatedTopic": str(raw_item.get("relatedTopic") or "")[:240],
            "relatedIntent": str(raw_item.get("relatedIntent") or "")[:500],
            "metrics": str(raw_item.get("metrics") or raw_item.get("relatedMetrics") or "")[:1000],
            "rules": str(raw_item.get("rules") or "")[:2000],
            "commonConclusions": str(raw_item.get("commonConclusions") or "")[:2000],
            "riskTips": str(raw_item.get("riskTips") or "")[:1600],
            "summaryTemplate": str(raw_item.get("summaryTemplate") or "")[:1600],
            "institutionScope": str(raw_item.get("institutionScope") or "全部机构")[:300],
            "sourceVersionId": source_ref,
            "evidence": str(raw_item.get("evidence") or f"来源知识文件：{source_ref}")[:2000],
            "enabled": True,
            "status": "当前有效",
            "updatedAt": now,
        }
    habit_type = HABIT_OUTPUT_TYPES.get(item_type) or str(raw_item.get("habitType") or "分析习惯")
    if habit_type not in {"分析习惯", "运营习惯", "汇报习惯"}:
        habit_type = "分析习惯"
    return {
        "id": item_id,
        "title": str(raw_item.get("title") or "知识文件行为习惯")[:200],
        "habitType": habit_type,
        "description": str(raw_item.get("description") or "从知识文件中提炼的行为习惯。")[:2000],
        "behaviorDetail": str(raw_item.get("behaviorDetail") or raw_item.get("description") or "")[:2400],
        "sourceVersionId": source_ref,
        "evidence": str(raw_item.get("evidence") or f"来源知识文件：{source_ref}")[:2000],
        "relatedMetrics": str(raw_item.get("relatedMetrics") or "")[:1000],
        "relatedOrgs": str(raw_item.get("relatedOrgs") or "")[:1000],
        "firstSeenAt": now,
        "lastSeenAt": now,
        "frequency": max(1, int(raw_item.get("frequency") or 1)),
        "weight": float(raw_item.get("weight") or 0.5),
        "status": "当前有效",
        "confidence": float(raw_item.get("confidence") or 0.6),
        "updatedAt": now,
    }


def _source_signature(source: dict[str, str]) -> str:
    return f"{source.get('source_type') or 'source'}:{source['id']}:v{source.get('version') or 'current'}"


def _extracted_source_signatures(services: Any, tenant_id: str) -> set[str]:
    bundle = services.data_asset_store.list_bundle(tenant_id)
    signatures: set[str] = set()
    for collection in ("intents", "analysis_experiences", "behavior_habits"):
        for item in bundle.get(collection, []):
            if not isinstance(item, dict):
                continue
            for signature in str(item.get("sourceVersionId") or "").split(","):
                normalized = signature.strip()
                if normalized:
                    signatures.add(normalized)
    return signatures


def _existing_memory_fingerprints(services: Any, tenant_id: str) -> set[str]:
    bundle = services.data_asset_store.list_bundle(tenant_id)
    fingerprints: set[str] = set()
    for item_type, collection in (
        ("intent", "intents"),
        ("analysis_experience", "analysis_experiences"),
        ("user_behavior_habit", "behavior_habits"),
    ):
        for item in bundle.get(collection, []):
            if isinstance(item, dict):
                fingerprints.add(_memory_fingerprint(item_type, item))
    return fingerprints


def _memory_fingerprint(item_type: str, item: dict[str, Any]) -> str:
    storage_type = "user_behavior_habit" if item_type in HABIT_OUTPUT_TYPES else item_type
    title = item.get("title") or item.get("name") or item.get("purpose") or ""
    description = item.get("description") or item.get("steps") or item.get("behaviorDetail") or ""
    habit_type = item.get("habitType") if storage_type == "user_behavior_habit" else ""
    normalized = "|".join(
        re.sub(r"\s+", "", str(value or "")).casefold()
        for value in (storage_type, habit_type, title, description)
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
