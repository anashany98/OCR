"""Remove legacy communication records that have no immutable source document."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models.communication import CommunicationMessage, CommunicationThread

logger = logging.getLogger("app.commands.cleanup_orphan_communications")


def cleanup_orphan_communications(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, int]:
    """Delete only messages with no source document and their empty threads.

    Docu-Intel has no user-authored communication endpoint: messages are
    materialised from ``.msg``/``.eml`` documents.  A NULL ``document_id``
    therefore means the record cannot be traced, reviewed or safely exposed
    in retrieval.  Project events/issues use ``SET NULL`` for message links,
    so removing these legacy rows preserves their independent evidence.
    """
    stats = {"messages": 0, "threads": 0, "removed_messages": 0, "removed_threads": 0}
    db = (session_factory or SessionLocal)()
    try:
        query = (
            select(CommunicationMessage)
            .where(CommunicationMessage.document_id.is_(None))
            .order_by(CommunicationMessage.id)
        )
        if limit is not None:
            query = query.limit(max(limit, 0))
        messages = list(db.scalars(query).all())
        thread_ids = {message.thread_id for message in messages}
        stats["messages"] = len(messages)
        stats["threads"] = len(thread_ids)
        if dry_run:
            return stats

        for message in messages:
            db.delete(message)
        db.flush()
        for thread_id in thread_ids:
            remaining = db.scalar(
                select(func.count(CommunicationMessage.id)).where(
                    CommunicationMessage.thread_id == thread_id
                )
            )
            if not remaining:
                thread = db.get(CommunicationThread, thread_id)
                if thread is not None:
                    db.delete(thread)
                    stats["removed_threads"] += 1
        db.commit()
        stats["removed_messages"] = len(messages)
    except Exception:
        db.rollback()
        logger.exception("orphan_communication_cleanup_failed")
        raise
    finally:
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean untraceable legacy communications")
    parser.add_argument("--execute", action="store_true", help="Persist changes; default is dry-run")
    parser.add_argument("--limit", type=int, help="Maximum messages to inspect")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(
        json.dumps(
            cleanup_orphan_communications(dry_run=not args.execute, limit=args.limit),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
