#!/usr/bin/env python3
"""Normalize and inspect the cross-project Data Crawler mount identity."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import PurePosixPath
import re
from typing import Mapping


VOLUME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
SUPPORTED_MOUNT_TYPES = {"bind", "volume"}


class MountContractError(ValueError):
    """A stable, non-secret mount-contract failure."""


@dataclass(frozen=True)
class DataCrawlerMountContract:
    mount_type: str
    source: str

    def docker_spec(self, *, read_only: bool) -> str:
        options = [f"type={self.mount_type}", f"src={self.source}", "dst=/app/data"]
        if read_only:
            options.append("readonly")
        if self.mount_type == "volume":
            options.append("volume-nocopy")
        return ",".join(options)


def normalize_mount_contract(
    mount_type: str = "",
    mount_source: str = "",
    *,
    legacy_volume: str = "",
    require_bind_directory: bool = False,
) -> DataCrawlerMountContract:
    normalized_type = str(mount_type or "").strip().lower()
    normalized_source = str(mount_source or "").strip()
    legacy = str(legacy_volume or "").strip()
    if not normalized_type and not normalized_source and legacy:
        normalized_type = "volume"
        normalized_source = legacy
    if normalized_type not in SUPPORTED_MOUNT_TYPES:
        raise MountContractError("data_crawler_mount_type_invalid")
    if not normalized_source:
        raise MountContractError("data_crawler_mount_source_required")
    if legacy and (normalized_type != "volume" or normalized_source != legacy):
        raise MountContractError("data_crawler_legacy_volume_conflict")
    if normalized_type == "volume":
        if VOLUME_PATTERN.fullmatch(normalized_source) is None:
            raise MountContractError("data_crawler_volume_name_invalid")
    else:
        if not normalized_source.startswith("/") or normalized_source == "/":
            raise MountContractError("data_crawler_bind_source_invalid")
        if "," in normalized_source or any(ord(char) < 32 for char in normalized_source):
            raise MountContractError("data_crawler_bind_source_invalid")
        parsed_source = PurePosixPath(normalized_source)
        if str(parsed_source) != normalized_source or ".." in parsed_source.parts:
            raise MountContractError("data_crawler_bind_source_not_normalized")
        if require_bind_directory and not os.path.isdir(normalized_source):
            raise MountContractError("data_crawler_bind_source_unavailable")
    return DataCrawlerMountContract(normalized_type, normalized_source)


def inspect_mount_evidence(
    mount: Mapping[str, object],
    contract: DataCrawlerMountContract,
    *,
    read_only: bool,
) -> dict[str, object]:
    actual_type = str(mount.get("Type") or "").strip().lower()
    if actual_type != contract.mount_type:
        raise MountContractError("data_crawler_mount_type_mismatch")
    actual_source = str(
        mount.get("Source") if contract.mount_type == "bind" else mount.get("Name")
        or ""
    ).strip()
    if actual_source != contract.source:
        raise MountContractError("data_crawler_mount_source_mismatch")
    expected_rw = not read_only
    if mount.get("RW") is not expected_rw:
        suffix = "not_read_only" if read_only else "not_writable"
        raise MountContractError(f"data_crawler_mount_{suffix}")
    return {
        "type": contract.mount_type,
        "source": contract.source,
        "destination": "/app/data",
        "read_only": read_only,
    }
