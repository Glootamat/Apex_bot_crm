"""Authenticated web API and PWA shell for Apex CRM."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import Database


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web" / "static"
load_dotenv(BASE_DIR / ".env")

db = Database(BASE_DIR / "workshop.sqlite3")
app = FastAPI(title="Apex CRM", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

COOKIE_NAME = "apex_crm_session"
SESSION_SECONDS = 12 * 60 * 60


class LoginRequest(BaseModel):
    username: str
    password: str


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))


def verify_password(password: str, encoded: str) -> bool:
    """Verify pbkdf2_sha256$iterations$salt$digest password format."""
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64decode(raw_salt), iterations
        )
        return hmac.compare_digest(digest, _b64decode(raw_digest))
    except (TypeError, ValueError):
        return False


def _session_secret() -> bytes:
    value = os.getenv("PWA_SESSION_SECRET", "")
    if len(value) < 32:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "PWA authentication is not configured"
        )
    return value.encode("utf-8")


def make_session(username: str) -> str:
    payload = json.dumps(
        {"sub": username, "exp": int(time.time()) + SESSION_SECONDS},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256)
    return encoded + "." + base64.urlsafe_b64encode(signature.digest()).rstrip(b"=").decode("ascii")


def session_username(session: str | None) -> str | None:
    if not session or "." not in session:
        return None
    encoded, raw_signature = session.split(".", 1)
    expected = hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64decode(raw_signature)):
        return None
    try:
        payload = json.loads(_b64decode(encoded))
        if int(payload["exp"]) <= int(time.time()):
            return None
        return str(payload["sub"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def require_user(session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None) -> str:
    username = session_username(session)
    if username is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return username


def owner_telegram_id() -> int:
    try:
        return int(os.environ["ADMIN_ID"])
    except (KeyError, ValueError) as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "CRM owner is not configured") from error


@app.get("/health")
def health() -> dict[str, str]:
    connection = db.connect()
    try:
        connection.execute("SELECT 1").fetchone()
    finally:
        connection.close()
    return {"status": "ok"}


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/login")
def login(data: LoginRequest, response: Response) -> dict[str, str]:
    expected_user = os.getenv("PWA_ADMIN_USER", "admin")
    expected_password = os.getenv("PWA_PASSWORD_HASH", "")
    if not (
        secrets.compare_digest(data.username, expected_user)
        and verify_password(data.password, expected_password)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    cookie_secure = os.getenv("PWA_COOKIE_SECURE", "true").casefold() not in {
        "0", "false", "no", "нет",
    }
    response.set_cookie(
        COOKIE_NAME, make_session(expected_user), max_age=SESSION_SECONDS,
        httponly=True, secure=cookie_secure, samesite="strict", path="/",
    )
    return {"status": "ok"}


@app.post("/api/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(_: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    telegram_id = owner_telegram_id()
    report = db.get_report_for_telegram_user(telegram_id)
    orders = db.get_recent_orders_for_telegram_user(telegram_id, limit=100)
    appointments = db.get_upcoming_appointments_for_telegram_user(telegram_id, limit=20)
    active = [order for order in orders if order.status == "in_progress"]
    return {
        "today_profit": report.today_profit,
        "active_orders": len(active),
        "upcoming_appointments": len(appointments),
        "orders": [asdict(order) for order in active[:8]],
        "appointments": [asdict(item) for item in appointments[:8]],
    }


@app.get("/api/search")
def search(q: str, _: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Введите минимум два символа")
    return db.search(owner_telegram_id(), query)
