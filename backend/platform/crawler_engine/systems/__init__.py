"""Built-in crawler systems.

This module is the single composition root. Individual system packages must
not import each other or be imported directly by the browser transport.
"""

from typing import Any


def built_in_crawler_profiles() -> tuple[tuple[Any, tuple[str, ...]], ...]:
    from .qifu_focuspro_sios import (
        LEGACY_QIFU_BUSINESS_SANDBOX_ACTION,
        LEGACY_QIFU_FUNNEL_ACTION,
        QifuBusinessSandboxProfile,
        QifuFunnelAnalysisProfile,
    )

    return (
        (QifuBusinessSandboxProfile(), (LEGACY_QIFU_BUSINESS_SANDBOX_ACTION,)),
        (QifuFunnelAnalysisProfile(), (LEGACY_QIFU_FUNNEL_ACTION,)),
    )


__all__ = ["built_in_crawler_profiles"]
