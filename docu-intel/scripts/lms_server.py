#!/usr/bin/env python3
"""lms_server.py — host-side HTTP shim for the ``lms`` CLI.

LM Studio's CLI (``lms.exe``) only runs on the host (Windows / macOS /
Linux desktop), but our backend runs inside a Linux container and
cannot execute it directly. This small server sits on the host and
exposes a tiny JSON API that the backend can call to load / unload
vision models on demand.

Endpoints:
  GET  /status                  -> {"models": [{"id": "...", "loaded": bool}, ...]}
  POST /load    {"model": "x"}  -> runs ``lms load x``
  POST /unload  {"model": "x"}  -> runs ``lms unload x``
  GET  /health                  -> {"status": "ok"}

Run on the host with:
    python lms_server.py            # foreground
    pythonw lms_server.py           # background (Windows, no console)

Or as a Windows service / Task Scheduler task that runs on logon.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = os.environ.get("LMS_SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("LMS_SERVER_PORT", "1235"))
LMS_BIN = os.environ.get("LMS_BIN") or os.path.join(
    os.path.expanduser("~"), ".lmstudio", "bin", "lms.exe"
)
LOG_LEVEL = os.environ.get("LMS_SERVER_LOG", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] lms_server: %(message)s",
)
log = logging.getLogger("lms_server")

_lock = threading.Lock()


def _lms(*args: str, timeout: float = 180.0) -> dict[str, Any]:
    """Run the lms CLI and return a structured result."""
    if not os.path.isfile(LMS_BIN):
        return {"ok": False, "error": f"lms binary not found at {LMS_BIN}", "stdout": "", "stderr": ""}
    try:
        proc = subprocess.run(
            [LMS_BIN, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"lms {' '.join(args)} timed out after {timeout}s"}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def _parse_ps(stdout: str) -> list[dict[str, Any]]:
    """Parse ``lms ps`` output (text table) into a list of model rows.

    Best-effort: we only need to know which models are loaded, so we
    look for rows that have non-empty STATUS (i.e. anything except
    blank)."""
    models: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("identifier"):
            continue
        # Lines look like: ``qwen/qwen3-14b ... IDLE ... Local``
        parts = stripped.split()
        if not parts:
            continue
        ident = parts[0]
        # If the line contains IDLE, the model is loaded
        loaded = "idle" in stripped.lower() or "loaded" in stripped.lower()
        models.append({"id": ident, "loaded": loaded})
    return models


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok", "lms_bin": LMS_BIN})
            return
        if self.path == "/status":
            with _lock:
                result = _lms("ps", timeout=15)
            if not result["ok"]:
                self._json(500, result)
                return
            self._json(200, {"models": _parse_ps(result["stdout"])})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        try:
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "error": "invalid JSON body"})
            return

        if self.path in ("/load", "/unload"):
            model = (body or {}).get("model", "").strip()
            if not model:
                self._json(400, {"ok": False, "error": "missing 'model'"})
                return
            verb = self.path.lstrip("/")
            log.info("%s %s", verb, model)
            with _lock:
                result = _lms(verb, model, timeout=180)
            self._json(200 if result["ok"] else 500, result)
            return
        self._json(404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug(format, *args)


def main() -> int:
    log.info("lms_server starting on %s:%d (lms=%s)", HOST, PORT, LMS_BIN)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
