"""Measure the actual prompt size sent to the LLM for a given question.

Replicates the context-collection + prompt-building path to see how many
tokens the prompt occupies, and whether it fits in LM Studio's loaded
context_length (8192) minus the reserved max_tokens for completion.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import json
import urllib.request

BASE = "http://localhost:8000/api/v1"


def _tok_est(text: str) -> int:
    # Same estimator used by prompts._estimate_tokens (words * 1.3).
    return int(len(text.split()) * 1.3)


def main() -> int:
    login = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                BASE + "/auth/login",
                data=json.dumps(
                    {"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"}
                ).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            timeout=60,
        ).read()
    )
    token = login["access_token"]
    docs = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                BASE + "/documents?limit=10",
                method="GET",
                headers={"Authorization": f"Bearer {token}"},
            ),
            timeout=60,
        ).read()
    )
    doc = next((d for d in docs if d.get("status") == "processed_ok"), docs[0])
    doc_id = doc["id"]

    from app.ai.prompts import (
        EXCERPT_PREVIEW_CHARS,
        MAX_CONTEXT_ITEMS_FOR_LLM,
        _PROMPT_OVERHEAD_TOKENS,
        _SYSTEM_PROMPT,
        _build_user_prompt,
        _context_line_for_ai,
        _estimate_tokens,
        build_context_text,
    )
    from app.ai.context import ContextItem, collect_context
    from app.core.config import settings
    from app.api.deps import decode_access_token
    from app.database.session import SessionLocal

    print(f"ai_max_context_tokens (budget) = {settings.ai_max_context_tokens}")
    print(f"_PROMPT_OVERHEAD_TOKENS        = {_PROMPT_OVERHEAD_TOKENS}")
    print(f"ai_max_retries / timeout       = {settings.ai_max_retries}s / {getattr(settings,'ai_request_timeout_seconds', '?')}")

    # Hit the chat once to populate context; we rebuild the prompt locally
    # by re-collecting context the same way the endpoint does. Simpler:
    # call collect_context directly.
    question = f"Que dice el documento {doc_id}? Resume lo mas importante."
    db = SessionLocal()
    try:
        from app.ai.tools import ToolCall

        tools = [ToolCall("hybrid_search", {"query": question, "filters": {"limit": 6}})]
        items, warnings, resolved = collect_context(db, tools, question)
    finally:
        db.close()

    print(f"\ncontext items collected = {len(items)}")
    context_text = build_context_text(items)
    print(f"context_text chars = {len(context_text)}  ~tokens = {_tok_est(context_text)}")
    user_prompt = _build_user_prompt(question, context_text, "Sin advertencias previas.")
    sys_tokens = _tok_est(_SYSTEM_PROMPT)
    user_tokens = _tok_est(user_prompt)
    print(f"system prompt ~tokens = {sys_tokens}")
    print(f"user prompt   ~tokens = {user_tokens}")
    total = sys_tokens + user_tokens
    print(f"TOTAL prompt  ~tokens = {total}")

    # LM Studio loaded_context_length = 8192; completion reserves max_tokens=4000.
    loaded_ctx = 8192
    max_completion = 4000
    available = loaded_ctx - max_completion
    print(f"\nLM Studio loaded_context_length = {loaded_ctx}")
    print(f"reserved for completion (max_tokens) = {max_completion}")
    print(f"available for prompt = {available}")
    if total > available:
        print(f"!! PROMPT EXCEEDS available by ~{total - available} tokens → 400 'Context size exceeded'")
    else:
        print(f"OK, prompt fits with ~{available - total} tokens to spare.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
