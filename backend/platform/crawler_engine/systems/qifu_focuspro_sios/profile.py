from __future__ import annotations

from ...profile_registry import (
    CrawlerProfileCollection,
    CrawlerProfileContext,
    CrawlerProfileDescriptor,
)
from .business_sandbox_collector import collect_business_sandbox
from .collector import collect_funnel_analysis


QIFU_SYSTEM_ID = "qifu_focuspro_sios"
QIFU_FUNNEL_PROFILE_ID = "qifu_focuspro_sios.funnel_analysis.v1"
QIFU_BUSINESS_SANDBOX_PROFILE_ID = "qifu_focuspro_sios.business_sandbox.v1"
LEGACY_QIFU_FUNNEL_ACTION = "collect_funnel_analysis"
LEGACY_QIFU_BUSINESS_SANDBOX_ACTION = "collect_business_sandbox"


class QifuFunnelAnalysisProfile:
    """Owns the Qifu funnel API contract, filter traversal, and row mapping."""

    descriptor = CrawlerProfileDescriptor(
        profile_id=QIFU_FUNNEL_PROFILE_ID,
        system_id=QIFU_SYSTEM_ID,
        display_name="奇富 FocusPro SIOS 漏斗分析",
        version=1,
        supported_operations=("data_query",),
        maintainer="crawler_engine.systems.qifu_focuspro_sios",
        description="遍历漏斗分析筛选条件并输出统一明细行。",
    )

    def collect(self, context: CrawlerProfileContext) -> CrawlerProfileCollection:
        result = collect_funnel_analysis(context.page, context.step)
        return CrawlerProfileCollection(rows=tuple(result.rows), metadata=dict(result.metadata))


class QifuBusinessSandboxProfile:
    """Owns the Qifu business-sandbox filters, sections, trends, and row mapping."""

    descriptor = CrawlerProfileDescriptor(
        profile_id=QIFU_BUSINESS_SANDBOX_PROFILE_ID,
        system_id=QIFU_SYSTEM_ID,
        display_name="奇富 FocusPro SIOS 经营沙盘",
        version=1,
        supported_operations=("data_query",),
        maintainer="crawler_engine.systems.qifu_focuspro_sios",
        description="遍历经营沙盘机构、产品、时间条件，采集全部板块指标与绩效趋势。",
    )

    def collect(self, context: CrawlerProfileContext) -> CrawlerProfileCollection:
        result = collect_business_sandbox(
            context.page,
            {**context.step, "checkpoint_run_key": context.request.idempotency_key},
        )
        return CrawlerProfileCollection(rows=tuple(result.rows), metadata=dict(result.metadata))
