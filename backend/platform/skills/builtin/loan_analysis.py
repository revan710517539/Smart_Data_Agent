from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

from backend.platform.skills.models import SkillRequest, SkillResult, SkillSpec


METHOD_SKILL_IDS = {
    "descriptive": "data.analysis.descriptive",
    "attribution": "data.analysis.attribution",
    "predictive": "data.analysis.predictive",
}


def build_loan_analysis_skills() -> list[tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]]:
    """Deterministic analysis methods shared by the scene and tenant overlays."""

    return [
        _method_skill("descriptive", "描述性分析", _describe),
        _method_skill("attribution", "归因分析", _attribute),
        _method_skill("predictive", "预测分析", _predict),
    ]


def _method_skill(
    kind: str,
    name: str,
    handler: Callable[[list[dict[str, Any]], dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]:
    skill_id = METHOD_SKILL_IDS[kind]
    spec = SkillSpec(
        skill_id=skill_id,
        name=name,
        skill_type="analysis_method",
        description=f"对受治理查询结果执行{name}，并显式返回证据边界。",
        input_schema={"data": "array", "analysis_plan": "object", "semantic_info": "object"},
        output_schema={"analysis_method": "object"},
        permission_scope=("analysis:run",),
        risk_level="low",
        runtime_type="python",
        version="1.0.0",
        owner="smart-data-agent",
        timeout_seconds=30,
    )

    def invoke(request: SkillRequest) -> SkillResult:
        rows = [dict(row) for row in request.inputs["data"] if isinstance(row, dict)]
        plan = dict(request.inputs["analysis_plan"])
        semantic = dict(request.inputs["semantic_info"])
        result = handler(rows, plan, semantic)
        result.update(
            {
                "kind": kind,
                "skill_id": skill_id,
                "row_count": len(rows),
                "dataset_id": str(plan.get("dataset_id") or semantic.get("dataset_id") or ""),
                "evidence_boundary": _evidence_boundary(rows, semantic),
            }
        )
        return SkillResult(
            skill_id=skill_id,
            output={"analysis_method": result},
            audit={
                "kind": kind,
                "row_count": len(rows),
                "claim_level": result["evidence_boundary"]["claim_level"],
            },
        )

    return spec, invoke


def _describe(rows: list[dict[str, Any]], plan: dict[str, Any], _semantic: dict[str, Any]) -> dict[str, Any]:
    metrics = _strings(plan.get("metrics"))
    dimensions = _strings(plan.get("dimensions"))
    metric_summaries: dict[str, Any] = {}
    for metric in metrics:
        values = [_number(row.get(metric)) for row in rows]
        numbers = [value for value in values if value is not None]
        metric_summaries[metric] = {
            "count": len(numbers),
            "missing": len(values) - len(numbers),
            "sum": round(sum(numbers), 6) if numbers else 0.0,
            "mean": round(sum(numbers) / len(numbers), 6) if numbers else None,
            "min": min(numbers) if numbers else None,
            "max": max(numbers) if numbers else None,
        }
    primary = metrics[0] if metrics else ""
    ranked = []
    if primary and dimensions:
        ranked = sorted(
            (
                {"dimension": row.get(dimensions[0]), "value": _number(row.get(primary))}
                for row in rows
                if _number(row.get(primary)) is not None
            ),
            key=lambda item: float(item["value"]),
            reverse=True,
        )[:10]
    return {
        "method": "total_structure_trend_extremes_anomalies",
        "metrics": metric_summaries,
        "primary_ranking": ranked,
        "dimensions": dimensions,
        "claims": ["仅陈述本次返回数据中的总量、结构、分布、极值和变化，不解释因果。"],
    }


def _attribute(rows: list[dict[str, Any]], plan: dict[str, Any], _semantic: dict[str, Any]) -> dict[str, Any]:
    metrics = _strings(plan.get("metrics"))
    dimensions = _strings(plan.get("dimensions"))
    primary = metrics[0] if metrics else ""
    dimension = dimensions[0] if dimensions else ""
    grouped: dict[str, float] = defaultdict(float)
    for row in rows:
        value = _number(row.get(primary)) if primary else None
        if value is not None:
            grouped[str(row.get(dimension) or "未分类")] += value
    total = sum(abs(value) for value in grouped.values())
    contributions = [
        {
            "dimension": key,
            "value": round(value, 6),
            "share_of_absolute_total": round(abs(value) / total, 6) if total else 0.0,
        }
        for key, value in sorted(grouped.items(), key=lambda item: abs(item[1]), reverse=True)
    ][:20]
    return {
        "method": "baseline_contribution_cross_check_counterevidence",
        "primary_metric": primary,
        "contribution_dimension": dimension,
        "contributions": contributions,
        "causal_status": "contribution_only",
        "required_for_causal_claim": ["明确对比基线", "时间先后关系", "机制证据", "反事实或准实验验证"],
        "claims": ["当前只计算结构贡献；没有充分反事实证据时，不把相关关系写成因果。"],
    }


def _predict(rows: list[dict[str, Any]], plan: dict[str, Any], _semantic: dict[str, Any]) -> dict[str, Any]:
    metrics = _strings(plan.get("metrics"))
    dimensions = _strings(plan.get("dimensions"))
    primary = metrics[0] if metrics else ""
    time_dimension = next((item for item in dimensions if any(token in item.casefold() for token in ("time", "date", "month", "week", "day", "stat_"))), "")
    series = [
        (str(row.get(time_dimension) or ""), value)
        for row in rows
        if time_dimension and (value := _number(row.get(primary))) is not None
    ]
    series.sort(key=lambda item: item[0])
    values = [item[1] for item in series]
    if len(values) < 4:
        return {
            "method": "time_series_baseline_with_interval",
            "status": "insufficient_history",
            "primary_metric": primary,
            "time_dimension": time_dimension,
            "minimum_points": 4,
            "observed_points": len(values),
            "forecast": None,
            "claims": ["历史点不足，不能生成可信预测；仅保留预测所需条件。"],
        }
    n = len(values)
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    denominator = sum((index - mean_x) ** 2 for index in range(n))
    slope = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values)) / denominator
    intercept = mean_y - slope * mean_x
    fitted = [intercept + slope * index for index in range(n)]
    residuals = [value - estimate for value, estimate in zip(values, fitted)]
    residual_std = math.sqrt(sum(value * value for value in residuals) / max(1, n - 2))
    point = intercept + slope * n
    margin = 1.96 * residual_std
    return {
        "method": "linear_baseline_with_residual_interval",
        "status": "baseline_ready",
        "primary_metric": primary,
        "time_dimension": time_dimension,
        "observed_points": n,
        "forecast": {
            "point": round(point, 6),
            "lower": round(point - margin, 6),
            "upper": round(point + margin, 6),
            "horizon": 1,
        },
        "assumptions": ["历史口径连续", "当前线性趋势短期延续", "未发生结构性政策或业务变化"],
        "invalid_when": ["指标口径变化", "样本覆盖突变", "政策、渠道或产品发生结构性变化"],
        "claims": ["结果是短期统计基线及区间，不是已发生事实或经营承诺。"],
    }


def _evidence_boundary(rows: list[dict[str, Any]], semantic: dict[str, Any]) -> dict[str, Any]:
    snapshot = semantic.get("source_snapshot") if isinstance(semantic.get("source_snapshot"), dict) else {}
    real = str(semantic.get("execution_mode") or "") == "real"
    complete = bool(semantic.get("evidence_complete") is True and snapshot)
    return {
        "execution_mode": str(semantic.get("execution_mode") or "unknown"),
        "source_snapshot": snapshot,
        "claim_level": "evidence_bound" if rows and real and complete else "limited",
        "publishable": bool(semantic.get("publishable") is True and rows and complete),
        "limitations": ([] if rows else ["查询未返回数据"]) + ([] if complete else ["缺少完整、不可变的数据快照证据"]),
    }


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value or [] if str(item).strip()]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
