"""Compatibility import for the pre-registry Qifu funnel collector path.

New code should use the registered profile instead of importing a system
collector from the crawler-engine root.
"""

from .systems.qifu_focuspro_sios.collector import (
    FunnelAPIError,
    FunnelCollection,
    collect_funnel_analysis,
)

__all__ = ["FunnelAPIError", "FunnelCollection", "collect_funnel_analysis"]
