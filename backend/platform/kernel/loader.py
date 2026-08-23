from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.platform.kernel.isolation import merge_pack_entries
from backend.platform.kernel.models import Capability, CapabilityPack, utc_now
from backend.platform.tenancy import ExecutionContext


class CapabilityLoader:
    """Compile a request-scoped capability pack. User rows override shared rows."""

    def __init__(
        self,
        skill_registry: Any,
        capability_store: Any,
        mcp_gateway: Any | None = None,
        memory_store: Any | None = None,
        data_asset_store: Any | None = None,
    ) -> None:
        self.skill_registry = skill_registry
        self.capability_store = capability_store
        self.mcp_gateway = mcp_gateway
        self.memory_store = memory_store
        self.data_asset_store = data_asset_store

    def compile(self, context: ExecutionContext) -> CapabilityPack:
        entries: list[dict[str, Any]] = []
        for spec in self.skill_registry.list():
            status = self.skill_registry.runtime_status(spec.skill_id)
            entries.append(
                {
                    "capability_id": spec.skill_id,
                    "kind": "executable",
                    "runtime_type": spec.runtime_type,
                    "owner_scope": "platform",
                    "owner_id": "platform",
                    "title": spec.name,
                    "description": spec.description,
                    "version": spec.version,
                    "status": "active" if status.get("healthy") else status.get("status") or "disabled",
                    "trigger": {},
                    "fingerprint": "",
                    "implemented": bool(status.get("implemented")),
                }
            )
        if self.mcp_gateway is not None:
            try:
                tools = self.mcp_gateway.list_tools_for_context(context)
            except Exception:
                tools = []
            for tool in tools:
                entries.append(
                    {
                        "capability_id": f"mcp:{tool['server_id']}.{tool['tool_name']}",
                        "kind": "plugin",
                        "runtime_type": "mcp",
                        "owner_scope": "platform",
                        "owner_id": "platform",
                        "title": str(tool["tool_name"]),
                        "description": str((tool.get("tool_definition") or {}).get("description") or ""),
                        "version": "1.0.0",
                        "status": tool.get("status") or "active",
                        "trigger": {"server_id": tool["server_id"], "tool_name": tool["tool_name"]},
                        "fingerprint": "",
                        "implemented": True,
                    }
                )
        if self.memory_store is not None:
            memories = self.memory_store.search(context.tenant_id, statuses=("active",), limit=40)
            for memory in memories:
                subject_type = str(getattr(memory, "subject_type", "tenant") or "tenant")
                subject_id = str(getattr(memory, "subject_id", "") or "")
                if subject_type == "user" and subject_id != context.user_id:
                    continue
                if subject_type not in {"user", "tenant", "org", "role"}:
                    continue
                entries.append(
                    {
                        "capability_id": f"memory:{getattr(memory, 'memory_id', '')}",
                        "kind": "memory",
                        "runtime_type": "context",
                        "owner_scope": "user" if subject_type == "user" else "tenant",
                        "owner_id": subject_id or context.tenant_id,
                        "title": str(getattr(memory, "title", "") or getattr(memory, "subject", "") or ""),
                        "description": "",
                        "version": "1.0.0",
                        "status": "active",
                        "trigger": {"memory_type": getattr(memory, "memory_type", "")},
                        "fingerprint": "",
                        "implemented": True,
                    }
                )
        if self.data_asset_store is not None:
            try:
                bundle = self.data_asset_store.list_published_bundle(context.tenant_id)
            except Exception:
                bundle = {}
            for skill in bundle.get("analysis_skills") or []:
                if not isinstance(skill, dict) or skill.get("enabled") is False:
                    continue
                skill_id = str(skill.get("id") or "").strip()
                if not skill_id:
                    continue
                entries.append(
                    {
                        "capability_id": f"analysis_skill:{skill_id}",
                        "kind": "procedure",
                        "runtime_type": "procedure",
                        "owner_scope": "tenant",
                        "owner_id": context.tenant_id,
                        "title": str(skill.get("name") or skill_id),
                        "description": str(skill.get("description") or ""),
                        "version": "1.0.0",
                        "status": "active",
                        "trigger": {
                            "skill_id": skill_id,
                            "category": skill.get("category") or "",
                            "terms": [
                                token
                                for token in (
                                    str(skill.get("name") or ""),
                                    *(skill.get("recommendedSkillIds") or [] if isinstance(skill.get("recommendedSkillIds"), list) else []),
                                )
                                if str(token).strip()
                            ],
                        },
                        "fingerprint": "",
                        "implemented": True,
                    }
                )
        org_ids = tuple(
            str(item)
            for item in context.page_context.get("org_ids") or ()
            if str(item).strip()
        )
        stored = self.capability_store.list_visible(
            context.tenant_id,
            context.user_id,
            statuses=("active",),
            role_ids=tuple(context.roles),
            org_ids=org_ids,
        )
        for item in stored:
            if isinstance(item, Capability):
                entries.append(item.index_entry())
            elif isinstance(item, dict):
                entries.append(item)
        merged = merge_pack_entries(entries)
        snapshot_material = {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "entries": merged,
        }
        content_hash = hashlib.sha256(
            json.dumps(snapshot_material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        pack = CapabilityPack(
            snapshot_id=f"pack_{content_hash[:24]}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            compiled_at=utc_now(),
            entries=tuple(merged),
        )
        self.capability_store.save_pack(
            {
                "snapshot_id": pack.snapshot_id,
                "tenant_id": pack.tenant_id,
                "user_id": pack.user_id,
                "entries": list(pack.entries),
                "entry_count": len(pack.entries),
                "content_hash": content_hash,
                "created_at": pack.compiled_at,
            }
        )
        return pack
