from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from time import monotonic
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from backend.authz import normalize_tenant_id
from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.customer_segment import MAX_CUSTOMER_IDS, customer_ids_for_user
from backend.platform.integrations.data_crawler import client_for_tenant
from backend.platform.tenancy.catalog import list_active_tenants


RUNTIME_CONFIGURATION_ASSET_TYPES = frozenset({
    "raw_table",
    "analysis_skill",
    "external_tool",
    "analysis_shortcut",
    "page_data", "table_relationship", "conclusion_rule",
})
TABLE_ASSET_LINEAGE_TYPES = frozenset({"dataset", "topic_table", "raw_table"})
VISUALIZATION_ASSET_KEYS = (
    "raw_tables", "topic_tables", "intents", "analysis_experiences", "behavior_habits",
    "knowledge_files", "analysis_skills", "external_tools", "analysis_shortcuts", "page_data", "table_relationships", "conclusion_rules", "relationships",
)
VISUALIZATION_TOPIC_LIFECYCLE_STATUSES = frozenset({"draft", "review", "active"})
SINGLE_INSTITUTION_PAGE_DATA_SCOPE = "single_institution"
MULTI_INSTITUTION_PAGE_DATA_SCOPE = "multi_institution"
CUSTOMER_SEGMENT_PAGE_DATA_SCOPE = "customer_segment"
MULTI_INSTITUTION_DIMENSION = "__institution_name"
MULTI_INSTITUTION_RELATIONSHIP_SCOPE = "multi_institution"
SINGLE_INSTITUTION_RELATIONSHIP_SCOPE = "single_institution"
_PAGE_DATA_PROJECTION_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_PAGE_DATA_PROJECTION_CACHE_MAX = 48
_PAGE_DATA_WORKSPACE_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_PAGE_DATA_WORKSPACE_CACHE_TTL_SECONDS = 20.0
_RELATIONSHIP_CATALOG_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_RELATIONSHIP_CATALOG_CACHE_TTL_SECONDS = 20.0
_CRAWLER_CATALOG_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="crawler-catalog")


def _crawler_catalog_key(institution_id: str, sql_id: str) -> str:
    identity = f"{str(institution_id).strip()}:{str(sql_id).strip()}"
    return f"crawler_sql_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


def _load_crawler_bindings(tenant_id: str) -> tuple[Any, dict[str, Any]]:
    client = client_for_tenant(tenant_id)
    return client, client.list_bindings()


def _merge_crawler_sql_catalog(
    tables: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    *,
    institution_id: str,
    institution_name: str,
) -> list[dict[str, Any]]:
    """Project every SQL script and attach only its manifest-backed CSV.

    SQL catalog presence and CSV delivery presence are deliberately separate.
    A script-only entry is visible in 原始表 for scheduling, but has no
    ``sourceKey`` and therefore cannot enter any data consumer.
    """

    data_by_sql_id: dict[str, dict[str, Any]] = {}
    unbound_tables: list[dict[str, Any]] = []
    for source in tables:
        table = {**source, "dataAvailable": True, "deliveryStatus": "available"}
        sql_id = str(table.get("sqlId") or "").strip()
        if sql_id:
            current = data_by_sql_id.get(sql_id)
            current_time = str((current or {}).get("crawlerFinishedAt") or (current or {}).get("updatedAt") or "")
            candidate_time = str(table.get("crawlerFinishedAt") or table.get("updatedAt") or "")
            if current is None or candidate_time > current_time:
                data_by_sql_id[sql_id] = table
        else:
            unbound_tables.append(table)

    projected: list[dict[str, Any]] = []
    seen_sql_ids: set[str] = set()
    for source_binding in bindings:
        binding = dict(source_binding) if isinstance(source_binding, dict) else {}
        sql_id = str(binding.get("sqlId") or "").strip()
        if (
            not sql_id
            or sql_id in seen_sql_ids
            or str(binding.get("institutionId") or "").strip() != institution_id
        ):
            continue
        seen_sql_ids.add(sql_id)
        catalog_key = _crawler_catalog_key(institution_id, sql_id)
        delivered = data_by_sql_id.pop(sql_id, None)
        if delivered is not None:
            projected.append({
                **delivered,
                "catalogKey": catalog_key,
                "sqlId": sql_id,
                "sqlName": str(binding.get("sqlName") or delivered.get("tableNameCn") or sql_id),
                "sqlParameters": [dict(item) for item in binding.get("parameters") or [] if isinstance(item, dict)],
                "dataAvailable": True,
                "deliveryStatus": "available",
            })
            continue
        sql_name = str(binding.get("sqlName") or sql_id)
        projected.append({
            "id": catalog_key,
            "assetId": f"raw-script:{catalog_key}",
            "catalogKey": catalog_key,
            "tableNameEn": sql_id,
            "tableNameCn": sql_name,
            "sqlName": sql_name,
            "source": "Data Crawler SQL 目录",
            "tableType": "sql_script",
            "primaryKey": "",
            "primaryKeys": [],
            "dateField": "",
            "orgField": "",
            "customerField": "",
            "description": "SQL 脚本已同步，尚未执行并交付 CSV。",
            "updateFrequency": "按手动刷新或定时任务执行",
            "restrictions": "仅可配置和执行；生成有效 CSV 前不会进入分析、页面数据、表关系、周报或可视化。",
            "exampleSql": "",
            "fields": [],
            "updatedAt": str((binding.get("latestDelivery") or {}).get("finishedAt") or ""),
            "rowCount": 0,
            "previewRows": [],
            "sqlId": sql_id,
            "sqlParameters": [dict(item) for item in binding.get("parameters") or [] if isinstance(item, dict)],
            "institutionId": institution_id,
            "institutionName": institution_name,
            "sourcePlatform": "毓数",
            "dataAvailable": False,
            "deliveryStatus": "not_executed",
            "lifecycleStatus": "active",
            "assetVersion": str(binding.get("sqlTemplateSha256") or "")[:16],
            "schemaVersion": "crawler_sql_catalog_v1",
            "lockVersion": 1,
        })

    # A manifest-backed CSV remains usable if its SQL was later removed from
    # the live catalog.  It stays data-backed, but cannot be refreshed or
    # scheduled until the producer restores the binding.
    for sql_id, table in data_by_sql_id.items():
        projected.append({
            **table,
            "catalogKey": _crawler_catalog_key(institution_id, sql_id),
            "dataAvailable": True,
            "deliveryStatus": "binding_missing",
        })
    projected.extend(unbound_tables)
    return projected


def _csv_table_assets(catalog: Any, *, wait_for_catalog: bool) -> list[dict[str, Any]]:
    """Return CSV tables for one tenant catalog.

    A catalog that is still priming is not a schema change. Page-data reads
    must wait for that first scan; skipping it makes the first multi-institution
    dashboard open fail closed with ``multi_institution_page_data_source_schema_changed``.
    """

    if catalog is None:
        return []
    if not getattr(catalog, "catalog_ready", True):
        if not wait_for_catalog:
            return []
        prime = getattr(catalog, "prime_catalog", None)
        if callable(prime):
            prime()
        else:
            waiter = getattr(catalog, "wait_until_ready", None)
            if callable(waiter):
                waiter(30.0)
    tables = catalog.table_assets() if hasattr(catalog, "table_assets") else []
    return [dict(item) for item in tables if isinstance(item, dict)]


def _raw_tables_for_tenant(handler: Any, tenant_id: str, *, wait_for_catalog: bool) -> list[dict[str, Any]]:
    """Return one tenant's CSV tables with the same metadata overlay as the picker."""

    catalog = handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id)
    tables = _csv_table_assets(catalog, wait_for_catalog=wait_for_catalog)
    data_asset_store = getattr(handler.services, "data_asset_store", None)
    stored = data_asset_store.list_bundle(tenant_id) if data_asset_store is not None else {"raw_tables": []}
    overlays = {
        str(item.get("sourceKey") or ""): item
        for item in stored.get("raw_tables", [])
        if isinstance(item, dict) and item.get("metadataOverlayVersion") == 1 and str(item.get("sourceKey") or "")
    }
    result: list[dict[str, Any]] = []
    for raw_table in tables:
        source_key = str(raw_table.get("sourceKey") or "").strip()
        if not source_key:
            continue
        overlay = overlays.get(source_key)
        table = dict(raw_table)
        if overlay:
            table = _raw_table_with_metadata_overlay(table, overlay)
        result.append(table)
    return result


def _authorized_raw_table_catalog(
    handler: Any,
    context: Any,
    *,
    wait_for_catalog: bool = True,
) -> tuple[dict[str, str], dict[tuple[str, str], dict[str, Any]]]:
    """Return authoritative, permission-filtered tables with server-owned institution labels.

    Relationship catalog listing passes ``wait_for_catalog=False`` so a cold CSV
    scan in another institution cannot stall the dataset picker past the client
    timeout. Page-data reads keep the wait so the first dashboard open does not
    fail closed as a schema change.
    """

    direct_tenant_labels = _direct_authorized_tenant_labels(handler, context)
    tenant_labels = _authorized_tenant_labels(handler, context)
    active_tenant_ids = set(_active_tenant_labels(handler))
    scope_service = getattr(handler.services, "tenant_scope_service", None)
    granted_scopes = scope_service.resource_grant_scopes(
        user_id=context.user_id,
        recipient_tenant_id=context.tenant_id,
        active_tenant_ids=active_tenant_ids,
        resource_type="raw_table",
        action="read",
    ) if scope_service is not None else {}
    table_by_ref: dict[tuple[str, str], dict[str, Any]] = {}
    for tenant_id in tenant_labels:
        for table in _raw_tables_for_tenant(handler, tenant_id, wait_for_catalog=wait_for_catalog):
            source_key = str(table.get("sourceKey") or "").strip()
            if not source_key:
                continue
            if tenant_id in direct_tenant_labels:
                table_by_ref[(tenant_id, source_key)] = table
                continue
            scope = granted_scopes.get((tenant_id, source_key, str(table.get("schemaFingerprint") or "")))
            projected = _granted_raw_table_projection(table, scope)
            if projected is not None:
                table_by_ref[(tenant_id, source_key)] = projected
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
    session = handler.services.access_service.session_for_user(context.user_id, tenant_hint=context.tenant_id)
    session_tenant_ids = {
        _normalized_tenant_id(str(label or ""))
        for label in session.get("institutions", [])
        if str(label or "").strip()
    }
    session_tenant_ids.add(context.tenant_id)
    direct_tenant_labels = {
        tenant_id: label for tenant_id, label in tenant_labels.items() if tenant_id in session_tenant_ids
    }
    active_tenant_ids = set(_active_tenant_labels(handler))
    scope_service = getattr(handler.services, "tenant_scope_service", None)
    granted_scopes = scope_service.resource_grant_scopes(
        user_id=context.user_id,
        recipient_tenant_id=context.tenant_id,
        active_tenant_ids=active_tenant_ids,
        resource_type="raw_table",
        action="read",
    ) if scope_service is not None else {}

    table_by_ref: dict[tuple[str, str], dict[str, Any]] = {}
    data_asset_store = getattr(handler.services, "data_asset_store", None)
    for tenant_id, source_keys in requested_sources.items():
        if tenant_id not in tenant_labels:
            continue
        catalog = handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id)
        stored = data_asset_store.list_bundle(tenant_id) if data_asset_store is not None else {"raw_tables": []}
        overlays = {
            str(item.get("sourceKey") or ""): item
            for item in stored.get("raw_tables", [])
            if isinstance(item, dict)
            and item.get("metadataOverlayVersion") == 1
            and str(item.get("sourceKey") or "") in source_keys
        }
        remaining = set(source_keys)
        for raw_table in _csv_table_assets(catalog, wait_for_catalog=True):
            source_key = str(raw_table.get("sourceKey") or "").strip()
            if source_key not in remaining:
                continue
            table = _raw_table_with_metadata_overlay(
                dict(raw_table), overlays.get(source_key),
            )
            if tenant_id not in direct_tenant_labels:
                scope = granted_scopes.get((tenant_id, source_key, str(table.get("schemaFingerprint") or "")))
                table = _granted_raw_table_projection(table, scope)
                if table is None:
                    continue
            table_by_ref[(tenant_id, source_key)] = table
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


def _field_contract(field: dict[str, Any]) -> tuple[str, str, str, bool, bool, bool]:
    """Return the stable semantic contract for one catalog field.

    A raw-table fingerprint is intentionally stricter than the page consumer:
    adding an unrelated column changes the fingerprint, but it must not break a
    page whose selected fields and relationship keys are unchanged.  Labels,
    physical type and semantic flags remain part of the compatibility gate so a
    renamed/retyped metric can never be silently rebound.
    """

    return (
        str(field.get("fieldNameCn") or field.get("fieldNameEn") or "").strip(),
        str(field.get("type") or "string").strip().casefold(),
        str(field.get("semanticRole") or "").strip().casefold(),
        bool(field.get("isPrimaryKey")),
        bool(field.get("isMetric")),
        bool(field.get("isTime")),
    )


def _fields_remain_compatible(
    saved_fields: Any,
    current_fields: Any,
    required_codes: set[str] | None = None,
) -> bool:
    saved = {
        str(field.get("fieldNameEn") or "").strip(): field
        for field in saved_fields if isinstance(field, dict) and str(field.get("fieldNameEn") or "").strip()
    } if isinstance(saved_fields, list) else {}
    current = {
        str(field.get("fieldNameEn") or "").strip(): field
        for field in current_fields if isinstance(field, dict) and str(field.get("fieldNameEn") or "").strip()
    } if isinstance(current_fields, list) else {}
    required = required_codes if required_codes is not None else set(saved)
    return bool(required) and all(
        code in saved and code in current and _field_contract(saved[code]) == _field_contract(current[code])
        for code in required
    )


def _multi_schema_fingerprint(sources: list[dict[str, Any]]) -> str:
    identity = "|".join(
        f"{source.get('tenantId', '')}:{source.get('sourceKey', '')}:{source.get('schemaFingerprint', '')}"
        for source in sorted(sources, key=lambda item: (str(item.get("tenantId") or ""), str(item.get("sourceKey") or "")))
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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
        if table is None:
            return None
        schema_changed = str(saved_node.get("schemaFingerprint") or "") != str(table.get("schemaFingerprint") or "")
        if schema_changed and not _fields_remain_compatible(saved_node.get("fields"), table.get("fields")):
            return None
        rebound_nodes.append({
            **saved_node,
            "tenantId": tenant_id,
            "institutionName": tenant_labels.get(tenant_id, tenant_id),
            "sourceTableId": str(table.get("id") or ""),
            "sourceTableName": str(table.get("tableNameCn") or table.get("tableNameEn") or ""),
            "schemaFingerprint": str(table.get("schemaFingerprint") or ""),
            "fields": [dict(field) for field in table.get("fields", []) if isinstance(field, dict)],
        })
    tenant_ids = {str(node.get("tenantId") or "") for node in rebound_nodes}
    fields = _relationship_common_fields(rebound_nodes)
    if len(tenant_ids) < 2 or not fields:
        return None
    identity = str(relationship.get("id") or "")
    sources = [
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
    ]
    return {
        "id": identity,
        "name": str(relationship.get("name") or "多机构关联数据"),
        "schemaFingerprint": _multi_schema_fingerprint(sources),
        "fields": fields,
        "sources": sources,
        "relationshipEdges": [dict(edge) for edge in relationship.get("edges", []) if isinstance(edge, dict)],
        "institutionCount": len(tenant_ids),
        "tableCount": len(rebound_nodes),
    }


def _page_data_scope(item: dict[str, Any]) -> str:
    explicit = str(item.get("institutionScope") or "").strip()
    if explicit in {SINGLE_INSTITUTION_PAGE_DATA_SCOPE, MULTI_INSTITUTION_PAGE_DATA_SCOPE, CUSTOMER_SEGMENT_PAGE_DATA_SCOPE}:
        return explicit
    pages = {str(page) for page in item.get("targetPages", []) if str(page)}
    if pages == {"customer_segment_analysis"}:
        return CUSTOMER_SEGMENT_PAGE_DATA_SCOPE
    return MULTI_INSTITUTION_PAGE_DATA_SCOPE if pages == {"dashboard"} else SINGLE_INSTITUTION_PAGE_DATA_SCOPE


def _customer_key_field(table: dict[str, Any]) -> str:
    fields = [field for field in table.get("fields", []) if isinstance(field, dict)]
    primary = [field for field in fields if bool(field.get("isPrimaryKey"))]
    if len(primary) != 1:
        return ""
    field = primary[0]
    code = str(field.get("fieldNameEn") or "").strip()
    label = str(field.get("fieldNameCn") or "").strip()
    customer_field = str(table.get("customerField") or "").strip()
    normalized = "".join(character for character in f"{code}{label}".casefold() if character.isalnum())
    recognized = (
        code == customer_field and bool(customer_field)
        or any(token in normalized for token in ("customerid", "customerno", "custid", "custno", "clientid", "clientno"))
        or any(token in label.casefold().replace(" ", "") for token in ("客户号", "客户编号", "客户id", "客户代码", "客户标识"))
    )
    return code if recognized else ""


def _normalized_tenant_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return normalized if normalized.startswith("tenant:") or normalized == "tenant_demo" else normalize_tenant_id(normalized)


def _current_raw_source_keys(raw_tables: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("sourceKey") or "").strip()
        for item in raw_tables
        if isinstance(item, dict) and str(item.get("sourceKey") or "").strip()
    }


def _local_source_keys(entries: list[dict[str, Any]], tenant_id: str) -> list[str]:
    current = _normalized_tenant_id(tenant_id)
    keys: list[str] = []
    for entry in entries:
        source_key = str(entry.get("sourceKey") or "").strip()
        if not source_key:
            continue
        owner = _normalized_tenant_id(str(entry.get("tenantId") or ""))
        if owner and owner != current:
            continue
        keys.append(source_key)
    return keys


def _source_ref(entry: dict[str, Any]) -> tuple[str, str] | None:
    tenant_id = _normalized_tenant_id(str(entry.get("tenantId") or ""))
    source_key = str(entry.get("sourceKey") or "").strip()
    if not tenant_id or not source_key:
        return None
    return tenant_id, source_key


def _source_refs(entries: list[dict[str, Any]]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for entry in entries:
        ref = _source_ref(entry) if isinstance(entry, dict) else None
        if ref is None:
            return []
        refs.append(ref)
    return refs


def _live_source_refs_for_nodes(handler: Any, context: Any, nodes: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Return currently readable (tenant, sourceKey) pairs for multi-institution overlays."""

    requested = [dict(node) for node in nodes if isinstance(node, dict)]
    if not requested:
        return set()
    try:
        _, table_by_ref = _authorized_raw_table_subset(handler, context, requested)
    except Exception:
        return set()
    return set(table_by_ref)


def _multi_overlay_nodes(page_data: list[Any], relationships: list[Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for item in page_data:
        if not isinstance(item, dict) or _page_data_scope(item) != MULTI_INSTITUTION_PAGE_DATA_SCOPE:
            continue
        nodes.extend(source for source in item.get("institutionSources") or [] if isinstance(source, dict))
    for item in relationships:
        if not isinstance(item, dict) or str(item.get("relationshipScope") or "") != MULTI_INSTITUTION_RELATIONSHIP_SCOPE:
            continue
        nodes.extend(node for node in item.get("nodes") or [] if isinstance(node, dict))
    return nodes


def _page_data_logical_title(value: str) -> str:
    text = re.sub(r"·\s*(单机构数据|页面数据|多机构数据|明细数据)$", "", str(value or "").strip())
    stem = re.sub(r"\.csv$", "", text, flags=re.I)
    without_prefix = re.sub(r"^\d{8}(?:_\d{6})?_", "", stem)
    without_suffix = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", without_prefix)
    title = without_suffix.rsplit("/", 1)[-1]
    return re.sub(r"[\s_\-./]+", "", title).casefold()


def _page_data_logical_title_candidate(value: str) -> bool:
    title = _page_data_logical_title(value)
    return bool(title) and re.fullmatch(r"csv[0-9a-f]{8,}", title) is None


def _unique_raw_table_by_page_data_title(page_data: dict[str, Any], raw_tables: list[dict[str, Any]]) -> dict[str, Any] | None:
    requested = {
        _page_data_logical_title(str(value or ""))
        for value in (page_data.get("sourceTableName"), page_data.get("name"))
        if _page_data_logical_title_candidate(str(value or ""))
    }
    requested.discard("")
    if not requested:
        return None
    matches = [
        item
        for item in raw_tables
        if isinstance(item, dict) and requested.intersection(
            {
                _page_data_logical_title(str(item.get(key) or ""))
                for key in ("tableNameCn", "tableNameEn", "fileName", "relativePath")
            }
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _resolve_page_data_raw_table(
    page_data: dict[str, Any],
    source_tables: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    source_key = str(page_data.get("sourceKey") or "").strip()
    if source_key and source_key in source_tables:
        return source_tables[source_key]
    return _unique_raw_table_by_page_data_title(page_data, list(source_tables.values()))


def _page_data_schema_compatible(page_data: dict[str, Any], table: dict[str, Any]) -> bool:
    requested_schema = str(page_data.get("schemaFingerprint") or "").strip()
    current_schema = str(table.get("schemaFingerprint") or "").strip()
    if not requested_schema or not current_schema or requested_schema == current_schema:
        return True
    current_fields = {
        str(field.get("fieldNameEn") or "").strip()
        for field in (table.get("fields") or [])
        if isinstance(field, dict) and str(field.get("fieldNameEn") or "").strip()
    }
    required = {
        str(field).strip()
        for field in [*(page_data.get("metricFields") or []), *(page_data.get("dimensionFields") or [])]
        if str(field).strip()
    }
    return bool(required) and all(field in current_fields for field in required)


def _page_data_available_for_raw_catalog(
    item: dict[str, Any],
    tenant_id: str,
    source_keys: set[str],
    raw_tables: list[dict[str, Any]] | None = None,
    *,
    live_source_refs: set[tuple[str, str]] | None = None,
) -> bool:
    """Keep page-data configs only when their live raw tables still exist.

    Multi-institution overlays must keep every participating institution's
    source, not just the current tenant's 原始表. Title rematch is only for
    single-institution deliveries whose dated filename rotated.
    """

    if not isinstance(item, dict):
        return False
    if _page_data_scope(item) == MULTI_INSTITUTION_PAGE_DATA_SCOPE:
        sources = [source for source in item.get("institutionSources") or [] if isinstance(source, dict)]
        refs = _source_refs(sources)
        local_keys = _local_source_keys(sources, tenant_id)
        if len({tenant for tenant, _key in refs}) < 2 or not local_keys or any(key not in source_keys for key in local_keys):
            return False
        if live_source_refs is not None:
            return all(ref in live_source_refs for ref in refs)
        return True
    key = str(item.get("sourceKey") or "").strip()
    if key and key in source_keys:
        return True
    if raw_tables:
        return _unique_raw_table_by_page_data_title(item, raw_tables) is not None
    return False


def _table_relationship_available_for_raw_catalog(
    item: dict[str, Any],
    tenant_id: str,
    source_keys: set[str],
    *,
    live_source_refs: set[tuple[str, str]] | None = None,
) -> bool:
    """Keep table relationships only when every referenced raw table still exists."""

    if not isinstance(item, dict):
        return False
    nodes = [node for node in item.get("nodes") or [] if isinstance(node, dict)]
    if not nodes:
        return False
    local_keys = _local_source_keys(nodes, tenant_id)
    if str(item.get("relationshipScope") or "") != MULTI_INSTITUTION_RELATIONSHIP_SCOPE:
        all_keys = [str(node.get("sourceKey") or "").strip() for node in nodes if str(node.get("sourceKey") or "").strip()]
        return bool(all_keys) and all(key in source_keys for key in all_keys)
    refs = _source_refs(nodes)
    if len({tenant for tenant, _key in refs}) < 2 or not local_keys or any(key not in source_keys for key in local_keys):
        return False
    if live_source_refs is not None:
        return all(ref in live_source_refs for ref in refs)
    return True


def _active_tenant_labels(handler: Any) -> dict[str, str]:
    return {
        str(item.get("id") or ""): str(item.get("name") or item.get("id") or "")
        for item in list_active_tenants(handler.services)
        if str(item.get("id") or "")
    }


def _direct_authorized_tenant_labels(handler: Any, context: Any) -> dict[str, str]:
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


def _authorized_tenant_labels(handler: Any, context: Any) -> dict[str, str]:
    direct = _direct_authorized_tenant_labels(handler, context)
    scope_service = getattr(handler.services, "tenant_scope_service", None)
    if scope_service is None:
        return direct
    active = _active_tenant_labels(handler)
    granted = scope_service.granted_source_tenant_ids(
        user_id=context.user_id,
        recipient_tenant_id=context.tenant_id,
        active_tenant_ids=set(active),
        resource_type="raw_table",
        action="read",
    )
    return {**direct, **{tenant_id: active[tenant_id] for tenant_id in sorted(granted) if tenant_id in active}}


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
    authorized = {
        tenant_id: candidates[tenant_id]
        for tenant_id in requested
        if tenant_id in candidates
        and enforcer.enforce(context.user_id, tenant_id, "asset:*", "read")
    }
    scope_service = getattr(handler.services, "tenant_scope_service", None)
    if scope_service is None:
        return authorized
    active = _active_tenant_labels(handler)
    granted = scope_service.granted_source_tenant_ids(
        user_id=context.user_id,
        recipient_tenant_id=context.tenant_id,
        active_tenant_ids=set(active),
        resource_type="raw_table",
        action="read",
    )
    authorized.update({tenant_id: active[tenant_id] for tenant_id in requested & granted if tenant_id in active})
    return authorized


def _granted_raw_table_projection(table: dict[str, Any], scope: Any) -> dict[str, Any] | None:
    if scope is None or not bool(getattr(scope, "allowed", False)):
        return None
    allowed_fields = set(getattr(scope, "field_scope", ()) or ())
    fields = [
        dict(field)
        for field in table.get("fields", [])
        if isinstance(field, dict) and str(field.get("fieldNameEn") or "") in allowed_fields
    ]
    if not fields:
        return None
    primary_keys = [str(field.get("fieldNameEn") or "") for field in fields if field.get("isPrimaryKey")]
    return {
        **table,
        "fields": fields,
        "primaryKey": primary_keys[0] if primary_keys else "",
        "primaryKeys": primary_keys,
        "crossTenantGrantIds": list(getattr(scope, "grant_ids", ()) or ()),
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


def _saved_multi_institution_candidate(
    handler: Any,
    context: Any,
    relationship_id: str,
) -> tuple[dict[str, Any] | None, bool, dict[tuple[str, str], dict[str, Any]]]:
    """Rebind one saved relationship without enumerating unrelated tenants.

    Page reads already carry the stable relationship ID. Rebuilding the full
    relationship picker catalog on every dashboard open adds no authority and
    makes latency grow with every institution visible to the account. The
    returned boolean distinguishes a governed relationship that failed to
    rebind from a legacy lineage ID that still needs the compatibility path.
    """

    data_asset_store = getattr(handler.services, "data_asset_store", None)
    if data_asset_store is None or not relationship_id:
        return None, False, {}
    relationships = data_asset_store.list_published_bundle(context.tenant_id).get("table_relationships", [])
    relationship = next(
        (
            item
            for item in relationships
            if isinstance(item, dict)
            and str(item.get("id") or "") == relationship_id
            and str(item.get("relationshipScope") or "") == MULTI_INSTITUTION_RELATIONSHIP_SCOPE
        ),
        None,
    )
    if relationship is None:
        return None, False, {}
    requested_nodes = [dict(item) for item in relationship.get("nodes", []) if isinstance(item, dict)]
    tenant_labels, table_by_ref = _authorized_raw_table_subset(handler, context, requested_nodes)
    return _candidate_from_relationship_asset(relationship, tenant_labels, table_by_ref), True, table_by_ref


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
        cache_key = (str(context.user_id), str(context.tenant_id))
        now = monotonic()
        cached = _RELATIONSHIP_CATALOG_CACHE.get(cache_key)
        if cached and now - cached[0] < _RELATIONSHIP_CATALOG_CACHE_TTL_SECONDS:
            handler._send_json(cached[1])
            return
        current_catalog = handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id)
        if not getattr(current_catalog, "catalog_ready", True):
            handler._send_json(
                {
                    "tenant_id": context.tenant_id,
                    "status": "loading",
                    "institutions": [],
                    "count": {"institutions": 0, "tables": 0},
                    "source_read_only": True,
                    "message": "当前机构的 Data Crawler 原始数据目录正在准备中，请稍候重试。",
                },
                headers={"Retry-After": "1"},
            )
            return
        tenant_labels, table_by_ref = _authorized_raw_table_catalog(handler, context, wait_for_catalog=False)
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
        payload = {
            "tenant_id": context.tenant_id,
            "status": "ready",
            "institutions": institutions,
            "count": {"institutions": len(institutions), "tables": sum(len(item["tables"]) for item in institutions)},
            "source_read_only": True,
        }
        _RELATIONSHIP_CATALOG_CACHE[cache_key] = (now, payload)
        if len(_RELATIONSHIP_CATALOG_CACHE) > 48:
            expired = [
                key for key, entry in _RELATIONSHIP_CATALOG_CACHE.items()
                if now - entry[0] >= _RELATIONSHIP_CATALOG_CACHE_TTL_SECONDS
            ]
            for key in expired:
                _RELATIONSHIP_CATALOG_CACHE.pop(key, None)
        handler._send_json(payload)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_data_assets_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        scope = str((params.get("scope") or [""])[0]).strip().lower()
        force_refresh = str((params.get("refresh") or [""])[0]).strip().lower() in {"1", "true", "yes"}
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
                for item in (csv_catalog.table_assets(force=True) if force_refresh else csv_catalog.table_assets())
            ]
            topic_tables = _visualization_topic_tables(handler, context.tenant_id)
            published_reader = getattr(handler.services.data_asset_store, "list_published_bundle", None)
            published = published_reader(context.tenant_id) if callable(published_reader) else stored
            multi_page_data = [
                item
                for item in published.get("page_data", [])
                if isinstance(item, dict) and _page_data_scope(item) == MULTI_INSTITUTION_PAGE_DATA_SCOPE
            ]
            raw_source_keys = _current_raw_source_keys(raw_tables)
            live_source_refs = _live_source_refs_for_nodes(
                handler,
                context,
                _multi_overlay_nodes(multi_page_data, []),
            )
            bundle = {key: [] for key in VISUALIZATION_ASSET_KEYS}
            bundle["raw_tables"] = raw_tables
            bundle["topic_tables"] = topic_tables
            bundle["page_data"] = [
                item
                for item in multi_page_data
                if _page_data_available_for_raw_catalog(
                    item,
                    context.tenant_id,
                    raw_source_keys,
                    raw_tables,
                    live_source_refs=live_source_refs,
                )
            ]
            handler._send_json({
                "tenant_id": context.tenant_id,
                **bundle,
                "source_mode": "visualization_catalog",
                "source_read_only": True,
                "count": {key: len(value) for key, value in bundle.items()},
            })
            return
        # The SQL directory is remote while the governed asset bundle is local.
        # Start both read-only branches together; serializing them pushed the
        # data-management page beyond the frontend request timeout in production.
        crawler_catalog_future = _CRAWLER_CATALOG_EXECUTOR.submit(
            _load_crawler_bindings,
            context.tenant_id,
        )
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
        csv_source = csv_catalog.snapshot(force=force_refresh)
        # Raw tables are generated only from the selected institution's
        # Data Crawler directory. Never merge or fall back to another tenant.
        # Do not merge in legacy stored raw-table records: they may describe a
        # deleted upload or retired external source and would make the data
        # management page disagree with the analysis picker.
        references = handler.services.data_asset_store.list_raw_table_external_references(context.tenant_id)
        csv_raw_tables = [
            _raw_table_with_metadata_overlay(
                _raw_table_with_external_reference(item, references.get(str(item.get("sourceKey") or ""))),
                raw_metadata_overlays.get(str(item.get("sourceKey") or "")),
            )
            for item in csv_catalog.table_assets()
        ]
        crawler_sql_catalog: dict[str, Any]
        try:
            crawler_client, binding_payload = crawler_catalog_future.result()
            binding_items = [
                dict(item)
                for item in binding_payload.get("items") or []
                if isinstance(item, dict)
            ]
            bundle["raw_tables"] = _merge_crawler_sql_catalog(
                csv_raw_tables,
                binding_items,
                institution_id=crawler_client.endpoint.institution_id,
                institution_name=crawler_client.endpoint.institution_directory,
            )
            crawler_sql_catalog = {
                "status": "ready",
                "institution_id": crawler_client.endpoint.institution_id,
                "script_count": len({str(item.get("sqlId") or "") for item in binding_items if item.get("sqlId")}),
            }
        except Exception as exc:
            # A transient catalog/API outage must not revoke a previously
            # delivered manifest-backed CSV.  The UI receives an explicit
            # degraded state and keeps only verified data files available.
            bundle["raw_tables"] = [
                {**item, "dataAvailable": True, "deliveryStatus": "catalog_unavailable"}
                for item in csv_raw_tables
            ]
            crawler_sql_catalog = {"status": "unavailable", "error": str(exc)}
        # Page data and table relationships are overlays on the live raw catalog.
        # Keep them as subsets of the current institution's 原始表, never leftover
        # configs whose CSV/upload has already left the directory.
        raw_source_keys = _current_raw_source_keys(bundle["raw_tables"])
        live_source_refs = _live_source_refs_for_nodes(
            handler,
            context,
            _multi_overlay_nodes(bundle.get("page_data", []), bundle.get("table_relationships", [])),
        )
        bundle["page_data"] = [
            item
            for item in bundle.get("page_data", [])
            if _page_data_available_for_raw_catalog(
                item,
                context.tenant_id,
                raw_source_keys,
                bundle["raw_tables"],
                live_source_refs=live_source_refs,
            )
        ]
        bundle["table_relationships"] = [
            item
            for item in bundle.get("table_relationships", [])
            if _table_relationship_available_for_raw_catalog(
                item,
                context.tenant_id,
                raw_source_keys,
                live_source_refs=live_source_refs,
            )
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
                "crawler_sql_catalog": crawler_sql_catalog,
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
        if item_type in {"page_data", "conclusion_rule"} and not handler.services.permission_broker.enforcer.has_super_admin_role(
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
        if item_type == "conclusion_rule":
            item = _bind_conclusion_rule_asset(handler, context, item)
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
    page_consumers = {"dashboard", "weekly_report", "institution_supervision", "customer_segment_analysis"}
    if page_code not in page_consumers:
        raise ValueError("page_data_page_code_invalid")
    bundle = services.data_asset_store.list_bundle(tenant_id)
    catalog = services.data_acquisition_service.csv_source.for_tenant(tenant_id)
    source_tables = {
        str(table.get("sourceKey") or ""): table
        for table in _csv_table_assets(catalog, wait_for_catalog=True)
        if str(table.get("sourceKey") or "")
    }
    raw_source_keys = set(source_tables)
    live_source_refs = _live_source_refs_for_nodes(
        SimpleNamespace(services=services),
        SimpleNamespace(tenant_id=tenant_id, user_id=user_id),
        _multi_overlay_nodes(bundle.get("page_data", []), []),
    )
    assets = [
        item
        for item in bundle.get("page_data", [])
        if isinstance(item, dict)
        and _page_data_belongs_to_page(item, page_code)
        and _page_data_available_for_raw_catalog(
            item,
            tenant_id,
            raw_source_keys,
            list(source_tables.values()),
            live_source_refs=live_source_refs,
        )
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
        include_newly_assigned=True,
    )
    workspace_key = (
        tenant_id,
        user_id,
        page_code,
        str((state.get("customerSegmentList") or {}).get("contentHash") or "") if isinstance(state.get("customerSegmentList"), dict) else "",
        tuple(layout),
        json.dumps(state.get("pageDataCards") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        json.dumps(state.get("pageDataPublicFilters") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        str(state.get("pageReportStyleId") or "balanced-canvas"),
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
        tuple(
            sorted(
                (
                    str(table.get("sourceKey") or ""),
                    str(table.get("contentHash") or ""),
                    str(table.get("schemaFingerprint") or ""),
                )
                for table in source_tables.values()
            )
        ),
    )
    cached_workspace = _PAGE_DATA_WORKSPACE_CACHE.get(workspace_key)
    if cached_workspace and cached_workspace[0] > monotonic():
        return deepcopy(cached_workspace[1])
    rows: dict[str, Any] = {}
    row_errors: dict[str, str] = {}
    row_source_tables = source_tables if page_code != "dashboard" else None
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
                source_tables=row_source_tables,
            )
        except Exception as exc:
            row_errors[asset_id] = str(exc) or "page_data_rows_unavailable"
    payload = {
        "tenant_id": tenant_id,
        "page_code": page_code,
        "assets": assets,
        "layout": layout,
        "cards": list(state.get("pageDataCards") or []),
        "public_filters": list(state.get("pageDataPublicFilters") or []),
        "page_style_id": str(state.get("pageReportStyleId") or "balanced-canvas"),
        "notes": list(state.get("pageDataNotes") or []),
        "rows": rows,
        "row_errors": row_errors,
        "raw_source_keys": sorted(raw_source_keys),
    }
    complete = bool(assets) and bool(layout) and all(asset_id in rows for asset_id in layout)
    if complete and page_code != "customer_segment_analysis":
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
    source_tables: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve one page-data projection through its governed source chain.

    Page modules retain their explicit target-page contract. Analytical
    consumers may reuse only multi-institution page data; they never receive a
    cross-institution raw-table catalog. Every read revalidates account scope,
    relationship identity, source schemas and institution provenance.
    """

    page_consumers = {"dashboard", "weekly_report", "institution_supervision", "customer_segment_analysis"}
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
        expected_scope = (
            MULTI_INSTITUTION_PAGE_DATA_SCOPE if consumer == "dashboard"
            else CUSTOMER_SEGMENT_PAGE_DATA_SCOPE if consumer == "customer_segment_analysis"
            else SINGLE_INSTITUTION_PAGE_DATA_SCOPE
        )
        if scope != expected_scope:
            raise PermissionError("page_data_scope_unavailable_for_page")
    elif scope != MULTI_INSTITUTION_PAGE_DATA_SCOPE:
        raise PermissionError("page_data_scope_unavailable_for_analysis")

    dimensions = [str(field) for field in page_data.get("dimensionFields", [])]
    metrics = [str(field) for field in page_data.get("metricFields", [])]
    selected_fields = list(dict.fromkeys([*dimensions, *metrics]))
    if scope == MULTI_INSTITUTION_PAGE_DATA_SCOPE:
        sources = _multi_page_data_source_tables(handler, context, page_data)
        effective_schema_fingerprint = _multi_schema_fingerprint([
            {
                **source,
                "schemaFingerprint": str(source_table.get("schemaFingerprint") or ""),
            }
            for source, source_table in sources
        ])
        data_fields = [field for field in selected_fields if field != MULTI_INSTITUTION_DIMENSION]
        if not sources or not data_fields or MULTI_INSTITUTION_DIMENSION not in dimensions:
            raise PermissionError("page_data_selected_field_unavailable")
        cache_key = (
            "multi",
            tenant_id,
            page_data_id,
            consumer,
            effective_schema_fingerprint,
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
        table = _page_data_source_table(handler, tenant_id, page_data, source_tables=source_tables)
        effective_schema_fingerprint = str(table.get("schemaFingerprint") or "")
        available = {str(field.get("fieldNameEn") or "") for field in table.get("fields", [])}
        if not selected_fields or any(field not in available for field in selected_fields):
            raise PermissionError("page_data_selected_field_unavailable")
        customer_list_metadata: dict[str, Any] | None = None
        customer_ids: list[str] | None = None
        if scope == CUSTOMER_SEGMENT_PAGE_DATA_SCOPE:
            customer_key = _customer_key_field(table)
            if not customer_key or customer_key != str(page_data.get("customerKeyField") or ""):
                raise PermissionError("customer_segment_page_data_customer_key_changed")
            customer_list_metadata, customer_ids = customer_ids_for_user(
                services,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        cache_key = (
            "single",
            tenant_id,
            page_data_id,
            consumer,
            str(table.get("contentHash") or ""),
            str(table.get("schemaFingerprint") or ""),
            tuple(selected_fields),
            str((customer_list_metadata or {}).get("contentHash") or ""),
        )
        cached = _page_data_projection_cache_get(cache_key)
        if cached is not None:
            return cached
        tenant_source = services.data_acquisition_service.csv_source.for_tenant(tenant_id)
        if customer_ids is None:
            _, source_rows = tenant_source.read_rows(
                str(table.get("relativePath") or ""),
                max_rows=500,
            )
        else:
            _, source_rows = tenant_source.read_rows_matching_values(
                str(table.get("relativePath") or ""),
                key_field=str(page_data.get("customerKeyField") or ""),
                values=customer_ids,
                max_matches=MAX_CUSTOMER_IDS,
            )
        labels = {
            str(field.get("fieldNameEn") or ""): str(field.get("fieldNameCn") or field.get("fieldNameEn") or "")
            for field in table.get("fields", [])
            if str(field.get("fieldNameEn") or "") in selected_fields
        }
        if customer_ids is None:
            rows = _project_page_data_rows(table, source_rows, selected_fields)
        else:
            customer_key = str(page_data.get("customerKeyField") or "")
            source_by_customer = {
                str(row.get(customer_key) or "").strip(): row
                for row in source_rows
                if str(row.get(customer_key) or "").strip()
            }
            matched_customer_count = sum(1 for customer_id in customer_ids if customer_id in source_by_customer)
            rows = [
                {
                    field: (
                        customer_id if field == customer_key
                        else str(source_by_customer.get(customer_id, {}).get(field) or "")
                    )
                    for field in selected_fields
                }
                for customer_id in customer_ids
            ][:MAX_CUSTOMER_IDS]

    payload = {
        "tenant_id": tenant_id,
        "page_code": consumer,
        "page_data_id": page_data_id,
        "source_key": str(page_data.get("sourceKey") or ""),
        "relationship_group_id": str(page_data.get("relationshipGroupId") or ""),
        "institution_scope": scope,
        "schema_fingerprint": effective_schema_fingerprint,
        "fields": selected_fields,
        "field_labels": labels,
        "row_count": len(rows),
        "rows": rows,
        "bounded": True,
    }
    if scope == CUSTOMER_SEGMENT_PAGE_DATA_SCOPE:
        payload["customer_segment"] = {
            "customer_count": int((customer_list_metadata or {}).get("customerCount") or 0),
            "matched_count": matched_customer_count,
            "content_hash": str((customer_list_metadata or {}).get("contentHash") or ""),
        }
    if scope != CUSTOMER_SEGMENT_PAGE_DATA_SCOPE:
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
    if page_code == "customer_segment_analysis":
        return scope == CUSTOMER_SEGMENT_PAGE_DATA_SCOPE and "customer_segment_analysis" in targets
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


def _bind_conclusion_rule_asset(handler: Any, context: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Bind a conclusion rule to one current governed dataset and Skill.

    The browser submits identifiers only. Names, fields, schema and Skill
    existence are read back from the tenant catalogs so a stale or forged rule
    cannot enter model context.
    """

    bundle = handler.services.data_asset_store.list_published_bundle(context.tenant_id)
    datasets = [
        *[dict(table, datasetKind="raw_table") for table in _raw_tables_for_tenant(handler, context.tenant_id, wait_for_catalog=True)],
        *[dict(table, datasetKind="topic_table") for table in bundle.get("topic_tables", []) if isinstance(table, dict)],
        *[dict(table, datasetKind="page_data") for table in bundle.get("page_data", []) if isinstance(table, dict)],
    ]
    requested_id = str(item.get("datasetId") or "").strip()
    requested_kind = str(item.get("datasetKind") or "").strip()
    dataset = next((candidate for candidate in datasets if str(candidate.get("datasetKind") or "") == requested_kind and requested_id in {
        str(candidate.get("id") or "").strip(),
        str(candidate.get("sourceKey") or "").strip(),
        str(candidate.get("datasetId") or "").strip(),
        str(candidate.get("code") or "").strip(),
    }), None)
    if dataset is None:
        raise PermissionError("conclusion_rule_dataset_unavailable")
    fields = dataset.get("sourceFields") if isinstance(dataset.get("sourceFields"), list) else dataset.get("fields")
    field_codes = {
        str(field.get("fieldNameEn") or field.get("code") or "").strip()
        for field in (fields or [])
        if isinstance(field, dict)
    }
    metric_rules = [dict(rule) for rule in item.get("metricRules", []) if isinstance(rule, dict)]
    if not metric_rules or any(str(rule.get("metricField") or "").strip() not in field_codes for rule in metric_rules):
        raise ValueError("conclusion_rule_metric_field_unavailable")
    skill_id = str(item.get("skillId") or "").strip()
    skill = next((candidate for candidate in bundle.get("analysis_skills", []) if isinstance(candidate, dict)
                  and str(candidate.get("id") or "") == skill_id and candidate.get("enabled") is not False), None)
    if skill is None:
        raise PermissionError("conclusion_rule_skill_unavailable")
    aliases = list(dict.fromkeys(filter(None, (
        str(dataset.get("id") or "").strip(), str(dataset.get("sourceKey") or "").strip(),
        str(dataset.get("datasetId") or "").strip(), str(dataset.get("code") or "").strip(),
    ))))
    name = str(dataset.get("name") or dataset.get("tableNameCn") or dataset.get("sourceTableName") or dataset.get("tableNameEn") or requested_id)
    return {
        **item,
        "purpose": "conclusion_generation",
        "datasetId": aliases[0],
        "datasetRefIds": aliases,
        "datasetName": name,
        "datasetKind": str(dataset.get("datasetKind") or "raw_table"),
        "datasetSchemaFingerprint": str(dataset.get("schemaFingerprint") or ""),
        "skillId": skill_id,
        "skillName": str(skill.get("name") or skill_id),
        "metricRules": metric_rules,
    }


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
            for candidate in _raw_tables_for_tenant(handler, context.tenant_id, wait_for_catalog=True)
            if str(candidate.get("sourceKey") or "") == source_key
        ),
        None,
    )
    if table is None:
        raise PermissionError("page_data_source_unavailable")
    if scope == CUSTOMER_SEGMENT_PAGE_DATA_SCOPE:
        customer_key = _customer_key_field(table)
        if not customer_key:
            raise PermissionError("customer_segment_detail_table_required")
    else:
        customer_key = ""
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
        "institutionScope": scope,
        "sourceTableId": str(table.get("id") or ""),
        "sourceTableName": str(table.get("tableNameCn") or table.get("tableNameEn") or ""),
        "sourceRelativePath": str(table.get("relativePath") or ""),
        "sourceFields": [dict(field) for field in table.get("fields", [])],
        "schemaFingerprint": str(table.get("schemaFingerprint") or ""),
        "contentHash": str(table.get("contentHash") or ""),
        "targetPages": ["customer_segment_analysis"] if scope == CUSTOMER_SEGMENT_PAGE_DATA_SCOPE else item.get("targetPages"),
        "customerKeyField": customer_key,
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
    candidate, saved_relationship_found, saved_tables = _saved_multi_institution_candidate(
        handler,
        context,
        relationship_id,
    )
    if saved_relationship_found and candidate is None:
        raise PermissionError("multi_institution_page_data_source_schema_changed")
    if candidate is None:
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
    if candidate is None:
        raise PermissionError("multi_institution_page_data_source_schema_changed")
    sources = candidate.get("sources")
    if not isinstance(sources, list) or len(sources) < 2:
        raise PermissionError("multi_institution_page_data_sources_unavailable")
    saved_refs = {
        (_normalized_tenant_id(str(source.get("tenantId") or "")), str(source.get("sourceKey") or ""))
        for source in page_data.get("institutionSources", [])
        if isinstance(source, dict)
    }
    current_refs = {
        (_normalized_tenant_id(str(source.get("tenantId") or "")), str(source.get("sourceKey") or ""))
        for source in sources if isinstance(source, dict)
    }
    selected_fields = {
        str(field or "").strip()
        for field in [*page_data.get("dimensionFields", []), *page_data.get("metricFields", [])]
        if str(field or "").strip() and str(field or "").strip() != MULTI_INSTITUTION_DIMENSION
    }
    exact_schema = str(candidate.get("schemaFingerprint") or "") == str(page_data.get("schemaFingerprint") or "")
    compatible_refresh = (
        saved_refs == current_refs
        and _fields_remain_compatible(page_data.get("sourceFields"), candidate.get("fields"), selected_fields)
    )
    if not exact_schema and not compatible_refresh:
        raise PermissionError("multi_institution_page_data_source_schema_changed")
    resolved: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_refs: set[tuple[str, str]] = set()
    direct_tenant_ids = set(_direct_authorized_tenant_labels(handler, context))
    active_tenant_ids = set(_active_tenant_labels(handler))
    for raw_source in sources:
        if not isinstance(raw_source, dict):
            raise PermissionError("multi_institution_page_data_sources_unavailable")
        tenant_id = _normalized_tenant_id(str(raw_source.get("tenantId") or ""))
        source_key = str(raw_source.get("sourceKey") or "").strip()
        if not tenant_id or not source_key or (tenant_id, source_key) in seen_refs:
            raise PermissionError("multi_institution_page_data_sources_unavailable")
        table = saved_tables.get((tenant_id, source_key)) if saved_relationship_found else next(
            (
                candidate
                for candidate in handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id).table_assets()
                if str(candidate.get("sourceKey") or "") == source_key
            ),
            None,
        )
        if table is None or str(table.get("schemaFingerprint") or "") != str(raw_source.get("schemaFingerprint") or ""):
            raise PermissionError("multi_institution_page_data_source_schema_changed")
        scope_service = getattr(handler.services, "tenant_scope_service", None)
        if scope_service is not None:
            access = scope_service.resolve_resource_access(
                user_id=context.user_id,
                recipient_tenant_id=context.tenant_id,
                source_tenant_id=tenant_id,
                active_tenant_ids=active_tenant_ids,
                direct_source_tenant_ids=direct_tenant_ids,
                resource_type="raw_table",
                resource_key=source_key,
                action="read",
                schema_fingerprint=str(table.get("schemaFingerprint") or ""),
                requested_fields=selected_fields,
            )
            if not access.allowed:
                raise PermissionError("multi_institution_page_data_sources_unavailable")
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


def _page_data_source_table(
    handler: Any,
    tenant_id: str,
    page_data: dict[str, Any],
    *,
    source_tables: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if source_tables is None:
        catalog = handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id)
        source_tables = {
            str(item.get("sourceKey") or ""): item
            for item in _csv_table_assets(catalog, wait_for_catalog=True)
            if str(item.get("sourceKey") or "")
        }
    table = _resolve_page_data_raw_table(page_data, source_tables)
    if table is None:
        raise PermissionError("page_data_source_unavailable")
    if not _page_data_schema_compatible(page_data, table):
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
    execution_mode = str(semantic.get("execution_mode") or "").strip().lower()
    if item_type == "topic_table" and execution_mode in {"uploaded_file", "uploaded_document_summary"}:
        raise ValueError("topic_table_uploaded_source_not_persisted")
    executed_sql_text = str(evidence.get("executed_sql") or evidence.get("execution_statement") or item.get("sql") or "").strip()
    has_persistable_select = False
    try:
        if executed_sql_text:
            _detail_query_from_execution(executed_sql_text)
            has_persistable_select = True
    except ValueError:
        has_persistable_select = False
    evidence_ready = bool(
        task.get("status") in {"completed", "review_required"}
        and execution_mode not in {"", "mock", "demo", "fallback", "unverified"}
        and evidence.get("evidence_id")
        and isinstance(evidence.get("source_snapshot"), dict)
        and evidence.get("source_snapshot")
        and (evidence.get("sql_executed") is True or has_persistable_select)
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
        bound["sql"] = _detail_query_from_execution(executed_sql_text)
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
        if item_type in {"page_data", "conclusion_rule"} and not handler.services.permission_broker.enforcer.has_super_admin_role(
            context.user_id, context.tenant_id
        ):
            raise PermissionError(f"global_super_admin_required_for_{item_type}")
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
