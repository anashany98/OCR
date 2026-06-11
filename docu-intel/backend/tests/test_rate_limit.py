"""
Unit tests for app.core.rate_limit

SEC-RL-1 (Sprint 0): the rate limit bucket key MUST be derived from
``request.client.host`` (the socket address, already validated by
uvicorn's --proxy-headers when enabled) and the integration API key.
Header-based IP extraction (X-Forwarded-For, X-Real-IP) is
**explicitly rejected** to prevent bucket-key forgery by an attacker
who can inject HTTP headers.

These tests exercise the key function directly with a fake
``Request`` built from a Starlette scope so the assertion is
independent of the rest of the FastAPI stack.
"""
from __future__ import annotations

from typing import Iterable

import pytest
from starlette.requests import Request

from app.core.rate_limit import _hash_api_key, rate_limit_key


def _make_request(
    *,
    client_host: str = "10.0.0.5",
    client_port: int = 12345,
    headers: Iterable[tuple[str, str]] = (),
) -> Request:
    """Build a Starlette Request with the given client address + headers.

    The headers are tuples (``(name, value)``) so we can pass the same
    header twice (e.g. two X-Forwarded-For entries) without the dict
    collapsing them.

    Starlette's scope requires headers as ``Iterable[tuple[bytes, bytes]]``,
    so we encode everything to latin-1 (the bytes/str bridge that
    Starlette's parser uses for HTTP/1.1 header values).
    """
    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": (client_host, client_port),
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in headers
        ],
    }
    return Request(scope)


class TestHashApiKey:
    """`_hash_api_key` is the privacy boundary for the bucket key."""

    def test_is_deterministic(self):
        assert _hash_api_key("abc") == _hash_api_key("abc")

    def test_differs_for_different_keys(self):
        assert _hash_api_key("abc") != _hash_api_key("xyz")

    def test_returns_16_hex_chars(self):
        # SHA-256 hex digest truncated to 16 chars = 64 bits of entropy
        result = _hash_api_key("any-key")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_does_not_leak_the_raw_key(self):
        # Critical: the bucket key MUST NOT contain the raw API key
        # anywhere; otherwise slowapi dumps or Redis MONITOR output
        # would leak the integration key.
        raw = "super-secret-key-do-not-leak-12345"
        hashed = _hash_api_key(raw)
        assert raw not in hashed
        assert len(hashed) < len(raw)


class TestRateLimitKeySocketOnly:
    """The bucket key is the socket address; no header-based forgery."""

    def test_returns_client_host_when_no_headers(self):
        request = _make_request(client_host="192.0.2.10")
        assert rate_limit_key(request) == "192.0.2.10"

    def test_ignores_x_forwarded_for_when_no_proxy(self):
        """Critical: a direct client (no --proxy-headers) cannot spoof
        the client IP by sending X-Forwarded-For. The bucket is still
        bound to the socket address."""
        request = _make_request(
            client_host="192.0.2.10",
            headers=[("x-forwarded-for", "1.2.3.4")],
        )
        assert rate_limit_key(request) == "192.0.2.10"

    def test_ignores_x_forwarded_for_with_multiple_ips(self):
        request = _make_request(
            client_host="192.0.2.10",
            headers=[("x-forwarded-for", "1.2.3.4, 5.6.7.8, 9.10.11.12")],
        )
        assert rate_limit_key(request) == "192.0.2.10"

    def test_ignores_x_real_ip(self):
        request = _make_request(
            client_host="192.0.2.10",
            headers=[("x-real-ip", "1.2.3.4")],
        )
        assert rate_limit_key(request) == "192.0.2.10"

    def test_ignores_combined_x_forwarded_for_and_x_real_ip(self):
        request = _make_request(
            client_host="192.0.2.10",
            headers=[
                ("x-forwarded-for", "1.2.3.4"),
                ("x-real-ip", "5.6.7.8"),
            ],
        )
        assert rate_limit_key(request) == "192.0.2.10"

    def test_ignores_header_with_lowercase_and_uppercase(self):
        """A determined attacker tries every casing of the header."""
        for variant in ("X-Forwarded-For", "X-FORWARDED-FOR", "x-Forwarded-For"):
            request = _make_request(
                client_host="192.0.2.10",
                headers=[(variant, "1.2.3.4")],
            )
            assert rate_limit_key(request) == "192.0.2.10", (
                f"failed for variant: {variant!r}"
            )

    def test_ignores_custom_forwarding_headers(self):
        """Belt and braces: even custom headers like ``Forwarded`` or
        ``X-Real-Ip`` (mixed case) are ignored."""
        for header in ("forwarded", "X-Real-Ip", "X-Cluster-Client-Ip"):
            request = _make_request(
                client_host="192.0.2.10",
                headers=[(header, "1.2.3.4")],
            )
            assert rate_limit_key(request) == "192.0.2.10", (
                f"failed for header: {header!r}"
            )


class TestRateLimitKeyApiKey:
    """When the API key is present, it always wins (and is hashed)."""

    def test_api_key_takes_precedence_over_socket(self):
        request = _make_request(
            client_host="192.0.2.10",
            headers=[("X-DocuIntel-API-Key", "key-1")],
        )
        key = rate_limit_key(request)
        assert key.startswith("api_key:")
        # The raw key MUST NOT appear in the bucket key
        assert "key-1" not in key
        # The same key always produces the same bucket
        assert key == rate_limit_key(request)

    def test_different_api_keys_get_different_buckets(self):
        req1 = _make_request(
            client_host="192.0.2.10",
            headers=[("X-DocuIntel-API-Key", "key-1")],
        )
        req2 = _make_request(
            client_host="192.0.2.10",
            headers=[("X-DocuIntel-API-Key", "key-2")],
        )
        assert rate_limit_key(req1) != rate_limit_key(req2)

    def test_api_key_ignored_when_empty(self):
        """An empty API key is treated as no API key at all."""
        request = _make_request(
            client_host="192.0.2.10",
            headers=[("X-DocuIntel-API-Key", "")],
        )
        # Falls back to client host
        assert rate_limit_key(request) == "192.0.2.10"

    def test_api_key_does_not_leak_into_redis_dump(self):
        """Critical: a Redis MONITOR stream or slowapi dump must not
        reveal the raw API key. We verify this by checking the bucket
        key is the truncated SHA-256, not the raw value."""
        raw_key = "supersecret-integration-key-xyz-1234567890"
        request = _make_request(
            client_host="192.0.2.10",
            headers=[("X-DocuIntel-API-Key", raw_key)],
        )
        bucket = rate_limit_key(request)
        # Nothing in the bucket key resembles the raw key
        assert raw_key[:8] not in bucket
        assert raw_key[-8:] not in bucket
        assert raw_key not in bucket


class TestRateLimitKeyCrossCheck:
    """The same client with a forged header should NOT change buckets."""

    @pytest.mark.parametrize(
        "spoofed_header,spoofed_value",
        [
            ("X-Forwarded-For", "1.2.3.4"),
            ("X-Real-IP", "1.2.3.4"),
            ("Forwarded", "for=1.2.3.4"),
            ("X-Cluster-Client-Ip", "1.2.3.4"),
            ("X-Originating-IP", "1.2.3.4"),
            ("True-Client-Ip", "1.2.3.4"),
            ("CF-Connecting-IP", "1.2.3.4"),
        ],
    )
    def test_no_spoofing_header_changes_bucket(self, spoofed_header, spoofed_value):
        legit = _make_request(client_host="192.0.2.10")
        spoofed = _make_request(
            client_host="192.0.2.10",
            headers=[(spoofed_header, spoofed_value)],
        )
        assert rate_limit_key(legit) == rate_limit_key(spoofed), (
            f"spoofed {spoofed_header!r}={spoofed_value!r} changed the bucket"
        )

    def test_real_spoofing_attempt_keeps_bucket_stable(self):
        """An attacker sends 100 different X-Forwarded-For values;
        all 100 requests land in the same bucket (so the rate limit
        still fires after 200 attempts)."""
        legit = _make_request(client_host="192.0.2.10")
        base_bucket = rate_limit_key(legit)
        for i in range(100):
            spoofed = _make_request(
                client_host="192.0.2.10",
                headers=[("X-Forwarded-For", f"10.0.0.{i}")],
            )
            assert rate_limit_key(spoofed) == base_bucket
