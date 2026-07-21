from __future__ import annotations

from typing import Protocol

from .contracts import CrawlerRequest, CrawlerResult


class CrawlerTransport(Protocol):
    name: str

    def execute(self, request: CrawlerRequest) -> CrawlerResult: ...

