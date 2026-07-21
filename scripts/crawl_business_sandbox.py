from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.platform.bootstrap import build_local_platform
from backend.platform.crawler_engine import CrawlerEngine, build_crawler_url_identity
from backend.platform.crawler_engine.playwright_transport import PlaywrightCrawlerTransport


DEFAULT_URL = "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/businessSandbox"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Use a registered system connection to crawl FocusPro SIOS business-sandbox data."
    )
    parser.add_argument("--db", default=".smart_data_agent.sqlite")
    parser.add_argument("--tenant", default="tenant:华兴银行")
    parser.add_argument("--connection-id", default="")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--headed", action="store_true", help="Debug only: show the crawler browser window.")
    parser.add_argument(
        "--captcha-stdin",
        action="store_true",
        help="Emergency fallback only: read the captcha from stdin when local OCR is unavailable.",
    )
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--storage-state", default=".crawler-sessions/qifu-business-sandbox.json")
    parser.add_argument("--checkpoint", default=".crawler-checkpoints/qifu-business-sandbox.jsonl")
    parser.add_argument(
        "--traversal-mode",
        choices=("current", "cartesian", "independent"),
        default="current",
    )
    parser.add_argument("--max-combinations", type=int, default=10_000)
    parser.add_argument("--request-delay-min-ms", type=int, default=250)
    parser.add_argument("--request-delay-max-ms", type=int, default=500)
    parser.add_argument("--max-rate-limit-retries", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--batch-concurrency", type=int, default=1)
    parser.add_argument("--statistical-date", action="append", default=[])
    parser.add_argument(
        "--allow-private-proxy-host",
        action="store_true",
        help="Allow only the target host when local proxy DNS maps it to a private fake IP.",
    )
    args = parser.parse_args()

    if args.allow_private_proxy_host:
        host = str(urlparse(args.url).hostname or "").strip().lower()
        if not host:
            raise ValueError("crawler_target_hostname_required")
        os.environ["SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS"] = _append_host_pattern(
            os.getenv("SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS", ""), host
        )
        if os.getenv("SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS", "").strip():
            os.environ["SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS"] = _append_host_pattern(
                os.getenv("SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS", ""), host
            )

    services = build_local_platform(Path(args.db))
    try:
        connection = _registered_connection(
            services.system_config_store,
            tenant_id=args.tenant,
            connection_id=args.connection_id,
            page_url=args.url,
        )
        _ensure_login_session(
            connection=connection,
            page_url=args.url,
            storage_state=Path(args.storage_state).resolve(),
            browser_channel=args.browser_channel,
            allow_stdin_fallback=args.captcha_stdin,
        )
        config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
        config = {key: value for key, value in config.items() if key != "requestDelayMs"}
        connection = services.data_acquisition_service.ensure_crawler_connection(
            args.tenant,
            {
                **connection,
                "crawlerConfig": {
                    **config,
                    "headless": not args.headed,
                    "browserChannel": args.browser_channel,
                    "storageStatePath": str(Path(args.storage_state).resolve()),
                    "checkpointPath": str(Path(args.checkpoint).resolve()),
                    "traversalMode": args.traversal_mode,
                    "maxCombinations": args.max_combinations,
                    "requestDelayMinMs": args.request_delay_min_ms,
                    "requestDelayMaxMs": args.request_delay_max_ms,
                    "maxRateLimitRetries": args.max_rate_limit_retries,
                    "batchSize": args.batch_size,
                    "batchConcurrency": args.batch_concurrency,
                    "statisticalDates": args.statistical_date,
                    "includeTotals": True,
                    "includeCurrentDate": True,
                },
            },
            "u_admin",
        )
        services.data_acquisition_service.crawler_engine = CrawlerEngine(
            transport=PlaywrightCrawlerTransport()
        )
        result = services.data_acquisition_service.validate_and_run_crawler(
            args.tenant,
            str(connection["id"]),
            "u_admin",
            "qifu-business-sandbox-manual",
        )
        print(f"Crawl succeeded: {result['row_count']} rows")
        print(f"CSV: {result['csv_path']}")
        print(f"Raw table asset: {result['raw_table_asset']['id']}")
        print(f"Automation task: {result['automation_task']['automation_task_id']}")
    finally:
        services.close()


def _registered_connection(store: object, *, tenant_id: str, connection_id: str, page_url: str) -> dict:
    if connection_id:
        connection = store.get_data_connection(tenant_id, connection_id, reveal_secret=True)
        if not connection:
            raise KeyError("data_connection_not_found")
        return connection
    target_identity = build_crawler_url_identity(
        {"sourceType": "智运平台（页面爬虫）", "queryPageUrl": page_url}
    )
    if target_identity is None:
        raise ValueError("crawler_page_url_required")
    matches = []
    for connection in store.list_data_connections(tenant_id, reveal_secret=True):
        identity = build_crawler_url_identity(connection)
        if identity and identity.page_url == target_identity.page_url:
            matches.append(connection)
    if not matches:
        raise KeyError("business_sandbox_data_connection_not_found")
    if len(matches) > 1:
        raise ValueError("duplicate_business_sandbox_data_connections")
    return matches[0]


def _ensure_login_session(
    *,
    connection: dict,
    page_url: str,
    storage_state: Path,
    browser_channel: str,
    allow_stdin_fallback: bool,
) -> None:
    from playwright.sync_api import sync_playwright

    from backend.platform.crawler_engine.captcha_ocr import (
        CaptchaRecognitionError,
        recognize_digit_captcha,
    )

    target = urlsplit(page_url)

    def is_target(value: str) -> bool:
        actual = urlsplit(value)
        return (
            actual.scheme.lower() == target.scheme.lower()
            and actual.netloc.lower() == target.netloc.lower()
            and actual.path.rstrip("/") == target.path.rstrip("/")
            and actual.fragment.casefold() == target.fragment.casefold()
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=browser_channel)
        context_options = {
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "viewport": {"width": 1440, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
            ),
            "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        }
        if storage_state.is_file():
            context_options["storage_state"] = str(storage_state)
        context = browser.new_context(**context_options)
        page = context.new_page()
        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5_000)
        if not is_target(page.url) or page.title().strip() == "统一登录平台":
            captcha_input = page.locator('input[placeholder="请输入验证码"]')
            captcha_input.wait_for(state="visible", timeout=60_000)
            account = str(connection.get("account") or "")
            password = str(connection.get("password") or "")
            if not account or not password:
                raise ValueError("business_sandbox_credentials_required")
            last_error = ""
            for attempt in range(1, 9):
                captcha_image = page.locator('img[src*="/user/captcha"]')
                captcha_image.wait_for(state="visible", timeout=30_000)
                try:
                    captcha = recognize_digit_captcha(captcha_image.screenshot(), expected_length=4)
                except CaptchaRecognitionError as exc:
                    if allow_stdin_fallback:
                        captcha = input("Captcha: ").strip()
                    else:
                        last_error = str(exc)
                        captcha_image.click()
                        page.wait_for_timeout(400 + (attempt * 75))
                        continue
                page.locator('input[placeholder="请输入邮箱或手机号"]').fill(account)
                page.locator('input[placeholder="请输入密码"]').fill(password)
                captcha_input.fill(captcha)
                captcha = ""
                page.get_by_role("button", name="登录", exact=True).click()
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if is_target(page.url) and page.title().strip() != "统一登录平台":
                        page.wait_for_timeout(3_000)
                        if is_target(page.url) and page.title().strip() != "统一登录平台":
                            break
                    page.wait_for_timeout(300)
                if is_target(page.url) and page.title().strip() != "统一登录平台":
                    break
                body = page.locator("body").inner_text()[:2_000]
                last_error = next(
                    (
                        line.strip()
                        for line in body.splitlines()
                        if "验证码" in line or "密码" in line or "账号" in line or "用户" in line
                    ),
                    "captcha_login_failed",
                )
                if any(token in last_error for token in ("密码错误", "账号不存在", "用户不存在", "账号已锁定")):
                    raise RuntimeError(f"business_sandbox_credential_error:{last_error}")
                captcha_input = page.locator('input[placeholder="请输入验证码"]')
                captcha_image = page.locator('img[src*="/user/captcha"]')
                captcha_image.click()
                page.wait_for_timeout(500 + (attempt * 100))
            else:
                failure_path = PROJECT_ROOT / "output" / "qifu-business-sandbox-captcha-failed.png"
                failure_path.parent.mkdir(parents=True, exist_ok=True)
                page.locator('img[src*="/user/captcha"]').screenshot(path=str(failure_path))
                raise RuntimeError(f"captcha_automatic_recognition_exhausted:{last_error}")
            account = password = ""
        storage_state.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(storage_state))
        storage_state.chmod(0o600)
        browser.close()


def _append_host_pattern(current: str, host: str) -> str:
    values = [item.strip() for item in current.split(",") if item.strip()]
    if host not in values:
        values.append(host)
    return ",".join(values)


if __name__ == "__main__":
    main()
