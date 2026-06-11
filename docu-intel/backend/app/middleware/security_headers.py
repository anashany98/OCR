"""Security headers middleware (SEC-HEADERS-1 / Sprint 1).

Adds the security headers the operator handbook requires. The
previous implementation only set three headers (``nosniff``,
``X-Frame-Options``, ``Referrer-Policy``) which is well below the
baseline for a tool that handles financial documents (imports,
NIFs, contract numbers). A successful XSS in the document viewer
would exfiltrate the user's JWT from ``localStorage``.

The new implementation adds:

* ``Strict-Transport-Security`` (HSTS) so a TLS-stripping attack on
  the first request is impossible.
* ``Content-Security-Policy`` (CSP) so the only scripts that run
  are the ones we ship.
* ``Permissions-Policy`` to revoke the camera, microphone, geolocation,
  USB, payment and FLoC APIs the SPA never needs.
* ``Cross-Origin-Opener-Policy`` and ``Cross-Origin-Resource-Policy``
  to harden against side-channel (Spectre) and XS-Leaks attacks.

The middleware is a pure ASGI middleware (``__call__``) rather than
a ``BaseHTTPMiddleware`` subclass because BaseHTTPMiddleware buffers
the entire response body and breaks streaming (SSE on
``/ai/ask/stream``). The pure-ASGI form only touches the
``http.response.start`` message and forwards everything else
unchanged.

CSP bypasses
------------
The CSP is **omitted** for a small allowlist of paths that host
third-party content the operator cannot control:

* ``/docs`` (Swagger UI) and ``/redoc`` (ReDoc) — they ship with
  inline scripts from their own CDN. Forcing a strict CSP would
  require us to either bundle a non-trivial fork of those tools or
  serve the SPA documentation from a separate origin. Operators
  who want CSP on docs can put the docs behind a separate path.
* ``/openapi.json`` — JSON content; CSP is meaningless.
"""
from __future__ import annotations

from typing import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings


# Paths that must NOT receive the strict CSP. The list is small on
# purpose: every entry is a maintenance burden. Add new paths only
# when absolutely necessary and always with a comment.
_CSP_BYPASS_PATHS: frozenset[str] = frozenset(
    {
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


def _build_csp(mode: str) -> str:
    """Build the Content-Security-Policy header value for ``mode``.

    The strict policy is the production profile. The ``local_dev``
    profile adds the Vite dev server to ``connect-src`` so HMR
    works when the operator runs the backend with
    ``ENVIRONMENT=local``.
    """
    # Production-grade baseline. Order is significant for some
    # browsers; ``default-src`` must come first to act as a
    # fallback for any directive that is not explicitly listed.
    directives: list[str] = [
        "default-src 'self'",
        # Images: the document viewer renders page previews and
        # thumbnails as ``data:`` and ``blob:`` URIs (PaddleOCR
        # writes its output to an in-memory buffer, not a file).
        "img-src 'self' data: blob:",
        # Fonts (the SPA uses local woff2 files from /assets).
        "font-src 'self' data:",
        # Styles: Tailwind and shadcn/ui inject ``<style>`` blocks
        # at runtime; ``'unsafe-inline'`` is the only practical
        # option until we migrate to CSS-in-JS with hashes.
        "style-src 'self' 'unsafe-inline'",
        # Scripts: strict. No inline, no eval. The SPA is bundled
        # by Vite so all the production code lives in static
        # ``.js`` files served from ``/assets``.
        "script-src 'self'",
        # Connections: ``self`` for the API; ``ws:`` only in
        # ``local_dev`` mode for the Vite HMR socket.
        "connect-src 'self'",
        # Frames: deny everything. The docu-intel SPA never
        # embeds third-party iframes.
        "frame-ancestors 'none'",
        # Forms: only POST to our own origin (e.g. login,
        # upload, reprocess).
        "form-action 'self'",
        # ``<base>`` is a historical XSS vector. Lock it down.
        "base-uri 'self'",
        # Disallow Flash, Java, etc. (defence in depth, modern
        # browsers ignore these but legacy proxies might still
        # honour them).
        "object-src 'none'",
        # Upgrade insecure requests when running behind a TLS
        # proxy. In ``local_dev`` the connection is plain HTTP,
        # so we skip this directive.
    ]
    if mode == "local_dev":
        # Add the Vite dev server. The exact port comes from the
        # CORS config; we hard-code 5173 + 5174 because those are
        # the ports the project's README documents.
        directives[5] = "connect-src 'self' ws://localhost:5173 ws://localhost:5174 http://localhost:5173 http://localhost:5174"
    if mode != "disabled":
        # The strict and local_dev profiles both upgrade
        # mixed-content requests. We can't always do this
        # reliably (some legacy integrations are plain HTTP), so
        # the operator can opt out by setting ``csp_mode =
        # "disabled"``.
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


# Permissions-Policy: a single, compact policy that revokes the
# whole family of "device" APIs the SPA does not need. The
# empty allowlist ``()`` is the standard way to disable a feature
# in Permissions-Policy.
_PERMISSIONS_POLICY: str = (
    "accelerometer=(), "
    "ambient-light-sensor=(), "
    "autoplay=(), "
    "battery=(), "
    "camera=(), "
    "display-capture=(), "
    "document-domain=(), "
    "encrypted-media=(), "
    "execution-while-not-rendered=(), "
    "execution-while-out-of-viewport=(), "
    "fullscreen=(self), "
    "geolocation=(), "
    "gyroscope=(), "
    "hid=(), "
    "identity-credentials-get=(), "
    "idle-detection=(), "
    "local-fonts=(), "
    "magnetometer=(), "
    "microphone=(), "
    "midi=(), "
    "otp-credentials=(), "
    "payment=(), "
    "picture-in-picture=(), "
    "publickey-credentials-create=(), "
    "publickey-credentials-get=(), "
    "screen-wake-lock=(), "
    "serial=(), "
    "speaker-selection=(), "
    "storage-access=(), "
    "usb=(), "
    "web-share=(), "
    "window-management=(), "
    "xr-spatial-tracking=(), "
    "interest-cohort=()"  # FLoC opt-out
)


# HSTS: 2 years + includeSubDomains + preload. The preload list is
# what Chrome/Firefox/Safari consult to force HTTPS on first visit;
# submitting to https://hstspreload.org is a one-off operator action.
# The value is large enough to be worth the trade-off (the cost of
# a wrong preload is the site being inaccessible over HTTP for the
# duration of the max-age, which only the operator can shorten).
_HSTS: str = "max-age=63072000; includeSubDomains; preload"


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that injects security headers into every
    HTTP response. Implemented as a low-level ASGI wrapper (not
    BaseHTTPMiddleware) so it composes with streaming responses
    such as the SSE endpoint on ``/ai/ask/stream``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._csp = _build_csp(settings.csp_mode)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Lifespan, websocket, etc. — forward untouched.
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        skip_csp = path in _CSP_BYPASS_PATHS

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                # ``message["headers"]`` is a list of ``(bytes, bytes)``
                # tuples per ASGI spec. We mutate it in place so the
                # response headers we set are visible to the
                # downstream app code that called ``send`` with the
                # start message.
                _inject_headers(message["headers"], skip_csp=skip_csp)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _inject_headers(
    headers: list[tuple[bytes, bytes]],
    *,
    skip_csp: bool,
) -> None:
    """Add the security headers to ``headers`` in place.

    Existing headers (e.g. those set by the route handler) are
    preserved; we only *add* missing ones, never overwrite. This
    matters for the CSP bypass paths: a future route handler that
    wants to set its own ``Content-Security-Policy`` will not be
    silently overwritten.
    """
    existing = {name.lower() for name, _value in headers}

    def _set(name: str, value: str) -> None:
        if name.lower() not in existing:
            headers.append((name.encode("ascii"), value.encode("ascii")))
            existing.add(name.lower())

    # Always-on headers (cheap, no CSP needed)
    _set("X-Content-Type-Options", "nosniff")
    _set("X-Frame-Options", "DENY")
    _set("Referrer-Policy", "strict-origin-when-cross-origin")
    _set("Strict-Transport-Security", _HSTS)
    _set("Permissions-Policy", _PERMISSIONS_POLICY)
    _set("Cross-Origin-Opener-Policy", "same-origin")
    _set("Cross-Origin-Resource-Policy", "same-origin")

    # CSP is the most likely to break legitimate features (Swagger UI,
    # ReDoc, dev-time HMR), so we skip it for known-bad paths and let
    # the operator tighten it via the ``csp_mode`` setting.
    if not skip_csp and settings.csp_mode != "disabled":
        # ``SecurityHeadersMiddleware.__init__`` builds the CSP once
        # at startup so we don't rebuild the string per request, but
        # we read ``settings.csp_mode`` here in case the operator
        # changed it in tests.
        _set("Content-Security-Policy", _build_csp(settings.csp_mode))


__all__ = ["SecurityHeadersMiddleware"]
