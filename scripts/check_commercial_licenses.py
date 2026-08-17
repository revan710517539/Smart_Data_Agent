from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "licenses" / "commercial_policy.json"
PACKAGE_LOCK = ROOT / "package-lock.json"
PYPROJECT = ROOT / "pyproject.toml"
SBOM_PATH = ROOT / "artifacts" / "sbom" / "smart-data-agent.cdx.json"


def audit(*, write_sbom: bool = False) -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    allowed = set(policy["allowed_spdx"]) | set(policy["allowed_expressions"])
    violations: list[str] = []
    components: list[dict[str, Any]] = []
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    for package_path, package in sorted(lock.get("packages", {}).items()):
        if not package_path or not package_path.startswith("node_modules/"):
            continue
        name = package_path.removeprefix("node_modules/")
        license_name = str(package.get("license") or "").strip()
        if not license_name:
            violations.append(f"npm:{name}:license_missing")
        elif license_name not in allowed:
            violations.append(f"npm:{name}:license_not_allowed:{license_name}")
        components.append(_component("npm", name, str(package.get("version") or ""), license_name))

    reviewed_python = set(policy["python_dependencies_reviewed"])
    for requirement in _python_dependencies():
        normalized = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].lower()
        if normalized not in reviewed_python:
            violations.append(f"python:{normalized}:review_required")
        components.append(_component("pypi", normalized, requirement, "reviewed-by-policy"))

    lowered_paths = [path.relative_to(ROOT).as_posix().lower() for path in ROOT.rglob("*") if ".git" not in path.parts and "node_modules" not in path.parts]
    for forbidden_path in policy["forbidden_source_paths"]:
        marker = str(forbidden_path).strip("/").lower()
        if any(path == marker or path.startswith(marker + "/") for path in lowered_paths):
            violations.append(f"source_path_forbidden:{forbidden_path}")

    report = {"policy": POLICY_PATH.relative_to(ROOT).as_posix(), "components": len(components), "violations": sorted(set(violations))}
    if write_sbom:
        SBOM_PATH.parent.mkdir(parents=True, exist_ok=True)
        SBOM_PATH.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "metadata": {"component": {"type": "application", "name": "smart-data-agent"}}, "components": components}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["sbom"] = SBOM_PATH.relative_to(ROOT).as_posix()
    return report


def _python_dependencies() -> list[str]:
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r"dependencies\s*=\s*\[(.*?)\]\s*\n", text, re.DOTALL)
    if not block:
        raise RuntimeError("pyproject_dependencies_not_found")
    return re.findall(r'"([^"]+)"', block.group(1))


def _component(ecosystem: str, name: str, version: str, license_name: str) -> dict[str, Any]:
    return {"type": "library", "name": name, "version": version, "purl": f"pkg:{ecosystem}/{name}", "licenses": [{"license": {"id": license_name}}]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed on non-commercial or unreviewed dependencies.")
    parser.add_argument("--write-sbom", action="store_true")
    args = parser.parse_args()
    report = audit(write_sbom=args.write_sbom)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
