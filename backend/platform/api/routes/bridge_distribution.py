from __future__ import annotations

from functools import lru_cache
import hashlib
from http import HTTPStatus
import io
import json
from pathlib import Path
from typing import Any
import zipfile

from backend.platform.api.support import send_route_exception


BRIDGE_DISTRIBUTION_VERSION = "1.1.0"
PACKAGE_PATH = "/api/integrations/bridge/distribution/package"
CHECKSUM_PATH = "/api/integrations/bridge/distribution/package.sha256"
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_PACKAGE_ROOTS = (
    Path("integrations/smart-data-agent-bridge"),
    Path("integrations/workbuddy-smart-data-report"),
    Path("integrations/workbuddy-smart-data-report-marketplace"),
    Path("integrations/codex-smart-data-agent-bridge"),
    Path("integrations/qwork-smart-data-agent-bridge"),
)
_ALLOWED_SUFFIXES = {"", ".cmd", ".json", ".md", ".ps1", ".py", ".sh"}
_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def handle_bridge_distribution_manifest_get(handler: Any, query: str) -> None:
    del query
    try:
        bundle, digest = build_bridge_distribution_bundle()
        handler._send_json(
            {
                "schema_version": "sda_bridge_distribution_v1",
                "version": BRIDGE_DISTRIBUTION_VERSION,
                "package": {
                    "path": PACKAGE_PATH,
                    "checksum_path": CHECKSUM_PATH,
                    "sha256": digest,
                    "bytes": len(bundle),
                    "content_type": "application/zip",
                },
                "channels": ["workbuddy", "codex", "qwork"],
                "platforms": ["macos", "windows"],
                "requirements": {
                    "server_scheme": "https",
                    "python": ">=3.10",
                    "administrator": False,
                },
                "authorization": "browser_device_approval",
                "secret_storage": {"macos": "Keychain", "windows": "DPAPI"},
                "data_flow": "authorized bounded reads, governed sync/actions, review-only learning evidence",
            },
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_distribution_package_get(handler: Any, query: str) -> None:
    del query
    try:
        bundle, digest = build_bridge_distribution_bundle()
        handler._send_bytes(
            bundle,
            content_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="smart-data-agent-bridge-{BRIDGE_DISTRIBUTION_VERSION}.zip"',
                "ETag": f'"sha256:{digest}"',
                "X-Content-SHA256": digest,
            },
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_distribution_checksum_get(handler: Any, query: str) -> None:
    del query
    try:
        _, digest = build_bridge_distribution_bundle()
        body = f"{digest}  smart-data-agent-bridge-{BRIDGE_DISTRIBUTION_VERSION}.zip\n".encode("ascii")
        handler._send_bytes(
            body,
            content_type="text/plain; charset=utf-8",
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


@lru_cache(maxsize=1)
def build_bridge_distribution_bundle() -> tuple[bytes, str]:
    files = _distribution_files()
    entries = [
        {
            "path": path.as_posix(),
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in files
    ]
    manifest = json.dumps(
        {
            "schema_version": "sda_bridge_package_v1",
            "version": BRIDGE_DISTRIBUTION_VERSION,
            "files": entries,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        _write_zip_entry(archive, Path("MANIFEST.json"), manifest, executable=False)
        for path, content in files:
            executable = path.suffix in {"", ".sh"} and (path.name == "SDA" or path.name == "sda-report" or path.suffix == ".sh")
            _write_zip_entry(archive, path, content, executable=executable)
    bundle = buffer.getvalue()
    return bundle, hashlib.sha256(bundle).hexdigest()


def _distribution_files() -> list[tuple[Path, bytes]]:
    selected: list[tuple[Path, bytes]] = []
    total_bytes = 0
    project_root = _PROJECT_ROOT.resolve()
    for relative_root in _PACKAGE_ROOTS:
        source_root = (_PROJECT_ROOT / relative_root).resolve()
        if project_root not in source_root.parents or not source_root.is_dir():
            raise FileNotFoundError(f"bridge_distribution_source_missing:{relative_root.as_posix()}")
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            relative = source.relative_to(project_root)
            if any(part in {"__pycache__", ".DS_Store"} for part in relative.parts):
                continue
            if source.suffix.lower() not in _ALLOWED_SUFFIXES:
                raise ValueError(f"bridge_distribution_file_type_not_allowed:{relative.as_posix()}")
            content = source.read_bytes()
            if len(content) > 1024 * 1024:
                raise ValueError(f"bridge_distribution_file_too_large:{relative.as_posix()}")
            total_bytes += len(content)
            if total_bytes > 4 * 1024 * 1024:
                raise ValueError("bridge_distribution_package_too_large")
            selected.append((relative, content))
    if not selected:
        raise FileNotFoundError("bridge_distribution_empty")
    return selected


def _write_zip_entry(archive: zipfile.ZipFile, path: Path, content: bytes, *, executable: bool) -> None:
    info = zipfile.ZipInfo(path.as_posix(), _ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = ((0o755 if executable else 0o644) & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content)
