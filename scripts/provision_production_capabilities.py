#!/usr/bin/env python3
"""Run the explicit, idempotent production Skill/Memory preparation job."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.platform.analysis_profiles import verify_loan_analysis_capabilities  # noqa: E402
from backend.platform.bootstrap import build_production_platform  # noqa: E402


def main() -> None:
    if os.getenv("SMART_DATA_AGENT_ENV", "").strip().lower() != "production":
        raise SystemExit("production_environment_required")
    if os.getenv("SMART_DATA_AGENT_CAPABILITY_MODE", "").strip().lower() != "seed":
        raise SystemExit("SMART_DATA_AGENT_CAPABILITY_MODE=seed is required")
    services = build_production_platform()
    try:
        result = verify_loan_analysis_capabilities(
            services.data_asset_store,
            services.memory_store,
        )
        print(
            json.dumps(
                {
                    "status": "prepared",
                    **result,
                    "canonical_topic_skills_activation": "active",
                    "institution_skill_copies": "forbidden",
                    "institution_memory_activation": "candidate",
                    "automatic_activation": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        services.close()


if __name__ == "__main__":
    main()
