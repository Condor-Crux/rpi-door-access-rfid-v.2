"""
app/api/rfid_scanner.py
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_admin, get_current_admin_cookie

router = APIRouter()

_ultimo_uid: str | None = None
_uid_del_puente: bool = False  # True si fue seteado por POST (bridge), no por rfid_polling_task


def set_ultimo_uid(uid: str | None, desde_puente: bool = False):
    global _ultimo_uid, _uid_del_puente
    if desde_puente:
        _ultimo_uid = uid
        _uid_del_puente = True
    elif not _uid_del_puente:
        _ultimo_uid = uid


class UidPayload(BaseModel):
    uid: str


@router.post("/api/rfid/last", status_code=200)
def recibir_uid(payload: UidPayload, admin: str = Depends(get_current_admin)):
    """El puente_rfid.py llama este endpoint con Bearer token JWT."""
    set_ultimo_uid(payload.uid, desde_puente=True)
    return {"status": "ok"}


@router.get("/api/rfid/last")
def obtener_uid(admin: str = Depends(get_current_admin_cookie)):
    """
    El browser hace polling con cookie de sesión (igual que el resto de la web).
    Devuelve el UID y lo borra (one-shot).
    """
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    global _ultimo_uid, _uid_del_puente
    uid = _ultimo_uid
    _ultimo_uid = None
    _uid_del_puente = False
    return {"uid": uid}
