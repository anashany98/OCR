"""Smoke test: reproduce the intermittent "LLM returns empty / falls back"
behaviour by asking the same question several times against a real document.

Usage (run from host, backend must be up on :8000):
    python docu-intel/backend/scripts/test_chat_intermittent.py

Prints, for each attempt: model_name, confidence, whether it fell back,
and a short excerpt of the answer. Run it a handful of times to see the
intermittent pattern.
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@local"
ADMIN_PASSWORD = "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"


def post(path: str, token: str | None, body: dict | None = None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if body is not None else "GET",
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def get(path: str, token: str):
    req = urllib.request.Request(
        BASE + path, method="GET", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> int:
    print("→ login …")
    login = post("/auth/login", None, {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    token = login["access_token"]
    print("  logged in as", login["user"].get("email") or login["user"].get("name"))

    docs = get("/documents?limit=10", token)
    if not docs:
        print("!! no documents found in the DB; nothing to ask about.")
        return 1
    # Pick the first document with OCR text.
    doc = next(
        (d for d in docs if (d.get("status") == "processed_ok")),
        docs[0],
    )
    doc_id = doc["id"]
    fname = doc.get("original_filename") or "?"
    print(f"→ using document #{doc_id} ({fname})")

    question = f"Que dice el documento {doc_id}? Resume lo mas importante."
    attempts = 6
    print(f"→ asking the SAME question {attempts} times to surface intermittency:\n")
    for i in range(1, attempts + 1):
        try:
            res = post("/ai/ask", token, {"question": question, "mode": "hybrid"})
        except Exception as exc:  # noqa: BLE001
            print(f"  #{i}: ERROR {exc}")
            continue
        model = res.get("model_name") or res.get("model") or "?"
        conf = res.get("confidence")
        answer = (res.get("answer") or "").strip().replace("\n", " ")
        fell_back = model == "backend_grounded_fallback"
        flag = "FALLBACK" if fell_back else "LLM"
        print(f"  #{i} [{flag}] model={model} conf={conf}")
        print(f"      {answer[:160]}")
    print("\n→ done. If you see a mix of [LLM] and [FALLBACK], that confirms the")
    print("  intermittent Qwen3 empty-answer failure mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
