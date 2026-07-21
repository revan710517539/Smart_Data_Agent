from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
from typing import Any
from urllib.parse import urlparse
import zipfile
import xml.etree.ElementTree as ET


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


DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "智能运营源站下载"
_XLSX_NAMESPACE = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_BROWSER_PROFILES = (
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36", {"width": 1440, "height": 900}),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36", {"width": 1512, "height": 982}),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36", {"width": 1365, "height": 768}),
)


class SourceSessionExpiredError(RuntimeError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download FocusPro business-sandbox source XLSX reports for each filter combination."
    )
    parser.add_argument("--db", default=".smart_data_agent.sqlite")
    parser.add_argument("--tenant", default="tenant:华兴银行")
    parser.add_argument("--connection-id", default="")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--storage-state", default=".crawler-sessions/qifu-business-sandbox.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", choices=("current", "cartesian"), default="current")
    parser.add_argument("--tab", action="append", choices=("经营沙盘", "经营明细"), default=[])
    parser.add_argument("--max-combinations", type=int, default=10_000)
    parser.add_argument("--request-delay-min-ms", type=int, default=250)
    parser.add_argument("--request-delay-max-ms", type=int, default=500)
    parser.add_argument("--max-request-retries", type=int, default=3)
    parser.add_argument("--max-session-refreshes", type=int, default=3)
    parser.add_argument("--circuit-breaker-failures", type=int, default=3)
    parser.add_argument("--source-cooldown-ms", type=int, default=60_000)
    parser.add_argument(
        "--only-key",
        action="append",
        default=[],
        help="Retry only an exact manifest key, for example '经营沙盘:abc123'. May be repeated.",
    )
    parser.add_argument("--allow-private-proxy-host", action="store_true")
    args = parser.parse_args()
    if args.request_delay_min_ms < 0 or args.request_delay_max_ms < args.request_delay_min_ms:
        raise ValueError("download_request_delay_range_invalid")
    if args.max_request_retries < 0:
        raise ValueError("download_max_request_retries_invalid")
    if args.max_session_refreshes < 0:
        raise ValueError("download_max_session_refreshes_invalid")
    if args.circuit_breaker_failures < 1:
        raise ValueError("download_circuit_breaker_failures_invalid")
    if args.source_cooldown_ms < 1_000:
        raise ValueError("download_source_cooldown_ms_invalid")
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
        for refresh_attempt in range(args.max_session_refreshes + 1):
            _ensure_login_session(
                connection=connection,
                page_url=args.url,
                storage_state=storage_state,
                browser_channel=args.browser_channel,
                allow_stdin_fallback=False,
            )
            try:
                download_reports(
                    page_url=args.url,
                    storage_state=storage_state,
                    browser_channel=args.browser_channel,
                    output_root=Path(args.output).resolve(),
                    mode=args.mode,
                    tabs=args.tab or ["经营沙盘", "经营明细"],
                    max_combinations=args.max_combinations,
                    delay_min_ms=args.request_delay_min_ms,
                    delay_max_ms=args.request_delay_max_ms,
                    max_request_retries=args.max_request_retries,
                    only_keys=set(args.only_key),
                    circuit_breaker_failures=args.circuit_breaker_failures,
                    source_cooldown_ms=args.source_cooldown_ms,
                )
                break
            except SourceSessionExpiredError:
                if refresh_attempt >= args.max_session_refreshes:
                    raise RuntimeError("source_session_refresh_exhausted")
                print(f"Source session expired; automatically refreshing ({refresh_attempt + 1}/{args.max_session_refreshes})")
    finally:
        services.close()


def download_reports(
    *,
    page_url: str,
    storage_state: Path,
    browser_channel: str,
    output_root: Path,
    mode: str,
    tabs: list[str],
    max_combinations: int,
    delay_min_ms: int,
    delay_max_ms: int,
    max_request_retries: int,
    only_keys: set[str] | None = None,
    circuit_breaker_failures: int = 3,
    source_cooldown_ms: int = 60_000,
) -> None:
    from playwright.sync_api import sync_playwright

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "下载清单.jsonl"
    failure_manifest_path = output_root / "下载失败清单.jsonl"
    completed = _completed_manifest_keys(manifest_path)
    profile = random.SystemRandom().choice(_BROWSER_PROFILES)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=browser_channel)
        context = browser.new_context(
            storage_state=str(storage_state),
            accept_downloads=True,
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
            raise SourceSessionExpiredError("business_sandbox_session_expired")
        enums = page.evaluate(
            """
            async () => {
              let require;
              window.webpackChunk_focuspro_h5_kop.push([[1000000005], {}, (value) => { require = value; }]);
              return await require(50826).queryEnum();
            }
            """
        )
        combinations = _download_combinations(enums, mode=mode)
        if len(combinations) > max_combinations:
            raise RuntimeError(
                f"download_filter_combinations_exceed_limit:{len(combinations)}>{max_combinations}"
            )
        total = len(combinations) * len(tabs)
        processed = 0
        consecutive_failures = 0
        for combination in combinations:
            for tab in tabs:
                processed += 1
                manifest_key = f"{tab}:{combination['key']}"
                if only_keys and manifest_key not in only_keys:
                    continue
                if manifest_key in completed:
                    continue
                try:
                    source_name, content = _request_source_report(
                        page=page,
                        context=context,
                        tab=tab,
                        combination=combination,
                        delay_min_ms=delay_min_ms,
                        delay_max_ms=delay_max_ms,
                        max_request_retries=max_request_retries,
                        user_agent=profile[0],
                    )
                    directory = output_root / tab / str(combination["directory"])
                    directory.mkdir(parents=True, exist_ok=True)
                    destination = directory / source_name
                    temporary = directory / f".{source_name}.{hashlib.sha256(content).hexdigest()[:12]}.tmp"
                    temporary.write_bytes(content)
                    validation = _validate_source_xlsx(temporary)
                    if not validation.get("valid_xlsx"):
                        temporary.unlink(missing_ok=True)
                        raise RuntimeError("source_report_xlsx_invalid")
                    temporary.replace(destination)
                except SourceSessionExpiredError:
                    raise
                except Exception as exc:
                    _append_jsonl(
                        failure_manifest_path,
                        {
                            "key": manifest_key,
                            "tab": tab,
                            "combination": combination,
                            "error_type": type(exc).__name__,
                            "error_code": _safe_error_code(exc),
                            "recorded_at": datetime_now_iso(),
                        },
                    )
                    print(f"[{processed}/{total}] FAILED {tab} {combination['directory']} {_safe_error_code(exc)}")
                    consecutive_failures += 1
                    if consecutive_failures >= circuit_breaker_failures:
                        print(
                            "Source export circuit breaker opened after "
                            f"{consecutive_failures} consecutive failures; "
                            f"cooling down {source_cooldown_ms}ms before resume."
                        )
                        page.wait_for_timeout(source_cooldown_ms)
                        consecutive_failures = 0
                    continue
                manifest = {
                    "key": manifest_key,
                    "tab": tab,
                    "combination": combination,
                    "source_file_name": source_name,
                    "path": str(destination),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "validation": validation,
                }
                _append_jsonl(manifest_path, manifest)
                completed.add(manifest_key)
                consecutive_failures = 0
                print(
                    f"[{processed}/{total}] {tab} {combination['directory']} "
                    f"rows={validation['data_rows']} nonzero={validation['nonzero_metric_cells']}"
                )
        context.storage_state(path=str(storage_state))
        storage_state.chmod(0o600)
        browser.close()


def _download_combinations(enums: dict[str, Any], *, mode: str) -> list[dict[str, Any]]:
    products = _options(enums.get("productList"))
    date_ranges = _options(enums.get("dateRange"))
    if not products:
        raise RuntimeError("download_product_options_empty")
    if not date_ranges:
        date_ranges = [{"code": "MONTH", "name": "月数据"}]
    month = next((item for item in date_ranges if item["code"] == "MONTH"), date_ranges[0])
    if mode == "current":
        orgs = [{"second_code": "", "second_name": "", "third_code": "", "third_name": "", "path": []}]
        products = products[:1]
        date_ranges = [month]
    else:
        orgs = [{"second_code": "", "second_name": "", "third_code": "", "third_name": "", "path": []}]
        for parent in enums.get("orgCodeList") if isinstance(enums.get("orgCodeList"), list) else []:
            if not isinstance(parent, dict):
                continue
            second_code = str(parent.get("code") or parent.get("value") or "").strip()
            second_name = str(parent.get("name") or parent.get("label") or second_code).strip()
            if not second_code or second_code == "000":
                continue
            orgs.append({"second_code": second_code, "second_name": second_name, "third_code": "", "third_name": "", "path": [second_code]})
            for child in parent.get("children") if isinstance(parent.get("children"), list) else []:
                if not isinstance(child, dict):
                    continue
                third_code = str(child.get("code") or child.get("value") or "").strip()
                third_name = str(child.get("name") or child.get("label") or third_code).strip()
                if third_code:
                    orgs.append({"second_code": second_code, "second_name": second_name, "third_code": third_code, "third_name": third_name, "path": [second_code, third_code]})
    combinations: list[dict[str, Any]] = []
    for org in orgs:
        for product in products:
            for date_range in date_ranges:
                org_name = (
                    f"{org['second_name']}-{org['third_name']}"
                    if org["third_name"]
                    else org["second_name"] or "总行"
                )
                directory = "_".join(
                    _safe_file_name_component(value, "未知")
                    for value in (org_name, product["name"], date_range["name"])
                )
                combinations.append(
                    {
                        **org,
                        "product_code": product["code"],
                        "product_name": product["name"],
                        "date_range": date_range["code"],
                        "date_range_name": date_range["name"],
                        "directory": directory,
                        "key": hashlib.sha256(
                            json.dumps(
                                [org["second_code"], org["third_code"], product["code"], date_range["code"]],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()[:20],
                    }
                )
    return combinations


def _download_payload(tab: str, combination: dict[str, Any]) -> dict[str, Any]:
    common = {
        "productCode": combination["product_code"],
        "dateRange": combination["date_range"],
    }
    selected_code = combination["third_code"] or combination["second_code"]
    if tab == "经营沙盘":
        return {
            **common,
            "productName": combination["product_name"],
            "orgCode": [combination["path"]] if combination["path"] else [],
            "secondOrgCode": combination["second_code"],
            "thirdOrgCode": combination["third_code"],
        }
    return {**common, "orgCode": [selected_code] if selected_code else []}


def _validate_source_xlsx(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names or "xl/worksheets/sheet1.xml" not in names:
                raise ValueError("xlsx_required_parts_missing")
            shared_strings = _shared_strings(archive)
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            rows = root.findall(".//m:sheetData/m:row", _XLSX_NAMESPACE)
            numeric_values: list[float] = []
            for row in rows[1:]:
                cells = row.findall("m:c", _XLSX_NAMESPACE)[4:]
                for cell in cells:
                    value = _xlsx_cell_value(cell, shared_strings)
                    normalized = value.replace(",", "").replace("%", "").strip()
                    try:
                        numeric_values.append(float(normalized))
                    except ValueError:
                        continue
            return {
                "valid_xlsx": True,
                "data_rows": max(0, len(rows) - 1),
                "numeric_metric_cells": len(numeric_values),
                "nonzero_metric_cells": sum(value != 0 for value in numeric_values),
                "complete": bool(rows[1:]) and any(value != 0 for value in numeric_values),
            }
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        return {"valid_xlsx": False, "complete": False, "error": type(exc).__name__}


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", _XLSX_NAMESPACE))
        for item in root.findall("m:si", _XLSX_NAMESPACE)
    ]


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", _XLSX_NAMESPACE))
    node = cell.find("m:v", _XLSX_NAMESPACE)
    value = "" if node is None else str(node.text or "")
    if cell.get("t") == "s" and value.isdigit() and int(value) < len(shared_strings):
        return shared_strings[int(value)]
    return value


def _completed_manifest_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    completed: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
            if (
                isinstance(row, dict)
                and row.get("key")
                and validation.get("valid_xlsx") is True
                and Path(str(row.get("path") or "")).is_file()
            ):
                completed.add(str(row["key"]))
    return completed


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _jitter(page: Any, minimum: int, maximum: int) -> None:
    page.wait_for_timeout(random.SystemRandom().randint(minimum, maximum))


def _request_source_report(
    *,
    page: Any,
    context: Any,
    tab: str,
    combination: dict[str, Any],
    delay_min_ms: int,
    delay_max_ms: int,
    max_request_retries: int,
    user_agent: str,
) -> tuple[str, bytes]:
    payload = _download_payload(tab, combination)
    last_error: Exception | None = None
    for attempt in range(max_request_retries + 1):
        if _session_expired(page):
            raise SourceSessionExpiredError("business_sandbox_session_expired")
        try:
            _jitter(page, delay_min_ms, delay_max_ms)
            report = page.evaluate(
                """
                async ({ tab, payload }) => {
                  let require;
                  window.webpackChunk_focuspro_h5_kop.push([
                    [(Date.now() % 1000000000) + 1000000000],
                    {},
                    (value) => { require = value; },
                  ]);
                  const api = require(50826);
                  return tab === '经营沙盘'
                    ? await api.downloadBusinessReport(payload)
                    : await api.downloadDetailReport(payload);
                }
                """,
                {"tab": tab, "payload": payload},
            )
            if not isinstance(report, dict) or not str(report.get("fileId") or "").strip():
                raise RuntimeError("source_report_file_id_missing")
            _jitter(page, delay_min_ms, delay_max_ms)
            file_url = page.evaluate(
                """
                async ({ fileId }) => {
                  let require;
                  window.webpackChunk_focuspro_h5_kop.push([
                    [(Date.now() % 1000000000) + 1000000000],
                    {},
                    (value) => { require = value; },
                  ]);
                  const response = await require(71543).NB({ fileId, fileType: 'xlsx' });
                  return response.data;
                }
                """,
                {"fileId": report["fileId"]},
            )
            if not isinstance(file_url, str) or not file_url.startswith(("https://", "http://")):
                raise RuntimeError("source_report_file_url_missing")
            _jitter(page, delay_min_ms, delay_max_ms)
            response = context.request.get(
                file_url,
                timeout=120_000,
                headers={
                    "Accept": (
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
                        "application/octet-stream;q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Referer": str(page.url),
                    "User-Agent": user_agent,
                },
            )
            if not response.ok:
                raise RuntimeError(f"source_report_download_http_{response.status}")
            source_name = _safe_file_name(str(report.get("fileName") or f"{tab}.xlsx"), "report.xlsx")
            if not source_name.lower().endswith(".xlsx"):
                source_name += ".xlsx"
            content = response.body()
            return source_name, content
        except Exception as exc:
            if _session_expired(page) or _is_session_error(exc):
                raise SourceSessionExpiredError("business_sandbox_session_expired") from exc
            last_error = exc
            if attempt >= max_request_retries:
                break
            _jitter(page, max(delay_min_ms * 2, 500), max(delay_max_ms * 2, 1_000))
    assert last_error is not None
    raise last_error


def _safe_error_code(exc: Exception) -> str:
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    if not lines:
        return type(exc).__name__
    # Playwright prefixes browser-side failures with a generic first line such
    # as "Page.evaluate: Error". Preserve the nested application response too;
    # it is needed to distinguish a source-side rate limit from a bad report.
    relevant = lines[1:4] if lines[0].startswith("Page.evaluate:") and len(lines) > 1 else lines[:3]
    return " | ".join(relevant)[:500]


def _session_expired(page: Any) -> bool:
    try:
        return (
            page.title().strip() == "统一登录平台"
            or "union-general-cas.qifu.tech" in str(page.url).lower()
        )
    except Exception:
        return False


def _is_session_error(exc: Exception) -> bool:
    value = str(exc).casefold()
    return any(token in value for token in ("unauthorized", "401", "登录失效", "登录过期", "未登录"))


def datetime_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _options(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("value") or "").strip()
        name = str(item.get("name") or item.get("label") or code).strip()
        if code:
            result.append({"code": code, "name": name})
    return result


def _safe_file_name(value: str, fallback: str) -> str:
    normalized = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip(" .")
    return normalized[:180] or fallback


def _safe_file_name_component(value: str, fallback: str) -> str:
    return _safe_file_name(value, fallback).replace("_", "-")


if __name__ == "__main__":
    main()
