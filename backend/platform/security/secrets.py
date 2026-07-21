from __future__ import annotations

import base64
import hashlib
import hmac
import os
import shlex
import subprocess
from typing import Protocol


SECRET_PREFIX_V1 = "enc:v1:"
SECRET_PREFIX = "enc:v2:"


class SecretConfigurationError(ValueError):
    pass


def encrypt_secret(value: str) -> str:
    """Encrypt or delegate secret protection before storing local config."""

    if not value or value.startswith((SECRET_PREFIX, SECRET_PREFIX_V1, "kms:")):
        return value
    return _secret_provider().encrypt(value)


def decrypt_secret(value: str) -> str:
    if not value:
        return value
    return _secret_provider_for_value(value).decrypt(value)


class SecretProvider(Protocol):
    def encrypt(self, value: str) -> str:
        ...

    def decrypt(self, value: str) -> str:
        ...


class LocalEnvelopeSecretProvider:
    """Development/local provider.

    This keeps secrets out of plaintext SQLite files, but production deployments
    should use KMSCommandSecretProvider through SMART_DATA_AGENT_SECRET_PROVIDER.
    """

    def encrypt(self, value: str) -> str:
        if not value or value.startswith((SECRET_PREFIX, SECRET_PREFIX_V1)):
            return value
        key = _secret_key()
        raw = value.encode("utf-8")
        nonce = os.urandom(16)
        encrypted = _xor_bytes(raw, _key_stream(key, nonce, len(raw)))
        tag = hmac.new(key, nonce + encrypted, hashlib.sha256).digest()
        return ":".join(
            [
                SECRET_PREFIX.rstrip(":"),
                _b64encode(nonce),
                _b64encode(encrypted),
                _b64encode(tag),
            ]
        )

    def decrypt(self, value: str) -> str:
        if not value:
            return value
        if value.startswith(SECRET_PREFIX_V1):
            return _decrypt_v1_secret(value)
        if not value.startswith(SECRET_PREFIX):
            return value
        key = _secret_key()
        parts = value.split(":")
        if len(parts) != 5 or parts[:2] != ["enc", "v2"]:
            raise ValueError("invalid encrypted secret envelope.")
        nonce = _b64decode(parts[2])
        encrypted = _b64decode(parts[3])
        tag = _b64decode(parts[4])
        expected_tag = hmac.new(key, nonce + encrypted, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("encrypted secret integrity check failed.")
        raw = _xor_bytes(encrypted, _key_stream(key, nonce, len(encrypted)))
        return raw.decode("utf-8")


class KMSCommandSecretProvider:
    """External KMS/Vault command provider.

    The command receives an action argument, either "encrypt" or "decrypt", and
    reads the secret value from stdin. It must print the protected value to stdout.
    """

    def __init__(self, command: str) -> None:
        self.command = command.strip()
        if not self.command:
            raise SecretConfigurationError("SMART_DATA_AGENT_KMS_COMMAND is required for KMS secret provider.")

    def encrypt(self, value: str) -> str:
        return self._call("encrypt", value)

    def decrypt(self, value: str) -> str:
        if not value.startswith("kms:"):
            return value
        return self._call("decrypt", value)

    def _call(self, action: str, value: str) -> str:
        args = [*shlex.split(self.command), action]
        result = subprocess.run(
            args,
            input=value,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise SecretConfigurationError(f"KMS command failed: {result.stderr.strip()[:200]}")
        output = result.stdout.strip()
        if not output:
            raise SecretConfigurationError("KMS command returned an empty secret envelope.")
        return output


def _secret_provider() -> SecretProvider:
    provider = os.getenv("SMART_DATA_AGENT_SECRET_PROVIDER", "local").strip().lower()
    if provider in {"kms", "command", "vault"}:
        return KMSCommandSecretProvider(os.getenv("SMART_DATA_AGENT_KMS_COMMAND", ""))
    if provider not in {"local", ""}:
        raise SecretConfigurationError(f"unknown secret provider: {provider}")
    return LocalEnvelopeSecretProvider()


def _secret_provider_for_value(value: str) -> SecretProvider:
    if value.startswith("kms:"):
        return KMSCommandSecretProvider(os.getenv("SMART_DATA_AGENT_KMS_COMMAND", ""))
    return _secret_provider()


def _secret_key() -> bytes:
    seed_value = os.getenv("SMART_DATA_AGENT_SECRET_KEY", "").strip()
    if not seed_value:
        if os.getenv("SMART_DATA_AGENT_AUTH_MODE", "development").strip().lower() == "strict":
            raise SecretConfigurationError("SMART_DATA_AGENT_SECRET_KEY is required in strict mode.")
        seed_value = "smart-data-agent-local-secret"
    seed = seed_value.encode("utf-8")
    return hashlib.sha256(seed).digest()


def _decrypt_v1_secret(value: str) -> str:
    key = _secret_key()
    encoded = base64.urlsafe_b64decode(value[len(SECRET_PREFIX_V1) :].encode("ascii"))
    raw = _xor_bytes(encoded, bytes(key[index % len(key)] for index in range(len(encoded))))
    return raw.decode("utf-8")


def _key_stream(key: bytes, nonce: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    produced = 0
    while produced < length:
        chunk = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        chunks.append(chunk)
        produced += len(chunk)
        counter += 1
    return b"".join(chunks)[:length]


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(left_byte ^ right_byte for left_byte, right_byte in zip(left, right))


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
