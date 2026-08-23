from __future__ import annotations

from typing import Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextvars import copy_context

from backend.platform.governance import PermissionBroker, approval_input_hash
from backend.platform.observability import TraceRecorder

from .models import SkillRequest, SkillResult, SkillSpec
from .registry import SkillRegistry


class SkillExecutor:
    """Validates, authorizes, executes, and traces skill calls."""

    def __init__(
        self,
        registry: SkillRegistry,
        permission_broker: PermissionBroker,
        trace_recorder: TraceRecorder,
        rate_limiter: Any | None = None,
        approval_store: Any | None = None,
    ) -> None:
        self.registry = registry
        self.permission_broker = permission_broker
        self.trace_recorder = trace_recorder
        self.rate_limiter = rate_limiter
        self.approval_store = approval_store
        self._invoke_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="skill-invoke")

    def close(self) -> None:
        self._invoke_pool.shutdown(wait=False, cancel_futures=True)

    def execute(self, request: SkillRequest) -> SkillResult:
        spec = self.registry.get(request.skill_id)
        status = self.registry.runtime_status(spec.skill_id)
        if not status["implemented"] or not status["healthy"]:
            raise RuntimeError(f"skill_unavailable:{spec.skill_id}:{status['status']}")
        self.permission_broker.require_skill(request.context, spec.skill_id)
        self._validate_inputs(spec, request.inputs)
        if spec.requires_approval:
            if not request.approval_id or self.approval_store is None:
                raise PermissionError(f"skill_approval_required:{spec.skill_id}")
            self.approval_store.consume(
                request.approval_id,
                tenant_id=request.context.tenant_id,
                requested_by=request.context.user_id,
                subject_type="skill",
                subject_id=spec.skill_id,
                action="execute",
                input_hash=approval_input_hash(request.inputs),
            )
        if self.rate_limiter is not None:
            decision = self.rate_limiter.check(
                f"skill:{request.context.tenant_id}:{request.context.user_id}:{spec.skill_id}",
                30,
                60,
            )
            if not decision.allowed:
                from backend.platform.security import RateLimitExceeded

                raise RateLimitExceeded(decision.retry_after_seconds)
        self.trace_recorder.add_span(
            "skill.execute.start",
            inputs={"skill_id": spec.skill_id, "input_keys": sorted(request.inputs)},
        )
        result = self._invoke_with_policy(spec, request)
        self._validate_outputs(spec, result.output)
        self.trace_recorder.add_span(
            "skill.execute.finish",
            inputs={"skill_id": spec.skill_id},
            outputs={"output_keys": sorted(result.output)},
        )
        return result

    def _invoke_with_policy(self, spec: SkillSpec, request: SkillRequest) -> SkillResult:
        last_error: Exception | None = None
        for attempt in range(spec.max_retries + 1):
            context = copy_context()
            future = self._invoke_pool.submit(context.run, self.registry.handler(spec.skill_id), request)
            try:
                return future.result(timeout=max(1, min(int(spec.timeout_seconds), 300)))
            except FutureTimeoutError as exc:
                future.cancel()
                last_error = TimeoutError(f"skill_timeout:{spec.skill_id}")
            except Exception as exc:
                last_error = exc
            if attempt < spec.max_retries:
                self.trace_recorder.add_span(
                    "skill.execute.retry",
                    inputs={"skill_id": spec.skill_id, "attempt": attempt + 1},
                    status="error",
                )
        assert last_error is not None
        raise last_error

    @staticmethod
    def _validate_inputs(spec: SkillSpec, inputs: dict[str, Any]) -> None:
        missing = [key for key, type_name in spec.input_schema.items() if not _is_optional(type_name) and key not in inputs]
        if missing:
            raise ValueError(f"Missing skill inputs for {spec.skill_id}: {', '.join(missing)}")
        _validate_schema(spec.skill_id, "input", spec.input_schema, inputs)

    @staticmethod
    def _validate_outputs(spec: SkillSpec, outputs: dict[str, Any]) -> None:
        missing = [key for key, type_name in spec.output_schema.items() if not _is_optional(type_name) and key not in outputs]
        if missing:
            raise ValueError(f"Missing skill outputs for {spec.skill_id}: {', '.join(missing)}")
        _validate_schema(spec.skill_id, "output", spec.output_schema, outputs)


def _is_optional(type_name: str) -> bool:
    return type_name.endswith("?")


def _base_type(type_name: str) -> str:
    return type_name[:-1] if _is_optional(type_name) else type_name


def _validate_schema(skill_id: str, direction: str, schema: dict[str, str], payload: dict[str, Any]) -> None:
    for key, type_name in schema.items():
        if key not in payload:
            continue
        expected_type = _base_type(type_name)
        value = payload[key]
        if expected_type == "string" and not isinstance(value, str):
            raise TypeError(f"Invalid {direction} for {skill_id}.{key}: expected string")
        if expected_type == "array" and not isinstance(value, (list, tuple)):
            raise TypeError(f"Invalid {direction} for {skill_id}.{key}: expected array")
        if expected_type == "object" and not isinstance(value, dict):
            raise TypeError(f"Invalid {direction} for {skill_id}.{key}: expected object")
        if expected_type == "number" and not isinstance(value, (int, float)):
            raise TypeError(f"Invalid {direction} for {skill_id}.{key}: expected number")
        if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise TypeError(f"Invalid {direction} for {skill_id}.{key}: expected integer")
        if expected_type == "boolean" and not isinstance(value, bool):
            raise TypeError(f"Invalid {direction} for {skill_id}.{key}: expected boolean")
