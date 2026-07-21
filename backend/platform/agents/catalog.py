from __future__ import annotations

import json
from pathlib import Path

from .models import AgentGroupSpec, AgentSpec


class AgentCatalog:
    """Loads governed Agent group definitions from config files."""

    def __init__(self, groups: list[AgentGroupSpec]) -> None:
        self._groups = {group.group_id: group for group in groups}
        self._agents = {
            agent.agent_id: agent
            for group in groups
            for agent in group.agents
        }

    @classmethod
    def from_config_dir(cls, config_dir: str | Path) -> "AgentCatalog":
        groups: list[AgentGroupSpec] = []
        for path in sorted(Path(config_dir).glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            groups.append(
                AgentGroupSpec(
                    group_id=payload["group_id"],
                    group_name=payload["group_name"],
                    mission=payload["mission"],
                    controller_agent=payload["controller_agent"],
                    agents=tuple(
                        AgentSpec(
                            agent_id=item["agent_id"],
                            name=item["name"],
                            agent_type=item["type"],
                            description=item["responsibility"],
                            allowed_skills=tuple(item.get("allowed_skills", ())),
                        )
                        for item in payload["agents"]
                    ),
                    stage_gates=tuple(payload.get("stage_gates", ())),
                )
            )
        return cls(groups)

    def get_group(self, group_id: str) -> AgentGroupSpec:
        return self._groups[group_id]

    def get_agent(self, agent_id: str) -> AgentSpec:
        return self._agents[agent_id]

    def list_groups(self) -> list[AgentGroupSpec]:
        return sorted(self._groups.values(), key=lambda group: group.group_id)

    def list_agents(self) -> list[AgentSpec]:
        return sorted(self._agents.values(), key=lambda agent: agent.agent_id)

    def has_agent(self, agent_id: str) -> bool:
        return agent_id in self._agents
