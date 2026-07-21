from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import sys
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.platform.crawler_engine import CrawlerEngine, CrawlerOperation, CrawlerRequest
from backend.platform.crawler_engine.playwright_transport import PlaywrightCrawlerTransport
from backend.platform.crawler_engine.systems.qifu_focuspro_sios import QIFU_FUNNEL_PROFILE_ID


DEFAULT_URL = "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/funnelAnalysis"


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect all configured funnel-analysis filters into one CSV.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", default="output/funnel_analysis_all.csv")
    parser.add_argument("--storage-state", default=".crawler-sessions/qifu-funnel.json")
    parser.add_argument("--headed", action="store_true", help="Open a login window for captcha/MFA input.")
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument(
        "--allow-private-proxy-host",
        action="store_true",
        help="Allow only the target hostname when local proxy DNS resolves it to a non-public fake IP.",
    )
    parser.add_argument("--traversal-mode", choices=("cartesian", "independent"), default="cartesian")
    parser.add_argument("--max-combinations", type=int, default=2_000)
    parser.add_argument("--request-delay-ms", type=int, default=350)
    parser.add_argument("--staff-search-term", action="append", default=[])
    parser.add_argument("--statistical-date", action="append", default=[])
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

    connection = {
        "loginUrl": args.url,
        "queryPageUrl": args.url,
        "crawlerConfig": {
            "headless": not args.headed,
            "browserChannel": args.browser_channel,
            "storageStatePath": args.storage_state,
        },
    }
    script = {
        "version": 1,
        "metadata": {"profile_id": QIFU_FUNNEL_PROFILE_ID},
        "steps": [
            {"action": "goto", "url": "${query_page_url}", "timeout_ms": 60_000},
            {
                "action": "wait_for_url",
                "url_contains": "#/sios/funnelAnalysis",
                "manual": True,
                "timeout_ms": 900_000,
            },
            {"action": "wait", "selector": ".funnel-analysis-page", "timeout_ms": 60_000},
            {
                "action": "collect_system",
                "profile_id": QIFU_FUNNEL_PROFILE_ID,
                "api_base": "app-module:24915",
                "traversal_mode": args.traversal_mode,
                "max_combinations": args.max_combinations,
                "request_delay_ms": args.request_delay_ms,
                "max_rate_limit_retries": 6,
                "include_totals": True,
                "staff_search_terms": args.staff_search_term,
                "statistical_dates": args.statistical_date,
                "timeout_ms": 900_000,
            },
        ],
    }
    result = CrawlerEngine(transport=PlaywrightCrawlerTransport()).execute(
        CrawlerRequest(
            tenant_id="tenant_demo",
            operation_type=CrawlerOperation.DATA_QUERY,
            idempotency_key="qifu-funnel-analysis-manual",
            connection=connection,
            script=script,
            timeout_seconds=900,
        )
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in result.rows for key in row})
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.rows)
    print(f"CSV written: {output.resolve()}")
    print(f"Rows: {len(result.rows)}; combinations: {result.metadata.get('combination_count', 0)}")


def _append_host_pattern(current: str, host: str) -> str:
    values = [item.strip() for item in current.split(",") if item.strip()]
    if host not in values:
        values.append(host)
    return ",".join(values)


if __name__ == "__main__":
    main()
