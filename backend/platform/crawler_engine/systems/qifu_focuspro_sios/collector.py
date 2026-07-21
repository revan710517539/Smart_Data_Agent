from __future__ import annotations

import itertools
import json
import random
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

from ...diagnostics import stable_json_hash


_API_PATHS = {
    "enum": "/lost/queryEnum",
    "staff": "/lost/queryStaffByName",
    "main": "/lost/queryMainItem",
    "sub": "/lost/querySubItem",
    "trend": "/lost/queryTrendChart",
    "lost": "/lost/queryLost",
    "lost_detail": "/lost/queryLostDetail",
    "node_types": "/lost/querySubItemType",
}


@dataclass(frozen=True)
class FunnelCollection:
    rows: list[dict[str, Any]]
    metadata: dict[str, Any]


class FunnelAPIError(RuntimeError):
    def __init__(self, path: str, code: str, message: str) -> None:
        super().__init__(f"{path}:{code}")
        self.path = path
        self.code = code
        self.message = message


@dataclass
class _FunnelAPIClient:
    page: Any
    api_base: str
    request_delay_ms: int
    request_delay_min_ms: int
    request_delay_max_ms: int
    max_rate_limit_retries: int

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        for attempt in range(self.max_rate_limit_retries + 1):
            delay = self.request_delay_ms or random.randint(
                self.request_delay_min_ms,
                self.request_delay_max_ms,
            )
            if delay:
                self.page.wait_for_timeout(delay)
            try:
                return _post(self.page, self.api_base, path, payload)
            except FunnelAPIError as exc:
                if exc.code != "BBTL5022" or attempt >= self.max_rate_limit_retries:
                    raise
                self.page.wait_for_timeout(min(5_000 * (2**attempt), 30_000))
        raise RuntimeError("funnel_rate_limit_retry_exhausted")


def collect_funnel_analysis(page: Any, step: dict[str, Any]) -> FunnelCollection:
    """Collect the authenticated funnel-analysis API surface into flat rows.

    The collector deliberately executes requests inside the authenticated page.
    Tokens and cookies therefore remain in the browser context and are never
    copied into Python diagnostics or result rows.
    """

    api_base = _resolve_api_base(page, step.get("api_base") or "/v2api")
    client = _FunnelAPIClient(
        page=page,
        api_base=api_base,
        request_delay_ms=_positive_int(step.get("request_delay_ms"), 0, 0, 10_000),
        request_delay_min_ms=_positive_int(step.get("request_delay_min_ms"), 250, 0, 10_000),
        request_delay_max_ms=_positive_int(step.get("request_delay_max_ms"), 500, 0, 10_000),
        max_rate_limit_retries=_positive_int(step.get("max_rate_limit_retries"), 6, 0, 10),
    )
    if client.request_delay_min_ms > client.request_delay_max_ms:
        raise ValueError("funnel_request_delay_range_invalid")
    enum_data = _mapping(client.post(_API_PATHS["enum"], {}), "funnel_enum_invalid")
    labels = _enum_labels(enum_data)
    rows = _enum_rows(enum_data)
    api_errors: list[dict[str, Any]] = []
    trend_item_limit = _positive_int(step.get("trend_item_limit"), 0, 0, 1_000)
    staff = _discover_staff(client, step.get("staff_search_terms") or [])
    rows.extend(_staff_rows(staff))

    combinations = _filter_combinations(enum_data, staff, step)
    max_combinations = _positive_int(step.get("max_combinations"), 2_000, 1, 50_000)
    if len(combinations) > max_combinations:
        raise RuntimeError(f"funnel_filter_combinations_exceed_limit:{len(combinations)}>{max_combinations}")

    lost_scenes = _string_list(step.get("lost_scenes") or ["COMPLETE", "APPROVAL", "PUTOUT"])
    for index, filters in enumerate(combinations, start=1):
        context = _filter_context(index, filters, labels, staff)
        product_code = str(filters.get("productCode") or "")
        node_data = _mapping(
            client.post(_API_PATHS["node_types"], {"productCode": product_code}),
            "funnel_node_types_invalid",
        )
        node_types = _node_types(node_data.get("subItemTypeList"))

        main = _mapping(client.post(_API_PATHS["main"], filters), "funnel_main_invalid")
        main_items = _mapping_list(main.get("mainItem"))
        rows.extend(_metric_rows(context, "main_item", _API_PATHS["main"], main_items))
        rows.extend(
            _trend_rows(
                client,
                context,
                filters,
                main_items,
                sub_item_type="MAIN_ITEMS",
                item_limit=trend_item_limit,
                api_errors=api_errors,
            )
        )

        for sub_item_type in node_types:
            payload = {**filters, "subItemType": sub_item_type}
            sub = _mapping(client.post(_API_PATHS["sub"], payload), "funnel_sub_invalid")
            title_items = _mapping_list(sub.get("titleItem"))
            content_items = _mapping_list(sub.get("contentItem"))
            rows.extend(
                _metric_rows(
                    context,
                    "sub_summary",
                    _API_PATHS["sub"],
                    title_items,
                    sub_item_type=sub_item_type,
                )
            )
            rows.extend(
                _metric_rows(
                    context,
                    "sub_item",
                    _API_PATHS["sub"],
                    content_items,
                    sub_item_type=sub_item_type,
                )
            )
            rows.extend(
                _trend_rows(
                    client,
                    context,
                    filters,
                    content_items,
                    sub_item_type=sub_item_type,
                    item_limit=trend_item_limit,
                    api_errors=api_errors,
                )
            )

        for lost_scene in lost_scenes:
            lost_payload = {**filters, "lostScene": lost_scene}
            lost = _mapping(client.post(_API_PATHS["lost"], lost_payload), "funnel_lost_invalid")
            total_rate = lost.get("totalLostRate")
            if total_rate not in (None, ""):
                rows.append(
                    _row(
                        context,
                        record_type="lost_total",
                        source_endpoint=_API_PATHS["lost"],
                        lost_scene=lost_scene,
                        metric_name="totalLostRate",
                        metric_value=total_rate,
                        raw_value={"totalLostRate": total_rate},
                    )
                )
            lost_items = _mapping_list(lost.get("lostList"))
            rows.extend(
                _metric_rows(
                    context,
                    "lost_item",
                    _API_PATHS["lost"],
                    lost_items,
                    lost_scene=lost_scene,
                )
            )
            for item in lost_items:
                lost_type = str(item.get("type") or "").strip()
                if not lost_type:
                    continue
                detail = _optional_mapping_post(
                    client,
                    _API_PATHS["lost_detail"],
                    {**filters, "lostType": lost_type},
                    context,
                    api_errors,
                    lost_scene=lost_scene,
                    lost_type=lost_type,
                )
                rows.extend(_lost_detail_rows(context, lost_scene, lost_type, detail))

    rows.extend(api_errors)

    metadata = {
        "profile": "qifu_focuspro_sios.funnel_analysis.v1",
        "api_base": api_base,
        "traversal_mode": str(step.get("traversal_mode") or "cartesian"),
        "combination_count": len(combinations),
        "row_count": len(rows),
        "api_error_count": len(api_errors),
        "request_delay_ms": client.request_delay_ms,
        "request_delay_min_ms": client.request_delay_min_ms,
        "request_delay_max_ms": client.request_delay_max_ms,
        "filters": [
            "secondOrgCode",
            "thirdOrgCode",
            "productCode",
            "dateRange",
            "channelCode",
            "staffNo",
            "staffRole",
            "statisticalDate",
        ],
        "staff_search_terms": len(_string_list(step.get("staff_search_terms") or [])),
        "statistical_dates": len(_string_list(step.get("statistical_dates") or [])),
        "trend_item_limit": trend_item_limit,
    }
    return FunnelCollection(rows=rows, metadata=metadata)


def _post(page: Any, api_base: str, path: str, payload: dict[str, Any]) -> Any:
    result = page.evaluate(
        """
        async ({ apiBase, path, payload }) => {
          if (apiBase.startsWith("app-module:")) {
            const moduleId = Number(apiBase.split(":", 2)[1]);
            const chunks = window.webpackChunk_focuspro_h5_kop;
            if (!Array.isArray(chunks) || !Number.isInteger(moduleId)) {
              throw new Error("funnel_app_module_unavailable");
            }
            let webpackRequire;
            const runtimeChunkId = (Date.now() % 1000000000) + 1000000000;
            chunks.push([[runtimeChunkId], {}, (require) => { webpackRequire = require; }]);
            if (!webpackRequire) throw new Error("funnel_webpack_runtime_unavailable");
            const apiModule = webpackRequire(moduleId);
            const api = apiModule && (apiModule.default || apiModule);
            const methods = {
              "/lost/queryEnum": "queryEnum",
              "/lost/queryStaffByName": "queryStaffByName",
              "/lost/queryMainItem": "queryMainItem",
              "/lost/querySubItem": "querySubItem",
              "/lost/queryTrendChart": "queryTrendChart",
              "/lost/queryLost": "queryLost",
              "/lost/queryLostDetail": "queryLostDetail",
              "/lost/querySubItemType": "getNodeList",
            };
            const method = methods[path];
            if (!method || !api || typeof api[method] !== "function") {
              throw new Error(`funnel_api_method_unavailable:${path}`);
            }
            try {
              let data;
              if (method === "queryEnum") data = await api[method]();
              else if (method === "queryStaffByName") data = await api[method](payload.name || "");
              else data = await api[method](payload);
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
          const body = Object.prototype.hasOwnProperty.call(payload, "businessType")
            ? payload
            : { businessType: bagClass, ...payload };
          const response = await fetch(`${apiBase}${path}`, {
            method: "POST",
            credentials: "include",
            headers,
            body: JSON.stringify(body),
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
        raise FunnelAPIError(path, str(result.get("code") or "API_ERROR"), str(result.get("message") or "request_failed"))
    return result


def _filter_combinations(enum_data: dict[str, Any], staff: list[dict[str, Any]], step: dict[str, Any]) -> list[dict[str, Any]]:
    products = _options(enum_data.get("productList"))
    if not products:
        raise RuntimeError("funnel_product_options_empty")
    date_ranges = _options(enum_data.get("dateRange"))
    channels = _options(enum_data.get("channelList"))
    roles = _options(enum_data.get("roleList"))
    orgs = _org_variants(enum_data.get("orgCodeList"), include_totals=bool(step.get("include_totals", True)))
    dates = _string_list(step.get("statistical_dates") or [])

    product_variants = [{"productCode": item["code"]} for item in products]
    date_range_variants = [{"dateRange": item["code"]} for item in date_ranges] or [{}]
    channel_variants = ([{}] if step.get("include_totals", True) else []) + [
        {"channelCode": item["code"]} for item in channels
    ]
    channel_variants = channel_variants or [{}]
    statistical_date_variants = ([{}] if step.get("include_totals", True) or not dates else []) + [
        {"statisticalDate": item} for item in dates
    ]
    statistical_date_variants = statistical_date_variants or [{}]
    staff_variants: list[dict[str, Any]] = [{}]
    if staff:
        staff_variants = []
        for item in staff:
            staff_no = str(item.get("staffNo") or "").strip()
            if not staff_no:
                continue
            staff_variants.append({"staffNo": staff_no})
            staff_variants.extend({"staffNo": staff_no, "staffRole": role["code"]} for role in roles)
        staff_variants = staff_variants or [{}]

    dimensions = [orgs, product_variants, date_range_variants, channel_variants, staff_variants, statistical_date_variants]
    mode = str(step.get("traversal_mode") or "cartesian").strip().lower()
    if mode == "current":
        default_product = str(step.get("default_product_code") or products[0]["code"]).strip()
        default_date = str(step.get("default_date_range") or "").strip()
        if not default_date:
            default_date = next((item["code"] for item in date_ranges if item["code"].upper() == "ALL"), date_ranges[0]["code"] if date_ranges else "")
        return _deduplicate_filters([{"productCode": default_product, **({"dateRange": default_date} if default_date else {})}])
    if mode == "independent":
        baseline = _merge_filters([dimension[0] for dimension in dimensions])
        candidates = [baseline]
        for dimension in dimensions:
            for variant in dimension:
                candidates.append({**baseline, **variant})
        return _deduplicate_filters(candidates)
    if mode != "cartesian":
        raise ValueError(f"funnel_traversal_mode_unsupported:{mode}")
    return _deduplicate_filters(_merge_filters(items) for items in itertools.product(*dimensions))


def _org_variants(value: Any, *, include_totals: bool) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [{}] if include_totals else []
    for parent in _mapping_list(value):
        second = str(parent.get("code") or "").strip()
        if not second:
            continue
        variants.append({"secondOrgCode": second})
        for child in _mapping_list(parent.get("children")):
            third = str(child.get("code") or "").strip()
            if third:
                variants.append({"secondOrgCode": second, "thirdOrgCode": third})
    return variants or [{}]


def _discover_staff(client: _FunnelAPIClient, terms: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for term in _string_list(terms):
        data = _mapping(
            client.post(_API_PATHS["staff"], {"name": term}),
            "funnel_staff_invalid",
        )
        found.extend(_mapping_list(data.get("list")))
    unique: dict[str, dict[str, Any]] = {}
    for item in found:
        staff_no = str(item.get("staffNo") or "").strip()
        if staff_no:
            unique[staff_no] = item
    return list(unique.values())


def _trend_rows(
    client: _FunnelAPIClient,
    context: dict[str, Any],
    filters: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    sub_item_type: str,
    item_limit: int,
    api_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in (items[:item_limit] if item_limit else items):
        item_type = str(item.get("type") or "").strip()
        if not item_type:
            continue
        trend = _optional_mapping_post(
            client,
            _API_PATHS["trend"],
            {**filters, "itemType": item_type},
            context,
            api_errors,
            sub_item_type=sub_item_type,
            item_type=item_type,
        )
        chart_map = trend.get("chartMap")
        if not isinstance(chart_map, dict):
            continue
        chart = chart_map.get(item_type)
        if not isinstance(chart, dict):
            continue
        for point in _mapping_list(chart.get("itemList")):
            rows.append(
                _row(
                    context,
                    record_type="trend_point",
                    source_endpoint=_API_PATHS["trend"],
                    sub_item_type=sub_item_type,
                    item_type=item_type,
                    metric_name=chart.get("itemName") or item.get("name"),
                    metric_value=point.get("value"),
                    metric_unit=chart.get("unitName"),
                    date_record=point.get("dateRecord"),
                    raw_value=point,
                )
            )
    return rows


def _optional_mapping_post(
    client: _FunnelAPIClient,
    path: str,
    payload: dict[str, Any],
    context: dict[str, Any],
    api_errors: list[dict[str, Any]],
    **error_context: Any,
) -> dict[str, Any]:
    try:
        return _mapping(client.post(path, payload), "funnel_optional_response_invalid")
    except FunnelAPIError as exc:
        api_errors.append(
            _row(
                context,
                record_type="api_error",
                source_endpoint=path,
                error_code=exc.code,
                error_message=exc.message,
                raw_value={"path": path, "code": exc.code, "message": exc.message},
                **error_context,
            )
        )
        return {}


def _metric_rows(
    context: dict[str, Any],
    record_type: str,
    endpoint: str,
    items: Iterable[dict[str, Any]],
    *,
    sub_item_type: str = "",
    lost_scene: str = "",
) -> list[dict[str, Any]]:
    return [
        _row(
            context,
            record_type=record_type,
            source_endpoint=endpoint,
            sub_item_type=sub_item_type,
            lost_scene=lost_scene,
            item_type=item.get("type"),
            metric_name=item.get("name"),
            metric_value=item.get("value"),
            metric_tips=item.get("tips"),
            weekly_rate=item.get("weeklyRate"),
            monthly_rate=item.get("monthlyRate"),
            raw_value=item,
        )
        for item in items
    ]


def _lost_detail_rows(
    context: dict[str, Any], lost_scene: str, lost_type: str, detail: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _mapping_list(detail.get("lostReasonList")):
        rows.append(
            _row(
                context,
                record_type="lost_reason",
                source_endpoint=_API_PATHS["lost_detail"],
                lost_scene=lost_scene,
                lost_type=lost_type,
                metric_name=item.get("reason"),
                metric_value=item.get("count"),
                metric_rate=item.get("rate"),
                raw_value=item,
            )
        )
    for key, record_type in (("limitDistribution", "limit_distribution"), ("intRateDistribution", "rate_distribution")):
        for item in _mapping_list(detail.get(key)):
            rows.append(
                _row(
                    context,
                    record_type=record_type,
                    source_endpoint=_API_PATHS["lost_detail"],
                    lost_scene=lost_scene,
                    lost_type=lost_type,
                    metric_name=item.get("range"),
                    metric_value=item.get("value"),
                    raw_value=item,
                )
            )
    return rows


def _enum_rows(enum_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, filter_key in (
        ("productList", "productCode"),
        ("dateRange", "dateRange"),
        ("channelList", "channelCode"),
        ("roleList", "staffRole"),
    ):
        for item in _options(enum_data.get(key)):
            rows.append(
                _row(
                    {},
                    record_type="filter_option",
                    source_endpoint=_API_PATHS["enum"],
                    filter_key=filter_key,
                    filter_code=item["code"],
                    filter_name=item["name"],
                    raw_value=item,
                )
            )
    for parent in _mapping_list(enum_data.get("orgCodeList")):
        rows.append(
            _row(
                {},
                record_type="filter_option",
                source_endpoint=_API_PATHS["enum"],
                filter_key="secondOrgCode",
                filter_code=parent.get("code"),
                filter_name=parent.get("name"),
                raw_value=parent,
            )
        )
        for child in _mapping_list(parent.get("children")):
            rows.append(
                _row(
                    {},
                    record_type="filter_option",
                    source_endpoint=_API_PATHS["enum"],
                    filter_key="thirdOrgCode",
                    filter_code=child.get("code"),
                    filter_name=child.get("name"),
                    second_org_code=parent.get("code"),
                    second_org_name=parent.get("name"),
                    raw_value=child,
                )
            )
    return rows


def _staff_rows(staff: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _row(
            {},
            record_type="filter_option",
            source_endpoint=_API_PATHS["staff"],
            filter_key="staffNo",
            filter_code=item.get("staffNo"),
            filter_name=item.get("staffName"),
            raw_value=item,
        )
        for item in staff
    ]


def _filter_context(
    index: int,
    filters: dict[str, Any],
    labels: dict[str, dict[str, str]],
    staff: list[dict[str, Any]],
) -> dict[str, Any]:
    staff_names = {str(item.get("staffNo") or ""): str(item.get("staffName") or "") for item in staff}
    return {
        "combination_index": index,
        "filter_signature": stable_json_hash(filters),
        "second_org_code": filters.get("secondOrgCode"),
        "second_org_name": labels["secondOrgCode"].get(str(filters.get("secondOrgCode") or ""), ""),
        "third_org_code": filters.get("thirdOrgCode"),
        "third_org_name": labels["thirdOrgCode"].get(str(filters.get("thirdOrgCode") or ""), ""),
        "product_code": filters.get("productCode"),
        "product_name": labels["productCode"].get(str(filters.get("productCode") or ""), ""),
        "date_range": filters.get("dateRange"),
        "date_range_name": labels["dateRange"].get(str(filters.get("dateRange") or ""), ""),
        "channel_code": filters.get("channelCode"),
        "channel_name": labels["channelCode"].get(str(filters.get("channelCode") or ""), ""),
        "staff_no": filters.get("staffNo"),
        "staff_name": staff_names.get(str(filters.get("staffNo") or ""), ""),
        "staff_role": filters.get("staffRole"),
        "staff_role_name": labels["staffRole"].get(str(filters.get("staffRole") or ""), ""),
        "statistical_date": filters.get("statisticalDate"),
    }


def _row(context: dict[str, Any], *, raw_value: Any = None, **values: Any) -> dict[str, Any]:
    return {
        **context,
        **{key: value for key, value in values.items() if value not in (None, "")},
        "raw_json": json.dumps(raw_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if raw_value is not None
        else "",
    }


def _enum_labels(enum_data: dict[str, Any]) -> dict[str, dict[str, str]]:
    labels = {
        "secondOrgCode": {},
        "thirdOrgCode": {},
        "productCode": _option_labels(enum_data.get("productList")),
        "dateRange": _option_labels(enum_data.get("dateRange")),
        "channelCode": _option_labels(enum_data.get("channelList")),
        "staffRole": _option_labels(enum_data.get("roleList")),
    }
    for parent in _mapping_list(enum_data.get("orgCodeList")):
        code = str(parent.get("code") or "")
        labels["secondOrgCode"][code] = str(parent.get("name") or "")
        for child in _mapping_list(parent.get("children")):
            labels["thirdOrgCode"][str(child.get("code") or "")] = str(child.get("name") or "")
    return labels


def _option_labels(value: Any) -> dict[str, str]:
    return {item["code"]: item["name"] for item in _options(value)}


def _options(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _mapping_list(value):
        code = str(item.get("code") or "").strip()
        if code:
            result.append({"code": code, "name": str(item.get("name") or "")})
    return result


def _node_types(value: Any) -> list[str]:
    result: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            key = item.get("code") or item.get("type") or item.get("value")
        else:
            key = item
        text = str(key or "").strip()
        if text:
            result.append(text)
    return list(dict.fromkeys(result))


def _merge_filters(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        merged.update(item)
    return {key: value for key, value in merged.items() if value not in (None, "")}


def _deduplicate_filters(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        normalized = {key: value for key, value in item.items() if value not in (None, "")}
        unique.setdefault(stable_json_hash(normalized), normalized)
    return list(unique.values())


def _relative_api_base(value: Any) -> str:
    base = str(value or "").strip().rstrip("/")
    if not base.startswith("/") or "://" in base or ".." in base:
        raise ValueError("funnel_api_base_must_be_relative")
    return base


def _resolve_api_base(page: Any, value: Any) -> str:
    configured = str(value or "").strip()
    if configured.startswith("app-module:"):
        module_id = configured.split(":", 1)[1]
        if not module_id.isdigit():
            raise ValueError("funnel_app_module_id_invalid")
        return configured
    if configured.lower() != "auto":
        return _relative_api_base(configured)
    urls = page.evaluate(
        """
        () => performance.getEntriesByType("resource")
          .map((entry) => entry.name)
          .filter((name) => name.includes("/lost/queryEnum"))
        """
    )
    if not isinstance(urls, list):
        raise RuntimeError("funnel_api_base_not_observed")
    page_origin = urlparse(str(page.url))
    for candidate in reversed(urls):
        parsed = urlparse(str(candidate))
        suffix = _API_PATHS["enum"]
        if not parsed.path.endswith(suffix):
            continue
        base_path = parsed.path[: -len(suffix)].rstrip("/")
        if (parsed.scheme, parsed.netloc) == (page_origin.scheme, page_origin.netloc):
            return base_path or "/"
        if parsed.scheme == "https" and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{base_path}"
    raise RuntimeError("funnel_api_base_not_observed")


def _mapping(value: Any, error: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(error)
    return value


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("funnel_list_parameter_required")
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _positive_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    number = int(value if value not in (None, "") else default)
    if number < minimum or number > maximum:
        raise ValueError("funnel_integer_parameter_out_of_range")
    return number
