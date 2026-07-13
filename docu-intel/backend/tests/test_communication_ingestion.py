from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import (
    AttachmentLink,
    CommunicationMessage,
    CommunicationParticipant,
    Document,
    HotelChain,
    ProjectIssue,
    ProjectParticipant,
)
from app.models.project import DocumentOccurrence, Project
from app.services.communication_ingestion import materialize_communication


def test_email_materialization_is_idempotent_and_source_backed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    brand = HotelChain(name="Marca")
    db.add(brand)
    db.flush()
    project = Project(year=2026, brand_id=brand.id, name="Reforma")
    attachment = Document(original_filename="plano.pdf", file_hash="attachment", source_path="/plano.pdf")
    email = Document(
        original_filename="incidencia.eml",
        file_hash="email",
        source_path="/incidencia.eml",
        extension=".eml",
    )
    db.add_all([project, attachment, email])
    db.flush()
    db.add_all([
        DocumentOccurrence(document_id=attachment.id, source_path="/plano.pdf", source_root="/", year=2026, brand_id=brand.id, project_id=project.id, original_filename="plano.pdf"),
        DocumentOccurrence(document_id=email.id, source_path="/incidencia.eml", source_root="/", year=2026, brand_id=brand.id, project_id=project.id, original_filename="incidencia.eml"),
    ])
    db.flush()
    text = """Message-ID: <case-1@example.test>
Date: Mon, 13 Jul 2026 12:00:00 +0000
From: Ana <ana@example.test>
To: Obra <obra@example.test>
Subject: Incidencia urgente en obra
Attachment: plano.pdf

Hay un problema de instalación.
"""

    materialize_communication(db, email, text=text)
    materialize_communication(db, email, text=text)
    db.commit()

    message = db.scalar(select(CommunicationMessage).where(CommunicationMessage.document_id == email.id))
    assert message is not None
    assert message.message_id_header == "case-1@example.test"
    assert message.has_attachments is True
    assert db.scalar(select(AttachmentLink).where(AttachmentLink.message_id == message.id)).document_id == attachment.id
    assert len(db.scalars(select(CommunicationParticipant)).all()) == 2
    assert len(db.scalars(select(ProjectParticipant)).all()) == 2
    assert db.scalar(select(ProjectIssue).where(ProjectIssue.source_document_id == email.id)) is not None
    assert len(db.scalars(select(CommunicationMessage)).all()) == 1


def test_image_analysis_keeps_per_label_confidence(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.image_analysis_service import analyze_image_document

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    (tmp_path / "foto.jpg").write_bytes(b"image-bytes")
    monkeypatch.setattr(settings, "files_dir", tmp_path)
    monkeypatch.setattr(
        "app.parsers.clip_classifier.classify_image_multilabel",
        lambda path: {
            "labels": [("foto_producto", 0.91), ("foto_instalacion", 0.62)],
            "primary_label": "foto_producto",
            "primary_confidence": 0.91,
        },
    )
    document = Document(
        original_filename="foto.jpg",
        file_hash="source-hash",
        source_path="/foto.jpg",
        stored_filename="foto.jpg",
    )
    db.add(document)
    db.flush()

    analysis = analyze_image_document(db, document, text="Visible")

    assert analysis is not None
    assert analysis.labels_json == ["foto_producto", "foto_instalacion"]
    assert analysis.objects_json == [
        {"kind": "classification_label", "value": "foto_producto", "confidence": 0.91},
        {"kind": "classification_label", "value": "foto_instalacion", "confidence": 0.62},
    ]
