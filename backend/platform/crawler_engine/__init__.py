"""Governed browser crawler boundary for external data platforms."""

from .contracts import (
    CrawlerDiagnostic,
    CrawlerExecutionError,
    CrawlerOperation,
    CrawlerRequest,
    CrawlerResult,
)
from .engine import CrawlerEngine
from .profile_registry import (
    CrawlerProfileCollection,
    CrawlerProfileContext,
    CrawlerProfileDescriptor,
    CrawlerProfileRegistry,
    CrawlerSystemProfile,
    get_default_crawler_profile_registry,
)
from .sql_parser import SQLDecomposition, SQLDecomposer
from .url_identity import CrawlerUrlIdentity, build_crawler_url_identity, infer_crawler_mode

__all__ = [
    "CrawlerDiagnostic",
    "CrawlerEngine",
    "CrawlerExecutionError",
    "CrawlerOperation",
    "CrawlerProfileCollection",
    "CrawlerProfileContext",
    "CrawlerProfileDescriptor",
    "CrawlerProfileRegistry",
    "CrawlerRequest",
    "CrawlerResult",
    "CrawlerSystemProfile",
    "CrawlerUrlIdentity",
    "SQLDecomposition",
    "SQLDecomposer",
    "build_crawler_url_identity",
    "get_default_crawler_profile_registry",
    "infer_crawler_mode",
]
