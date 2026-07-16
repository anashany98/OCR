from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.ai.active_context import get_or_create_session, record_message
from app.database.base import Base
from app.models import ChatMessage, User


def test_session_history_is_owned_and_keeps_message_order():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(email="owner@example.test", name="Owner", password_hash="hash")
    db.add(user)
    db.flush()

    session, created = get_or_create_session(db, user, "session-owner")
    assert created is True
    record_message(db, session, role="user", content="Pregunta")
    record_message(db, session, role="assistant", content="Respuesta")
    db.commit()

    stored = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
    ).all()
    assert [(item.role, item.content) for item in stored] == [
        ("user", "Pregunta"),
        ("assistant", "Respuesta"),
    ]

    same_uuid, created = get_or_create_session(db, user, "session-owner")
    assert created is False
    assert same_uuid.id == session.id
