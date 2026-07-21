from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def ensure_business_sandbox_login_session(
    *,
    connection: dict[str, Any],
    page_url: str,
    storage_state: Path,
    browser_channel: str = "chrome",
) -> None:
    """Create or refresh a FocusPro session without opening a visible browser."""

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

    account = str(connection.get("account") or "")
    password = str(connection.get("password") or "")
    if not account or not password:
        raise ValueError("business_sandbox_credentials_required")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=browser_channel)
        context_options: dict[str, Any] = {
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
        try:
            page = context.new_page()
            page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5_000)
            if not is_target(page.url) or page.title().strip() == "统一登录平台":
                captcha_input = page.locator('input[placeholder="请输入验证码"]')
                captcha_input.wait_for(state="visible", timeout=60_000)
                last_error = ""
                for attempt in range(1, 9):
                    captcha_image = page.locator('img[src*="/user/captcha"]')
                    captcha_image.wait_for(state="visible", timeout=30_000)
                    try:
                        captcha = recognize_digit_captcha(captcha_image.screenshot(), expected_length=4)
                    except CaptchaRecognitionError as exc:
                        last_error = str(exc)
                        captcha_image.click()
                        page.wait_for_timeout(400 + attempt * 75)
                        continue
                    page.locator('input[placeholder="请输入邮箱或手机号"]').fill(account)
                    page.locator('input[placeholder="请输入密码"]').fill(password)
                    captcha_input.fill(captcha)
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
                    captcha_image.click()
                    page.wait_for_timeout(500 + attempt * 100)
                else:
                    raise RuntimeError(f"captcha_automatic_recognition_exhausted:{last_error}")
            storage_state.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(storage_state))
            storage_state.chmod(0o600)
        finally:
            context.close()
            browser.close()
