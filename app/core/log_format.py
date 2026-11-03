"""
Single source of truth for rendering audit-log entries.

Both the server-rendered log table (`/ui/logs`) and the live SSE feed funnel
through `enrich_log()`, so a row looks identical whether it arrived on page
load or was pushed the instant it happened. Output is plain JSON-serialisable
strings (no datetime objects) so the same dict can be published over SSE and
rendered by the same Jinja partial.
"""
import datetime

# icon glyph, ring/badge classes, human label — keyed by event_type
ICONS = {
    "rfid.grant":      ["✓", "bg-emerald-100 text-emerald-700 ring-emerald-200", "Acceso concedido"],
    "rfid.deny":       ["✕", "bg-rose-100 text-rose-600 ring-rose-200", "Acceso denegado"],
    "user.created":    ["+", "bg-sky-100 text-sky-700 ring-sky-200", "Usuario creado"],
    "user.deleted":    ["–", "bg-slate-100 text-slate-500 ring-slate-200", "Usuario eliminado"],
    "company.created": ["+", "bg-violet-100 text-violet-700 ring-violet-200", "Empresa creada"],
    "company.deleted": ["–", "bg-slate-100 text-slate-500 ring-slate-200", "Empresa eliminada"],
    "card.created":    ["+", "bg-cyan-100 text-cyan-700 ring-cyan-200", "Tarjeta creada"],
    "card.edited":     ["✎", "bg-amber-100 text-amber-700 ring-amber-200", "Tarjeta editada"],
    "card.recharged":  ["↑", "bg-teal-100 text-teal-700 ring-teal-200", "Créditos recargados"],
    "card.unlinked":   ["⊘", "bg-orange-100 text-orange-700 ring-orange-200", "Tarjeta desvinculada"],
    "batch.blanquear": ["⊗", "bg-rose-100 text-rose-600 ring-rose-200", "Blanqueo de tarjetas"],
}
_DEFAULT_ICON = ["•", "bg-slate-100 text-slate-500 ring-slate-200", ""]

# Human-readable event type labels (Spanish) — used by the filter dropdown
EVENT_LABELS = {
    "rfid.grant":      "Acceso concedido",
    "rfid.deny":       "Acceso denegado",
    "user.created":    "Usuario creado",
    "user.deleted":    "Usuario eliminado",
    "company.created": "Empresa creada",
    "company.deleted": "Empresa eliminada",
    "card.created":    "Tarjeta creada",
    "card.edited":     "Tarjeta editada",
    "card.recharged":  "Créditos recargados",
    "card.unlinked":   "Tarjeta desvinculada",
    "batch.blanquear": "Blanqueo de tarjetas",
}

# Event type categories for UI grouping / filtering
EVENT_CATEGORIES = {
    "rfid":      ["rfid.grant", "rfid.deny"],
    "users":     ["user.created", "user.deleted"],
    "companies": ["company.created", "company.deleted"],
    "cards":     ["card.created", "card.edited", "card.recharged", "card.unlinked", "batch.blanquear"],
}

_KEY_TYPE_LABELS = {
    "particulares": "Particular",
    "cuenta_corriente": "Cta. Cte.",
    "ticket_carga": "Ticket carga",
}

# Humanised labels for the expandable "hard data" panel
_HARD_LABELS = {
    "account_id": "Tarjeta",
    "invoice_number": "Comprobante / Ticket Nº",
    "key_type": "Tipo de llave",
    "credits": "Créditos",
    "credits_remaining": "Créditos restantes",
    "credits_before": "Créditos antes",
    "credits_after": "Créditos después",
    "amount": "Monto",
    "status": "Estado",
    "expiration_date": "Vencimiento",
    "user_id": "Usuario Nº",
    "previous_user_id": "Usuario anterior Nº",
    "company_id": "Empresa Nº",
    "company_name": "Empresa",
    "first_name": "Nombre",
    "last_name": "Apellido",
    "name": "Nombre",
    "document_type": "Tipo doc.",
    "document_number": "Documento",
    "nationality": "Nacionalidad",
    "email": "Email",
    "reason": "Motivo",
    "blanqueadas": "Blanqueadas",
    "not_found": "No encontradas",
}


def _kt(v):
    return _KEY_TYPE_LABELS.get(v, v)


def _fmt_exp(v):
    """Format an ISO expiration timestamp as 'YYYY-MM-DD HH:MM'."""
    if not v:
        return ""
    try:
        return datetime.datetime.fromisoformat(v).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(v)


def _summary_columns(event_type, d, summary):
    """Derive the (objeto, detalle) pair shown in the dense table columns."""
    et = event_type
    objeto = ""
    detalle = ""

    if et == "rfid.grant":
        objeto = d.get("account_id", "")
        parts = []
        cr = d.get("credits_remaining")
        if cr is not None:
            parts.append(f"{cr} créd. restantes")
        if d.get("key_type"):
            parts.append(_kt(d["key_type"]))
        detalle = " · ".join(parts)
    elif et == "rfid.deny":
        objeto = d.get("account_id", "")
        detalle = d.get("reason", "")
    elif et == "card.recharged":
        objeto = d.get("account_id", "")
        detalle = f"+{d.get('amount')} créd ({d.get('credits_before')} → {d.get('credits_after')})"
    elif et in ("card.created", "card.edited"):
        objeto = d.get("account_id", "")
        parts = []
        if d.get("user_id"):
            parts.append(f"usuario #{d['user_id']}")
        if d.get("status"):
            parts.append(f"estado {d['status']}")
        if d.get("credits") is not None:
            parts.append(f"{d['credits']} créd")
        if d.get("key_type"):
            parts.append(_kt(d["key_type"]))
        if d.get("invoice_number"):
            parts.append(f"ticket #{d['invoice_number']}")
        if d.get("expiration_date"):
            parts.append(f"vence {_fmt_exp(d['expiration_date'])}")
        detalle = " · ".join(parts)
    elif et == "card.unlinked":
        objeto = d.get("account_id", "")
        pu = d.get("previous_user_id")
        detalle = f"era de usuario #{pu}" if pu else ""
    elif et == "user.created":
        name = (f"{d.get('first_name', '')} {d.get('last_name', '')}").strip()
        objeto = name or d.get("name", "")
        parts = []
        if d.get("company_name"):
            parts.append(d["company_name"])
        if d.get("document_number"):
            parts.append(f"{d.get('document_type') or 'Doc'} {d['document_number']}")
        if d.get("nationality"):
            parts.append(d["nationality"])
        if d.get("email"):
            parts.append(d["email"])
        detalle = " · ".join(parts)
    elif et == "user.deleted":
        objeto = d.get("name", "") or d.get("user", "")
        if d.get("user_id"):
            detalle = f"#{d['user_id']}"
    elif et in ("company.created", "company.deleted"):
        objeto = d.get("name", "")
        if d.get("company_id"):
            detalle = f"#{d['company_id']}"
    elif et == "batch.blanquear":
        b = d.get("blanqueadas") or []
        nf = d.get("not_found") or []
        objeto = ", ".join(str(x) for x in b[:5]) + ("…" if len(b) > 5 else "")
        parts = [f"{len(b)} blanqueada(s)"]
        if nf:
            parts.append(f"{len(nf)} no encontrada(s)")
        detalle = " · ".join(parts) if b or nf else (summary or "")

    # Fallback — derive from the human summary ("X — Y")
    if not objeto and not detalle:
        s = summary or ""
        if "—" in s:
            objeto = s.split("—", 1)[1].strip()
        else:
            detalle = s

    return objeto, detalle


def _hard_pairs(event_type, d):
    """Curated, humanised key/value list for the click-to-expand panel —
    shows even the hardest data (e.g. invoice number for ticket cards)."""
    pairs = []
    for key, value in d.items():
        if value is None or value == "" or value == []:
            continue
        label = _HARD_LABELS.get(key, key.replace("_", " ").capitalize())
        if key == "key_type":
            value = _kt(value)
        elif key == "expiration_date":
            value = _fmt_exp(value)
        elif isinstance(value, list):
            value = ", ".join(str(x) for x in value)
        pairs.append([label, str(value)])
    return pairs


def enrich_log(event_type, actor, timestamp, details, summary=""):
    """Turn a raw audit record into a fully render-ready, JSON-serialisable dict.

    `timestamp` is a datetime; `details` is a dict (already parsed from JSON).
    """
    d = details or {}
    objeto, detalle = _summary_columns(event_type, d, summary)
    icon, icon_class, type_label = ICONS.get(event_type, [_DEFAULT_ICON[0], _DEFAULT_ICON[1], event_type])

    return {
        "event_type": event_type,
        "actor": actor,
        "date": timestamp.strftime("%Y-%m-%d"),
        "time_hm": timestamp.strftime("%H:%M"),
        "time_s": timestamp.strftime("%S"),
        "icon": icon,
        "icon_class": icon_class,
        "type_label": type_label,
        "objeto": objeto,
        "detalle": detalle,
        "hard": _hard_pairs(event_type, d),
    }
