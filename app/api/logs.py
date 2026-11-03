import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy.orm import Session

from app.infrastructure.database import get_db
from app.infrastructure.models import AuditLogModel
from app.core.security import get_current_admin_cookie
from app.core.log_format import enrich_log, EVENT_LABELS, EVENT_CATEGORIES

router = APIRouter()
templates = make_templates()

PER_PAGE = 50


def _enrich(row):
    """Adapt a DB audit row into the shared render-ready dict."""
    try:
        details = json.loads(row.details) if row.details else {}
    except (ValueError, TypeError):
        details = {}
    return enrich_log(row.event_type, row.actor, row.timestamp, details, row.summary)


def _build_query(db: Session, event_type: str, actor: str, text: str, date_from: str, date_to: str):
    query = db.query(AuditLogModel).order_by(AuditLogModel.timestamp.desc())

    if event_type and event_type != "all":
        if event_type in EVENT_CATEGORIES:
            query = query.filter(AuditLogModel.event_type.in_(EVENT_CATEGORIES[event_type]))
        else:
            query = query.filter(AuditLogModel.event_type == event_type)

    if actor and actor != "all":
        query = query.filter(AuditLogModel.actor == actor)

    if text.strip():
        pattern = f"%{text.strip()}%"
        query = query.filter(AuditLogModel.summary.ilike(pattern))

    if date_from.strip():
        try:
            dt = datetime.datetime.strptime(date_from.strip(), "%Y-%m-%d")
            query = query.filter(AuditLogModel.timestamp >= dt)
        except ValueError:
            pass

    if date_to.strip():
        try:
            dt = datetime.datetime.strptime(date_to.strip(), "%Y-%m-%d") + datetime.timedelta(days=1)
            query = query.filter(AuditLogModel.timestamp < dt)
        except ValueError:
            pass

    return query


def build_logs_context(db: Session, event_type="all", actor="all", text="",
                       date_from="", date_to="", page=1):
    """Shared context builder so the dashboard and /ui/logs render identically."""
    query = _build_query(db, event_type, actor, text, date_from, date_to)
    total = query.count()
    rows = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()

    return {
        "logs": [_enrich(r) for r in rows],
        "has_more": (page * PER_PAGE) < total,
        "next_page": page + 1,
        "total": total,
        "filters": {
            "event_type": event_type,
            "actor": actor,
            "text": text,
            "date_from": date_from,
            "date_to": date_to,
        },
        "event_labels": EVENT_LABELS,
        "event_categories": list(EVENT_CATEGORIES.keys()),
        "all_event_types": list(EVENT_LABELS.keys()),
    }


@router.get("/ui/logs", response_class=HTMLResponse)
def ui_logs(
    request: Request,
    event_type: str = "all",
    actor: str = "all",
    text: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        raise HTTPException(status_code=401)

    context = build_logs_context(db, event_type, actor, text, date_from, date_to, page)

    is_htmx = request.headers.get("HX-Request")
    template = "_logs_table.html" if is_htmx else "_tab_logs.html"
    return templates.TemplateResponse(request, template, context)
