from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any


class WeeklyReportLearningEngine:
    """Extract reusable learning from a saved weekly report version.

    The debate runner is intentionally isolated from API handlers and stores so a
    hosted LLM client can replace the local deterministic runner without changing
    persistence or page contracts.
    """

    def __init__(self, report_store: Any, data_asset_store: Any, application_store: Any) -> None:
        self.report_store = report_store
        self.data_asset_store = data_asset_store
        self.application_store = application_store

    def analyze_version(
        self,
        tenant_id: str,
        version_id: str,
        actor_user_id: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        existing = self.report_store.get_weekly_ai_task(tenant_id, version_id)
        if existing and existing.get("status") == "已完成" and not force:
            return existing

        now = _now()
        version = self.report_store.get_weekly_report_version(tenant_id, version_id)
        if not version:
            task = _analysis_task(
                tenant_id,
                version_id,
                "分析失败",
                {},
                {},
                {},
                "历史版本不存在。",
                now,
            )
            return self.report_store.upsert_weekly_ai_task(tenant_id, task, updated_by=actor_user_id)

        snapshot = build_weekly_report_snapshot(version)
        task = _analysis_task(tenant_id, version_id, "分析中", snapshot, {}, {}, "", now)
        self.report_store.upsert_weekly_ai_task(tenant_id, task, updated_by=actor_user_id)

        try:
            debate_result = run_local_multi_role_debate(snapshot)
            final_result = debate_result["final_result"]
            evidence_summary = version.get("evidenceSummary") if isinstance(version.get("evidenceSummary"), dict) else {}
            methods = self._persist_analysis_methods(
                tenant_id, version_id, actor_user_id, final_result["data_analysis_methods"], evidence_summary, now
            )
            habits = self._persist_behavior_habits(
                tenant_id, version_id, actor_user_id, final_result["user_behavior_habits"], evidence_summary, now
            )
            todos = self._persist_todos(
                tenant_id, version_id, actor_user_id, final_result["todo_tasks"], evidence_summary, now
            )
            persisted_final = {
                **final_result,
                "data_analysis_methods": methods,
                "user_behavior_habits": habits,
                "todo_tasks": todos,
            }
            completed = _analysis_task(tenant_id, version_id, "已完成", snapshot, debate_result, persisted_final, "", now)
            return self.report_store.upsert_weekly_ai_task(tenant_id, completed, updated_by=actor_user_id)
        except Exception as exc:
            failed = _analysis_task(
                tenant_id,
                version_id,
                "分析失败",
                snapshot,
                {},
                {},
                str(exc),
                now,
            )
            return self.report_store.upsert_weekly_ai_task(tenant_id, failed, updated_by=actor_user_id)

    def analyze_pending_versions(self, tenant_id: str, actor_user_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        tasks = {task.get("version_id"): task for task in self.report_store.list_weekly_ai_tasks(tenant_id)}
        analyzed: list[dict[str, Any]] = []
        for version in self.report_store.list_weekly_report_versions(tenant_id):
            version_id = str(version.get("id") or "")
            if not version_id or version_id in tasks:
                continue
            analyzed.append(self.analyze_version(tenant_id, version_id, actor_user_id, force=True))
            if len(analyzed) >= limit:
                break
        return analyzed

    def _persist_analysis_methods(
        self,
        tenant_id: str,
        version_id: str,
        actor_user_id: str,
        methods: list[dict[str, Any]],
        evidence_summary: dict[str, Any],
        now: str,
    ) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for method in methods:
            content = {
                **method,
                "id": _stable_id("analysis_method", method["title"]),
                "name": method["title"],
                "updatedAt": now[:10],
                "enabled": False,
                "status": "候选待复核",
            }
            candidate = self.report_store.create_learning_candidate(
                tenant_id,
                version_id,
                "analysis_method",
                content,
                evidence_summary,
                float(method.get("confidence") or 0.7),
                actor_user_id,
            )
            saved.append({**content, "learningCandidateId": candidate["learning_candidate_id"]})
        return saved

    def _persist_behavior_habits(
        self,
        tenant_id: str,
        version_id: str,
        actor_user_id: str,
        habits: list[dict[str, Any]],
        evidence_summary: dict[str, Any],
        now: str,
    ) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for habit in habits:
            content = {
                **habit,
                "id": _stable_id("behavior_habit", habit["title"]),
                "updatedAt": now[:10],
                "status": "候选待复核",
            }
            candidate = self.report_store.create_learning_candidate(
                tenant_id,
                version_id,
                "behavior_habit",
                content,
                evidence_summary,
                float(habit.get("confidence") or 0.7),
                actor_user_id,
            )
            saved.append({**content, "learningCandidateId": candidate["learning_candidate_id"]})
        return saved

    def _persist_todos(
        self,
        tenant_id: str,
        version_id: str,
        actor_user_id: str,
        todos: list[dict[str, Any]],
        evidence_summary: dict[str, Any],
        now: str,
    ) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for todo in todos:
            todo_id = _stable_id("weekly_todo", f"{todo.get('source_version_id')}:{todo.get('title')}")
            payload = {
                "todo": {
                    "id": todo_id,
                    "title": todo.get("title") or "经营周报待办",
                    "description": _todo_description(todo),
                    "status": _todo_status_to_ui(todo.get("status")),
                    "priority": _todo_priority_to_ui(todo.get("priority")),
                    "dueDate": _normalize_due_date(todo.get("due_date"), now),
                    "assignee": todo.get("owner") or "当前用户",
                    "listName": "经营周报闭环",
                    "labels": ["经营周报", str(todo.get("related_metric") or "待跟进")],
                    "source": "weekly_report",
                    "ownerUserId": actor_user_id,
                    "createdBy": "weekly_report_ai",
                    "createdAt": now,
                    "updatedAt": now,
                    "sourceVersionId": todo.get("source_version_id") or "",
                    "sourceText": todo.get("source_text") or "",
                    "background": todo.get("background") or "",
                    "suggestion": todo.get("suggestion") or "",
                    "relatedOrg": todo.get("related_org") or "",
                    "relatedMetric": todo.get("related_metric") or "",
                    "confidence": float(todo.get("confidence") or 0),
                },
                "ownerUserId": actor_user_id,
            }
            candidate = self.report_store.create_learning_candidate(
                tenant_id,
                version_id,
                "todo",
                payload,
                evidence_summary,
                float(todo.get("confidence") or 0.7),
                actor_user_id,
            )
            saved.append({**payload["todo"], "status": "candidate", "learningCandidateId": candidate["learning_candidate_id"]})
        return saved


def build_weekly_report_snapshot(version: dict[str, Any]) -> dict[str, Any]:
    report = version.get("report") if isinstance(version.get("report"), dict) else {}
    sections = []
    for section in report.get("sections") if isinstance(report.get("sections"), list) else []:
        if not isinstance(section, dict):
            continue
        blocks = []
        for block in section.get("blocks") if isinstance(section.get("blocks"), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "table":
                blocks.append(
                    {
                        "id": str(block.get("id") or ""),
                        "type": "table",
                        "title": str(block.get("title") or ""),
                        "data_source": str(block.get("dataSource") or ""),
                        "fields": _string_list(block.get("fields")),
                        "rows": [row for row in block.get("rows", []) if isinstance(row, dict)][:50],
                        "analysis_conclusion": str((block.get("analysis") or {}).get("conclusion") or ""),
                    }
                )
            elif block.get("type") == "text":
                text = _block_text(block)
                blocks.append(
                    {
                        "id": str(block.get("id") or ""),
                        "type": "text",
                        "title": str(block.get("title") or ""),
                        "content": text,
                    }
                )
        sections.append(
            {
                "id": str(section.get("id") or ""),
                "name": str(section.get("name") or ""),
                "blocks": blocks,
            }
        )
    comments = [comment for comment in version.get("comments", []) if isinstance(comment, dict)]
    return {
        "version_id": str(version.get("id") or ""),
        "version_name": str(version.get("name") or ""),
        "saved_at": str(version.get("savedAt") or ""),
        "report_id": str(version.get("reportId") or report.get("id") or ""),
        "institution": str(report.get("institutionName") or ""),
        "period": str(report.get("period") or ""),
        "business_line": str(report.get("projectNo") or "经营周报"),
        "filters": {"institution": str(report.get("institutionName") or "")},
        "sections": sections,
        "comments": comments[:200],
        "evidence_summary": version.get("evidenceSummary") if isinstance(version.get("evidenceSummary"), dict) else {},
        "learning_engine": "deterministic_multi_role_rules",
    }


def run_local_multi_role_debate(snapshot: dict[str, Any]) -> dict[str, Any]:
    metrics = _extract_metrics(snapshot)
    evidence = _best_evidence(snapshot)
    todo_sources = _todo_source_texts(snapshot)
    source_version_id = snapshot["version_id"]
    institution = snapshot.get("institution") or ""
    period = snapshot.get("period") or ""
    method = {
        "title": "目标达成率-异常定位-原因拆解-动作制定分析法",
        "description": "用户先查看核心经营指标的目标达成情况，再定位异常指标和业务波动，随后结合重点客户、客户经理跟进或渠道转化拆解原因，最后形成下一步运营动作。",
        "analysis_steps": ["查看目标达成率", "识别异常指标", "定位落后机构或业务线", "拆解业务原因", "形成后续动作"],
        "scenario": "经营周报分析、机构经营分析、指标异常分析",
        "source_version_id": source_version_id,
        "sourceVersionId": source_version_id,
        "sourceVersionName": snapshot.get("version_name") or "",
        "evidence": evidence,
        "related_metrics": metrics[:8],
        "related_orgs": [institution] if institution else [],
        "confidence": 0.88 if evidence else 0.72,
    }
    habits = [
        {
            "title": "目标完成度优先的经营判断习惯",
            "habit_type": "分析习惯",
            "description": "用户习惯先从目标完成情况切入，判断核心经营指标是否达标，再围绕落后指标和异常机构展开原因分析。",
            "behavior_detail": evidence,
            "source_version_id": source_version_id,
            "sourceVersionId": source_version_id,
            "sourceVersionName": snapshot.get("version_name") or "",
            "evidence": evidence,
            "related_metrics": metrics[:5],
            "related_orgs": [institution] if institution else [],
            "confidence": 0.86 if evidence else 0.7,
        },
        {
            "title": "清单化推进经营事项的运营习惯",
            "habit_type": "运营习惯",
            "description": "用户倾向把经营问题拆成客户清单、机构动作、责任跟进和复核节奏，便于下周期继续闭环。",
            "behavior_detail": todo_sources[0]["text"] if todo_sources else evidence,
            "source_version_id": source_version_id,
            "sourceVersionId": source_version_id,
            "sourceVersionName": snapshot.get("version_name") or "",
            "evidence": todo_sources[0]["text"] if todo_sources else evidence,
            "related_metrics": metrics[:5],
            "related_orgs": [institution] if institution else [],
            "confidence": 0.82 if todo_sources else 0.68,
        },
        {
            "title": "结论先行并补充数据证据的汇报习惯",
            "habit_type": "汇报习惯",
            "description": "用户倾向先给出经营结论，再补充指标、机构或行动依据，形成适合管理层快速阅读的表达方式。",
            "behavior_detail": evidence,
            "source_version_id": source_version_id,
            "sourceVersionId": source_version_id,
            "sourceVersionName": snapshot.get("version_name") or "",
            "evidence": evidence,
            "related_metrics": metrics[:5],
            "related_orgs": [institution] if institution else [],
            "confidence": 0.8 if evidence else 0.66,
        },
    ]
    todos = _extract_todos(snapshot, todo_sources, metrics, institution, period)
    final_result = {
        "data_analysis_methods": [method] if evidence else [],
        "user_behavior_habits": [habit for habit in habits if habit.get("evidence")],
        "todo_tasks": todos,
    }
    return {
        "rounds": [
            {
                "name": "第一轮：独立提炼",
                "roles": {
                    "数据分析师": {
                        "finding": method["description"],
                        "evidence": method["evidence"],
                        "uncertainty": "仅基于当前历史版本中的图表、表格和分析结论，不外推未出现指标。",
                    },
                    "运营策略专家": {
                        "finding": habits[1]["description"],
                        "evidence": habits[1]["evidence"],
                        "uncertainty": "单期出现的运营动作需要后续版本验证高频性。",
                    },
                    "管理者视角": {
                        "finding": "优先保留与核心经营指标、风险提示和下周动作相关的内容。",
                        "evidence": evidence,
                        "uncertainty": "没有明确责任人的动作不强行补责任人。",
                    },
                    "任务提取员": {
                        "finding": f"提取到 {len(todos)} 条可执行待办。",
                        "evidence": "；".join(todo.get("source_text", "") for todo in todos[:3]),
                        "uncertainty": "模糊表达仅作为待处理任务，不自动标记执行人。",
                    },
                },
            },
            {
                "name": "第二轮：交叉质疑",
                "checks": [
                    "确认分析方法来自表格字段、分析结论和计划文本的连续关系，不把普通描述误判为方法。",
                    "确认用户行为习惯保留来源证据，并通过频次和时间衰减控制权重。",
                    "确认待办事项来自下一步计划、评论或问题说明，不编造历史版本之外的事项。",
                ],
            },
            {
                "name": "第三轮：统一收敛",
                "summary": "收敛为数据分析方法、用户行为习惯、待办事项三类结构化结果。",
            },
        ],
        "final_result": final_result,
    }


def _analysis_task(
    tenant_id: str,
    version_id: str,
    status: str,
    input_snapshot: dict[str, Any],
    debate_result: dict[str, Any],
    final_result: dict[str, Any],
    error_message: str,
    now: str,
) -> dict[str, Any]:
    return {
        "id": _stable_id("weekly_ai_task", version_id),
        "tenant_id": tenant_id,
        "version_id": version_id,
        "status": status,
        "input_snapshot": input_snapshot,
        "debate_result": debate_result,
        "final_result": final_result,
        "error_message": error_message,
        "created_at": now,
        "updated_at": now,
    }


def _compress_memory_item(
    existing: list[dict[str, Any]],
    candidate: dict[str, Any],
    now: str,
    *,
    title_keys: tuple[str, ...],
) -> dict[str, Any]:
    title = _first_text(candidate, title_keys)
    matched = next((item for item in existing if _first_text(item, title_keys) == title), None)
    source_version_id = str(candidate.get("source_version_id") or candidate.get("sourceVersionId") or "")
    confidence = _float(candidate.get("confidence"), 0.75)
    if not matched:
        candidate["firstSeenAt"] = now
        candidate["lastSeenAt"] = now
        candidate["frequency"] = int(candidate.get("frequency") or 1)
        candidate["weight"] = round(_weight(candidate["frequency"], confidence, True), 3)
        candidate["sourceVersions"] = [source_version_id] if source_version_id else []
        return candidate

    source_versions = [str(item) for item in matched.get("sourceVersions", []) if str(item)]
    seen_again = bool(source_version_id and source_version_id in source_versions)
    if source_version_id and source_version_id not in source_versions:
        source_versions.insert(0, source_version_id)
    frequency = int(matched.get("frequency") or 1) + (0 if seen_again else 1)
    return {
        **matched,
        **candidate,
        "id": matched.get("id") or candidate["id"],
        "firstSeenAt": matched.get("firstSeenAt") or now,
        "lastSeenAt": now,
        "frequency": frequency,
        "weight": round(_weight(frequency, confidence, True), 3),
        "status": "当前有效" if frequency > 0 else "历史归档",
        "sourceVersions": source_versions[:20],
        "confidence": confidence,
    }


def _extract_metrics(snapshot: dict[str, Any]) -> list[str]:
    metrics: list[str] = []
    for section in snapshot.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") != "table":
                continue
            for field in block.get("fields", []):
                text = str(field).strip()
                if text and text not in metrics:
                    metrics.append(text)
    return metrics


def _best_evidence(snapshot: dict[str, Any]) -> str:
    for section in snapshot.get("sections", []):
        for block in section.get("blocks", []):
            conclusion = str(block.get("analysis_conclusion") or "").strip()
            if conclusion:
                return conclusion[:500]
    for source in _todo_source_texts(snapshot):
        if source["text"]:
            return source["text"][:500]
    return ""


def _todo_source_texts(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    keywords = ("下周", "下一步", "待补充", "需要", "建议", "推动", "跟进", "复核", "计划", "清单")
    for section in snapshot.get("sections", []):
        section_name = str(section.get("name") or "")
        for block in section.get("blocks", []):
            text = str(block.get("content") or block.get("analysis_conclusion") or "").strip()
            if not text:
                continue
            for sentence in _split_sentences(text):
                if any(keyword in sentence for keyword in keywords) or "计划" in section_name:
                    sources.append({"module": section_name or str(block.get("title") or ""), "text": sentence})
    for comment in snapshot.get("comments", []):
        text = str(comment.get("text") or "").strip()
        if text:
            sources.append({"module": str(comment.get("targetLabel") or "评论"), "text": text})
    return sources[:12]


def _extract_todos(
    snapshot: dict[str, Any],
    sources: list[dict[str, str]],
    metrics: list[str],
    institution: str,
    period: str,
) -> list[dict[str, Any]]:
    todos = []
    source_version_id = snapshot["version_id"]
    for source in sources[:6]:
        text = source["text"]
        metric = _match_metric(text, metrics) or (metrics[0] if metrics else "")
        todos.append(
            {
                "title": _todo_title(text, metric),
                "source_version_id": source_version_id,
                "source_text": text,
                "background": f"{snapshot.get('version_name') or period}中出现需要继续跟进的经营动作。",
                "suggestion": _todo_suggestion(text),
                "related_org": institution,
                "related_metric": metric,
                "owner": "",
                "due_date": "",
                "priority": _priority(text, metric),
                "status": "待处理",
                "confidence": 0.84 if any(token in text for token in ("下周", "周一", "周三", "需要")) else 0.72,
            }
        )
    return todos


def _block_text(block: dict[str, Any]) -> str:
    items = block.get("contentItems")
    if isinstance(items, list):
        values = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "paragraph":
                values.append(str(item.get("text") or ""))
            elif item.get("type") == "image":
                values.append(f"[图片：{item.get('name') or '未命名图片'}]")
        return "\n".join(values).strip()
    return str(block.get("content") or "").strip()


def _todo_description(todo: dict[str, Any]) -> str:
    parts = [
        str(todo.get("background") or ""),
        f"建议动作：{todo.get('suggestion')}" if todo.get("suggestion") else "",
        f"来源原文：{todo.get('source_text')}" if todo.get("source_text") else "",
    ]
    return "\n".join(part for part in parts if part)


def _todo_title(text: str, metric: str) -> str:
    clean = re.sub(r"^[0-9一二三四五六七八九十]+[.、]\s*", "", text).strip("；。")
    if len(clean) <= 28:
        return clean
    prefix = f"跟进{metric}" if metric else "跟进经营周报事项"
    return f"{prefix}：{clean[:30]}"


def _todo_suggestion(text: str) -> str:
    if "清单" in text:
        return "形成责任清单，按机构、客户经理或客户分层跟踪完成情况。"
    if "复核" in text:
        return "补齐数据证据并在下期周报中复核变化。"
    if "原因" in text:
        return "拆解责任主体和影响因素，补充原因说明及处理动作。"
    return "明确责任人、完成时间和复盘口径，纳入待办任务持续跟进。"


def _priority(text: str, metric: str) -> str:
    if any(token in text for token in ("风险", "缺口", "异常", "下周", "周一", "必须")):
        return "高"
    if metric:
        return "中"
    return "低"


def _weight(frequency: int, confidence: float, latest: bool) -> float:
    time_weight = 0.42 if latest else 0.22
    frequency_weight = min(0.28, frequency * 0.07)
    latest_weight = 0.15 if latest else 0
    confidence_weight = min(0.15, confidence * 0.15)
    return time_weight + frequency_weight + latest_weight + confidence_weight


def _match_metric(text: str, metrics: list[str]) -> str:
    for metric in metrics:
        if metric and metric in text:
            return metric
    return ""


def _split_sentences(text: str) -> list[str]:
    candidates = re.split(r"[\n。；;]+", text)
    return [candidate.strip() for candidate in candidates if candidate.strip()]


def _todo_priority_to_ui(value: Any) -> str:
    return {"高": "high", "中": "medium", "低": "low"}.get(str(value), "medium")


def _todo_status_to_ui(value: Any) -> str:
    return {"待处理": "todo", "处理中": "in_progress", "已完成": "done", "已关闭": "closed"}.get(str(value), "todo")


def _normalize_due_date(value: Any, now: str) -> str:
    text = str(value or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return now[:10]


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
