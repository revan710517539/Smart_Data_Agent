from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

import certifi
import jwt

from backend.platform.storage import connect_sqlite

from .egress import safe_urlopen, validate_outbound_url
from .secrets import decrypt_secret, encrypt_secret
from .session import AuthenticationError


@dataclass(frozen=True)
class OIDCTransaction:
    transaction_id: str
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    expires_at: int


class InMemoryOIDCTransactionStore:
    def __init__(self) -> None:
        self._transactions: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        return None

    def create(self, redirect_uri: str, ttl_seconds: int = 300, now: int | None = None) -> OIDCTransaction:
        transaction, record = _new_transaction(redirect_uri, ttl_seconds, now)
        self._transactions[_state_hash(transaction.state)] = record
        return transaction

    def consume(self, state: str, now: int | None = None) -> OIDCTransaction:
        current = int(time.time() if now is None else now)
        record = self._transactions.get(_state_hash(state))
        transaction = _validate_transaction_record(record, state, current)
        record["consumed_at"] = current
        return transaction


class SQLiteOIDCTransactionStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = connect_sqlite(str(db_path))
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def create(self, redirect_uri: str, ttl_seconds: int = 300, now: int | None = None) -> OIDCTransaction:
        transaction, record = _new_transaction(redirect_uri, ttl_seconds, now)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_oidc_transactions(
                    transaction_id, state_hash, nonce, code_verifier_secret,
                    redirect_uri, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction.transaction_id,
                    record["state_hash"],
                    transaction.nonce,
                    encrypt_secret(transaction.code_verifier),
                    transaction.redirect_uri,
                    record["created_at"],
                    transaction.expires_at,
                ),
            )
        return transaction

    def consume(self, state: str, now: int | None = None) -> OIDCTransaction:
        current = int(time.time() if now is None else now)
        state_hash = _state_hash(state)
        row = self._conn.execute(
            "SELECT * FROM platform_oidc_transactions WHERE state_hash = ?",
            (state_hash,),
        ).fetchone()
        record = dict(row) if row else None
        if record:
            record["code_verifier"] = decrypt_secret(str(record.pop("code_verifier_secret")))
        transaction = _validate_transaction_record(record, state, current)
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_oidc_transactions SET consumed_at = ?
                WHERE state_hash = ? AND consumed_at IS NULL AND expires_at > ?
                """,
                (current, state_hash, current),
            )
            if cursor.rowcount != 1:
                raise AuthenticationError("oidc_transaction_already_consumed")
        return transaction


class OIDCClient:
    def __init__(self, transaction_store: Any) -> None:
        self.transaction_store = transaction_store
        self.issuer = os.getenv("SMART_DATA_AGENT_OIDC_ISSUER", "").strip().rstrip("/")
        self.client_id = os.getenv("SMART_DATA_AGENT_OIDC_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("SMART_DATA_AGENT_OIDC_CLIENT_SECRET", "").strip()
        self.authorization_endpoint = os.getenv("SMART_DATA_AGENT_OIDC_AUTHORIZATION_ENDPOINT", "").strip()
        self.token_endpoint = os.getenv("SMART_DATA_AGENT_OIDC_TOKEN_ENDPOINT", "").strip()
        self.jwks_uri = os.getenv("SMART_DATA_AGENT_OIDC_JWKS_URI", "").strip()
        self.redirect_uri = os.getenv("SMART_DATA_AGENT_OIDC_REDIRECT_URI", "").strip()

    def close(self) -> None:
        close = getattr(self.transaction_store, "close", None)
        if callable(close):
            close()

    def validate_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("issuer", self.issuer),
                ("client_id", self.client_id),
                ("authorization_endpoint", self.authorization_endpoint),
                ("token_endpoint", self.token_endpoint),
                ("jwks_uri", self.jwks_uri),
                ("redirect_uri", self.redirect_uri),
            )
            if not value
        ]
        if missing:
            raise AuthenticationError("oidc_configuration_incomplete")
        for endpoint in (self.authorization_endpoint, self.token_endpoint, self.jwks_uri, self.redirect_uri):
            validate_outbound_url(endpoint)

    def start(self) -> dict[str, Any]:
        self.validate_config()
        transaction = self.transaction_store.create(self.redirect_uri)
        challenge = _b64url(hashlib.sha256(transaction.code_verifier.encode("ascii")).digest())
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": "openid profile email",
                "state": transaction.state,
                "nonce": transaction.nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return {
            "authorization_url": f"{self.authorization_endpoint}?{query}",
            "expires_at": transaction.expires_at,
        }

    def exchange_code(self, code: str, state: str) -> dict[str, Any]:
        self.validate_config()
        if not code or not state:
            raise AuthenticationError("oidc_code_and_state_required")
        transaction = self.transaction_store.consume(state)
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": transaction.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": transaction.code_verifier,
        }
        if self.client_secret:
            body["client_secret"] = self.client_secret
        request = Request(
            self.token_endpoint,
            data=urlencode(body).encode("utf-8"),
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        with safe_urlopen(
            request,
            timeout=10,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        id_token = str(payload.get("id_token") or "") if isinstance(payload, dict) else ""
        if not id_token:
            raise AuthenticationError("oidc_id_token_missing")
        claims = self._verify_id_token(id_token, transaction.nonce)
        email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
        if not email:
            raise AuthenticationError("oidc_email_claim_missing")
        require_verified = os.getenv("SMART_DATA_AGENT_OIDC_REQUIRE_VERIFIED_EMAIL", "true").lower() != "false"
        if require_verified and claims.get("email_verified") is not True:
            raise AuthenticationError("oidc_email_not_verified")
        return {
            "subject": str(claims.get("sub") or ""),
            "email": email,
            "claims": {
                "iss": claims.get("iss"),
                "sub": claims.get("sub"),
                "email": email,
            },
        }

    def _verify_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        header = jwt.get_unverified_header(id_token)
        algorithm = str(header.get("alg") or "")
        if algorithm not in {"RS256", "ES256"}:
            raise AuthenticationError("oidc_signing_algorithm_not_allowed")
        kid = str(header.get("kid") or "")
        with safe_urlopen(
            Request(self.jwks_uri, headers={"Accept": "application/json"}),
            timeout=8,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            jwks = json.loads(response.read(2_000_000).decode("utf-8"))
        keys = jwks.get("keys") if isinstance(jwks, dict) else None
        key_payload = next((item for item in keys or [] if isinstance(item, dict) and str(item.get("kid") or "") == kid), None)
        if not key_payload:
            raise AuthenticationError("oidc_signing_key_not_found")
        key = jwt.PyJWK.from_dict(key_payload, algorithm=algorithm).key
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=[algorithm],
                audience=self.client_id,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "sub", "aud", "nonce"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("oidc_id_token_invalid") from exc
        if not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
            raise AuthenticationError("oidc_nonce_mismatch")
        return dict(claims)


def _new_transaction(redirect_uri: str, ttl_seconds: int, now: int | None) -> tuple[OIDCTransaction, dict[str, Any]]:
    current = int(time.time() if now is None else now)
    state = secrets.token_urlsafe(32)
    transaction = OIDCTransaction(
        transaction_id="oidctx_" + secrets.token_urlsafe(18),
        state=state,
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(64),
        redirect_uri=redirect_uri,
        expires_at=current + max(60, min(int(ttl_seconds), 600)),
    )
    return transaction, {
        "transaction_id": transaction.transaction_id,
        "state_hash": _state_hash(state),
        "state": state,
        "nonce": transaction.nonce,
        "code_verifier": transaction.code_verifier,
        "redirect_uri": redirect_uri,
        "created_at": current,
        "expires_at": transaction.expires_at,
        "consumed_at": None,
    }


def _validate_transaction_record(record: dict[str, Any] | None, state: str, current: int) -> OIDCTransaction:
    if not record or record.get("consumed_at") is not None:
        raise AuthenticationError("oidc_transaction_unknown_or_consumed")
    if current >= int(record["expires_at"]):
        raise AuthenticationError("oidc_transaction_expired")
    if not secrets.compare_digest(str(record["state_hash"]), _state_hash(state)):
        raise AuthenticationError("oidc_state_mismatch")
    return OIDCTransaction(
        transaction_id=str(record["transaction_id"]),
        state=state,
        nonce=str(record["nonce"]),
        code_verifier=str(record["code_verifier"]),
        redirect_uri=str(record["redirect_uri"]),
        expires_at=int(record["expires_at"]),
    )


def _state_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
