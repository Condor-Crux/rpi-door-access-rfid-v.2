from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, Response
from app.core.templates import make_templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
import datetime
import re

from pydantic import BaseModel
from app.infrastructure.database import get_db, SessionLocal
from app.infrastructure.models import AccountModel, CompanyModel, UserModel, LoadedTicketModel
from app.domain.entities import Account
from app.domain.workflows import process_swipe
from app.core.events import broadcaster
from app.core.config import settings
from app.core.security import get_current_admin, get_current_admin_cookie
from app.core.time import utcnow
from app.core.audit import log_audit
from app.api.stats import compute_kpi
from app.api.logs import build_logs_context

router = APIRouter()
templates = make_templates()

# REST API

@router.get("/api/accounts", response_model=List[Account])
def read_accounts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    accounts = db.query(AccountModel).offset(skip).limit(limit).all()
    return accounts

@router.post("/api/accounts", response_model=Account)
def create_account(account: Account, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    db_account = db.query(AccountModel).filter(AccountModel.account_id == account.account_id).first()
    if db_account:
        raise HTTPException(status_code=400, detail="Account already exists")
    new_account = AccountModel(
        account_id=account.account_id,
        status=account.status,
        expiration_date=account.expiration_date,
        credits=account.credits,
        key_type=account.key_type,
        invoice_number=account.invoice_number if account.key_type == "ticket_carga" else None,
    )
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    return new_account

@router.put("/api/accounts/{account_id}/recharge")
def recharge_account(account_id: str, amount: int, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    db_account = db.query(AccountModel).filter(AccountModel.account_id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")
    # A cash "Pago" is available on every key_type, including ticket_carga:
    # a client may show up without their voucher (or without cuenta
    # corriente) and still needs to pay to get in.
    db_account.credits += amount
    db.commit()
    db.refresh(db_account)
    return {"status": "success", "new_credits": db_account.credits}


class RfidSwipeRequest(BaseModel):
    uid: str


@router.post("/api/rfid/last")
def rfid_swipe(
    req: RfidSwipeRequest,
    request: Request,
    admin: str = Depends(get_current_admin),
):
    with SessionLocal() as db:
        result = process_swipe(
            card_id=req.uid,
            db=db,
            green_led=request.app.state.green_led,
            red_led=request.app.state.red_led,
            buzzer=request.app.state.buzzer,
            relay=request.app.state.relay,
            verbose=settings.VERBOSE,
        )
    if result.get("reason") == "Not Found":
        broadcaster.publish("new_card", {"uid": req.uid})
    return result


# Web UI Routes

@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), admin: str = Depends(get_current_admin_cookie)):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)

    users = (
        db.query(UserModel)
        .options(joinedload(UserModel.company))
        .filter(UserModel.deleted_at == None)
        .order_by(UserModel.first_name, UserModel.last_name)
        .all()
    )
    companies = (
        db.query(CompanyModel)
        .filter(CompanyModel.deleted_at == None)
        .order_by(CompanyModel.id)
        .all()
    )
    kpi = compute_kpi(db)

    return templates.TemplateResponse(request, "index.html", {
        "users": users,
        "companies": companies,
        "kpi": kpi,
        # Seed the dashboard's live log with the most recent entries.
        **build_logs_context(db),
    })


@router.post("/ui/accounts/create")
def ui_create_account(
    request: Request,
    account_id: str = Form(...),
    status: str = Form(...),
    expiration_date: str = Form(...),
    credits: int = Form(...),
    user_id: int = Form(None),
    key_type: str = Form("particulares"),
    invoice_number: Optional[str] = Form(None),
    ticket_type: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie)
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    try:
        exp_date_obj = datetime.datetime.fromisoformat(expiration_date)
    except ValueError:
        exp_date_obj = utcnow() + datetime.timedelta(hours=24)

    invoice_number = invoice_number if key_type == "ticket_carga" else None
    ticket_type = _normalize_ticket_type(ticket_type) if key_type == "ticket_carga" else None
    if key_type == "ticket_carga":
        # A ticket de carga is always worth exactly one credit — never an
        # arbitrary, staff-entered amount. Ignore whatever the form sent.
        credits = 1
        error = _validate_ticket_fields(invoice_number, ticket_type)
        if error:
            return _invoice_conflict_response(request, db, user_id, error)

    account = db.query(AccountModel).filter(AccountModel.account_id == account_id).first()
    created = False
    if not account:
        conflict = _find_duplicate_invoice(db, key_type, invoice_number, ticket_type)
        if conflict:
            return _invoice_conflict_response(request, db, user_id, _invoice_conflict_message(db, conflict))
        account = AccountModel(
            account_id=account_id,
            status=status,
            expiration_date=exp_date_obj,
            credits=credits,
            user_id=user_id,
            key_type=key_type,
            # invoice_number/ticket_type are intentionally left unset here —
            # they used to be a denormalized "most recently loaded ticket"
            # cache on the account row, but that copy could silently go
            # stale (e.g. if a ledger row was ever removed directly in the
            # database). The ledger (LoadedTicketModel) below is now the only
            # place this is stored; anything that needs to display it reads
            # it from there, live, via _attach_ticket_history.
        )
        db.add(account)
        if key_type == "ticket_carga" and invoice_number is not None:
            # The card's first ticket is a redemption like any other — it
            # goes in the permanent ledger too, so later tickets for this
            # same llave are checked against a complete history.
            db.add(LoadedTicketModel(invoice_number=invoice_number, account_id=account_id, credits=credits,
                                      ticket_type=ticket_type))
        try:
            db.commit()
        except IntegrityError:
            # Safety net for a race with another request past the check above —
            # the DB's unique constraint on the ledger is the ultimate source of truth.
            db.rollback()
            conflict = _find_duplicate_invoice(db, key_type, invoice_number, ticket_type)
            message = _invoice_conflict_message(db, conflict) if conflict else f"El ticket #{invoice_number} ya fue cargado."
            return _invoice_conflict_response(request, db, user_id, message)
        db.refresh(account)
        created = True
        log_audit(db, "card.created", "admin",
                  f"Tarjeta creada: {account_id}" + (f" → usuario #{user_id}" if user_id else ""),
                  {"account_id": account_id, "status": status, "credits": credits,
                   "expiration_date": exp_date_obj.isoformat(), "user_id": user_id,
                   "key_type": key_type, "invoice_number": invoice_number, "ticket_type": ticket_type})
        if key_type == "ticket_carga" and invoice_number is not None:
            log_audit(db, "ticket.loaded", "admin",
                      f"Ticket {ticket_type}-{invoice_number} cargado — tarjeta {account_id} (+{credits} créditos)",
                      {"account_id": account_id, "invoice_number": invoice_number, "credits_added": credits,
                       "ticket_type": ticket_type})
    else:
        # Update existing card's user assignment
        if user_id is not None:
            account.user_id = user_id
            db.commit()
            db.refresh(account)

    if request.headers.get("HX-Request") and user_id:
        # Return updated user detail panel
        from app.infrastructure.models import AccountModel as AM
        user, accounts = _user_with_accounts(db, user_id)
        companies = db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()
        response = templates.TemplateResponse(
            request, "_user_detail_panel.html",
            {"user": user, "accounts": accounts, "companies": companies}
        )
        if created:
            response.headers["HX-Trigger"] = "account-created"
        return response

    if request.headers.get("HX-Request"):
        _attach_ticket_history(db, [account])
        response = templates.TemplateResponse(request, "_account_row.html", {"acc": account})
        if created:
            response.headers["HX-Trigger"] = "account-created"
        return response

    return RedirectResponse(url="/", status_code=303)


def _attach_ticket_history(db: Session, accounts):
    """Attaches a read-only `.ticket_history` (most recent first) and
    `.latest_ticket` (the most recent row, or None) to each account, sourced
    live from the permanent ledger (LoadedTicketModel).

    This is the single source of truth for "what ticket is currently on this
    card" — nothing is cached on AccountModel itself, so there's nothing that
    can go stale if a ledger row is ever removed directly in the database
    (outside the app, which has no delete-ticket feature by design).
    """
    for acc in accounts:
        acc.ticket_history = (
            db.query(LoadedTicketModel)
            .filter(LoadedTicketModel.account_id == acc.account_id)
            .order_by(LoadedTicketModel.created_at.desc())
            .all()
            if acc.key_type == "ticket_carga" else []
        )
        acc.latest_ticket = acc.ticket_history[0] if acc.ticket_history else None
    return accounts


def _user_with_accounts(db, user_id):
    user = (
        db.query(UserModel)
        .options(joinedload(UserModel.company))
        .filter(UserModel.id == user_id)
        .first()
    )
    if not user:
        return None, []
    accounts = (
        db.query(AccountModel)
        .filter(AccountModel.user_id == user_id)
        .order_by(AccountModel.expiration_date.desc())
        .all()
    )
    _attach_ticket_history(db, accounts)
    return user, accounts


VALID_TICKET_TYPES = {"A", "B", "Y", "R"}
TICKET_NUMBER_PATTERN = re.compile(r"^\d{8}$")  # exactly 8 digits — leading zeros are significant


def _normalize_ticket_type(ticket_type: Optional[str]) -> str:
    return (ticket_type or "").strip().upper()


def _validate_ticket_fields(invoice_number: Optional[str], ticket_type: str) -> Optional[str]:
    """Returns an error message if the ticket number/type aren't valid, else None.

    invoice_number is a string, not a number: it's an 8-character code where
    a leading zero is significant (e.g. "00012345" is a different ticket from
    "12345"), so this checks length/digits via regex rather than a numeric
    range. The 8-digit rule and the A/B/Y/R type only apply going forward —
    tickets redeemed before this validation existed are left as-is, so this
    is only ever called for new submissions (create with key_type=ticket_carga,
    or load-ticket), never retroactively against existing rows.
    """
    if invoice_number is None or not TICKET_NUMBER_PATTERN.fullmatch(invoice_number):
        return "El N° de ticket debe tener exactamente 8 dígitos."
    if ticket_type not in VALID_TICKET_TYPES:
        return "El tipo de ticket debe ser A, B, Y o R."
    return None


def _find_duplicate_invoice(
    db: Session, key_type: str, invoice_number: Optional[str], ticket_type: Optional[str]
) -> Optional[LoadedTicketModel]:
    """Looks up a prior redemption of this exact (número, tipo) pair in the
    permanent ledger.

    Global and permanent by design: a ticket de carga is a physical, one-time
    paper voucher, so a (número, tipo) pair stays "spent" forever, on
    whichever card redeemed it — regardless of that card's current status or
    user. The same número IS allowed to reappear under a different tipo
    (A-10000111 and B-10000111 are different vouchers), so both fields are
    part of the lookup. Returns None for other key_types (these fields don't
    apply to them). Every redemption is a brand new ledger row, so unlike the
    old account-scoped check, there's no "exclude this account" case to
    handle.
    """
    if key_type != "ticket_carga" or invoice_number is None:
        return None
    return db.query(LoadedTicketModel).filter(
        LoadedTicketModel.invoice_number == invoice_number,
        LoadedTicketModel.ticket_type == ticket_type,
    ).first()


def _invoice_conflict_message(db: Session, ticket: LoadedTicketModel) -> str:
    account = (
        db.query(AccountModel)
        .options(joinedload(AccountModel.user))
        .filter(AccountModel.account_id == ticket.account_id)
        .first()
    )
    owner = "sin usuario asignado"
    if account and account.user:
        owner = f"{account.user.first_name} {account.user.last_name}"
    label = f"{ticket.ticket_type}-{ticket.invoice_number}" if ticket.ticket_type else f"#{ticket.invoice_number}"
    return f"El ticket {label} ya fue cargado — tarjeta {ticket.account_id}, {owner}."


def _invoice_conflict_response(request: Request, db: Session, user_id: Optional[int], message: str):
    """Renders the conflict back into whatever the caller was expecting.

    The only live UI path that reaches this is the per-user card form (HTMX
    request carrying a user_id), so we re-render the user detail panel with
    invoice_error set. Anything else (direct API use, or the unused generic
    create modal) gets a plain 400 — there's no swap target to surface it in.
    """
    if request.headers.get("HX-Request") and user_id:
        user, accounts = _user_with_accounts(db, user_id)
        companies = db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()
        return templates.TemplateResponse(
            request, "_user_detail_panel.html",
            {"user": user, "accounts": accounts, "companies": companies, "invoice_error": message}
        )
    raise HTTPException(status_code=400, detail=message)


@router.post("/ui/accounts/{account_id}/recharge")
def ui_recharge_account(
    account_id: str,
    request: Request,
    amount: int = Form(...),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    if amount <= 0 or amount > 10000:
        raise HTTPException(status_code=400, detail="amount must be between 1 and 10000")
    account = db.query(AccountModel).filter(AccountModel.account_id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    # A cash "Pago" is available on every key_type, including ticket_carga:
    # a client may show up without their voucher (or without cuenta
    # corriente) and still needs to pay to get in. Tickets keep their own
    # separate +1-per-redemption channel (ui_load_ticket) — this is an
    # additional, independent way to add credit, not a replacement for it.
    prev_credits = account.credits
    account.credits += amount
    db.commit()
    db.refresh(account)
    log_audit(db, "card.recharged", "admin",
              f"Créditos recargados: tarjeta {account_id} (+{amount}, total {account.credits})",
              {"account_id": account_id, "amount": amount,
               "credits_before": prev_credits, "credits_after": account.credits})

    if request.headers.get("HX-Request"):
        # If called from user detail panel, return updated panel
        if account.user_id:
            user, accounts = _user_with_accounts(db, account.user_id)
            companies = db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()
            return templates.TemplateResponse(
                request, "_user_detail_panel.html",
                {"user": user, "accounts": accounts, "companies": companies}
            )
        _attach_ticket_history(db, [account])
        return templates.TemplateResponse(request, "_account_row.html", {"acc": account})

    return RedirectResponse(url="/", status_code=303)


@router.post("/ui/accounts/{account_id}/edit")
def ui_edit_account(
    account_id: str,
    request: Request,
    status: str = Form(...),
    expiration_date: str = Form(...),
    credits: int = Form(...),
    key_type: str = Form("particulares"),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    account = db.query(AccountModel).filter(AccountModel.account_id == account_id).first()
    if not account:
        raise HTTPException(status_code=404)

    # invoice_number is retired from this form: once a ticket is redeemed its
    # number and the credits it added are permanent history (see
    # LoadedTicketModel / ui_load_ticket below), not something to hand-edit.
    # account.invoice_number (the "most recently loaded ticket" display
    # field) is left untouched here.
    try:
        account.expiration_date = datetime.datetime.fromisoformat(expiration_date)
    except ValueError:
        pass
    account.status = status
    account.key_type = key_type
    if key_type != "ticket_carga":
        # For ticket_carga, credits only ever change via ui_load_ticket
        # (+1 per redeemed ticket) — this form can't set an arbitrary value.
        account.credits = credits
    db.commit()
    db.refresh(account)
    log_audit(db, "card.edited", "admin",
              f"Tarjeta editada: {account_id} — estado={status}, créditos={account.credits}",
              {"account_id": account_id, "status": status, "credits": account.credits,
               "expiration_date": account.expiration_date.isoformat(),
               "key_type": key_type})

    if request.headers.get("HX-Request") and account.user_id:
        user, accounts = _user_with_accounts(db, account.user_id)
        companies = db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()
        return templates.TemplateResponse(
            request, "_user_detail_panel.html",
            {"user": user, "accounts": accounts, "companies": companies}
        )
    return RedirectResponse(url="/", status_code=303)


@router.post("/ui/accounts/{account_id}/load-ticket")
def ui_load_ticket(
    account_id: str,
    request: Request,
    invoice_number: str = Form(...),
    ticket_type: str = Form(...),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    """Redeems one more ticket de carga onto an existing llave.

    A client can bring several tickets over time; each one is checked against
    the full permanent ledger (any card, any time) and, if it's genuinely new,
    credits exactly one unit — a ticket de carga is never worth a
    staff-entered amount, unlike a cash "Pago" or a cuenta corriente
    adjustment.
    """
    credits = 1
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    ticket_type = _normalize_ticket_type(ticket_type)
    account = db.query(AccountModel).filter(AccountModel.account_id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.key_type != "ticket_carga":
        raise HTTPException(status_code=400, detail="La tarjeta no es de tipo 'Ticket de carga'.")

    error = _validate_ticket_fields(invoice_number, ticket_type)
    if error:
        return _invoice_conflict_response(request, db, account.user_id, error)

    conflict = _find_duplicate_invoice(db, account.key_type, invoice_number, ticket_type)
    if conflict:
        return _invoice_conflict_response(request, db, account.user_id, _invoice_conflict_message(db, conflict))

    db.add(LoadedTicketModel(invoice_number=invoice_number, account_id=account_id, credits=credits,
                              ticket_type=ticket_type))
    prev_credits = account.credits
    account.credits += credits
    # Note: account.invoice_number/ticket_type are intentionally NOT updated
    # here — the ledger row just added above is the only place this is
    # stored. Whatever needs to display "the current ticket" reads it live
    # from there (see _attach_ticket_history), so it can never go stale.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conflict = _find_duplicate_invoice(db, account.key_type, invoice_number, ticket_type)
        message = _invoice_conflict_message(db, conflict) if conflict else f"El ticket #{invoice_number} ya fue cargado."
        return _invoice_conflict_response(request, db, account.user_id, message)
    db.refresh(account)
    log_audit(db, "ticket.loaded", "admin",
              f"Ticket {ticket_type}-{invoice_number} cargado — tarjeta {account_id} (+{credits}, total {account.credits})",
              {"account_id": account_id, "invoice_number": invoice_number, "credits_added": credits,
               "ticket_type": ticket_type, "credits_before": prev_credits, "credits_after": account.credits})

    if request.headers.get("HX-Request") and account.user_id:
        user, accounts = _user_with_accounts(db, account.user_id)
        companies = db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()
        return templates.TemplateResponse(
            request, "_user_detail_panel.html",
            {"user": user, "accounts": accounts, "companies": companies}
        )
    return RedirectResponse(url="/", status_code=303)


@router.delete("/ui/accounts/{account_id}")
def ui_unlink_account(
    account_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    account = db.query(AccountModel).filter(AccountModel.account_id == account_id).first()
    if not account:
        raise HTTPException(status_code=404)
    user_id = account.user_id
    account.user_id = None
    db.commit()
    log_audit(db, "card.unlinked", "admin",
              f"Tarjeta desvinculada: {account_id}" + (f" (era de usuario #{user_id})" if user_id else ""),
              {"account_id": account_id, "previous_user_id": user_id})

    if request.headers.get("HX-Request") and user_id:
        user, accounts = _user_with_accounts(db, user_id)
        companies = db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()
        return templates.TemplateResponse(
            request, "_user_detail_panel.html",
            {"user": user, "accounts": accounts, "companies": companies}
        )
    return Response(status_code=200, content="")


@router.post("/ui/accounts/blanquear")
def ui_blanquear(
    request: Request,
    account_ids: str = Form(...),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    ids = [s.strip() for s in account_ids.split(",") if s.strip()]
    updated = db.query(AccountModel).filter(AccountModel.account_id.in_(ids)).all()
    blanqueadas = [acc.account_id for acc in updated]
    for acc in updated:
        acc.user_id = None
    db.commit()
    count = len(updated)
    if ids:
        log_audit(db, "batch.blanquear", "admin",
                  f"Blanqueo de {count} tarjeta(s) — {count} de {len(ids)} encontradas",
                  {"requested": ids, "blanqueadas": blanqueadas, "not_found": [i for i in ids if i not in blanqueadas]})
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_blanquear_result.html", {"count": count, "ids": ids})
    return RedirectResponse(url="/", status_code=303)


def _render_event_html(event_name: str, data: dict) -> str | None:
    if event_name == "kpi":
        return templates.get_template("_kpi_cards.html").render(kpi=data)
    if event_name == "audit":
        # `data` is already an enrich_log() dict — render one log row.
        return templates.get_template("_log_row.html").render(e=data)
    if event_name == "new_card":
        return templates.get_template("_new_card_notification.html").render(uid=data["uid"])
    return None


def _sse_format(event_name: str, html: str) -> str:
    lines = "\n".join(f"data: {line}" for line in html.splitlines())
    return f"event: {event_name}\n{lines}\n\n"


@router.get("/sse/events")
async def sse_events(admin: str = Depends(get_current_admin_cookie)):
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async def stream():
        async for payload in broadcaster.subscribe():
            name = payload["event"]
            if name == "ping":
                yield ": ping\n\n"
                continue
            if name == "ready":
                yield "event: ready\ndata: ok\n\n"
                continue
            html = _render_event_html(name, payload["data"])
            if html is None:
                continue
            yield _sse_format(name, html)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
