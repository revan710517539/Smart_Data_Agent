from __future__ import annotations

import csv
import io
import json
import os
import secrets
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.platform.security import validate_outbound_url

from .contracts import CrawlerExecutionError, CrawlerOperation, CrawlerRequest, CrawlerResult
from .diagnostics import build_diagnostic, stable_json_hash
from .profile_registry import (
    CrawlerProfileCollection,
    CrawlerProfileContext,
    CrawlerProfileRegistry,
    get_default_crawler_profile_registry,
)
from .url_identity import build_crawler_url_identity


_BROWSER_PROFILES = (
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "viewport": {"width": 1512, "height": 982},
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "viewport": {"width": 1365, "height": 768},
    },
)


class PlaywrightCrawlerTransport:
    """Generic, versioned browser-DSL runner used by the dedicated crawler worker."""

    name = "playwright"

    def __init__(self, profile_registry: CrawlerProfileRegistry | None = None) -> None:
        self.profile_registry = profile_registry or get_default_crawler_profile_registry()

    def execute(self, request: CrawlerRequest) -> CrawlerResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency is production locked.
            raise RuntimeError("playwright_dependency_missing") from exc

        connection = dict(request.connection)
        secret_values = [connection.get("password"), connection.get("token"), request.readonly_sql]
        timeout_ms = min(max(int(request.timeout_seconds), 1), 900) * 1000
        failed_step = "browser_start"
        page = None
        network: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        crawler_config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
        headless = _boolean_setting(
            crawler_config.get("headless"),
            os.getenv("SMART_DATA_AGENT_CRAWLER_HEADLESS", "true"),
        )
        channel = str(
            crawler_config.get("browserChannel")
            or os.getenv("SMART_DATA_AGENT_CRAWLER_BROWSER_CHANNEL", "")
        ).strip()
        storage_state_path = _storage_state_path(request, connection, crawler_config)
        if storage_state_path:
            connection["crawlerConfig"] = {**crawler_config, "storageStatePath": storage_state_path}
            crawler_config = connection["crawlerConfig"]
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {"headless": headless}
            if channel:
                launch_options["channel"] = channel
            browser = playwright.chromium.launch(**launch_options)
            browser_profile = secrets.choice(_BROWSER_PROFILES)
            context_options: dict[str, Any] = {
                "accept_downloads": True,
                "user_agent": str(browser_profile["user_agent"]),
                "viewport": dict(browser_profile["viewport"]),
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "color_scheme": "light",
                "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            }
            if storage_state_path and Path(storage_state_path).is_file():
                context_options["storage_state"] = storage_state_path
            context = browser.new_context(**context_options)
            try:
                page = context.new_page()
                page.set_default_timeout(min(timeout_ms, 60_000))
                page.on(
                    "response",
                    lambda response: network.append(
                        {"method": response.request.method, "url": response.url, "status": response.status}
                    ) if len(network) < 100 else None,
                )
                for index, step in enumerate(request.script.get("steps", [])):
                    action = str(step["action"])
                    failed_step = f"{index + 1}:{action}"
                    outcome = self._run_step(page, action, step, request, connection)
                    if isinstance(outcome, CrawlerProfileCollection):
                        rows = list(outcome.rows)
                        metadata.update(outcome.metadata)
                    elif isinstance(outcome, list):
                        rows = outcome
                    elif isinstance(outcome, dict):
                        metadata.update(outcome)
                if request.operation_type == CrawlerOperation.DATA_QUERY and not rows:
                    raise RuntimeError("empty_result")
                observed_at = datetime.now(timezone.utc).isoformat()
                if storage_state_path:
                    state_path = Path(storage_state_path)
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(state_path))
                    state_path.chmod(0o600)
                snapshot = {
                    "snapshot_id": f"crawler:{stable_json_hash({'key': request.idempotency_key, 'at': observed_at})[:24]}",
                    "observed_at": observed_at,
                    "source_version": request.script_version_id or "browser-profile-v1",
                    "operation_type": request.operation_type.value,
                    "transport": self.name,
                    "page_url_hash": stable_json_hash(page.url),
                }
                return CrawlerResult(
                    status="succeeded",
                    rows=tuple(rows),
                    metadata=metadata,
                    diagnostics={"transport": self.name, "steps": len(request.script.get("steps", []))},
                    source_snapshot=snapshot,
                    schema_hash=stable_json_hash(sorted({key for row in rows for key in row}) if rows else metadata),
                )
            except Exception as exc:
                screenshot = None
                dom_summary = ""
                page_url = ""
                page_title = ""
                if page is not None:
                    try:
                        screenshot = page.screenshot(full_page=False)
                        dom_summary = page.locator("body").inner_text()[:8_000]
                        page_url = page.url
                        page_title = page.title()
                    except Exception:
                        pass
                diagnostic = build_diagnostic(
                    exc,
                    failed_step=failed_step,
                    secrets=[str(item) for item in secret_values if item],
                    page_url=page_url,
                    page_title=page_title,
                    dom_summary=dom_summary,
                    screenshot=screenshot,
                    network_summary=network,
                )
                raise CrawlerExecutionError(diagnostic.error_code, diagnostic.summary, diagnostic) from exc
            finally:
                context.close()
                browser.close()

    def _run_step(
        self,
        page: Any,
        action: str,
        step: dict[str, Any],
        request: CrawlerRequest,
        connection: dict[str, Any],
    ) -> CrawlerProfileCollection | list[dict[str, Any]] | dict[str, Any] | None:
        selector = str(step.get("selector") or "")
        timeout = int(step.get("timeout_ms") or 15_000)
        if action == "goto":
            url = self._resolve_url(str(step.get("url") or ""), connection)
            validate_outbound_url(url)
            page.goto(url, wait_until=str(step.get("wait_until") or "domcontentloaded"), timeout=timeout)
            return None
        if action in {"fill", "search_table"}:
            value = self._resolve_value(step, request, connection)
            locator = page.locator(selector)
            if bool(step.get("optional")) and locator.count() == 0:
                return None
            locator.fill(value, timeout=timeout)
            return None
        if action in {"click", "open_metadata"}:
            locator = page.locator(selector)
            if bool(step.get("optional")) and locator.count() == 0:
                return None
            locator.click(timeout=timeout)
            return None
        if action == "wait":
            if selector:
                page.locator(selector).wait_for(state=str(step.get("state") or "visible"), timeout=timeout)
            else:
                page.wait_for_timeout(min(timeout, 30_000))
            _save_storage_state(page, connection)
            return None
        if action == "wait_for_url":
            url_contains = str(step.get("url_contains") or "").strip()
            if not url_contains:
                raise ValueError("wait_for_url_value_required")
            target_url = self._resolve_url("${query_page_url}", connection)

            def url_matches(value: Any) -> bool:
                if bool(step.get("match_query_page")):
                    actual = urlsplit(str(value))
                    target = urlsplit(target_url)
                    return (
                        actual.scheme.lower() == target.scheme.lower()
                        and actual.netloc.lower() == target.netloc.lower()
                        and actual.path.rstrip("/") == target.path.rstrip("/")
                        and actual.fragment.casefold() == target.fragment.casefold()
                    )
                return url_contains in str(value)

            config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
            headless = _boolean_setting(config.get("headless"), os.getenv("SMART_DATA_AGENT_CRAWLER_HEADLESS", "true"))
            deadline = time.monotonic() + (timeout / 1000)
            headless_deadline = min(deadline, time.monotonic() + 15)
            while time.monotonic() < deadline:
                if url_matches(page.url):
                    stability_ms = int(step.get("stability_ms") or 5_000)
                    page.wait_for_timeout(min(max(stability_ms, 500), 15_000))
                    title = page.title().strip()
                    if url_matches(page.url) and title != "统一登录平台":
                        _save_storage_state(page, connection)
                        return None
                if bool(step.get("manual")) and headless and time.monotonic() >= headless_deadline:
                    raise RuntimeError("captcha_or_mfa_manual_intervention_required")
                page.wait_for_timeout(500)
            raise TimeoutError("authenticated_query_page_timeout")
        if action in {"collect_system", "collect_funnel_analysis"}:
            profile_id = str(step.get("profile_id") or action).strip()
            return self.profile_registry.collect(
                profile_id,
                CrawlerProfileContext(
                    page=page,
                    request=request,
                    connection=connection,
                    step=step,
                ),
            )
        if action == "submit_sql":
            if not request.readonly_sql:
                raise ValueError("readonly_sql_required")
            page.locator(selector).fill(request.readonly_sql, timeout=timeout)
            submit_selector = str(step.get("submit_selector") or "")
            if submit_selector:
                page.locator(submit_selector).click(timeout=timeout)
            return None
        if action == "download_csv":
            with page.expect_download(timeout=timeout) as download_info:
                page.locator(selector).click(timeout=timeout)
            download = download_info.value
            with tempfile.TemporaryDirectory(prefix="smart-data-crawler-") as tmpdir:
                path = Path(tmpdir) / (download.suggested_filename or "result.csv")
                download.save_as(path)
                return _csv_rows(path.read_bytes())
        if action == "extract_metadata":
            columns = step.get("column_selectors")
            if not isinstance(columns, dict) or not columns:
                raise ValueError("metadata_column_selectors_required")
            items: list[dict[str, Any]] = []
            for row in page.locator(selector).all():
                item = {str(key): row.locator(str(value)).inner_text().strip() for key, value in columns.items()}
                items.append(item)
            return {"fields": items}
        raise ValueError(f"unsupported_browser_action:{action}")

    @staticmethod
    def _resolve_url(value: str, connection: dict[str, Any]) -> str:
        aliases = {
            "${login_url}": str(connection.get("loginUrl") or connection.get("apiUrl") or ""),
            "${query_page_url}": str(connection.get("queryPageUrl") or connection.get("apiUrl") or ""),
        }
        return aliases.get(value, value)

    @staticmethod
    def _resolve_value(step: dict[str, Any], request: CrawlerRequest, connection: dict[str, Any]) -> str:
        key = str(step.get("value_key") or "")
        values = {
            "account": connection.get("account"),
            "password": connection.get("password"),
            "space_id": connection.get("spaceId"),
            "readonly_sql": request.readonly_sql,
            "topic_table_id": request.topic_table_id,
            "raw_table_name": request.parameters.get("raw_table_name"),
        }
        if key not in values:
            raise ValueError(f"browser_value_key_not_allowed:{key}")
        return str(values[key] or "")


def _csv_rows(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig")
    stream = io.StringIO(text)
    dialect = csv.Sniffer().sniff(text[:4_096], delimiters=",\t;") if text.strip() else csv.excel
    return [dict(row) for row in csv.DictReader(stream, dialect=dialect)]


def _boolean_setting(value: Any, default: Any) -> bool:
    normalized = str(default if value in (None, "") else value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("crawler_boolean_setting_invalid")


def _save_storage_state(page: Any, connection: dict[str, Any]) -> None:
    config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
    value = str(config.get("storageStatePath") or os.getenv("SMART_DATA_AGENT_CRAWLER_STORAGE_STATE", "")).strip()
    if not value:
        return
    path = Path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.context.storage_state(path=str(path))
    path.chmod(0o600)


def _storage_state_path(
    request: CrawlerRequest,
    connection: dict[str, Any],
    crawler_config: dict[str, Any],
) -> str:
    explicit = str(
        crawler_config.get("storageStatePath")
        or os.getenv("SMART_DATA_AGENT_CRAWLER_STORAGE_STATE", "")
    ).strip()
    if explicit:
        return explicit
    identity = build_crawler_url_identity(connection)
    if identity is None:
        return ""
    root = Path(os.getenv("SMART_DATA_AGENT_CRAWLER_SESSION_DIR", ".crawler-sessions").strip() or ".crawler-sessions")
    tenant_segment = _safe_path_segment(request.tenant_id or "tenant")
    crawler_segment = _safe_path_segment(identity.crawler_key)
    return str(root / tenant_segment / f"{crawler_segment}.json")


def _safe_path_segment(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value))
    return normalized[:120] or "default"
