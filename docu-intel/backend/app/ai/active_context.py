"""CTX-2 — Active conversation context: in-memory view of the session state.

The :class:`ActiveContext` dataclass is the small, well-typed view that
the rest of the agent pipeline (intent router, scope guard, reference
resolver, confidence gates, answer formatter) reads and writes. It
mirrors the JSON blob stored in ``chat_sessions.state_json`` so the
rest of the code never has to deal with ``dict.get(..., None)`` chains.

The public surface is intentionally tiny:

* :func:`load_active_context` — read the session row, return an
  :class:`ActiveContext` (empty one when the row does not exist yet).
* :func:`save_active_context` — write an :class:`ActiveContext` back to
  the session row, creating it on first write.
* :func:`update_after_answer` — convenience helper: from the result of
  a turn (resolved document, budget number, …) update the right keys
  on the context without the orchestrator having to know the schema.

The dataclass fields are the ones the user asked for in the task brief:

* ``current_budget_number`` / ``current_budget_id``
* ``current_client_name``
* ``current_folder_path``
* ``current_document_id`` / ``current_document_path`` /
  ``current_document_type``
* ``current_invoice_number`` / ``current_order_number`` /
  ``current_delivery_note_number``
* ``last_user_intent``
* ``last_retrieved_document_ids``
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, User

logger = logging.getLogger("app.ai.active_context")


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class ActiveContext:
    """The per-session in-conversation state.

    Every field is optional: an empty context is a legitimate state
    (the user has not asked anything yet, or the first turn did not
    resolve any entity). Downstream code MUST tolerate ``None`` and
    treat it as "no constraint".
    """

    current_budget_number: str | None = None
    current_budget_id: int | None = None
    current_client_name: str | None = None
    current_folder_path: str | None = None
    current_document_id: int | None = None
    current_document_path: str | None = None
    current_document_type: str | None = None
    current_invoice_number: str | None = None
    current_order_number: str | None = None
    current_delivery_note_number: str | None = None
    last_user_intent: str | None = None
    last_retrieved_document_ids: list[int] = field(default_factory=list)

    # ----- helpers -----

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ActiveContext":
        if not payload:
            return cls()
        # Be defensive: the JSON column may contain unexpected keys
        # added by an older or newer version. Drop them silently so
        # deserialisation can never crash the agent.
        known = {f for f in cls().__dataclass_fields__}
        clean = {k: v for k, v in payload.items() if k in known}
        return cls(**clean)

    @property
    def has_budget_scope(self) -> bool:
        """True when the context pins a specific budget (number or id)."""
        return bool(self.current_budget_number or self.current_budget_id)

    def scope_filters(self) -> dict[str, Any]:
        """Map the context into a filters dict for the search service.

        Returns an empty dict when no budget is active. When a budget
        is active, prefers ``budget_scope_id`` (indexed FK) and falls
        back to ``source_path`` substring so the filter also catches
        documents that were ingested before the ``budget_scope`` row
        was created.
        """
        if not self.has_budget_scope:
            return {}
        out: dict[str, Any] = {}
        if self.current_budget_id is not None:
            out["budget_scope_id"] = int(self.current_budget_id)
        if self.current_budget_number:
            # Match by folder: most projects put the budget number in
            # the folder name (e.g. "Presupuesto 260009/"). Use a
            # LIKE on the relative source path; the column is indexed
            # via trgm (migration 0031) so the substring is fast.
            out["source_path_like"] = f"%Presupuesto {self.current_budget_number}%"
        return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def new_session_uuid() -> str:
    """Return a fresh opaque session id (UUID4 hex)."""
    return uuid.uuid4().hex


def get_or_create_session(
    db: Session, user: User | None, session_uuid: str | None
) -> tuple[ChatSession, bool]:
    """Find an existing session row or create a new one.

    Returns ``(session, created)``. The caller uses ``created`` to
    decide whether the first-turn state should be inserted in a
    separate transaction.
    """
    if not session_uuid:
        # Stateless request — caller should not have called this.
        # We still create a brand-new session to keep the call simple
        # but we return ``created=True`` so the API can choose to
        # discard it.
        session_uuid = new_session_uuid()
    stmt = select(ChatSession).where(ChatSession.session_uuid == session_uuid)
    if user is not None:
        stmt = stmt.where(ChatSession.user_id == user.id)
    row = db.scalar(stmt)
    if row is not None:
        return row, False
    row = ChatSession(
        user_id=user.id if user is not None else None,
        session_uuid=session_uuid,
        state_json={},
    )
    db.add(row)
    db.flush()
    return row, True


def load_active_context(
    db: Session, user: User | None, session_uuid: str | None
) -> ActiveContext:
    """Return the :class:`ActiveContext` for the session, or empty one."""
    if not session_uuid:
        return ActiveContext()
    stmt = select(ChatSession).where(ChatSession.session_uuid == session_uuid)
    if user is not None:
        stmt = stmt.where(ChatSession.user_id == user.id)
    row = db.scalar(stmt)
    if row is None:
        return ActiveContext()
    return ActiveContext.from_dict(row.state_json or {})


def save_active_context(
    db: Session, user: User | None, session_uuid: str | None, ctx: ActiveContext
) -> ChatSession:
    """Persist the :class:`ActiveContext` to the session row."""
    row, _ = get_or_create_session(db, user, session_uuid)
    row.state_json = ctx.to_dict()
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Update helpers
# ---------------------------------------------------------------------------


def update_after_answer(
    ctx: ActiveContext,
    *,
    intent: str | None = None,
    resolved_document: dict | None = None,
    resolved_budget: dict | None = None,
    resolved_order: dict | None = None,
    resolved_invoice: dict | None = None,
    retrieved_document_ids: Iterable[int] | None = None,
) -> ActiveContext:
    """Mutate the context in place from the result of a turn.

    The orchestrator calls this with whatever was resolved. Empty
    arguments are a no-op so the call site stays simple. The function
    returns the same ``ctx`` so it composes with assignments.
    """
    if intent:
        ctx.last_user_intent = intent
    if resolved_document:
        doc_id = resolved_document.get("id")
        if doc_id is not None:
            ctx.current_document_id = int(doc_id)
        path = resolved_document.get("source_path")
        if path:
            ctx.current_document_path = str(path)
        doc_type = resolved_document.get("document_type")
        if doc_type:
            ctx.current_document_type = str(doc_type)
        if path and "/" in path:
            # The folder the document lives in is what we treat as
            # the active scope (it usually contains the budget name).
            ctx.current_folder_path = path.rsplit("/", 1)[0] + "/"
    if resolved_budget:
        number = resolved_budget.get("number")
        if number:
            ctx.current_budget_number = str(number)
        bid = resolved_budget.get("id")
        if bid is not None:
            ctx.current_budget_id = int(bid)
        client = resolved_budget.get("client")
        if client:
            ctx.current_client_name = str(client)
    if resolved_order:
        number = resolved_order.get("number")
        if number:
            ctx.current_order_number = str(number)
    if resolved_invoice:
        number = resolved_invoice.get("number")
        if number:
            ctx.current_invoice_number = str(number)
    if retrieved_document_ids:
        # Dedupe + keep the most recent 20 ids so the JSON column does
        # not grow unbounded across long sessions.
        seen: list[int] = []
        for did in retrieved_document_ids:
            if did is None:
                continue
            try:
                did_int = int(did)
            except (TypeError, ValueError):
                continue
            if did_int in seen:
                continue
            seen.append(did_int)
        ctx.last_retrieved_document_ids = seen[-20:]
    return ctx


def record_message(
    db: Session,
    session: ChatSession,
    *,
    role: str,
    content: str,
    intent: str | None = None,
    was_structured_hit: bool = False,
    question_id: int | None = None,
) -> ChatMessage:
    """Append a turn to ``chat_messages`` and return the new row.

    Best-effort: a failure to record a message must never break the
    chat pipeline, so we catch and log. The caller is expected to
    ``db.commit()`` at the end of the request.
    """
    try:
        msg = ChatMessage(
            session_id=session.id,
            question_id=question_id,
            role=role,
            content=content,
            intent=intent,
            was_structured_hit=was_structured_hit,
        )
        db.add(msg)
        db.flush()
        return msg
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_message failed: %s", exc)
        # Return a transient unsaved instance so the caller can keep
        # using the value without an AttributeError.
        return msg if "msg" in locals() else ChatMessage(  # type: ignore[has-type]
            session_id=session.id,
            role=role,
            content=content,
            intent=intent,
            was_structured_hit=was_structured_hit,
        )
