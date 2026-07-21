from __future__ import annotations

from .models import SkillHandler, SkillSpec


class SkillRegistry:
    """Governed capability registry."""

    def __init__(self) -> None:
        self._specs: dict[str, SkillSpec] = {}
        self._handlers: dict[str, SkillHandler] = {}

    def declare(self, spec: SkillSpec) -> None:
        self._specs.setdefault(spec.skill_id, spec)

    def register(self, spec: SkillSpec, handler: SkillHandler) -> None:
        if spec.status != "active":
            raise ValueError(f"Cannot register disabled skill: {spec.skill_id}")
        self._specs[spec.skill_id] = spec
        self._handlers[spec.skill_id] = handler

    def get(self, skill_id: str) -> SkillSpec:
        try:
            return self._specs[skill_id]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {skill_id}") from exc

    def handler(self, skill_id: str) -> SkillHandler:
        try:
            return self._handlers[skill_id]
        except KeyError as exc:
            raise KeyError(f"Unknown skill handler: {skill_id}") from exc

    def runtime_status(self, skill_id: str) -> dict[str, object]:
        spec = self.get(skill_id)
        implemented = skill_id in self._handlers
        return {
            "skill_id": skill_id,
            "version": spec.version,
            "configured": True,
            "implemented": implemented,
            "healthy": implemented and spec.status == "active",
            "enabled": spec.status == "active",
            "status": (
                "disabled" if spec.status != "active" else "healthy" if implemented else "configured_unimplemented"
            ),
        }

    def list_runtime_statuses(self) -> list[dict[str, object]]:
        return [self.runtime_status(spec.skill_id) for spec in self.list()]

    def list(self, skill_type: str | None = None) -> list[SkillSpec]:
        specs = self._specs.values()
        if skill_type:
            specs = [spec for spec in specs if spec.skill_type == skill_type]
        return sorted(specs, key=lambda spec: spec.skill_id)
