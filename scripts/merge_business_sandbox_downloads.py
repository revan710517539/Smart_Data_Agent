from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "智能运营源站下载"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "智能运营" / "完整页面数据" / "经营沙盘"
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge source 经营沙盘 XLSX downloads into one code-free standard 65-column CSV."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--expected-reports", type=int, default=5_278)
    args = parser.parse_args()
    summary = merge_downloads(
        input_root=Path(args.input).resolve(),
        output_root=Path(args.output).resolve(),
        expected_reports=args.expected_reports,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def merge_downloads(*, input_root: Path, output_root: Path, expected_reports: int) -> dict[str, Any]:
    manifest_path = input_root / "下载清单.jsonl"
    if not manifest_path.is_file():
        raise FileNotFoundError("business_sandbox_download_manifest_missing")
    manifests: dict[str, dict[str, Any]] = {}
    with manifest_path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict) or item.get("tab") != "经营沙盘":
                continue
            key = str(item.get("key") or "")
            source_path = Path(str(item.get("path") or ""))
            if key and source_path.is_file():
                manifests[key] = item
    headers: list[str] | None = None
    records: list[list[str]] = []
    errors: list[dict[str, str]] = []
    for key, item in sorted(manifests.items()):
        source_path = Path(str(item["path"]))
        try:
            source_rows = _xlsx_rows(source_path)
            if len(source_rows) < 2 or len(source_rows[0]) != 65:
                raise ValueError("business_report_shape_invalid")
            if headers is None:
                headers = source_rows[0]
            elif headers != source_rows[0]:
                raise ValueError("business_report_headers_changed")
            combination = item.get("combination") if isinstance(item.get("combination"), dict) else {}
            for row in source_rows[1:]:
                normalized = (row + [""] * 65)[:65]
                normalized[0] = str(combination.get("second_name") or "")
                normalized[1] = str(combination.get("third_name") or "")
                records.append(normalized)
        except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
            errors.append({"key": key, "path": str(source_path), "error": type(exc).__name__})
    if headers is None:
        raise RuntimeError("business_sandbox_download_rows_empty")
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / "经营沙盘全量标准指标报表.csv"
    _write_csv(destination, headers, records)
    summary = {
        "path": str(destination),
        "expected_reports": expected_reports,
        "merged_reports": len(manifests) - len(errors),
        "merged_rows": len(records),
        "columns": len(headers),
        "complete": len(manifests) - len(errors) == expected_reports,
        "errors": errors[:100],
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }
    _write_json(output_root / "完整性清单.json", summary)
    return summary


def _xlsx_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _shared_strings(archive)
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        output: list[list[str]] = []
        for row in root.findall(".//m:sheetData/m:row", _NS):
            output.append([_cell_value(cell, shared_strings) for cell in row.findall("m:c", _NS)])
        return output


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", _NS))
        for item in root.findall("m:si", _NS)
    ]


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", _NS))
    node = cell.find("m:v", _NS)
    value = "" if node is None else str(node.text or "")
    if cell.get("t") == "s" and value.isdigit() and int(value) < len(shared_strings):
        return shared_strings[int(value)]
    return value


def _write_csv(path: Path, headers: list[str], records: list[list[str]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(records)
    content = stream.getvalue().encode("utf-8-sig")
    temporary = path.parent / f".{path.name}.{hashlib.sha256(content).hexdigest()[:12]}.tmp"
    temporary.write_bytes(content)
    temporary.replace(path)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.{hashlib.sha256(content).hexdigest()[:12]}.tmp"
    temporary.write_bytes(content)
    temporary.replace(path)


if __name__ == "__main__":
    main()
