from .permissions import private_mode
import asyncio
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from typing import Literal

import psutil
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from .integration import machine_auth
from .store import Store
from .cameras import Manager, usb_devices
from .video_settings import usb_modes, DEFAULT_SETTINGS, MIN_ROTATION_SECONDS

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "dsecret"
PRIVATE.mkdir(mode=0o700, exist_ok=True)
private_mode(PRIVATE, 0o700)
CREDENTIALS = PRIVATE / "admin.json"
if not CREDENTIALS.exists():
    password, salt = secrets.token_urlsafe(18), secrets.token_hex(16)
    CREDENTIALS.write_text(
        json.dumps(
            {
                "salt": salt,
                "hash": hashlib.scrypt(
                    password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
                ).hex(),
            }
        )
    )
    (PRIVATE / "admin-password.txt").write_text("Login: ADMIN\nHasło: " + password + "\n")
    private_mode(PRIVATE / "admin-password.txt", 0o600)
    private_mode(CREDENTIALS, 0o600)
credentials = json.loads(CREDENTIALS.read_text())
(ROOT / "logi").mkdir(exist_ok=True)
handler = RotatingFileHandler(ROOT / "logi/server.log", maxBytes=2_000_000, backupCount=3)
logging.basicConfig(
    level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
store = Store(ROOT / "data/parking.sqlite3")
sessions = {}
attempts = {}
session_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    app.state.manager = Manager(store)
    yield
    app.state.manager.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


def auth(request: Request):
    token = request.cookies.get("session", "")
    with session_lock:
        expires = sessions.get(token, 0)
    if expires < time.time():
        raise HTTPException(401, "Zaloguj się")
    if request.method not in ("GET", "HEAD"):
        if not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", "").encode(), token.encode()
        ):
            raise HTTPException(403, "Brak tokenu CSRF")
    return token


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    host = request.client.host
    now = time.time()
    with session_lock:
        failures = [t for t in attempts.get(host, []) if now - t < 300]
        attempts[host] = failures
        if len(failures) >= 8:
            raise HTTPException(429, "Zbyt wiele prób. Spróbuj za 5 minut.")
        # Record before hashing to bound concurrent login attempts too.
        failures.append(now)
    digest = hashlib.scrypt(
        body.password.encode(), salt=bytes.fromhex(credentials["salt"]), n=16384, r=8, p=1
    ).hex()
    if body.username != "ADMIN" or not hmac.compare_digest(digest, credentials["hash"]):
        raise HTTPException(401, "Nieprawidłowy login lub hasło")
    token = secrets.token_urlsafe(32)
    with session_lock:
        attempts.pop(host, None)
        for key in list(sessions):
            if sessions[key] < now:
                sessions.pop(key, None)
        sessions[token] = now + 8 * 3600
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=8 * 3600,
    )
    return {"csrf": token}


@app.get("/api/session")
def session(token=Depends(auth)):
    return {"username": "ADMIN", "csrf": token}


@app.post("/api/logout")
def logout(response: Response, token=Depends(auth)):
    with session_lock:
        sessions.pop(token, None)
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/devices", dependencies=[Depends(auth)])
def devices():
    return usb_devices()


class CameraInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str
    source: str = Field(min_length=1, max_length=2048)


@app.post("/api/cameras", dependencies=[Depends(auth)])
def add_camera(body: CameraInput):
    if body.kind == "usb":
        if body.source not in {d["source"] for d in usb_devices() if d.get("available", True)}:
            raise HTTPException(400, "Wybierz podłączone urządzenie USB")
    elif body.kind == "ip":
        url = urlparse(body.source)
        if url.scheme not in {"rtsp", "rtsps", "http", "https"} or not url.hostname:
            raise HTTPException(400, "Podaj adres RTSP lub HTTP kamery")
    else:
        raise HTTPException(400, "Nieprawidłowy typ kamery")
    try:
        camera_id = store.add_camera(body.name, body.kind, body.source)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    app.state.manager.reload()
    return {"id": camera_id}


@app.get("/api/cameras", dependencies=[Depends(auth)])
def cameras():
    return [w.snapshot() for w in list(app.state.manager.workers.values())]


class CameraSettingsInput(BaseModel):
    rotation_seconds: int | None = Field(default=None, ge=MIN_ROTATION_SECONDS, le=120)
    width: int | None = Field(default=None, ge=160, le=4096)
    height: int | None = Field(default=None, ge=120, le=2160)
    fps: float | None = Field(default=None, ge=1, le=60, allow_inf_nan=False)
    format: Literal["MJPG", "YUYV"] | None = None


@app.get("/api/cameras/{camera_id}/capabilities", dependencies=[Depends(auth)])
def capabilities(camera_id: int):
    worker = app.state.manager.workers.get(camera_id)
    if worker is None:
        raise HTTPException(404, "Nie ma takiej kamery")
    return {
        "kind": worker.config["kind"],
        "settings_supported": worker.config["kind"] == "usb"
        and not worker.config["source"].startswith("bridge:"),
        "modes": usb_modes(worker.config["source"]) if worker.config["kind"] == "usb" else [],
        "minimum_seconds": worker.minimum_seconds(),
    }


@app.put("/api/cameras/{camera_id}/settings", dependencies=[Depends(auth)])
def camera_settings(camera_id: int, body: CameraSettingsInput):
    worker = app.state.manager.workers.get(camera_id)
    if worker is None:
        raise HTTPException(404, "Nie ma takiej kamery")
    if getattr(worker, "test_video", None):
        raise HTTPException(400, "Wyłącz nagranie testowe, aby zmienić parametry USB")
    if worker.config["source"].startswith("bridge:"):
        raise HTTPException(400, "Parametry USB Windows ustaw w mostku na komputerze Windows")
    if worker.config["kind"] != "usb":
        raise HTTPException(400, "Parametry strumienia IP zmień w kamerze lub serwerze RTSP")
    current = DEFAULT_SETTINGS | worker.config.get("settings", {})
    settings = current | body.model_dump(exclude_none=True)
    minimum = worker.minimum_seconds()
    if settings["rotation_seconds"] < minimum:
        raise HTTPException(
            400, f"Minimalna tura przy obecnej szybkości analizy wynosi {minimum} s"
        )
    if any(settings[key] != current[key] for key in ("width", "height", "fps", "format")):
        modes = usb_modes(worker.config["source"])
        if not any(
            m["width"] == settings["width"]
            and m["height"] == settings["height"]
            and m["format"] == settings["format"]
            and any(abs(f - settings["fps"]) < 0.01 for f in m["fps"])
            for m in modes
        ):
            raise HTTPException(
                400, "Urządzenie nie zgłasza takiej kombinacji formatu, rozdzielczości i FPS"
            )
    store.settings(camera_id, settings)
    app.state.manager.reload()
    return {"ok": True, "settings": settings, "minimum_seconds": minimum}


class Rect(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0.01, le=1)
    h: float = Field(gt=0.01, le=1)


class Zones(BaseModel):
    arrival: Rect | list[Rect] | None = None
    departure: Rect | list[Rect] | None = None


@app.put("/api/cameras/{camera_id}/zones", dependencies=[Depends(auth)])
def zones(camera_id: int, body: Zones):
    if camera_id not in app.state.manager.workers:
        raise HTTPException(404, "Nie ma takiej kamery")
    values = body.model_dump(exclude_none=True)
    groups = {
        kind: (value if isinstance(value, list) else [value]) for kind, value in values.items()
    }
    for rectangles in groups.values():
        if len(rectangles) > 32:
            raise HTTPException(400, "Możesz dodać maksymalnie 32 obszary każdego koloru")
        for r in rectangles:
            if r["x"] + r["w"] > 1.0001 or r["y"] + r["h"] > 1.0001:
                raise HTTPException(400, "Obszar wychodzi poza obraz")
    for a in groups.get("arrival", []):
        for b in groups.get("departure", []):
            if max(a["x"], b["x"]) < min(a["x"] + a["w"], b["x"] + b["w"]) and max(
                a["y"], b["y"]
            ) < min(a["y"] + a["h"], b["y"] + b["h"]):
                raise HTTPException(400, "Zielone i czerwone obszary nie mogą się nakładać")
    store.zones(camera_id, values)
    app.state.manager.reload()
    return {"ok": True}


@app.delete("/api/cameras/{camera_id}", dependencies=[Depends(auth)])
def delete(camera_id: int):
    store.delete(camera_id)
    app.state.manager.reload()
    return {"ok": True}


@app.get("/api/cameras/{camera_id}/stream")
async def stream(camera_id: int, request: Request, token=Depends(auth)):
    worker = app.state.manager.workers.get(camera_id)
    if worker is None:
        raise HTTPException(404)

    async def frames():
        previous = -1
        while not worker.stop.is_set() and sessions.get(token, 0) > time.time():
            if await request.is_disconnected():
                return
            with worker.lock:
                jpeg, sequence = worker.jpeg, worker.sequence
            if jpeg and sequence != previous:
                previous = sequence
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.025)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/parking", dependencies=[Depends(auth)])
def parking():
    return (
        app.state.manager.parking_store() if hasattr(app.state.manager, "parking_store") else store
    ).parking()


@app.get("/api/events", dependencies=[Depends(auth)])
def events(after_id: int = 0):
    return {"events": store.events(max(0, after_id))}


@app.get("/api/integration/events", dependencies=[Depends(machine_auth)])
def machine_events(after_id: int = 0):
    return {"events": store.events(max(0, after_id))}


@app.get("/api/integration/parking", dependencies=[Depends(machine_auth)])
def machine_parking():
    return (
        app.state.manager.parking_store() if hasattr(app.state.manager, "parking_store") else store
    ).parking()


process = psutil.Process()
psutil.cpu_percent()


@app.get("/api/server", dependencies=[Depends(auth)])
def server():
    memory = psutil.virtual_memory()
    temperatures = psutil.sensors_temperatures()
    readings = [
        t.current
        for key, values in temperatures.items()
        if key in {"coretemp", "k10temp", "cpu_thermal"}
        for t in values
    ]
    return {
        "test_mode": bool(getattr(app.state.manager, "test_store", None))
        and app.state.manager.parking_store() is app.state.manager.test_store,
        "cpu": psutil.cpu_percent(),
        "ram_percent": memory.percent,
        "ram_used": memory.used,
        "ram_total": memory.total,
        "temperature": max(readings) if readings else None,
        "load": os.getloadavg(),
        "process_ram": process.memory_info().rss,
        "cpu_threads": psutil.cpu_count(),
        "ocr": app.state.manager.ocr_status,
    }


@app.get("/")
def index():
    return FileResponse(ROOT / "app/static/index.html")


@app.get("/assets/{filename}")
def asset(filename: str):
    if filename not in {"app.js", "style.css"}:
        raise HTTPException(404)
    return FileResponse(ROOT / "app/static" / filename)
