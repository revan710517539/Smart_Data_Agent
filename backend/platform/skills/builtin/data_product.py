from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any, Callable

from backend.platform.skills.models import SkillRequest, SkillResult, SkillSpec


def build_data_product_skills() -> list[tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]]:
    """Build deterministic, evidence-bound data product skills.

    These handlers intentionally do not call a model. They form the stable
    execution floor that learned procedural skills may guide but never replace.
    """

    from .loan_analysis import build_loan_analysis_skills

    return [
        _profile_skill(),
        *build_loan_analysis_skills(),
        _conclusion_skill(),
        _bi_report_skill(),
        _governance_skill(),
    ]


def _profile_skill() -> tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]:
    spec = SkillSpec(
        skill_id="data.analysis.profile",
        name="Data Analysis Profile",
        skill_type="analysis_algorithm",
        description="Profile governed query results without changing source data.",
        input_schema={"data": "array", "metrics": "array", "dimensions": "array"},
        output_schema={"analysis_profile": "object"},
        permission_scope=("analysis:run",),
        risk_level="low",
        runtime_type="python",
        timeout_seconds=30,
    )

    def handler(request: SkillRequest) -> SkillResult:
        rows = [dict(row) for row in request.inputs["data"] if isinstance(row, dict)]
        metrics = _strings(request.inputs.get("metrics"))
        dimensions = _strings(request.inputs.get("dimensions"))
        columns = list(dict.fromkeys(key for row in rows for key in row))
        metric_summary = {
            metric: _numeric_summary([row.get(metric) for row in rows])
            for metric in metrics
        }
        dimension_summary = {
            dimension: _dimension_summary([row.get(dimension) for row in rows])
            for dimension in dimensions
        }
        profile = {
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": columns,
            "metrics": metric_summary,
            "dimensions": dimension_summary,
            "empty_result": not rows,
            "profile_hash": _stable_hash(
                {
                    "columns": columns,
                    "metrics": metric_summary,
                    "dimensions": dimension_summary,
                    "row_count": len(rows),
                }
            ),
        }
        return SkillResult(
            skill_id=spec.skill_id,
            output={"analysis_profile": profile},
            audit={"row_count": len(rows), "metric_count": len(metrics), "dimension_count": len(dimensions)},
        )

    return spec, handler


def _governance_skill() -> tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]:
    spec = SkillSpec(
        skill_id="data.governance.assess",
        name="Data Governance Assess",
        skill_type="data_governance",
        description="Assess completeness, duplicates, sensitive fields, execution mode, and evidence readiness.",
        input_schema={"data": "array", "dataset_id": "string", "semantic_info": "object"},
        output_schema={"governance_assessment": "object"},
        permission_scope=("analysis:run", "data:quality"),
        risk_level="low",
        runtime_type="python",
        timeout_seconds=30,
    )

    def handler(request: SkillRequest) -> SkillResult:
        rows = [dict(row) for row in request.inputs["data"] if isinstance(row, dict)]
        semantic_info = dict(request.inputs.get("semantic_info") or {})
        columns = list(dict.fromkeys(key for row in rows for key in row))
        total_cells = len(rows) * len(columns)
        null_cells = sum(
            1
            for row in rows
            for column in columns
            if row.get(column) is None or str(row.get(column)).strip() == ""
        )
        row_hashes = [_stable_hash(row) for row in rows]
        duplicate_count = max(0, len(row_hashes) - len(set(row_hashes)))
        sensitive_fields = [
            column
            for column in columns
            if any(
                token in column.casefold()
                for token in (
                    "customer_id", "customer_name", "phone", "mobile", "id_card",
                    "证件", "身份证", "手机号", "客户号", "客户姓名",
                )
            )
        ]
        completeness = 1.0 if total_cells == 0 else round((total_cells - null_cells) / total_cells, 6)
        duplicate_ratio = 0.0 if not rows else round(duplicate_count / len(rows), 6)
        execution_mode = str(semantic_info.get("execution_mode") or "unknown")
        publishable = bool(semantic_info.get("publishable") is True and execution_mode == "real")
        issues: list[dict[str, Any]] = []
        if completeness < 0.95:
            issues.append({"code": "LOW_COMPLETENESS", "severity": "warning", "value": completeness})
        if duplicate_ratio > 0:
            issues.append({"code": "DUPLICATE_ROWS", "severity": "warning", "value": duplicate_ratio})
        if sensitive_fields:
            issues.append({"code": "SENSITIVE_FIELDS_PRESENT", "severity": "info", "fields": sensitive_fields})
        if not publishable:
            issues.append({"code": "NOT_PUBLISHABLE_EVIDENCE", "severity": "info", "execution_mode": execution_mode})
        score = max(
            0.0,
            min(
                1.0,
                completeness
                - min(duplicate_ratio, 0.3)
                - (0.05 if sensitive_fields else 0)
                - (0.1 if not publishable else 0),
            ),
        )
        assessment = {
            "dataset_id": str(request.inputs["dataset_id"]),
            "row_count": len(rows),
            "completeness": completeness,
            "duplicate_count": duplicate_count,
            "duplicate_ratio": duplicate_ratio,
            "sensitive_fields": sensitive_fields,
            "execution_mode": execution_mode,
            "publishable": publishable,
            "quality_score": round(score, 6),
            "issues": issues,
            "policy": {
                "source_data_mutated": False,
                "arbitrary_code_executed": False,
                "permission_boundary": "existing_skill_executor",
            },
        }
        return SkillResult(
            skill_id=spec.skill_id,
            output={"governance_assessment": assessment},
            audit={
                "dataset_id": assessment["dataset_id"],
                "quality_score": assessment["quality_score"],
                "issue_count": len(issues),
            },
        )

    return spec, handler


def _conclusion_skill() -> tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]:
    spec = SkillSpec(
        skill_id="conclusion.generate",
        name="Evidence Conclusion Generate",
        skill_type="conclusion_generation",
        description="Generate layered conclusions from reviewed plans, profiles, and governance evidence.",
        input_schema={
            "question": "string",
            "analysis_plan": "object",
            "analysis_profile": "object",
            "governance_assessment": "object",
            "learned_guidance": "array?",
        },
        output_schema={"conclusions": "array", "conclusion_contract": "object"},
        permission_scope=("analysis:run",),
        risk_level="low",
        runtime_type="python",
        timeout_seconds=30,
    )

    def handler(request: SkillRequest) -> SkillResult:
        plan = dict(request.inputs["analysis_plan"])
        profile = dict(request.inputs["analysis_profile"])
        governance = dict(request.inputs["governance_assessment"])
        metrics = _strings(plan.get("metrics"))
        dimensions = _strings(plan.get("dimensions"))
        primary_metric = metrics[0] if metrics else "metric_value"
        primary = dict((profile.get("metrics") or {}).get(primary_metric) or {})
        count = int(primary.get("count") or 0)
        total = float(primary.get("sum") or 0)
        mean = float(primary.get("mean") or 0)
        facts = [
            f"本轮返回 {int(profile.get('row_count') or 0)} 行、{int(profile.get('column_count') or 0)} 个字段。",
            f"{primary_metric} 的有效值共 {count} 个，合计 {total:,.2f}，均值 {mean:,.2f}。",
        ]
        if dimensions:
            facts.append(f"分析按 {'、'.join(dimensions)} 进行拆分。")
        interpretations = [
            "当前结论仅描述本次证据范围内的结构和变化，不将相关性直接表述为因果。"
        ]
        if governance.get("issues"):
            interpretations.append(
                f"数据治理检查发现 {len(governance['issues'])} 项提示，解释和发布时需保留适用边界。"
            )
        learned = [
            {
                "skill_id": str(item.get("skill_id") or item.get("id") or ""),
                "viewpoint_strategy": str(item.get("viewpointStrategy") or ""),
                "output_format": str(item.get("outputFormat") or ""),
            }
            for item in request.inputs.get("learned_guidance") or []
            if isinstance(item, dict)
        ]
        actions = [
            "复核口径、时间范围和机构权限后，再将结论用于经营动作。",
            "对异常维度下钻到可追溯明细，并同时保留反证与风险提示。",
        ]
        conclusions = [*facts, *interpretations, *actions]
        contract = {
            "facts": facts,
            "interpretations": interpretations,
            "actions": actions,
            "question": str(request.inputs["question"]),
            "primary_metric": primary_metric,
            "evidence_profile_hash": str(profile.get("profile_hash") or ""),
            "governance_score": governance.get("quality_score"),
            "learned_skill_guidance": learned,
            "claim_policy": "facts_then_interpretation_then_action",
        }
        return SkillResult(
            skill_id=spec.skill_id,
            output={"conclusions": conclusions, "conclusion_contract": contract},
            audit={
                "conclusion_count": len(conclusions),
                "profile_hash": contract["evidence_profile_hash"],
                "learned_skill_count": len(learned),
            },
        )

    return spec, handler


def _bi_report_skill() -> tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]:
    spec = SkillSpec(
        skill_id="bi.report.generate",
        name="Governed BI Report Generate",
        skill_type="report_generation",
        description="Build an auditable BI report specification from analysis evidence.",
        input_schema={
            "question": "string",
            "analysis_plan": "object",
            "analysis_profile": "object",
            "governance_assessment": "object",
            "chart_spec": "object",
            "conclusions": "array",
        },
        output_schema={"report_spec": "object"},
        permission_scope=("analysis:run", "report:generate"),
        risk_level="low",
        runtime_type="python",
        timeout_seconds=30,
    )

    def handler(request: SkillRequest) -> SkillResult:
        plan = dict(request.inputs["analysis_plan"])
        profile = dict(request.inputs["analysis_profile"])
        governance = dict(request.inputs["governance_assessment"])
        report_spec = {
            "schema": "smart_data_agent.bi_report.v1",
            "title": str(request.inputs["question"])[:200],
            "dataset_id": str(plan.get("dataset_id") or ""),
            "sections": [
                {
                    "id": "executive_summary",
                    "type": "conclusion",
                    "title": "核心结论",
                    "items": list(request.inputs["conclusions"]),
                },
                {
                    "id": "visual_analysis",
                    "type": "chart",
                    "title": "可视化分析",
                    "chart_spec": dict(request.inputs["chart_spec"]),
                },
                {
                    "id": "data_profile",
                    "type": "profile",
                    "title": "数据概览",
                    "profile": profile,
                },
                {
                    "id": "governance",
                    "type": "governance",
                    "title": "数据治理与发布边界",
                    "assessment": governance,
                },
            ],
            "metric_codes": _strings(plan.get("metrics")),
            "dimension_codes": _strings(plan.get("dimensions")),
            "evidence": {
                "profile_hash": str(profile.get("profile_hash") or ""),
                "execution_mode": str(governance.get("execution_mode") or "unknown"),
                "publishable": bool(governance.get("publishable")),
            },
            "status": "generated_spec",
            "published": False,
        }
        report_spec["content_hash"] = _stable_hash(report_spec)
        return SkillResult(
            skill_id=spec.skill_id,
            output={"report_spec": report_spec},
            audit={
                "dataset_id": report_spec["dataset_id"],
                "section_count": len(report_spec["sections"]),
                "content_hash": report_spec["content_hash"],
            },
        )

    return spec, handler


def _numeric_summary(values: list[Any]) -> dict[str, Any]:
    numbers = [number for value in values if (number := _number(value)) is not None]
    missing = len(values) - len(numbers)
    if not numbers:
        return {
            "count": 0,
            "missing": missing,
            "sum": 0.0,
            "mean": 0.0,
            "min": None,
            "max": None,
            "first": None,
            "last": None,
            "change": None,
        }
    return {
        "count": len(numbers),
        "missing": missing,
        "sum": round(sum(numbers), 6),
        "mean": round(sum(numbers) / len(numbers), 6),
        "min": min(numbers),
        "max": max(numbers),
        "first": numbers[0],
        "last": numbers[-1],
        "change": round(numbers[-1] - numbers[0], 6) if len(numbers) > 1 else 0.0,
    }


def _dimension_summary(values: list[Any]) -> dict[str, Any]:
    normalized = [str(value) for value in values if value is not None and str(value).strip()]
    counts = Counter(normalized)
    return {
        "count": len(normalized),
        "missing": len(values) - len(normalized),
        "cardinality": len(counts),
        "top_values": [
            {"value": value, "count": count}
            for value, count in counts.most_common(10)
        ],
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
