from __future__ import annotations

from typing import Any

from backend.platform.kernel.events import EventBus
from backend.platform.settings import call_model_text_completion


class ModelGateway:
    """Single model completion seam for planning, supervisor, and learning drafts."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        model = inputs.get("model") if isinstance(inputs.get("model"), dict) else {}
        prompt = str(inputs.get("prompt") or "")
        max_tokens = int(inputs.get("max_tokens") or 1200)
        if self.event_bus is not None:
            self.event_bus.publish("llm.request", {"model_id": model.get("id") or "", "prompt_chars": len(prompt)})
        result = call_model_text_completion(model, prompt, max_tokens=max_tokens)
        if self.event_bus is not None:
            self.event_bus.publish(
                "llm.response",
                {"status": result.get("status"), "latency_ms": result.get("latency_ms"), "error_code": result.get("error_code")},
            )
        return result
