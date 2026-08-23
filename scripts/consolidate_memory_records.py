#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.platform.assets.postgresql_store import PostgreSQLDataAssetStore
from backend.platform.database import MySQLConnectionPool, MySQLStoreConnectionPool
from backend.platform.memory.fusion import fuse_payloads, fuse_record_content, memory_identity
from backend.platform.memory.models import MemoryRecord
from backend.platform.memory.postgresql_store import PostgreSQLMemoryStore


CURRENT_MEMORY_STATUSES = {"candidate", "review", "active"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolidate duplicate tenant memories by topic and action.")
    parser.add_argument("--tenant", action="append", default=[], help="Tenant code; repeat to limit scope.")
    parser.add_argument("--apply", action="store_true", help="Apply the plan. Default is read-only dry-run.")
    parser.add_argument("--backup", help="Required with --apply; secure JSON backup path outside the repository.")
    parser.add_argument(
        "--repair-from-backup",
        help="Recompute already-created fused counts from an exact pre-cleanup backup.",
    )
    parser.add_argument("--actor", default="u_super_admin", help="Existing reviewer-capable external user id.")
    args = parser.parse_args()
    database_url = os.getenv("SMART_DATA_AGENT_DATABASE_URL", "").strip()
    if not database_url.lower().startswith(("mysql://", "mysql+pymysql://")):
        raise SystemExit("SMART_DATA_AGENT_DATABASE_URL must point to MySQL")
    if args.apply and not args.backup:
        raise SystemExit("--backup is required with --apply")
    if args.apply and args.repair_from_backup:
        raise SystemExit("--apply and --repair-from-backup are mutually exclusive")

    raw_pool = MySQLConnectionPool(database_url, min_size=1, max_size=4)
    compat_pool = MySQLStoreConnectionPool(raw_pool)
    assets = PostgreSQLDataAssetStore(compat_pool)
    memories = PostgreSQLMemoryStore(compat_pool)
    try:
        if args.repair_from_backup:
            result = _repair_from_backup(raw_pool, Path(args.repair_from_backup))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        snapshot = _snapshot(raw_pool, set(args.tenant))
        plan = _build_plan(snapshot)
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", **_plan_summary(plan)}, ensure_ascii=False, indent=2))
        if not args.apply:
            return 0
        backup_path = _write_backup(Path(args.backup), snapshot, plan)
        result = _apply_plan(raw_pool, assets, memories, plan, actor=args.actor)
        result["backup"] = str(backup_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        raw_pool.close()


def _snapshot(pool: MySQLConnectionPool, tenant_filter: set[str]) -> dict[str, Any]:
    with pool.connection() as connection, connection.cursor() as cursor:
        tenant_where = "WHERE tenant_code IN (%s)" % ",".join(["%s"] * len(tenant_filter)) if tenant_filter else ""
        cursor.execute(
            f"SELECT tenant_id, tenant_code FROM platform_tenants {tenant_where} ORDER BY tenant_code",
            tuple(sorted(tenant_filter)),
        )
        tenants = list(cursor.fetchall())
        tenant_ids = [row["tenant_id"] for row in tenants]
        if not tenant_ids:
            return {"tenants": [], "asset_items": [], "skill_memory_refs": {}, "memory_records": [], "memory_evidence": []}
        placeholders = ",".join(["%s"] * len(tenant_ids))
        cursor.execute(
            f"""
            SELECT i.asset_item_id, i.tenant_id, t.tenant_code, i.item_type, i.item_code,
                   i.status, i.payload, i.updated_at, i.lock_version
            FROM platform_data_asset_items i
            JOIN platform_tenants t ON t.tenant_id = i.tenant_id
            WHERE i.tenant_id IN ({placeholders})
              AND i.item_type IN ('analysis_experience','user_behavior_habit')
              AND i.status <> 'archived'
            ORDER BY t.tenant_code, i.item_type, i.updated_at, i.item_code
            """,
            tuple(tenant_ids),
        )
        asset_items = [_json_row(row, "payload") for row in cursor.fetchall()]
        cursor.execute(
            f"""
            SELECT t.tenant_code, i.payload
            FROM platform_data_asset_items i
            JOIN platform_tenants t ON t.tenant_id = i.tenant_id
            WHERE i.tenant_id IN ({placeholders})
              AND i.item_type = 'analysis_skill'
              AND i.status <> 'archived'
            ORDER BY t.tenant_code, i.item_code
            """,
            tuple(tenant_ids),
        )
        skill_memory_refs: dict[str, list[str]] = {}
        for row in cursor.fetchall():
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else dict(row["payload"] or {})
            references = [str(value) for value in (payload.get("memoryRefs") or []) if str(value).strip()]
            skill_memory_refs.setdefault(str(row["tenant_code"]), []).extend(references)
        cursor.execute(
            f"""
            SELECT m.memory_id, m.tenant_id, t.tenant_code, m.memory_key, m.memory_type,
                   m.subject_type, m.subject_id, m.title, m.content, m.content_hash,
                   m.status, m.confidence, m.weight, m.valid_from, m.expires_at,
                   m.supersedes_memory_id, m.source_trace_id, m.created_by,
                   m.created_at, m.updated_at
            FROM platform_memory_records m
            JOIN platform_tenants t ON t.tenant_id = m.tenant_id
            WHERE m.tenant_id IN ({placeholders})
              AND m.memory_type IN ('analysis_case','behavior_habit')
              AND m.status IN ('candidate','review','active')
            ORDER BY t.tenant_code, m.memory_type, m.subject_type, m.subject_id, m.updated_at, m.memory_key
            """,
            tuple(tenant_ids),
        )
        memory_records = [_json_row(row, "content") for row in cursor.fetchall()]
        memory_ids = [row["memory_id"] for row in memory_records]
        evidence: list[dict[str, Any]] = []
        if memory_ids:
            evidence_placeholders = ",".join(["%s"] * len(memory_ids))
            cursor.execute(
                f"SELECT * FROM platform_memory_evidence WHERE memory_id IN ({evidence_placeholders}) ORDER BY created_at, memory_evidence_id",
                tuple(memory_ids),
            )
            evidence = [_serializable_row(row) for row in cursor.fetchall()]
    return {
        "tenants": [_serializable_row(row) for row in tenants],
        "asset_items": asset_items,
        "skill_memory_refs": {tenant: sorted(set(values)) for tenant, values in skill_memory_refs.items()},
        "memory_records": memory_records,
        "memory_evidence": evidence,
    }


def _build_plan(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    asset_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in snapshot["asset_items"]:
        payload = dict(row["payload"])
        identity = memory_identity(str(row["item_type"]), payload)
        asset_groups.setdefault((str(row["tenant_code"]), str(row["item_type"]), identity.merge_key), []).append(row)

    memory_groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in snapshot["memory_records"]:
        identity = memory_identity(str(row["memory_type"]), dict(row["content"]), title=str(row["title"]))
        key = (
            str(row["tenant_code"]),
            str(row["memory_type"]),
            str(row["subject_type"]),
            str(row["subject_id"]),
            identity.merge_key,
        )
        memory_groups.setdefault(key, []).append(row)

    assets = [
        _asset_plan(rows, set(snapshot.get("skill_memory_refs", {}).get(str(rows[0]["tenant_code"]), [])))
        for rows in asset_groups.values()
        if len(rows) > 1
    ]
    memories = [_memory_plan(rows) for rows in memory_groups.values() if len(rows) > 1]
    return {"asset_groups": assets, "memory_groups": memories}


def _asset_plan(rows: list[dict[str, Any]], referenced_ids: set[str]) -> dict[str, Any]:
    latest = max(rows, key=lambda row: (_timestamp(row.get("updated_at")), str(row.get("item_code") or "")))
    referenced_group_ids = sorted({str(row["item_code"]) for row in rows} & referenced_ids)
    canonical_id = referenced_group_ids[0] if len(referenced_group_ids) == 1 else str(latest["item_code"])
    has_active = any(str(row["status"]) == "active" for row in rows)
    has_ambiguous_references = len(referenced_group_ids) > 1
    return {
        "tenant": latest["tenant_code"],
        "item_type": latest["item_type"],
        "canonical_id": canonical_id,
        "duplicate_ids": [row["item_code"] for row in rows if row["item_code"] != canonical_id],
        "referenced_ids": referenced_group_ids,
        "statuses": sorted({str(row["status"]) for row in rows}),
        "payload": latest["payload"],
        "apply": not has_active and not has_ambiguous_references,
        "reason": (
            "active_asset_requires_human_review"
            if has_active
            else "multiple_skill_references_require_human_review"
            if has_ambiguous_references
            else "same_topic_and_action"
        ),
    }


def _memory_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = max(rows, key=lambda row: (_timestamp(row.get("updated_at")), str(row.get("memory_key") or "")))
    statuses = {str(row["status"]) for row in rows}
    identity = memory_identity(str(latest["memory_type"]), dict(latest["content"]), title=str(latest["title"]))
    digest = hashlib.sha256(
        "|".join(
            (
                str(latest["tenant_code"]),
                str(latest["memory_type"]),
                str(latest["subject_type"]),
                str(latest["subject_id"]),
                identity.merge_key,
            )
        ).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "tenant": latest["tenant_code"],
        "memory_type": latest["memory_type"],
        "subject_type": latest["subject_type"],
        "subject_id": latest["subject_id"],
        "canonical_id": f"mem_fused_{digest}",
        "source_ids": [row["memory_key"] for row in rows],
        "source_database_ids": [str(row["memory_id"]) for row in rows],
        "statuses": sorted(statuses),
        "title": latest["title"],
        # The store performs the actual fusion under a transaction lock.  Pass
        # only the newest payload here so occurrence counts are not added twice.
        "content": dict(latest["content"]),
        "source_trace_id": latest.get("source_trace_id"),
        "confidence": max(float(row.get("confidence") or 0) for row in rows),
        "weight": max(float(row.get("weight") or 0) for row in rows),
        "apply": "active" not in statuses,
        "reason": "active_memory_requires_human_review" if "active" in statuses else "same_topic_and_action",
    }


def _apply_plan(
    raw_pool: MySQLConnectionPool,
    assets: PostgreSQLDataAssetStore,
    memories: PostgreSQLMemoryStore,
    plan: dict[str, list[dict[str, Any]]],
    *,
    actor: str,
) -> dict[str, Any]:
    asset_applied = 0
    memory_applied = 0
    skipped = 0
    for group in plan["asset_groups"]:
        if not group["apply"]:
            skipped += 1
            continue
        assets.upsert_item(
            group["tenant"],
            group["item_type"],
            {**group["payload"], "id": group["canonical_id"]},
            updated_by=actor,
            lifecycle_status="review",
            consolidate_existing=True,
        )
        asset_applied += 1

    for group in plan["memory_groups"]:
        if not group["apply"]:
            skipped += 1
            continue
        created = memories.write(
            MemoryRecord(
                memory_id=group["canonical_id"],
                memory_type=group["memory_type"],
                tenant_id=group["tenant"],
                subject=group["title"],
                title=group["title"],
                content=group["content"],
                source_trace_id=group["source_trace_id"],
                confidence=group["confidence"],
                weight=group["weight"],
                verified_status="candidate",
                subject_type=group["subject_type"],
                subject_id=group["subject_id"],
                created_by=actor,
            ),
            force=True,
            consolidate_existing=True,
        )
        if created:
            _copy_evidence(raw_pool, group["tenant"], group["canonical_id"], group["source_database_ids"], actor)
            memory_applied += 1
    return {
        "status": "applied",
        "asset_groups_applied": asset_applied,
        "memory_groups_applied": memory_applied,
        "groups_skipped": skipped,
    }


def _repair_from_backup(pool: MySQLConnectionPool, path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    backup = json.loads(resolved.read_text(encoding="utf-8"))
    if backup.get("schema") != "smart_data_agent_memory_consolidation_backup_v1":
        raise ValueError("unsupported_memory_consolidation_backup")
    snapshot_rows = {
        str(row["memory_key"]): row
        for row in backup.get("snapshot", {}).get("memory_records", [])
    }
    asset_rows = {
        (str(row["tenant_code"]), str(row["item_type"]), str(row["item_code"])): row
        for row in backup.get("snapshot", {}).get("asset_items", [])
    }
    repaired = 0
    assets_repaired = 0
    evidence_links_repaired = 0
    snapshot_evidence = backup.get("snapshot", {}).get("memory_evidence", [])
    with pool.transaction() as connection, connection.cursor() as cursor:
        for group in backup.get("plan", {}).get("asset_groups", []):
            if not group.get("apply"):
                continue
            source_ids = [str(group["canonical_id"]), *(str(value) for value in group["duplicate_ids"])]
            source_rows = [asset_rows[(str(group["tenant"]), str(group["item_type"]), item_id)] for item_id in source_ids]
            expected = fuse_payloads(
                str(group["item_type"]),
                [dict(row["payload"]) for row in source_rows],
                canonical_id=str(group["canonical_id"]),
            )
            cursor.execute("SELECT tenant_id FROM platform_tenants WHERE tenant_code = %s", (group["tenant"],))
            tenant = cursor.fetchone()
            if not tenant:
                raise KeyError(f"tenant_not_found:{group['tenant']}")
            cursor.execute(
                "SELECT asset_item_id,payload,status FROM platform_data_asset_items WHERE tenant_id = %s AND item_type = %s AND item_code = %s FOR UPDATE",
                (tenant["tenant_id"], group["item_type"], group["canonical_id"]),
            )
            current = cursor.fetchone()
            if not current or str(current["status"]) not in {"draft", "review"}:
                raise ValueError(f"fused_asset_not_repairable:{group['canonical_id']}")
            current_payload = json.loads(current["payload"]) if isinstance(current["payload"], str) else dict(current["payload"] or {})
            current_sources = set(str(value) for value in current_payload.get("mergedFromIds") or [])
            if not set(str(value) for value in group["duplicate_ids"]).issubset(current_sources):
                raise ValueError(f"fused_asset_source_mismatch:{group['canonical_id']}")
            payload_json = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            cursor.execute(
                "UPDATE platform_data_asset_items SET payload = %s, updated_at = CURRENT_TIMESTAMP WHERE asset_item_id = %s",
                (payload_json, current["asset_item_id"]),
            )
            cursor.execute(
                """
                UPDATE platform_data_asset_versions
                SET payload = %s, payload_hash = %s, updated_at = CURRENT_TIMESTAMP
                WHERE asset_item_id = %s
                  AND version_number = (SELECT latest.version_number FROM (
                    SELECT MAX(version_number) AS version_number
                    FROM platform_data_asset_versions WHERE asset_item_id = %s
                  ) latest)
                """,
                (payload_json, payload_hash, current["asset_item_id"], current["asset_item_id"]),
            )
            assets_repaired += 1
        for group in backup.get("plan", {}).get("memory_groups", []):
            if not group.get("apply"):
                continue
            source_rows = [snapshot_rows[str(memory_key)] for memory_key in group["source_ids"]]
            expected = fuse_record_content(
                str(group["memory_type"]),
                str(group["title"]),
                [dict(row["content"]) for row in source_rows],
                memory_ids=(str(row["memory_key"]) for row in source_rows),
            )
            cursor.execute("SELECT tenant_id FROM platform_tenants WHERE tenant_code = %s", (group["tenant"],))
            tenant = cursor.fetchone()
            if not tenant:
                raise KeyError(f"tenant_not_found:{group['tenant']}")
            cursor.execute(
                "SELECT memory_id,content,status FROM platform_memory_records WHERE tenant_id = %s AND memory_key = %s FOR UPDATE",
                (tenant["tenant_id"], group["canonical_id"]),
            )
            current = cursor.fetchone()
            if not current or str(current["status"]) not in {"candidate", "review"}:
                raise ValueError(f"fused_memory_not_repairable:{group['canonical_id']}")
            current_content = json.loads(current["content"]) if isinstance(current["content"], str) else dict(current["content"] or {})
            current_sources = set(str(value) for value in current_content.get("mergedFromMemoryIds") or [])
            if not set(str(value) for value in group["source_ids"]).issubset(current_sources):
                raise ValueError(f"fused_memory_source_mismatch:{group['canonical_id']}")
            content_json = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
            cursor.execute(
                "UPDATE platform_memory_records SET content = %s, content_hash = %s, updated_at = CURRENT_TIMESTAMP WHERE memory_id = %s",
                (content_json, content_hash, current["memory_id"]),
            )
            source_database_ids = set(str(value) for value in group["source_database_ids"])
            latest_evidence: dict[tuple[str, str], dict[str, Any]] = {}
            for evidence in snapshot_evidence:
                if str(evidence.get("memory_id")) not in source_database_ids:
                    continue
                evidence_key = (str(evidence.get("evidence_type")), str(evidence.get("evidence_id")))
                if evidence_key not in latest_evidence or _timestamp(evidence.get("created_at")) > _timestamp(latest_evidence[evidence_key].get("created_at")):
                    latest_evidence[evidence_key] = evidence
            for evidence in latest_evidence.values():
                cursor.execute(
                    """
                    INSERT INTO platform_memory_evidence(
                        memory_evidence_id, tenant_id, memory_id, evidence_type, evidence_id,
                        evidence_hash, support_type, created_by
                    ) VALUES(UUID(), %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE evidence_hash = VALUES(evidence_hash),
                      support_type = VALUES(support_type), updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        tenant["tenant_id"], current["memory_id"], evidence["evidence_type"], evidence["evidence_id"],
                        evidence["evidence_hash"], evidence["support_type"], evidence.get("created_by"),
                    ),
                )
                evidence_links_repaired += 1
            repaired += 1
    return {
        "status": "repaired",
        "asset_records_repaired": assets_repaired,
        "runtime_records_repaired": repaired,
        "canonical_evidence_links_repaired": evidence_links_repaired,
        "backup": str(resolved),
    }


def _copy_evidence(pool: MySQLConnectionPool, tenant_code: str, canonical_key: str, source_ids: list[str], actor: str) -> None:
    if not source_ids:
        return
    with pool.transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT tenant_id FROM platform_tenants WHERE tenant_code = %s", (tenant_code,))
        tenant = cursor.fetchone()
        cursor.execute(
            "SELECT memory_id FROM platform_memory_records WHERE tenant_id = %s AND memory_key = %s",
            (tenant["tenant_id"], canonical_key),
        )
        canonical = cursor.fetchone()
        cursor.execute(
            "SELECT user_id FROM platform_user_profiles WHERE external_subject = %s",
            (actor,),
        )
        actor_row = cursor.fetchone()
        placeholders = ",".join(["%s"] * len(source_ids))
        cursor.execute(
            f"SELECT evidence_type,evidence_id,evidence_hash,support_type FROM platform_memory_evidence WHERE memory_id IN ({placeholders}) ORDER BY created_at DESC, memory_evidence_id DESC",
            tuple(source_ids),
        )
        for evidence in cursor.fetchall():
            cursor.execute(
                """
                INSERT IGNORE INTO platform_memory_evidence(
                    memory_evidence_id, tenant_id, memory_id, evidence_type, evidence_id,
                    evidence_hash, support_type, created_by
                ) VALUES (UUID(), %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant["tenant_id"], canonical["memory_id"], evidence["evidence_type"], evidence["evidence_id"],
                    evidence["evidence_hash"], evidence["support_type"], actor_row["user_id"] if actor_row else None,
                ),
            )


def _write_backup(path: Path, snapshot: dict[str, Any], plan: dict[str, Any]) -> Path:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        raise FileExistsError(f"backup already exists: {resolved}")
    resolved.write_text(
        json.dumps(
            {
                "schema": "smart_data_agent_memory_consolidation_backup_v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "snapshot": snapshot,
                "plan": plan,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    resolved.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return resolved


def _plan_summary(plan: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "asset_duplicate_groups": len(plan["asset_groups"]),
        "asset_records_to_archive": sum(len(group["duplicate_ids"]) for group in plan["asset_groups"] if group["apply"]),
        "runtime_duplicate_groups": len(plan["memory_groups"]),
        "runtime_records_to_supersede": sum(len(group["source_ids"]) for group in plan["memory_groups"] if group["apply"]),
        "skipped_active_groups": sum(not group["apply"] for group in [*plan["asset_groups"], *plan["memory_groups"]]),
        "groups": [
            {
                key: group[key]
                for key in ("tenant", "item_type", "memory_type", "canonical_id", "duplicate_ids", "referenced_ids", "source_ids", "statuses", "apply", "reason")
                if key in group
            }
            for group in [*plan["asset_groups"], *plan["memory_groups"]]
        ],
    }


def _json_row(row: dict[str, Any], field: str) -> dict[str, Any]:
    result = _serializable_row(row)
    raw = result.get(field)
    result[field] = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    return result


def _serializable_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in dict(row).items()}


def _timestamp(value: Any) -> str:
    return str(value or "")


if __name__ == "__main__":
    raise SystemExit(main())
