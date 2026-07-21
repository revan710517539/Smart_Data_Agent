from __future__ import annotations

import itertools
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from ...diagnostics import stable_json_hash


BUSINESS_SANDBOX_PROFILE_ID = "qifu_focuspro_sios.business_sandbox.v1"

_API_PATHS = {
    "enum": "/sandbox/detail/queryEnum",
    "section_types": "/sandbox/business/querySubItemType",
    "section": "/sandbox/business/querySubItem",
    "trend": "/sandbox/business/queryTrendChart",
    "detail_section_types": "/sandbox/detail/querySubItemType",
    "detail_section": "/sandbox/detail/querySubItem",
    "detail_trend": "/sandbox/detail/queryTrendChart",
    "business_download": "/sandbox/business/downloadReport",
    "detail_download": "/sandbox/detail/downloadReport",
}


@dataclass(frozen=True)
class BusinessSandboxCollection:
    rows: list[dict[str, Any]]
    metadata: dict[str, Any]


class BusinessSandboxAPIError(RuntimeError):
    def __init__(self, path: str, code: str, message: str) -> None:
        super().__init__(f"{path}:{code}")
        self.path = path
        self.code = code
        self.message = message


@dataclass
class _BusinessSandboxAPIClient:
    page: Any
    api_context: Any
    api_base: str
    request_delay_min_ms: int
    request_delay_max_ms: int
    max_rate_limit_retries: int
    batch_concurrency: int

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        for attempt in range(self.max_rate_limit_retries + 1):
            delay_ms = random.SystemRandom().randint(
                self.request_delay_min_ms,
                self.request_delay_max_ms,
            )
            if delay_ms:
                self.page.wait_for_timeout(delay_ms)
            try:
                return _post(self.api_context, self.api_base, path, payload)
            except BusinessSandboxAPIError as exc:
                if exc.code != "BBTL5022" or attempt >= self.max_rate_limit_retries:
                    raise
                self.page.wait_for_timeout(min(5_000 * (2**attempt), 30_000))
        raise RuntimeError("business_sandbox_rate_limit_retry_exhausted")

    def post_many(self, path: str, payloads: list[dict[str, Any]]) -> list[Any]:
        if not payloads:
            return []
        if self.batch_concurrency <= 1 or len(payloads) == 1:
            return [self.post(path, payload) for payload in payloads]
        return _post_many(
            self.api_context,
            self.api_base,
            path,
            payloads,
            concurrency=self.batch_concurrency,
            request_delay_min_ms=self.request_delay_min_ms,
            request_delay_max_ms=self.request_delay_max_ms,
            max_rate_limit_retries=self.max_rate_limit_retries,
        )


def collect_business_sandbox(page: Any, step: dict[str, Any]) -> BusinessSandboxCollection:
    """Collect every registered business-sandbox section and trend series.

    Requests run inside the authenticated page so cookies and access tokens are
    never copied into Python. The default traversal captures the page's current
    default state: total organization, first/default product, and monthly data.
    ``cartesian`` and ``independent`` remain available for explicit bulk jobs.
    """

    api_context = _business_api_context(
        page,
        timeout_ms=_positive_int(step.get("app_module_wait_ms"), 60_000, 1_000, 180_000),
    )
    api_base = _resolve_api_base(api_context, step.get("api_base") or "app-module:50826")
    fixed_delay = step.get("request_delay_ms")
    delay_min = _positive_int(
        fixed_delay if fixed_delay is not None else step.get("request_delay_min_ms"),
        250,
        0,
        10_000,
    )
    delay_max = _positive_int(
        fixed_delay if fixed_delay is not None else step.get("request_delay_max_ms"),
        500,
        0,
        10_000,
    )
    if delay_max < delay_min:
        raise ValueError("business_sandbox_request_delay_range_invalid")
    client = _BusinessSandboxAPIClient(
        page=page,
        api_context=api_context,
        api_base=api_base,
        request_delay_min_ms=delay_min,
        request_delay_max_ms=delay_max,
        max_rate_limit_retries=_positive_int(step.get("max_rate_limit_retries"), 3, 0, 10),
        batch_concurrency=_positive_int(step.get("batch_concurrency"), 1, 1, 32),
    )
    enum_data = _mapping(client.post(_API_PATHS["enum"], {}), "business_sandbox_enum_invalid")
    rows = _enum_rows(enum_data)
    labels = _enum_labels(enum_data)
    combinations = _filter_combinations(enum_data, step)
    max_combinations = _positive_int(step.get("max_combinations"), 2_000, 1, 50_000)
    if len(combinations) > max_combinations:
        raise RuntimeError(
            f"business_sandbox_filter_combinations_exceed_limit:{len(combinations)}>{max_combinations}"
        )

    checkpoint = _CollectionCheckpoint.from_step(
        step,
        signature=stable_json_hash(
            {
                "profile": BUSINESS_SANDBOX_PROFILE_ID,
                "collection_schema": 3,
                "run_key": str(step.get("checkpoint_run_key") or ""),
                "combinations": combinations,
            }
        ),
        total_combinations=len(combinations),
        initial_rows=rows,
    )
    resume_offset = 0
    if checkpoint is not None:
        rows, resume_offset = checkpoint.load_or_initialize()

    batch_size = _positive_int(step.get("batch_size"), 16, 1, 200)
    if resume_offset >= len(combinations):
        if not any(row.get("record_type") in {"section_summary", "section_metric"} for row in rows):
            raise RuntimeError("business_sandbox_metrics_empty")
        if not any(row.get("record_type") == "detail_metric" for row in rows):
            raise RuntimeError("business_sandbox_detail_metrics_empty")
        return BusinessSandboxCollection(
            rows=rows,
            metadata=_collection_metadata(
                rows=rows,
                step=step,
                api_base=api_base,
                combination_count=len(combinations),
                request_delay_min_ms=client.request_delay_min_ms,
                request_delay_max_ms=client.request_delay_max_ms,
                batch_size=batch_size,
                batch_concurrency=client.batch_concurrency,
                resume_offset=resume_offset,
                checkpoint_enabled=True,
            ),
        )

    sections_by_product: dict[str, list[dict[str, str]]] = {}
    detail_sections_by_product: dict[str, list[dict[str, Any]]] = {}
    for product_code in dict.fromkeys(str(item["productCode"]) for item in combinations):
        section_data = _mapping(
            client.post(_API_PATHS["section_types"], {"productCode": product_code}),
            "business_sandbox_section_types_invalid",
        )
        sections = _section_types(section_data.get("subItemTypeList"))
        if not sections:
            raise RuntimeError(f"business_sandbox_sections_empty:{product_code}")
        sections_by_product[product_code] = sections
        detail_section_data = _mapping(
            client.post(_API_PATHS["detail_section_types"], {"productCode": product_code}),
            "business_sandbox_detail_section_types_invalid",
        )
        detail_sections = _detail_leaf_sections(detail_section_data.get("subItemTypeList"))
        if not detail_sections:
            raise RuntimeError(f"business_sandbox_detail_sections_empty:{product_code}")
        detail_sections_by_product[product_code] = detail_sections

    for offset in range(resume_offset, len(combinations), batch_size):
        batch = combinations[offset : offset + batch_size]
        batch_rows: list[dict[str, Any]] = []
        section_requests: list[tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]]] = []
        for batch_index, filters in enumerate(batch, start=offset + 1):
            context = _filter_context(batch_index, filters, labels)
            sections = sections_by_product[str(filters["productCode"])]
            for section in sections:
                section_requests.append(
                    (
                        context,
                        filters,
                        section,
                        {**filters, "subItemType": section["code"]},
                    )
                )
        section_results = client.post_many(
            _API_PATHS["section"],
            [request[3] for request in section_requests],
        )
        trend_requests: list[tuple[dict[str, Any], str, str, str, dict[str, Any]]] = []
        for request, raw_result in zip(section_requests, section_results, strict=True):
            context, filters, section, _payload = request
            section_code = section["code"]
            section_name = section["name"]
            result = _mapping(
                raw_result,
                f"business_sandbox_section_invalid:{section_code}",
            )
            title_items = _mapping_list(result.get("titleItem"))
            content_items = _mapping_list(result.get("contentItem"))
            batch_rows.extend(
                _metric_rows(
                    context,
                    title_items,
                    record_type="section_summary",
                    section_code=section_code,
                    section_name=section_name,
                )
            )
            batch_rows.extend(
                _metric_rows(
                    context,
                    content_items,
                    record_type="section_metric",
                    section_code=section_code,
                    section_name=section_name,
                )
            )
            if section_code == "PERFORMANCE_TRACKING" or bool(step.get("collect_all_trends")):
                for item_type in _metric_types(content_items):
                    trend_requests.append(
                        (
                            context,
                            section_code,
                            section_name,
                            item_type,
                            {**filters, "itemType": item_type},
                        )
                    )
        trend_results = client.post_many(
            _API_PATHS["trend"],
            [request[4] for request in trend_requests],
        )
        for request, raw_trend in zip(trend_requests, trend_results, strict=True):
            context, section_code, section_name, item_type, _payload = request
            trend = _mapping(
                raw_trend,
                f"business_sandbox_trend_invalid:{item_type}",
            )
            batch_rows.extend(
                _trend_rows(
                    context,
                    trend,
                    section_code=section_code,
                    section_name=section_name,
                    item_type=item_type,
                )
            )
        detail_requests: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for batch_index, filters in enumerate(batch, start=offset + 1):
            context = _filter_context(batch_index, filters, labels)
            for section in detail_sections_by_product[str(filters["productCode"])]:
                metrics = [
                    {**metric, "checked": True}
                    for metric in _mapping_list(section.get("metrics"))
                ]
                payload = {
                    "productCode": str(filters["productCode"]),
                    "dateRange": str(filters.get("dateRange") or "MONTH"),
                    "subItemType": str(section["code"]),
                    "metrics": metrics,
                    "filter": {},
                    "orgCode": _detail_org_codes(filters),
                }
                if filters.get("dateRecord"):
                    payload["dateRecord"] = str(filters["dateRecord"])
                detail_requests.append((context, filters, section, payload))
        detail_results = client.post_many(
            _API_PATHS["detail_section"],
            [request[3] for request in detail_requests],
        )
        detail_trend_requests: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, dict[str, Any]]] = []
        for request, raw_result in zip(detail_requests, detail_results, strict=True):
            context, filters, section, _payload = request
            result = _mapping(
                raw_result,
                f"business_sandbox_detail_section_invalid:{section['code']}",
            )
            batch_rows.extend(
                _detail_metric_rows(
                    context,
                    result,
                    section_code=str(section["code"]),
                    section_name=str(section["name"]),
                    date_range=str(filters.get("dateRange") or "MONTH"),
                    requested_org_codes=_detail_org_codes(filters),
                    metric_schema=_mapping_list(section.get("metrics")),
                )
            )
            if bool(step.get("collect_detail_trends", True)):
                metric_types = [
                    str(metric.get("type") or "").strip()
                    for metric in _mapping_list(section.get("metrics"))
                    if str(metric.get("type") or "").strip()
                ]
                if not bool(step.get("collect_all_trends")):
                    metric_types = metric_types[:1]
                for item_type in metric_types:
                    org_codes = _detail_org_codes(filters) or ["000"]
                    trend_payload = {
                        "orgCode": org_codes,
                        "productCode": str(filters["productCode"]),
                        "dateRange": str(filters.get("dateRange") or "MONTH"),
                        "itemType": item_type,
                    }
                    if filters.get("dateRecord"):
                        trend_payload["dateRecord"] = str(filters["dateRecord"])
                    detail_trend_requests.append((context, filters, section, item_type, trend_payload))
        detail_trend_results = client.post_many(
            _API_PATHS["detail_trend"],
            [request[4] for request in detail_trend_requests],
        )
        for request, raw_trend in zip(detail_trend_requests, detail_trend_results, strict=True):
            context, _filters, section, item_type, _payload = request
            batch_rows.extend(
                _detail_trend_rows(
                    context,
                    _mapping(raw_trend, f"business_sandbox_detail_trend_invalid:{item_type}"),
                    section_code=str(section["code"]),
                    section_name=str(section["name"]),
                    item_type=item_type,
                )
            )
        rows.extend(batch_rows)
        if checkpoint is not None:
            checkpoint.append(batch_rows, next_offset=offset + len(batch))

    if not any(row.get("record_type") in {"section_summary", "section_metric"} for row in rows):
        raise RuntimeError("business_sandbox_metrics_empty")
    if not any(row.get("record_type") == "detail_metric" for row in rows):
        raise RuntimeError("business_sandbox_detail_metrics_empty")

    metadata = _collection_metadata(
        rows=rows,
        step=step,
        api_base=api_base,
        combination_count=len(combinations),
        request_delay_min_ms=client.request_delay_min_ms,
        request_delay_max_ms=client.request_delay_max_ms,
        batch_size=batch_size,
        batch_concurrency=client.batch_concurrency,
        resume_offset=resume_offset,
        checkpoint_enabled=checkpoint is not None,
    )
    return BusinessSandboxCollection(rows=rows, metadata=metadata)


def _collection_metadata(
    *,
    rows: list[dict[str, Any]],
    step: dict[str, Any],
    api_base: str,
    combination_count: int,
    request_delay_min_ms: int,
    request_delay_max_ms: int,
    batch_size: int,
    batch_concurrency: int,
    resume_offset: int,
    checkpoint_enabled: bool,
) -> dict[str, Any]:
    section_count = len(
        {
            (str(row.get("filter_hash") or ""), str(row.get("section_code") or ""))
            for row in rows
            if row.get("record_type") in {"section_summary", "section_metric"}
            and row.get("section_code")
        }
    )
    trend_request_count = len(
        {
            (str(row.get("filter_hash") or ""), str(row.get("metric_type") or ""))
            for row in rows
            if row.get("record_type") == "trend_point" and row.get("metric_type")
        }
    )
    detail_section_count = len(
        {
            (str(row.get("filter_hash") or ""), str(row.get("section_code") or ""))
            for row in rows
            if row.get("record_type") == "detail_metric" and row.get("section_code")
        }
    )
    detail_trend_request_count = len(
        {
            (str(row.get("filter_hash") or ""), str(row.get("section_code") or ""), str(row.get("metric_type") or ""))
            for row in rows
            if row.get("record_type") == "detail_trend_point" and row.get("metric_type")
        }
    )
    return {
        "profile": BUSINESS_SANDBOX_PROFILE_ID,
        "page_name": "经营沙盘与经营明细",
        "api_base": api_base,
        "traversal_mode": str(step.get("traversal_mode") or "current"),
        "combination_count": combination_count,
        "section_count": section_count,
        "trend_request_count": trend_request_count,
        "detail_section_count": detail_section_count,
        "detail_trend_request_count": detail_trend_request_count,
        "row_count": len(rows),
        "request_delay_min_ms": request_delay_min_ms,
        "request_delay_max_ms": request_delay_max_ms,
        "batch_size": batch_size,
        "batch_concurrency": batch_concurrency,
        "resumed_from_combination": resume_offset,
        "checkpoint_enabled": checkpoint_enabled,
        "filters": ["secondOrgCode", "thirdOrgCode", "productCode", "dateRange", "dateRecord"],
        "statistical_dates": len(_string_list(step.get("statistical_dates") or [])),
    }


@dataclass
class _CollectionCheckpoint:
    rows_path: Path
    state_path: Path
    signature: str
    total_combinations: int
    initial_rows: list[dict[str, Any]]

    @classmethod
    def from_step(
        cls,
        step: dict[str, Any],
        *,
        signature: str,
        total_combinations: int,
        initial_rows: list[dict[str, Any]],
    ) -> _CollectionCheckpoint | None:
        source = str(step.get("checkpoint_path") or "").strip()
        if not source:
            return None
        rows_path = Path(source).expanduser().resolve()
        if rows_path.suffix.lower() != ".jsonl":
            raise ValueError("business_sandbox_checkpoint_must_be_jsonl")
        return cls(
            rows_path=rows_path,
            state_path=rows_path.with_suffix(".state.json"),
            signature=signature,
            total_combinations=total_combinations,
            initial_rows=initial_rows,
        )

    def load_or_initialize(self) -> tuple[list[dict[str, Any]], int]:
        state = self._read_state()
        if (
            state.get("signature") == self.signature
            and int(state.get("total_combinations") or 0) == self.total_combinations
            and self.rows_path.is_file()
        ):
            rows = self._read_rows()
            next_offset = max(0, min(int(state.get("next_offset") or 0), self.total_combinations))
            return rows, next_offset
        self.rows_path.parent.mkdir(parents=True, exist_ok=True)
        with self.rows_path.open("w", encoding="utf-8") as handle:
            for row in self.initial_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        self._write_state(next_offset=0)
        return [dict(row) for row in self.initial_rows], 0

    def append(self, rows: list[dict[str, Any]], *, next_offset: int) -> None:
        with self.rows_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        self._write_state(next_offset=next_offset)

    def _read_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with self.rows_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise RuntimeError("business_sandbox_checkpoint_row_invalid")
                rows.append(value)
        return rows

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write_state(self, *, next_offset: int) -> None:
        state = {
            "signature": self.signature,
            "total_combinations": self.total_combinations,
            "next_offset": next_offset,
            "complete": next_offset >= self.total_combinations,
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)


def _post(api_context: Any, api_base: str, path: str, payload: dict[str, Any]) -> Any:
    result = api_context.evaluate(
        """
        async ({ apiBase, path, payload }) => {
          if (apiBase.startsWith("app-module:")) {
            const moduleId = Number(apiBase.split(":", 2)[1]);
            const chunks = window.webpackChunk_focuspro_h5_kop;
            if (!Array.isArray(chunks) || !Number.isInteger(moduleId)) {
              throw new Error("business_sandbox_app_module_unavailable");
            }
            let webpackRequire;
            const runtimeChunkId = (Date.now() % 1000000000) + 1000000000;
            chunks.push([[runtimeChunkId], {}, (require) => { webpackRequire = require; }]);
            if (!webpackRequire) throw new Error("business_sandbox_webpack_runtime_unavailable");
            const api = webpackRequire(moduleId);
            const methods = {
              "/sandbox/detail/queryEnum": "queryEnum",
              "/sandbox/business/querySubItemType": "queryBusinessSubItemType",
              "/sandbox/business/querySubItem": "queryBusinessSubItem",
              "/sandbox/business/queryTrendChart": "queryBusinessTrendChart",
              "/sandbox/detail/querySubItemType": "queryDetailSubItemType",
              "/sandbox/detail/querySubItem": "queryDetailSubItem",
              "/sandbox/detail/queryTrendChart": "queryDetailTrendChart",
              "/sandbox/business/downloadReport": "downloadBusinessReport",
              "/sandbox/detail/downloadReport": "downloadDetailReport",
            };
            const method = methods[path];
            if (!method || !api || typeof api[method] !== "function") {
              throw new Error(`business_sandbox_api_method_unavailable:${path}`);
            }
            try {
              const data = method === "queryEnum" ? await api[method]() : await api[method](payload);
              return { __crawlerApiResult: true, ok: true, data };
            } catch (error) {
              const code = String((error && error.code) || "API_ERROR").slice(0, 120);
              const message = String(
                (error && (error.msg || error.err || error.message)) || "request_failed"
              ).slice(0, 500);
              return { __crawlerApiResult: true, ok: false, code, message };
            }
          }
          const read = (key) => localStorage.getItem(key) || sessionStorage.getItem(key) || "";
          const token = read("token");
          const shiroSid = read("shiroSid");
          const headers = { Accept: "application/json", "Content-Type": "application/json" };
          if (token) headers.Authorization = token;
          else if (shiroSid) headers.ShiroSid = shiroSid;
          const bagClass = Number(read("bagClass") || 1);
          const response = await fetch(`${apiBase}${path}`, {
            method: "POST",
            credentials: "include",
            headers,
            body: JSON.stringify({ businessType: bagClass, ...payload }),
          });
          if (!response.ok) throw new Error(`api_http_${response.status}:${path}`);
          const result = await response.json();
          if (result && (result.code === "IOPS100" || result.flag === "S")) return result.data ?? true;
          if (result && (result.code || result.msg)) {
            throw new Error(`api_business_error:${path}:${result.code || "UNKNOWN"}`);
          }
          return result && Object.prototype.hasOwnProperty.call(result, "data") ? result.data : result;
        }
        """,
        {"apiBase": api_base, "path": path, "payload": payload},
    )
    if isinstance(result, dict) and result.get("__crawlerApiResult") is True:
        if result.get("ok") is True:
            return result.get("data")
        raise BusinessSandboxAPIError(
            path,
            str(result.get("code") or "API_ERROR"),
            str(result.get("message") or "request_failed"),
        )
    return result


def _post_many(
    api_context: Any,
    api_base: str,
    path: str,
    payloads: list[dict[str, Any]],
    *,
    concurrency: int,
    request_delay_min_ms: int,
    request_delay_max_ms: int,
    max_rate_limit_retries: int,
) -> list[Any]:
    results = api_context.evaluate(
        """
        async ({ apiBase, path, payloads, concurrency, requestDelayMinMs, requestDelayMaxMs, maxRetries }) => {
          let call;
          if (apiBase.startsWith("app-module:")) {
            const moduleId = Number(apiBase.split(":", 2)[1]);
            const chunks = window.webpackChunk_focuspro_h5_kop;
            if (!Array.isArray(chunks) || !Number.isInteger(moduleId)) {
              throw new Error("business_sandbox_app_module_unavailable");
            }
            let webpackRequire;
            const runtimeChunkId = (Date.now() % 1000000000) + 1000000000;
            chunks.push([[runtimeChunkId], {}, (require) => { webpackRequire = require; }]);
            if (!webpackRequire) throw new Error("business_sandbox_webpack_runtime_unavailable");
            const api = webpackRequire(moduleId);
            const methods = {
              "/sandbox/detail/queryEnum": "queryEnum",
              "/sandbox/business/querySubItemType": "queryBusinessSubItemType",
              "/sandbox/business/querySubItem": "queryBusinessSubItem",
              "/sandbox/business/queryTrendChart": "queryBusinessTrendChart",
              "/sandbox/detail/querySubItemType": "queryDetailSubItemType",
              "/sandbox/detail/querySubItem": "queryDetailSubItem",
              "/sandbox/detail/queryTrendChart": "queryDetailTrendChart",
              "/sandbox/business/downloadReport": "downloadBusinessReport",
              "/sandbox/detail/downloadReport": "downloadDetailReport",
            };
            const method = methods[path];
            if (!method || !api || typeof api[method] !== "function") {
              throw new Error(`business_sandbox_api_method_unavailable:${path}`);
            }
            call = (payload) => method === "queryEnum" ? api[method]() : api[method](payload);
          } else {
            const read = (key) => localStorage.getItem(key) || sessionStorage.getItem(key) || "";
            const token = read("token");
            const shiroSid = read("shiroSid");
            const headers = { Accept: "application/json", "Content-Type": "application/json" };
            if (token) headers.Authorization = token;
            else if (shiroSid) headers.ShiroSid = shiroSid;
            const bagClass = Number(read("bagClass") || 1);
            call = async (payload) => {
              const response = await fetch(`${apiBase}${path}`, {
                method: "POST",
                credentials: "include",
                headers,
                body: JSON.stringify({ businessType: bagClass, ...payload }),
              });
              if (!response.ok) throw new Error(`api_http_${response.status}:${path}`);
              const result = await response.json();
              if (result && (result.code === "IOPS100" || result.flag === "S")) return result.data ?? true;
              if (result && (result.code || result.msg)) {
                const error = new Error(result.msg || "api_business_error");
                error.code = result.code || "UNKNOWN";
                throw error;
              }
              return result && Object.prototype.hasOwnProperty.call(result, "data") ? result.data : result;
            };
          }
          const output = new Array(payloads.length);
          let cursor = 0;
          let blockedUntil = 0;
          let nextAllowedAt = 0;
          const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
          const worker = async () => {
            while (true) {
              const index = cursor++;
              if (index >= payloads.length) return;
              for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
                const jitter = requestDelayMinMs + Math.floor(
                  Math.random() * (requestDelayMaxMs - requestDelayMinMs + 1)
                );
                const scheduledAt = Math.max(Date.now(), blockedUntil, nextAllowedAt);
                nextAllowedAt = scheduledAt + jitter;
                const gateDelay = scheduledAt - Date.now();
                if (gateDelay > 0) await pause(gateDelay);
                try {
                  output[index] = { ok: true, data: await call(payloads[index]) };
                  break;
                } catch (error) {
                  const code = String((error && error.code) || "API_ERROR").slice(0, 120);
                  const message = String(
                    (error && (error.msg || error.err || error.message)) || "request_failed"
                  ).slice(0, 500);
                  if (code !== "BBTL5022" || attempt >= maxRetries) {
                    output[index] = { ok: false, code, message };
                    break;
                  }
                  const cooldown = Math.min(15000 * (2 ** attempt), 120000);
                  blockedUntil = Math.max(blockedUntil, Date.now() + cooldown);
                  await pause(cooldown);
                }
              }
            }
          };
          await Promise.all(
            Array.from({ length: Math.min(concurrency, payloads.length) }, () => worker())
          );
          return output;
        }
        """,
        {
            "apiBase": api_base,
            "path": path,
            "payloads": payloads,
            "concurrency": concurrency,
            "requestDelayMinMs": request_delay_min_ms,
            "requestDelayMaxMs": request_delay_max_ms,
            "maxRetries": max_rate_limit_retries,
        },
    )
    if not isinstance(results, list) or len(results) != len(payloads):
        raise RuntimeError(f"business_sandbox_batch_result_invalid:{path}")
    values: list[Any] = []
    for result in results:
        if not isinstance(result, dict) or result.get("ok") is not True:
            payload = result if isinstance(result, dict) else {}
            raise BusinessSandboxAPIError(
                path,
                str(payload.get("code") or "API_ERROR"),
                str(payload.get("message") or "request_failed"),
            )
        values.append(result.get("data"))
    return values


def _filter_combinations(enum_data: dict[str, Any], step: dict[str, Any]) -> list[dict[str, Any]]:
    products = _options(enum_data.get("productList"))
    if not products:
        raise RuntimeError("business_sandbox_product_options_empty")
    orgs = _org_variants(enum_data.get("orgCodeList"), include_totals=bool(step.get("include_totals", True)))
    date_ranges = _options(enum_data.get("dateRange"))
    product_variants = [{"productCode": item["code"]} for item in products]
    date_range_variants = [{"dateRange": item["code"]} for item in date_ranges] or [{"dateRange": "MONTH"}]
    dates = _string_list(step.get("statistical_dates") or [])
    date_variants = ([{}] if bool(step.get("include_current_date", True)) else []) + [
        {"dateRecord": item} for item in dates
    ]
    date_variants = date_variants or [{}]
    dimensions = [orgs, product_variants, date_range_variants, date_variants]
    mode = str(step.get("traversal_mode") or "current").strip().lower()
    if mode == "current":
        monthly_range = next(
            (item for item in date_range_variants if str(item.get("dateRange") or "").upper() == "MONTH"),
            date_range_variants[0],
        )
        explicit_date = {"dateRecord": dates[0]} if dates else {}
        return [
            _merge_filters(
                (
                    orgs[0],
                    product_variants[0],
                    monthly_range,
                    explicit_date,
                )
            )
        ]
    if mode == "independent":
        baseline = _merge_filters(dimension[0] for dimension in dimensions)
        candidates = [baseline]
        for dimension in dimensions:
            candidates.extend({**baseline, **variant} for variant in dimension)
        return _deduplicate_filters(candidates)
    if mode != "cartesian":
        raise ValueError(f"business_sandbox_traversal_mode_unsupported:{mode}")
    return _deduplicate_filters(_merge_filters(items) for items in itertools.product(*dimensions))


def _org_variants(value: Any, *, include_totals: bool) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [{}] if include_totals else []
    for parent in _mapping_list(value):
        second = str(parent.get("code") or parent.get("value") or "").strip()
        if not second:
            continue
        variants.append({"secondOrgCode": second})
        for child in _mapping_list(parent.get("children")):
            third = str(child.get("code") or child.get("value") or "").strip()
            if third:
                variants.append({"secondOrgCode": second, "thirdOrgCode": third})
    return _deduplicate_filters(variants or [{}])


def _section_types(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            code = str(item.get("code") or item.get("value") or item.get("type") or "").strip()
            name = str(item.get("name") or item.get("label") or code).strip()
        else:
            code = str(item or "").strip()
            name = code
        if code:
            result.append({"code": code, "name": name})
    return list({item["code"]: item for item in result}.values())


def _detail_leaf_sections(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(items: Any) -> None:
        for item in _mapping_list(items):
            children = _mapping_list(item.get("children"))
            if children:
                visit(children)
                continue
            code = str(item.get("code") or item.get("value") or "").strip()
            if not code:
                continue
            result.append(
                {
                    "code": code,
                    "name": str(item.get("name") or item.get("label") or code).strip(),
                    "metrics": _mapping_list(item.get("metrics")),
                }
            )

    visit(value)
    return list({str(item["code"]): item for item in result}.values())


def _detail_org_codes(filters: dict[str, Any]) -> list[str]:
    third = str(filters.get("thirdOrgCode") or "").strip()
    second = str(filters.get("secondOrgCode") or "").strip()
    return [third or second] if third or second else []


_DETAIL_PERIODS = {
    "7DAY": ("cur7day", "last7day", "近7日", "上个7日"),
    "30DAY": ("cur30day", "last30day", "近30日", "上个30日"),
    "WEEK": ("curWeek", "lastWeek", "本周", "上个周"),
    "MONTH": ("curMonth", "lastMonth", "本月", "上个月"),
    "QUARTER": ("curQuarter", "lastQuarter", "本季", "上个季"),
    "YEAR": ("curYear", "lastYear", "本年", ""),
    "ALL": ("value", "", "累计", ""),
}


def _detail_metric_rows(
    context: dict[str, Any],
    result: dict[str, Any],
    *,
    section_code: str,
    section_name: str,
    date_range: str,
    requested_org_codes: list[str],
    metric_schema: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_key, previous_key, current_label, previous_label = _DETAIL_PERIODS.get(
        date_range,
        _DETAIL_PERIODS["MONTH"],
    )
    allowed = set(requested_org_codes) if requested_org_codes else {"000", "ALL"}
    schema_order = {
        str(metric.get("type") or metric.get("code") or "").strip(): index
        for index, metric in enumerate(metric_schema)
        if str(metric.get("type") or metric.get("code") or "").strip()
    }
    rows: list[dict[str, Any]] = []
    for source_row in _mapping_list(result.get("rows")):
        dimension_code = str(source_row.get("dimension_code") or source_row.get("dimensionCode") or "").strip()
        if dimension_code not in allowed:
            continue
        dimension_name = "总行" if dimension_code in {"000", "ALL", ""} else (
            context.get("third_org_name") if dimension_code == context.get("third_org_code")
            else context.get("second_org_name") if dimension_code == context.get("second_org_code")
            else dimension_code
        )
        for index, metric in enumerate(_mapping_list(source_row.get("metrics_values")), start=1):
            metric_code = str(metric.get("type") or metric.get("code") or "").strip()
            current_value = metric.get(current_key)
            if current_value in (None, "") and current_key != "value":
                current_value = metric.get("value")
            rows.append(
                _row(
                    context,
                    crawl_page="经营明细",
                    record_type="detail_metric",
                    source_endpoint=_API_PATHS["detail_section"],
                    section_code=section_code,
                    section_name=section_name,
                    item_path=f"{section_name}/{index}",
                    metric_type=metric_code,
                    metric_name=metric.get("name") or metric_code,
                    metric_value=current_value,
                    metric_code=metric_code,
                    dimension_code=dimension_code,
                    dimension_name=dimension_name,
                    period_label=current_label,
                    comparison_label=previous_label,
                    comparison_value=metric.get(previous_key) if previous_key else "",
                    schema_order=schema_order.get(metric_code, len(schema_order) + index),
                    raw_value=metric,
                )
            )
    return rows


def _detail_trend_rows(
    context: dict[str, Any],
    trend: dict[str, Any],
    *,
    section_code: str,
    section_name: str,
    item_type: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    chart_map = trend.get("chartMap") if isinstance(trend.get("chartMap"), dict) else trend
    for series_code, series_value in chart_map.items():
        if not isinstance(series_value, dict):
            continue
        for point in _mapping_list(series_value.get("itemList") or series_value.get("data")):
            rows.append(
                _row(
                    context,
                    crawl_page="经营明细",
                    record_type="detail_trend_point",
                    source_endpoint=_API_PATHS["detail_trend"],
                    section_code=section_code,
                    section_name=section_name,
                    metric_type=item_type,
                    trend_series=series_code,
                    trend_date=point.get("dateRecord") or point.get("date") or point.get("name"),
                    trend_value=point.get("value"),
                    raw_value=point,
                )
            )
    return rows


def _metric_rows(
    context: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    record_type: str,
    section_code: str,
    section_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, item in _walk_items(items):
        rows.append(
            _row(
                context,
                record_type=record_type,
                source_endpoint=_API_PATHS["section"],
                section_code=section_code,
                section_name=section_name,
                item_path=path,
                metric_type=item.get("type") or item.get("code"),
                metric_name=item.get("name") or item.get("label") or item.get("type"),
                metric_value=item.get("value"),
                unit_name=item.get("unitName") or item.get("unit"),
                weekly_rate=item.get("weeklyRate"),
                monthly_rate=item.get("monthlyRate"),
                metric_label=item.get("label"),
                tips=item.get("tips"),
                raw_value=item,
            )
        )
    return rows


def _trend_rows(
    context: dict[str, Any],
    trend: dict[str, Any],
    *,
    section_code: str,
    section_name: str,
    item_type: str,
) -> list[dict[str, Any]]:
    chart_map = trend.get("chartMap") if isinstance(trend.get("chartMap"), dict) else trend
    rows: list[dict[str, Any]] = []
    for series_code, series_value in chart_map.items():
        if not isinstance(series_value, dict):
            continue
        points = _mapping_list(series_value.get("itemList") or series_value.get("data"))
        for point in points:
            trend_date = point.get("dateRecord") or point.get("date") or point.get("name")
            trend_value = point.get("value")
            rows.append(
                _row(
                    context,
                    record_type="trend_point",
                    source_endpoint=_API_PATHS["trend"],
                    section_code=section_code,
                    section_name=section_name,
                    metric_type=item_type,
                    metric_name=series_value.get("itemName") or series_value.get("name") or series_code,
                    unit_name=series_value.get("unitName") or series_value.get("unit"),
                    trend_series=series_code,
                    trend_date=trend_date,
                    trend_value=trend_value,
                    metric_value=trend_value,
                    raw_value=point,
                )
            )
    return rows


def _metric_types(items: list[dict[str, Any]]) -> list[str]:
    values = [str(item.get("type") or "").strip() for _, item in _walk_items(items)]
    return list(dict.fromkeys(item for item in values if item))


def _walk_items(items: list[dict[str, Any]], prefix: str = "") -> Iterable[tuple[str, dict[str, Any]]]:
    for index, item in enumerate(items, start=1):
        path = f"{prefix}.{index}" if prefix else str(index)
        yield path, item
        children = _mapping_list(item.get("children"))
        if children:
            yield from _walk_items(children, path)


def _enum_rows(enum_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension, source in (
        ("productCode", "productList"),
        ("dateRange", "dateRange"),
    ):
        for item in _options(enum_data.get(source)):
            rows.append(
                _row(
                    {},
                    record_type="filter_option",
                    source_endpoint=_API_PATHS["enum"],
                    metric_type=dimension,
                    metric_name=item["name"],
                    metric_value=item["code"],
                    raw_value=item,
                )
            )
    for org in _mapping_list(enum_data.get("orgCodeList")):
        second_code = str(org.get("code") or org.get("value") or "").strip()
        rows.append(
            _row(
                {},
                record_type="filter_option",
                source_endpoint=_API_PATHS["enum"],
                metric_type="secondOrgCode",
                metric_name=org.get("name") or org.get("label"),
                metric_value=second_code,
                raw_value=org,
            )
        )
        for child in _mapping_list(org.get("children")):
            rows.append(
                _row(
                    {},
                    record_type="filter_option",
                    source_endpoint=_API_PATHS["enum"],
                    second_org_code=second_code,
                    metric_type="thirdOrgCode",
                    metric_name=child.get("name") or child.get("label"),
                    metric_value=child.get("code") or child.get("value"),
                    raw_value=child,
                )
            )
    return rows


def _enum_labels(enum_data: dict[str, Any]) -> dict[str, dict[str, str]]:
    labels = {
        "productCode": {item["code"]: item["name"] for item in _options(enum_data.get("productList"))},
        "dateRange": {item["code"]: item["name"] for item in _options(enum_data.get("dateRange"))},
        "secondOrgCode": {},
        "thirdOrgCode": {},
    }
    for parent in _mapping_list(enum_data.get("orgCodeList")):
        code = str(parent.get("code") or parent.get("value") or "").strip()
        if code:
            labels["secondOrgCode"][code] = str(parent.get("name") or parent.get("label") or code)
        for child in _mapping_list(parent.get("children")):
            child_code = str(child.get("code") or child.get("value") or "").strip()
            if child_code:
                labels["thirdOrgCode"][child_code] = str(child.get("name") or child.get("label") or child_code)
    return labels


def _filter_context(index: int, filters: dict[str, Any], labels: dict[str, dict[str, str]]) -> dict[str, Any]:
    return {
        "combination_index": index,
        "second_org_code": str(filters.get("secondOrgCode") or ""),
        "second_org_name": labels["secondOrgCode"].get(str(filters.get("secondOrgCode") or ""), "总行"),
        "third_org_code": str(filters.get("thirdOrgCode") or ""),
        "third_org_name": labels["thirdOrgCode"].get(str(filters.get("thirdOrgCode") or ""), "全部"),
        "product_code": str(filters.get("productCode") or ""),
        "product_name": labels["productCode"].get(str(filters.get("productCode") or ""), ""),
        "date_range": str(filters.get("dateRange") or ""),
        "date_range_name": labels["dateRange"].get(str(filters.get("dateRange") or ""), ""),
        "date_record": str(filters.get("dateRecord") or ""),
        "filter_hash": stable_json_hash(filters)[:16],
    }


def _row(context: dict[str, Any], **values: Any) -> dict[str, Any]:
    raw_value = values.pop("raw_value", None)
    return {
        "crawl_page": values.pop("crawl_page", "经营沙盘"),
        "combination_index": context.get("combination_index", ""),
        "filter_hash": context.get("filter_hash", ""),
        "second_org_code": context.get("second_org_code", ""),
        "second_org_name": context.get("second_org_name", ""),
        "third_org_code": context.get("third_org_code", ""),
        "third_org_name": context.get("third_org_name", ""),
        "product_code": context.get("product_code", ""),
        "product_name": context.get("product_name", ""),
        "date_range": context.get("date_range", ""),
        "date_range_name": context.get("date_range_name", ""),
        "date_record": context.get("date_record", ""),
        "section_code": values.pop("section_code", ""),
        "section_name": values.pop("section_name", ""),
        "record_type": values.pop("record_type", ""),
        "item_path": values.pop("item_path", ""),
        "metric_type": values.pop("metric_type", ""),
        "metric_code": values.pop("metric_code", ""),
        "metric_name": values.pop("metric_name", ""),
        "metric_value": values.pop("metric_value", ""),
        "dimension_code": values.pop("dimension_code", ""),
        "dimension_name": values.pop("dimension_name", ""),
        "period_label": values.pop("period_label", ""),
        "comparison_label": values.pop("comparison_label", ""),
        "comparison_value": values.pop("comparison_value", ""),
        "schema_order": values.pop("schema_order", ""),
        "unit_name": values.pop("unit_name", ""),
        "weekly_rate": values.pop("weekly_rate", ""),
        "monthly_rate": values.pop("monthly_rate", ""),
        "metric_label": values.pop("metric_label", ""),
        "tips": values.pop("tips", ""),
        "trend_series": values.pop("trend_series", ""),
        "trend_date": values.pop("trend_date", ""),
        "trend_value": values.pop("trend_value", ""),
        "source_endpoint": values.pop("source_endpoint", ""),
        "raw_json": json.dumps(raw_value if raw_value is not None else values, ensure_ascii=False, sort_keys=True),
    }


def _mapping(value: Any, error: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(error)
    return value


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _options(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _mapping_list(value):
        code = str(item.get("code") or item.get("value") or item.get("key") or "").strip()
        if code:
            result.append(
                {
                    "code": code,
                    "name": str(item.get("name") or item.get("label") or item.get("text") or code).strip(),
                }
            )
    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip())) if isinstance(value, list) else []


def _merge_filters(values: Iterable[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        result.update(value)
    return result


def _deduplicate_filters(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for value in values:
        normalized = {str(key): item for key, item in value.items() if item not in (None, "")}
        unique.setdefault(json.dumps(normalized, ensure_ascii=False, sort_keys=True), normalized)
    return list(unique.values())


def _positive_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(default if value in (None, "") else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("business_sandbox_integer_setting_invalid") from exc
    return max(minimum, min(parsed, maximum))


def _business_api_context(page: Any, *, timeout_ms: int) -> Any:
    """Locate the portal child frame that owns the FocusPro webpack runtime."""

    frames = getattr(page, "frames", None)
    if not isinstance(frames, list):
        return page
    attempts = max(1, timeout_ms // 500)
    for _ in range(attempts):
        for frame in list(getattr(page, "frames", []) or []):
            try:
                available = frame.evaluate(
                    "() => Array.isArray(window.webpackChunk_focuspro_h5_kop)"
                )
            except Exception:
                continue
            if available is True:
                return frame
        page.wait_for_timeout(500)
    frame_urls = [str(getattr(frame, "url", ""))[:300] for frame in list(getattr(page, "frames", []) or [])]
    raise RuntimeError(
        "business_sandbox_app_context_unavailable:"
        + stable_json_hash(frame_urls)[:16]
    )


def _resolve_api_base(page: Any, value: Any) -> str:
    source = str(value or "").strip()
    if source.startswith("app-module:"):
        module_id = source.split(":", 1)[1]
        if not module_id.isdigit():
            raise ValueError("business_sandbox_app_module_invalid")
        return source
    if source.startswith("/"):
        parsed = urlparse(str(page.url))
        return f"{parsed.scheme}://{parsed.netloc}{source.rstrip('/')}"
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("business_sandbox_api_base_invalid")
    return source.rstrip("/")


__all__ = [
    "BUSINESS_SANDBOX_PROFILE_ID",
    "BusinessSandboxAPIError",
    "BusinessSandboxCollection",
    "collect_business_sandbox",
]
