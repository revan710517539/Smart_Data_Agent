from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Any, Callable

from backend.platform.kernel.models import utc_now

KernelListener = Callable[[str, dict[str, Any]], None]


class EventBus:
    """In-process kernel event bus. Listener failures never fail the publisher."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._listeners: dict[str, list[KernelListener]] = defaultdict(list)
        self._log: list[dict[str, Any]] = []

    def subscribe(self, event_type: str, listener: KernelListener) -> Callable[[], None]:
        name = str(event_type or "").strip()
        if not name:
            raise ValueError("runtime_event_type_required")
        with self._lock:
            self._listeners[name].append(listener)

        def dispose() -> None:
            with self._lock:
                current = self._listeners.get(name) or []
                self._listeners[name] = [item for item in current if item is not listener]

        return dispose

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "event_type": str(event_type),
            "payload": dict(payload or {}),
            "created_at": utc_now(),
        }
        with self._lock:
            self._log.append(event)
            listeners = list(self._listeners.get(event_type, ()))
            listeners.extend(self._listeners.get("*", ()))
        for listener in listeners:
            try:
                listener(event_type, event["payload"])
            except Exception:
                continue
        return event

    def recent(self, event_type: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._log)
        if event_type:
            items = [item for item in items if item["event_type"] == event_type]
        return items[-max(1, min(int(limit), 500)) :]
