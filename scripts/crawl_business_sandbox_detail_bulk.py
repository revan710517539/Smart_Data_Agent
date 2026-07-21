from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import sys
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.platform.bootstrap import build_local_platform
from scripts.crawl_business_sandbox import (
    DEFAULT_URL,
    _append_host_pattern,
    _ensure_login_session,
    _registered_connection,
)


DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "智能运营" / "完整页面数据" / "经营明细"
_PERIOD_KEYS = {
    "7DAY": ("cur7day", "last7day"),
    "30DAY": ("cur30day", "last30day"),
    "WEEK": ("curWeek", "lastWeek"),
    "MONTH": ("curMonth", "lastMonth"),
    "QUARTER": ("curQuarter", "lastQuarter"),
    "YEAR": ("curYear", "lastYear"),
    "ALL": ("value", ""),
}
_BROWSER_PROFILES = (
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36", {"width": 1440, "height": 900}),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36", {"width": 1512, "height": 982}),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36", {"width": 1365, "height": 768}),
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-collect complete FocusPro 经营明细 metrics for every organization/product/time combination."
    )
    parser.add_argument("--db", default=".smart_data_agent.sqlite")
    parser.add_argument("--tenant", default="tenant:华兴银行")
    parser.add_argument("--connection-id", default="")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--storage-state", default=".crawler-sessions/qifu-business-sandbox.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--org-batch-size", type=int, default=40)
    parser.add_argument("--request-delay-min-ms", type=int, default=250)
    parser.add_argument("--request-delay-max-ms", type=int, default=500)
    parser.add_argument("--max-rate-limit-retries", type=int, default=3)
    parser.add_argument("--allow-private-proxy-host", action="store_true")
    args = parser.parse_args()
    if args.org_batch_size < 1 or args.org_batch_size > 100:
        raise ValueError("detail_bulk_org_batch_size_invalid")
    if args.request_delay_min_ms < 0 or args.request_delay_max_ms < args.request_delay_min_ms:
        raise ValueError("detail_bulk_request_delay_range_invalid")
    if args.allow_private_proxy_host:
        host = str(urlparse(args.url).hostname or "").strip().lower()
        if not host:
            raise ValueError("crawler_target_hostname_required")
        os.environ["SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS"] = _append_host_pattern(
            os.getenv("SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS", ""), host
        )
    services = build_local_platform(Path(args.db))
    try:
        connection = _registered_connection(
            services.system_config_store,
            tenant_id=args.tenant,
            connection_id=args.connection_id,
            page_url=args.url,
        )
        storage_state = Path(args.storage_state).resolve()
        _ensure_login_session(
            connection=connection,
            page_url=args.url,
            storage_state=storage_state,
            browser_channel=args.browser_channel,
            allow_stdin_fallback=False,
        )
        collect_all_details(
            page_url=args.url,
            storage_state=storage_state,
            browser_channel=args.browser_channel,
            output_root=Path(args.output).resolve(),
            org_batch_size=args.org_batch_size,
            delay_min_ms=args.request_delay_min_ms,
            delay_max_ms=args.request_delay_max_ms,
            max_retries=args.max_rate_limit_retries,
        )
    finally:
        services.close()


def collect_all_details(
    *,
    page_url: str,
    storage_state: Path,
    browser_channel: str,
    output_root: Path,
    org_batch_size: int,
    delay_min_ms: int,
    delay_max_ms: int,
    max_retries: int,
) -> None:
    from playwright.sync_api import sync_playwright

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "完整性清单.json"
    manifest = _read_json(manifest_path)
    completed = set(manifest.get("completed", [])) if isinstance(manifest, dict) else set()
    profile = random.SystemRandom().choice(_BROWSER_PROFILES)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=browser_channel)
        context = browser.new_context(
            storage_state=str(storage_state),
            user_agent=profile[0],
            viewport=profile[1],
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            color_scheme="light",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        page = context.new_page()
        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)
        if page.title().strip() == "统一登录平台":
            raise RuntimeError("business_sandbox_session_expired")
        enums = _api_call(page, "queryEnum", {}, delay_min_ms, delay_max_ms, max_retries)
        products = _options(enums.get("productList"))
        date_ranges = _options(enums.get("dateRange"))
        org_labels, org_codes = _organization_index(enums.get("orgCodeList"))
        expected_codes = {"000", *org_codes}
        summaries = manifest.get("reports", {}) if isinstance(manifest, dict) else {}
        total = len(products) * len(date_ranges)
        current = 0
        for product in products:
            section_response = _api_call(
                page,
                "queryDetailSubItemType",
                {"productCode": product["code"]},
                delay_min_ms,
                delay_max_ms,
                max_retries,
            )
            sections = _detail_leaf_sections(section_response.get("subItemTypeList"))
            schema = [
                (str(section["code"]), str(metric.get("type") or ""), str(metric.get("name") or metric.get("type") or ""))
                for section in sections
                for metric in section["metrics"]
                if str(metric.get("type") or "")
            ]
            for date_range in date_ranges:
                current += 1
                report_key = f"{product['code']}:{date_range['code']}"
                destination = output_root / (
                    f"经营明细完整报表_{_safe_name(product['name'], '未知产品')}_"
                    f"{_safe_name(date_range['name'], '时间维度')}.csv"
                )
                if report_key in completed and destination.is_file():
                    continue
                values_by_org: dict[str, dict[tuple[str, str], Any]] = {}
                requested_batches = [org_codes[index:index + org_batch_size] for index in range(0, len(org_codes), org_batch_size)]
                if not requested_batches:
                    requested_batches = [[]]
                for batch_index, batch in enumerate(requested_batches, start=1):
                    for section in sections:
                        metrics = [{**metric, "checked": True} for metric in section["metrics"]]
                        result = _api_call(
                            page,
                            "queryDetailSubItem",
                            {
                                "productCode": product["code"],
                                "dateRange": date_range["code"],
                                "subItemType": section["code"],
                                "metrics": metrics,
                                "filter": {},
                                "orgCode": batch,
                            },
                            delay_min_ms,
                            delay_max_ms,
                            max_retries,
                        )
                        current_key, _previous_key = _PERIOD_KEYS.get(date_range["code"], ("value", ""))
                        for source_row in result.get("rows") if isinstance(result.get("rows"), list) else []:
                            if not isinstance(source_row, dict):
                                continue
                            dimension_code = str(source_row.get("dimension_code") or "").strip()
                            if not dimension_code or dimension_code not in expected_codes:
                                continue
                            target = values_by_org.setdefault(dimension_code, {})
                            for metric in source_row.get("metrics_values") if isinstance(source_row.get("metrics_values"), list) else []:
                                if not isinstance(metric, dict):
                                    continue
                                metric_code = str(metric.get("type") or "").strip()
                                if not metric_code:
                                    continue
                                value = metric.get(current_key)
                                if value in (None, "") and current_key != "value":
                                    value = metric.get("value")
                                target.setdefault((str(section["code"]), metric_code), value if value is not None else "")
                    print(
                        f"[{current}/{total}] {product['name']} {date_range['name']} "
                        f"org-batch={batch_index}/{len(requested_batches)} rows={len(values_by_org)}"
                    )
                statistical_date = _statistical_date(
                    page,
                    product_code=product["code"],
                    date_range=date_range["code"],
                    item_type=schema[0][1] if schema else "active_staff_num",
                    delay_min_ms=delay_min_ms,
                    delay_max_ms=delay_max_ms,
                    max_retries=max_retries,
                )
                headers = ["机构", "产品名称", "统计日期", "时间维度", *[item[2] for item in schema]]
                records: list[list[Any]] = []
                for org_code in ["000", *org_codes]:
                    metrics = values_by_org.get(org_code, {})
                    records.append(
                        [
                            org_labels.get(org_code, org_code),
                            product["name"],
                            statistical_date,
                            date_range["name"],
                            *[metrics.get((section_code, metric_code), "") for section_code, metric_code, _name in schema],
                        ]
                    )
                _write_csv(destination, headers, records)
                nonempty_codes = {
                    code
                    for code, metrics in values_by_org.items()
                    if any(value not in (None, "") for value in metrics.values())
                }
                summary = {
                    "path": str(destination),
                    "expected_organizations": len(expected_codes),
                    "returned_organizations": len(values_by_org),
                    "organizations_with_values": len(nonempty_codes),
                    "metric_columns": len(schema),
                    "complete_structure": expected_codes.issubset(values_by_org),
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
                summaries[report_key] = summary
                completed.add(report_key)
                _write_json_atomic(
                    manifest_path,
                    {
                        "completed": sorted(completed),
                        "expected_reports": total,
                        "completed_reports": len(completed),
                        "reports": summaries,
                    },
                )
        context.storage_state(path=str(storage_state))
        storage_state.chmod(0o600)
        browser.close()


def _api_call(
    page: Any,
    method: str,
    payload: dict[str, Any],
    delay_min_ms: int,
    delay_max_ms: int,
    max_retries: int,
) -> dict[str, Any]:
    for attempt in range(max_retries + 1):
        page.wait_for_timeout(random.SystemRandom().randint(delay_min_ms, delay_max_ms))
        result = page.evaluate(
            """
            async ({ method, payload }) => {
              let require;
              window.webpackChunk_focuspro_h5_kop.push([
                [(Date.now() % 1000000000) + 1000000000],
                {},
                (value) => { require = value; },
              ]);
              try {
                const api = require(50826);
                const data = method === 'queryEnum' ? await api[method]() : await api[method](payload);
                return { ok: true, data };
              } catch (error) {
                return {
                  ok: false,
                  code: String((error && error.code) || 'API_ERROR'),
                  message: String((error && (error.msg || error.message)) || 'request_failed'),
                };
              }
            }
            """,
            {"method": method, "payload": payload},
        )
        if isinstance(result, dict) and result.get("ok") is True:
            data = result.get("data")
            return data if isinstance(data, dict) else {}
        code = str(result.get("code") or "API_ERROR") if isinstance(result, dict) else "API_ERROR"
        if attempt >= max_retries:
            raise RuntimeError(f"detail_bulk_api_failed:{method}:{code}")
        page.wait_for_timeout(min(5_000 * (2**attempt), 30_000))
    raise RuntimeError(f"detail_bulk_api_retry_exhausted:{method}")


def _statistical_date(
    page: Any,
    *,
    product_code: str,
    date_range: str,
    item_type: str,
    delay_min_ms: int,
    delay_max_ms: int,
    max_retries: int,
) -> str:
    trend = _api_call(
        page,
        "queryDetailTrendChart",
        {"orgCode": ["000"], "productCode": product_code, "dateRange": date_range, "itemType": item_type},
        delay_min_ms,
        delay_max_ms,
        max_retries,
    )
    dates: list[str] = []
    chart_map = trend.get("chartMap") if isinstance(trend.get("chartMap"), dict) else trend
    for series in chart_map.values():
        if not isinstance(series, dict):
            continue
        for point in series.get("itemList") if isinstance(series.get("itemList"), list) else []:
            if isinstance(point, dict):
                value = str(point.get("dateRecord") or point.get("date") or "")
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    dates.append(value)
    return max(dates) if dates else ""


def _organization_index(value: Any) -> tuple[dict[str, str], list[str]]:
    labels = {"000": "总行"}
    codes: list[str] = []
    for parent in value if isinstance(value, list) else []:
        if not isinstance(parent, dict):
            continue
        parent_code = str(parent.get("code") or "").strip()
        parent_name = str(parent.get("name") or parent_code).strip()
        if parent_code and parent_code != "000":
            labels[parent_code] = parent_name
            codes.append(parent_code)
        for child in parent.get("children") if isinstance(parent.get("children"), list) else []:
            if not isinstance(child, dict):
                continue
            child_code = str(child.get("code") or "").strip()
            child_name = str(child.get("name") or child_code).strip()
            if child_code:
                labels[child_code] = f"{parent_name}/{child_name}"
                codes.append(child_code)
    return labels, list(dict.fromkeys(codes))


def _detail_leaf_sections(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(items: Any) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            children = item.get("children") if isinstance(item.get("children"), list) else []
            if children:
                visit(children)
                continue
            code = str(item.get("code") or "").strip()
            if code:
                result.append(
                    {
                        "code": code,
                        "name": str(item.get("name") or code),
                        "metrics": [metric for metric in item.get("metrics", []) if isinstance(metric, dict)],
                    }
                )

    visit(value)
    return result


def _options(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("value") or "").strip()
        if code:
            result.append({"code": code, "name": str(item.get("name") or item.get("label") or code).strip()})
    return result


def _write_csv(path: Path, headers: list[str], records: list[list[Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(records)
    content = stream.getvalue().encode("utf-8-sig")
    temporary = path.parent / f".{path.name}.{hashlib.sha256(content).hexdigest()[:12]}.tmp"
    temporary.write_bytes(content)
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.{hashlib.sha256(content).hexdigest()[:12]}.tmp"
    temporary.write_bytes(content)
    temporary.replace(path)


def _safe_name(value: str, fallback: str) -> str:
    normalized = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip(" .")
    return normalized[:120] or fallback


if __name__ == "__main__":
    main()
