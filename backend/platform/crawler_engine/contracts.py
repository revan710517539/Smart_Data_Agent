from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class CrawlerOperation(StrEnum):
    CONNECTIVITY_TEST = "connectivity_test"
    DATA_QUERY = "data_query"
    METADATA_QUERY = "metadata_query"


class CrawlerErrorCode(StrEnum):
    LOGIN_FAILED = "LOGIN_FAILED"
    ACCOUNT_EXPIRED = "ACCOUNT_EXPIRED"
    PAGE_CHANGED = "PAGE_CHANGED"
    SQL_PARSE_FAILED = "SQL_PARSE_FAILED"
    RAW_TABLE_PARSE_FAILED = "RAW_TABLE_PARSE_FAILED"
    METADATA_FETCH_FAILED = "METADATA_FETCH_FAILED"
    SQL_EXECUTION_FAILED = "SQL_EXECUTION_FAILED"
    CSV_DOWNLOAD_FAILED = "CSV_DOWNLOAD_FAILED"
    CSV_SCHEMA_CHANGED = "CSV_SCHEMA_CHANGED"
    EMPTY_RESULT = "EMPTY_RESULT"
    NETWORK_ERROR = "NETWORK_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"
    TRANSPORT_NOT_CONFIGURED = "TRANSPORT_NOT_CONFIGURED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass(frozen=True)
class CrawlerDiagnostic:
    error_code: str
    summary: str
    failed_step: str = ""
    page_url: str = ""
    page_title: str = ""
    dom_summary: str = ""
    screenshot_sha256: str = ""
    network_summary: tuple[dict[str, Any], ...] = ()
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CrawlerRequest:
    tenant_id: str
    operation_type: CrawlerOperation
    idempotency_key: str
    connection: dict[str, Any] = field(repr=False)
    org_id: str | None = None
    topic_table_id: str | None = None
    connection_version_id: str | None = None
    script_version_id: str | None = None
    readonly_sql: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    script: dict[str, Any] = field(default_factory=dict, repr=False)
    timeout_seconds: int = 240


@dataclass(frozen=True)
class CrawlerResult:
    status: str
    rows: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    source_snapshot: dict[str, Any] = field(default_factory=dict)
    output_cursor: dict[str, Any] = field(default_factory=dict)
    schema_hash: str = ""
    error_code: str | None = None

    @property
    def rows_read(self) -> int:
        return len(self.rows)


class CrawlerExecutionError(RuntimeError):
    def __init__(self, error_code: str, summary: str, diagnostic: CrawlerDiagnostic | None = None) -> None:
        super().__init__(error_code)
        self.error_code = str(error_code)
        self.summary = str(summary)
        self.diagnostic = diagnostic or CrawlerDiagnostic(self.error_code, self.summary)
