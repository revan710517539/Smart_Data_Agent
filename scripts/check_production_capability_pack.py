#!/usr/bin/env python3
"""Validate the governed Skill/Memory pack without activating candidates."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.platform.analysis_profiles import (  # noqa: E402
    SOURCE_PATH,
    load_analysis_profiles,
    prepare_loan_analysis_capabilities,
)
from backend.platform.assets.store import (  # noqa: E402
    InMemoryDataAssetStore,
    PLATFORM_ANALYSIS_SKILL_IDS,
    PLATFORM_TOOL_IDS,
)
from backend.platform.memory import InMemoryMemoryStore  # noqa: E402


BASE_SKILL_IDS = set(PLATFORM_ANALYSIS_SKILL_IDS)


def main() -> None:
    profiles = load_analysis_profiles()
    sources = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    source_items = sources.get("sources") if isinstance(sources, dict) else None
    if sources.get("schemaVersion") != 1 or not isinstance(source_items, list) or len(source_items) != 12:
        raise SystemExit("loan_analysis_source_registry_invalid")
    names = [str(item.get("name") or "").strip() for item in source_items if isinstance(item, dict)]
    hashes = [str(item.get("sha256") or "").strip().lower() for item in source_items if isinstance(item, dict)]
    if len(names) != 12 or len(set(names)) != 12:
        raise SystemExit("loan_analysis_source_names_invalid")
    if len(hashes) != 12 or len(set(hashes)) != 12 or not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
        raise SystemExit("loan_analysis_source_hashes_invalid")
    policy = sources.get("policy") if isinstance(sources.get("policy"), dict) else {}
    if policy.get("rawDocumentsCommitted") is not False or policy.get("personalDetailsCopied") is not False:
        raise SystemExit("loan_analysis_source_privacy_policy_invalid")

    assets = InMemoryDataAssetStore(seed_defaults=False)
    memories = InMemoryMemoryStore()
    try:
        first = prepare_loan_analysis_capabilities(assets, memories, import_actor="system")
        second = prepare_loan_analysis_capabilities(assets, memories, import_actor="system")
        if first.get("skills_merged") != 33 or first.get("institution_skills_archived") != 0 or first.get("memories_created") != 110:
            raise SystemExit("production_capability_pack_count_invalid")
        if second.get("skills_merged") != 0 or second.get("institution_skills_archived") != 0 or second.get("memories_created") != 0:
            raise SystemExit("production_capability_pack_not_idempotent")
        for profile in profiles["institutions"]:
            tenant_id = str(profile["tenantId"])
            items = assets.list_bundle(tenant_id)["analysis_skills"]
            if any(str(item.get("id") or "").startswith("institution.") for item in items):
                raise SystemExit(f"institution_skill_duplicate:{tenant_id}")
            published = assets.list_published_bundle(tenant_id)["analysis_skills"]
            published_ids = {str(item.get("id") or "") for item in published}
            if not BASE_SKILL_IDS.issubset(published_ids):
                raise SystemExit(f"institution_base_skill_missing:{tenant_id}")
            canonical = [item for item in published if str(item.get("id") or "") in {"topic-descriptive", "topic-attribution", "topic-predictive"}]
            if len(canonical) != 3 or any(len(item.get("memoryRefs") or []) < 10 for item in canonical):
                raise SystemExit(f"canonical_topic_skill_memory_invalid:{tenant_id}")
            tool_ids = {str(item.get("id") or "") for item in assets.list_published_bundle(tenant_id)["external_tools"]}
            if not set(PLATFORM_TOOL_IDS).issubset(tool_ids):
                raise SystemExit(f"institution_platform_tool_missing:{tenant_id}")
            catalog_experiences = {
                str(item.get("id") or "")
                for item in assets.list_published_bundle(tenant_id)["analysis_experiences"]
            }
            memory_items = memories.search(tenant_id, statuses=("candidate",), limit=20)
            if len(memory_items) != 10 or any(item.created_by != "system" for item in memory_items):
                raise SystemExit(f"institution_memory_candidate_invalid:{tenant_id}")
            if any(item.memory_id not in catalog_experiences for item in memory_items):
                raise SystemExit(f"institution_memory_catalog_missing:{tenant_id}")

        base = InMemoryDataAssetStore(seed_defaults=True).list_bundle("tenant_demo")["analysis_skills"]
        base_ids = {str(item.get("id") or "") for item in base}
        if not BASE_SKILL_IDS.issubset(base_ids):
            raise SystemExit("base_scene_skill_pack_incomplete")
    finally:
        memories.close()

    print(
        json.dumps(
            {
                "status": "passed",
                "source_count": 12,
                "institution_count": 11,
                "base_skill_count": len(BASE_SKILL_IDS),
                "canonical_topic_skill_merges": 33,
                "institution_skill_duplicates": 0,
                "memory_candidates": 110,
                "activation": profiles.get("activation"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
