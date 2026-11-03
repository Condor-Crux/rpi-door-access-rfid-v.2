from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy.orm import Session
from typing import List

from app.infrastructure.database import get_db
from app.infrastructure.models import CompanyModel
from app.domain.entities import Company
from app.core.security import get_current_admin, get_current_admin_cookie
from app.core.time import utcnow
from app.core.audit import log_audit

router = APIRouter()
templates = make_templates()


def _active_companies(db: Session):
    return db.query(CompanyModel).filter(CompanyModel.deleted_at == None).order_by(CompanyModel.id).all()


@router.get("/api/companies", response_model=List[Company])
def list_companies(
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    return _active_companies(db)


@router.post("/ui/companies/create")
def ui_create_company(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    existing = db.query(CompanyModel).filter(CompanyModel.name == name, CompanyModel.deleted_at == None).first()
    if not existing:
        new_company = CompanyModel(name=name)
        db.add(new_company)
        db.commit()
        db.refresh(new_company)
        log_audit(db, "company.created", "admin",
                  f"Empresa creada: {name}",
                  {"company_id": new_company.id, "name": name})
    companies = _active_companies(db)
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_company_list_editable.html", {"companies": companies})
    return RedirectResponse(url="/", status_code=303)


@router.post("/ui/companies/create-option")
def ui_create_company_option(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    name = name.strip()
    company = db.query(CompanyModel).filter(CompanyModel.name == name, CompanyModel.deleted_at == None).first()
    if not company:
        company = CompanyModel(name=name)
        db.add(company)
        db.commit()
        db.refresh(company)
        log_audit(db, "company.created", "admin",
                  f"Empresa creada: {name}",
                  {"company_id": company.id, "name": name})
    companies = _active_companies(db)
    return templates.TemplateResponse(
        request, "_company_options.html",
        {"companies": companies, "selected_id": company.id},
    )


@router.delete("/ui/companies/{company_id}")
def ui_delete_company(
    company_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin_cookie),
):
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    company = db.query(CompanyModel).filter(CompanyModel.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404)
    if company.name == "Particulares":
        raise HTTPException(status_code=400, detail="Particulares is protected")
    company.deleted_at = utcnow()
    db.commit()
    log_audit(db, "company.deleted", "admin",
              f"Empresa eliminada: {company.name}",
              {"company_id": company_id, "name": company.name})
    companies = _active_companies(db)
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_company_list_editable.html", {"companies": companies})
    return RedirectResponse(url="/", status_code=303)
