from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnalysisWorkspaceContext:
    page_key: str
    artifact_id: str = ""
    dataset_snapshot: dict[str, Any] = field(default_factory=dict)
    metric_versions: tuple[dict[str, Any], ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    selected_data_point: dict[str, Any] | None = None
    allowed_actions: tuple[str, ...] = ()
    evidence_refs: tuple[dict[str, Any], ...] = ()

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualizationSpec:
    chart_type: str
    title: str
    x: str = ""
    y: tuple[str, ...] = ()
    series: str = ""
    orientation: str = "vertical"
    reason: str = ""
    alternatives: tuple[str, ...] = ()
    unit: str = ""
    precision: int = 2
    interactions: tuple[str, ...] = ("inspect", "branch")
    pivot: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)
