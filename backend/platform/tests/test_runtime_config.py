import unittest
from unittest.mock import patch

from backend.platform.runtime_config import (
    RuntimeConfigurationError,
    cors_origin_for_request,
    load_runtime_config,
)
from backend.platform.security import AuthenticationError, make_session_token, resolve_request_context, verify_session_token


class RuntimeConfigTest(unittest.TestCase):
    def test_staging_development_login_does_not_require_a_shared_env_password(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_ENV": "staging",
                "SMART_DATA_AGENT_AUTH_MODE": "development",
            },
            clear=True,
        ):
            config = load_runtime_config()
        self.assertEqual(config.environment, "staging")
        self.assertEqual(config.auth_mode, "development")

    def test_insecure_production_profile_fails_closed(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_ENV": "production",
                "SMART_DATA_AGENT_AUTH_MODE": "development",
                "SMART_DATA_AGENT_DATA_WAREHOUSE": "json",
                "SMART_DATA_AGENT_SECRET_PROVIDER": "local",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeConfigurationError) as raised:
                load_runtime_config()
        message = str(raised.exception)
        self.assertIn("auth", message.lower())
        self.assertIn("mock/json", message)
        self.assertIn("MySQL", message)

    def test_explicit_secure_production_profile_is_accepted(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_ENV": "production",
                "SMART_DATA_AGENT_AUTH_MODE": "strict",
                "SMART_DATA_AGENT_AUTH_SECRET": "test-only-secret-with-32-characters-minimum",
                "SMART_DATA_AGENT_DATA_WAREHOUSE": "csv_object",
                "SMART_DATA_AGENT_DATABASE_URL": "mysql+pymysql://sda@db.example/smart_data_agent?ssl_mode=verify_identity&ssl_ca=/run/secrets/mysql_ca.pem",
                "SMART_DATA_AGENT_SECRET_PROVIDER": "kms",
                "SMART_DATA_AGENT_KMS_COMMAND": "vault-helper",
                "SMART_DATA_AGENT_OBJECT_STORE": "s3",
                "SMART_DATA_AGENT_OBJECT_BUCKET": "smart-data-agent-prod",
                "SMART_DATA_AGENT_OBJECT_REGION": "cn-east-1",
                "SMART_DATA_AGENT_CORS_ORIGINS": "https://analytics.example.com",
                "SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS": "idp.example.com,analytics.example.com",
                "SMART_DATA_AGENT_OIDC_ISSUER": "https://idp.example.com",
                "SMART_DATA_AGENT_OIDC_CLIENT_ID": "smart-data-agent",
                "SMART_DATA_AGENT_OIDC_CLIENT_SECRET": "test-client-secret",
                "SMART_DATA_AGENT_OIDC_AUTHORIZATION_ENDPOINT": "https://idp.example.com/authorize",
                "SMART_DATA_AGENT_OIDC_TOKEN_ENDPOINT": "https://idp.example.com/token",
                "SMART_DATA_AGENT_OIDC_JWKS_URI": "https://idp.example.com/jwks",
                "SMART_DATA_AGENT_OIDC_REDIRECT_URI": "https://analytics.example.com/api/auth/oidc/callback",
                "SMART_DATA_AGENT_REDIS_URL": "rediss://redis.example.com/0",
                "SMART_DATA_AGENT_CLAMAV_HOST": "clamav.example.com",
            },
            clear=True,
        ):
            config = load_runtime_config()
        self.assertTrue(config.is_production)
        self.assertEqual(config.cors_origins, ("https://analytics.example.com",))

    def test_cors_never_returns_wildcard_and_loopback_is_development_only(self) -> None:
        with patch.dict("os.environ", {"SMART_DATA_AGENT_ENV": "development"}, clear=True):
            development = load_runtime_config()
        self.assertEqual(cors_origin_for_request("http://localhost:5174", development), "http://localhost:5174")
        self.assertIsNone(cors_origin_for_request("https://attacker.example", development))

        with patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_ENV": "production",
                "SMART_DATA_AGENT_AUTH_MODE": "strict",
                "SMART_DATA_AGENT_AUTH_SECRET": "test-only-secret-with-32-characters-minimum",
                "SMART_DATA_AGENT_DATA_WAREHOUSE": "csv_object",
                "SMART_DATA_AGENT_DATABASE_URL": "mysql+pymysql://sda@db.example/smart_data_agent?ssl_mode=verify_identity&ssl_ca=/run/secrets/mysql_ca.pem",
                "SMART_DATA_AGENT_SECRET_PROVIDER": "kms",
                "SMART_DATA_AGENT_KMS_COMMAND": "vault-helper",
                "SMART_DATA_AGENT_OBJECT_STORE": "s3",
                "SMART_DATA_AGENT_OBJECT_BUCKET": "smart-data-agent-prod",
                "SMART_DATA_AGENT_OBJECT_REGION": "cn-east-1",
                "SMART_DATA_AGENT_CORS_ORIGINS": "https://analytics.example.com",
                "SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS": "idp.example.com,analytics.example.com",
                "SMART_DATA_AGENT_OIDC_ISSUER": "https://idp.example.com",
                "SMART_DATA_AGENT_OIDC_CLIENT_ID": "smart-data-agent",
                "SMART_DATA_AGENT_OIDC_CLIENT_SECRET": "test-client-secret",
                "SMART_DATA_AGENT_OIDC_AUTHORIZATION_ENDPOINT": "https://idp.example.com/authorize",
                "SMART_DATA_AGENT_OIDC_TOKEN_ENDPOINT": "https://idp.example.com/token",
                "SMART_DATA_AGENT_OIDC_JWKS_URI": "https://idp.example.com/jwks",
                "SMART_DATA_AGENT_OIDC_REDIRECT_URI": "https://analytics.example.com/api/auth/oidc/callback",
                "SMART_DATA_AGENT_REDIS_URL": "rediss://redis.example.com/0",
                "SMART_DATA_AGENT_CLAMAV_HOST": "clamav.example.com",
            },
            clear=True,
        ):
            production = load_runtime_config()
        self.assertEqual(
            cors_origin_for_request("https://analytics.example.com", production),
            "https://analytics.example.com",
        )
        self.assertIsNone(cors_origin_for_request("http://localhost:5173", production))

    def test_session_token_validates_issuer_audience_session_id_and_expiry(self) -> None:
        token = make_session_token(
            "u_admin",
            "tenant_demo",
            secret="test-secret",
            ttl_seconds=60,
            issued_at=1_700_000_000,
        )
        session = verify_session_token(token, secret="test-secret", now=1_700_000_001)
        self.assertEqual(session.issuer, "smart-data-agent")
        self.assertEqual(session.audience, "smart-data-agent-api")
        self.assertTrue(session.session_id)

        with patch.dict("os.environ", {"SMART_DATA_AGENT_AUTH_AUDIENCE": "another-api"}):
            with self.assertRaises(AuthenticationError):
                verify_session_token(token, secret="test-secret", now=1_700_000_001)

        with patch.dict("os.environ", {"SMART_DATA_AGENT_AUTH_MODE": "strict"}):
            no_expiry = make_session_token(
                "u_admin",
                "tenant_demo",
                secret="test-secret",
                issued_at=1_700_000_000,
            )
            with self.assertRaises(AuthenticationError):
                verify_session_token(no_expiry, secret="test-secret", now=1_700_000_001)

    def test_signed_session_accepts_encoded_header_and_websocket_tenant_query(self) -> None:
        secret = "test-only-secret-with-32-characters-minimum"
        with patch.dict("os.environ", {"SMART_DATA_AGENT_AUTH_SECRET": secret}, clear=True):
            token = make_session_token(
                "u_super_admin",
                "tenant:华兴银行",
                tenant_ids=("tenant:华兴银行", "tenant:广州银行"),
                secret=secret,
                ttl_seconds=60,
            )
            from_header = resolve_request_context(
                {"authorization": f"Bearer {token}", "x-tenant-id": "tenant%3A%E5%B9%BF%E5%B7%9E%E9%93%B6%E8%A1%8C"},
            )
            from_websocket_query = resolve_request_context(
                {"authorization": f"Bearer {token}"},
                params={"tenant_id": ["tenant:广州银行"]},
            )

        self.assertEqual(from_header.tenant_id, "tenant:广州银行")
        self.assertEqual(from_websocket_query.tenant_id, "tenant:广州银行")

    def test_super_admin_wildcard_session_allows_any_requested_tenant(self) -> None:
        secret = "test-only-secret-with-32-characters-minimum"
        with patch.dict("os.environ", {"SMART_DATA_AGENT_AUTH_SECRET": secret}, clear=True):
            token = make_session_token(
                "u_jinghaozhe_jk",
                "tenant:华兴银行",
                tenant_ids=("*", "tenant:华兴银行"),
                secret=secret,
                ttl_seconds=60,
            )
            switched = resolve_request_context(
                {"authorization": f"Bearer {token}", "x-tenant-id": "tenant%3A%E4%B8%89%E5%B3%A1%E9%93%B6%E8%A1%8C"},
            )
        self.assertEqual(switched.tenant_id, "tenant:三峡银行")
        self.assertEqual(switched.user_id, "u_jinghaozhe_jk")

    def test_strict_session_rejects_conflicting_user_tenant_and_cookie(self) -> None:
        secret = "test-only-secret-with-32-characters-minimum"
        with patch.dict("os.environ", {"SMART_DATA_AGENT_AUTH_SECRET": secret}, clear=True):
            token = make_session_token("u_admin", "tenant_a", tenant_ids=("tenant_a",), secret=secret, ttl_seconds=60)
            other = make_session_token("u_other", "tenant_b", tenant_ids=("tenant_b",), secret=secret, ttl_seconds=60)
            with self.assertRaisesRegex(AuthenticationError, "requested user") as user_error:
                resolve_request_context({"authorization": f"Bearer {token}", "x-user-id": "u_other"})
            with self.assertRaisesRegex(AuthenticationError, "tenant is not authorized") as tenant_error:
                resolve_request_context({"authorization": f"Bearer {token}", "x-tenant-id": "tenant_b"})
            with self.assertRaisesRegex(AuthenticationError, "different sessions") as session_error:
                resolve_request_context({"authorization": f"Bearer {token}", "cookie": f"sda_session={other}"})
        self.assertEqual(user_error.exception.error_code, "user_context_conflict")
        self.assertEqual(user_error.exception.status_code, 403)
        self.assertEqual(tenant_error.exception.error_code, "tenant_context_conflict")
        self.assertEqual(session_error.exception.error_code, "session_context_conflict")


if __name__ == "__main__":
    unittest.main()
