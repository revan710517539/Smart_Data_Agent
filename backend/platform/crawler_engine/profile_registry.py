from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from .contracts import CrawlerRequest


_PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")


@dataclass(frozen=True)
class CrawlerProfileDescriptor:
    """Stable identity and management metadata for one independently maintained crawler."""

    profile_id: str
    system_id: str
    display_name: str
    version: int
    supported_operations: tuple[str, ...]
    maintainer: str
    description: str = ""

    def __post_init__(self) -> None:
        _validate_identifier(self.profile_id, "crawler_profile_id_invalid")
        _validate_identifier(self.system_id, "crawler_system_id_invalid")
        if not self.display_name.strip():
            raise ValueError("crawler_profile_display_name_required")
        if self.version < 1:
            raise ValueError("crawler_profile_version_invalid")
        if not self.supported_operations:
            raise ValueError("crawler_profile_operations_required")
        if not self.maintainer.strip():
            raise ValueError("crawler_profile_maintainer_required")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supported_operations"] = list(self.supported_operations)
        return payload


@dataclass(frozen=True)
class CrawlerProfileContext:
    page: Any = field(repr=False)
    request: CrawlerRequest
    connection: dict[str, Any] = field(repr=False)
    step: dict[str, Any]


@dataclass(frozen=True)
class CrawlerProfileCollection:
    rows: tuple[dict[str, Any], ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class CrawlerSystemProfile(Protocol):
    descriptor: CrawlerProfileDescriptor

    def collect(self, context: CrawlerProfileContext) -> CrawlerProfileCollection:
        """Collect rows without owning browser startup, authentication, or persistence."""


class CrawlerProfileRegistry:
    """Unified catalog and dispatcher for system-isolated crawler profiles."""

    def __init__(self) -> None:
        self._profiles: dict[str, CrawlerSystemProfile] = {}
        self._aliases: dict[str, str] = {}

    def register(self, profile: CrawlerSystemProfile, *, aliases: tuple[str, ...] = ()) -> None:
        descriptor = profile.descriptor
        profile_id = descriptor.profile_id
        if profile_id in self._profiles or profile_id in self._aliases:
            raise ValueError(f"crawler_profile_already_registered:{profile_id}")
        for alias in aliases:
            _validate_identifier(alias, "crawler_profile_alias_invalid")
            if alias in self._profiles or alias in self._aliases:
                raise ValueError(f"crawler_profile_alias_already_registered:{alias}")
        self._profiles[profile_id] = profile
        self._aliases.update({alias: profile_id for alias in aliases})

    def get(self, profile_id_or_alias: str) -> CrawlerSystemProfile:
        key = str(profile_id_or_alias or "").strip()
        profile_id = self._aliases.get(key, key)
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"crawler_profile_not_registered:{key}") from exc

    def list_profiles(self, *, system_id: str | None = None) -> tuple[CrawlerProfileDescriptor, ...]:
        descriptors = [profile.descriptor for profile in self._profiles.values()]
        if system_id:
            descriptors = [item for item in descriptors if item.system_id == system_id]
        return tuple(sorted(descriptors, key=lambda item: (item.system_id, item.profile_id)))

    def collect(self, profile_id_or_alias: str, context: CrawlerProfileContext) -> CrawlerProfileCollection:
        profile = self.get(profile_id_or_alias)
        descriptor = profile.descriptor
        operation = context.request.operation_type.value
        if operation not in descriptor.supported_operations:
            raise ValueError(f"crawler_profile_operation_not_supported:{descriptor.profile_id}:{operation}")
        result = profile.collect(context)
        if not isinstance(result, CrawlerProfileCollection):
            raise TypeError(f"crawler_profile_result_invalid:{descriptor.profile_id}")
        rows = tuple(dict(row) for row in result.rows)
        metadata = {
            **result.metadata,
            "crawler_profile": descriptor.to_dict(),
        }
        return CrawlerProfileCollection(rows=rows, metadata=metadata)


@lru_cache(maxsize=1)
def get_default_crawler_profile_registry() -> CrawlerProfileRegistry:
    from .systems import built_in_crawler_profiles

    registry = CrawlerProfileRegistry()
    for profile, aliases in built_in_crawler_profiles():
        registry.register(profile, aliases=aliases)
    return registry


def _validate_identifier(value: str, error: str) -> None:
    if not _PROFILE_ID_PATTERN.fullmatch(str(value or "")):
        raise ValueError(error)
