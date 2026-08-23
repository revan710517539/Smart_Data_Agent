from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


MEMORY_ASSET_TYPES = frozenset({"analysis_experience", "user_behavior_habit"})
FUSIBLE_MEMORY_TYPES = frozenset({"analysis_experience", "analysis_case", "user_behavior_habit", "behavior_habit"})


@dataclass(frozen=True)
class MemoryIdentity:
    topic: str
    action: str
    merge_key: str


@dataclass(frozen=True)
class AssetFusion:
    item: dict[str, Any]
    duplicate_ids: tuple[str, ...]
    matched: bool


_ACTION_RULES = (
    ("prediction", ("预测", "预估", "推演", "趋势外推")),
    ("attribution", ("归因", "原因", "为什么", "为何", "驱动因素")),
    ("ranking", ("排名", "排行", "top", "领先", "落后")),
    ("comparison", ("对比", "比较", "差异", "结构")),
    ("trend", ("趋势", "走势", "变化", "波动", "时序")),
    ("diagnosis", ("异常", "风险", "诊断", "预警")),
    ("reporting", ("周报", "报告", "汇报", "复盘")),
    ("operation", ("动作", "行动", "跟进", "清单", "推进", "运营")),
    ("method", ("方法", "思路", "流程", "路径", "步骤")),
    ("descriptive", ("描述性", "总体", "极值")),
)

_TITLE_PREFIXES = (
    "分析案例",
    "分析方法记忆",
    "操作习惯",
)

_TOPIC_NOISE = (
    "请帮我",
    "帮我",
    "请给我",
    "给我一下",
    "给我",
    "请",
    "一下",
    "做一下",
    "看一下",
    "分析一下",
    "分析",
    "展示",
    "说明",
    "生成",
    "图表",
    "图",
    "方法",
    "思路",
    "流程",
    "路径",
    "趋势",
    "走势",
    "变化",
    "对比",
    "比较",
    "排名",
    "归因",
    "原因",
    "预测",
)


def memory_identity(memory_type: str, payload: dict[str, Any], *, title: str = "") -> MemoryIdentity:
    """Return a conservative tenant-local topic/action identity.

    Explicit producer fields win.  Legacy records fall back to a normalized
    business subject plus an action class.  The fallback intentionally keeps
    ambiguous short prompts separate instead of attempting an unsafe semantic
    merge.
    """

    normalized_type = _canonical_type(memory_type)
    display_title = str(title or payload.get("title") or payload.get("name") or payload.get("subject") or "").strip()
    clean_title = _strip_title_prefix(display_title)
    explicit_topic = _first_text(
        payload,
        "memoryTopic",
        "memory_topic",
        "topic",
        "relatedTopic",
        "related_topic",
    )
    explicit_action = _first_text(payload, "memoryAction", "memory_action", "action")
    habit_type = _normalize_text(payload.get("habitType") or payload.get("habit_type"))

    if explicit_action:
        action = _normalize_text(explicit_action)
    else:
        action = _classify_action(" ".join((clean_title, str(payload.get("behaviorDetail") or ""))))
    if normalized_type == "behavior_habit" and habit_type:
        action = f"{habit_type}:{action}"

    if explicit_topic:
        topic = _normalize_text(explicit_topic)
    elif normalized_type == "behavior_habit" and payload.get("target_type"):
        topic = _normalize_text(payload.get("target_type"))
    else:
        topic = _topic_from_title(clean_title)
    if not topic:
        # Ambiguous prompts such as "分析一下" only merge with the same
        # normalized prompt.  This prevents a generic action from collapsing
        # unrelated business questions.
        topic = f"title:{_normalize_text(clean_title or display_title) or 'untitled'}"

    scope = f"{normalized_type}|{habit_type}|{topic}|{action}"
    merge_key = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    return MemoryIdentity(topic=topic[:240], action=action[:120], merge_key=merge_key)


def prepare_asset_fusion(
    item_type: str,
    incoming: dict[str, Any],
    existing_items: Iterable[dict[str, Any]],
    *,
    consolidate_existing: bool = False,
) -> AssetFusion:
    if item_type not in MEMORY_ASSET_TYPES:
        return AssetFusion(dict(incoming), (), False)
    incoming_copy = dict(incoming)
    incoming_identity = memory_identity(item_type, incoming_copy)
    matches = [
        dict(item)
        for item in existing_items
        if isinstance(item, dict)
        and memory_identity(item_type, item).merge_key == incoming_identity.merge_key
    ]
    if not matches:
        return AssetFusion(
            fuse_payloads(item_type, [incoming_copy], canonical_id=str(incoming_copy.get("id") or "")),
            (),
            False,
        )

    all_versions = [*matches] if consolidate_existing else [*matches, incoming_copy]
    latest_existing = max(matches, key=_memory_recency)
    incoming_id = str(incoming_copy.get("id") or "").strip()
    explicit_existing_update = bool(incoming_id) and any(str(item.get("id") or "") == incoming_id for item in matches)
    canonical_id = incoming_id if explicit_existing_update else str(latest_existing.get("id") or incoming_id)
    fused = fuse_payloads(item_type, all_versions, canonical_id=canonical_id)
    duplicate_ids = tuple(
        sorted(
            {
                str(item.get("id") or "")
                for item in matches
                if str(item.get("id") or "") and str(item.get("id") or "") != canonical_id
            }
        )
    )
    return AssetFusion(fused, duplicate_ids, True)


def fuse_payloads(memory_type: str, records: Iterable[dict[str, Any]], *, canonical_id: str = "") -> dict[str, Any]:
    values = [dict(record) for record in records if isinstance(record, dict)]
    if not values:
        return {}
    values.sort(key=_memory_recency)
    latest = dict(values[-1])
    identity = memory_identity(memory_type, latest)

    # Latest version owns mutable analytical content.  Older versions only
    # fill fields that the latest omitted; stale conclusions are never joined
    # onto a newer result.
    for older in reversed(values[:-1]):
        for field in (
            "description",
            "steps",
            "analysisSteps",
            "rules",
            "riskTips",
            "summaryTemplate",
            "behaviorDetail",
            "relatedIntent",
            "scenario",
            "habitType",
        ):
            if latest.get(field) in (None, "", []):
                latest[field] = older.get(field)

    if canonical_id:
        latest["id"] = canonical_id
    latest = _annotate(latest, identity)
    latest["occurrenceCount"] = sum(_occurrence_count(item) for item in values)
    latest["frequency"] = sum(max(1, _as_int(item.get("frequency"), 1)) for item in values)
    latest["firstSeenAt"] = _earliest_text(values, "firstSeenAt", "first_seen_at", "updatedAt", "updated_at")
    latest["lastSeenAt"] = _latest_text(values, "lastSeenAt", "last_seen_at", "updatedAt", "updated_at")
    latest["sourceVersionIds"] = _unique_text_values(values, "sourceVersionIds", "sourceVersionId", "source_version_id")
    latest["evidenceHistory"] = _unique_text_values(values, "evidenceHistory", "evidence", limit=40)
    latest["mergedFromIds"] = _merged_ids(values, canonical_id)
    latest["relatedMetrics"] = _merge_csv_values(values, "relatedMetrics", "related_metrics", "metrics")
    if latest.get("metrics") in (None, "") and latest.get("relatedMetrics"):
        latest["metrics"] = latest["relatedMetrics"]
    latest["weight"] = max((_as_float(item.get("weight"), 0) for item in values), default=0)
    latest["confidence"] = max((_as_float(item.get("confidence"), 0) for item in values), default=0)
    return latest


def fuse_record_content(
    memory_type: str,
    title: str,
    contents: Iterable[dict[str, Any]],
    *,
    memory_ids: Iterable[str] = (),
) -> dict[str, Any]:
    values = [dict(content) for content in contents if isinstance(content, dict)]
    latest = dict(values[-1]) if values else {}
    identity = memory_identity(memory_type, latest, title=title)
    latest["memoryTopic"] = identity.topic
    latest["memoryAction"] = identity.action
    latest["memoryMergeKey"] = identity.merge_key
    latest["occurrenceCount"] = sum(_occurrence_count(item) for item in values) or 1
    if any("observation_count" in item for item in values):
        latest["observation_count"] = sum(max(0, _as_int(item.get("observation_count"), 0)) for item in values)
    merged = [str(value).strip() for value in memory_ids if str(value).strip()]
    for item in values:
        for value in item.get("mergedFromMemoryIds") or ():
            if str(value).strip():
                merged.append(str(value).strip())
    latest["mergedFromMemoryIds"] = list(dict.fromkeys(merged))[-100:]
    return latest


def _annotate(payload: dict[str, Any], identity: MemoryIdentity) -> dict[str, Any]:
    return {
        **payload,
        "memoryTopic": identity.topic,
        "memoryAction": identity.action,
        "memoryMergeKey": identity.merge_key,
    }


def _canonical_type(memory_type: str) -> str:
    return {
        "analysis_experience": "analysis_case",
        "user_behavior_habit": "behavior_habit",
    }.get(str(memory_type or "").strip(), str(memory_type or "other").strip())


def _strip_title_prefix(value: str) -> str:
    result = str(value or "").strip()
    for prefix in _TITLE_PREFIXES:
        result = re.sub(rf"^{re.escape(prefix)}\s*[：:]?\s*", "", result, flags=re.IGNORECASE)
    return result.strip()


def _classify_action(value: str) -> str:
    normalized = _normalize_text(value)
    for action, terms in _ACTION_RULES:
        if any(_normalize_text(term) in normalized for term in terms):
            return action
    return "analysis"


def _topic_from_title(value: str) -> str:
    topic = str(value or "")
    for noise in _TOPIC_NOISE:
        topic = re.sub(re.escape(noise), "", topic, flags=re.IGNORECASE)
    normalized = _normalize_text(topic).strip("的")
    return normalized if len(normalized) >= 2 else ""


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _occurrence_count(payload: dict[str, Any]) -> int:
    return max(1, _as_int(payload.get("occurrenceCount"), 1))


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _memory_recency(payload: dict[str, Any]) -> tuple[float, int, str]:
    for key in ("updatedAt", "updated_at", "lastSeenAt", "last_seen_at", "publishedAt", "reviewedAt", "createdAt", "created_at"):
        parsed = _parse_datetime(payload.get(key))
        if parsed is not None:
            return parsed.timestamp(), _as_int(payload.get("assetVersion"), 0), str(payload.get("id") or "")
    return 0.0, _as_int(payload.get("assetVersion"), 0), str(payload.get("id") or "")


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _earliest_text(values: list[dict[str, Any]], *keys: str) -> str:
    candidates: list[tuple[datetime, str]] = []
    for item in values:
        for key in keys:
            text = str(item.get(key) or "").strip()
            parsed = _parse_datetime(text)
            if parsed is not None:
                candidates.append((parsed, text))
                break
    return min(candidates, default=(datetime.now(timezone.utc), ""), key=lambda pair: pair[0])[1]


def _latest_text(values: list[dict[str, Any]], *keys: str) -> str:
    candidates: list[tuple[datetime, str]] = []
    for item in values:
        for key in keys:
            text = str(item.get(key) or "").strip()
            parsed = _parse_datetime(text)
            if parsed is not None:
                candidates.append((parsed, text))
                break
    return max(candidates, default=(datetime.fromtimestamp(0, timezone.utc), ""), key=lambda pair: pair[0])[1]


def _unique_text_values(values: list[dict[str, Any]], *keys: str, limit: int = 100) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        for key in keys:
            raw = item.get(key)
            candidates = raw if isinstance(raw, list) else re.split(r"[,\n]+", str(raw or ""))
            for candidate in candidates:
                text = str(candidate or "").strip()
                marker = _normalize_text(text)
                if text and marker and marker not in seen:
                    seen.add(marker)
                    result.append(text)
                    if len(result) >= limit:
                        return result
    return result


def _merged_ids(values: list[dict[str, Any]], canonical_id: str) -> list[str]:
    result: list[str] = []
    for item in values:
        candidates = [item.get("id"), *(item.get("mergedFromIds") or [])]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text and text != canonical_id and text not in result:
                result.append(text)
    return result[-100:]


def _merge_csv_values(values: list[dict[str, Any]], *keys: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for item in values:
        for key in keys:
            raw = item.get(key)
            candidates = raw if isinstance(raw, list) else re.split(r"[,，、\n]+", str(raw or ""))
            for candidate in candidates:
                text = str(candidate or "").strip()
                marker = _normalize_text(text)
                if text and marker and marker not in seen:
                    seen.add(marker)
                    parts.append(text)
    return ", ".join(parts)[:2000]


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
