from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.download_business_sandbox_reports import DEFAULT_OUTPUT, _validate_source_xlsx


TABS = ("经营沙盘", "经营明细")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit the resumable FocusPro business-sandbox source-download manifest."
    )
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--expected-per-tab", type=int, default=5_278)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.expected_per_tab < 1:
        raise ValueError("expected_per_tab_must_be_positive")

    root = Path(args.root).resolve()
    summary = audit_downloads(root, expected_per_tab=args.expected_per_tab)
    output = Path(args.output).resolve() if args.output else root / "下载完整性清单.json"
    _write_json_atomic(output, summary)
    print(json.dumps(summary["summary"], ensure_ascii=False, sort_keys=True))
    print(f"Audit: {output}")


def audit_downloads(root: Path, *, expected_per_tab: int) -> dict[str, Any]:
    manifest = root / "下载清单.jsonl"
    records = _latest_manifest_records(manifest)
    sections: dict[str, dict[str, Any]] = {}
    for tab in TABS:
        tab_records = [row for row in records.values() if row.get("tab") == tab]
        stats = Counter()
        missing_paths: list[str] = []
        invalid_paths: list[str] = []
        for row in tab_records:
            path = Path(str(row.get("path") or ""))
            if not path.is_file():
                stats["missing_file"] += 1
                if len(missing_paths) < 100:
                    missing_paths.append(str(path))
                continue
            stats["present_file"] += 1
            validation = _validate_source_xlsx(path)
            if not validation.get("valid_xlsx"):
                stats["invalid_xlsx"] += 1
                if len(invalid_paths) < 100:
                    invalid_paths.append(str(path))
                continue
            stats["valid_xlsx"] += 1
            if int(validation.get("data_rows") or 0) > 0:
                stats["with_data_rows"] += 1
            if int(validation.get("nonzero_metric_cells") or 0) > 0:
                stats["with_nonzero_metrics"] += 1
            else:
                stats["all_numeric_metrics_zero"] += 1
        delivery_complete = (
            len(tab_records) == expected_per_tab
            and stats["present_file"] == expected_per_tab
            and stats["valid_xlsx"] == expected_per_tab
        )
        sections[tab] = {
            "expected_files": expected_per_tab,
            "manifest_records": len(tab_records),
            "present_files": stats["present_file"],
            "valid_xlsx_files": stats["valid_xlsx"],
            "files_with_data_rows": stats["with_data_rows"],
            "files_with_nonzero_metrics": stats["with_nonzero_metrics"],
            "files_with_all_numeric_metrics_zero": stats["all_numeric_metrics_zero"],
            "missing_file_count": stats["missing_file"],
            "invalid_xlsx_count": stats["invalid_xlsx"],
            "download_delivery_complete": delivery_complete,
            "sample_missing_paths": missing_paths,
            "sample_invalid_xlsx_paths": invalid_paths,
        }
    expected_total = expected_per_tab * len(TABS)
    valid_total = sum(section["valid_xlsx_files"] for section in sections.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest),
        "tabs": sections,
        "summary": {
            "expected_files": expected_total,
            "manifest_records": len(records),
            "valid_xlsx_files": valid_total,
            "download_delivery_complete": all(
                section["download_delivery_complete"] for section in sections.values()
            ),
        },
    }


def _latest_manifest_records(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            if key:
                records[key] = row
    return records


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
