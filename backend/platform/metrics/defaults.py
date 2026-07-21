from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_default_metric_dictionary() -> list[dict[str, Any]]:
    seed_path = Path(__file__).resolve().parents[3] / "data" / "metric_dictionary_seed.json"
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return []
    return [dict(metric) for metric in metrics if isinstance(metric, dict)]
