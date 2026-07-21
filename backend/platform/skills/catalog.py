from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import SkillSpec


class SkillConfigCatalog:
    """Loads skill metadata from configs/skills without requiring runtime handlers."""

    def __init__(self, specs: list[SkillSpec]) -> None:
        self._specs = {spec.skill_id: spec for spec in specs}

    @classmethod
    def from_config_dir(cls, config_dir: str | Path) -> "SkillConfigCatalog":
        specs: list[SkillSpec] = []
        for path in sorted(Path(config_dir).glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries = payload if isinstance(payload, list) else [payload]
            specs.extend(cls._parse_entry(entry) for entry in entries)
        return cls(specs)

    @staticmethod
    def _parse_entry(entry: dict[str, Any]) -> SkillSpec:
        return SkillSpec(
            skill_id=entry["skill_id"],
            name=entry.get("skill_name") or entry.get("name") or entry["skill_id"],
            skill_type=entry["skill_type"],
            description=entry.get("description", ""),
            input_schema=entry.get("input_schema", {}),
            output_schema=entry.get("output_schema", {}),
            permission_scope=tuple(entry.get("permission_scope", ())),
            risk_level=entry.get("risk_level", "medium"),
            runtime_type=entry.get("runtime_type", "python"),
            version=entry.get("version", "1.0.0"),
            owner=entry.get("owner", "data-platform"),
            status=entry.get("status", "active"),
            timeout_seconds=int(entry.get("timeout_seconds", 60)),
            max_retries=max(0, min(int(entry.get("max_retries", 0)), 3)),
            requires_approval=bool(entry.get("requires_approval", entry.get("risk_level") == "high")),
        )

    def get(self, skill_id: str) -> SkillSpec:
        return self._specs[skill_id]

    def has(self, skill_id: str) -> bool:
        return skill_id in self._specs

    def list(self) -> list[SkillSpec]:
        return sorted(self._specs.values(), key=lambda spec: spec.skill_id)
