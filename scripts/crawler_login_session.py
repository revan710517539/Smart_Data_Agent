from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path

from playwright.sync_api import sync_playwright


DEFAULT_URL = "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/funnelAnalysis"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a protected crawler browser session after manual captcha/MFA.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--storage-state", default=".crawler-sessions/qifu-funnel-provided-account.json")
    parser.add_argument("--browser-channel", default="chrome")
    args = parser.parse_args()

    account = input("Account: ")
    password = getpass("Password: ")
    state_path = Path(args.storage_state)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, channel=args.browser_channel)
        context = browser.new_context()
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        page.locator('input[placeholder="请输入邮箱或手机号"]').fill(account, timeout=60_000)
        page.locator('input[placeholder="请输入密码"]').fill(password, timeout=60_000)
        account = password = ""
        print("Credentials filled. Enter the captcha in Chrome and click Login.", flush=True)
        page.locator(".funnel-analysis-page").wait_for(timeout=900_000)
        page.wait_for_timeout(2_500)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        state_path.chmod(0o600)
        print(f"Login session saved: {state_path}", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
