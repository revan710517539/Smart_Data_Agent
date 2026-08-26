from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.platform.database.mysql import mysql_tls_configured


class RuntimeConfigurationError(RuntimeError):
    """Raised when the process would start with an unsafe runtime profile."""


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    auth_mode: str
    data_warehouse: str
    cors_origins: tuple[str, ...]
    database_url: str
    secret_provider: str
    object_store: str
    object_bucket: str
    object_region: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_authorization_endpoint: str
    oidc_token_endpoint: str
    oidc_jwks_uri: str
    oidc_redirect_uri: str
    development_mysql_compatible_versions: tuple[str, ...] = ()
    public_origin: str = ""
    wss_enabled: bool = False
    asr_enabled: bool = False
    embedded_worker_enabled: bool = True
    data_crawler_root: str = "/app/data"
    data_crawler_root_configured: bool = False
    image_reference: str = ""
    auto_migrate: bool = True
    allow_http_model_egress: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_runtime_config() -> RuntimeConfig:
    environment = os.getenv("SMART_DATA_AGENT_ENV", "development").strip().lower()
    if environment not in {"development", "test", "staging", "production"}:
        raise RuntimeConfigurationError(f"Unsupported SMART_DATA_AGENT_ENV: {environment}")
    origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv("SMART_DATA_AGENT_CORS_ORIGINS", "").split(",")
        if origin.strip()
    )
    production = environment == "production"
    public_origin = os.getenv("SMART_DATA_AGENT_PUBLIC_ORIGIN", "").strip().rstrip("/")
    configured_data_crawler_root = (
        os.getenv("SMART_DATA_AGENT_DATA_CRAWLER_ROOT", "").strip()
        or os.getenv("DATA_CRAWLER_OUTPUT_DIR", "").strip()
    )
    config = RuntimeConfig(
        environment=environment,
        auth_mode=os.getenv("SMART_DATA_AGENT_AUTH_MODE", "development").strip().lower(),
        data_warehouse=os.getenv("SMART_DATA_AGENT_DATA_WAREHOUSE", "json").strip().lower(),
        cors_origins=origins,
        database_url=os.getenv("SMART_DATA_AGENT_DATABASE_URL", "").strip(),
        secret_provider=os.getenv("SMART_DATA_AGENT_SECRET_PROVIDER", "local").strip().lower(),
        object_store=os.getenv("SMART_DATA_AGENT_OBJECT_STORE", "local").strip().lower(),
        object_bucket=os.getenv("SMART_DATA_AGENT_OBJECT_BUCKET", "").strip(),
        object_region=os.getenv("SMART_DATA_AGENT_OBJECT_REGION", "").strip(),
        oidc_issuer=os.getenv("SMART_DATA_AGENT_OIDC_ISSUER", "").strip(),
        oidc_client_id=os.getenv("SMART_DATA_AGENT_OIDC_CLIENT_ID", "").strip(),
        oidc_authorization_endpoint=os.getenv("SMART_DATA_AGENT_OIDC_AUTHORIZATION_ENDPOINT", "").strip(),
        oidc_token_endpoint=os.getenv("SMART_DATA_AGENT_OIDC_TOKEN_ENDPOINT", "").strip(),
        oidc_jwks_uri=os.getenv("SMART_DATA_AGENT_OIDC_JWKS_URI", "").strip(),
        oidc_redirect_uri=os.getenv("SMART_DATA_AGENT_OIDC_REDIRECT_URI", "").strip(),
        development_mysql_compatible_versions=tuple(
            version.strip()
            for version in os.getenv("SMART_DATA_AGENT_DEVELOPMENT_MYSQL_COMPATIBLE_VERSIONS", "").split(",")
            if version.strip()
        ),
        public_origin=public_origin,
        wss_enabled=strict_environment_boolean(
            "SMART_DATA_AGENT_WSS_ENABLED",
            default=not production,
            required=production,
        ),
        asr_enabled=strict_environment_boolean(
            "SMART_DATA_AGENT_ASR_ENABLED",
            default=not production,
            required=production,
        ),
        embedded_worker_enabled=strict_environment_boolean(
            "SMART_DATA_AGENT_EMBEDDED_WORKER",
            default=not production,
            required=production,
        ),
        data_crawler_root=configured_data_crawler_root or "/app/data",
        data_crawler_root_configured=bool(configured_data_crawler_root),
        image_reference=os.getenv("SMART_DATA_AGENT_IMAGE_REFERENCE", "").strip(),
        auto_migrate=strict_environment_boolean(
            "SMART_DATA_AGENT_AUTO_MIGRATE",
            default=not production,
            required=production,
        ),
        allow_http_model_egress=strict_environment_boolean(
            "SMART_DATA_AGENT_ALLOW_HTTP_MODEL_EGRESS",
            default=False,
            required=production,
        ),
    )
    validate_runtime_config(config)
    return config


def validate_runtime_config(config: RuntimeConfig) -> None:
    if config.auth_mode not in {"development", "strict"}:
        raise RuntimeConfigurationError(f"Unsupported auth mode: {config.auth_mode}")
    for origin in config.cors_origins:
        parsed = urlparse(origin)
        if origin == "*" or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeConfigurationError(f"Invalid CORS origin: {origin}")
    if config.database_url and not config.database_url.lower().startswith(("mysql://", "mysql+pymysql://")):
        raise RuntimeConfigurationError("SMART_DATA_AGENT_DATABASE_URL must point to MySQL")
    invalid_mysql_versions = [
        version
        for version in config.development_mysql_compatible_versions
        if not all(part.isdigit() for part in version.split(".")) or len(version.split(".")) != 3
    ]
    if invalid_mysql_versions:
        raise RuntimeConfigurationError(
            "SMART_DATA_AGENT_DEVELOPMENT_MYSQL_COMPATIBLE_VERSIONS must contain exact numeric versions"
        )
    if config.development_mysql_compatible_versions and config.environment not in {"development", "test"}:
        raise RuntimeConfigurationError(
            "SMART_DATA_AGENT_DEVELOPMENT_MYSQL_COMPATIBLE_VERSIONS is forbidden outside development/test"
        )
    if config.public_origin:
        parsed_public_origin = urlparse(config.public_origin)
        if parsed_public_origin.scheme not in {"http", "https"} or not parsed_public_origin.netloc:
            raise RuntimeConfigurationError("SMART_DATA_AGENT_PUBLIC_ORIGIN must be an absolute HTTP(S) origin")
        if parsed_public_origin.path not in {"", "/"} or parsed_public_origin.params or parsed_public_origin.query or parsed_public_origin.fragment:
            raise RuntimeConfigurationError("SMART_DATA_AGENT_PUBLIC_ORIGIN must not contain a path, query, or fragment")
    if config.asr_enabled and not config.wss_enabled:
        raise RuntimeConfigurationError("SMART_DATA_AGENT_ASR_ENABLED=true requires SMART_DATA_AGENT_WSS_ENABLED=true")
    if not config.is_production:
        return
    errors: list[str] = []
    if config.auto_migrate:
        errors.append("SMART_DATA_AGENT_AUTO_MIGRATE must be false; migrations run as an explicit release job")
    if config.allow_http_model_egress:
        errors.append("SMART_DATA_AGENT_ALLOW_HTTP_MODEL_EGRESS must be false in production")
    if config.auth_mode != "strict":
        errors.append("SMART_DATA_AGENT_AUTH_MODE must be strict")
    if config.data_warehouse in {"json", "mock", "json_mock_warehouse"}:
        errors.append("mock/json data warehouse is forbidden")
    if not config.cors_origins:
        errors.append("SMART_DATA_AGENT_CORS_ORIGINS must be explicit")
    elif any(urlparse(origin).scheme != "https" for origin in config.cors_origins):
        errors.append("production CORS origins must use https")
    if not config.public_origin:
        errors.append("SMART_DATA_AGENT_PUBLIC_ORIGIN must be explicit")
    elif urlparse(config.public_origin).scheme != "https":
        errors.append("SMART_DATA_AGENT_PUBLIC_ORIGIN must use https")
    elif config.public_origin not in config.cors_origins:
        errors.append("SMART_DATA_AGENT_PUBLIC_ORIGIN must be included in SMART_DATA_AGENT_CORS_ORIGINS")
    if not config.data_crawler_root_configured:
        errors.append("SMART_DATA_AGENT_DATA_CRAWLER_ROOT must be explicit")
    if config.secret_provider != "kms":
        errors.append("SMART_DATA_AGENT_SECRET_PROVIDER must be kms")
    if not os.getenv("SMART_DATA_AGENT_KMS_COMMAND", "").strip():
        errors.append("SMART_DATA_AGENT_KMS_COMMAND is required for KMS encryption")
    if config.object_store not in {"s3", "oss", "s3_compatible"}:
        errors.append("SMART_DATA_AGENT_OBJECT_STORE must be s3/oss compatible")
    if not config.object_bucket or not config.object_region:
        errors.append("SMART_DATA_AGENT_OBJECT_BUCKET and SMART_DATA_AGENT_OBJECT_REGION are required")
    if not config.database_url.lower().startswith(("mysql://", "mysql+pymysql://")):
        errors.append("SMART_DATA_AGENT_DATABASE_URL must point to MySQL")
    elif not mysql_tls_configured(config.database_url):
        errors.append("SMART_DATA_AGENT_DATABASE_URL must enforce MySQL TLS")
    auth_secret = os.getenv("SMART_DATA_AGENT_AUTH_SECRET", "").strip()
    if len(auth_secret) < 32:
        errors.append("SMART_DATA_AGENT_AUTH_SECRET must contain at least 32 characters")
    oidc_values = {
        "SMART_DATA_AGENT_OIDC_ISSUER": config.oidc_issuer,
        "SMART_DATA_AGENT_OIDC_CLIENT_ID": config.oidc_client_id,
        "SMART_DATA_AGENT_OIDC_AUTHORIZATION_ENDPOINT": config.oidc_authorization_endpoint,
        "SMART_DATA_AGENT_OIDC_TOKEN_ENDPOINT": config.oidc_token_endpoint,
        "SMART_DATA_AGENT_OIDC_JWKS_URI": config.oidc_jwks_uri,
        "SMART_DATA_AGENT_OIDC_REDIRECT_URI": config.oidc_redirect_uri,
        "SMART_DATA_AGENT_OIDC_CLIENT_SECRET": os.getenv("SMART_DATA_AGENT_OIDC_CLIENT_SECRET", "").strip(),
    }
    missing_oidc = [name for name, value in oidc_values.items() if not value]
    if missing_oidc:
        errors.append("OIDC configuration is incomplete: " + ",".join(missing_oidc))
    if not os.getenv("SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS", "").strip():
        errors.append("SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS must include IdP and provider hosts")
    redis_url = os.getenv("SMART_DATA_AGENT_REDIS_URL", "").strip()
    if not redis_url:
        errors.append("SMART_DATA_AGENT_REDIS_URL is required")
    elif urlparse(redis_url).scheme != "rediss":
        errors.append("SMART_DATA_AGENT_REDIS_URL must use rediss:// in production")
    object_endpoint = os.getenv("SMART_DATA_AGENT_OBJECT_ENDPOINT", "").strip()
    if object_endpoint and urlparse(object_endpoint).scheme != "https":
        errors.append("SMART_DATA_AGENT_OBJECT_ENDPOINT must use https")
    if not os.getenv("SMART_DATA_AGENT_CLAMAV_HOST", "").strip():
        errors.append("SMART_DATA_AGENT_CLAMAV_HOST is required for document malware scanning")
    if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", config.image_reference):
        errors.append("SMART_DATA_AGENT_IMAGE_REFERENCE must be an immutable repository@sha256 digest")
    for name in (
        "SMART_DATA_AGENT_SOURCE_ARCHIVE_SHA256",
        "SMART_DATA_AGENT_DEPENDENCY_LOCK_SHA256",
        "SMART_DATA_AGENT_FRONTEND_ASSETS_SHA256",
        "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_SHA256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", os.getenv(name, "").strip()):
            errors.append(f"{name} must be a 64-character SHA-256 identity")
    if errors:
        raise RuntimeConfigurationError("Unsafe production configuration: " + "; ".join(errors))


def strict_environment_boolean(name: str, *, default: bool, required: bool = False) -> bool:
    """Read an operational boolean without accepting ambiguous aliases.

    Deployment flags are part of the release contract.  Values such as ``1``,
    ``yes`` and an empty string must not silently change production behavior.
    """

    raw = os.getenv(name)
    if raw is None:
        if required:
            raise RuntimeConfigurationError(f"{name} must be explicitly set to true or false")
        return default
    value = raw.strip()
    if value not in {"true", "false"}:
        raise RuntimeConfigurationError(f"{name} must be exactly true or false")
    return value == "true"


def runtime_capability_matrix(config: RuntimeConfig) -> dict[str, dict[str, object]]:
    """Return secret-free configuration and dependency readiness evidence."""

    crawler_root = Path(config.data_crawler_root)
    crawler_dependency_ready = crawler_root.is_dir() and os.access(crawler_root, os.R_OK)
    public_configured = bool(config.public_origin) and config.public_origin in config.cors_origins
    database_configured = bool(config.database_url)
    crawler_ready = crawler_dependency_ready or not config.is_production
    public_ready = public_configured or not config.is_production
    database_ready = database_configured or not config.is_production
    authentication_ready = config.auth_mode == "strict" if config.is_production else bool(config.auth_mode)
    return {
        "public_origin": {
            "configured": bool(config.public_origin),
            "enabled": bool(config.public_origin),
            "ready": public_ready,
            "status": "ready" if public_ready else "not_configured",
            "origin": config.public_origin,
        },
        "wss": {
            "configured": True,
            "enabled": config.wss_enabled,
            "ready": True,
            "status": "enabled" if config.wss_enabled else "disabled",
        },
        "asr": {
            "configured": True,
            "enabled": config.asr_enabled,
            "ready": not config.asr_enabled or config.wss_enabled,
            "status": "enabled" if config.asr_enabled else "disabled",
            "dependency": "wss",
        },
        "data_crawler": {
            "configured": config.data_crawler_root_configured,
            "enabled": bool(config.data_crawler_root),
            "ready": crawler_ready,
            "status": "ready" if crawler_dependency_ready else "optional_in_non_production" if not config.is_production else "mount_unavailable",
        },
        "database": {
            "configured": database_configured,
            "enabled": database_configured,
            "ready": database_ready,
            "status": "configured" if database_configured else "optional_in_non_production" if not config.is_production else "not_configured",
        },
        "authentication": {
            "configured": bool(config.auth_mode),
            "enabled": True,
            "ready": authentication_ready,
            "status": config.auth_mode,
        },
        "embedded_worker": {
            "configured": True,
            "enabled": config.embedded_worker_enabled,
            "ready": True,
            "status": "enabled" if config.embedded_worker_enabled else "disabled",
        },
    }


def runtime_capability_summary(config: RuntimeConfig) -> dict[str, object]:
    """Return the startup capability contract without endpoints, paths or secrets."""

    return {
        "schema_version": "smart-data-agent-runtime-capabilities/v1",
        "environment": config.environment,
        "public_origin_configured": bool(config.public_origin),
        "wss_enabled": config.wss_enabled,
        "asr_enabled": config.asr_enabled,
        "crawler_root_configured": config.data_crawler_root_configured,
        "database_configured": bool(config.database_url),
        "authentication_strict": config.auth_mode == "strict",
        "embedded_worker_enabled": config.embedded_worker_enabled,
    }


def emit_runtime_capability_summary(config: RuntimeConfig) -> None:
    print(
        "Smart Data Agent runtime capabilities "
        + json.dumps(runtime_capability_summary(config), ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def cors_origin_for_request(origin: str | None, config: RuntimeConfig) -> str | None:
    if not origin:
        return None
    normalized = origin.rstrip("/")
    if normalized in config.cors_origins:
        return normalized
    if config.environment in {"development", "test"}:
        parsed = urlparse(normalized)
        if parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return normalized
    return None
