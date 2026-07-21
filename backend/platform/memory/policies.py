from __future__ import annotations

from .models import MemoryRecord


def should_persist_memory(record: MemoryRecord) -> bool:
    reusable_types = {
        "analysis_case",
        "business_rule",
        "metric_correction",
        "user_preference",
        "behavior_habit",
        "business_fact",
        "preference",
        "warning",
    }
    minimum_confidence = 0.5 if record.verified_status == "candidate" else 0.7
    return record.memory_type in reusable_types and record.confidence >= minimum_confidence
