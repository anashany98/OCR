"""Materialise parsed email documents as project communication records."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import getaddresses, parsedate_to_datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.project import DocumentOccurrence


def materialize_communication(db: Session, document: Document, *, text: str) -> None:
    """Materialise an email without making OCR/search depend on it.

    The source document is the immutable provenance for every message, issue
    and attachment. Reprocessing is safe: a document id or RFC Message-ID
    already present returns without adding a second thread or participant.
    """
    if document.extension not in {".msg", ".eml"}:
        return
    from app.models.communication import (
        AttachmentLink,
        CommunicationMessage,
        CommunicationParticipant,
        CommunicationThread,
        Contact,
        ProjectIssue,
        ProjectParticipant,
    )

    headers = _headers(text)
    message_id = headers.get("message_id")
    if db.scalar(select(CommunicationMessage.id).where(CommunicationMessage.document_id == document.id)):
        return
    if message_id and db.scalar(
        select(CommunicationMessage.id).where(CommunicationMessage.message_id_header == message_id)
    ):
        return
    occurrence = db.scalar(select(DocumentOccurrence).where(DocumentOccurrence.document_id == document.id).order_by(DocumentOccurrence.id))
    subject = headers.get("subject") or document.original_filename
    normalized = re.sub(r"^(re|fw|fwd)\s*:\s*", "", subject, flags=re.I).strip().lower()
    project_id = occurrence.project_id if occurrence else None
    reply_to = headers.get("in_reply_to")
    thread = None
    if reply_to:
        thread = db.scalar(select(CommunicationThread).where(CommunicationThread.message_id_header == reply_to))
    if thread is None:
        thread = db.scalar(
            select(CommunicationThread).where(
                CommunicationThread.project_id == project_id,
                CommunicationThread.subject == normalized,
            )
        )
    if thread is None:
        thread = CommunicationThread(
            subject=normalized,
            project_id=project_id,
            budget_scope_id=occurrence.budget_scope_id if occurrence else document.budget_scope_id,
            message_id_header=message_id,
            message_count=0,
        )
        db.add(thread)
        db.flush()
    sender_name, sender = _first_address(headers.get("from"))
    sender = sender or "unknown@invalid.local"
    recipients = _addresses(headers.get("to"))
    copied = _addresses(headers.get("cc"))
    message = CommunicationMessage(
        thread_id=thread.id,
        document_id=document.id,
        message_id_header=message_id,
        in_reply_to=reply_to,
        from_email=sender,
        from_name=sender_name,
        to_json=[email for _, email in recipients],
        cc_json=[email for _, email in copied],
        subject=subject,
        body_text=text,
        sent_at=_parse_sent_at(headers.get("date")),
        has_attachments=False,
    )
    db.add(message)
    db.flush()
    thread.message_count = db.scalar(
        select(func.count(CommunicationMessage.id)).where(
            CommunicationMessage.thread_id == thread.id
        )
    ) or 0
    thread.last_message_at = message.sent_at or datetime.now(UTC)
    thread.started_at = thread.started_at or message.sent_at or datetime.now(UTC)

    participants = [("from", sender_name, sender), *[("to", name, email) for name, email in recipients], *[("cc", name, email) for name, email in copied]]
    for role, name, email in participants:
        if not email:
            continue
        contact = _get_or_create_contact(db, Contact, email=email, name=name)
        if not db.scalar(
            select(CommunicationParticipant.id).where(
                CommunicationParticipant.thread_id == thread.id,
                CommunicationParticipant.contact_id == contact.id,
                CommunicationParticipant.role == role,
            )
        ):
            db.add(CommunicationParticipant(thread_id=thread.id, contact_id=contact.id, email=email, role=role))
        if project_id is not None and not db.scalar(
            select(ProjectParticipant.id).where(
                ProjectParticipant.project_id == project_id,
                ProjectParticipant.contact_id == contact.id,
                ProjectParticipant.role == _project_role(role),
            )
        ):
            db.add(ProjectParticipant(project_id=project_id, contact_id=contact.id, email=email, role=_project_role(role), role_confidence=0.9))

    attachment_count = _link_named_attachments(db, AttachmentLink, document, message.id, project_id, text)
    message.has_attachments = attachment_count > 0
    if project_id is not None and _looks_like_issue(subject, text) and not db.scalar(
        select(ProjectIssue.id).where(ProjectIssue.source_document_id == document.id)
    ):
        db.add(ProjectIssue(project_id=project_id, title=subject[:500], description=text[:4000], source_document_id=document.id))
    db.flush()


def _headers(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for key in ("subject", "from", "to", "cc", "date", "message-id", "in-reply-to"):
        match = re.search(rf"^{key}\s*:\s*(.+)$", text or "", flags=re.I | re.M)
        if match:
            found[key.replace("-", "_")] = match.group(1).strip().strip("<>")
    return found


def _addresses(value: str | None) -> list[tuple[str | None, str]]:
    return [(name or None, email.lower()) for name, email in getaddresses([value or ""]) if email]


def _first_address(value: str | None) -> tuple[str | None, str | None]:
    addresses = _addresses(value)
    return addresses[0] if addresses else (None, None)


def _parse_sent_at(value: str | None):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _get_or_create_contact(db: Session, contact_model, *, email: str, name: str | None):
    contact = db.scalar(select(contact_model).where(contact_model.email == email))
    if contact is None:
        contact = contact_model(email=email, name=name or email)
        db.add(contact)
        db.flush()
    return contact


def _project_role(role: str) -> str:
    return "cliente" if role == "from" else "otro"


def _link_named_attachments(db: Session, link_model, document: Document, message_id: int, project_id: int | None, text: str) -> int:
    names = {
        name.strip().strip('"')
        for name in re.findall(r"(?:adjunto|attachment)\s*:\s*([^\n;,]+)", text or "", flags=re.I)
        if name.strip()
    }
    if not names:
        return 0
    stmt = select(Document).where(Document.original_filename.in_(names), Document.id != document.id)
    if project_id is not None:
        stmt = stmt.join(DocumentOccurrence).where(DocumentOccurrence.project_id == project_id)
    count = 0
    for attachment in db.scalars(stmt).unique().all():
        if db.scalar(select(link_model.id).where(link_model.message_id == message_id, link_model.document_id == attachment.id)):
            continue
        db.add(link_model(message_id=message_id, document_id=attachment.id, original_filename=attachment.original_filename))
        count += 1
    return count


def _looks_like_issue(subject: str, text: str) -> bool:
    return bool(re.search(r"\b(incidencia|problema|defecto|retraso|urgente|no funciona)\b", f"{subject}\n{text}", flags=re.I))
