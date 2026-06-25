"""CTX-2 — Per-user chat session state for grounded, scope-aware answers.

A ``ChatSession`` is the persistence layer behind the in-conversation
"active context" (current budget, current document, last intent, …).
The state is a JSON blob so the orchestrator can read/write arbitrary
keys without schema migrations every time the LLM agent learns a new
"remember this" field.

The :class:`ChatMessage` table mirrors the question/answer pair as it
was delivered to the user, so the admin UI (and the API) can render a
chat-style history even when the user did not explicitly enable the
session-scoped UI yet. The orchestrator does not depend on this table
to resolve follow-ups — that is what :class:`ChatSession.state_json`
is for — but having the message log around makes debugging and auditing
much easier.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChatSession(Base):
    """A long-lived chat session owned by a user.

    The combination ``(user_id, session_uuid)`` is unique so two
    devices/browsers of the same user can have their own independent
    session without colliding. ``state_json`` is the live in-conversation
    context (current budget, current document, last intent, …).
    """

    __tablename__ = "chat_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "session_uuid", name="uq_chat_sessions_user_uuid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # A stable opaque identifier the client can pass back via
    # ``AskRequest.session_id``. ``None`` = the call is stateless and
    # does not contribute to any active context.
    session_uuid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # The JSON snapshot of the active conversation context. Schema is
    # documented in :mod:`app.ai.active_context` (the ``ActiveContext``
    # dataclass). Keep the column NOT NULL with a default so old rows
    # added before the column existed keep working.
    state_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Last time the session was read or written. Used by the cleanup
    # job to expire sessions the user abandoned.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id.asc()",
    )


class ChatMessage(Base):
    """A single turn inside a :class:`ChatSession`.

    The ``intent`` column records what :func:`app.ai.intent_router.classify_intent`
    classified the question as, so we can audit the router's behaviour
    after the fact. ``was_structured_hit`` records whether the
    structured-first path produced the answer (True) or whether the LLM /
    RAG was used (False).
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "question_id",
            name="uq_chat_messages_session_question",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Optional FK to ``ai_questions.id`` for cross-referencing the
    # historical answer log. Nullable so a turn recorded by tests
    # without a real AIQuestion row still works.
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_questions.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    was_structured_hit: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    session = relationship("ChatSession", back_populates="messages")
