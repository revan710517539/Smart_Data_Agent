from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import TaskType


@dataclass(frozen=True)
class AnalysisIntentRule:
    rule_id: str
    task_type: TaskType
    terms: tuple[str, ...]
    dataset_id: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    chart_types: tuple[str, ...]
    analysis_angles: tuple[str, ...]


class AnalysisPlanningCatalog:
    """Config-backed intent and plan selector for the deterministic workflow."""

    def __init__(
        self,
        rules: tuple[AnalysisIntentRule, ...],
        default_rule: AnalysisIntentRule,
        business_focus: str,
    ) -> None:
        self.rules = rules
        self.default_rule = default_rule
        self.business_focus = business_focus

    @classmethod
    def from_config_path(cls, path: str | Path = "configs/analysis/intent_rules.json") -> "AnalysisPlanningCatalog":
        config_path = Path(path)
        if not config_path.exists():
            return cls.default()
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        rules = tuple(_rule_from_payload(item) for item in raw.get("rules", []) if isinstance(item, dict))
        default_rule = _rule_from_payload({"id": "default", "terms": [], **dict(raw.get("default") or {})})
        return cls(
            rules=rules,
            default_rule=default_rule,
            business_focus=str(raw.get("business_focus") or DEFAULT_BUSINESS_FOCUS),
        )

    @classmethod
    def default(cls) -> "AnalysisPlanningCatalog":
        default_rule = AnalysisIntentRule(
            rule_id="default",
            task_type="simple_metric_query",
            terms=(),
            dataset_id="loan_operation_mart",
            metrics=("loan_amount", "drawdown_rate"),
            dimensions=("branch_name", "product_line"),
            chart_types=("column", "table"),
            analysis_angles=(
                "按机构和产品线拆分规模贡献",
                "结合动支率、转化率和余额变化判断经营质量",
            ),
        )
        return cls(rules=(), default_rule=default_rule, business_focus=DEFAULT_BUSINESS_FOCUS)

    def select(self, question: str) -> AnalysisIntentRule:
        normalized = question.lower()
        for rule in self.rules:
            if any(term and (term in question or term.lower() in normalized) for term in rule.terms):
                return rule
        return self.default_rule


DEFAULT_BUSINESS_FOCUS = "消费贷关注客群转化、额度使用和风险迁徙；经营贷关注经营稳定性、续贷留存、行业风险和动支节奏。"


def _rule_from_payload(payload: dict[str, Any]) -> AnalysisIntentRule:
    return AnalysisIntentRule(
        rule_id=str(payload.get("id") or "unnamed"),
        task_type=_task_type(payload.get("task_type")),
        terms=tuple(_string_list(payload.get("terms"))),
        dataset_id=str(payload.get("dataset_id") or "loan_operation_mart"),
        metrics=tuple(_string_list(payload.get("metrics")) or ["loan_amount"]),
        dimensions=tuple(_string_list(payload.get("dimensions")) or ["branch_name"]),
        chart_types=tuple(_string_list(payload.get("chart_types")) or ["column", "table"]),
        analysis_angles=tuple(_string_list(payload.get("analysis_angles"))),
    )


def _task_type(value: Any) -> TaskType:
    text = str(value or "simple_metric_query")
    if text in {"simple_metric_query", "diagnostic_analysis", "report_generation"}:
        return text  # type: ignore[return-value]
    return "simple_metric_query"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]
