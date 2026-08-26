#!/usr/bin/env python3
"""Record and compare candidate/production runtime identity without secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

try:
    from scripts.data_crawler_mount_contract import (
        MountContractError,
        inspect_mount_evidence,
        normalize_mount_contract,
    )
except ModuleNotFoundError:  # Direct execution sets sys.path to scripts/.
    from data_crawler_mount_contract import (  # type: ignore[no-redef]
        MountContractError,
        inspect_mount_evidence,
        normalize_mount_contract,
    )


ROOT = Path(__file__).resolve().parents[1]
IDENTITY_KEYS = (
    "commit_sha",
    "image_reference",
    "source_archive_sha256",
    "dependency_lock_sha256",
    "frontend_assets_sha256",
    "release_toolchain_sha256",
)
SUPPORTED_TARGET_PLATFORMS = {"linux/amd64", "linux/arm64"}
CAPABILITY_KEYS = (
    "configured",
    "enabled",
    "ready",
    "status",
    "dependency",
    "schema_version",
    "tenant_count",
    "file_count",
)


def assert_local_source_closure(identity: dict[str, str], local_release: dict[str, object]) -> None:
    differences = [
        key
        for key in ("commit_sha", *IDENTITY_KEYS[2:])
        if str(local_release.get(key) or "") != identity[key]
    ]
    if differences:
        raise SystemExit("deployment_identity_source_closure_mismatch:" + ",".join(differences))


def normalized_capabilities(value: object) -> dict[str, dict[str, object]]:
    """Project a secret-free, location-independent capability contract.

    Candidate and production use different public origins and runtime instance
    identifiers. Those locations are evidence, not capabilities. Operational
    semantics and bounded Crawler inventory must remain identical.
    """

    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, object]] = {}
    for capability_name, raw_capability in sorted(value.items()):
        if not isinstance(raw_capability, dict):
            continue
        result[str(capability_name)] = {
            key: raw_capability[key]
            for key in CAPABILITY_KEYS
            if key in raw_capability
        }
    return result


def assert_capability_compatibility(candidate: object, production: object) -> None:
    candidate_matrix = normalized_capabilities(candidate)
    production_matrix = normalized_capabilities(production)
    if candidate_matrix == production_matrix:
        return
    names = sorted(set(candidate_matrix) | set(production_matrix))
    differences = [name for name in names if candidate_matrix.get(name) != production_matrix.get(name)]
    raise SystemExit("deployment_identity_candidate_production_capability_mismatch:" + ",".join(differences))


def normalized_image_platform(image: dict[str, object]) -> dict[str, str]:
    """Return the concrete Linux image platform selected by the Docker daemon."""

    operating_system = str(image.get("Os") or "").strip().lower()
    architecture = str(image.get("Architecture") or "").strip().lower()
    platform_name = f"{operating_system}/{architecture}"
    if platform_name not in SUPPORTED_TARGET_PLATFORMS:
        raise SystemExit("deployment_identity_image_platform_unsupported")
    return {
        "os": operating_system,
        "architecture": architecture,
        "variant": str(image.get("Variant") or "").strip().lower(),
        "platform": platform_name,
    }


def immutable_image_reference_matches(
    image_reference: str,
    *,
    image_id: str,
    repo_digests: list[str],
) -> bool:
    """Accept a registry digest or the exact local Image ID used offline."""

    if re.fullmatch(r".+@sha256:[0-9a-f]{64}", image_reference):
        return image_reference in repo_digests
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_reference):
        return image_reference == image_id
    return False


def deployment_container_evidence(
    container: dict[str, object],
    image: dict[str, object],
    *,
    commit_sha: str,
    image_reference: str,
    data_crawler_mount_type: str = "",
    data_crawler_mount_source: str = "",
    data_crawler_volume: str = "",
    expected_platform: str = "",
) -> dict[str, object]:
    container_id = str(container.get("Id") or "").strip()
    image_id = str(container.get("Image") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise SystemExit("deployment_identity_container_id_invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise SystemExit("deployment_identity_container_image_id_invalid")
    state = container.get("State") if isinstance(container.get("State"), dict) else {}
    if state.get("Running") is not True:
        raise SystemExit("deployment_identity_container_not_running")
    if str(image.get("Id") or "") != image_id:
        raise SystemExit("deployment_identity_image_id_mismatch")
    config = image.get("Config") if isinstance(image.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    if labels.get("org.opencontainers.image.revision") != commit_sha:
        raise SystemExit("deployment_identity_container_revision_mismatch")
    repo_digests = sorted(str(item) for item in image.get("RepoDigests") or [])
    if not immutable_image_reference_matches(
        image_reference,
        image_id=image_id,
        repo_digests=repo_digests,
    ):
        raise SystemExit("deployment_identity_container_digest_mismatch")
    platform_evidence = normalized_image_platform(image)
    if expected_platform and platform_evidence["platform"] != expected_platform:
        raise SystemExit("deployment_identity_image_platform_mismatch")
    evidence: dict[str, object] = {
        "container_id": container_id,
        "container_name": str(container.get("Name") or "").removeprefix("/"),
        "image_id": image_id,
        "image_reference": image_reference,
        "repo_digests": repo_digests,
        "platform": platform_evidence,
    }
    if data_crawler_mount_type or data_crawler_mount_source or data_crawler_volume:
        evidence["data_crawler_mount"] = data_crawler_mount_evidence(
            container,
            expected_type=data_crawler_mount_type,
            expected_source=data_crawler_mount_source,
            expected_volume=data_crawler_volume,
        )
    return evidence


def data_crawler_mount_evidence(
    container: dict[str, object],
    *,
    expected_type: str = "",
    expected_source: str = "",
    expected_volume: str = "",
) -> dict[str, object]:
    try:
        contract = normalize_mount_contract(
            expected_type,
            expected_source,
            legacy_volume=expected_volume,
        )
    except MountContractError as exc:
        raise SystemExit(f"deployment_identity_{exc}") from exc
    mounts = [
        item
        for item in container.get("Mounts") or []
        if isinstance(item, dict) and str(item.get("Destination") or "") == "/app/data"
    ]
    if len(mounts) != 1:
        raise SystemExit("deployment_identity_data_crawler_mount_required")
    mount = mounts[0]
    try:
        return inspect_mount_evidence(mount, contract, read_only=True)
    except MountContractError as exc:
        raise SystemExit(f"deployment_identity_{exc}") from exc


def _docker_inspect(kind: str, reference: str) -> dict[str, object]:
    completed = subprocess.run(
        ("docker", kind, "inspect", reference),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or f"deployment_identity_{kind}_inspect_failed")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise SystemExit(f"deployment_identity_{kind}_inspect_invalid")
    return payload[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("candidate", "production"))
    parser.add_argument("base_url")
    parser.add_argument("commit_sha")
    parser.add_argument("--compare")
    parser.add_argument("--container")
    parser.add_argument(
        "--data-crawler-volume",
        default=os.getenv("DATA_CRAWLER_SHARED_VOLUME", ""),
        help="Compatibility alias for a volume mount; prefer mount type/source.",
    )
    parser.add_argument(
        "--data-crawler-mount-type",
        default=os.getenv("DATA_CRAWLER_MOUNT_TYPE", ""),
    )
    parser.add_argument(
        "--data-crawler-mount-source",
        default=os.getenv("DATA_CRAWLER_MOUNT_SOURCE", ""),
    )
    parser.add_argument(
        "--target-platform",
        default=os.getenv("SMART_DATA_AGENT_TARGET_PLATFORM", ""),
    )
    args = parser.parse_args()
    sha = args.commit_sha.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("deployment_identity_commit_sha_invalid")
    if not str(args.container or "").strip():
        raise SystemExit("deployment_identity_container_required")
    try:
        mount_contract = normalize_mount_contract(
            args.data_crawler_mount_type,
            args.data_crawler_mount_source,
            legacy_volume=args.data_crawler_volume,
        )
    except MountContractError as exc:
        raise SystemExit(f"deployment_identity_{exc}") from exc
    target_platform = str(args.target_platform or "").strip().lower()
    if target_platform not in SUPPORTED_TARGET_PLATFORMS:
        raise SystemExit("deployment_identity_target_platform_invalid")
    base_url = args.base_url.rstrip("/")
    with urllib.request.urlopen(f"{base_url}/api/ready", timeout=15) as response:
        health = json.load(response)
    if health.get("ready") is not True:
        raise SystemExit("deployment_identity_runtime_not_ready")
    build = health.get("build") if isinstance(health.get("build"), dict) else {}
    identity = {key: str(build.get(key) or "") for key in IDENTITY_KEYS}
    if identity["commit_sha"] != sha:
        raise SystemExit("deployment_identity_commit_mismatch")
    if not re.fullmatch(r"(?:.+@)?sha256:[0-9a-f]{64}", identity["image_reference"]):
        raise SystemExit("deployment_identity_image_reference_not_immutable")
    for key in IDENTITY_KEYS[2:]:
        if not re.fullmatch(r"[0-9a-f]{64}", identity[key]):
            raise SystemExit(f"deployment_identity_hash_invalid:{key}")
    local_release = json.loads((ROOT / "artifacts" / "release" / "release-identity.json").read_text(encoding="utf-8"))
    assert_local_source_closure(identity, local_release)
    container_inspect = _docker_inspect("container", str(args.container))
    image_inspect = _docker_inspect("image", str(container_inspect.get("Image") or ""))
    container_evidence = deployment_container_evidence(
        container_inspect,
        image_inspect,
        commit_sha=sha,
        image_reference=identity["image_reference"],
        data_crawler_mount_type=mount_contract.mount_type,
        data_crawler_mount_source=mount_contract.source,
        expected_platform=target_platform,
    )
    if args.compare:
        previous = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        previous_identity = previous.get("identity") if isinstance(previous.get("identity"), dict) else {}
        differences = [key for key in IDENTITY_KEYS if str(previous_identity.get(key) or "") != identity[key]]
        if differences:
            raise SystemExit("deployment_identity_candidate_production_mismatch:" + ",".join(differences))
        assert_capability_compatibility(previous.get("capabilities"), health.get("capabilities"))
        previous_container = previous.get("container") if isinstance(previous.get("container"), dict) else {}
        if previous_container.get("platform") != container_evidence["platform"]:
            raise SystemExit("deployment_identity_candidate_production_platform_mismatch")
        if previous_container.get("image_id") != container_evidence["image_id"]:
            raise SystemExit("deployment_identity_candidate_production_image_id_mismatch")
        if previous_container.get("data_crawler_mount") != container_evidence.get("data_crawler_mount"):
            raise SystemExit("deployment_identity_candidate_production_data_crawler_mount_mismatch")
    runtime = health.get("runtime") if isinstance(health.get("runtime"), dict) else {}
    instance_id = str(runtime.get("instance_id") or "").strip()
    if not instance_id or len(instance_id) > 128:
        raise SystemExit("deployment_identity_runtime_instance_invalid")
    payload = {
        "schema_version": "smart-data-agent-deployment-identity/v2",
        "phase": args.phase,
        "base_url": base_url,
        "identity": identity,
        "runtime": {"instance_id": instance_id},
        "container": container_evidence,
        "capabilities": health.get("capabilities") or {},
        "capability_contract": normalized_capabilities(health.get("capabilities")),
    }
    output = ROOT / "artifacts" / "release" / f"{args.phase}-identity.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": "passed", **payload}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
