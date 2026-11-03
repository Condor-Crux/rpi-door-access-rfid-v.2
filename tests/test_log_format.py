import datetime

import app.core.audit as audit_module
from app.core.audit import log_audit
from app.core.log_format import enrich_log
from app.infrastructure.models import AuditLogModel


def _ts():
    return datetime.datetime(2026, 6, 16, 14, 5, 9)


def test_enrich_exposes_icon_and_columns():
    e = enrich_log("rfid.grant", "system", _ts(),
                   {"account_id": "ABC1", "credits_remaining": 4, "key_type": "particulares"})
    assert e["icon"] == "✓"
    assert e["objeto"] == "ABC1"
    assert "4 créd. restantes" in e["detalle"]
    assert e["date"] == "2026-06-16" and e["time_hm"] == "14:05" and e["time_s"] == "09"


def test_ticket_invoice_surfaces_in_hard_data():
    """The hardest datum — the ticket's invoice number — must be one click away."""
    e = enrich_log("card.created", "admin", _ts(),
                   {"account_id": "T9", "key_type": "ticket_carga", "invoice_number": 5567})
    hard = dict(e["hard"])
    assert hard["Comprobante / Ticket Nº"] == "5567"
    assert hard["Tipo de llave"] == "Ticket carga"


def test_hard_data_skips_empty_values():
    e = enrich_log("card.created", "admin", _ts(),
                   {"account_id": "T9", "invoice_number": None, "user_id": ""})
    hard = dict(e["hard"])
    assert "Comprobante / Ticket Nº" not in hard
    assert hard == {"Tarjeta": "T9"}


def test_log_audit_broadcasts_audit_event(db_session, monkeypatch):
    """Every audit write pushes a live, render-ready `audit` SSE event."""
    captured = []
    monkeypatch.setattr(audit_module.broadcaster, "publish",
                        lambda event_type, data: captured.append((event_type, data)))

    log_audit(db_session, "user.created", "admin", "Usuario creado — Ana",
              {"first_name": "Ana", "last_name": "Paz", "document_number": "30111222"})

    # Persisted...
    assert db_session.query(AuditLogModel).filter_by(event_type="user.created").count() == 1
    # ...and broadcast as an enriched row.
    assert len(captured) == 1
    name, data = captured[0]
    assert name == "audit"
    assert data["icon"] == "+"
    assert data["objeto"] == "Ana Paz"
    assert ["Documento", "30111222"] in data["hard"]
