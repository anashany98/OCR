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


class AIAnswerSource(Base):
    __tablename__ = "ai_answer_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("ai_answers.id", ondelete="CASCADE"), index=True, nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    block_id: Mapped[int | None] = mapped_column(ForeignKey("document_blocks.id", ondelete="SET NULL"))
    relevance_score: Mapped[float | None] = mapped_column(Float)
    excerpt: Mapped[str | None] = mapped_column(Text)

    answer = relationship("AIAnswer", back_populates="sources")

