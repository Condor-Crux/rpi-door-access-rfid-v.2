from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from typing import List

from app.infrastructure.database import get_db
from app.infrastructure.models import UserModel, CompanyModel
from app.domain.entities import User
from app.core.security import get_current_admin, get_current_admin_cookie
from app.core.time import utcnow
from app.core.audit import log_audit
from app.api.endpoints import _user_with_accounts

router = APIRouter()
templates = make_templates()


def _active_users(db: Session):
    return (
        db.query(UserModel)
        .options(joinedload(UserModel.company))
        .filter(UserModel.deleted_at == None)
        .order_by(UserModel.first_name, UserModel.last_name)
        .all()
    )


@router.get("/api/users", response_model=List[User])
def list_users(
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    return _active_users(db)


@router.get("/ui/users/search", response_class=HTMLResponse)
def ui_search_users(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        raise HTTPException(status_code=401)
    if q.strip():
        pattern = f"%{q.strip()}%"
        users = (
            db.query(UserModel)
            .options(joinedload(UserModel.company))
            .filter(
                UserModel.deleted_at == None,
                or_(
                    UserModel.first_name.ilike(pattern),
                    UserModel.last_name.ilike(pattern),
                    UserModel.email.ilike(pattern),
                ),
            )
            .order_by(UserModel.first_name, UserModel.last_name)
            .all()
        )
    else:
        users = _active_users(db)
    return templates.TemplateResponse(request, "_user_search_results.html", {"users": users})


@router.get("/ui/users/{user_id}/detail", response_class=HTMLResponse)
def ui_user_detail(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        raise HTTPException(status_code=401)
    user, accounts = _user_with_accounts(db, user_id)
    if not user:
        raise HTTPException(status_code=404)
    companies = db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()
    return templates.TemplateResponse(
        request, "_user_detail_panel.html",
        {"user": user, "accounts": accounts, "companies": companies}
    )


@router.post("/ui/users/create")
def ui_create_user(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(""),
    company_id: int = Form(...),
    document_type: str = Form(""),
    document_number: str = Form(""),
    nationality: str = Form("AR"),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    user = UserModel(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=email.strip() or None,
        company_id=company_id,
        document_type=document_type.strip() or None,
        document_number=document_number.strip() or None,
        nationality=(nationality or "AR").strip().upper(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user = db.query(UserModel).options(joinedload(UserModel.company)).filter(UserModel.id == user.id).first()
    log_audit(db, "user.created", "admin",
              f"Usuario creado: {user.first_name} {user.last_name}",
              {"user_id": user.id, "first_name": user.first_name, "last_name": user.last_name,
               "email": user.email, "company_id": user.company_id,
               "company_name": user.company.name if user.company else None,
               "document_type": user.document_type, "document_number": user.document_number,
               "nationality": user.nationality})
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_user_row_editable.html", {"u": user})
    return RedirectResponse(url="/", status_code=303)


@router.delete("/ui/users/{user_id}")
def ui_delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404)
    name = f"{user.first_name} {user.last_name}"
    user.deleted_at = utcnow()
    db.commit()
    log_audit(db, "user.deleted", "admin",
              f"Usuario eliminado: {name}",
              {"user_id": user_id, "name": name})
    from fastapi.responses import Response
    return Response(status_code=200, content="")
