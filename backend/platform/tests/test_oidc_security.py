from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.platform.security import AuthenticationError, InMemoryOIDCTransactionStore, OIDCClient


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.payload if limit < 0 else self.payload[:limit]


class OIDCSecurityTest(unittest.TestCase):
    def test_authorization_code_pkce_nonce_signature_and_one_time_state(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
        jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
        environment = {
            "SMART_DATA_AGENT_OIDC_ISSUER": "https://idp.example.com",
            "SMART_DATA_AGENT_OIDC_CLIENT_ID": "smart-data-agent",
            "SMART_DATA_AGENT_OIDC_CLIENT_SECRET": "client-secret",
            "SMART_DATA_AGENT_OIDC_AUTHORIZATION_ENDPOINT": "https://idp.example.com/authorize",
            "SMART_DATA_AGENT_OIDC_TOKEN_ENDPOINT": "https://idp.example.com/token",
            "SMART_DATA_AGENT_OIDC_JWKS_URI": "https://idp.example.com/jwks",
            "SMART_DATA_AGENT_OIDC_REDIRECT_URI": "https://analytics.example.com/api/auth/oidc/callback",
            "SMART_DATA_AGENT_OIDC_REQUIRE_VERIFIED_EMAIL": "true",
        }
        with patch.dict("os.environ", environment, clear=True), patch(
            "backend.platform.security.oidc.validate_outbound_url",
            side_effect=lambda value: value,
        ):
            client = OIDCClient(InMemoryOIDCTransactionStore())
            started = client.start()
            query = parse_qs(urlparse(started["authorization_url"]).query)
            state = query["state"][0]
            nonce = query["nonce"][0]
            self.assertEqual(query["code_challenge_method"], ["S256"])
            self.assertTrue(query["code_challenge"][0])
            now = int(time.time())
            id_token = jwt.encode(
                {
                    "iss": "https://idp.example.com",
                    "sub": "employee-123",
                    "aud": "smart-data-agent",
                    "iat": now,
                    "exp": now + 300,
                    "nonce": nonce,
                    "email": "lina@bank.com",
                    "email_verified": True,
                },
                private_key,
                algorithm="RS256",
                headers={"kid": "key-1"},
            )
            responses = [_Response({"id_token": id_token}), _Response({"keys": [jwk]})]
            with patch("backend.platform.security.oidc.safe_urlopen", side_effect=responses):
                identity = client.exchange_code("one-time-code", state)

            self.assertEqual(identity["email"], "lina@bank.com")
            self.assertEqual(identity["subject"], "employee-123")
            with self.assertRaisesRegex(AuthenticationError, "oidc_transaction_unknown_or_consumed"):
                client.exchange_code("replayed-code", state)

    def test_oidc_transaction_rejects_unknown_state(self) -> None:
        store = InMemoryOIDCTransactionStore()
        store.create("https://analytics.example.com/callback", now=1_000)
        with self.assertRaisesRegex(AuthenticationError, "unknown_or_consumed"):
            store.consume("attacker-state", now=1_001)


if __name__ == "__main__":
    unittest.main()
