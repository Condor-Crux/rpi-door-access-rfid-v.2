#!/usr/bin/env python3
"""
Seed de datos MOCK — Parador Km1151
====================================

Emula una tarde de actividad real en el Parador usando personajes de Los Simpsons.
Ejecuta la capa de servicios real del sistema (no SQL directo): crea empresas,
usuarios, tarjetas, recargas y simula swipes RFID vía `process_swipe()` con el
hardware mock. Cada paso imprime output narrativo para visualizar el flujo.

Uso:
    python scripts/seed_mock_data.py
    python scripts/seed_mock_data.py --reset   # borra la DB antes de seedear

Al terminar, abrí el panel admin para ver KPIs, tarjetas, usuarios y logs.
"""
from __future__ import annotations

import argparse
import datetime
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.audit import log_audit
from app.core.time import utcnow
from app.domain.workflows import process_swipe
from app.infrastructure.database import SessionLocal, init_db
from app.infrastructure.hardware.mock_impl import (
    MockBuzzer,
    MockDoorRelay,
    MockLedIndicator,
)
from app.infrastructure.models import (
    AccessLogModel,
    AccountModel,
    AuditLogModel,
    CompanyModel,
    UserModel,
)


# ---------- helpers de narración ----------

def banner(text: str) -> None:
    line = "═" * 72
    print(f"\n{line}\n  {text}\n{line}")


def step(text: str) -> None:
    print(f"  · {text}")


def swipe_narrate(who: str, card: str) -> None:
    print(f"\n  ◇ {who} apoya la tarjeta {card} en el lector…")


def pause(seconds: float = 0.25) -> None:
    time.sleep(seconds)


# ---------- operaciones reales del sistema ----------
# Replican la lógica de los endpoints FastAPI llamando las mismas utilidades
# (`log_audit`, modelos ORM). No se inserta nada saltándose el audit trail.

def create_company(db, name: str) -> CompanyModel:
    company = CompanyModel(name=name)
    db.add(company)
    db.commit()
    db.refresh(company)
    log_audit(db, "company.created", "admin",
              f"Empresa creada — {name}",
              {"company_id": company.id, "name": name})
    step(f"Empresa creada: {name} (id={company.id})")
    return company


def create_user(db, first: str, last: str, email: str, company: CompanyModel,
                document_type: str = "DNI", document_number: str | None = None,
                nationality: str = "AR") -> UserModel:
    user = UserModel(
        first_name=first, last_name=last, email=email or None, company_id=company.id,
        document_type=document_type, document_number=document_number,
        nationality=nationality,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit(db, "user.created", "admin",
              f"Usuario creado — {first} {last}",
              {"user_id": user.id, "name": f"{first} {last}", "company": company.name,
               "document_type": document_type, "document_number": document_number,
               "nationality": nationality})
    step(f"Usuario creado: {first} {last} [{nationality} {document_type} {document_number or '—'}] → {company.name}")
    return user


def issue_card(db, uid: str, user: UserModel | None, credits: int,
               status: str = "active", expires_in_days: int = 365,
               key_type: str = "particulares",
               invoice_number: int | None = None) -> AccountModel:
    expiration = utcnow() + datetime.timedelta(days=expires_in_days)
    if key_type != "ticket_carga":
        invoice_number = None
    card = AccountModel(
        account_id=uid,
        status=status,
        expiration_date=expiration,
        credits=credits,
        user_id=user.id if user else None,
        key_type=key_type,
        invoice_number=invoice_number,
    )
    db.add(card)
    db.commit()
    owner = f"{user.first_name} {user.last_name}" if user else "sin asignar"
    log_audit(db, "card.created", "admin",
              f"Tarjeta emitida — {uid} ({owner})",
              {"account_id": uid, "user": owner, "credits": credits,
               "status": status, "expires": expiration.isoformat(),
               "key_type": key_type, "invoice_number": invoice_number})
    extra = ""
    kt_label = {"particulares": "particular", "cuenta_corriente": "cta. cte.",
                "ticket_carga": "ticket carga"}.get(key_type, key_type)
    extra += f"  [{kt_label}]"
    if key_type == "ticket_carga" and invoice_number is not None:
        extra += f"  [ticket #{invoice_number}]"
    if status != "active":
        extra += f"  [estado={status}]"
    if expires_in_days < 0:
        extra += "  [VENCIDA]"
    step(f"Tarjeta {uid} → {owner}  (créditos={credits}){extra}")
    return card


def recharge_card(db, uid: str, amount: int) -> None:
    card = db.query(AccountModel).filter(AccountModel.account_id == uid).first()
    before = card.credits
    card.credits += amount
    db.commit()
    log_audit(db, "card.recharged", "admin",
              f"Recarga — tarjeta {uid} +{amount} créditos",
              {"account_id": uid, "amount": amount,
               "credits_before": before, "credits_after": card.credits})
    step(f"Recarga: {uid}  {before} → {card.credits} créditos  (+{amount})")


# ---------- setup hardware mock ----------

def build_mock_hw():
    return dict(
        green_led=MockLedIndicator("green"),
        red_led=MockLedIndicator("red"),
        buzzer=MockBuzzer(),
        relay=MockDoorRelay(),
    )


def swipe(db, hw, card_uid: str) -> dict:
    # El sleep de 1s dentro de deny_access() lo dejamos vivo — emula el feedback real.
    return process_swipe(card_uid, db, **hw, verbose=False)


# ---------- reset opcional ----------

def reset_database() -> None:
    db_file = ROOT / "rpi_door_access.db"
    for suffix in ("", "-wal", "-shm"):
        path = db_file.with_name(db_file.name + suffix) if suffix else db_file
        if path.exists():
            path.unlink()
            print(f"  · Borrado: {path.name}")


# ---------- guión principal ----------

def main(reset: bool) -> None:
    if reset:
        banner("RESET — borrando base de datos existente")
        reset_database()

    init_db()

    banner("PARADOR KM1151 — seed de datos MOCK (Los Simpsons)")
    print("  Viernes por la tarde. El parador abre en media hora.")
    print("  El operador empieza a cargar el sistema desde el panel admin.\n")
    pause(0.5)

    db = SessionLocal()
    try:
        # ---------------- FASE 1: empresas ----------------
        banner("FASE 1 — Alta de empresas")
        familia = create_company(db, "Familia Simpson")
        planta = create_company(db, "Planta Nuclear de Springfield")
        moe_bar = create_company(db, "Bar de Moe")
        particulares = db.query(CompanyModel).filter_by(name="Particulares").first()
        pause()

        # ---------------- FASE 2: usuarios ----------------
        banner("FASE 2 — Alta de usuarios")
        homer = create_user(db, "Homer", "Simpson", "homer@snpp.com", planta,
                            document_number="20123456", nationality="AR")
        marge = create_user(db, "Marge", "Simpson", "marge@simpson.com", familia,
                            document_number="21234567", nationality="AR")
        bart = create_user(db, "Bart", "Simpson", "elbarto@gmail.com", familia,
                           document_number="45678901", nationality="AR")
        lisa = create_user(db, "Lisa", "Simpson", "lisa@saxo.org", familia,
                           document_number="46789012", nationality="AR")
        maggie = create_user(db, "Maggie", "Simpson", "", familia,
                             document_number="55123456", nationality="AR")
        ned = create_user(db, "Ned", "Flanders", "ned@okilydokily.com", particulares,
                          document_type="Pasaporte", document_number="CHL7788991", nationality="CL")
        moe = create_user(db, "Moe", "Szyslak", "moe@tavern.com", moe_bar,
                          document_type="Pasaporte", document_number="BR998877A", nationality="BR")
        barney = create_user(db, "Barney", "Gumble", "barney@tavern.com", moe_bar,
                             document_type="CI", document_number="4567890", nationality="UY")
        apu = create_user(db, "Apu", "Nahasapeemapetilon", "apu@kwikemart.com", particulares,
                          document_type="Pasaporte", document_number="IN1234567", nationality="OT")
        krusty = create_user(db, "Krusty", "ElPayaso", "krusty@kbbl.tv", particulares,
                             document_type="Pasaporte", document_number="PY5566778", nationality="PY")
        pause()

        # ---------------- FASE 3: tarjetas ----------------
        banner("FASE 3 — Emisión de tarjetas RFID")
        print("  (Maggie no recibe tarjeta — es bebé, usa la de Marge)\n")

        # Particulares: se les VENDEN créditos
        issue_card(db, "HOMER001", homer, credits=5, key_type="particulares")
        issue_card(db, "MARGE002", marge, credits=10, key_type="particulares")
        # Bart: tarjeta VENCIDA (ya expiró hace 2 días) — se ve en los logs como deny
        issue_card(db, "BART0003", bart, credits=3, expires_in_days=-2, key_type="particulares")
        # Cuenta corriente: se les REGALAN créditos (la empresa los cubre)
        issue_card(db, "LISA0004", lisa, credits=8, key_type="cuenta_corriente")
        issue_card(db, "NED00005", ned, credits=20, key_type="cuenta_corriente")
        # Ticket de carga: se les REGALAN créditos contra un ticket que registramos
        issue_card(db, "MOE00006", moe, credits=2, key_type="ticket_carga", invoice_number=100487)
        issue_card(db, "BARN0007", barney, credits=0, key_type="ticket_carga", invoice_number=100512)  # recargará más tarde
        # Apu: tarjeta INACTIVA
        issue_card(db, "APU00008", apu, credits=5, status="inactive", key_type="particulares")
        issue_card(db, "KRUS0009", krusty, credits=4, key_type="ticket_carga", invoice_number=100533)
        pause()

        # ---------------- FASE 4: recarga inicial ----------------
        banner("FASE 4 — Recargas de mostrador")
        recharge_card(db, "MOE00006", 3)   # Moe llega justo y recarga
        pause()

        # ---------------- FASE 5: jornada de swipes ----------------
        banner("FASE 5 — Jornada de uso del baño (swipes RFID reales)")
        hw = build_mock_hw()

        swipe_narrate("Ned Flanders (llegó primero, obvio)", "NED00005")
        swipe(db, hw, "NED00005")

        swipe_narrate("Marge Simpson (con Maggie en brazos)", "MARGE002")
        swipe(db, hw, "MARGE002")

        swipe_narrate("Bart Simpson (tarjeta vencida, no sabe)", "BART0003")
        swipe(db, hw, "BART0003")  # Expired

        swipe_narrate("Lisa Simpson", "LISA0004")
        swipe(db, hw, "LISA0004")

        swipe_narrate("Homer Simpson (sudoroso tras el turno)", "HOMER001")
        swipe(db, hw, "HOMER001")

        swipe_narrate("Apu Nahasapeemapetilon (tarjeta inactiva)", "APU00008")
        swipe(db, hw, "APU00008")  # Invalid Status

        swipe_narrate("Moe Szyslak", "MOE00006")
        swipe(db, hw, "MOE00006")

        swipe_narrate("Krusty el Payaso", "KRUS0009")
        swipe(db, hw, "KRUS0009")

        swipe_narrate("Barney (perdió su tarjeta, encuentra una en el piso)", "LOST9999")
        swipe(db, hw, "LOST9999")  # Not Found

        swipe_narrate("Homer vuelve (segunda ducha)", "HOMER001")
        swipe(db, hw, "HOMER001")

        swipe_narrate("Ned vuelve después de trotar", "NED00005")
        swipe(db, hw, "NED00005")

        swipe_narrate("Bart insiste con la misma tarjeta vencida", "BART0003")
        swipe(db, hw, "BART0003")  # Expired de nuevo

        swipe_narrate("Homer (tercera vez — está haciendo tiempo)", "HOMER001")
        swipe(db, hw, "HOMER001")

        swipe_narrate("Moe (segunda ducha — accidente con la cerveza)", "MOE00006")
        swipe(db, hw, "MOE00006")

        swipe_narrate("Krusty (segundo pase)", "KRUS0009")
        swipe(db, hw, "KRUS0009")

        swipe_narrate("Homer (cuarta vez)", "HOMER001")
        swipe(db, hw, "HOMER001")

        swipe_narrate("Marge (baño exprés)", "MARGE002")
        swipe(db, hw, "MARGE002")

        swipe_narrate("Lisa", "LISA0004")
        swipe(db, hw, "LISA0004")

        swipe_narrate("Homer (quinta — Marge ya lo mira raro)", "HOMER001")
        swipe(db, hw, "HOMER001")

        swipe_narrate("Homer otra vez, pero se quedó sin créditos", "HOMER001")
        swipe(db, hw, "HOMER001")  # Out of Credits

        # Barney recarga y entra
        print("\n  Barney cruza la calle y recarga su tarjeta:")
        recharge_card(db, "BARN0007", 5)
        swipe_narrate("Barney (tarjeta recién recargada)", "BARN0007")
        swipe(db, hw, "BARN0007")

        swipe_narrate("Moe (tercera — pero ya agotó)", "MOE00006")
        swipe(db, hw, "MOE00006")  # quizá Out of Credits

        swipe_narrate("Homer apoya una tarjeta random que encontró en el patio", "XYZ12345")
        swipe(db, hw, "XYZ12345")  # Not Found

        swipe_narrate("Ned (baño antes de irse)", "NED00005")
        swipe(db, hw, "NED00005")

        # ---------------- FASE 6: resumen ----------------
        banner("FASE 6 — Resumen del día")

        grants = db.query(AccessLogModel).filter(AccessLogModel.event_type == "grant").count()
        denies = db.query(AccessLogModel).filter(AccessLogModel.event_type == "deny").count()
        audits = db.query(AuditLogModel).count()
        users = db.query(UserModel).filter(UserModel.deleted_at.is_(None)).count()
        companies = db.query(CompanyModel).filter(CompanyModel.deleted_at.is_(None)).count()
        cards = db.query(AccountModel).count()

        print(f"  Usuarios activos         : {users}")
        print(f"  Empresas                 : {companies}")
        print(f"  Tarjetas emitidas        : {cards}")
        print(f"  Swipes concedidos        : {grants}")
        print(f"  Swipes denegados         : {denies}")
        print(f"  Eventos de auditoría     : {audits}")

        print("\n  Desglose de denegaciones:")
        from sqlalchemy import func
        rows = (
            db.query(AccessLogModel.reason, func.count(AccessLogModel.id))
            .filter(AccessLogModel.event_type == "deny")
            .group_by(AccessLogModel.reason)
            .all()
        )
        for reason, count in rows:
            print(f"    - {reason:<20s} {count}")

        banner("LISTO — abrí el panel admin y mirá las 4 pestañas")
        print("  → http://localhost:8000/admin  (usuario: admin)\n")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed mock data — Parador Km1151")
    parser.add_argument("--reset", action="store_true",
                        help="Borra la DB antes de seedear (cuidado en prod)")
    args = parser.parse_args()
    main(reset=args.reset)
