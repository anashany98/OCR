"""Materialise parsed email documents as project communication records."""

from __future__ import annotations

import re
from datetime import UTC, datetime, time
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
    message = db.scalar(
        select(CommunicationMessage).where(CommunicationMessage.document_id == document.id)
    )
    if message is None and message_id:
        duplicate = db.scalar(
            select(CommunicationMessage).where(CommunicationMessage.message_id_header == message_id)
        )
        # The same RFC message can be attached to a duplicate source file.
        # Keep the first immutable source instead of creating a second record.
        if duplicate is not None:
            return
    occurrence = db.scalar(
        select(DocumentOccurrence)
        .where(DocumentOccurrence.document_id == document.id)
        .order_by(DocumentOccurrence.id)
    )
    subject = headers.get("subject") or document.original_filename
    normalized = _normalise_subject(subject)
    project_id = occurrence.project_id if occurrence else None
    reply_to = headers.get("in_reply_to")
    thread = None
    if reply_to:
        parent = db.scalar(
            select(CommunicationMessage).where(CommunicationMessage.message_id_header == reply_to)
        )
        if parent is not None:
            thread = db.get(CommunicationThread, parent.thread_id)
        if thread is None:
            thread = db.scalar(
                select(CommunicationThread).where(CommunicationThread.message_id_header == reply_to)
            )
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
    old_thread_id = message.thread_id if message is not None else None
    if message is None:
        message = CommunicationMessage(
            thread_id=thread.id,
            document_id=document.id,
            from_email=sender,
            subject=subject,
        )
        db.add(message)
    message.thread_id = thread.id
    message.message_id_header = message_id
    message.in_reply_to = reply_to
    message.from_email = sender
    message.from_name = sender_name
    message.to_json = [email for _, email in recipients]
    message.cc_json = [email for _, email in copied]
    message.subject = subject
    message.body_text = text
    message.sent_at = _parse_sent_at(headers.get("date"))
    message.has_attachments = False
    db.flush()
    thread.message_count = (
        db.scalar(
            select(func.count(CommunicationMessage.id)).where(
                CommunicationMessage.thread_id == thread.id
            )
        )
        or 0
    )
    thread.last_message_at = message.sent_at or datetime.now(UTC)
    thread.started_at = thread.started_at or message.sent_at or datetime.now(UTC)

    if old_thread_id is not None and old_thread_id != thread.id:
        old_thread = db.get(CommunicationThread, old_thread_id)
        if old_thread is not None:
            old_thread.message_count = (
                db.scalar(
                    select(func.count(CommunicationMessage.id)).where(
                        CommunicationMessage.thread_id == old_thread.id
                    )
                )
                or 0
            )
            if old_thread.message_count == 0:
                db.delete(old_thread)

    participants = [
        ("from", sender_name, sender),
        *[("to", name, email) for name, email in recipients],
        *[("cc", name, email) for name, email in copied],
    ]
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
            db.add(
                CommunicationParticipant(
                    thread_id=thread.id, contact_id=contact.id, email=email, role=role
                )
            )
        if project_id is not None and not db.scalar(
            select(ProjectParticipant.id).where(
                ProjectParticipant.project_id == project_id,
                ProjectParticipant.contact_id == contact.id,
                ProjectParticipant.role == _project_role(role),
            )
        ):
            db.add(
                ProjectParticipant(
                    project_id=project_id,
                    contact_id=contact.id,
                    email=email,
                    role=_project_role(role),
                    role_confidence=0.9,
                )
            )

    attachment_count = _link_named_attachments(
        db, AttachmentLink, document, message.id, project_id, text
    )
    message.has_attachments = (
        attachment_count > 0
        or db.scalar(
            select(AttachmentLink.id).where(AttachmentLink.message_id == message.id).limit(1)
        )
        is not None
    )
    if (
        project_id is not None
        and _looks_like_issue(subject, text)
        and not db.scalar(
            select(ProjectIssue.id).where(ProjectIssue.source_document_id == document.id)
        )
    ):
        db.add(
            ProjectIssue(
                project_id=project_id,
                title=subject[:500],
                description=text[:4000],
                source_document_id=document.id,
            )
        )
    db.flush()


def _headers(text: str) -> dict[str, str]:
    """Read RFC and Spanish message headers emitted by the parsers.

    ``extract_msg`` serialises many Spanish mailboxes as ``Asunto``, ``De``,
    ``Para`` and ``Fecha``.  Those values are metadata, not body text.
    """
    found: dict[str, str] = {}
    aliases = {
        "subject": ("subject", "asunto"),
        "from": ("from", "de", "remitente"),
        "to": ("to", "para", "destinatario"),
        "cc": ("cc", "copia", "con copia"),
        "date": ("date", "fecha", "enviado"),
        "message_id": ("message-id", "message id", "id de mensaje"),
        "in_reply_to": ("in-reply-to", "in reply to", "en respuesta a"),
    }
    # Headers precede the body in parser output.  Limiting the scan avoids
    # reading a quoted historical message as the current message metadata.
    header_text = "\n".join((text or "").splitlines()[:80])
    for canonical, names in aliases.items():
        for name in names:
            match = re.search(
                rf"^{re.escape(name)}\s*:\s*(.+)$",
                header_text,
                flags=re.I | re.M,
            )
            if match:
                found[canonical] = match.group(1).strip().strip("<>")
                break
    return found


def _normalise_subject(subject: str) -> str:
    value = (subject or "").strip()
    while True:
        stripped = re.sub(r"^(?:re|fw|fwd|rv|enc)\s*:\s*", "", value, flags=re.I).strip()
        if stripped == value:
            return value.lower()
        value = stripped


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
        from app.services.dates import parse_spanish_date

        parsed_date = parse_spanish_date(value)
        return datetime.combine(parsed_date, time.min, tzinfo=UTC) if parsed_date else None


def _get_or_create_contact(db: Session, contact_model, *, email: str, name: str | None):
    contact = db.scalar(select(contact_model).where(contact_model.email == email))
    if contact is None:
        contact = contact_model(email=email, name=name or email)
        db.add(contact)
        db.flush()
    return contact


def _project_role(role: str) -> str:
    return "cliente" if role == "from" else "otro"


def _link_named_attachments(
    db: Session, link_model, document: Document, message_id: int, project_id: int | None, text: str
) -> int:
    names = _attachment_names(text)
    if not names:
        return 0
    stmt = select(Document).where(
        func.lower(Document.original_filename).in_({name.lower() for name in names}),
        Document.id != document.id,
    )
    if project_id is not None:
        stmt = stmt.join(DocumentOccurrence).where(DocumentOccurrence.project_id == project_id)
    count = 0
    for attachment in db.scalars(stmt).unique().all():
        if db.scalar(
            select(link_model.id).where(
                link_model.message_id == message_id, link_model.document_id == attachment.id
            )
        ):
            continue
        db.add(
            link_model(
                message_id=message_id,
                document_id=attachment.id,
                original_filename=attachment.original_filename,
            )
        )
        count += 1
    return count


def _attachment_names(text: str) -> set[str]:
    """Extract names from English and Spanish attachment sections."""
    lines = (text or "").splitlines()
    names: set[str] = set()
    header_re = re.compile(
        r"^\s*(?:adjuntos?|attachments?)\s*(?:\(\s*\d+\s*\))?\s*:\s*(.*)$",
        flags=re.I,
    )
    filename_re = re.compile(
        r"[\w .()\[\]{}@+\-]+\.(?:pdf|docx?|xlsx?|xlsm|png|jpe?g|tiff?|bmp|webp|dxf)",
        flags=re.I,
    )
    for index, line in enumerate(lines):
        match = header_re.match(line)
        if not match:
            continue
        candidates = [match.group(1)]
        # ``Adjuntos (2):`` may be followed by bullet names. Stop at a blank
        # line or at the next header so body prose is never treated as a file.
        for following in lines[index + 1 : index + 11]:
            if not following.strip() or re.match(r"^\s*[^:]{1,40}:\s*", following):
                break
            candidates.append(following.lstrip(" -\t"))
        for candidate in candidates:
            for filename in filename_re.findall(candidate):
                names.add(filename.strip().strip('"'))
    return names


def _looks_like_issue(subject: str, text: str) -> bool:
    return bool(
        re.search(
            r"\b(incidencia|problema|defecto|retraso|urgente|no funciona)\b",
            f"{subject}\n{text}",
            flags=re.I,
        )
    )
