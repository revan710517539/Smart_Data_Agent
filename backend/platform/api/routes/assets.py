from __future__ import annotations

import base64
import binascii
import hashlib
from copy import deepcopy
from time import monotonic
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from backend.authz import normalize_tenant_id
from backend.platform.api.support import first_query_value, send_route_exception


RUNTIME_CONFIGURATION_ASSET_TYPES = frozenset({
    "raw_table",
    "analysis_skill",
    "external_tool",
    "analysis_shortcut",
    "page_data", "table_relationship",
})
TABLE_ASSET_LINEAGE_TYPES = frozenset({"dataset", "topic_table", "raw_table"})
VISUALIZATION_ASSET_KEYS = (
    "raw_tables", "topic_tables", "intents", "analysis_experiences", "behavior_habits",
    "knowledge_files", "analysis_skills", "external_tools", "analysis_shortcuts", "page_data", "table_relationships", "relationships",
)
VISUALIZATION_TOPIC_LIFECYCLE_STATUSES = frozenset({"draft", "review", "active"})
SINGLE_INSTITUTION_PAGE_DATA_SCOPE = "single_institution"
MULTI_INSTITUTION_PAGE_DATA_SCOPE = "multi_institution"
MULTI_INSTITUTION_DIMENSION = "__institution_name"
MULTI_INSTITUTION_RELATIONSHIP_SCOPE = "multi_institution"
SINGLE_INSTITUTION_RELATIONSHIP_SCOPE = "single_institution"
_PAGE_DATA_PROJECTION_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_PAGE_DATA_PROJECTION_CACHE_MAX = 48
_PAGE_DATA_WORKSPACE_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_PAGE_DATA_WORKSPACE_CACHE_TTL_SECONDS = 20.0


def _authorized_raw_table_catalog(handler: Any, context: Any) -> tuple[dict[str, str], dict[tuple[str, str], dict[str, Any]]]:
    """Return authoritative, permission-filtered tables with server-owned institution labels."""

    tenant_labels = _authorized_tenant_labels(handler, context)
    table_by_ref: dict[tuple[str, str], dict[str, Any]] = {}
    for tenant_id in tenant_labels:
        catalog = handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id)
        if not getattr(catalog, "catalog_ready", True):
            continue
        data_asset_store = getattr(handler.services, "data_asset_store", None)
        stored = data_asset_store.list_bundle(tenant_id) if data_asset_store is not None else {"raw_tables": []}
        overlays = {
            str(item.get("sourceKey") or ""): item
            for item in stored.get("raw_tables", [])
            if isinstance(item, dict) and item.get("metadataOverlayVersion") == 1 and str(item.get("sourceKey") or "")
        }
        for raw_table in catalog.table_assets():
            source_key = str(raw_table.get("sourceKey") or "").strip()
            if not source_key:
                continue
            table = _raw_table_with_metadata_overlay(dict(raw_table), overlays.get(source_key))
            table_by_ref[(tenant_id, source_key)] = table
    return tenant_labels, table_by_ref


def _authorized_raw_table_subset(
    handler: Any,
    context: Any,
    requested_nodes: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[tuple[str, str], dict[str, Any]]]:
    """Rebind only the tables referenced by a submitted relationship graph.

    Catalog/list endpoints intentionally enumerate every authorized institution.
    A relationship save only needs to recheck its submitted tenant/source pairs;
    scanning unrelated institutions adds seconds of latency without strengthening
    RBAC or schema validation.
    """

    requested_sources: dict[str, set[str]] = {}
    for requested in requested_nodes:
        tenant_id = _normalized_tenant_id(str(requested.get("tenantId") or ""))
        source_key = str(requested.get("sourceKey") or "").strip()
        if tenant_id and source_key:
            requested_sources.setdefault(tenant_id, set()).add(source_key)

    tenant_labels = _authorized_requested_tenant_labels(
        handler,
        context,
        set(requested_sources),
    )

    table_by_ref: dict[tuple[str, str], dict[str, Any]] = {}
    data_asset_store = getattr(handler.services, "data_asset_store", None)
    for tenant_id, source_keys in requested_sources.items():
        if tenant_id not in tenant_labels:
            continue
        catalog = handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id)
        if not getattr(catalog, "catalog_ready", True):
            continue
        stored = data_asset_store.list_bundle(tenant_id) if data_asset_store is not None else {"raw_tables": []}
        overlays = {
            str(item.get("sourceKey") or ""): item
            for item in stored.get("raw_tables", [])
            if isinstance(item, dict)
            and item.get("metadataOverlayVersion") == 1
            and str(item.get("sourceKey") or "") in source_keys
        }
        remaining = set(source_keys)
        for raw_table in catalog.table_assets():
            source_key = str(raw_table.get("sourceKey") or "").strip()
            if source_key not in remaining:
                continue
            table_by_ref[(tenant_id, source_key)] = _raw_table_with_metadata_overlay(
                dict(raw_table), overlays.get(source_key),
            )
            remaining.discard(source_key)
            if not remaining:
                break
    return tenant_labels, table_by_ref


def _relationship_common_fields(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Intersect the institution projections by stable field code and compatible type."""

    by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
    for node in nodes:
        tenant_fields = by_tenant.setdefault(str(node.get("tenantId") or ""), {})
        for field in node.get("fields", []):
            if not isinstance(field, dict):
                continue
            code = str(field.get("fieldNameEn") or "")
            if not code:
                continue
            previous = tenant_fields.get(code)
            if previous is None or (not previous.get("isPrimaryKey") and field.get("isPrimaryKey")):
                tenant_fields[code] = dict(field)
    if len(by_tenant) < 2:
        return []
    common_codes = set.intersection(*(set(fields) for fields in by_tenant.values()))
    result: list[dict[str, Any]] = []
    first_tenant = sorted(by_tenant)[0]
    for code in sorted(common_codes):
        candidates = [fields[code] for fields in by_tenant.values()]
        types = {str(field.get("type") or "string") for field in candidates}
        roles = {str(field.get("semanticRole") or "") for field in candidates}
        if len(types) != 1 or len(roles) != 1:
            continue
        result.append(dict(by_tenant[first_tenant][code]))
    return result


def _candidate_from_relationship_asset(
    relationship: dict[str, Any],
    tenant_labels: dict[str, str],
    table_by_ref: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    rebound_nodes: list[dict[str, Any]] = []
    for saved_node in relationship.get("nodes", []):
        if not isinstance(saved_node, dict):
            return None
        tenant_id = _normalized_tenant_id(str(saved_node.get("tenantId") or ""))
        source_key = str(saved_node.get("sourceKey") or "")
        table = table_by_ref.get((tenant_id, source_key))
        if table is None or str(saved_node.get("schemaFingerprint") or "") != str(table.get("schemaFingerprint") or ""):
            return None
        rebound_nodes.append({
            **saved_node,
            "tenantId": tenant_id,
            "institutionName": tenant_labels.get(tenant_id, tenant_id),
            "sourceTableId": str(table.get("id") or ""),
            "sourceTableName": str(table.get("tableNameCn") or table.get("tableNameEn") or ""),
            "fields": [dict(field) for field in table.get("fields", []) if isinstance(field, dict)],
        })
    tenant_ids = {str(node.get("tenantId") or "") for node in rebound_nodes}
    fields = _relationship_common_fields(rebound_nodes)
    if len(tenant_ids) < 2 or not fields:
        return None
    identity = str(relationship.get("id") or "")
    schema_identity = "|".join(
        f"{node['tenantId']}:{node['sourceKey']}:{node['schemaFingerprint']}"
        for node in sorted(rebound_nodes, key=lambda item: (str(item["tenantId"]), str(item["sourceKey"])))
    )
    return {
        "id": identity,
        "name": str(relationship.get("name") or "多机构关联数据"),
        "schemaFingerprint": hashlib.sha256(schema_identity.encode("utf-8")).hexdigest(),
        "fields": fields,
        "sources": [
            {
                "nodeId": str(node.get("id") or ""),
                "tenantId": str(node.get("tenantId") or ""),
                "institutionName": str(node.get("institutionName") or ""),
                "sourceKey": str(node.get("sourceKey") or ""),
                "sourceTableId": str(node.get("sourceTableId") or ""),
                "sourceTableName": str(node.get("sourceTableName") or ""),
                "schemaFingerprint": str(node.get("schemaFingerprint") or ""),
            }
            for node in rebound_nodes
        ],
        "relationshipEdges": [dict(edge) for edge in relationship.get("edges", []) if isinstance(edge, dict)],
        "institutionCount": len(tenant_ids),
        "tableCount": len(rebound_nodes),
    }


def _page_data_scope(item: dict[str, Any]) -> str:
    explicit = str(item.get("institutionScope") or "").strip()
    if explicit in {SINGLE_INSTITUTION_PAGE_DATA_SCOPE, MULTI_INSTITUTION_PAGE_DATA_SCOPE}:
        return explicit
    pages = {str(page) for page in item.get("targetPages", []) if str(page)}
    return MULTI_INSTITUTION_PAGE_DATA_SCOPE if pages == {"dashboard"} else SINGLE_INSTITUTION_PAGE_DATA_SCOPE


def _normalized_tenant_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return normalized if normalized.startswith("tenant:") or normalized == "tenant_demo" else normalize_tenant_id(normalized)


def _authorized_tenant_labels(handler: Any, context: Any) -> dict[str, str]:
    session = handler.services.access_service.session_for_user(context.user_id, tenant_hint=context.tenant_id)
    labels = [str(label or "").strip() for label in session.get("institutions", []) if str(label or "").strip()]
    candidates = {_normalized_tenant_id(label): label for label in labels}
    candidates.setdefault(context.tenant_id, str(session.get("institution") or context.tenant_id))
    enforcer = handler.services.permission_broker.enforcer
    return {
        tenant_id: label
        for tenant_id, label in candidates.items()
        if tenant_id and enforcer.enforce(context.user_id, tenant_id, "asset:*", "read")
    }


def _authorized_requested_tenant_labels(
    handler: Any,
    context: Any,
    requested_tenant_ids: set[str],
) -> dict[str, str]:
    """Authorize only the tenant scopes referenced by one submitted graph.

    The full catalog endpoint intentionally evaluates every institution visible
    to the account. A save request already declares its bounded tenant set, so
    rechecking unrelated institutions adds permission-store round trips without
    increasing the authority of the saved relationship.
    """

    requested = {_normalized_tenant_id(tenant_id) for tenant_id in requested_tenant_ids}
    requested.discard("")
    session = handler.services.access_service.session_for_user(
        context.user_id,
        tenant_hint=context.tenant_id,
    )
    candidates = {
        _normalized_tenant_id(str(label or "")): str(label or "").strip()
        for label in session.get("institutions", [])
        if str(label or "").strip()
    }
    candidates.setdefault(context.tenant_id, str(session.get("institution") or context.tenant_id))
    enforcer = handler.services.permission_broker.enforcer
    return {
        tenant_id: candidates[tenant_id]
        for tenant_id in requested
        if tenant_id in candidates
        and enforcer.enforce(context.user_id, tenant_id, "asset:*", "read")
    }


def _multi_relationship_endpoint(edge: dict[str, Any], endpoint: str) -> tuple[str, str] | None:
    metadata = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
    if str(metadata.get("relationshipScope") or metadata.get("relationship_scope") or "") != MULTI_INSTITUTION_RELATIONSHIP_SCOPE:
        return None
    title = "source" if endpoint == "source" else "target"
    tenant_id = _normalized_tenant_id(str(metadata.get(f"{title}TenantId") or metadata.get(f"{title}_tenant_id") or ""))
    source_key = str(metadata.get(f"{title}SourceKey") or metadata.get(f"{title}_source_key") or "").strip()
    endpoint_id = str(edge.get(f"{endpoint}_id") or "").strip()
    if (not tenant_id or not source_key) and "::" in endpoint_id:
        encoded_tenant, encoded_source = endpoint_id.split("::", 1)
        tenant_id = tenant_id or _normalized_tenant_id(encoded_tenant)
        source_key = source_key or encoded_source.strip()
    return (tenant_id, source_key) if tenant_id and source_key else None


def _multi_institution_candidates(handler: Any, context: Any) -> list[dict[str, Any]]:
    """Project governed relationship groups across the account's authorized tenants."""

    tenant_labels, table_by_ref = _authorized_raw_table_catalog(handler, context)
    if len(tenant_labels) < 2:
        return []
    data_asset_store = getattr(handler.services, "data_asset_store", None)
    relationship_assets = data_asset_store.list_published_bundle(context.tenant_id).get("table_relationships", []) if data_asset_store is not None else []
    explicit = [
        candidate
        for relationship in relationship_assets
        if isinstance(relationship, dict)
        and str(relationship.get("relationshipScope") or "") == MULTI_INSTITUTION_RELATIONSHIP_SCOPE
        and (candidate := _candidate_from_relationship_asset(relationship, tenant_labels, table_by_ref)) is not None
    ]
    if explicit:
        return sorted(explicit, key=lambda item: (str(item.get("name") or ""), str(item.get("id") or "")))[:100]

    # Backward compatibility: previously provisioned explicit lineage edges
    # remain consumable until they are upgraded to a named relationship group.
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for relationship_tenant in tenant_labels:
        for edge in handler.services.lineage_store.list_edges(relationship_tenant):
            if not _is_table_asset_relationship(edge):
                continue
            source = _multi_relationship_endpoint(edge, "source")
            target = _multi_relationship_endpoint(edge, "target")
            if not source or not target or source == target:
                continue
            if source not in table_by_ref or target not in table_by_ref:
                continue
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)

    candidates: list[dict[str, Any]] = []
    visited: set[tuple[str, str]] = set()
    for root in sorted(adjacency):
        if root in visited:
            continue
        pending = [root]
        component: set[tuple[str, str]] = set()
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency.get(current, set()) - component)
        visited.update(component)
        refs_by_tenant = {tenant_id: (tenant_id, source_key) for tenant_id, source_key in component}
        if len(refs_by_tenant) < 2 or len(refs_by_tenant) != len(component):
            continue
        tables = [(ref, table_by_ref[ref]) for ref in sorted(refs_by_tenant.values())]
        schemas = {str(table.get("schemaFingerprint") or "") for _, table in tables}
        if "" in schemas or len(schemas) != 1:
            continue
        identity = "|".join(f"{tenant_id}:{source_key}" for (tenant_id, source_key), _ in tables)
        first = tables[0][1]
        candidates.append({
            "id": "multi_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            "name": f"{first.get('tableNameCn') or first.get('tableNameEn') or '关联数据表'} · {len(tables)} 个机构",
            "schemaFingerprint": next(iter(schemas)),
            "fields": [dict(field) for field in first.get("fields", []) if isinstance(field, dict)],
            "sources": [
                {
                    "tenantId": tenant_id,
                    "institutionName": tenant_labels.get(tenant_id, tenant_id),
                    "sourceKey": source_key,
                    "sourceTableId": str(table.get("id") or ""),
                    "sourceTableName": str(table.get("tableNameCn") or table.get("tableNameEn") or ""),
                    "schemaFingerprint": str(table.get("schemaFingerprint") or ""),
                }
                for (tenant_id, source_key), table in tables
            ],
        })
    return sorted(candidates, key=lambda item: (str(item.get("name") or ""), str(item.get("id") or "")))[:100]


def _visualization_topic_tables(
    handler: Any,
    tenant_id: str,
    requested_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return current-tenant topic tables that the chart editor can read.

    Visualization is an authorized editing surface, not the analysis runtime.
    Draft/review candidates may therefore be charted when they already own a
    bounded Topic_Data snapshot. Runtime consumers continue to use the
    published bundle and this helper is not part of that path.
    """

    if requested_ids is not None and not requested_ids:
        return []
    topics = [
        dict(item)
        for item in handler.services.data_asset_store.list_bundle(tenant_id).get("topic_tables", [])
        if isinstance(item, dict)
        and str(item.get("id") or "")
        and str(item.get("lifecycleStatus") or "active") in VISUALIZATION_TOPIC_LIFECYCLE_STATUSES
        and (requested_ids is None or str(item.get("id") or "") in requested_ids)
    ]
    snapshots = handler.services.topic_data_store.topic_table_snapshots(
        tenant_id,
        [str(item["id"]) for item in topics],
    )
    return [
        {**item, "dataSnapshot": snapshot}
        for item in topics
        if (snapshot := snapshots.get(str(item["id"]))) and snapshot.get("has_data") is True
    ]


def _is_table_asset_relationship(edge: dict[str, Any]) -> bool:
    """Return true only for lineage whose two endpoints are table assets."""

    return (
        str(edge.get("source_type") or "") in TABLE_ASSET_LINEAGE_TYPES
        and str(edge.get("target_type") or "") in TABLE_ASSET_LINEAGE_TYPES
    )


def _raw_table_with_external_reference(
    table: dict[str, Any], reference: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project SDA policy onto a dynamic, read-only CSV catalog entry.

    A changed schema always fails closed.  This keeps a prior approval from
    unintentionally exposing columns added by a later crawler delivery.
    """

    expected_schema = str(table.get("schemaFingerprint") or "")
    reference_schema = str((reference or {}).get("schemaFingerprint") or "")
    shared = bool(reference and reference.get("mode") == "shared" and reference_schema == expected_schema)
    return {
        **table,
        "externalReferenceMode": "shared" if shared else "private",
        "externalReferenceUpdatedAt": str((reference or {}).get("updatedAt") or ""),
        "externalReferenceSchemaChanged": bool(reference and reference_schema != expected_schema),
    }


def _raw_field_role(field: dict[str, Any]) -> str:
    role = str(field.get("semanticRole") or "").strip().lower()
    if role in {"metric", "dimension", "date"}:
        return role
    data_type = str(field.get("type") or "string").strip().lower()
    name = f"{field.get('fieldNameEn') or ''} {field.get('fieldNameCn') or ''}"
    if bool(field.get("isTime")) or data_type in {"date", "datetime"} or any(token in name.lower() for token in ("date", "time", "日期", "时间")):
        return "date"
    if bool(field.get("isMetric")) or data_type in {"integer", "decimal", "rate"}:
        return "metric"
    return "dimension"


def _raw_metric_type(field: dict[str, Any]) -> str:
    name = f"{field.get('fieldNameEn') or ''} {field.get('fieldNameCn') or ''}".lower()
    data_type = str(field.get("type") or "decimal").strip().lower()
    if str(field.get("semanticRole") or "").strip().lower() == "metric" and data_type in {"integer", "decimal", "rate"}:
        return data_type
    if any(token in name for token in ("率", "占比", "比例", "rate", "ratio", "percent", "pct")):
        return "rate"
    return data_type if data_type in {"integer", "decimal", "rate"} else "decimal"


def _normalized_raw_fields(
    source_fields: list[dict[str, Any]], configured_fields: list[dict[str, Any]] | None = None,
    preferred_primary_key: str = "",
) -> list[dict[str, Any]]:
    configured = {
        str(field.get("fieldNameEn") or "").strip(): field
        for field in (configured_fields or [])
        if isinstance(field, dict) and str(field.get("fieldNameEn") or "").strip()
    }
    source_codes = [str(field.get("fieldNameEn") or "").strip() for field in source_fields]
    if configured and set(configured) != set(source_codes):
        raise ValueError("raw_table_metadata_fields_changed")
    normalized: list[dict[str, Any]] = []
    for source in source_fields:
        code = str(source.get("fieldNameEn") or "").strip()
        candidate = {**source, **configured.get(code, {})}
        role = _raw_field_role(candidate)
        data_type = "string" if role == "dimension" else "date" if role == "date" else _raw_metric_type(candidate)
        normalized.append({
            **candidate,
            "fieldNameEn": code,
            "fieldNameCn": str(candidate.get("fieldNameCn") or source.get("fieldNameCn") or code).strip(),
            "type": data_type,
            "semanticRole": role,
            "dateFormat": "yyyy-MM-dd" if role == "date" else None,
            "isTime": role == "date",
            "isMetric": role == "metric",
            "isPrimaryKey": role == "dimension" and bool(candidate.get("isPrimaryKey") or (not configured and code == preferred_primary_key)),
        })
    if not any(field["isPrimaryKey"] for field in normalized):
        primary_index = next((index for index, field in enumerate(normalized) if field["semanticRole"] == "dimension"), 0)
        if normalized:
            normalized[primary_index] = {
                **normalized[primary_index], "semanticRole": "dimension", "type": "string",
                "dateFormat": None, "isTime": False, "isMetric": False, "isPrimaryKey": True,
            }
    return normalized


def _raw_table_with_metadata_overlay(table: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    expected_schema = str(table.get("schemaFingerprint") or "")
    overlay_schema = str((overlay or {}).get("schemaFingerprint") or "")
    applicable = bool(
        overlay
        and overlay.get("metadataOverlayVersion") == 1
        and overlay_schema == expected_schema
        and str(overlay.get("sourceKey") or "") == str(table.get("sourceKey") or "")
    )
    fields = _normalized_raw_fields(
        [dict(field) for field in table.get("fields", []) if isinstance(field, dict)],
        [dict(field) for field in (overlay or {}).get("fields", []) if isinstance(field, dict)] if applicable else None,
        str(table.get("primaryKey") or ""),
    )
    primary_keys = [str(field["fieldNameEn"]) for field in fields if field.get("isPrimaryKey")]
    return {
        **table,
        "fields": fields,
        "primaryKey": primary_keys[0] if primary_keys else "",
        "primaryKeys": primary_keys,
        "dateField": next((str(field["fieldNameEn"]) for field in fields if field.get("semanticRole") == "date"), ""),
        "metadataConfigId": str((overlay or {}).get("id") or "") if applicable else "",
        "metadataConfigLockVersion": int((overlay or {}).get("lockVersion") or 0) if applicable else 0,
        "metadataConfigSchemaChanged": bool(overlay and overlay.get("metadataOverlayVersion") == 1 and overlay_schema != expected_schema),
    }


def _bind_raw_table_metadata_asset(handler: Any, context: Any, item: dict[str, Any]) -> dict[str, Any]:
    source_key = str(item.get("sourceKey") or "").strip()
    schema_fingerprint = str(item.get("schemaFingerprint") or "").strip()
    tables = handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id).table_assets()
    table = next((candidate for candidate in tables if str(candidate.get("sourceKey") or "") == source_key), None)
    if table is None:
        raise PermissionError("raw_table_metadata_source_unavailable")
    if schema_fingerprint != str(table.get("schemaFingerprint") or ""):
        raise ValueError("raw_table_metadata_schema_changed")
    fields = _normalized_raw_fields(
        [dict(field) for field in table.get("fields", []) if isinstance(field, dict)],
        [dict(field) for field in item.get("fields", []) if isinstance(field, dict)],
        str(table.get("primaryKey") or ""),
    )
    if not fields or not any(field.get("isPrimaryKey") for field in fields):
        raise ValueError("raw_table_metadata_primary_key_required")
    return {
        "id": str(item.get("id") or f"raw_metadata_{source_key}"),
        "metadataOverlayVersion": 1,
        "sourceKey": source_key,
        "schemaFingerprint": schema_fingerprint,
        "tableNameEn": str(table.get("tableNameEn") or ""),
        "tableNameCn": str(table.get("tableNameCn") or ""),
        "source": str(table.get("source") or ""),
        "description": "SDA 字段语义、显示格式与联合主键配置；不修改原始 CSV。",
        "fields": fields,
        "primaryKey": next(str(field["fieldNameEn"]) for field in fields if field.get("isPrimaryKey")),
        "primaryKeys": [str(field["fieldNameEn"]) for field in fields if field.get("isPrimaryKey")],
        "updatedAt": str(item.get("updatedAt") or ""),
        "lockVersion": item.get("lockVersion"),
    }


def _bind_table_relationship_asset(handler: Any, context: Any, item: dict[str, Any]) -> dict[str, Any]:
    requested_nodes = item.get("nodes")
    requested_edges = item.get("edges")
    if not isinstance(requested_nodes, list) or not (2 <= len(requested_nodes) <= 12):
        raise ValueError("table_relationship_nodes_invalid")
    if not isinstance(requested_edges, list) or not requested_edges or len(requested_edges) > 24:
        raise ValueError("table_relationship_edges_invalid")
    if not all(isinstance(requested, dict) for requested in requested_nodes):
        raise ValueError("table_relationship_node_invalid")
    tenant_labels, table_by_ref = _authorized_raw_table_subset(handler, context, requested_nodes)

    nodes: list[dict[str, Any]] = []
    node_by_id: dict[str, dict[str, Any]] = {}
    refs: set[tuple[str, str]] = set()
    for index, requested in enumerate(requested_nodes):
        tenant_id = _normalized_tenant_id(str(requested.get("tenantId") or ""))
        source_key = str(requested.get("sourceKey") or "").strip()
        if tenant_id not in tenant_labels:
            raise PermissionError("table_relationship_tenant_unavailable")
        table = table_by_ref.get((tenant_id, source_key))
        if table is None:
            raise PermissionError("table_relationship_table_unavailable")
        if str(requested.get("schemaFingerprint") or "") != str(table.get("schemaFingerprint") or ""):
            raise ValueError("table_relationship_table_schema_changed")
        if (tenant_id, source_key) in refs:
            raise ValueError("table_relationship_duplicate_table")
        refs.add((tenant_id, source_key))
        node_id = str(requested.get("id") or f"node_{index + 1}").strip()[:80]
        if not node_id or node_id in node_by_id:
            raise ValueError("table_relationship_duplicate_node")
        position = requested.get("position") if isinstance(requested.get("position"), dict) else {}
        node = {
            "id": node_id,
            "tenantId": tenant_id,
            "institutionName": tenant_labels[tenant_id],
            "sourceKey": source_key,
            "sourceTableId": str(table.get("id") or ""),
            "sourceTableName": str(table.get("tableNameCn") or table.get("tableNameEn") or ""),
            "schemaFingerprint": str(table.get("schemaFingerprint") or ""),
            "position": {
                "x": max(0, min(2400, int(position.get("x") or 0))),
                "y": max(0, min(1600, int(position.get("y") or 0))),
            },
            "fields": [dict(field) for field in table.get("fields", []) if isinstance(field, dict)],
        }
        nodes.append(node)
        node_by_id[node_id] = node

    adjacency = {node_id: set() for node_id in node_by_id}
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str, str]] = set()
    for index, requested in enumerate(requested_edges):
        if not isinstance(requested, dict):
            raise ValueError("table_relationship_edge_invalid")
        source_node_id = str(requested.get("sourceNodeId") or "")
        target_node_id = str(requested.get("targetNodeId") or "")
        source_node = node_by_id.get(source_node_id)
        target_node = node_by_id.get(target_node_id)
        if source_node is None or target_node is None or source_node_id == target_node_id:
            raise ValueError("table_relationship_edge_node_invalid")
        source_field_code = str(requested.get("sourceField") or "")
        target_field_code = str(requested.get("targetField") or "")
        source_field = next((field for field in source_node["fields"] if str(field.get("fieldNameEn") or "") == source_field_code), None)
        target_field = next((field for field in target_node["fields"] if str(field.get("fieldNameEn") or "") == target_field_code), None)
        if source_field is None or target_field is None:
            raise ValueError("table_relationship_edge_field_invalid")
        if not source_field.get("isPrimaryKey") and not target_field.get("isPrimaryKey"):
            raise ValueError("table_relationship_edge_primary_key_required")
        if str(source_field.get("type") or "") != str(target_field.get("type") or ""):
            raise ValueError("table_relationship_edge_type_mismatch")
        edge_key = (source_node_id, source_field_code, target_node_id, target_field_code)
        reverse_key = (target_node_id, target_field_code, source_node_id, source_field_code)
        if edge_key in edge_keys or reverse_key in edge_keys:
            raise ValueError("table_relationship_duplicate_edge")
        edge_keys.add(edge_key)
        adjacency[source_node_id].add(target_node_id)
        adjacency[target_node_id].add(source_node_id)
        edges.append({
            "id": "edge_" + hashlib.sha256("|".join(edge_key).encode("utf-8")).hexdigest()[:20],
            "sourceNodeId": source_node_id,
            "sourceField": source_field_code,
            "targetNodeId": target_node_id,
            "targetField": target_field_code,
            "joinType": "inner",
        })

    pending = [nodes[0]["id"]]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency[current] - visited)
    if len(visited) != len(nodes):
        raise ValueError("table_relationship_graph_disconnected")
    tenant_ids = {str(node["tenantId"]) for node in nodes}
    for tenant_id in tenant_ids:
        local_nodes = {str(node["id"]) for node in nodes if str(node["tenantId"]) == tenant_id}
        if len(local_nodes) <= 1:
            continue
        local_pending = [next(iter(local_nodes))]
        local_visited: set[str] = set()
        while local_pending:
            current = local_pending.pop()
            if current in local_visited:
                continue
            local_visited.add(current)
            local_pending.extend({node_id for node_id in adjacency[current] if node_id in local_nodes} - local_visited)
        if local_visited != local_nodes:
            raise ValueError("table_relationship_institution_graph_disconnected")
    relationship_scope = (
        MULTI_INSTITUTION_RELATIONSHIP_SCOPE
        if len(tenant_ids) > 1
        else SINGLE_INSTITUTION_RELATIONSHIP_SCOPE
    )
    if relationship_scope == MULTI_INSTITUTION_RELATIONSHIP_SCOPE:
        if not any(node_by_id[edge["sourceNodeId"]]["tenantId"] != node_by_id[edge["targetNodeId"]]["tenantId"] for edge in edges):
            raise ValueError("table_relationship_cross_institution_edge_required")
        if not _relationship_common_fields(nodes):
            raise ValueError("table_relationship_common_fields_required")
    return {
        **item,
        "name": str(item.get("name") or "").strip()[:120],
        # Scope is server-derived from authorized node tenants.  The client
        # cannot promote a single-institution relationship into a cross-
        # institution source for multi-institution pages.
        "relationshipScope": relationship_scope,
        "nodes": nodes,
        "edges": edges,
        "institutionCount": len(tenant_ids),
        "tableCount": len(nodes),
        "updatedAt": str(item.get("updatedAt") or ""),
    }


def handle_table_relationship_catalog_get(handler: Any, query: str = "") -> None:
    del query
    try:
        context = handler._request_context()
        handler._require_asset_permission(context, "read")
        tenant_labels, table_by_ref = _authorized_raw_table_catalog(handler, context)
        institutions = []
        for tenant_id, institution_name in sorted(tenant_labels.items(), key=lambda item: item[1]):
            tables = [
                {
                    "tenantId": tenant_id,
                    "institutionName": institution_name,
                    "id": str(table.get("id") or ""),
                    "sourceKey": source_key,
                    "tableNameEn": str(table.get("tableNameEn") or ""),
                    "tableNameCn": str(table.get("tableNameCn") or table.get("tableNameEn") or ""),
                    "schemaFingerprint": str(table.get("schemaFingerprint") or ""),
                    "rowCount": int(table.get("rowCount") or 0),
                    "fields": [dict(field) for field in table.get("fields", []) if isinstance(field, dict)],
                }
                for (candidate_tenant, source_key), table in sorted(table_by_ref.items())
                if candidate_tenant == tenant_id
            ]
            institutions.append({"tenantId": tenant_id, "institutionName": institution_name, "tables": tables})
        handler._send_json({
            "tenant_id": context.tenant_id,
            "institutions": institutions,
            "count": {"institutions": len(institutions), "tables": sum(len(item["tables"]) for item in institutions)},
            "source_read_only": True,
        })
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_data_assets_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        scope = str((params.get("scope") or [""])[0]).strip().lower()
        if scope == "runtime":
            # Runtime consumers must use the same published asset versions as
            # the analysis executor. A newer review candidate must not hide
            # the last approved version or become executable before approval.
            bundle = handler.services.data_asset_store.list_published_bundle(context.tenant_id)
            bundle["raw_tables"] = []
            bundle["external_tools"] = [
                item
                for item in bundle.get("external_tools", [])
                if str(item.get("toolType") or "").casefold() not in {"browser_collector", "page_collector"}
            ]
            handler._send_json({"tenant_id": context.tenant_id, **bundle, "source_mode": "runtime_published", "count": {key: len(value) for key, value in bundle.items()}})
            return
        if scope == "knowledge":
            bundle = handler.services.data_asset_store.list_bundle(context.tenant_id)
            bundle["raw_tables"] = []
            bundle["topic_tables"] = []
            bundle["external_tools"] = [
                item
                for item in bundle.get("external_tools", [])
                if str(item.get("toolType") or "").casefold() not in {"browser_collector", "page_collector"}
            ]
            handler._send_json({"tenant_id": context.tenant_id, **bundle, "source_mode": "knowledge_only", "count": {key: len(value) for key, value in bundle.items()}})
            return
        if scope == "visualization":
            csv_catalog = handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id)
            if not csv_catalog.catalog_ready:
                handler._send_json(
                    {
                        "tenant_id": context.tenant_id,
                        "status": "loading",
                        "message": "当前机构的 Data Crawler 原始数据目录正在准备中，请稍候重试。",
                        "source_mode": "visualization_catalog",
                    },
                    headers={"Retry-After": "1"},
                )
                return
            stored = handler.services.data_asset_store.list_bundle(context.tenant_id)
            overlays = {
                str(item.get("sourceKey") or ""): item
                for item in stored.get("raw_tables", [])
                if item.get("metadataOverlayVersion") == 1 and str(item.get("sourceKey") or "")
            }
            references = handler.services.data_asset_store.list_raw_table_external_references(context.tenant_id)
            raw_tables = [
                _raw_table_with_metadata_overlay(
                    _raw_table_with_external_reference(item, references.get(str(item.get("sourceKey") or ""))),
                    overlays.get(str(item.get("sourceKey") or "")),
                )
                for item in csv_catalog.table_assets()
            ]
            topic_tables = _visualization_topic_tables(handler, context.tenant_id)
            published_reader = getattr(handler.services.data_asset_store, "list_published_bundle", None)
            published = published_reader(context.tenant_id) if callable(published_reader) else stored
            multi_page_data = [
                item
                for item in published.get("page_data", [])
                if isinstance(item, dict) and _page_data_scope(item) == MULTI_INSTITUTION_PAGE_DATA_SCOPE
            ]
            bundle = {key: [] for key in VISUALIZATION_ASSET_KEYS}
            bundle["raw_tables"] = raw_tables
            bundle["topic_tables"] = topic_tables
            bundle["page_data"] = multi_page_data
            handler._send_json({
                "tenant_id": context.tenant_id,
                **bundle,
                "source_mode": "visualization_catalog",
                "source_read_only": True,
                "count": {key: len(value) for key, value in bundle.items()},
            })
            return
        csv_catalog = handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id)
        if not csv_catalog.catalog_ready:
            handler._send_json(
                {
                    "tenant_id": context.tenant_id,
                    "status": "loading",
                    "message": "当前机构的 Data Crawler 原始数据目录正在准备中，请稍候重试。",
                    "source_mode": "csv_folder",
                },
                headers={"Retry-After": "1"},
            )
            return
        bundle = handler.services.data_asset_store.list_bundle(context.tenant_id)
        raw_metadata_overlays = {
            str(item.get("sourceKey") or ""): item
            for item in bundle.get("raw_tables", [])
            if item.get("metadataOverlayVersion") == 1 and str(item.get("sourceKey") or "")
        }
        bundle["external_tools"] = [
            item
            for item in bundle.get("external_tools", [])
            if str(item.get("toolType") or "").casefold() not in {"browser_collector", "page_collector"}
        ]
        csv_source = csv_catalog.snapshot()
        # Raw tables are generated only from the selected institution's
        # Data Crawler directory. Never merge or fall back to another tenant.
        # Do not merge in legacy stored raw-table records: they may describe a
        # deleted upload or retired external source and would make the data
        # management page disagree with the analysis picker.
        references = handler.services.data_asset_store.list_raw_table_external_references(context.tenant_id)
        bundle["raw_tables"] = [
            _raw_table_with_metadata_overlay(
                _raw_table_with_external_reference(item, references.get(str(item.get("sourceKey") or ""))),
                raw_metadata_overlays.get(str(item.get("sourceKey") or "")),
            )
            for item in csv_catalog.table_assets()
        ]
        topic_snapshots = handler.services.topic_data_store.topic_table_snapshots(
            context.tenant_id,
            [str(item.get("id") or "") for item in bundle.get("topic_tables", []) if item.get("id")],
        )
        bundle["topic_tables"] = [
            {**item, "dataSnapshot": topic_snapshots.get(str(item.get("id") or ""))}
            for item in bundle.get("topic_tables", [])
        ]
        bundle["relationships"] = [
            edge
            for edge in handler.services.lineage_store.list_edges(context.tenant_id)
            if _is_table_asset_relationship(edge)
        ]
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                **bundle,
                "source_mode": "csv_folder",
                "source_read_only": True,
                "csv_source": csv_source,
                "count": {key: len(value) for key, value in bundle.items()},
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_multi_institution_page_data_candidates_get(handler: Any, query: str = "") -> None:
    del query
    try:
        context = handler._request_context()
        handler._require_asset_permission(context, "read")
        candidates = _multi_institution_candidates(handler, context)
        handler._send_json({
            "tenant_id": context.tenant_id,
            "candidates": candidates,
            "count": len(candidates),
            "relationship_required": True,
            "source_read_only": True,
        })
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_data_asset_item_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        item_type = str(payload.get("item_type") or "").strip()
        item = payload.get("item")
        if not isinstance(item, dict):
            raise ValueError("item must be an object.")
        if item_type == "page_data" and not handler.services.permission_broker.enforcer.has_super_admin_role(
            context.user_id, context.tenant_id
        ):
            raise PermissionError("global_super_admin_required_for_page_data")
        handler._require_asset_permission(context, "manage" if item_type == "raw_table" else "create")
        item = dict(item)
        if item_type == "raw_table":
            item = _bind_raw_table_metadata_asset(handler, context, item)
        requested_id = str(item.get("id") or "").strip()
        existing = (
            handler.services.data_asset_store.get_item(context.tenant_id, item_type, requested_id)
            if requested_id
            else None
        )
        if existing:
            expected_lock_version = payload.get("expected_lock_version", item.get("lockVersion"))
            if expected_lock_version is None or int(expected_lock_version) != int(existing.get("lockVersion") or 0):
                raise RuntimeError("data_asset_lock_version_conflict")
        else:
            item["id"] = f"asset_{uuid4().hex}"
        for untrusted_field in (
            "lifecycleStatus",
            "assetVersion",
            "schemaVersion",
            "lockVersion",
            "submittedBy",
            "reviewedBy",
            "reviewedAt",
            "publishedAt",
            "executionId",
            "evidenceId",
            "sourceSnapshot",
            "publicationReady",
            "reviewRequired",
            "tenantBindingMode",
        ):
            item.pop(untrusted_field, None)
        if item_type in {"topic_table", "analysis_experience"} and item.get("analysisTaskId"):
            item = _bind_analysis_asset(handler, context, item_type, item)
        if item_type == "page_data":
            item = _bind_page_data_asset(handler, context, item)
        if item_type == "table_relationship":
            item = _bind_table_relationship_asset(handler, context, item)
        saved = handler.services.data_asset_store.upsert_item(
            context.tenant_id,
            item_type,
            item,
            updated_by=context.user_id,
            # These records are operational configuration, not analytical
            # truth data. Authorized maintainers expect save/toggle actions to
            # take effect immediately. They remain versioned and audited.
            lifecycle_status="active" if item_type in RUNTIME_CONFIGURATION_ASSET_TYPES else "review",
        )
        if item_type == "topic_table" and item.get("analysisTaskId"):
            task = handler.services.task_repository.get_task(str(item["analysisTaskId"]))
            if task:
                snapshot = handler.services.topic_data_store.record_topic_table_snapshot(
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    topic_table_id=str(saved.get("id") or ""),
                    task=task,
                )
                saved = {**saved, "dataSnapshot": snapshot}
        handler._write_audit(context, "data_asset.item.upsert", item_type, str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "item_type": item_type, "item": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_page_data_rows_get(handler: Any, query: str) -> None:
    """Read a bounded projection for one active page-data asset.

    The saved source identity is revalidated against the current tenant CSV
    catalog on every read. A replaced schema therefore fails closed instead of
    silently rendering newly introduced columns.
    """

    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        page_data_id = first_query_value(params, "page_data_id")
        page_code = first_query_value(params, "page_code")
        if not page_data_id:
            raise ValueError("page_data_id is required.")
        payload = read_page_data_rows_payload(
            handler.services,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            page_data_id=page_data_id,
            consumer=page_code,
        )
        handler._send_json(payload)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_page_data_workspace_get(handler: Any, query: str) -> None:
    """Return layout, assigned page-data assets and their rows in one read."""

    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        page_code = first_query_value(params, "page_code")
        if not page_code:
            raise ValueError("page_code is required.")
        handler._send_json(
            read_page_data_workspace_payload(
                handler.services,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                page_code=page_code,
            )
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def read_page_data_workspace_payload(
    services: Any,
    *,
    tenant_id: str,
    user_id: str,
    page_code: str,
) -> dict[str, Any]:
    page_consumers = {"dashboard", "weekly_report", "institution_supervision"}
    if page_code not in page_consumers:
        raise ValueError("page_data_page_code_invalid")
    bundle = services.data_asset_store.list_published_bundle(tenant_id)
    assets = [
        item
        for item in bundle.get("page_data", [])
        if isinstance(item, dict) and _page_data_belongs_to_page(item, page_code)
    ]
    module = services.application_store.get_module(tenant_id, page_code, actor_user_id=user_id)
    state = module.get("state") if isinstance(module, dict) else {}
    if not isinstance(state, dict):
        state = {}
    saved_layout = [str(item or "").strip() for item in state.get("pageDataLayout") or [] if str(item or "").strip()]
    available_ids = [str(item.get("id") or "") for item in assets if str(item.get("id") or "")]
    layout = _resolve_page_data_layout(
        saved_layout,
        available_ids,
        include_newly_assigned=page_code in {"weekly_report", "institution_supervision"},
    )
    workspace_key = (
        tenant_id,
        user_id,
        page_code,
        tuple(layout),
        tuple(
            (
                str(item.get("id") or ""),
                str(item.get("schemaFingerprint") or ""),
                str(item.get("updatedAt") or ""),
                str(item.get("lockVersion") or ""),
                tuple(item.get("metricFields") or []),
                tuple(item.get("dimensionFields") or []),
            )
            for item in assets
            if str(item.get("id") or "") in set(layout)
        ),
    )
    cached_workspace = _PAGE_DATA_WORKSPACE_CACHE.get(workspace_key)
    if cached_workspace and cached_workspace[0] > monotonic():
        return deepcopy(cached_workspace[1])
    rows: dict[str, Any] = {}
    row_errors: dict[str, str] = {}
    for asset_id in layout:
        page_data = next((item for item in assets if str(item.get("id") or "") == asset_id), None)
        if page_data is None:
            continue
        try:
            rows[asset_id] = read_page_data_rows_payload(
                services,
                tenant_id=tenant_id,
                user_id=user_id,
                page_data_id=asset_id,
                consumer=page_code,
                bundle=bundle,
                page_data=page_data,
            )
        except Exception as exc:
            row_errors[asset_id] = str(exc) or "page_data_rows_unavailable"
    payload = {
        "tenant_id": tenant_id,
        "page_code": page_code,
        "assets": assets,
        "layout": layout,
        "notes": list(state.get("pageDataNotes") or []),
        "rows": rows,
        "row_errors": row_errors,
    }
    complete = bool(assets) and bool(layout) and all(asset_id in rows for asset_id in layout)
    if complete:
        if len(_PAGE_DATA_WORKSPACE_CACHE) >= 32:
            _PAGE_DATA_WORKSPACE_CACHE.pop(next(iter(_PAGE_DATA_WORKSPACE_CACHE)))
        _PAGE_DATA_WORKSPACE_CACHE[workspace_key] = (monotonic() + _PAGE_DATA_WORKSPACE_CACHE_TTL_SECONDS, deepcopy(payload))
    return payload


def read_page_data_rows_payload(
    services: Any,
    *,
    tenant_id: str,
    user_id: str,
    page_data_id: str,
    consumer: str,
    bundle: dict[str, Any] | None = None,
    page_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one page-data projection through its governed source chain.

    Page modules retain their explicit target-page contract. Analytical
    consumers may reuse only multi-institution page data; they never receive a
    cross-institution raw-table catalog. Every read revalidates account scope,
    relationship identity, source schemas and institution provenance.
    """

    page_consumers = {"dashboard", "weekly_report", "institution_supervision"}
    analytical_consumers = {"self_analysis", "visual_report", "my_reports"}
    if consumer not in page_consumers | analytical_consumers:
        raise ValueError("page_data_page_code_invalid")
    context = SimpleNamespace(tenant_id=tenant_id, user_id=user_id)
    handler = SimpleNamespace(services=services)
    if bundle is None:
        bundle = services.data_asset_store.list_published_bundle(tenant_id)
    if page_data is None:
        page_data = next(
            (item for item in bundle.get("page_data", []) if str(item.get("id") or "") == page_data_id),
            None,
        )
    if page_data is None:
        raise PermissionError("page_data_unavailable_for_page")
    scope = _page_data_scope(page_data)
    if consumer in page_consumers:
        if consumer not in page_data.get("targetPages", []):
            raise PermissionError("page_data_unavailable_for_page")
        if (consumer == "dashboard") != (scope == MULTI_INSTITUTION_PAGE_DATA_SCOPE):
            raise PermissionError("page_data_scope_unavailable_for_page")
    elif scope != MULTI_INSTITUTION_PAGE_DATA_SCOPE:
        raise PermissionError("page_data_scope_unavailable_for_analysis")

    dimensions = [str(field) for field in page_data.get("dimensionFields", [])]
    metrics = [str(field) for field in page_data.get("metricFields", [])]
    selected_fields = list(dict.fromkeys([*dimensions, *metrics]))
    if scope == MULTI_INSTITUTION_PAGE_DATA_SCOPE:
        sources = _multi_page_data_source_tables(handler, context, page_data)
        data_fields = [field for field in selected_fields if field != MULTI_INSTITUTION_DIMENSION]
        if not sources or not data_fields or MULTI_INSTITUTION_DIMENSION not in dimensions:
            raise PermissionError("page_data_selected_field_unavailable")
        cache_key = (
            "multi",
            tenant_id,
            page_data_id,
            consumer,
            str(page_data.get("schemaFingerprint") or ""),
            tuple(selected_fields),
            tuple(sorted(
                (
                    str(source.get("tenantId") or ""),
                    str(source.get("sourceKey") or ""),
                    str(source_table.get("contentHash") or ""),
                    str(source_table.get("schemaFingerprint") or ""),
                )
                for source, source_table in sources
            )),
        )
        cached = _page_data_projection_cache_get(cache_key)
        if cached is not None:
            return cached
        rows: list[dict[str, str]] = []
        by_tenant: dict[str, list[tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]]] = {}
        institution_count = len({str(source["tenantId"]) for source, _ in sources})
        per_tenant_limit = max(1, 500 // max(1, institution_count))
        for source, source_table in sources:
            _, raw_rows = services.data_acquisition_service.csv_source.for_tenant(str(source["tenantId"])).read_rows(
                str(source_table.get("relativePath") or ""),
                max_rows=per_tenant_limit,
            )
            by_tenant.setdefault(str(source["tenantId"]), []).append((source, source_table, raw_rows))
        relationship_edges = [dict(edge) for edge in page_data.get("relationshipEdges", []) if isinstance(edge, dict)]
        for source_tenant_id, tenant_sources in by_tenant.items():
            local_node_ids = {str(source.get("nodeId") or "") for source, _, _ in tenant_sources}
            local_edges = [
                edge for edge in relationship_edges
                if str(edge.get("sourceNodeId") or "") in local_node_ids
                and str(edge.get("targetNodeId") or "") in local_node_ids
            ]
            joined_rows = _join_institution_rows(tenant_sources, local_edges)
            institution_name = str(tenant_sources[0][0].get("institutionName") or source_tenant_id)
            for row in joined_rows:
                rows.append({MULTI_INSTITUTION_DIMENSION: institution_name, **{field: row.get(field, "") for field in data_fields}})
        rows = rows[:500]
        labels = {
            MULTI_INSTITUTION_DIMENSION: "机构",
            **{
                str(field.get("fieldNameEn") or ""): str(field.get("fieldNameCn") or field.get("fieldNameEn") or "")
                for field in page_data.get("sourceFields", [])
                if str(field.get("fieldNameEn") or "") in data_fields
            },
        }
    else:
        table = _page_data_source_table(handler, tenant_id, page_data)
        available = {str(field.get("fieldNameEn") or "") for field in table.get("fields", [])}
        if not selected_fields or any(field not in available for field in selected_fields):
            raise PermissionError("page_data_selected_field_unavailable")
        cache_key = (
            "single",
            tenant_id,
            page_data_id,
            consumer,
            str(table.get("contentHash") or ""),
            str(table.get("schemaFingerprint") or ""),
            tuple(selected_fields),
        )
        cached = _page_data_projection_cache_get(cache_key)
        if cached is not None:
            return cached
        _, source_rows = services.data_acquisition_service.csv_source.for_tenant(tenant_id).read_rows(
            str(table.get("relativePath") or ""),
            max_rows=500,
        )
        labels = {
            str(field.get("fieldNameEn") or ""): str(field.get("fieldNameCn") or field.get("fieldNameEn") or "")
            for field in table.get("fields", [])
            if str(field.get("fieldNameEn") or "") in selected_fields
        }
        rows = _project_page_data_rows(table, source_rows, selected_fields)

    payload = {
        "tenant_id": tenant_id,
        "page_code": consumer,
        "page_data_id": page_data_id,
        "source_key": str(page_data.get("sourceKey") or ""),
        "relationship_group_id": str(page_data.get("relationshipGroupId") or ""),
        "institution_scope": scope,
        "schema_fingerprint": str(page_data.get("schemaFingerprint") or ""),
        "fields": selected_fields,
        "field_labels": labels,
        "row_count": len(rows),
        "rows": rows,
        "bounded": True,
    }
    _page_data_projection_cache_put(cache_key, payload)
    return payload


def _page_data_projection_cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    cached = _PAGE_DATA_PROJECTION_CACHE.get(key)
    return deepcopy(cached) if cached is not None else None


def _page_data_projection_cache_put(key: tuple[Any, ...], payload: dict[str, Any]) -> None:
    if key not in _PAGE_DATA_PROJECTION_CACHE and len(_PAGE_DATA_PROJECTION_CACHE) >= _PAGE_DATA_PROJECTION_CACHE_MAX:
        _PAGE_DATA_PROJECTION_CACHE.pop(next(iter(_PAGE_DATA_PROJECTION_CACHE)))
    _PAGE_DATA_PROJECTION_CACHE[key] = deepcopy(payload)


def _page_data_belongs_to_page(item: dict[str, Any], page_code: str) -> bool:
    scope = _page_data_scope(item)
    targets = [str(page) for page in item.get("targetPages", [])] if isinstance(item.get("targetPages"), list) else []
    if page_code == "dashboard":
        return scope == MULTI_INSTITUTION_PAGE_DATA_SCOPE and "dashboard" in targets
    if page_code not in {"weekly_report", "institution_supervision"}:
        return False
    assigned = "institution_supervision" if "institution_supervision" in targets else "weekly_report"
    return scope == SINGLE_INSTITUTION_PAGE_DATA_SCOPE and assigned == page_code


def _resolve_page_data_layout(saved_layout: list[str], available_ids: list[str], *, include_newly_assigned: bool) -> list[str]:
    available = set(available_ids)
    kept = [asset_id for asset_id in saved_layout if asset_id in available]
    extras = [asset_id for asset_id in available_ids if asset_id not in kept]
    if include_newly_assigned:
        return [*kept, *extras]
    return kept or list(available_ids)


def _bind_page_data_asset(handler: Any, context: Any, item: dict[str, Any]) -> dict[str, Any]:
    scope = _page_data_scope(item)
    if scope == MULTI_INSTITUTION_PAGE_DATA_SCOPE:
        relationship_group_id = str(item.get("relationshipGroupId") or item.get("sourceKey") or "").strip()
        candidate = next(
            (candidate for candidate in _multi_institution_candidates(handler, context) if str(candidate.get("id") or "") == relationship_group_id),
            None,
        )
        if candidate is None:
            raise PermissionError("multi_institution_page_data_relationship_unavailable")
        available = {str(field.get("fieldNameEn") or "") for field in candidate.get("fields", [])}
        metrics = [str(field or "").strip() for field in item.get("metricFields", [])]
        requested_dimensions = [
            str(field or "").strip()
            for field in item.get("dimensionFields", [])
            if str(field or "").strip() != MULTI_INSTITUTION_DIMENSION
        ]
        selected = [*requested_dimensions, *metrics]
        if not metrics or any(not field or field not in available for field in selected):
            raise ValueError("page_data_selected_field_unavailable")
        return {
            **item,
            "institutionScope": MULTI_INSTITUTION_PAGE_DATA_SCOPE,
            "relationshipGroupId": str(candidate["id"]),
            "sourceKey": str(candidate["id"]),
            "sourceTableId": str(candidate["id"]),
            "sourceTableName": str(candidate["name"]),
            "sourceRelativePath": "",
            "sourceFields": [
                {
                    "fieldNameEn": MULTI_INSTITUTION_DIMENSION,
                    "fieldNameCn": "机构",
                    "type": "string",
                    "semanticRole": "dimension",
                    "isMetric": False,
                    "isTime": False,
                },
                *[dict(field) for field in candidate.get("fields", []) if isinstance(field, dict)],
            ],
            "targetPages": ["dashboard"],
            "metricFields": metrics,
            "dimensionFields": [MULTI_INSTITUTION_DIMENSION, *requested_dimensions],
            "schemaFingerprint": str(candidate["schemaFingerprint"]),
            "contentHash": "",
            "institutionSources": [dict(source) for source in candidate.get("sources", [])],
            "relationshipEdges": [dict(edge) for edge in candidate.get("relationshipEdges", [])],
        }

    source_key = str(item.get("sourceKey") or "").strip()
    table = next(
        (
            candidate
            for candidate in handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id).table_assets()
            if str(candidate.get("sourceKey") or "") == source_key
        ),
        None,
    )
    if table is None:
        raise PermissionError("page_data_source_unavailable")
    if str(item.get("schemaFingerprint") or "") != str(table.get("schemaFingerprint") or ""):
        raise ValueError("page_data_source_schema_changed")
    available = {str(field.get("fieldNameEn") or "") for field in table.get("fields", [])}
    selected = [
        *[str(field or "").strip() for field in item.get("dimensionFields", [])],
        *[str(field or "").strip() for field in item.get("metricFields", [])],
    ]
    if not selected or any(field not in available for field in selected):
        raise ValueError("page_data_selected_field_unavailable")
    return {
        **item,
        "institutionScope": SINGLE_INSTITUTION_PAGE_DATA_SCOPE,
        "sourceTableId": str(table.get("id") or ""),
        "sourceTableName": str(table.get("tableNameCn") or table.get("tableNameEn") or ""),
        "sourceRelativePath": str(table.get("relativePath") or ""),
        "sourceFields": [dict(field) for field in table.get("fields", [])],
        "schemaFingerprint": str(table.get("schemaFingerprint") or ""),
        "contentHash": str(table.get("contentHash") or ""),
    }


def _multi_page_data_source_tables(handler: Any, context: Any, page_data: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    authorized_tenants = set(_authorized_tenant_labels(handler, context))
    saved_sources = page_data.get("institutionSources")
    if not isinstance(saved_sources, list) or any(
        not isinstance(source, dict) or _normalized_tenant_id(str(source.get("tenantId") or "")) not in authorized_tenants
        for source in saved_sources
    ):
        raise PermissionError("multi_institution_page_data_sources_unavailable")
    relationship_id = str(page_data.get("relationshipGroupId") or "")
    candidates = _multi_institution_candidates(handler, context)
    candidate = next((item for item in candidates if str(item.get("id") or "") == relationship_id), None)
    if candidate is None and not relationship_id:
        saved_refs = {
            (_normalized_tenant_id(str(source.get("tenantId") or "")), str(source.get("sourceKey") or ""))
            for source in page_data.get("institutionSources", [])
            if isinstance(source, dict)
        }
        candidate = next((
            item for item in candidates
            if saved_refs == {
                (_normalized_tenant_id(str(source.get("tenantId") or "")), str(source.get("sourceKey") or ""))
                for source in item.get("sources", [])
                if isinstance(source, dict)
            }
        ), None)
    if candidate is None or str(candidate.get("schemaFingerprint") or "") != str(page_data.get("schemaFingerprint") or ""):
        raise PermissionError("multi_institution_page_data_source_schema_changed")
    sources = candidate.get("sources")
    if not isinstance(sources, list) or len(sources) < 2:
        raise PermissionError("multi_institution_page_data_sources_unavailable")
    resolved: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_refs: set[tuple[str, str]] = set()
    for raw_source in sources:
        if not isinstance(raw_source, dict):
            raise PermissionError("multi_institution_page_data_sources_unavailable")
        tenant_id = _normalized_tenant_id(str(raw_source.get("tenantId") or ""))
        source_key = str(raw_source.get("sourceKey") or "").strip()
        if not tenant_id or not source_key or (tenant_id, source_key) in seen_refs:
            raise PermissionError("multi_institution_page_data_sources_unavailable")
        table = next(
            (
                candidate
                for candidate in handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id).table_assets()
                if str(candidate.get("sourceKey") or "") == source_key
            ),
            None,
        )
        if table is None or str(table.get("schemaFingerprint") or "") != str(raw_source.get("schemaFingerprint") or ""):
            raise PermissionError("multi_institution_page_data_source_schema_changed")
        seen_refs.add((tenant_id, source_key))
        resolved.append(({
            "nodeId": str(raw_source.get("nodeId") or ""),
            "tenantId": tenant_id,
            "institutionName": str(raw_source.get("institutionName") or tenant_id),
            "sourceKey": source_key,
        }, table))
    return resolved


def _join_institution_rows(
    source_rows: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]],
    relationship_edges: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Inner-join tables inside one institution; cross-institution links define equivalence only."""

    if not source_rows:
        return []
    node_rows: dict[str, list[dict[str, str]]] = {}
    for source, table, rows in source_rows:
        node_rows[str(source.get("nodeId") or "")] = _project_page_data_rows(
            table,
            rows,
            [str(field.get("fieldNameEn") or "") for field in table.get("fields", []) if isinstance(field, dict)],
        )
    first_node = str(source_rows[0][0].get("nodeId") or "")
    joined = [dict(row) for row in node_rows[first_node]]
    joined_nodes = {first_node}
    remaining = set(node_rows) - joined_nodes
    while remaining:
        link = next((
            edge for edge in relationship_edges
            if isinstance(edge, dict)
            and (
                (str(edge.get("sourceNodeId") or "") in joined_nodes and str(edge.get("targetNodeId") or "") in remaining)
                or (str(edge.get("targetNodeId") or "") in joined_nodes and str(edge.get("sourceNodeId") or "") in remaining)
            )
        ), None)
        if link is None:
            raise PermissionError("multi_institution_page_data_relationship_disconnected")
        source_in_joined = str(link.get("sourceNodeId") or "") in joined_nodes
        next_node = str(link.get("targetNodeId") if source_in_joined else link.get("sourceNodeId") or "")
        joined_field = str(link.get("sourceField") if source_in_joined else link.get("targetField") or "")
        next_field = str(link.get("targetField") if source_in_joined else link.get("sourceField") or "")
        index: dict[str, list[dict[str, str]]] = {}
        for row in node_rows[next_node]:
            index.setdefault(str(row.get(next_field) or ""), []).append(row)
        merged: list[dict[str, str]] = []
        for row in joined:
            for match in index.get(str(row.get(joined_field) or ""), []):
                merged.append({**match, **row})
                if len(merged) >= 500:
                    break
            if len(merged) >= 500:
                break
        joined = merged
        joined_nodes.add(next_node)
        remaining.remove(next_node)
    return joined


def _page_data_source_table(handler: Any, tenant_id: str, page_data: dict[str, Any]) -> dict[str, Any]:
    source_key = str(page_data.get("sourceKey") or "")
    table = next(
        (
            candidate
            for candidate in handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id).table_assets()
            if str(candidate.get("sourceKey") or "") == source_key
        ),
        None,
    )
    if table is None:
        raise PermissionError("page_data_source_unavailable")
    if str(page_data.get("schemaFingerprint") or "") != str(table.get("schemaFingerprint") or ""):
        raise PermissionError("page_data_source_schema_changed")
    return table


def _project_page_data_rows(
    table: dict[str, Any], source_rows: list[dict[str, str]], selected_fields: list[str],
) -> list[dict[str, str]]:
    """Translate protected CSV headers into the stable schema field codes.

    ``read_rows`` deliberately returns the original delivered headers while
    page-data assets persist the catalog's stable ``fieldNameEn`` codes.  The
    projection must therefore use the catalog mapping instead of looking up
    field codes directly in source rows.
    """

    source_headers = {
        str(field.get("fieldNameEn") or ""): str(field.get("fieldNameCn") or field.get("fieldNameEn") or "")
        for field in table.get("fields", [])
        if isinstance(field, dict)
    }
    return [
        {field: source.get(source_headers.get(field, field), "") for field in selected_fields}
        for source in source_rows
    ]


def handle_data_asset_raw_file_upload(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=12 * 1024 * 1024)
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        encoded = str(payload.get("content_base64") or payload.get("contentBase64") or "").strip()
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid_content_base64") from exc
        result = handler.services.data_acquisition_service.upload_raw_asset_file(
            context.tenant_id,
            str(payload.get("file_name") or payload.get("fileName") or ""),
            content,
            context.user_id,
        )
        handler._write_audit(
            context,
            "data_asset.raw_file.upload",
            "raw_file",
            str(result.get("artifact_id") or ""),
            {
                "file_name": result.get("file_name"),
                "content_hash": result.get("content_hash"),
                "size_bytes": result.get("size_bytes"),
                "table_count": result.get("table_count", 0),
                "duplicate": bool(result.get("duplicate")),
                "immutable": bool(result.get("immutable")),
            },
        )
        handler._send_json({"tenant_id": context.tenant_id, "file": result})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_raw_table_external_reference_update(handler: Any) -> None:
    """Persist SDA-side WorkBuddy consent without ever writing the CSV file."""

    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "manage")
        source_key = str(payload.get("source_key") or payload.get("sourceKey") or "").strip()
        mode = str(payload.get("mode") or "").strip().lower()
        schema_fingerprint = str(payload.get("schema_fingerprint") or payload.get("schemaFingerprint") or "").strip()
        tables = handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id).table_assets()
        table = next((item for item in tables if str(item.get("sourceKey") or "") == source_key), None)
        if table is None:
            raise PermissionError("raw_table_external_reference_source_unavailable")
        if schema_fingerprint != str(table.get("schemaFingerprint") or ""):
            raise ValueError("raw_table_external_reference_schema_changed")
        record = handler.services.data_asset_store.set_raw_table_external_reference(
            context.tenant_id, source_key, mode, schema_fingerprint, context.user_id,
        )
        handler._write_audit(
            context,
            "data_asset.raw_table.external_reference.update",
            "raw_table_source",
            source_key,
            {"mode": record["mode"], "schema_fingerprint": record["schemaFingerprint"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "external_reference": record})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_topic_data_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        reference_type = first_query_value(params, "reference_type")
        reference_id = first_query_value(params, "reference_id")
        data_type = first_query_value(params, "data_type") or "data"
        if reference_type == "topic":
            topic = handler.services.data_asset_store.get_item(context.tenant_id, "topic_table", reference_id)
            if topic is None:
                raise PermissionError("topic_table_unavailable")
        elif reference_type == "report":
            report = handler.services.report_store.get_analysis_result(
                context.tenant_id,
                reference_id,
                actor_user_id=context.user_id,
            )
            if report is None:
                raise PermissionError("saved_report_unavailable")
        result = handler.services.topic_data_store.read_reference(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            reference_type=reference_type,
            reference_id=reference_id,
            data_type=data_type,
        )
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _bind_analysis_asset(handler: Any, context: Any, item_type: str, item: dict[str, Any]) -> dict[str, Any]:
    task_id = str(item.get("analysisTaskId") or "").strip()
    task = handler.services.task_repository.get_task(task_id)
    if not task or task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id:
        raise PermissionError("analysis_task_unavailable_for_asset")
    results = task.get("skill_results") if isinstance(task.get("skill_results"), list) else []
    result = results[0] if results and isinstance(results[0], dict) else {}
    semantic = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    review = task.get("review") if isinstance(task.get("review"), dict) else {}
    evidence_ready = bool(
        task.get("status") in {"completed", "review_required"}
        and str(semantic.get("execution_mode") or "") not in {"", "mock", "demo", "fallback", "unverified"}
        and evidence.get("evidence_id")
        and isinstance(evidence.get("source_snapshot"), dict)
        and evidence.get("source_snapshot")
        and evidence.get("sql_executed") is True
    )
    if not evidence_ready:
        raise ValueError("executed_analysis_evidence_required_for_asset_candidate")
    publishable = bool(
        task.get("status") == "completed"
        and review.get("status") == "passed"
        and review.get("publication_gate") == "allowed"
        and semantic.get("publishable") is True
    )
    bound = {
        **item,
        "analysisTaskId": task_id,
        "executionId": str(task.get("execution_id") or task_id),
        "evidenceId": str(evidence.get("evidence_id") or ""),
        "sourceSnapshot": evidence.get("source_snapshot"),
        "publicationReady": publishable,
        "reviewRequired": not publishable,
        "tenantBindingMode": "analysis_task_scoped",
    }
    if item_type == "topic_table":
        bound["sql"] = _detail_query_from_execution(str(evidence.get("executed_sql") or ""))
        rows = result.get("data") if isinstance(result.get("data"), list) else []
        if rows and isinstance(rows[0], dict):
            requested_fields = bound.get("fields") if isinstance(bound.get("fields"), list) else []
            requested_names = {
                str(field.get("fieldNameEn") or "")
                for field in requested_fields
                if isinstance(field, dict)
            }
            actual_names = set(rows[0])
            if not requested_names or not requested_names.issubset(actual_names):
                raise ValueError("topic_table_fields_do_not_match_executed_result")
    else:
        bound["sourceVersionId"] = task_id
        bound["evidence"] = f"analysis_evidence:{evidence.get('evidence_id')}"
    return bound


def _detail_query_from_execution(executed_sql: str) -> str:
    sql = executed_sql.strip()
    if not sql:
        raise ValueError("executed_sql_required_for_topic_table")
    lines = sql.splitlines()
    while lines and lines[0].lstrip().startswith("--"):
        lines.pop(0)
    sql = "\n".join(lines).strip()
    if not sql:
        raise ValueError("executed_sql_required_for_topic_table")
    if ";" in sql.rstrip(";"):
        raise ValueError("topic_table_requires_single_executed_query")
    return sql.rstrip(";").strip()


def handle_data_asset_item_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "manage")
        item_type = str(payload.get("item_type") or "").strip()
        item_id = str(payload.get("item_id") or "").strip()
        decision = str(payload.get("decision") or "").strip()
        if not item_type or not item_id:
            raise ValueError("item_type and item_id are required.")
        reviewed = handler.services.data_asset_store.review_item(
            context.tenant_id,
            item_type,
            item_id,
            decision=decision,
            reviewer_user_id=context.user_id,
            comments=str(payload.get("comments") or ""),
            expected_version=int(payload["expected_version"]) if payload.get("expected_version") is not None else None,
        )
        handler._write_audit(
            context,
            "data_asset.item.review",
            item_type,
            item_id,
            {"decision": decision, "version": reviewed.get("assetVersion")},
        )
        handler._send_json({"tenant_id": context.tenant_id, "item_type": item_type, "item": reviewed})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_data_asset_item_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        item_type = first_query_value(params, "item_type")
        item_id = first_query_value(params, "item_id")
        if not item_type or not item_id:
            raise ValueError("item_type and item_id are required.")
        if item_type == "page_data" and not handler.services.permission_broker.enforcer.has_super_admin_role(
            context.user_id, context.tenant_id
        ):
            raise PermissionError("global_super_admin_required_for_page_data")
        handler._require_asset_permission(context, "create")
        deleted = handler.services.data_asset_store.delete_item(context.tenant_id, item_type, item_id)
        updated_shortcut_count = (
            _remove_deleted_skill_references(handler, context, item_id)
            if deleted and item_type == "analysis_skill"
            else 0
        )
        handler._write_audit(
            context,
            "data_asset.item.delete",
            item_type,
            item_id,
            {"deleted": deleted, "updated_shortcut_count": updated_shortcut_count},
        )
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "item_type": item_type,
                "item_id": item_id,
                "deleted": deleted,
                "updated_shortcut_count": updated_shortcut_count,
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _remove_deleted_skill_references(handler: Any, context: Any, skill_id: str) -> int:
    """Remove a deleted Skill from saved shortcut configuration in this tenant."""
    store = handler.services.data_asset_store
    updated_count = 0
    for shortcut in store.list_bundle(context.tenant_id).get("analysis_shortcuts", []):
        skill_ids = shortcut.get("skillIds") if isinstance(shortcut.get("skillIds"), list) else []
        next_skill_ids = [str(candidate) for candidate in skill_ids if str(candidate) != skill_id]
        if len(next_skill_ids) == len(skill_ids):
            continue
        store.upsert_item(
            context.tenant_id,
            "analysis_shortcut",
            {**shortcut, "skillIds": next_skill_ids},
            updated_by=context.user_id,
            lifecycle_status="active",
        )
        updated_count += 1
    return updated_count
