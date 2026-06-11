"""
Unit tests for AUTH-JWT-1 (Sprint 1).

The previous implementation signed every JWT in the system with
``settings.jwt_secret``:

* User access tokens (``/api/v1/*`` endpoints) → ``jwt_secret``
* Integration budget session tokens (``/integrations/v1/*``) → ``jwt_secret``
* API key HMAC digest (``api_key_hash`` column) → ``jwt_secret``

A leak of ``jwt_secret`` compromised every surface at once. The
fix:

* ``create_access_token`` keeps using ``jwt_secret`` and now sets
  ``typ="access"`` on every newly issued token.
* ``create_budget_session_token`` is signed with
  ``settings.integration_jwt_secret`` (falls back to ``jwt_secret``).
* ``hash_integration_api_key`` is computed with
  ``settings.api_key_hmac_secret`` (falls back to ``jwt_secret``).
* ``decode_access_token`` rejects tokens whose ``typ`` claim is set
  to something other than ``"access"`` (so a budget session token
  cannot authenticate as a user).
* ``decode_budget_session_token`` uses a separate decoder that
  verifies the signature against the integration secret, so a user
  access token cannot be replayed as a budget session.

These tests verify the secret separation, the ``typ`` claim, and
the defence-in-depth rejection paths.
"""
from __future__ import annotations

import time

import pytest

from app.core import security as security_module
from app.core.config import settings
from app.core.security import (
    ACCESS_TOKEN_TYP,
    BUDGET_SESSION_TYP,
    _api_key_hmac_secret,
    _encode_jwt,
    _integration_jwt_secret,
    _user_jwt_secret,
    create_access_token,
    decode_access_token,
    decode_integration_token,
)
from app.services.budget_scope import (
    create_budget_session_token,
    decode_budget_session_token,
)
from app.services.integration_security import (
    hash_integration_api_key,
    verify_integration_api_key,
)


# ---------------------------------------------------------------------------
# Secret resolver helpers
# ---------------------------------------------------------------------------


class TestSecretResolvers:
    """The three secrets must be addressable independently."""

    def test_user_secret_uses_jwt_secret(self):
        assert _user_jwt_secret() == settings.jwt_secret

    def test_integration_secret_falls_back_to_jwt_secret_when_empty(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "integration_jwt_secret", "")
        assert _integration_jwt_secret() == settings.jwt_secret

    def test_integration_secret_uses_dedicated_value_when_set(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "integration_jwt_secret", "integ-secret-xyz")
        assert _integration_jwt_secret() == "integ-secret-xyz"

    def test_api_key_hmac_secret_falls_back_to_jwt_secret_when_empty(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "api_key_hmac_secret", "")
        assert _api_key_hmac_secret() == settings.jwt_secret

    def test_api_key_hmac_secret_uses_dedicated_value_when_set(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "api_key_hmac_secret", "hmac-secret-xyz")
        assert _api_key_hmac_secret() == "hmac-secret-xyz"


# ---------------------------------------------------------------------------
# typ claim on issued tokens
# ---------------------------------------------------------------------------


class TestAccessTokenTyp:
    """Access tokens must carry ``typ="access"`` and the right secret."""

    def test_new_access_token_has_typ_access(self):
        token = create_access_token("user-123")
        payload = decode_access_token(token)
        assert payload["typ"] == ACCESS_TOKEN_TYP
        assert payload["typ"] == "access"

    def test_access_token_uses_user_secret(self):
        # A token signed with a *different* secret must be rejected.
        # We verify the reverse: re-encoding with the wrong secret
        # yields a different signature.
        token = create_access_token("user-123")
        # Tamper with the signature by encoding the same payload with
        # the integration secret.
        forged = _encode_jwt(
            decode_access_token(token) | {"exp": int(time.time()) + 60},
            secret="wrong-secret",
        )
        with pytest.raises(ValueError, match="signature"):
            decode_access_token(forged)


class TestBudgetSessionTokenTyp:
    """Budget session tokens must carry ``typ="budget_session"`` and
    be signed with the integration secret."""

    def _make_session_token(self) -> str:
        return create_budget_session_token(
            client_id=42,
            technician_id="tech-1",
            budget_scope_id=10,
            budget_code="245745",
            can_see_amounts=True,
        )

    def test_new_session_token_has_typ_budget_session(self):
        token = self._make_session_token()
        claims = decode_budget_session_token(token)
        assert claims.client_id == 42
        assert claims.technician_id == "tech-1"
        assert claims.budget_code == "245745"
        assert claims.can_see_amounts is True


# ---------------------------------------------------------------------------
# Cross-purpose rejection: tokens must not be replayable
# ---------------------------------------------------------------------------


class TestCrossPurposeRejection:
    """A user access token MUST NOT be usable as a budget session, and
    a budget session token MUST NOT be usable as a user access token.
    This is the headline defence of AUTH-JWT-1.
    """

    def test_access_token_rejected_as_budget_session(self):
        access_token = create_access_token("user-123")
        with pytest.raises(ValueError, match="budget session"):
            decode_budget_session_token(access_token)

    def test_budget_session_rejected_as_access_token(self):
        session_token = create_budget_session_token(
            client_id=1,
            technician_id="tech-1",
            budget_scope_id=10,
            budget_code="245745",
            can_see_amounts=False,
        )
        with pytest.raises(ValueError, match="Wrong token type"):
            decode_access_token(session_token)

    def test_access_token_fails_integration_signature(self, monkeypatch):
        """A token signed with the user secret MUST also fail the
        integration signature check when the integration secret is
        distinct (defence in depth: even if a caller forgot the typ
        check, the secret check would still reject)."""
        # Force distinct secrets so the signature check (not just the
        # typ check) catches the replay attempt.
        monkeypatch.setattr(settings, "integration_jwt_secret", "integ-secret-abc")
        access_token = create_access_token("user-123")
        with pytest.raises(ValueError, match="signature"):
            decode_integration_token(access_token)

    def test_budget_session_fails_user_signature(self, monkeypatch):
        """A budget session signed with the integration secret MUST
        also fail the user signature check when the secrets are
        distinct."""
        monkeypatch.setattr(settings, "integration_jwt_secret", "integ-secret-abc")
        session_token = create_budget_session_token(
            client_id=1,
            technician_id="tech-1",
            budget_scope_id=10,
            budget_code="245745",
            can_see_amounts=False,
        )
        with pytest.raises(ValueError, match="signature"):
            decode_access_token(session_token)

    def test_budget_session_fails_user_via_typ_when_secrets_equal(self):
        """When the integration secret equals the user secret, the
        signature check passes but the typ check still rejects.
        """
        session_token = create_budget_session_token(
            client_id=1,
            technician_id="tech-1",
            budget_scope_id=10,
            budget_code="245745",
            can_see_amounts=False,
        )
        with pytest.raises(ValueError, match="Wrong token type"):
            decode_access_token(session_token)


# ---------------------------------------------------------------------------
# typ strict mode: a forged typ must be rejected
# ---------------------------------------------------------------------------


class TestTypStrictMode:
    """A token with the right signature but a wrong typ must be rejected.

    This catches the case where an attacker has the user secret but
    tries to forge a token with typ="budget_session" (or vice versa).
    """

    def test_access_endpoint_rejects_budget_session_typ(self):
        # Build a token signed with the user secret but claiming
        # typ="budget_session".
        forged = _encode_jwt(
            {
                "sub": "1",  # would parse as user id
                "typ": "budget_session",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            secret=_user_jwt_secret(),
        )
        with pytest.raises(ValueError, match="Wrong token type"):
            decode_access_token(forged)

    def test_budget_session_rejects_access_typ(self):
        # Token signed with the integration secret but claiming
        # typ="access". decode_budget_session_token requires
        # typ="budget_session" AND sub="integration_budget_session".
        forged = _encode_jwt(
            {
                "sub": "1",
                "typ": "access",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            secret=_integration_jwt_secret(),
        )
        with pytest.raises(ValueError, match="Invalid budget session"):
            decode_budget_session_token(forged)


# ---------------------------------------------------------------------------
# Backward compatibility: tokens without typ must still work
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """Tokens issued before Sprint 1 lack the ``typ`` claim; the
    decoder must continue to accept them so existing user sessions
    are not invalidated by this rollout.
    """

    def test_legacy_access_token_without_typ_is_accepted(self):
        legacy = _encode_jwt(
            {
                "sub": "user-123",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            secret=_user_jwt_secret(),
        )
        payload = decode_access_token(legacy)
        assert payload["sub"] == "user-123"
        # typ missing, payload has no "typ" key
        assert "typ" not in payload

    def test_legacy_token_with_wrong_typ_is_rejected(self):
        """A typ other than 'access' is still rejected — the only
        tolerated 'no typ' case is the legacy 'missing' one."""
        legacy_with_typ = _encode_jwt(
            {
                "sub": "user-123",
                "typ": "something_else",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            secret=_user_jwt_secret(),
        )
        with pytest.raises(ValueError, match="Wrong token type"):
            decode_access_token(legacy_with_typ)


# ---------------------------------------------------------------------------
# API key HMAC uses the dedicated secret
# ---------------------------------------------------------------------------


class TestApiKeyHmacSeparation:
    """The API key HMAC must use a dedicated secret so a leak of the
    user JWT secret cannot be used to brute-force API key hashes.
    """

    def test_hashing_changes_when_secret_changes(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key_hmac_secret", "hmac-secret-1")
        h1 = hash_integration_api_key("key-abc")
        monkeypatch.setattr(settings, "api_key_hmac_secret", "hmac-secret-2")
        h2 = hash_integration_api_key("key-abc")
        assert h1 != h2
        # Both still have the correct prefix
        assert h1.startswith("hmac_sha256$")
        assert h2.startswith("hmac_sha256$")

    def test_verify_succeeds_against_same_secret(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key_hmac_secret", "stable-secret")
        api_key = "my-integration-key"
        stored = hash_integration_api_key(api_key)
        assert verify_integration_api_key(api_key, stored) is True
        assert verify_integration_api_key("wrong-key", stored) is False

    def test_fallback_to_jwt_secret_when_dedicated_empty(self, monkeypatch):
        """When ``api_key_hmac_secret`` is empty, the hash uses
        ``jwt_secret`` (legacy mode). The hashed value is the same
        as a pre-Sprint-1 deployment."""
        monkeypatch.setattr(settings, "api_key_hmac_secret", "")
        # Pre-Sprint-1 reference: HMAC(api_key, jwt_secret, sha256)
        import hashlib
        import hmac as _hmac
        reference = "hmac_sha256$" + _hmac.new(
            settings.jwt_secret.encode("utf-8"),
            b"key-abc",
            hashlib.sha256,
        ).hexdigest()
        assert hash_integration_api_key("key-abc") == reference

    def test_hash_differs_from_jwt_secret_hash(self, monkeypatch):
        """When a dedicated secret IS set, the hash is NOT the same
        as the legacy jwt_secret-based hash."""
        monkeypatch.setattr(settings, "api_key_hmac_secret", "new-dedicated")
        api_key = "key-abc"
        h_new = hash_integration_api_key(api_key)
        # Compute the legacy hash
        import hashlib
        import hmac as _hmac
        h_legacy = "hmac_sha256$" + _hmac.new(
            settings.jwt_secret.encode("utf-8"),
            api_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert h_new != h_legacy
