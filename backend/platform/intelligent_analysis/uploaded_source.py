from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.platform.ingestion.csv_folder import _infer_type, _stable_field_codes
from backend.platform.ingestion.workbook import parse_static_workbook
from backend.platform.knowledge.files import (
    build_document_ocr_extractor,
    detect_document_type,
    parse_document,
)
from backend.platform.settings import call_model_text_completion


MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_INLINE_ROWS = 5_000
MAX_CACHE_ITEMS = 32
CACHE_TTL_SECONDS = 30 * 60
MEDIA_UNSUPPORTED_MESSAGE = "暂不支持视频、语音类文件。"
IMAGE_NO_TEXT_MESSAGE = "已识别为图片截图，但当前无法自动提取其中的文字。请上传 Word、PDF，或将文字复制到输入框后再分析。"
DOCUMENT_NO_TEXT_MESSAGE = "已识别为文档，但没有提取到可分析文字。请上传带文字的 Word、PDF，或带数字的 Excel。"
EXCEL_XLS_MESSAGE = "请上传 .xlsx 格式的 Excel 文件。"

_MEDIA_SUFFIXES = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".wmv", ".flv", ".m4v", ".3gp",
    ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma", ".aiff", ".opus", ".amr", ".weba",
})
_NUMBER_RE = re.compile(
    r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:%|万|亿)?$"
)

_cache_lock = threading.Lock()
_source_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass
class UploadedAnalysisSources:
    data_tables: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, str]] = field(default_factory=list)
    media_names: list[str] = field(default_factory=list)

    @property
    def media_blocked(self) -> bool:
        return bool(self.media_names) and not self.data_tables and not self.documents


def is_uploaded_analysis_table(table: dict[str, Any] | None) -> bool:
    if not isinstance(table, dict):
        return False
    path = str(table.get("relativePath") or table.get("relative_path") or "").strip()
    kind = str(table.get("kind") or "").strip().lower()
    return path.startswith("upload://") or kind == "uploaded_file"


def classify_uploaded_source(
    file_name: str,
    content: bytes,
    content_type: str = "",
) -> dict[str, Any]:
    normalized_name = str(file_name or "").strip() or "未命名文件"
    suffix = Path(normalized_name).suffix.lower()
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if not content:
        raise ValueError("analysis_uploaded_file_empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("analysis_uploaded_file_too_large")

    if _is_media(suffix, mime):
        return _payload(
            normalized_name,
            mime or "application/octet-stream",
            "unsupported_media",
            MEDIA_UNSUPPORTED_MESSAGE,
        )

    content_hash = hashlib.sha256(content).hexdigest()
    if suffix == ".xls":
        return _payload(
            normalized_name,
            mime or "application/vnd.ms-excel",
            "unsupported_media",
            EXCEL_XLS_MESSAGE,
            content_hash=content_hash,
        )

    if suffix in {".xlsx"} or _looks_like_xlsx(content):
        try:
            return _classify_tabular(normalized_name, content, content_hash, "xlsx")
        except ValueError as exc:
            raise ValueError("analysis_uploaded_file_unsupported") from exc
    if suffix in {".csv", ".tsv"} or mime in {"text/csv", "text/tab-separated-values"}:
        return _classify_tabular(normalized_name, content, content_hash, "csv", delimiter="\t" if suffix == ".tsv" else ",")
    if suffix == ".json" or mime == "application/json":
        return _classify_json(normalized_name, content, content_hash)

    detected_mime, parser_type = detect_document_type(normalized_name, content)
    if parser_type in {"pdf", "docx", "text", "ocr_image"}:
        extracted, warning = _extract_document_text(content, detected_mime, parser_type)
        message = warning or f"已识别为文档“{normalized_name}”，将生成文本总结。"
        result = _payload(
            normalized_name,
            detected_mime,
            "text_document",
            message,
            extracted_text=extracted,
            content_hash=content_hash,
        )
        remember_uploaded_source(content_hash, result)
        return result

    if suffix in {".txt", ".md", ".markdown", ".sql"}:
        text = content.decode("utf-8-sig", errors="replace").strip()
        result = _payload(
            normalized_name,
            mime or "text/plain",
            "text_document",
            f"已识别为文档“{normalized_name}”，将生成文本总结。",
            extracted_text=text,
            content_hash=content_hash,
        )
        remember_uploaded_source(content_hash, result)
        return result

    raise ValueError("analysis_uploaded_file_unsupported")


def resolve_uploaded_analysis_sources(page_context: dict[str, Any] | None) -> UploadedAnalysisSources:
    files = page_context.get("files") if isinstance(page_context, dict) else None
    if not isinstance(files, list):
        return UploadedAnalysisSources()
    sources = UploadedAnalysisSources()
    seen_tables: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        classified = _hydrate_uploaded_file(item)
        classification = str(classified.get("classification") or "")
        name = str(classified.get("file_name") or item.get("name") or "未命名文件")
        if classification == "unsupported_media":
            sources.media_names.append(name)
            continue
        table = classified.get("table") if isinstance(classified.get("table"), dict) else None
        if classification == "data_source" and table and is_uploaded_analysis_table(table):
            table_id = str(table.get("id") or "")
            if table_id and table_id not in seen_tables:
                seen_tables.add(table_id)
                sources.data_tables.append(table)
            continue
        extracted = str(classified.get("extracted_text") or "").strip()
        if classification == "text_document" or extracted:
            sources.documents.append({"name": name, "extracted_text": extracted})
    return sources


def remember_uploaded_source(content_hash: str, payload: dict[str, Any]) -> None:
    key = str(content_hash or "").strip()
    if not key:
        return
    with _cache_lock:
        _source_cache[key] = (time.monotonic(), dict(payload))
        stale = [item for item, (saved_at, _) in _source_cache.items() if time.monotonic() - saved_at > CACHE_TTL_SECONDS]
        for item in stale:
            _source_cache.pop(item, None)
        while len(_source_cache) > MAX_CACHE_ITEMS:
            oldest = min(_source_cache, key=lambda item: _source_cache[item][0])
            _source_cache.pop(oldest, None)


def recall_uploaded_source(content_hash: str) -> dict[str, Any] | None:
    key = str(content_hash or "").strip()
    if not key:
        return None
    with _cache_lock:
        saved = _source_cache.get(key)
        if saved is None:
            return None
        saved_at, payload = saved
        if time.monotonic() - saved_at > CACHE_TTL_SECONDS:
            _source_cache.pop(key, None)
            return None
        return dict(payload)


def summarize_uploaded_documents(
    question: str,
    documents: list[dict[str, str]],
    model: dict[str, Any] | None,
) -> str:
    texts = [
        f"文件：{item.get('name') or '未命名'}\n{str(item.get('extracted_text') or '').strip()}"
        for item in documents
        if str(item.get("extracted_text") or "").strip()
    ]
    if not texts:
        if any(_looks_like_image_name(str(item.get("name") or "")) for item in documents):
            return IMAGE_NO_TEXT_MESSAGE
        return DOCUMENT_NO_TEXT_MESSAGE
    joined = "\n\n".join(texts)[:12_000]
    if not isinstance(model, dict) or not model.get("id"):
        return joined[:4000]
    prompt = (
        "用户在智能分析中上传了文档。请只根据这些文档内容回答问题，不要调用或改用系统数据表。\n"
        f"用户问题：{question.strip() or '请总结上传文档'}\n\n"
        f"文档内容：\n{joined}\n\n"
        "请输出简洁的中文文本总结，直接写结论，不要使用 JSON。"
    )
    completion = call_model_text_completion(model, prompt, max_tokens=1200)
    summary = str(completion.get("response_text") or "").strip()
    if completion.get("status") == "connected" and summary:
        return summary[:8000]
    return joined[:4000]


def build_uploaded_document_summary(
    question: str,
    documents: list[dict[str, str]],
    model: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary = summarize_uploaded_documents(question, documents, model)
    names = "、".join(str(item.get("name") or "文档") for item in documents[:8]) or "上传文档"
    sql = "-- 本次分析使用上传文档文本，未查询系统数据表。"
    query_result = {
        "sql": sql,
        "data": [],
        "chart_spec": {"type": "text", "title": "文本总结", "x": "", "y": ""},
        "visualization_spec": {
            "chart_type": "text",
            "title": "文本总结",
            "reason": "上传文件没有可分析数字，改为文本总结",
            "alternatives": [],
        },
        "semantic_info": {
            "dataset_id": "uploaded_document",
            "data_source": "uploaded_document",
            "execution_mode": "uploaded_document_summary",
            "sql_executed": False,
            "policy_enforced_at_source": True,
            "publishable": False,
            "schema_mapping": {"metrics": [], "dimensions": [], "field_labels": {}},
            "metric_definitions_bound": False,
            "source_snapshot": {"document_names": names},
        },
    }
    plan = {
        "dataset_id": "uploaded_document",
        "metrics": [],
        "dimensions": [],
        "chart_types": ["text"],
        "analysis_angles": ["仅总结用户上传的文档文字", "不调度系统数据表"],
        "business_focus": f"总结上传文档：{names}",
        "temporary_metric_semantics": True,
        "temporary_metric_source": "uploaded_document",
        "planning_source": "uploaded_document",
        "planning_invocation": {
            "status": "skipped",
            "callable": False,
            "message": "上传文档按文本总结处理，跳过数据表查询。",
        },
    }
    intelligent_analysis = {
        "planning": plan,
        "suggested_sql": sql,
        "executed_sql": sql,
        "visualization_suggestions": [{"type": "text", "title": "文本总结", "purpose": "展示上传文档的文字总结。"}],
        "analysis_approach": ["仅根据上传文档文字进行总结，不查询系统数据表。"],
        "metric_scenarios": [],
        "metric_findings": [],
        "possible_conclusions": [summary],
        "analysis_summary": summary,
        "conclusion_coverage": {},
        "planning_invocation": plan["planning_invocation"],
        "model_invocation": {"status": "connected" if isinstance(model, dict) and model.get("id") else "skipped"},
        "model_draft": summary,
    }
    return query_result, plan, intelligent_analysis


def public_classify_payload(result: dict[str, Any]) -> dict[str, Any]:
    table = result.get("table") if isinstance(result.get("table"), dict) else None
    public_table = None
    if table:
        public_table = {
            **table,
            "previewRows": list(table.get("previewRows") or [])[:50],
        }
    return {
        "classification": result.get("classification"),
        "message": result.get("message") or "",
        "file_name": result.get("file_name") or "",
        "content_type": result.get("content_type") or "",
        "content_hash": result.get("content_hash") or "",
        "extracted_text": str(result.get("extracted_text") or "")[:24_000],
        "table": public_table,
        "row_count": int((table or {}).get("rowCount") or 0),
    }


def _hydrate_uploaded_file(item: dict[str, Any]) -> dict[str, Any]:
    content_hash = str(item.get("contentHash") or item.get("content_hash") or "").strip()
    cached = recall_uploaded_source(content_hash)
    if cached:
        return cached
    encoded = str(item.get("content_base64") or item.get("contentBase64") or "").strip()
    if encoded:
        import base64
        import binascii

        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            content = b""
        if content:
            return classify_uploaded_source(
                str(item.get("name") or item.get("file_name") or "未命名文件"),
                content,
                str(item.get("type") or item.get("content_type") or ""),
            )
    table = item.get("parsedTable") or item.get("parsed_table") or item.get("table")
    extracted = str(item.get("extractedText") or item.get("extracted_text") or item.get("contentPreview") or "").strip()
    classification = str(item.get("classification") or "").strip()
    name = str(item.get("name") or item.get("file_name") or "未命名文件")
    if isinstance(table, dict) and (classification == "data_source" or _table_has_numbers(table)):
        return _payload(name, str(item.get("type") or ""), "data_source", "", table=table, extracted_text=extracted, content_hash=content_hash)
    if classification == "unsupported_media" or _is_media(Path(name).suffix.lower(), str(item.get("type") or "")):
        return _payload(name, str(item.get("type") or ""), "unsupported_media", MEDIA_UNSUPPORTED_MESSAGE, content_hash=content_hash)
    if classification == "text_document" or extracted:
        return _payload(name, str(item.get("type") or ""), "text_document", "", extracted_text=extracted, content_hash=content_hash)
    return _payload(name, str(item.get("type") or ""), classification or "text_document", "", extracted_text=extracted, content_hash=content_hash)


def _classify_tabular(
    file_name: str,
    content: bytes,
    content_hash: str,
    kind: str,
    *,
    delimiter: str = ",",
) -> dict[str, Any]:
    if kind == "xlsx":
        sheets = parse_static_workbook(file_name, content)
        chosen = None
        fallback_text = []
        for sheet in sheets:
            table = _table_from_csv_bytes(file_name, sheet.name, sheet.csv_bytes, content_hash, ",")
            if table and _table_has_numbers(table):
                chosen = table
                break
            if table:
                fallback_text.append(_table_as_text(table))
        if chosen is not None:
            result = _payload(
                file_name,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "data_source",
                f"已识别“{file_name}”中的数据，将作为本次分析数据源，不调度系统数据表。",
                table=chosen,
                content_hash=content_hash,
            )
            remember_uploaded_source(content_hash, result)
            return result
        extracted = "\n\n".join(item for item in fallback_text if item).strip()
        result = _payload(
            file_name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text_document",
            f"“{file_name}”没有可分析数字，将生成文本总结。",
            extracted_text=extracted,
            content_hash=content_hash,
        )
        remember_uploaded_source(content_hash, result)
        return result

    table = _table_from_csv_bytes(file_name, Path(file_name).stem, content, content_hash, delimiter)
    if table and _table_has_numbers(table):
        result = _payload(
            file_name,
            "text/csv",
            "data_source",
            f"已识别“{file_name}”中的数据，将作为本次分析数据源，不调度系统数据表。",
            table=table,
            content_hash=content_hash,
        )
        remember_uploaded_source(content_hash, result)
        return result
    text = content.decode("utf-8-sig", errors="replace").strip()
    result = _payload(
        file_name,
        "text/csv",
        "text_document",
        f"“{file_name}”没有可分析数字，将生成文本总结。",
        extracted_text=text,
        content_hash=content_hash,
    )
    remember_uploaded_source(content_hash, result)
    return result


def _classify_json(file_name: str, content: bytes, content_hash: str) -> dict[str, Any]:
    text = content.decode("utf-8-sig", errors="replace")
    parsed = json.loads(text)
    rows: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        rows = [dict(item) for item in parsed if isinstance(item, dict)]
    elif isinstance(parsed, dict):
        for key in ("data", "rows", "items", "records"):
            value = parsed.get(key)
            if isinstance(value, list):
                rows = [dict(item) for item in value if isinstance(item, dict)]
                break
        if not rows and all(not isinstance(value, (dict, list)) for value in parsed.values()):
            rows = [parsed]
    if rows:
        headers = []
        for row in rows:
            for key in row:
                label = str(key).strip()
                if label and label not in headers:
                    headers.append(label)
        table = _table_from_rows(file_name, Path(file_name).stem, headers, rows, content_hash)
        if table and _table_has_numbers(table):
            result = _payload(
                file_name,
                "application/json",
                "data_source",
                f"已识别“{file_name}”中的数据，将作为本次分析数据源，不调度系统数据表。",
                table=table,
                content_hash=content_hash,
            )
            remember_uploaded_source(content_hash, result)
            return result
    result = _payload(
        file_name,
        "application/json",
        "text_document",
        f"“{file_name}”没有可分析数字，将生成文本总结。",
        extracted_text=text.strip(),
        content_hash=content_hash,
    )
    remember_uploaded_source(content_hash, result)
    return result


def _table_from_csv_bytes(
    file_name: str,
    sheet_name: str,
    content: bytes,
    content_hash: str,
    delimiter: str,
) -> dict[str, Any] | None:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = [list(row) for row in reader]
    if not rows:
        return None
    headers = [str(value or "").strip() or f"字段{index}" for index, value in enumerate(rows[0], start=1)]
    body = rows[1:]
    records = []
    for row in body:
        record = {headers[index]: (row[index].strip() if index < len(row) else "") for index in range(len(headers))}
        if any(record.values()):
            records.append(record)
    if not records:
        return None
    return _table_from_rows(file_name, sheet_name, headers, records, content_hash)


def _table_from_rows(
    file_name: str,
    sheet_name: str,
    headers: list[str],
    rows: list[dict[str, Any]],
    content_hash: str,
) -> dict[str, Any]:
    used: set[str] = set()
    normalized_headers: list[str] = []
    for index, header in enumerate(headers, start=1):
        base = str(header or "").strip() or f"字段{index}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        normalized_headers.append(candidate)
    samples = {header: [] for header in normalized_headers}
    limited_rows: list[dict[str, str]] = []
    for row in rows[:MAX_INLINE_ROWS]:
        normalized: dict[str, str] = {}
        for header in normalized_headers:
            value = row.get(header, "")
            text = "" if value is None else str(value).strip()
            normalized[header] = text
            if text and len(samples[header]) < 8:
                samples[header].append(text)
        limited_rows.append(normalized)
    field_codes = _stable_field_codes(normalized_headers)
    fields = []
    for header in normalized_headers:
        inferred = _infer_type(samples[header])
        fields.append({
            "fieldNameEn": field_codes[header],
            "fieldNameCn": header,
            "type": inferred,
            "isMetric": inferred in {"integer", "decimal"},
            "isTime": inferred in {"date", "datetime"},
            "explanation": f"上传文件字段“{header}”",
        })
    identity = content_hash[:24]
    coded_rows = [
        {field_codes[header]: row.get(header, "") for header in normalized_headers}
        for row in limited_rows
    ]
    metric_codes = [str(field["fieldNameEn"]) for field in fields if field["isMetric"]]
    dimension_codes = [str(field["fieldNameEn"]) for field in fields if not field["isMetric"]]
    schema_fingerprint = hashlib.sha256(
        json.dumps(
            [
                {
                    "canonical_id": field["fieldNameEn"],
                    "physical_name": field["fieldNameCn"],
                    "type": field["type"],
                }
                for field in fields
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    display_name = f"{Path(file_name).stem}_{sheet_name}" if sheet_name and sheet_name != Path(file_name).stem else Path(file_name).stem
    return {
        "id": f"upload_{identity}",
        "assetId": f"upload:{content_hash}",
        "assetVersion": content_hash[:16],
        "kind": "uploaded_file",
        "tableNameEn": f"upload_{identity[:16]}",
        "tableNameCn": display_name[:160],
        "name": display_name[:160],
        "code": f"upload_{identity[:16]}",
        "source": "用户上传文件",
        "tableType": "uploaded_file",
        "description": f"{file_name} · 用户上传数据，共 {len(coded_rows)} 行、{len(fields)} 个字段。",
        "exampleSql": f"-- 上传文件：{file_name}\nSELECT * FROM upload_{identity[:16]} LIMIT 100;",
        "fields": fields,
        "relativePath": f"upload://{identity}",
        "schemaFingerprint": schema_fingerprint,
        "contentHash": content_hash,
        "rowCount": len(coded_rows),
        "previewRows": coded_rows,
        "metricCodes": metric_codes,
        "defaultMetrics": metric_codes[:8],
        "dimensionCodes": dimension_codes,
        "defaultDimensions": dimension_codes[:4],
        "chartTypes": ["column", "table", "line"],
        "sourceReadOnly": True,
        "workbookName": file_name,
        "sheetName": sheet_name,
    }


def _table_has_numbers(table: dict[str, Any]) -> bool:
    fields = [field for field in table.get("fields") or [] if isinstance(field, dict)]
    if any(str(field.get("type") or "").lower() in {"integer", "decimal", "number", "float"} or field.get("isMetric") for field in fields):
        return True
    for row in table.get("previewRows") or []:
        if not isinstance(row, dict):
            continue
        for value in row.values():
            text = str(value or "").strip().replace(" ", "")
            if text and _NUMBER_RE.fullmatch(text.replace(",", "")):
                return True
    return False


def _table_as_text(table: dict[str, Any]) -> str:
    fields = [field for field in table.get("fields") or [] if isinstance(field, dict)]
    headers = [str(field.get("fieldNameCn") or field.get("fieldNameEn") or "") for field in fields]
    codes = [str(field.get("fieldNameEn") or "") for field in fields]
    lines = ["\t".join(headers)]
    for row in (table.get("previewRows") or [])[:80]:
        if isinstance(row, dict):
            lines.append("\t".join(str(row.get(code) or "") for code in codes))
    return "\n".join(lines).strip()


def _extract_document_text(content: bytes, content_type: str, parser_type: str) -> tuple[str, str]:
    if parser_type == "ocr_image":
        extractor = build_document_ocr_extractor()
        if extractor is None:
            return "", IMAGE_NO_TEXT_MESSAGE
        try:
            text, _engine = extractor.extract(content, content_type)
            return text.strip(), ""
        except Exception:
            return "", IMAGE_NO_TEXT_MESSAGE
    try:
        text, _engine = parse_document(content, parser_type)
        return text.strip(), ""
    except Exception as exc:
        should_try_ocr = parser_type == "pdf" and str(exc) == "pdf_has_no_extractable_text"
        if should_try_ocr:
            extractor = build_document_ocr_extractor()
            if extractor is not None:
                try:
                    text, _engine = extractor.extract(content, content_type)
                    return text.strip(), ""
                except Exception:
                    pass
        if parser_type == "ocr_image":
            return "", IMAGE_NO_TEXT_MESSAGE
        return "", DOCUMENT_NO_TEXT_MESSAGE


def _is_media(suffix: str, mime: str) -> bool:
    if suffix in _MEDIA_SUFFIXES:
        return True
    return mime.startswith("video/") or mime.startswith("audio/")


def _looks_like_xlsx(content: bytes) -> bool:
    if not content.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return "xl/workbook.xml" in set(archive.namelist())
    except zipfile.BadZipFile:
        return False


def _looks_like_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def _payload(
    file_name: str,
    content_type: str,
    classification: str,
    message: str,
    *,
    table: dict[str, Any] | None = None,
    extracted_text: str = "",
    content_hash: str = "",
) -> dict[str, Any]:
    return {
        "file_name": file_name,
        "content_type": content_type,
        "classification": classification,
        "message": message,
        "table": table,
        "extracted_text": extracted_text,
        "content_hash": content_hash,
    }
