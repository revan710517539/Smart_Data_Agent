from __future__ import annotations

import base64
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"x": _MAIN, "r": _REL, "p": _PKG}
_NAME = "新指标名称（命名规则：客群+业务节点+计算逻辑）"
_REQUIRED = {"应用场景", "原指标名称", _NAME, "指标口径", "取值逻辑", "取值表名", "系统来源", "指标维度", "统计时间", "指标引用文档"}


def parse_metric_workbook(encoded_content: str) -> list[dict[str, str]]:
    try:
        raw = base64.b64decode(encoded_content, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("指标文件内容无效，请重新选择 .xlsx 文件。") from exc
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError("指标文件不能为空且不得超过 8MB。")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            rows = _rows(archive.read(_sheet_path(archive)), _strings(archive))
    except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("无法解析指标 Excel，请使用标准 .xlsx 模板。") from exc
    if not rows:
        raise ValueError("Excel 中未找到指标数据。")
    headers = {value.strip(): index for index, value in enumerate(rows[0]) if value.strip()}
    if not _REQUIRED.issubset(headers):
        raise ValueError("Excel 缺少指标模板必填列，请使用“指标库-指标体系”工作表。")
    output: list[dict[str, str]] = []
    current_institution = ""
    for values in rows[1:]:
        row = {header: values[index].strip() if index < len(values) else "" for header, index in headers.items()}
        current_institution = row.get("数据机构") or current_institution
        name = row.get(_NAME) or row.get("原指标名称")
        if not name:
            continue
        description = "；".join(part for part in [
            f"原指标名称：{row['原指标名称']}" if row.get("原指标名称") else "",
            f"数据机构：{current_institution}" if current_institution else "",
            f"备注：{row['备注']}" if row.get("备注") else "",
        ] if part)
        output.append({"metricName": name, "definition": row.get("指标口径", ""), "valueLogic": row.get("取值逻辑", ""), "sourceTable": row.get("取值表名", ""), "dimension": row.get("指标维度", ""), "description": description, "applicationScene": row.get("应用场景", ""), "systemSource": row.get("系统来源", ""), "statTime": row.get("统计时间", ""), "referenceDocument": row.get("指标引用文档", "")})
    if not output:
        raise ValueError("Excel 中没有可导入的指标名称。")
    return output


def _strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(item.itertext()) for item in root.findall("x:si", _NS)]


def _sheet_path(archive: ZipFile) -> str:
    book = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relations = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {item.attrib.get("Id"): item.attrib.get("Target", "") for item in relations.findall("p:Relationship", _NS)}
    sheets = book.findall("x:sheets/x:sheet", _NS)
    sheet = next((item for item in sheets if item.attrib.get("name") == "指标库-指标体系"), sheets[0] if sheets else None)
    if sheet is None:
        raise KeyError("worksheet missing")
    target = targets.get(sheet.attrib.get(f"{{{_REL}}}id"), "")
    return str(PurePosixPath("xl") / target).replace("xl/xl/", "xl/")


def _rows(payload: bytes, strings: list[str]) -> list[list[str]]:
    root = ElementTree.fromstring(payload)
    output: list[list[str]] = []
    for row in root.findall("x:sheetData/x:row", _NS):
        values: list[str] = []
        for cell in row.findall("x:c", _NS):
            column = _column(cell.attrib.get("r", "A1"))
            while len(values) <= column:
                values.append("")
            raw = cell.findtext("x:v", default="", namespaces=_NS)
            if cell.attrib.get("t") == "s" and raw:
                values[column] = strings[int(raw)]
            elif cell.attrib.get("t") == "inlineStr":
                inline = cell.find("x:is", _NS)
                values[column] = "".join(inline.itertext()) if inline is not None else ""
            else:
                values[column] = raw
        output.append(values)
    return output


def _column(reference: str) -> int:
    value = 0
    for char in (item for item in reference.upper() if item.isalpha()):
        value = value * 26 + ord(char) - ord("A") + 1
    return max(value - 1, 0)
