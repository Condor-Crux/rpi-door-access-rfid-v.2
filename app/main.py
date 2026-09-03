import asyncio
import socket
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.infrastructure.database import init_db, SessionLocal
from app.api.endpoints import router as endpoints_router
from app.api.auth import router as auth_router
from app.api.stats import router as stats_router
from app.api.companies import router as companies_router
from app.api.users import router as users_router
from app.api.logs import router as logs_router
from app.infrastructure.hardware.factory import build_factory
from app.domain.workflows import process_swipe
from app.core.config import settings


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


init_db()

factory, platform_label = build_factory()
mode = "GPIO" if platform_label == "raspberry-pi" else "MOCK"
print(f"[BOOT] Platform: {platform_label} — hardware mode: {mode}")

reader = factory.rfid_reader()
green_led = factory.green_led()
red_led = factory.red_led()
buzzer = factory.buzzer()
relay = factory.door_relay()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.green_led = green_led
    app.state.red_led = red_led
    app.state.buzzer = buzzer
    app.state.relay = relay
    ip = _lan_ip()
    print(f"[BOOT] Admin UI: http://{ip}:8000  (platform={platform_label}, hw={mode})")
    task = asyncio.create_task(rfid_polling_task())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="RPi RFID Door Access API", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(endpoints_router)
app.include_router(stats_router)
app.include_router(companies_router)
app.include_router(users_router)
app.include_router(logs_router)


async def rfid_polling_task():
    verbose = settings.VERBOSE
    if verbose:
        print("[RFID] Polling started — waiting for cards...")

    idle_ticks = 0
    while True:
        try:
            card_id = reader.read_card()
            if card_id:
                if verbose:
                    print(f"[RFID] Card detected: {card_id}")
                with SessionLocal() as db:
                    result = process_swipe(
                        card_id=card_id,
                        db=db,
                        green_led=green_led,
                        red_led=red_led,
                        buzzer=buzzer,
                        relay=relay,
                        verbose=verbose,
                    )
                if verbose:
                    print(f"[RFID] Result: {result}")
                idle_ticks = 0
            else:
                if verbose:
                    idle_ticks += 1
                    if idle_ticks % 20 == 0:
                        print("[RFID] No card — still polling...")

            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[RFID] Error in polling loop: {e}")
            await asyncio.sleep(2.0)


