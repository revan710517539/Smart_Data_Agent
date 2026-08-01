from __future__ import annotations

import json
import re
from typing import Any

from backend.platform.security.sql_validation import validate_read_only_sql_candidate
from .sandbox import RestrictedRowTransformSandbox


class ModelAcquisitionRepairGenerator:
    """Generate a reviewed candidate only; never changes the active script."""

    def __init__(self, system_config_store: Any, transform_sandbox: RestrictedRowTransformSandbox) -> None:
        self.system_config_store = system_config_store
        self.transform_sandbox = transform_sandbox

    def generate(
        self,
        tenant_id: str,
        failed_version: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> dict[str, Any] | None:
        runtime = str(failed_version.get("runtime") or "").strip()
        # CSV sources are read-only.  There is no page script or external
        # source configuration to repair here; the producer must correct the
        # source CSV and the catalog will refresh automatically.
        return {
            "candidate_source_code": None,
            "model_call": {
                "status": "skipped",
                "error_code": "csv_source_repair_requires_file_update",
                "runtime": runtime,
            },
        }
