from __future__ import annotations

import hashlib
import hmac
import secrets

DEFAULT_ACCOUNT_PASSWORD = "123456"
MIN_PASSWORD_LENGTH = 6
_PBKDF2_ITERATIONS = 80_000
_SCHEME = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    text = str(password or "")
    if len(text) < MIN_PASSWORD_LENGTH:
        raise ValueError("password_new_too_short")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
    return f"{_SCHEME}${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(stored_hash: str, password: str) -> bool:
    raw = str(stored_hash or "")
    parts = raw.split("$")
    if len(parts) != 4 or parts[0] != _SCHEME:
        return False
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = parts[3]
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations).hex()
    return hmac.compare_digest(actual, expected)


def default_password_hash() -> str:
    return hash_password(DEFAULT_ACCOUNT_PASSWORD)
