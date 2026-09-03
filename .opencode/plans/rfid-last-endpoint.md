# Plan: Crear endpoint POST /api/rfid/last

## Problema
El puente USB envía UIDs a `POST /api/rfid/last` pero ese endpoint no existe (404).

## Cambio 1: app/main.py — Exponer hardware via app.state

En la función `lifespan`, agregar antes del yield:

```python
app.state.green_led = green_led
app.state.red_led = red_led
app.state.buzzer = buzzer
app.state.relay = relay
```

## Cambio 2: app/api/endpoints.py — Nuevo endpoint

Agregar imports:
```python
from pydantic import BaseModel
from app.domain.workflows import process_swipe
from app.infrastructure.database import SessionLocal
from app.core.config import settings
```

Agregar endpoint:
```python
class RfidSwipeRequest(BaseModel):
    uid: str

@router.post("/api/rfid/last")
def rfid_swipe(
    req: RfidSwipeRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin),
):
    result = process_swipe(
        card_id=req.uid,
        db=db,
        green_led=request.app.state.green_led,
        red_led=request.app.state.red_led,
        buzzer=request.app.state.buzzer,
        relay=request.app.state.relay,
        verbose=settings.VERBOSE,
    )
    return result
```

## Verificación
1. Correr `python run.py -v` en la RPi
2. El puente debe logear "UID enviado: ..." en vez de 404
3. El dashboard muestra el evento de acceso
