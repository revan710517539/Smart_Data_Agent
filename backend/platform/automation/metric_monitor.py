from __future__ import annotations

import json
from math import isfinite
from typing import Any, Callable

from backend.platform.semantic import SemanticQueryRequest


SUPPORTED_COMPARISONS = {"relative_change", "absolute_change", "above", "below"}
SUPPORTED_DIRECTIONS = {"both", "up", "down"}


def run_metric_monitor(
    services: Any,
    *,
    tenant_id: str,
    user_id: str,
    config: dict[str, Any],
    trigger_payload: dict[str, Any],
    request_id: str,
    cancellation_check: Callable[[], bool] | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Evaluate the hard anomaly rule before crossing the model boundary."""

    merged = {**config, **trigger_payload}
    metric_contexts = [dict(item) for item in merged.get("selected_metrics") or [] if isinstance(item, dict)]
    if not metric_contexts:
        raise ValueError("automatic_analysis_metrics_required")
    rule = _normalize_rule(merged.get("anomaly_rule"))
    snapshots = [
        _query_metric_snapshot(services, tenant_id, user_id, metric, rule)
        for metric in metric_contexts[:20]
    ]
    evaluated = [snapshot for snapshot in snapshots if snapshot.get("status") == "evaluated"]
    matched = [snapshot for snapshot in evaluated if snapshot.get("triggered") is True]
    trigger_mode = str(rule.get("match_mode") or "any")
    hard_triggered = bool(evaluated) and (
        len(matched) == len(evaluated) if trigger_mode == "all" else bool(matched)
    )
    monitoring_result = {
        "triggered": hard_triggered,
        "model_invoked": False,
        "match_mode": trigger_mode,
        "rule": rule,
        "metrics": snapshots,
        "triggered_metric_count": len(matched),
    }
    if not hard_triggered:
        return monitoring_result

    from backend.platform.api.routes.analysis import run_analysis

    skill = merged.get("analysis_skill") if isinstance(merged.get("analysis_skill"), dict) else {}
    prompt = str(merged.get("prompt") or merged.get("question") or "").strip()
    if not prompt:
        raise ValueError("automatic_analysis_prompt_required")
    model_selection = merged.get("model_application_selection")
    if not isinstance(model_selection, dict) or not str(model_selection.get("integrationId") or "").strip():
        raise ValueError("automatic_analysis_model_selection_required")
    selected_tables = _selected_tables(metric_contexts)
    packaged_context = {
        "anomaly_rule": rule,
        "triggered_metrics": matched,
        "selected_metrics": metric_contexts,
        "analysis_skill": skill,
    }
    question = (
        f"{prompt}\n\n"
        "以下是自动监控硬规则命中的上下文。请基于治理后的指标口径、Skill和实际查询证据进行归因分析：\n"
        + json.dumps(packaged_context, ensure_ascii=False, default=str)[:12000]
    )
    analysis = run_analysis(
        services,
        user_id=user_id,
        tenant_id=tenant_id,
        question=question,
        page_context={
            "route": "automation/automatic-analysis",
            "request_id": request_id,
            "analysis_trigger": "automatic_metric_anomaly",
            "model_application_module": "automatic_analysis",
            "model_application_selection": dict(model_selection),
            "selected_data_tables": selected_tables,
            "analysis_skill": skill,
            "analysis_context_skills": [skill] if skill else [],
            "analysis_policy": {"resultDelivery": "data_first"},
            "monitoring_trigger": monitoring_result,
        },
        cancellation_check=cancellation_check,
        progress_callback=progress_callback,
    )
    return {
        **monitoring_result,
        "model_invoked": True,
        "analysis_task_id": analysis.get("task_id"),
        "analysis_status": analysis.get("status"),
        "analysis": analysis,
    }


def _query_metric_snapshot(
    services: Any,
    tenant_id: str,
    user_id: str,
    metric: dict[str, Any],
    rule: dict[str, Any],
) -> dict[str, Any]:
    metric_code = str(metric.get("metricCode") or metric.get("metric_code") or "").strip()
    dataset_id = str(metric.get("datasetId") or metric.get("dataset_id") or "").strip()
    time_dimension = str(metric.get("timeDimension") or metric.get("time_dimension") or "stat_date").strip()
    label = str(metric.get("metricName") or metric.get("metric_name") or metric_code).strip()
    if not metric_code or not dataset_id:
        return {"status": "unavailable", "metric": label, "reason": "metric_execution_metadata_missing"}
    try:
        result = services.semantic_service.query(
            SemanticQueryRequest(
                question=f"获取{label}最近两个统计周期用于异动监控",
                tenant_id=tenant_id,
                user_id=user_id,
                dataset_id=dataset_id,
                metrics=(metric_code,),
                dimensions=(time_dimension,),
                limit=max(2, int(rule.get("lookback_periods") or 2)),
                sort_direction="desc",
                context={"surface": "automatic_analysis", "purpose": "hard_anomaly_rule"},
            )
        )
    except (KeyError, ValueError, PermissionError) as exc:
        return {"status": "unavailable", "metric": label, "reason": str(exc)[:240]}
    usable = []
    for row in result.data:
        value = _number(row.get(metric_code))
        if value is None:
            continue
        usable.append({"period": str(row.get(time_dimension) or ""), "value": value})
    usable.sort(key=lambda item: item["period"])
    if len(usable) < 2:
        return {
            "status": "insufficient_data",
            "metric": label,
            "metric_code": metric_code,
            "dataset_id": dataset_id,
            "points": usable,
            "reason": "at_least_two_periods_required",
        }
    previous, current = usable[-2], usable[-1]
    evaluation = _evaluate(previous["value"], current["value"], rule)
    return {
        "status": "evaluated",
        "metric": label,
        "metric_code": metric_code,
        "dataset_id": dataset_id,
        "time_dimension": time_dimension,
        "previous": previous,
        "current": current,
        **evaluation,
    }


def _evaluate(previous: float, current: float, rule: dict[str, Any]) -> dict[str, Any]:
    comparison = str(rule["comparison"])
    threshold = float(rule["threshold"])
    delta = current - previous
    relative_change = None if previous == 0 else delta / abs(previous) * 100
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    direction_matches = rule["direction"] == "both" or rule["direction"] == direction
    observed: float | None
    if comparison == "relative_change":
        observed = relative_change
        threshold_matches = observed is not None and abs(observed) >= threshold
    elif comparison == "absolute_change":
        observed = delta
        threshold_matches = abs(delta) >= threshold
    elif comparison == "above":
        observed = current
        threshold_matches = current > threshold
        direction_matches = True
    else:
        observed = current
        threshold_matches = current < threshold
        direction_matches = True
    return {
        "comparison": comparison,
        "threshold": threshold,
        "observed": observed,
        "delta": delta,
        "relative_change_percent": relative_change,
        "direction": direction,
        "triggered": bool(threshold_matches and direction_matches),
    }


def _normalize_rule(value: Any) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, dict) else {}
    comparison = str(raw.get("comparison") or "relative_change")
    if comparison not in SUPPORTED_COMPARISONS:
        raise ValueError("automatic_analysis_rule_comparison_invalid")
    direction = str(raw.get("direction") or "both")
    if direction not in SUPPORTED_DIRECTIONS:
        raise ValueError("automatic_analysis_rule_direction_invalid")
    threshold = _number(raw.get("threshold"))
    if threshold is None or threshold < 0:
        raise ValueError("automatic_analysis_rule_threshold_invalid")
    return {
        "comparison": comparison,
        "threshold": threshold,
        "direction": direction,
        "match_mode": "all" if str(raw.get("match_mode")) == "all" else "any",
        "lookback_periods": max(2, min(int(raw.get("lookback_periods") or 2), 52)),
    }


def _selected_tables(metrics: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for metric in metrics:
        table_id = str(metric.get("tableId") or metric.get("table_id") or "").strip()
        table_code = str(metric.get("tableCode") or metric.get("table_code") or "").strip()
        identity = table_id or table_code
        if not identity or identity in seen:
            continue
        seen.add(identity)
        result.append({
            "id": table_id,
            "code": table_code,
            "name": str(metric.get("sourceTable") or metric.get("source_table") or "").strip(),
        })
    return result


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None
