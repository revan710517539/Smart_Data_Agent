from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


ANALYSIS_RESOLUTION_KEY = "analysisResolution"


@dataclass(frozen=True)
class AnalysisTableResolution:
    table: dict[str, Any]
    strategy: str
    version_changed: bool


class AnalysisContractError(ValueError):
    """A bounded, user-actionable analysis contract failure.

    The ordinary ``ValueError`` boundary intentionally loses field and stage
    context.  This exception keeps only schema/asset metadata; source rows and
    credentials are never included.
    """

    def __init__(
        self,
        code: str,
        stage: str,
        *,
        missing_fields: Iterable[dict[str, Any] | str] = (),
        required_fields: Iterable[str] = (),
        available_fields: Iterable[str] = (),
        field_differences: Iterable[dict[str, Any]] = (),
        asset: dict[str, Any] | None = None,
        retryable: bool = False,
        user_action: str = "",
    ) -> None:
        super().__init__(code)
        self.code = str(code)
        self.stage = str(stage)
        self.missing_fields = tuple(_public_missing_field(item) for item in missing_fields)
        self.required_fields = tuple(dict.fromkeys(str(item) for item in required_fields if str(item)))
        self.available_fields = tuple(sorted(dict.fromkeys(str(item) for item in available_fields if str(item)))[:120])
        self.field_differences = tuple(_public_field_difference(item) for item in field_differences)
        self.asset = _bounded_asset_snapshot(asset or {})
        self.retryable = bool(retryable)
        self.user_action = str(user_action or "")[:300]

    def public_details(self, *, request_id: str = "") -> dict[str, Any]:
        return {
            "error": self.code,
            "stage": self.stage,
            "missingFields": [dict(item) for item in self.missing_fields],
            "requiredFields": list(self.required_fields),
            "availableFields": list(self.available_fields),
            "fieldDifferences": [dict(item) for item in self.field_differences],
            "asset": dict(self.asset),
            "retryable": self.retryable,
            "userAction": self.user_action,
            "requestId": str(request_id or ""),
        }

    def public_message(self) -> str:
        names = [str(item.get("displayName") or item.get("canonicalId") or "") for item in self.missing_fields]
        names = [name for name in names if name]
        field_text = "、".join(f"“{name}”" for name in names[:8])
        if self.code == "analysis_table_schema_changed":
            suffix = f"，涉及字段{field_text}" if field_text else ""
            return f"所选数据表的字段结构已经变化{suffix}。请确认字段差异后重新生成分析方案。"
        if self.code == "analysis_table_reference_invalid":
            return "所选数据表引用不完整，请刷新站内数据后重新选择。"
        if self.code == "analysis_table_version_outdated":
            return "所选数据表在任务执行期间发生变化，本次任务已停止以避免混用不同版本。请刷新后重新提交。"
        if self.code in {"analysis_table_unavailable", "analysis_table_retired", "analysis_table_tenant_mismatch"}:
            return "所选数据表当前不可用，请刷新站内数据并确认当前机构后重新选择。"
        if self.code == "analysis_required_field_missing":
            stage_labels = {
                "plan_validation": "分析方案",
                "query_output": "查询结果",
                "data_processing_output": "数据处理结果",
            }
            stage_label = stage_labels.get(self.stage, "分析结果")
            suffix = f"缺少字段{field_text}" if field_text else "缺少必要字段"
            action = self.user_action or "请重新生成分析方案后重试。"
            return f"{stage_label}{suffix}。{action}"
        return "分析数据契约校验失败，请刷新数据表并重新生成分析方案。"


def resolve_analysis_table_reference(
    requested: dict[str, Any],
    catalog: list[dict[str, Any]],
    *,
    tenant_id: str = "",
) -> AnalysisTableResolution:
    """Resolve one client selection to one current, tenant-scoped table.

    Stable identity and exact content evidence are authoritative.  A unique
    title is never enough to authorize a different delivery.
    """

    requested_tenant = str(requested.get("tenantId") or requested.get("tenant_id") or "").strip()
    if requested_tenant and tenant_id and requested_tenant != tenant_id:
        raise AnalysisContractError("analysis_table_tenant_mismatch", "asset_resolution")
    if not _has_reference_identity(requested):
        raise AnalysisContractError("analysis_table_reference_invalid", "asset_resolution")

    all_candidates = [dict(item) for item in catalog if isinstance(item, dict) and _same_kind(requested, item)]
    candidates = [item for item in all_candidates if _catalog_tenant_matches(item, tenant_id)]
    foreign_candidates = [item for item in all_candidates if not _catalog_tenant_matches(item, tenant_id)]
    if not candidates and _resolve_table_match(requested, foreign_candidates)[0] is not None:
        raise AnalysisContractError("analysis_table_tenant_mismatch", "asset_resolution")
    active_candidates = [item for item in candidates if _table_lifecycle(item) == "active"]
    retired_candidates = [item for item in candidates if _table_lifecycle(item) != "active"]
    match, strategy = _resolve_table_match(requested, active_candidates)
    if match is None:
        retired, _retired_strategy = _resolve_table_match(requested, retired_candidates)
        if retired is not None:
            raise AnalysisContractError(
                "analysis_table_retired",
                "asset_resolution",
                asset=resolved_asset_snapshot(retired, tenant_id=tenant_id),
                user_action="请刷新站内数据并重新选择仍在使用的数据表。",
            )
        raise AnalysisContractError("analysis_table_unavailable", "asset_resolution")

    field_differences = _schema_field_differences(requested, match)
    if field_differences:
        contract = field_contract_from_table(requested)
        by_id = {str(item.get("canonicalId") or ""): item for item in contract}
        incompatible_fields = list(dict.fromkeys(str(item.get("canonicalId") or "") for item in field_differences))
        raise AnalysisContractError(
            "analysis_table_schema_changed",
            "asset_resolution",
            missing_fields=[
                by_id.get(field, {"canonicalId": field, "displayName": "字段结构" if field == "__schema_contract__" else field})
                for field in incompatible_fields
            ],
            required_fields=sorted(_table_field_ids(requested)),
            available_fields=sorted(_table_field_ids(match)),
            field_differences=field_differences,
            asset=resolved_asset_snapshot(match, tenant_id=tenant_id),
            user_action="请确认字段差异后重新选择数据表。",
        )

    resolution = resolved_asset_snapshot(match, tenant_id=tenant_id)
    requested_version = _asset_version(requested)
    resolved = {
        **match,
        ANALYSIS_RESOLUTION_KEY: {
            **resolution,
            "matchStrategy": strategy,
            "requestedAssetVersion": requested_version,
            "versionChanged": bool(requested_version and requested_version != resolution["assetVersion"]),
            "serverAuthorized": True,
        },
    }
    return AnalysisTableResolution(
        table=resolved,
        strategy=strategy,
        version_changed=bool(requested_version and requested_version != resolution["assetVersion"]),
    )


def resolved_asset_snapshot(table: dict[str, Any], *, tenant_id: str = "") -> dict[str, Any]:
    kind = _table_kind(table)
    content_hash = str(table.get("contentHash") or table.get("content_hash") or "").strip()
    source_key = str(table.get("sourceKey") or table.get("source_key") or "").strip()
    table_id = str(table.get("id") or table.get("code") or table.get("tableNameEn") or "").strip()
    explicit_asset_id = str(table.get("assetId") or table.get("asset_id") or "").strip()
    if explicit_asset_id:
        stable_id = explicit_asset_id
    elif kind == "uploaded_file":
        stable_id = f"upload:{content_hash or table_id}"
    elif kind == "raw" and source_key:
        stable_id = f"raw:{source_key}"
    else:
        stable_id = f"{kind}:{table_id}"
    return {
        "tenantId": str(tenant_id or ""),
        "assetId": stable_id,
        "assetVersion": _asset_version(table),
        "tableId": table_id,
        "sourceKey": source_key,
        "relativePath": str(table.get("relativePath") or table.get("relative_path") or "").strip(),
        "contentHash": content_hash,
        "schemaFingerprint": str(table.get("schemaFingerprint") or table.get("schema_fingerprint") or "").strip(),
        "sourceType": "upload" if kind == "uploaded_file" else "station",
    }


def field_contract_from_table(table: dict[str, Any]) -> list[dict[str, Any]]:
    contract: list[dict[str, Any]] = []
    for field in table.get("fields") or []:
        if not isinstance(field, dict):
            continue
        canonical = str(field.get("fieldNameEn") or field.get("canonicalId") or field.get("code") or "").strip()
        if not canonical:
            continue
        physical = str(field.get("physicalName") or field.get("fieldNameCn") or canonical).strip() or canonical
        display = str(field.get("displayName") or field.get("fieldNameCn") or canonical).strip() or canonical
        role = "metric" if field.get("isMetric") else "date" if field.get("isTime") else "dimension"
        contract.append({
            "canonicalId": canonical,
            "physicalName": physical,
            "displayName": display,
            "queryAlias": canonical,
            "dataType": str(field.get("type") or "string"),
            "role": str(field.get("semanticRole") or role),
        })
    existing = {str(item["canonicalId"]) for item in contract}
    labels = table.get("fieldLabels") if isinstance(table.get("fieldLabels"), dict) else {}
    metadata = table.get("fieldMetadata") if isinstance(table.get("fieldMetadata"), dict) else {}
    metric_codes = {str(item) for item in table.get("metricCodes") or [] if str(item)}
    for canonical in sorted(_table_field_ids(table) - existing):
        details = metadata.get(canonical) if isinstance(metadata.get(canonical), dict) else {}
        contract.append({
            "canonicalId": canonical,
            "physicalName": str(details.get("physicalName") or labels.get(canonical) or canonical),
            "displayName": str(details.get("displayName") or labels.get(canonical) or canonical),
            "queryAlias": canonical,
            "dataType": str(details.get("type") or "unknown"),
            "role": str(details.get("semanticRole") or ("metric" if canonical in metric_codes else "dimension")),
        })
    return contract


def bind_plan_field_contract(plan: dict[str, Any], table: dict[str, Any] | None = None) -> dict[str, Any]:
    bound = dict(plan)
    contract = field_contract_from_table(table or {})
    by_id = {str(item["canonicalId"]): item for item in contract}
    required = list(dict.fromkeys([
        *[str(item) for item in bound.get("dimensions") or [] if str(item)],
        *[str(item) for item in bound.get("metrics") or [] if str(item)],
    ]))
    for field in required:
        if field == "row_count" or field in by_id:
            continue
        by_id[field] = {
            "canonicalId": field,
            "physicalName": field,
            "displayName": _plan_field_label(bound, field),
            "queryAlias": field,
            "dataType": "integer" if field == "row_count" else "unknown",
            "role": "metric" if field in set(bound.get("metrics") or []) else "dimension",
        }
    if table:
        available = _table_field_ids(table) | {"row_count"}
        missing = [field for field in required if field not in available]
        if missing:
            raise AnalysisContractError(
                "analysis_required_field_missing",
                "plan_validation",
                missing_fields=[by_id[field] for field in missing],
                required_fields=required,
                available_fields=sorted(available),
                asset=table.get(ANALYSIS_RESOLUTION_KEY) if isinstance(table, dict) else {},
                user_action="请按当前数据表字段重新生成分析方案。",
            )
        resolution = table.get(ANALYSIS_RESOLUTION_KEY)
        if isinstance(resolution, dict):
            bound["asset_snapshot"] = _bounded_asset_snapshot(resolution)
    bound["field_contract"] = [by_id[field] for field in required if field in by_id]
    return bound


def normalize_query_output_contract(plan: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(output)
    rows = [dict(row) for row in output.get("data") or [] if isinstance(row, dict)]
    semantic = dict(output.get("semantic_info") or {}) if isinstance(output.get("semantic_info"), dict) else {}
    mapping = dict(semantic.get("schema_mapping") or {}) if isinstance(semantic.get("schema_mapping"), dict) else {}
    contract = [dict(item) for item in plan.get("field_contract") or [] if isinstance(item, dict)]
    by_id = {str(item.get("canonicalId") or ""): item for item in contract}
    required = list(dict.fromkeys([
        *[str(item) for item in plan.get("dimensions") or [] if str(item)],
        *[str(item) for item in plan.get("metrics") or [] if str(item)],
    ]))
    aliases = _explicit_field_aliases(mapping, contract)
    declared_output = mapping.get("output_fields") or mapping.get("outputFields") or []
    provider_output_fields = sorted({
        str(item)
        for item in declared_output
        if isinstance(declared_output, (list, tuple, set)) and str(item)
    })
    normalized_aliases: dict[str, str] = {}
    for canonical in required:
        alias = aliases.get(canonical, "")
        if not alias or alias == canonical:
            continue
        if rows and all(canonical not in row and alias in row for row in rows):
            for row in rows:
                row[canonical] = row[alias]
            normalized_aliases[canonical] = alias
    row_output_fields = sorted({str(key) for row in rows for key in row if not str(key).startswith("_")})
    authoritative_output_fields = row_output_fields if rows else provider_output_fields
    normalized_output_fields = set(authoritative_output_fields)
    for canonical, alias in aliases.items():
        if canonical in authoritative_output_fields or alias in authoritative_output_fields:
            normalized_output_fields.add(canonical)
    available = sorted(normalized_output_fields)
    missing = [
        field
        for field in required
        if (
            any(field not in row for row in rows)
            if rows
            else field not in normalized_output_fields
        )
    ]
    if missing:
        raise AnalysisContractError(
            "analysis_required_field_missing",
            "query_output",
            missing_fields=[by_id.get(field, field) for field in missing],
            required_fields=required,
            available_fields=available,
            asset=(semantic.get("source_snapshot") if isinstance(semantic.get("source_snapshot"), dict) else {}),
            user_action="查询没有返回这些字段，系统已停止数据处理；请重新生成查询方案。",
        )
    mapping.update({
        "field_contract": contract,
        "output_fields": available,
        "provider_output_fields": provider_output_fields,
        "normalized_aliases": normalized_aliases,
    })
    semantic["schema_mapping"] = mapping
    normalized["semantic_info"] = semantic
    normalized["data"] = rows
    return normalized


def processing_output_error(
    plan: dict[str, Any],
    processed_rows: list[dict[str, Any]],
    missing: Iterable[str],
) -> AnalysisContractError:
    contract = [dict(item) for item in plan.get("field_contract") or [] if isinstance(item, dict)]
    by_id = {str(item.get("canonicalId") or ""): item for item in contract}
    available = sorted({str(key) for row in processed_rows for key in row if not str(key).startswith("_")})
    required = [
        *[str(item) for item in plan.get("dimensions") or [] if str(item)],
        *[str(item) for item in plan.get("metrics") or [] if str(item)],
    ]
    return AnalysisContractError(
        "analysis_required_field_missing",
        "data_processing_output",
        missing_fields=[by_id.get(field, field) for field in missing],
        required_fields=required,
        available_fields=available,
        asset=plan.get("asset_snapshot") if isinstance(plan.get("asset_snapshot"), dict) else {},
        user_action="数据处理脚本删除了必要字段，系统无法安全生成结果。",
    )


def _explicit_field_aliases(mapping: dict[str, Any], contract: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    raw = mapping.get("field_aliases") or mapping.get("fieldAliases") or {}
    if isinstance(raw, dict):
        aliases.update({str(key): str(value) for key, value in raw.items() if str(key) and str(value)})
    for item in contract:
        canonical = str(item.get("canonicalId") or "")
        alias = str(item.get("queryAlias") or "")
        if canonical and alias:
            aliases.setdefault(canonical, alias)
    return aliases


def _public_missing_field(value: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, dict):
        canonical = str(value.get("canonicalId") or value.get("canonical_id") or value.get("expectedKey") or "")
        return {
            "canonicalId": canonical,
            "displayName": str(value.get("displayName") or value.get("display_name") or canonical),
            "expectedKey": str(value.get("queryAlias") or value.get("expectedKey") or canonical),
        }
    text = str(value)
    return {"canonicalId": text, "displayName": text, "expectedKey": text}


def _public_field_difference(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonicalId": str(value.get("canonicalId") or "")[:190],
        "displayName": str(value.get("displayName") or value.get("canonicalId") or "")[:190],
        "change": str(value.get("change") or "changed")[:80],
        "previous": str(value.get("previous") or "")[:190],
        "current": str(value.get("current") or "")[:190],
    }


def _bounded_asset_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "assetId": ("assetId", "asset_id", "table_id", "id"),
        "assetVersion": ("assetVersion", "asset_version", "version"),
        "schemaFingerprint": ("schemaFingerprint", "schema_fingerprint"),
        "contentHash": ("contentHash", "content_hash"),
        "sourceKey": ("sourceKey", "source_key"),
        "relativePath": ("relativePath", "relative_path"),
        "sourceType": ("sourceType", "source_type"),
    }
    result: dict[str, Any] = {}
    for target, keys in aliases.items():
        selected = next((value.get(key) for key in keys if value.get(key) not in (None, "")), None)
        if selected is not None:
            result[target] = str(selected)[:500]
    return result


def _plan_field_label(plan: dict[str, Any], field: str) -> str:
    for definition in plan.get("metric_definitions") or []:
        if isinstance(definition, dict) and str(definition.get("metric_code") or "") == field:
            return str(definition.get("metric_name") or field)
    return field


def _has_reference_identity(table: dict[str, Any]) -> bool:
    return any(
        str(table.get(key) or "").strip()
        for key in ("assetId", "asset_id", "id", "code", "tableNameEn", "sourceKey", "relativePath", "contentHash")
    )


def _table_kind(table: dict[str, Any]) -> str:
    explicit = str(table.get("kind") or table.get("tableType") or "").strip().lower()
    path = str(table.get("relativePath") or "")
    if explicit in {"uploaded_file", "upload"} or path.startswith("upload://"):
        return "uploaded_file"
    if explicit in {"page_data", "topic", "raw"}:
        return explicit
    if table.get("datasetId"):
        return "topic"
    if table.get("tableNameEn") or path:
        return "raw"
    return explicit or "asset"


def _same_kind(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_kind = _table_kind(left)
    right_kind = _table_kind(right)
    return left_kind == right_kind or left_kind == "asset" or right_kind == "asset"


def _same_value(left: dict[str, Any], right: dict[str, Any], key: str) -> bool:
    left_value = str(left.get(key) or "").strip()
    right_value = str(right.get(key) or "").strip()
    return bool(left_value and right_value and left_value == right_value)


def _matches_code(requested: dict[str, Any], item: dict[str, Any]) -> bool:
    requested_code = str(requested.get("code") or requested.get("tableNameEn") or "").strip()
    return bool(requested_code and requested_code in {
        str(item.get("code") or "").strip(),
        str(item.get("tableNameEn") or "").strip(),
    })


def _same_path_and_content(requested: dict[str, Any], item: dict[str, Any]) -> bool:
    return _same_value(requested, item, "relativePath") and _same_value(requested, item, "contentHash")


def _same_content(requested: dict[str, Any], item: dict[str, Any]) -> bool:
    return _same_value(requested, item, "contentHash")


def _same_path_and_schema(requested: dict[str, Any], item: dict[str, Any]) -> bool:
    return _same_value(requested, item, "relativePath") and _same_value(requested, item, "schemaFingerprint")


def _resolve_table_match(
    requested: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    ordered = (
        ("asset_id", lambda item: _same_asset_id(requested, item)),
        ("id", lambda item: _same_value(requested, item, "id")),
        ("source_key", lambda item: _same_value(requested, item, "sourceKey")),
        ("path_content_hash", lambda item: _same_path_and_content(requested, item)),
        ("path_schema", lambda item: _same_path_and_schema(requested, item)),
        (
            "content_hash",
            lambda item: _table_kind(requested) == "uploaded_file" and _same_content(requested, item),
        ),
        ("code", lambda item: _table_kind(requested) != "raw" and _matches_code(requested, item)),
    )
    for strategy, predicate in ordered:
        match = _unique_match(candidates, predicate)
        if match is not None:
            return match, strategy
    legacy = None if _table_kind(requested) == "raw" else _legacy_evidence_match(requested, candidates)
    return legacy, "legacy_title_with_schema_evidence"


def _same_asset_id(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_value = str(left.get("assetId") or left.get("asset_id") or "").strip()
    right_value = str(right.get("assetId") or right.get("asset_id") or "").strip()
    return bool(left_value and right_value and left_value == right_value)


def _catalog_tenant_matches(table: dict[str, Any], tenant_id: str) -> bool:
    table_tenant = str(table.get("tenantId") or table.get("tenant_id") or "").strip()
    return not tenant_id or not table_tenant or table_tenant == tenant_id


def _table_lifecycle(table: dict[str, Any]) -> str:
    status = str(table.get("lifecycleStatus") or table.get("status") or "active").strip().lower()
    return "active" if status in {"", "active", "published", "ready"} else status


def _unique_match(items: list[dict[str, Any]], predicate: Any) -> dict[str, Any] | None:
    matched = [item for item in items if predicate(item)]
    return matched[0] if len(matched) == 1 else None


def _legacy_evidence_match(requested: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any] | None:
    schema = str(requested.get("schemaFingerprint") or "").strip()
    content = str(requested.get("contentHash") or "").strip()
    if not schema and not content:
        return None
    titles = _logical_title_keys(requested)
    if not titles:
        return None
    return _unique_match(
        items,
        lambda item: bool(titles & _logical_title_keys(item))
        and ((content and str(item.get("contentHash") or "") == content) or (schema and str(item.get("schemaFingerprint") or "") == schema)),
    )


def _logical_title_keys(item: dict[str, Any]) -> set[str]:
    from backend.platform.ingestion.csv_folder import _delivery_name_parts

    result: set[str] = set()
    for value in (item.get("tableNameCn"), item.get("name"), item.get("fileName"), item.get("relativePath")):
        title, _date = _delivery_name_parts(str(value or ""))
        cleaned = "".join(character.casefold() for character in (title or str(value or "")) if character.isalnum())
        if cleaned:
            result.add(cleaned)
    return result


def _table_field_ids(table: dict[str, Any]) -> set[str]:
    field_ids = {
        str(field.get("fieldNameEn") or field.get("canonicalId") or field.get("code") or "").strip()
        for field in table.get("fields") or []
        if isinstance(field, dict) and str(field.get("fieldNameEn") or field.get("canonicalId") or field.get("code") or "").strip()
    }
    for key in ("fieldLabels", "fieldMetadata"):
        mapping = table.get(key)
        if isinstance(mapping, dict):
            field_ids.update(str(item).strip() for item in mapping if str(item).strip())
    for key in ("metricCodes", "metric_codes", "dimensionCodes", "dimension_codes"):
        values = table.get(key)
        if isinstance(values, (list, tuple)):
            field_ids.update(str(item).strip() for item in values if str(item).strip())
    return field_ids


def _schema_field_differences(requested: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    requested_schema = str(requested.get("schemaFingerprint") or "").strip()
    current_schema = str(current.get("schemaFingerprint") or "").strip()
    if not requested_schema or not current_schema or requested_schema == current_schema:
        return []
    requested_contract = {
        str(item.get("canonicalId") or ""): item
        for item in field_contract_from_table(requested)
        if str(item.get("canonicalId") or "")
    }
    current_contract = {
        str(item.get("canonicalId") or ""): item
        for item in field_contract_from_table(current)
        if str(item.get("canonicalId") or "")
    }
    if not requested_contract:
        return [{
            "canonicalId": "__schema_contract__",
            "displayName": "字段结构",
            "change": "schema_fingerprint_changed_without_field_contract",
            "previous": requested_schema,
            "current": current_schema,
        }]
    differences: list[dict[str, str]] = []
    for canonical, expected in sorted(requested_contract.items()):
        actual = current_contract.get(canonical)
        display = str(expected.get("displayName") or canonical)
        if actual is None:
            differences.append({
                "canonicalId": canonical,
                "displayName": display,
                "change": "field_missing",
                "previous": str(expected.get("physicalName") or canonical),
                "current": "",
            })
            continue
        comparisons = (
            ("field_type_changed", "dataType"),
            ("physical_name_changed", "physicalName"),
            ("semantic_role_changed", "role"),
        )
        for change, key in comparisons:
            previous = str(expected.get(key) or "").strip().casefold()
            current_value = str(actual.get(key) or "").strip().casefold()
            if key == "dataType" and "unknown" in {previous, current_value}:
                continue
            if previous and current_value and previous != current_value:
                differences.append({
                    "canonicalId": canonical,
                    "displayName": display,
                    "change": change,
                    "previous": str(expected.get(key) or ""),
                    "current": str(actual.get(key) or ""),
                })
                break
    return differences


def _asset_version(table: dict[str, Any]) -> str:
    explicit = str(table.get("assetVersion") or table.get("asset_version") or table.get("version") or "").strip()
    content = str(table.get("contentHash") or table.get("content_hash") or "").strip()
    if _table_kind(table) == "raw" and content:
        return content[:16]
    return explicit or content[:16] or str(table.get("schemaFingerprint") or "").strip()[:16] or "1"
