import csv
import datetime
import io
import json
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
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


@router.get("/ui/logs/export")
def export_logs_csv(
    event_type: str = "all",
    actor: str = "all",
    text: str = "",
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        raise HTTPException(status_code=401)

    rows = _build_query(db, event_type, actor, text, date_from, date_to).all()

    # Collect all user_ids referenced in details to resolve names in one query
    user_ids = set()
    for row in rows:
        try:
            d = json.loads(row.details) if row.details else {}
        except (ValueError, TypeError):
            d = {}
        for key in ("user_id", "previous_user_id"):
            if d.get(key):
                user_ids.add(int(d[key]))

    from app.infrastructure.models import UserModel
    user_names = {}
    if user_ids:
        for u in db.query(UserModel.id, UserModel.first_name, UserModel.last_name).filter(UserModel.id.in_(user_ids)).all():
            user_names[u.id] = f"{u.first_name} {u.last_name}"

    def _resolve(text):
        return re.sub(r"usuario #(\d+)", lambda m: user_names.get(int(m.group(1)), m.group(0)), text)

    output = io.StringIO()
    output.write("﻿")  # BOM for Excel UTF-8
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Hora", "Tipo de evento", "Actor", "Objeto", "Detalle"])
    for row in rows:
        e = _enrich(row)
        writer.writerow([
            e["date"],
            f"{e['time_hm']}:{e['time_s']}",
            e["type_label"],
            e["actor"],
            e["objeto"],
            _resolve(e["detalle"]),
        ])

    filename = f"logs_{datetime.date.today()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
