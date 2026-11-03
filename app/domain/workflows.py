from typing import Dict, Any
from sqlalchemy.orm import Session
from app.core.events import broadcaster
from app.core.time import utcnow
from app.infrastructure.models import AccountModel, AccessLogModel
from app.infrastructure.hardware.interfaces import LedIndicator, Buzzer, DoorRelay
from app.core.audit import log_audit


def _broadcast_kpi(db: Session) -> None:
    """Push recomputed KPI snapshot to all SSE subscribers. Local import avoids circular deps."""
    from app.api.stats import compute_kpi
    broadcaster.publish("kpi", compute_kpi(db).model_dump())


def log_access(db: Session, account_id: str, event_type: str, reason: str = None) -> None:
    log_entry = AccessLogModel(
        account_id=account_id,
        event_type=event_type,
        reason=reason,
        timestamp=utcnow()
    )
    db.add(log_entry)
    db.commit()

def grant_access(db: Session, account: AccountModel, green_led: LedIndicator, buzzer: Buzzer, relay: DoorRelay, verbose: bool = False) -> None:
    if verbose:
        print(f"[SWIPE] ACCESS GRANTED — account={account.account_id}, credits={account.credits} → {account.credits - 1}")
    buzzer.beep(times=1, duration=0.2)
    green_led.on()
    try:
        relay.trigger(seconds=5.0)
    finally:
        green_led.off()
    account.credits -= 1
    db.commit()
    log_access(db, account.account_id, "grant")
    log_audit(db, "rfid.grant", "system",
              f"Acceso concedido — tarjeta {account.account_id}",
              {"account_id": account.account_id, "credits_remaining": account.credits,
               "key_type": getattr(account, "key_type", None)})
    _broadcast_kpi(db)


def deny_access(db: Session, account_id: str, reason: str, red_led: LedIndicator, buzzer: Buzzer, verbose: bool = False) -> None:
    if verbose:
        print(f"[SWIPE] ACCESS DENIED — card={account_id}, reason={reason}")
    if reason == "Out of Credits":
        buzzer.beep(times=3, duration=0.2)
    else:
        buzzer.beep(times=1, duration=0.5)
    red_led.on()
    import time
    time.sleep(1.0)
    red_led.off()
    log_access(db, account_id, "deny", reason)
    log_audit(db, "rfid.deny", "system",
              f"Acceso denegado — tarjeta {account_id} ({reason})",
              {"account_id": account_id, "reason": reason})
    _broadcast_kpi(db)


def process_swipe(
    card_id: str,
    db: Session,
    green_led: LedIndicator,
    red_led: LedIndicator,
    buzzer: Buzzer,
    relay: DoorRelay,
    verbose: bool = False,
) -> Dict[str, Any]:

    if verbose:
        print(f"[SWIPE] Looking up card: {card_id}")

    account = db.query(AccountModel).filter(AccountModel.account_id == card_id).first()

    if not account:
        if verbose:
            print(f"[SWIPE] Card {card_id} not found in DB")
        deny_access(db, card_id, "Not Found", red_led, buzzer, verbose)
        return {"status": "denied", "reason": "Not Found"}

    if verbose:
        print(f"[SWIPE] Account found — id={account.account_id}, status={account.status}, credits={account.credits}, expires={account.expiration_date}")

    if account.status != "active":
        deny_access(db, card_id, "Invalid Status", red_led, buzzer, verbose)
        return {"status": "denied", "reason": "Invalid Status"}

    if account.expiration_date < utcnow():
        deny_access(db, card_id, "Expired", red_led, buzzer, verbose)
        return {"status": "denied", "reason": "Expired"}

    if account.credits <= 0:
        deny_access(db, card_id, "Out of Credits", red_led, buzzer, verbose)
        return {"status": "denied", "reason": "Out of Credits"}

    grant_access(db, account, green_led, buzzer, relay, verbose)
    return {"status": "granted"}
