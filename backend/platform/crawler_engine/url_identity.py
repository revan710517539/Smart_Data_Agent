from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


QIFU_BUSINESS_SANDBOX_PROFILE_ID = "qifu_focuspro_sios.business_sandbox.v1"
QIFU_FUNNEL_PROFILE_ID = "qifu_focuspro_sios.funnel_analysis.v1"
QIFU_YUSHU_MY_QUERIES_PROFILE_ID = "qifu_yushu.my_queries.v1"


@dataclass(frozen=True)
class CrawlerUrlIdentity:
    """Stable crawler instance identity derived from one registered page URL."""

    crawler_key: str
    page_url: str
    mode: str
    profile_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def build_crawler_url_identity(connection: dict[str, Any]) -> CrawlerUrlIdentity | None:
    mode = infer_crawler_mode(connection)
    if not mode:
        return None
    page_url = normalize_crawler_page_url(
        str(connection.get("queryPageUrl") or connection.get("apiUrl") or "")
    )
    if not page_url:
        return None
    profile_id = str(connection.get("crawlerProfileId") or "").strip()
    if not profile_id and "ghbank-focuspro-sios.qifu.tech" in page_url:
        fragment = page_url.lower()
        if "#/sios/businesssandbox" in fragment:
            profile_id = QIFU_BUSINESS_SANDBOX_PROFILE_ID
        elif "#/sios/funnelanalysis" in fragment:
            profile_id = QIFU_FUNNEL_PROFILE_ID
    if not profile_id and "union-yushu.qifu.tech" in page_url and "/bolt/dataquery" in page_url.lower():
        profile_id = QIFU_YUSHU_MY_QUERIES_PROFILE_ID
    return CrawlerUrlIdentity(
        crawler_key=f"url_{hashlib.sha256(page_url.encode('utf-8')).hexdigest()[:24]}",
        page_url=page_url,
        mode=mode,
        profile_id=profile_id,
    )


def infer_crawler_mode(connection: dict[str, Any]) -> str:
    explicit = str(connection.get("crawlerMode") or "").strip().lower()
    if explicit in {"page", "sql"}:
        return explicit
    source_type = str(connection.get("sourceType") or "").strip().casefold()
    if "sql" in source_type or ("毓数" in source_type and ("爬虫" in source_type or "crawler" in source_type)):
        return "sql"
    if "页面" in source_type or "智运" in source_type or "爬虫" in source_type or "crawler" in source_type:
        return "page"
    return ""


def normalize_crawler_page_url(value: str) -> str:
    source = str(value or "").strip()
    if not source:
        return ""
    parsed = urlsplit(source)
    if not parsed.scheme or not parsed.netloc:
        return source
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = hostname if not port or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, parsed.fragment))


__all__ = [
    "QIFU_BUSINESS_SANDBOX_PROFILE_ID",
    "QIFU_FUNNEL_PROFILE_ID",
    "QIFU_YUSHU_MY_QUERIES_PROFILE_ID",
    "CrawlerUrlIdentity",
    "build_crawler_url_identity",
    "infer_crawler_mode",
    "normalize_crawler_page_url",
]
