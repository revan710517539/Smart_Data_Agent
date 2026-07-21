from __future__ import annotations

import json
import re
from typing import Any

from backend.platform.security.sql_validation import validate_read_only_sql_candidate
from backend.platform.settings import call_model_text_completion, resolve_model_for_application
from backend.platform.crawler_engine.policy import validate_repair_candidate

from .sandbox import RestrictedRowTransformSandbox


class ModelAcquisitionRepairGenerator:
    """Generate a reviewed candidate only; never changes the active script."""

    application_module = "crawler_exception_optimization"

    def __init__(self, system_config_store: Any, transform_sandbox: RestrictedRowTransformSandbox) -> None:
        self.system_config_store = system_config_store
        self.transform_sandbox = transform_sandbox

    def generate(
        self,
        tenant_id: str,
        failed_version: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> dict[str, Any] | None:
        runtime = str(failed_version.get("runtime") or "").strip()
        model = resolve_model_for_application(
            self.system_config_store,
            tenant_id,
            self.application_module,
            reveal_secret=True,
        )
        if not model:
            return {
                "candidate_source_code": None,
                "model_call": {
                    "status": "skipped",
                    "error_code": "model_application_module_not_ready",
                    "model_id": self.application_module,
                    "prompt_template_id": "crawler.repair.v1",
                    "routing_key": self.application_module,
                },
            }
        source_code = str(failed_version.get("source_code") or "")
        prompt = _repair_prompt(runtime, source_code, diagnosis)
        completion = call_model_text_completion(model, prompt, max_tokens=1600)
        audit = {
            key: completion.get(key)
            for key in (
                "status",
                "error_code",
                "request_hash",
                "response_hash",
                "latency_ms",
                "input_tokens",
                "output_tokens",
                "usage_source",
                "model_id",
                "used_model",
            )
            if completion.get(key) not in (None, "")
        }
        audit["prompt_template_id"] = "crawler.repair.v1" if runtime == "browser" else "acquisition.repair.v1"
        audit["routing_key"] = self.application_module
        if completion.get("status") != "connected":
            return {"candidate_source_code": None, "model_call": audit}
        candidate = _extract_candidate(str(completion.get("response_text") or ""))
        validated = _validate_candidate(runtime, source_code, candidate, self.transform_sandbox)
        return {"candidate_source_code": validated, "model_call": audit}


def _repair_prompt(runtime: str, source_code: str, diagnosis: dict[str, Any]) -> str:
    safe_diagnosis = {
        key: diagnosis.get(key)
        for key in ("error_code", "recommended_action", "quality_summary")
        if diagnosis.get(key) not in (None, "", {})
    }
    return (
        "你是数据采集脚本修复器。只能返回一个 JSON 对象，格式为 "
        '{"candidate_source_code":"修复后的完整源码"}。不得返回解释、凭证、密钥或 Markdown。\n'
        f"运行时：{runtime}\n"
        f"脱敏诊断：{json.dumps(safe_diagnosis, ensure_ascii=False, sort_keys=True)}\n"
        "约束：保留租户和机构过滤；SQL 只能是一个只读 SELECT/WITH；Python 只能使用既有 transform_rows(rows, context) 沙箱；"
        "HTTP 配置必须是 JSON 对象；browser 运行时只能调整选择器、等待、导航和下载参数，禁止改变 SQL、输出 Schema、主题或指标定义。"
        "候选只进入人工四眼评审，不会自动应用。\n"
        f"失败版本源码：\n{source_code[:30000]}"
    )


def _extract_candidate(response_text: str) -> str:
    text = response_text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("llm_repair_response_must_be_json") from exc
    if not isinstance(payload, dict) or set(payload) != {"candidate_source_code"}:
        raise ValueError("llm_repair_response_schema_invalid")
    candidate = str(payload.get("candidate_source_code") or "").strip()
    if not candidate or len(candidate) > 100_000:
        raise ValueError("llm_repair_candidate_size_invalid")
    return candidate


def _validate_candidate(
    runtime: str,
    original: str,
    candidate: str,
    transform_sandbox: RestrictedRowTransformSandbox,
) -> str:
    if runtime == "sql":
        return validate_read_only_sql_candidate(candidate)
    if runtime == "browser":
        return validate_repair_candidate(original, candidate)
    if runtime not in {"http", "python"}:
        raise ValueError("llm_repair_runtime_unsupported")
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError("llm_repair_candidate_config_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("query"), dict):
        raise ValueError("llm_repair_candidate_query_required")
    if set(payload) - {"query", "transform_code"}:
        raise ValueError("llm_repair_candidate_unknown_keys")
    if runtime == "python":
        transform_sandbox.validate(str(payload.get("transform_code") or ""))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
