from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class AIQuestion(Base):
    __tablename__ = "ai_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="questions")
    answers = relationship("AIAnswer", back_populates="question", cascade="all, delete-orphan")


class AIAnswer(Base):
    __tablename__ = "ai_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("ai_questions.id", ondelete="CASCADE"), index=True, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    model_name: Mapped[str | None] = mapped_column(String(255))
    # JSON snapshot of the document the agent resolved (entities + relations).
    # Only filled when the user mentions a specific file in the question.
    resolved_document_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    question = relationship("AIQuestion", back_populates="answers")
    sources = relationship("AIAnswerSource", back_populates="answer", cascade="all, delete-orphan")
    feedbacks = relationship("AIAnswerFeedback", back_populates="answer", cascade="all, delete-orphan")


class AIAnswerSource(Base):
    __tablename__ = "ai_answer_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("ai_answers.id", ondelete="CASCADE"), index=True, nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    block_id: Mapped[int | None] = mapped_column(ForeignKey("document_blocks.id", ondelete="SET NULL"))
    relevance_score: Mapped[float | None] = mapped_column(Float)
    excerpt: Mapped[str | None] = mapped_column(Text)
    # R3 — feedback-derived multiplier. Defaults to 1.0; bumped
    # up by positive feedback and down by negative feedback via
    # :func:`app.services.feedback_loop.apply_chunk_weights`.
    # The field is read at retrieval time and applied as a
    # multiplier on the source's relevance score so the retriever
    # ranks community-endorsed chunks higher.
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False, index=True)

    answer = relationship("AIAnswer", back_populates="sources")


class AIAnswerFeedback(Base):
    """R3 — single 👍/👎 vote on an answer, optionally tagged
    with a reason + a free-form comment.

    Multiple votes per user on the same answer are allowed (the
    user can change their mind); the loop keeps only the most
    recent vote per ``(answer_id, user_id)`` pair when applying
    the weight adjustment. Anonymous feedback (no user) is
    rejected by the API layer — every vote must be tied to a
    real user so we can audit the loop and roll back spam.
    """

    __tablename__ = "ai_answer_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("ai_answers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # +1 (positive) or -1 (negative). Encoded as a small int
    # so we can keep the column indexed cheaply.
    vote: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional reason: ``"alucinacion"``, ``"fuente_incorrecta"``,
    # ``"irrelevante"``, ``"otro"``. Free-form ``Text`` so the
    # operator can extend the set without a migration.
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )

    answer = relationship("AIAnswer", back_populates="feedbacks")

