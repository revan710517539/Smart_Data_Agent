from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    provider: str
    capabilities: tuple[str, ...]
    context_window: int
    data_policy: str
    status: str = "active"


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    prompt_type: str
    template_content: str
    variables: tuple[str, ...]
    version: str = "1.0.0"


class InMemoryModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelSpec] = {}
        self._prompts: dict[str, PromptTemplate] = {}

    def register_model(self, spec: ModelSpec) -> None:
        self._models[spec.model_id] = spec

    def get_model(self, model_id: str) -> ModelSpec:
        return self._models[model_id]

    def register_prompt(self, template: PromptTemplate) -> None:
        self._prompts[template.prompt_id] = template

    def get_prompt(self, prompt_id: str) -> PromptTemplate:
        return self._prompts[prompt_id]

