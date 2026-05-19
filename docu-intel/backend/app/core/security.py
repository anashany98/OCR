from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

try:
    import bcrypt
except ImportError:
    bcrypt = None

from app.core.config import settings


def hash_password(password: str) -> str:
    if bcrypt is not None:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 150_000)
    return "pbkdf2_sha256$150000$" + _b64(salt) + "$" + _b64(digest)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("$2") and bcrypt is not None:
        return bool(bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")))

    if password_hash.startswith("pbkdf2_sha256$"):
        _, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)

    return False


def create_access_token(subject: str, expires_in_seconds: int | None = None) -> str:
    now = int(time.time())
    expires = now + (expires_in_seconds or settings.jwt_expire_minutes * 60)
    payload = {"sub": subject, "iat": now, "exp": expires}
    return _encode_jwt(payload)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        raise ValueError("Invalid token format")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = _sign(signing_input)
    if not hmac.compare_digest(expected, signature_b64):
        raise ValueError("Invalid token signature")

    header = json.loads(_unb64(header_b64))
    alg = header.get("alg", "")
    if alg not in {"HS256", "HS384", "HS512"}:
        raise ValueError(f"Unsupported algorithm: {alg}")

    payload = json.loads(_unb64(payload_b64))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("Expired token")
    return payload


def _encode_jwt(payload: dict[str, Any]) -> str:
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(f"{header_b64}.{payload_b64}".encode("ascii"))
    return f"{header_b64}.{payload_b64}.{signature}"


def _sign(signing_input: bytes) -> str:
    digest = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return _b64(digest)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)

