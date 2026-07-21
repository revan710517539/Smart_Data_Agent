from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class ArtifactObject:
    object_uri: str
    content_hash: str
    size_bytes: int


class LocalArtifactObjectStore:
    """Content-addressed local adapter for immutable acquisition artifacts.

    The database stores an opaque ``object://`` URI rather than a host path.
    Production can replace this adapter with S3/OSS without changing acquisition
    facts or API contracts.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        if root is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="smart-data-agent-artifacts-")
            root = self._temporary.name
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def put(self, tenant_id: str, content: bytes, suffix: str = ".bin") -> ArtifactObject:
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")
        digest = hashlib.sha256(content).hexdigest()
        tenant_segment = _safe_segment(tenant_id)
        normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        normalized_suffix = _safe_segment(normalized_suffix)[:16] or ".bin"
        directory = self.root / tenant_segment / digest[:2]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{digest}{normalized_suffix}"
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise RuntimeError("artifact_hash_collision")
        else:
            temporary = directory / f".{digest}.{os.getpid()}.tmp"
            try:
                with temporary.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return ArtifactObject(
            object_uri=f"object://local/{tenant_segment}/{digest[:2]}/{target.name}",
            content_hash=digest,
            size_bytes=len(content),
        )

    def read(self, tenant_id: str, object_uri: str, expected_hash: str) -> bytes:
        parsed = urlparse(object_uri)
        if parsed.scheme != "object" or parsed.netloc != "local":
            raise ValueError("unsupported_artifact_object_uri")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 3 or parts[0] != _safe_segment(tenant_id):
            raise PermissionError("artifact_tenant_mismatch")
        target = (self.root / parts[0] / parts[1] / parts[2]).resolve()
        if self.root not in target.parents:
            raise PermissionError("artifact_path_escape")
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise RuntimeError("artifact_integrity_check_failed")
        return content


class S3ArtifactObjectStore:
    """Content-addressed S3/OSS adapter with tenant prefixes and hash verification."""

    def __init__(
        self,
        bucket: str,
        *,
        region: str,
        endpoint_url: str | None = None,
        prefix: str = "smart-data-agent",
        kms_key_id: str | None = None,
        client=None,
    ) -> None:
        self.bucket = str(bucket or "").strip()
        self.region = str(region or "").strip()
        self.prefix = str(prefix or "smart-data-agent").strip("/")
        self.kms_key_id = str(kms_key_id or "").strip() or None
        if not self.bucket or not self.region or not self.prefix:
            raise ValueError("s3_object_store_configuration_required")
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - dependency contract.
                raise RuntimeError("boto3_required_for_s3_object_store") from exc
            client = boto3.client("s3", region_name=self.region, endpoint_url=endpoint_url or None)
        self.client = client

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def health(self) -> dict[str, object]:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return {"ready": True, "adapter": "s3", "bucket": self.bucket, "durable": True}
        except Exception as exc:
            return {"ready": False, "adapter": "s3", "error": type(exc).__name__, "durable": True}

    def put(self, tenant_id: str, content: bytes, suffix: str = ".bin") -> ArtifactObject:
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")
        digest = hashlib.sha256(content).hexdigest()
        tenant_segment = _safe_segment(tenant_id)
        normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        normalized_suffix = _safe_segment(normalized_suffix)[:16] or ".bin"
        key = f"{self.prefix}/{tenant_segment}/{digest[:2]}/{digest}{normalized_suffix}"
        try:
            existing = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if not _is_not_found(exc):
                raise
        else:
            metadata = existing.get("Metadata") or {}
            if metadata.get("sha256") != digest or int(existing.get("ContentLength") or -1) != len(content):
                raise RuntimeError("artifact_hash_collision")
            return ArtifactObject(f"s3://{self.bucket}/{key}", digest, len(content))
        put_args = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
            "ContentLength": len(content),
            "Metadata": {"sha256": digest, "tenant": tenant_segment},
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode("ascii"),
            "ServerSideEncryption": "aws:kms" if self.kms_key_id else "AES256",
        }
        if self.kms_key_id:
            put_args["SSEKMSKeyId"] = self.kms_key_id
        self.client.put_object(**put_args)
        return ArtifactObject(f"s3://{self.bucket}/{key}", digest, len(content))

    def read(self, tenant_id: str, object_uri: str, expected_hash: str) -> bytes:
        parsed = urlparse(object_uri)
        tenant_segment = _safe_segment(tenant_id)
        expected_prefix = f"{self.prefix}/{tenant_segment}/"
        key = parsed.path.lstrip("/")
        if parsed.scheme != "s3" or parsed.netloc != self.bucket or not key.startswith(expected_prefix):
            raise PermissionError("artifact_tenant_mismatch")
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        content = body.read() if hasattr(body, "read") else bytes(body)
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise RuntimeError("artifact_integrity_check_failed")
        return content


def _safe_segment(value: str) -> str:
    normalized = _SAFE_SEGMENT.sub("_", str(value or "").strip())[:120]
    if not normalized or normalized in {".", ".."}:
        raise ValueError("invalid_object_store_segment")
    return normalized


def _is_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str((response.get("Error") or {}).get("Code") or "")
        return code in {"404", "NoSuchKey", "NotFound"}
    return isinstance(exc, (FileNotFoundError, KeyError))
