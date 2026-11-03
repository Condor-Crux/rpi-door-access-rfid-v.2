"""
Unified audit log. Every system event — RFID swipes and all admin actions —
is written here. Records are never updated or deleted.
"""
import json
from sqlalchemy.orm import Session
from app.infrastructure.models import AuditLogModel
from app.core.time import utcnow
from app.core.events import broadcaster
from app.core.log_format import enrich_log


def log_audit(
    db: Session,
    event_type: str,
    actor: str,
    summary: str,
    details: dict | None = None,
) -> None:
    ts = utcnow()
    entry = AuditLogModel(
        timestamp=ts,
        event_type=event_type,
        actor=actor,
        summary=summary,
        details=json.dumps(details, default=str) if details else None,
    )
    db.add(entry)
    db.commit()
    # Push the same enriched row every SSE-connected dashboard renders live.
    broadcaster.publish("audit", enrich_log(event_type, actor, ts, details or {}, summary))
