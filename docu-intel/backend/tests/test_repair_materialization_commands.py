from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.commands.cleanup_orphan_communications import cleanup_orphan_communications
from app.commands.repair_communication_materialization import (
    repair_communication_materialization,
)
from app.commands.repair_technical_extractions import repair_technical_extractions
from app.database.base import Base
from app.models import CommunicationMessage, ConstructionWorkItem, Document, DocumentPage


def _factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_communication_repair_replays_only_source_backed_email_documents():
    factory = _factory()
    db = factory()
    email = Document(
        original_filename="correo.eml",
        file_hash="repair-email",
        extension=".eml",
    )
    db.add(email)
    db.flush()
    db.add(
        DocumentPage(
            document_id=email.id,
            page_number=1,
            text="Asunto: Seguimiento\nDe: Ana <ana@example.test>\nPara: Obra <obra@example.test>",
        )
    )
    db.commit()
    db.close()

    assert repair_communication_materialization(dry_run=True, session_factory=factory) == {
        "candidates": 1,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    assert repair_communication_materialization(dry_run=False, session_factory=factory)["updated"] == 1

    db = factory()
    assert db.scalar(select(func.count(CommunicationMessage.id))) == 1


def test_technical_repair_backfills_current_medicion_type():
    factory = _factory()
    db = factory()
    document = Document(
        original_filename="mediciones.pdf",
        file_hash="repair-measurements",
        document_type="medicion",
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="1 ESTRUCTURA\n1.1 CIMENTACION\n1.1.1 Excavacion m3 45,00 12,50 562,50",
        )
    )
    db.commit()
    db.close()

    stats = repair_technical_extractions(dry_run=False, session_factory=factory)
    assert stats["updated"] == 1

    db = factory()
    assert db.scalar(select(func.count(ConstructionWorkItem.id))) == 1


def test_orphan_communication_cleanup_keeps_source_backed_messages():
    factory = _factory()
    db = factory()
    orphan = Document(
        original_filename="orphan.eml",
        file_hash="cleanup-orphan",
        extension=".eml",
    )
    source = Document(
        original_filename="source.eml",
        file_hash="cleanup-source",
        extension=".eml",
    )
    db.add_all([orphan, source])
    db.flush()
    from app.models.communication import CommunicationMessage, CommunicationThread

    orphan_thread = CommunicationThread(subject="legacy")
    source_thread = CommunicationThread(subject="source")
    db.add_all([orphan_thread, source_thread])
    db.flush()
    db.add_all([
        CommunicationMessage(thread_id=orphan_thread.id, from_email="unknown@invalid.local", subject="legacy"),
        CommunicationMessage(
            thread_id=source_thread.id,
            document_id=source.id,
            from_email="ana@example.test",
            subject="source",
        ),
    ])
    db.commit()
    source_id = source.id
    db.close()

    assert cleanup_orphan_communications(dry_run=True, session_factory=factory)["messages"] == 1
    result = cleanup_orphan_communications(dry_run=False, session_factory=factory)
    assert result["removed_messages"] == 1
    assert result["removed_threads"] == 1

    db = factory()
    remaining = list(db.scalars(select(CommunicationMessage)).all())
    assert len(remaining) == 1
    assert remaining[0].document_id == source_id
