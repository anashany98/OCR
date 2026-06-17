"""Block 7 — Security TODOs regression tests.

These tests lock the minimum viable hardening for the internal
deployment:

* ``integration_jwt_secret`` and ``api_key_hmac_secret`` MUST be
  set to a value distinct from ``jwt_secret`` in non-local
  environments. The use-site fallback to ``jwt_secret`` is
  retained only for local development.
* ``max_upload_files`` defaults to 2_000 (down from the
  effectively-unbounded 10_000_000). The Starlette multipart
  monkeypatch in ``app.core.multipart_limits`` is still in
  place; a future commit will replace it with a native
  FastAPI hook.
* The Dockerfile CMD no longer defaults to
  ``--forwarded-allow-ips=*`` (wildcard). The new default is
  the RFC1918 private network ranges plus loopback, and
  operators should still pin ``UVICORN_FORWARDED_ALLOW_IPS``
  to the actual reverse-proxy CIDR in ``.env.production``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _settings_with_env(env: dict[str, str]):
    """Build a fresh ``Settings`` instance with the given env overrides.

    ``Settings`` is a pydantic ``BaseSettings`` model; we rebuild it
    so the test does not depend on the process-wide environment
    leaking into the assertions.
    """
    # ``BaseSettings`` reads ``os.environ`` at instantiation, so we
    # set the overrides there and clear anything we want to control.
    saved = {k: os.environ.pop(k, None) for k in env}
    for k, v in env.items():
        if v is not None:
            os.environ[k] = v
    try:
        from app.core.config import Settings

        return Settings()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Per-purpose secrets — distinct from jwt_secret
# ---------------------------------------------------------------------------


def test_integration_jwt_secret_must_differ_from_jwt_secret_in_production() -> None:
    """SEC-BLOCK-7: a duplicate secret means a leak in one
    surface compromises the other. In production the validator
    rejects the setting when it matches ``JWT_SECRET``.
    """
    secret = "x" * 64
    with pytest.raises(ValueError, match="must differ from JWT_SECRET"):
        _settings_with_env(
            {
                "ENVIRONMENT": "production",
                "JWT_SECRET": secret,
                "INTEGRATION_JWT_SECRET": secret,
            }
        )


def test_api_key_hmac_secret_must_differ_from_jwt_secret_in_production() -> None:
    """SEC-BLOCK-7: same rule for the API-key HMAC secret."""
    secret = "x" * 64
    with pytest.raises(ValueError, match="must differ from JWT_SECRET"):
        _settings_with_env(
            {
                "ENVIRONMENT": "production",
                "JWT_SECRET": secret,
                "API_KEY_HMAC_SECRET": secret,
            }
        )


def test_integration_jwt_secret_empty_rejected_in_production() -> None:
    """In non-local environments both secrets must be set; the
    use-site fallback to ``jwt_secret`` is local-dev only.
    """
    with pytest.raises(ValueError, match="INTEGRATION_JWT_SECRET must be set"):
        _settings_with_env(
            {
                "ENVIRONMENT": "production",
                "JWT_SECRET": "x" * 64,
                # INTEGRATION_JWT_SECRET intentionally not set
            }
        )


def test_api_key_hmac_secret_empty_rejected_in_production() -> None:
    with pytest.raises(ValueError, match="API_KEY_HMAC_SECRET must be set"):
        _settings_with_env(
            {
                "ENVIRONMENT": "production",
                "JWT_SECRET": "x" * 64,
                # API_KEY_HMAC_SECRET intentionally not set
            }
        )


def test_integration_secrets_accepted_in_local_with_fallback() -> None:
    """In ``local`` the use-site fallback to ``jwt_secret`` is
    accepted. The settings load without raising and the
    defaults are empty strings (the use-site code falls
    back to ``jwt_secret`` when the dedicated value is empty).
    """
    settings = _settings_with_env(
        {
            "ENVIRONMENT": "local",
            "JWT_SECRET": "x" * 64,
        }
    )
    assert settings.integration_jwt_secret == ""
    assert settings.api_key_hmac_secret == ""


def test_integration_secrets_accepted_when_distinct_in_production() -> None:
    """When the dedicated secrets are set to distinct values
    in production, the settings load cleanly.
    """
    settings = _settings_with_env(
        {
            "ENVIRONMENT": "production",
            "JWT_SECRET": "a" * 64,
            "INTEGRATION_JWT_SECRET": "b" * 64,
            "API_KEY_HMAC_SECRET": "c" * 64,
        }
    )
    assert settings.integration_jwt_secret == "b" * 64
    assert settings.api_key_hmac_secret == "c" * 64


# ---------------------------------------------------------------------------
# max_upload_files — bounded default
# ---------------------------------------------------------------------------


def test_max_upload_files_default_is_bounded() -> None:
    """SEC-BLOCK-7: the previous default of 10_000_000 was
    effectively unbounded. The new default of 2_000 supports
    a folder drag-and-drop while protecting the worker from
    OOM. Operators that need to ingest larger batches can
    override via ``MAX_UPLOAD_FILES``.
    """
    settings = _settings_with_env({})
    assert settings.max_upload_files == 2_000
    # And the upper bound is sane (not the old 10_000_000).
    assert settings.max_upload_files < 10_000


# ---------------------------------------------------------------------------
# Dockerfile --forwarded-allow-ips default
# ---------------------------------------------------------------------------


def test_dockerfile_cmd_no_longer_uses_wildcard_forwarded_allow_ips() -> None:
    """SEC-BLOCK-7: the Dockerfile must NOT default to
    ``--forwarded-allow-ips=*`` (wildcard). The default is
    now the RFC1918 private network ranges plus loopback,
    so the default is not wide open.
    """
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    cmd_line = next(
        (
            line
            for line in dockerfile.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("CMD ")
        ),
        None,
    )
    assert cmd_line is not None, "Dockerfile is missing a CMD instruction"
    assert "--forwarded-allow-ips=*" not in cmd_line, (
        "Dockerfile CMD still defaults --forwarded-allow-ips to wildcard '*'. "
        "Change the default to the RFC1918 private network ranges so the "
        "deployment is not wide-open by default."
    )
    assert "10.0.0.0/8" in cmd_line, (
        "Dockerfile CMD should include the RFC1918 10.0.0.0/8 range in the "
        "default --forwarded-allow-ips value"
    )
