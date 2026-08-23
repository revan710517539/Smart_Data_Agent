from __future__ import annotations

import argparse
from importlib import metadata
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "licenses" / "open_source_policy.json"
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
        _check_license("npm", name, license_name, allowed, policy, violations)
        components.append(_component("npm", name, str(package.get("version") or ""), license_name))

    expectations = policy.get("python_license_expectations") or {}
    for requirement in _python_dependencies():
        normalized = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].lower()
        expected = set(expectations.get(normalized) or [])
        if not expected:
            violations.append(f"python:{normalized}:license_expectation_missing")
            continue
        try:
            distribution = metadata.distribution(normalized)
        except metadata.PackageNotFoundError:
            violations.append(f"python:{normalized}:distribution_missing")
            continue
        license_name = _python_license(distribution.metadata)
        if license_name not in expected:
            violations.append(f"python:{normalized}:license_drift:{license_name or 'missing'}")
        _check_license("python", normalized, license_name, allowed, policy, violations)
        components.append(_component("pypi", normalized, distribution.version, license_name))

    lowered_paths = [
        path.relative_to(ROOT).as_posix().lower()
        for path in ROOT.rglob("*")
        if ".git" not in path.parts and "node_modules" not in path.parts and "artifacts" not in path.parts
    ]
    for forbidden_path in policy["forbidden_source_paths"]:
        marker = str(forbidden_path).strip("/").lower()
        if any(path == marker or path.startswith(marker + "/") for path in lowered_paths):
            violations.append(f"source_path_forbidden:{forbidden_path}")

    report = {
        "schema_version": "smart-data-agent-open-source-audit/v1",
        "policy": POLICY_PATH.relative_to(ROOT).as_posix(),
        "project_distribution": policy.get("project_distribution"),
        "components": len(components),
        "violations": sorted(set(violations)),
    }
    if write_sbom:
        SBOM_PATH.parent.mkdir(parents=True, exist_ok=True)
        SBOM_PATH.write_text(
            json.dumps({
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "metadata": {"component": {"type": "application", "name": "smart-data-agent"}},
                "components": components,
            }, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report["sbom"] = SBOM_PATH.relative_to(ROOT).as_posix()
    return report


def _check_license(
    ecosystem: str,
    name: str,
    license_name: str,
    allowed: set[str],
    policy: dict[str, Any],
    violations: list[str],
) -> None:
    if not license_name:
        violations.append(f"{ecosystem}:{name}:license_missing")
        return
    lowered = license_name.lower()
    if any(lowered.startswith(str(prefix).lower()) for prefix in policy.get("forbidden_license_prefixes", [])):
        violations.append(f"{ecosystem}:{name}:proprietary_or_source_available:{license_name}")
    if any(str(marker).lower() in lowered for marker in policy.get("forbidden_license_markers", [])):
        violations.append(f"{ecosystem}:{name}:restricted_marker:{license_name}")
    if license_name not in allowed:
        violations.append(f"{ecosystem}:{name}:license_not_allowed:{license_name}")


def _python_license(package: metadata.PackageMetadata) -> str:
    expression = str(package.get("License-Expression") or "").strip()
    if expression:
        return expression
    classifiers = "\n".join(package.get_all("Classifier") or [])
    classifier_map = (
        ("Mozilla Public License 2.0", "MPL-2.0"),
        ("Apache Software License", "Apache-2.0"),
        ("MIT License", "MIT"),
        ("BSD License", "BSD-3-Clause"),
    )
    for marker, spdx in classifier_map:
        if marker in classifiers:
            return spdx
    license_text = str(package.get("License") or "").strip()
    if "Permission is hereby granted, free of charge" in license_text:
        return "MIT"
    return " ".join(license_text.split())[:160]


def _python_dependencies() -> list[str]:
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r"dependencies\s*=\s*\[(.*?)\]\s*\n", text, re.DOTALL)
    if not block:
        raise RuntimeError("pyproject_dependencies_not_found")
    return re.findall(r'"([^"]+)"', block.group(1))


def _component(ecosystem: str, name: str, version: str, license_name: str) -> dict[str, Any]:
    return {
        "type": "library",
        "name": name,
        "version": version,
        "purl": f"pkg:{ecosystem}/{name}",
        "licenses": [{"license": {"id": license_name}}],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed on proprietary, source-available, or unreviewed dependencies.")
    parser.add_argument("--write-sbom", action="store_true")
    args = parser.parse_args()
    report = audit(write_sbom=args.write_sbom)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
