from __future__ import annotations

import os
from dataclasses import dataclass
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
    if not config.is_production:
        return
    errors: list[str] = []
    if config.auth_mode != "strict":
        errors.append("SMART_DATA_AGENT_AUTH_MODE must be strict")
    if config.data_warehouse in {"json", "mock", "json_mock_warehouse"}:
        errors.append("mock/json data warehouse is forbidden")
    if not config.cors_origins:
        errors.append("SMART_DATA_AGENT_CORS_ORIGINS must be explicit")
    elif any(urlparse(origin).scheme != "https" for origin in config.cors_origins):
        errors.append("production CORS origins must use https")
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
    if errors:
        raise RuntimeConfigurationError("Unsafe production configuration: " + "; ".join(errors))


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
