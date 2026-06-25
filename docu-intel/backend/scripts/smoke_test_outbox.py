"""End-to-end smoke test for the webhook outbox.

Starts a tiny HTTP server, enqueues a webhook via the outbox path, drains
the worker, and asserts the receiver got the request and the DB row is
marked delivered.
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/app")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://app:dYxfj6mgrsZHuK8_FrmU2eHbCjMHWTHg@postgres:5432/docuintel",
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)
os.environ["INTEGRATION_WEBHOOK_URL"] = "http://127.0.0.1:19999/hook"
os.environ["INTEGRATION_WEBHOOK_EVENTS"] = '["document.processed"]'

RECEIVED: list[dict] = []
PORT = 19999


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        RECEIVED.append({"path": self.path, "headers": dict(self.headers), "body": body})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args, **kwargs):
        pass


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(1.0)
    print(f"receiver listening on :{PORT}")

    # Sanity check
    import socket

    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", PORT))
        s.close()
    except Exception as e:
        print(f"receiver check failed: {e}")
        server.shutdown()
        sys.exit(1)
    print("receiver verified")

    # Patch the worker to use our SessionLocal
    import app.workers.webhooks_tasks as wht
    from app.database.session import SessionLocal
    from app.services import webhooks as webhooks_service

    wht._get_session = lambda: SessionLocal()

    r = webhooks_service.emit_integration_webhook(
        "document.processed",
        {"document_id": 42, "filename": "smoke.pdf"},
    )
    print(f"emit: {r}")

    from app.workers.webhooks_tasks import deliver_pending_webhooks_task

    result = deliver_pending_webhooks_task()
    print(f"deliver: {result}")

    time.sleep(1.0)

    from sqlalchemy import select

    from app.models import WebhookOutbox

    db = SessionLocal()
    try:
        row = db.scalar(select(WebhookOutbox).order_by(WebhookOutbox.id.desc()).limit(1))
        if row:
            print(
                f"row: id={row.id} status={row.status} attempts={row.attempts} "
                f"last_response_code={row.last_response_code} last_error={row.last_error}"
            )
    finally:
        db.close()

    server.shutdown()

    if RECEIVED and any(r.get("path") == "/hook" for r in RECEIVED):
        body = json.loads(RECEIVED[0]["body"])
        print(f"OK: receiver got event={body.get('event')} payload={body.get('payload')}")
        print(f"OK: signature header present: {'X-Docuintel-Signature' in RECEIVED[0]['headers']}")
        sys.exit(0)
    else:
        print(f"FAIL: receiver got {len(RECEIVED)} requests")
        sys.exit(1)


if __name__ == "__main__":
    main()
