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

# Token-type claim values used to keep access tokens and integration
# tokens (budget sessions) on separate rails, even when they share
# the same algorithm. AUTH-JWT-1 (Sprint 1) added these so a stolen
# budget-session token cannot be presented as a user access token
# (defence in depth on top of the per-purpose HMAC secret).
ACCESS_TOKEN_TYP = "access"
BUDGET_SESSION_TYP = "budget_session"


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


def _user_jwt_secret() -> str:
    """Secret used to sign user access tokens.

    Always ``settings.jwt_secret``; the integration secret is a
    separate value (``_integration_jwt_secret``).
    """
    return settings.jwt_secret


def _integration_jwt_secret() -> str:
    """Secret used to sign integration-issued JWTs (budget sessions).

    Falls back to ``settings.jwt_secret`` for backward compatibility
    when the operator has not yet set ``INTEGRATION_JWT_SECRET``;
    the next release of the deployment runbook will require a
    distinct value.
    """
    return settings.integration_jwt_secret or settings.jwt_secret


def _api_key_hmac_secret() -> str:
    """Secret used to HMAC integration API keys before storing them.

    Same fallback policy as ``_integration_jwt_secret``.
    """
    return settings.api_key_hmac_secret or settings.jwt_secret


def create_access_token(subject: str, expires_in_seconds: int | None = None) -> str:
    now = int(time.time())
    expires = now + (expires_in_seconds or settings.jwt_expire_minutes * 60)
    payload = {
        "sub": subject,
        # ``typ`` is set on every newly issued token; the decoder
        # accepts a missing ``typ`` for backward compatibility with
        # tokens issued before this field existed.
        "typ": ACCESS_TOKEN_TYP,
        "iat": now,
        "exp": expires,
    }
    return _encode_jwt(payload, secret=_user_jwt_secret())


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = _sign(signing_input, secret=_user_jwt_secret())
    if not hmac.compare_digest(expected, signature_b64):
        raise ValueError("Invalid token signature")

    header = json.loads(_unb64(header_b64))
    alg = header.get("alg", "")
    if alg != settings.jwt_algorithm:
        raise ValueError(f"Unsupported algorithm: {alg}")

    payload = json.loads(_unb64(payload_b64))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("Expired token")
    # If the token carries a ``typ`` claim, it MUST be ``access``.
    # Tokens without ``typ`` are accepted for backward compatibility
    # (pre-Sprint-1 access tokens); the next major release will
    # require the field.
    typ = payload.get("typ")
    if typ is not None and typ != ACCESS_TOKEN_TYP:
        raise ValueError(
            f"Wrong token type for access endpoint: {typ!r} (expected {ACCESS_TOKEN_TYP!r})"
        )
    return payload


def _encode_jwt(payload: dict[str, Any], *, secret: str) -> str:
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(f"{header_b64}.{payload_b64}".encode("ascii"), secret=secret)
    return f"{header_b64}.{payload_b64}.{signature}"


def decode_integration_token(token: str) -> dict[str, Any]:
    """Decode a JWT signed with the integration secret.

    Verifies the signature against ``_integration_jwt_secret`` and
    returns the payload. Does NOT enforce a specific ``typ``; the
    caller is expected to check ``typ`` (e.g.
    ``decode_budget_session_token`` requires ``BUDGET_SESSION_TYP``).

    The decoder is the integration-side counterpart of
    :func:`decode_access_token`. A token signed with the user secret
    will fail signature verification here and raise ``ValueError``,
    so a user access token cannot be replayed against the integration
    endpoints.
    """
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = _sign(signing_input, secret=_integration_jwt_secret())
    if not hmac.compare_digest(expected, signature_b64):
        raise ValueError("Invalid token signature")

    header = json.loads(_unb64(header_b64))
    alg = header.get("alg", "")
    if alg != settings.jwt_algorithm:
        raise ValueError(f"Unsupported algorithm: {alg}")

    payload = json.loads(_unb64(payload_b64))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("Expired token")
    return payload


def _sign(signing_input: bytes, *, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return _b64(digest)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
