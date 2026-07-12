"""Materialise parsed email documents as project communication records."""
from __future__ import annotations

import re
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.project import DocumentOccurrence


def materialize_communication(db: Session, document: Document, *, text: str) -> None:
    if document.extension not in {".msg", ".eml"}:
        return
    from app.models.communication import CommunicationMessage, CommunicationThread
    if db.scalar(select(CommunicationMessage.id).where(CommunicationMessage.document_id == document.id)):
        return
    headers = _headers(text)
    occurrence = db.scalar(select(DocumentOccurrence).where(DocumentOccurrence.document_id == document.id).order_by(DocumentOccurrence.id))
    subject = headers.get("subject") or document.original_filename
    normalized = re.sub(r"^(re|fw|fwd)\s*:\s*", "", subject, flags=re.I).strip().lower()
    thread = db.scalar(select(CommunicationThread).where(CommunicationThread.project_id == (occurrence.project_id if occurrence else None), CommunicationThread.subject == normalized))
    if thread is None:
        thread = CommunicationThread(subject=normalized, project_id=occurrence.project_id if occurrence else None, budget_scope_id=occurrence.budget_scope_id if occurrence else document.budget_scope_id, message_count=0)
        db.add(thread)
        db.flush()
    sender = headers.get("from") or "unknown@invalid.local"
    message = CommunicationMessage(thread_id=thread.id, document_id=document.id, from_email=sender, from_name=headers.get("from_name"), to_json=_emails(headers.get("to")), cc_json=_emails(headers.get("cc")), subject=subject, body_text=text, has_attachments=False)
    db.add(message)
    thread.message_count += 1
    db.flush()


def _headers(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for key in ("subject", "from", "to", "cc"):
        match = re.search(rf"^{key}\s*:\s*(.+)$", text or "", flags=re.I | re.M)
        if match:
            found[key] = match.group(1).strip()
    return found


def _emails(value: str | None) -> list[str]:
    return re.findall(r"[\w.+-]+@[\w.-]+", value or "")
