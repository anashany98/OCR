"""S3.2 (Sprint 3) — CSP nonce per request.

The previous security-headers middleware (see
``app.middleware.security_headers``) emits a static CSP
``script-src 'self'`` that is permissive enough for our
current SPA (which has no inline scripts — Vite injects
``<script src="/src/main.tsx">`` and that's it).

For future hardening (``style-src 'unsafe-inline'`` removal,
injected Sentry config, runtime theme switching) the
``script-src`` and ``style-src`` directives need per-request
nonces that the application can opt into:

* the backend middleware generates a fresh ``secrets.token_urlsafe``
  on every request, stores it in ``request.state.csp_nonce``,
  and embeds it in the CSP header as ``script-src 'self'
  'nonce-...'`` and ``style-src 'self' 'nonce-...'
  'unsafe-inline'`` (the latter still requires ``unsafe-inline``
  while the Tailwind setup uses runtime-injected styles, but
  the nonce lets a future migration drop the ``unsafe-inline``
  for any style block that opts in by setting the
  ``nonce-...`` attribute).
* the application reads ``request.state.csp_nonce`` to add
  the same nonce to its ``<script nonce="...">`` and
  ``<style nonce="...">`` tags.

The middleware is a separate ASGI wrapper (not a
``BaseHTTPMiddleware``) so it runs before the
``SecurityHeadersMiddleware`` and so it composes with
streaming responses. The nonces are per-request
``contextvars.ContextVar``-style state, isolated from
concurrent requests inside the same worker process.

Operators who need to keep the legacy ``csp_mode="disabled"``
behaviour for a specific deployment (e.g. to debug a
``nonce``-related breakage) can keep it: the nonce middleware
still runs and still sets ``request.state.csp_nonce``, but
the downstream ``SecurityHeadersMiddleware`` will not emit
a CSP header and so the nonce is effectively unused.
"""

from __future__ import annotations

# ``base64`` import kept for parity with the other middleware
# helpers; the CSP nonce is plain base64-urlsafe.
import base64
import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

_NONCE_KEY = "csp_nonce"


def _mint_nonce() -> str:
    """Return a fresh CSP nonce: 16 random bytes → 22-char
    base64-urlsafe string. Plenty of entropy (128 bits) for
    the CSP use case and short enough to fit in a CSP header
    without bloat.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode("ascii")


class CSPNonceMiddleware:
    """Mint a per-request CSP nonce and stash it on the request scope.

    The middleware reads ``scope["state"]`` (an empty dict
    populated by Starlette on every request) and writes
    ``state["csp_nonce"] = <random>``. Downstream middlewares
    (notably :class:`SecurityHeadersMiddleware`) read the same
    key to embed the nonce in the CSP header. Application
    code can read it via ``request.state.csp_nonce``.

    Implementation detail: the nonce is computed at
    ``http.request`` time (not at the very first ASGI call) so
    that healthcheck-style requests with no downstream
    middlewares still get a nonce (it's free) but never cause a
    CSP header to be emitted (the SecurityHeadersMiddleware is
    the one that decides what to do with the nonce).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ``state`` is a dict-like Starlette creates per
        # request; it's the same dict the ``request.state``
        # proxy reads from. Mints happen exactly once per
        # request, regardless of how many middlewares wrap
        # the app.
        state = scope.setdefault("state", {})  # type: ignore[arg-type]
        state[_NONCE_KEY] = _mint_nonce()

        # Wrap ``send`` so we can also expose the nonce in
        # the ``X-CSP-Nonce`` response header. The
        # ``Content-Security-Policy`` header carries the same
        # value; the ``X-CSP-Nonce`` header is a debugging
        # convenience for the operator who wants to verify
        # the round-trip from a ``curl`` call.
        original_send = send

        async def send_with_nonce(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-csp-nonce", state[_NONCE_KEY].encode("ascii")))
                message["headers"] = headers
            await original_send(message)

        await self.app(scope, receive, send_with_nonce)


def get_request_nonce(scope: Scope) -> str | None:
    """Return the nonce minted for the current request, or
    ``None`` if the middleware did not run (e.g. a test that
    built a request without the middleware in the stack).
    """
    state = scope.get("state", {}) if isinstance(scope, dict) else {}
    if not isinstance(state, dict):
        return None
    return state.get(_NONCE_KEY)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Settings hook: the ``csp_nonce_enabled`` flag.
# ---------------------------------------------------------------------------
# Operators who run an older Vite build that does not pass the
# nonce through to dynamic ``<style>`` tags can disable the
# nonce injection by setting ``CSP_NONCE_ENABLED=false`` in the
# environment. The default (``True``) is the safe production
# behaviour: the nonce is in the header and the static
# ``script-src 'self'`` is still emitted (the nonce is appended
# in addition, so a future ``<script nonce=...>`` tag will
# be allowed).


def is_nonce_enabled() -> bool:
    return settings.csp_nonce_enabled


__all__ = [
    "CSPNonceMiddleware",
    "get_request_nonce",
    "get_request_nonce",  # legacy alias
    "is_nonce_enabled",
]
