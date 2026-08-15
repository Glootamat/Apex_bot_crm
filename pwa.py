"""Authenticated web API and PWA shell for Apex CRM."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from aiohttp import ClientError
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, field_validator
from psycopg import IntegrityError as PostgresIntegrityError

from database import Database
from diagnostic_pdf import build_diagnostic_pdf
from openrouter import OpenRouterError, analyze_receipt_image, analyze_vehicle_document
from supplier_catalog import configured_suppliers, get_profit_liga_orders, get_rossko_orders, rounded_sale_price, search_suppliers, serialize_offer


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web" / "static"
REACT_DIST_DIR = BASE_DIR / "frontend" / "dist"
WEB_DIR = REACT_DIST_DIR if (REACT_DIST_DIR / "index.html").exists() else STATIC_DIR
load_dotenv(BASE_DIR / ".env")

db = Database(BASE_DIR / "workshop.sqlite3")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Apply idempotent database migrations before serving API requests."""
    db.initialize()
    yield


app = FastAPI(title="Apex CRM", docs_url=None, redoc_url=None, lifespan=lifespan)
ASSETS_DIR = WEB_DIR / "assets" if WEB_DIR == REACT_DIST_DIR else STATIC_DIR
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
UPLOAD_DIR = BASE_DIR / "uploads" / "order_photos"
DIAGNOSTIC_UPLOAD_DIR = BASE_DIR / "uploads" / "diagnostics"

COOKIE_NAME = "apex_crm_refresh"
ACCESS_TOKEN_SECONDS = 10 * 60
REFRESH_TOKEN_SECONDS = 30 * 24 * 60 * 60
JWT_ISSUER = "apex-crm"
JWT_AUDIENCE = "apex-crm-pwa"
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
_login_failures: dict[str, list[float]] = {}
_login_failures_lock = threading.Lock()

RequiredName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
OptionalText = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=4000)]
PartsSource = Literal["workshop", "customer"] | None


def _mechanic_can_mutate(method: str, path: str) -> bool:
    if path in {"/api/logout", "/api/presence"} or path.startswith("/api/diagnostics"):
        return True
    match = re.fullmatch(r"/api/orders/(\d+)(?:/(status|photos))?", path)
    if match is None:
        return False
    action = match.group(2)
    return (method == "PUT" and action is None) or (
        method == "POST" and action in {"status", "photos"}
    )


def _login_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_is_limited(key: str) -> bool:
    now = time.monotonic()
    with _login_failures_lock:
        if len(_login_failures) > 4096:
            expired = [candidate for candidate, stamps in _login_failures.items() if not stamps or now - stamps[-1] >= LOGIN_WINDOW_SECONDS]
            for candidate in expired:
                _login_failures.pop(candidate, None)
        failures = [stamp for stamp in _login_failures.get(key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
        _login_failures[key] = failures
        return len(failures) >= LOGIN_MAX_FAILURES


def _record_login_failure(key: str) -> None:
    with _login_failures_lock:
        _login_failures.setdefault(key, []).append(time.monotonic())


def _clear_login_failures(key: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(key, None)


def _valid_image_content(content_type: str, content: bytes) -> bool:
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def _password_version(account: dict[str, object]) -> str:
    digest = hmac.new(
        _session_secret(), str(account.get("password_hash") or "").encode("utf-8"), hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode("ascii")


@app.middleware("http")
async def prevent_api_caching(request: Request, call_next):
    """CRM API responses must always reflect the current shared SQLite database."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
        "manifest-src 'self'; worker-src 'self' blob:"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def bind_authentication_context(request: Request, call_next):
    """Centrally authenticate every private API route with a Bearer access JWT."""
    context = None
    authorization = request.headers.get("authorization", "")
    identity = session_identity(authorization[7:].strip()) if authorization.lower().startswith("bearer ") else None
    if identity is not None:
        if db.refresh_family_active(identity[3], identity[0], identity[1]):
            context = db.get_auth_context(identity[0], identity[1])
        current_password_version = _password_version(context) if context else ""
        if context is not None and not secrets.compare_digest(identity[2], current_password_version):
            context = None
    token = _auth_context.set(context)
    try:
        public_api = {"/api/login", "/api/refresh", "/api/logout"}
        if (
            request.url.path.startswith("/api/") and request.url.path not in public_api
            and request.method != "OPTIONS" and context is None
        ):
            return FastAPIResponse(
                content=json.dumps({"detail": "Authentication required"}),
                status_code=status.HTTP_401_UNAUTHORIZED, media_type="application/json",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if context is not None and request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            role = str(context["role"])
            if role in {"viewer", "accountant"} and request.url.path not in {"/api/logout", "/api/presence"}:
                return FastAPIResponse(
                    content=json.dumps({"detail": "Для вашей роли доступен только просмотр"}, ensure_ascii=False),
                    status_code=status.HTTP_403_FORBIDDEN, media_type="application/json",
                )
            if role == "mechanic" and not _mechanic_can_mutate(request.method, request.url.path):
                return FastAPIResponse(
                    content=json.dumps({"detail": "Механик может изменять только работы и диагностику"}, ensure_ascii=False),
                    status_code=status.HTTP_403_FORBIDDEN, media_type="application/json",
                )
        return await call_next(request)
    finally:
        _auth_context.reset(token)


class LoginRequest(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class StaffCreatePayload(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    password: Annotated[str, StringConstraints(min_length=10, max_length=1024)]
    full_name: RequiredName
    role: str


class StaffUpdatePayload(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: Annotated[str | None, StringConstraints(min_length=10, max_length=1024)] = None


class OrganizationCreatePayload(BaseModel):
    name: RequiredName
    city: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)] = None
    owner_name: RequiredName
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    password: Annotated[str, StringConstraints(min_length=10, max_length=1024)]
    demo: bool = True


class WorkspacePayload(BaseModel):
    name: RequiredName
    city: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)] = None


class PasswordChangePayload(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    new_password: Annotated[str, StringConstraints(min_length=10, max_length=1024)]


class OrganizationAccessPayload(BaseModel):
    action: Literal["block", "activate", "demo"]


class CustomerPayload(BaseModel):
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
    phone: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=50)] = None


class CarPayload(BaseModel):
    customer_id: Annotated[int | None, Field(gt=0)] = None
    brand: RequiredName
    model: RequiredName
    year: Annotated[int | None, Field(ge=1886, le=2100)] = None
    plate_number: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20)] = None
    vin: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=17)] = None
    mileage: Annotated[int | None, Field(ge=0, le=10_000_000)] = None

    @field_validator("vin")
    @classmethod
    def validate_vin(cls, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.upper()
        if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", normalized):
            raise ValueError("VIN должен содержать 17 допустимых символов")
        return normalized


class AppointmentPayload(BaseModel):
    car_id: Annotated[int, Field(gt=0)]
    description: RequiredText
    starts_at: Annotated[str, StringConstraints(strip_whitespace=True, min_length=16, max_length=40)]
    agreed_amount: Annotated[int | None, Field(ge=0, le=1_000_000_000)] = None
    is_flexible: bool = False
    parts_source: PartsSource = None

    @field_validator("starts_at")
    @classmethod
    def validate_starts_at(cls, value: str) -> str:
        try:
            from datetime import datetime
            datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Укажите корректные дату и время") from error
        return value


class OrderPayload(BaseModel):
    car_id: Annotated[int, Field(gt=0)]
    description: RequiredText
    labor_revenue: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0
    parts_cost: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0
    parts_revenue: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0
    parts_profit: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0
    concern: OptionalText = None
    agreed_amount: Annotated[int | None, Field(ge=0, le=1_000_000_000)] = None
    recommendations: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=10_000)] = None
    parts_source: PartsSource = None
    mileage_at_visit: Annotated[int | None, Field(ge=0, le=10_000_000)] = None


class ActionPayload(BaseModel):
    action: Literal["arrived", "no_show", "ready", "in_progress", "completed"]
    mileage_at_visit: Annotated[int | None, Field(ge=0, le=10_000_000)] = None


class DiagnosticStartPayload(BaseModel):
    car_id: Annotated[int, Field(gt=0)]
    service_order_id: Annotated[int | None, Field(gt=0)] = None


class DiagnosticItemPayload(BaseModel):
    status: Literal["unchecked", "ok", "attention", "critical"] | None = None
    left_status: Literal["unchecked", "ok", "attention", "critical"] | None = None
    right_status: Literal["unchecked", "ok", "attention", "critical"] | None = None
    comment: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=4000)] = None
    recommendation: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=4000)] = None
    estimated_cost: Annotated[int | None, Field(ge=0, le=1_000_000_000)] = None


class DiagnosticPayload(BaseModel):
    mileage: Annotated[int | None, Field(ge=0, le=10_000_000)] = None
    notes: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=10_000)] = None
    status: Literal["draft", "completed"] = "draft"


class VinRecognitionPayload(BaseModel):
    vin: Annotated[str, StringConstraints(strip_whitespace=True, min_length=17, max_length=17)]


class CatalogAddPayload(BaseModel):
    order_id: Annotated[int, Field(gt=0)]
    name: RequiredName
    article: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    quantity: Annotated[int, Field(ge=1, le=999)] = 1
    purchase_price: Annotated[int, Field(gt=0, le=1_000_000_000)]
    markup_percent: Annotated[float, Field(ge=0, le=300)] = 40


class RosskoImportPayload(BaseModel):
    order_id: Annotated[int, Field(gt=0)]
    rossko_order_id: Annotated[int, Field(gt=0)]
    markup_percent: Annotated[float, Field(ge=0, le=300)] = 40
    part_articles: Annotated[list[str] | None, Field(max_length=999)] = None


class ProfitLigaImportPayload(BaseModel):
    order_id: Annotated[int, Field(gt=0)]
    profit_order_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    markup_percent: Annotated[float, Field(ge=0, le=300)] = 40
    part_articles: Annotated[list[str] | None, Field(max_length=999)] = None


DIAGNOSTIC_CHECKLIST = [
    ("general", "body_condition", "Состояние кузова", False),
    ("general", "glass_mirrors", "Стёкла и зеркала", False),
    ("general", "lights", "Освещение и световые приборы", False),
    ("general", "interior", "Салон и оборудование", False),
    ("general", "fluids_leaks", "Уровни жидкостей и подтёки", False),
    ("front_suspension", "steering_tips", "Наконечники рулевых тяг", True),
    ("front_suspension", "steering_rods", "Рулевые тяги", True),
    ("front_suspension", "steering_rack", "Рулевая рейка", False),
    ("front_suspension", "steering_boots", "Пыльники рулевого управления", True),
    ("front_suspension", "ball_joints", "Шаровые опоры", True),
    ("front_suspension", "wheel_bearings", "Подшипники ступицы", True),
    ("front_suspension", "silent_blocks", "Сайлентблоки и рычаги", True),
    ("front_suspension", "front_shocks", "Амортизаторы и опоры", True),
    ("front_suspension", "front_springs", "Пружины", True),
    ("front_suspension", "stabilizer", "Стойки и втулки стабилизатора", True),
    ("front_suspension", "engine_mounts", "Подушки крепления двигателя", False),
    ("rear_suspension", "rear_shocks", "Задние амортизаторы", True),
    ("rear_suspension", "rear_springs", "Задние пружины", True),
    ("rear_suspension", "rear_bearings", "Задние ступичные подшипники", True),
    ("rear_suspension", "rear_bushings", "Сайлентблоки задней подвески", True),
    ("rear_suspension", "rear_arms", "Рычаги задней подвески", True),
    # These parts are replaced as an axle set.  A single status avoids the
    # misleading left/right choice even when wear was noticed on one side.
    ("brakes", "front_pads", "Передние тормозные колодки", False),
    ("brakes", "rear_pads", "Задние тормозные колодки", False),
    ("brakes", "front_discs", "Передние тормозные диски", False),
    ("brakes", "rear_discs", "Задние диски или барабаны", False),
    ("brakes", "brake_fluid", "Тормозная жидкость", False),
    ("brakes", "parking_brake", "Стояночный тормоз", False),
    ("engine", "engine_oil_level", "Уровень масла", False),
    ("engine", "engine_oil_condition", "Состояние масла", False),
    ("engine", "engine_leaks", "Течи масла и технических жидкостей", False),
    ("engine", "belts", "Ремни и ролики", False),
    ("engine", "cooling", "Радиатор и система охлаждения", False),
    ("engine", "exhaust", "Выхлопная система", False),
    ("engine", "engine_noise", "Посторонние шумы двигателя", False),
    ("engine", "transmission", "КПП, сцепление и приводы", False),
    ("body", "paint", "Лакокрасочное покрытие", False),
    ("body", "doors", "Двери, замки и уплотнители", False),
    ("body", "wipers", "Стеклоочистители и омыватель", False),
    ("body", "seatbelts", "Ремни безопасности", False),
    ("body", "tires", "Шины и остаток протектора", True),
    ("body", "spare_wheel", "Запасное колесо и инструмент", False),
    ("electrics", "battery", "АКБ и заряд", False),
    ("electrics", "alternator", "Генератор", False),
    ("electrics", "starter", "Стартер", False),
    ("electrics", "exterior_lights", "Внешние световые приборы", False),
    ("electrics", "dashboard", "Приборная панель", False),
    ("electrics", "windows", "Стеклоподъёмники и центральный замок", False),
    ("electrics", "diagnostic_errors", "Ошибки электронных блоков", False),
    ("ac", "ac_cooling", "Работа кондиционера", False),
    ("ac", "ac_pressure", "Давление хладагента", False),
    ("ac", "heater", "Отопитель салона", False),
    ("ac", "blower", "Вентилятор отопителя", False),
    ("ac", "cabin_filter", "Салонный фильтр", False),
]


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


def hash_password(password: str, iterations: int = 600_000) -> str:
    if len(password) < 10:
        raise ValueError("Пароль должен содержать не менее 10 символов")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).rstrip(b"=").decode("ascii"),
        base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"),
    )


def _session_secret() -> bytes:
    value = os.getenv("PWA_SESSION_SECRET", "")
    if len(value) < 32:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "PWA authentication is not configured"
        )
    return value.encode("utf-8")


def make_session(
    account_id: int, organization_id: int, password_version: str = "", family_id: str = "",
) -> str:
    """Create a standards-compatible short-lived HS256 access JWT."""
    now = int(time.time())
    header = _jwt_part({"alg": "HS256", "typ": "JWT"})
    payload = _jwt_part({
        "iss": JWT_ISSUER, "aud": JWT_AUDIENCE, "typ": "access",
        "sub": str(account_id), "org": organization_id, "pwd": password_version,
        "iat": now, "nbf": now, "exp": now + ACCESS_TOKEN_SECONDS,
        "jti": secrets.token_urlsafe(16), "sid": family_id,
    })
    signing_input = f"{header}.{payload}"
    signature = hmac.new(_session_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def _jwt_part(value: dict[str, object]) -> str:
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def session_identity(session: str | None) -> tuple[int, int, str, str] | None:
    if not session or session.count(".") != 2:
        return None
    raw_header, encoded, raw_signature = session.split(".", 2)
    try:
        header = json.loads(_b64decode(raw_header))
        if header != {"alg": "HS256", "typ": "JWT"}:
            return None
        expected = hmac.new(
            _session_secret(), f"{raw_header}.{encoded}".encode("ascii"), hashlib.sha256,
        ).digest()
        decoded_signature = _b64decode(raw_signature)
        canonical_signature = base64.urlsafe_b64encode(decoded_signature).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(raw_signature, canonical_signature) or not hmac.compare_digest(expected, decoded_signature):
            return None
        payload = json.loads(_b64decode(encoded))
        now = int(time.time())
        if (
            payload.get("iss") != JWT_ISSUER or payload.get("aud") != JWT_AUDIENCE
            or payload.get("typ") != "access" or int(payload["exp"]) <= now
            or int(payload["nbf"]) > now + 30 or int(payload["iat"]) > now + 30
            or not isinstance(payload.get("jti"), str) or not payload.get("sid")
        ):
            return None
        return (
            int(payload["sub"]), int(payload["org"]), str(payload.get("pwd", "")),
            str(payload["sid"]),
        )
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None


_auth_context: ContextVar[dict[str, object] | None] = ContextVar("auth_context", default=None)


def require_user() -> dict[str, object]:
    context = _auth_context.get()
    if context is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return context


def require_manager(context: Annotated[dict[str, object], Depends(require_user)]) -> dict[str, object]:
    if context["role"] not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для управления сотрудниками")
    return context


def require_platform_admin(context: Annotated[dict[str, object], Depends(require_user)]) -> dict[str, object]:
    if not context["platform_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступно только владельцу платформы")
    return context


def owner_telegram_id() -> int:
    context = _auth_context.get()
    if context is not None:
        return int(context["data_owner_telegram_id"])
    try:
        return int(os.environ["ADMIN_ID"])
    except (KeyError, ValueError) as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "CRM owner is not configured") from error


def owner_user_id() -> int:
    context = _auth_context.get()
    if context is not None:
        return int(context["data_owner_user_id"])
    connection = db.connect()
    try:
        row = connection.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (owner_telegram_id(),)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "CRM owner is not initialized")
    return int(row["id"])


def require_car(car_id: int):
    car = db.get_car_for_user(owner_user_id(), car_id)
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автомобиль не найден")
    return car


def require_order(order_id: int):
    try:
        order = db.get_service_order(order_id)
    except ValueError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ-наряд не найден") from error
    require_car(order.car_id)
    return order


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
    return FileResponse(
        WEB_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        WEB_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def _refresh_hash(token: str) -> str:
    return hmac.new(_session_secret(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _set_refresh_cookie(response: Response, token: str) -> None:
    cookie_secure = os.getenv("PWA_COOKIE_SECURE", "true").casefold() not in {
        "0", "false", "no", "нет",
    }
    response.set_cookie(
        COOKIE_NAME, token, max_age=REFRESH_TOKEN_SECONDS,
        httponly=True, secure=cookie_secure, samesite="strict", path="/api",
    )


def _issue_token_pair(response: Response, account: dict[str, object]) -> dict[str, object]:
    refresh_token = secrets.token_urlsafe(48)
    session_id = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TOKEN_SECONDS)
    db.create_refresh_session(
        session_id, session_id, int(account["id"]), int(account["organization_id"]),
        _refresh_hash(refresh_token), expires.isoformat(),
    )
    _set_refresh_cookie(response, refresh_token)
    return {
        "access_token": make_session(
            int(account["id"]), int(account["organization_id"]), _password_version(account),
            session_id,
        ),
        "token_type": "bearer", "expires_in": ACCESS_TOKEN_SECONDS,
    }


@app.post("/api/login")
def login(data: LoginRequest, request: Request, response: Response) -> dict[str, object]:
    login_key = _login_key(request)
    if _login_is_limited(login_key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Слишком много попыток входа. Повторите через 15 минут",
        )
    expected_user = os.getenv("PWA_ADMIN_USER", "admin").strip().casefold()
    expected_password = os.getenv("PWA_PASSWORD_HASH", "")
    account = db.get_auth_account(data.username)
    password_valid = verify_password(
        data.password, str(account["password_hash"]) if account is not None else expected_password,
    )
    if account is None and secrets.compare_digest(data.username.strip().casefold(), expected_user) and password_valid:
        account = db.bootstrap_web_owner(
            expected_user, expected_password, os.getenv("PWA_OWNER_NAME", "Владелец"), owner_telegram_id(),
        )
    if account is None or not password_valid:
        _record_login_failure(login_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    _clear_login_failures(login_key)
    db.record_staff_login(int(account["id"]), int(account["organization_id"]))
    return {"status": "ok"} | _issue_token_pair(response, account)


@app.post("/api/refresh")
def refresh_access_token(response: Response, request: Request) -> dict[str, object]:
    refresh_token = request.cookies.get(COOKIE_NAME)
    session = db.get_refresh_session(_refresh_hash(refresh_token)) if refresh_token else None
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is invalid")
    if session.get("revoked_at"):
        db.revoke_refresh_family(str(session["family_id"]))
        response.delete_cookie(COOKIE_NAME, path="/api")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token reuse detected")
    try:
        expires_at = datetime.fromisoformat(str(session["expires_at"]).replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is invalid") from error
    if expires_at <= datetime.now(timezone.utc):
        db.revoke_refresh_session(_refresh_hash(refresh_token))
        response.delete_cookie(COOKIE_NAME, path="/api")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired")
    account = db.get_auth_context(int(session["account_id"]), int(session["organization_id"]))
    if account is None:
        db.revoke_refresh_family(str(session["family_id"]))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is unavailable")
    new_token = secrets.token_urlsafe(48)
    new_id = secrets.token_urlsafe(24)
    new_expiry = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TOKEN_SECONDS)
    if not db.rotate_refresh_session(
        str(session["id"]), new_id, str(session["family_id"]), int(session["account_id"]),
        int(session["organization_id"]), _refresh_hash(new_token), new_expiry.isoformat(),
    ):
        db.revoke_refresh_family(str(session["family_id"]))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token reuse detected")
    _set_refresh_cookie(response, new_token)
    return {
        "access_token": make_session(
            int(account["id"]), int(account["organization_id"]), _password_version(account),
            str(session["family_id"]),
        ),
        "token_type": "bearer", "expires_in": ACCESS_TOKEN_SECONDS,
    }


@app.get("/api/account")
def account(context: Annotated[dict[str, object], Depends(require_user)]) -> dict[str, object]:
    return {key: context[key] for key in ("id", "username", "full_name", "organization_id", "organization_name", "role", "platform_admin")}


@app.get("/api/settings/staff")
def staff_list(context: Annotated[dict[str, object], Depends(require_manager)]) -> list[dict[str, object]]:
    return db.list_staff(int(context["organization_id"]))


@app.post("/api/presence")
def presence_heartbeat(context: Annotated[dict[str, object], Depends(require_user)]) -> dict[str, str]:
    """Record an active PWA session without creating an additional login event."""
    db.touch_staff_presence(int(context["id"]), int(context["organization_id"]))
    return {"status": "ok"}


@app.get("/api/settings/workspace")
def workspace_get(context: Annotated[dict[str, object], Depends(require_manager)]) -> dict[str, object]:
    workspace = db.get_workspace(int(context["organization_id"]))
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Рабочее пространство не найдено")
    return workspace


@app.put("/api/settings/workspace")
def workspace_update(data: WorkspacePayload, context: Annotated[dict[str, object], Depends(require_manager)]) -> dict[str, object]:
    if not data.name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите название автосервиса")
    workspace = db.update_workspace(int(context["organization_id"]), data.name, data.city)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Рабочее пространство не найдено")
    return workspace


@app.put("/api/settings/password")
def password_update(
    data: PasswordChangePayload, response: Response,
    context: Annotated[dict[str, object], Depends(require_user)],
) -> dict[str, object]:
    account = db.get_auth_account(str(context["username"]))
    if account is None or not verify_password(data.current_password, str(account["password_hash"])):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Текущий пароль введён неверно")
    try:
        db.update_account_password(int(context["id"]), hash_password(data.new_password))
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    refreshed = db.get_auth_account(str(context["username"]))
    if refreshed is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Учётная запись больше недоступна")
    db.revoke_account_sessions(int(context["id"]))
    return {"status": "ok"} | _issue_token_pair(response, refreshed)


@app.post("/api/settings/staff", status_code=status.HTTP_201_CREATED)
def staff_create(data: StaffCreatePayload, context: Annotated[dict[str, object], Depends(require_manager)]) -> dict[str, object]:
    roles = {"admin", "service_advisor", "mechanic", "accountant", "viewer"}
    if data.role not in roles:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная роль")
    try:
        account_id = db.create_staff(
            int(context["organization_id"]), data.username, hash_password(data.password), data.full_name, data.role,
        )
    except (ValueError, PostgresIntegrityError, sqlite3.IntegrityError) as error:
        detail = str(error) if isinstance(error, ValueError) else "Этот логин уже занят"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from error
    return next(item for item in db.list_staff(int(context["organization_id"])) if int(item["id"]) == account_id)


@app.patch("/api/settings/staff/{account_id}")
def staff_update(account_id: int, data: StaffUpdatePayload, context: Annotated[dict[str, object], Depends(require_manager)]) -> dict[str, object]:
    roles = {"admin", "service_advisor", "mechanic", "accountant", "viewer"}
    if data.role is not None and data.role not in roles:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная роль")
    try:
        password_hash = hash_password(data.password) if data.password else None
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    if not db.update_staff(int(context["organization_id"]), account_id, data.role, data.active, password_hash):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден или является владельцем")
    if data.active is False or password_hash is not None:
        db.revoke_account_sessions(account_id)
    return next(item for item in db.list_staff(int(context["organization_id"])) if int(item["id"]) == account_id)


@app.get("/api/platform/organizations")
def organizations_list(_: Annotated[dict[str, object], Depends(require_platform_admin)]) -> list[dict[str, object]]:
    return db.list_organizations()


@app.get("/api/platform/organizations/{organization_id}")
def organization_detail(
    organization_id: int,
    _: Annotated[dict[str, object], Depends(require_platform_admin)],
) -> dict[str, object]:
    detail = db.get_organization_detail(organization_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автосервис не найден")
    return detail


@app.post("/api/platform/organizations/{organization_id}/staff", status_code=status.HTTP_201_CREATED)
def organization_staff_create(
    organization_id: int, data: StaffCreatePayload,
    _: Annotated[dict[str, object], Depends(require_platform_admin)],
) -> dict[str, object]:
    roles = {"admin", "service_advisor", "mechanic", "accountant", "viewer"}
    if db.get_organization_detail(organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автосервис не найден")
    if data.role not in roles:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная роль")
    try:
        account_id = db.create_staff(
            organization_id, data.username, hash_password(data.password), data.full_name, data.role,
        )
    except (ValueError, PostgresIntegrityError, sqlite3.IntegrityError) as error:
        detail = str(error) if isinstance(error, ValueError) else "Этот логин уже занят"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from error
    return next(item for item in db.list_staff(organization_id) if int(item["id"]) == account_id)


@app.patch("/api/platform/organizations/{organization_id}/staff/{account_id}")
def organization_staff_update(
    organization_id: int, account_id: int, data: StaffUpdatePayload,
    _: Annotated[dict[str, object], Depends(require_platform_admin)],
) -> dict[str, object]:
    roles = {"admin", "service_advisor", "mechanic", "accountant", "viewer"}
    if data.role is not None and data.role not in roles:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная роль")
    try:
        password_hash = hash_password(data.password) if data.password else None
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    if not db.update_staff(organization_id, account_id, data.role, data.active, password_hash):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден или является владельцем")
    if data.active is False or password_hash is not None:
        db.revoke_account_sessions(account_id)
    return next(item for item in db.list_staff(organization_id) if int(item["id"]) == account_id)


@app.post("/api/platform/organizations", status_code=status.HTTP_201_CREATED)
def organization_create(data: OrganizationCreatePayload, _: Annotated[dict[str, object], Depends(require_platform_admin)]) -> dict[str, object]:
    if not data.name.strip() or not data.owner_name.strip() or not data.username.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Заполните название сервиса и данные владельца")
    try:
        organization_id = db.create_organization(
            data.name, data.city, data.owner_name, data.username, hash_password(data.password),
            7 if data.demo else 0,
        )
    except (ValueError, PostgresIntegrityError, sqlite3.IntegrityError) as error:
        detail = str(error) if isinstance(error, ValueError) else "Этот логин уже занят"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from error
    return next(item for item in db.list_organizations() if int(item["id"]) == organization_id)


@app.post("/api/platform/organizations/{organization_id}/access")
def organization_access(
    organization_id: int, data: OrganizationAccessPayload,
    context: Annotated[dict[str, object], Depends(require_platform_admin)],
) -> dict[str, object]:
    if organization_id == int(context["organization_id"]) and data.action == "block":
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя заблокировать собственный автосервис")
    if data.action not in {"block", "activate", "demo"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестное действие")
    if not db.update_organization_access(organization_id, data.action):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автосервис не найден")
    return next(item for item in db.list_organizations() if int(item["id"]) == organization_id)


@app.post("/api/logout")
def logout(response: Response, request: Request) -> dict[str, str]:
    refresh_token = request.cookies.get(COOKIE_NAME)
    if refresh_token:
        db.revoke_refresh_session(_refresh_hash(refresh_token))
    response.delete_cookie(COOKIE_NAME, path="/api")
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


@app.get("/api/finance/ai-usage")
def ai_usage_finance(
    period: int = 30,
    _: Annotated[dict[str, object], Depends(require_platform_admin)] = None,
) -> dict[str, object]:
    if period not in {1, 7, 30, 0}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Допустимы периоды: 1, 7, 30 или 0")
    summary = db.get_ai_usage_summary(period or None)
    summary["usd_to_rub_rate"] = max(1.0, float(os.getenv("AI_USD_TO_RUB_RATE", "90")))
    return summary


@app.get("/api/search")
def search(
    q: Annotated[str, Query(max_length=200)],
    _: Annotated[dict[str, object], Depends(require_user)],
) -> dict[str, object]:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Введите минимум два символа")
    return db.search(owner_telegram_id(), query)


@app.get("/api/crm")
def crm_data(_: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    telegram_id = owner_telegram_id()
    report = db.get_report_for_telegram_user(telegram_id)
    photos = db.get_order_photos_for_telegram_user(telegram_id)
    orders = db.get_recent_orders_for_telegram_user(telegram_id, limit=300)
    customers = db.get_customers_for_telegram_user(telegram_id)
    cars = db.get_cars_for_telegram_user(telegram_id)
    customers_by_id = {item.id: item for item in customers}
    cars_by_id = {item.id: item for item in cars}
    serialized_orders = []
    for item in orders:
        car = cars_by_id.get(item.car_id)
        customer = customers_by_id.get(car.customer_id) if car and car.customer_id else None
        serialized_orders.append(
            asdict(item) | {
                "profit": item.profit,
                "year": car.year if car else None,
                "customer_phone": customer.phone if customer else None,
                "parts": [asdict(part) for part in db.get_part_items(item.id)],
                "attachments": [
                    photo | {
                        "url": f"/api/order-photos/{str(photo['telegram_file_id'])[4:]}"
                        if str(photo["telegram_file_id"]).startswith("pwa:") else None
                    }
                    for photo in photos.get(item.id, [])
                ],
            }
        )
    return {
        "customers": [asdict(item) for item in customers],
        "cars": [asdict(item) for item in cars],
        "appointments": [
            asdict(item) for item in db.get_upcoming_appointments_for_telegram_user(telegram_id, limit=200)
        ],
        "appointment_history": [
            asdict(item) for item in db.get_recent_appointments_for_telegram_user(telegram_id, limit=500)
        ],
        "orders": serialized_orders,
        "finance": asdict(report) | {"revenue": report.revenue, "profit": report.profit},
    }


@app.post("/api/customers")
def create_customer(data: CustomerPayload, _: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    name = data.full_name.strip() or "Имя не указано"
    customer_id = db.add_customer(owner_user_id(), name, data.phone or None)
    customer = db.get_customer_for_telegram_user(owner_telegram_id(), customer_id)
    return asdict(customer) if customer else {"id": customer_id}


@app.put("/api/customers/{customer_id}")
def edit_customer(
    customer_id: int, data: CustomerPayload, _: Annotated[str, Depends(require_user)]
) -> dict[str, object]:
    if db.get_customer_for_telegram_user(owner_telegram_id(), customer_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    db.update_customer(
        customer_id, data.full_name.strip() or "Имя не указано", data.phone or None,
        replace_nullable=True,
    )
    return asdict(db.get_customer_for_telegram_user(owner_telegram_id(), customer_id))


@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: int, _: Annotated[str, Depends(require_user)]) -> dict[str, str]:
    if not db.delete_customer(owner_user_id(), customer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    return {"status": "ok"}


@app.post("/api/cars")
def create_car(data: CarPayload, _: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    if data.customer_id is not None and db.get_customer_for_telegram_user(
        owner_telegram_id(), data.customer_id
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    car_id = db.add_car(
        owner_user_id(), data.brand.strip(), data.model.strip(), data.year,
        data.plate_number or None, data.customer_id, data.vin or None, data.mileage,
    )
    return asdict(require_car(car_id))


@app.put("/api/cars/{car_id}")
def edit_car(car_id: int, data: CarPayload, _: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    require_car(car_id)
    if data.customer_id is not None and db.get_customer_for_telegram_user(
        owner_telegram_id(), data.customer_id
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    db.update_car(
        car_id, data.customer_id, data.brand.strip(), data.model.strip(), data.year,
        data.plate_number or None, data.vin or None, data.mileage, replace_nullable=True,
    )
    return asdict(require_car(car_id))


@app.delete("/api/cars/{car_id}")
def delete_car(car_id: int, _: Annotated[str, Depends(require_user)]) -> dict[str, str]:
    require_car(car_id)
    if not db.delete_car(owner_user_id(), car_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автомобиль не найден")
    return {"status": "ok"}


@app.post("/api/appointments")
def create_appointment(
    data: AppointmentPayload, _: Annotated[str, Depends(require_user)]
) -> dict[str, object]:
    require_car(data.car_id)
    try:
        appointment_id = db.add_appointment(
            data.car_id, data.description.strip(), data.starts_at,
            agreed_amount=data.agreed_amount, is_flexible=data.is_flexible,
            parts_source=data.parts_source,
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return asdict(db.get_appointment_for_telegram_user(owner_telegram_id(), appointment_id))


@app.put("/api/appointments/{appointment_id}")
def edit_appointment(
    appointment_id: int, data: AppointmentPayload,
    _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    require_car(data.car_id)
    if db.get_appointment_for_telegram_user(owner_telegram_id(), appointment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    try:
        db.update_appointment(
            owner_user_id(), appointment_id, car_id=data.car_id,
            description=data.description.strip(), starts_at=data.starts_at,
            agreed_amount=data.agreed_amount, is_flexible=data.is_flexible,
            parts_source=data.parts_source, replace_nullable=True,
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return asdict(db.get_appointment_for_telegram_user(owner_telegram_id(), appointment_id))


@app.delete("/api/appointments/{appointment_id}")
def delete_appointment(
    appointment_id: int, _: Annotated[str, Depends(require_user)]
) -> dict[str, str]:
    appointment = db.get_appointment_for_telegram_user(owner_telegram_id(), appointment_id)
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    if appointment.status != "scheduled" or appointment.service_order_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Можно удалить только предварительную запись, по которой ещё не создан заказ-наряд",
        )
    if not db.delete_appointment(owner_user_id(), appointment_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Запись уже изменена или удалена")
    return {"status": "ok"}


@app.get("/api/trash")
def trash(_: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    retention_days = max(1, int(os.getenv("ARCHIVE_RETENTION_DAYS", "30")))
    db.purge_archived(owner_user_id(), older_than_days=retention_days)
    return {"retention_days": retention_days, "items": db.get_trash(owner_user_id())}


@app.post("/api/trash/{kind}/{entity_id}/restore")
def restore_from_trash(
    kind: str, entity_id: int, _: Annotated[str, Depends(require_user)]
) -> dict[str, str]:
    try:
        restored = db.restore_archived(owner_user_id(), kind, entity_id)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    if not restored:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Не удалось восстановить запись: она уже восстановлена или её место занято",
        )
    return {"status": "ok"}


@app.post("/api/appointments/{appointment_id}/action")
def appointment_action(
    appointment_id: int, data: ActionPayload,
    _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    if db.get_appointment_for_telegram_user(owner_telegram_id(), appointment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    if data.action == "arrived":
        result = db.start_appointment(owner_user_id(), appointment_id)
    elif data.action == "no_show":
        result = db.mark_appointment_no_show(owner_user_id(), appointment_id)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестное действие")
    if result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Действие уже выполнено")
    return asdict(result) | {"profit": result.profit}


@app.post("/api/orders")
def create_order(data: OrderPayload, _: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    require_car(data.car_id)
    order = db.add_service_order(
        data.car_id, data.description.strip(), data.labor_revenue, data.parts_cost,
        data.parts_revenue, data.parts_profit, data.concern, data.agreed_amount,
        data.recommendations, data.parts_source,
        data.mileage_at_visit,
    )
    return asdict(order) | {"profit": order.profit}


@app.put("/api/orders/{order_id}")
def edit_order(
    order_id: int, data: OrderPayload,
    context: Annotated[dict[str, object], Depends(require_user)],
) -> dict[str, object]:
    order = require_order(order_id)
    if context["role"] == "mechanic":
        restricted_changed = (
            data.car_id != order.car_id
            or data.labor_revenue != order.labor_revenue
            or data.parts_cost != order.parts_cost
            or data.parts_revenue != order.parts_revenue
            or data.parts_profit != order.parts_profit
            or data.concern != order.concern
            or data.agreed_amount != order.agreed_amount
            or data.recommendations != order.recommendations
            or data.parts_source != order.parts_source
            or data.mileage_at_visit != order.mileage_at_visit
        )
        if restricted_changed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Механик может изменять только описание выполненных работ",
            )
        order = db.update_service_order(
            order_id, data.description, order.labor_revenue, order.parts_cost,
            order.parts_revenue, order.parts_profit, False,
        )
        return asdict(order) | {"profit": order.profit}
    if data.car_id != order.car_id:
        require_car(data.car_id)
        db.reassign_order_car(owner_user_id(), order_id, data.car_id)
    order = db.update_service_order(
        order_id, data.description.strip(), data.labor_revenue, data.parts_cost,
        data.parts_revenue, data.parts_profit, False,
    )
    order = db.update_order_crm_fields(
        order_id, owner_user_id(), concern=data.concern,
        agreed_amount=data.agreed_amount, recommendations=data.recommendations,
        mileage_at_visit=data.mileage_at_visit, replace_nullable=True,
    )
    order = db.update_order_parts_source(order_id, data.parts_source, owner_user_id())
    return asdict(order) | {"profit": order.profit}


@app.post("/api/orders/{order_id}/status")
def order_status(
    order_id: int, data: ActionPayload, _: Annotated[str, Depends(require_user)]
) -> dict[str, object]:
    require_order(order_id)
    try:
        if data.mileage_at_visit is not None:
            db.update_order_crm_fields(
                order_id, owner_user_id(), mileage_at_visit=data.mileage_at_visit,
            )
        order = db.set_order_status(order_id, data.action, owner_user_id())
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    return asdict(order) | {"profit": order.profit}


@app.delete("/api/orders/{order_id}")
def delete_order(order_id: int, _: Annotated[str, Depends(require_user)]) -> dict[str, str]:
    require_order(order_id)
    if not db.delete_service_order(owner_user_id(), order_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ-наряд не найден")
    return {"status": "ok"}


@app.post("/api/orders/{order_id}/photos")
async def upload_order_photo(
    order_id: int, request: Request, _: Annotated[str, Depends(require_user)],
    photo_type: str = "work", caption: str | None = None,
) -> dict[str, object]:
    """Accept a camera image as a raw request body without multipart overhead."""
    require_order(order_id)
    if caption is not None and len(caption) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Подпись должна быть не длиннее 500 символов")
    if photo_type not in {"work", "receipt"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный тип фотографии")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if content_type not in extensions:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Поддерживаются JPG, PNG и WebP")
    content = await request.body()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Фото должно быть не больше 10 МБ")
    if not _valid_image_content(content_type, content):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Содержимое файла не соответствует формату изображения")
    filename = f"{uuid.uuid4().hex}{extensions[content_type]}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / filename).write_bytes(content)
    photo_id = db.add_order_photo(order_id, f"pwa:{filename}", caption, photo_type)
    result: dict[str, object] = {
        "id": photo_id, "photo_type": photo_type, "caption": caption,
        "url": f"/api/order-photos/{filename}", "recognized": False,
    }
    if photo_type != "receipt":
        return result

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_openrouter_api_key":
        return result | {"recognition_error": "Распознавание не настроено"}
    vision_model = os.getenv("OPENROUTER_VISION_MODEL", "google/gemini-2.5-flash")
    markup_percent = min(1000.0, max(0.0, float(os.getenv("RECEIPT_MARKUP_PERCENT", "40"))))
    try:
        response = await analyze_receipt_image(api_key, content, content_type, vision_model)
        db.log_ai_usage(
            "vision", response.model, response.input_tokens, response.output_tokens,
            response.cost_usd,
        )
        analysis = response.value
        items = [item for item in analysis.items if item.name and item.total_cost is not None]
        total_cost = analysis.total_cost if analysis.total_cost is not None else sum(
            item.total_cost or 0 for item in items
        )
        if not items or total_cost <= 0:
            return result | {"recognition_error": "Не удалось распознать позиции и стоимость"}
        receipt = db.add_receipt(
            order_id, total_cost,
            [(item.name, item.article, item.quantity, item.unit_cost, item.total_cost) for item in items],
        )
        markup = db.apply_markup_to_receipt(owner_user_id(), receipt.id, markup_percent)
        if markup is None:
            raise OpenRouterError("Не удалось применить наценку")
        _, count, purchase_cost, markup_profit = markup
        return result | {
            "recognized": True,
            "receipt_id": receipt.id,
            "items_count": count,
            "purchase_cost": purchase_cost,
            "markup_percent": markup_percent,
            "markup_profit": markup_profit,
            "selling_price": purchase_cost + markup_profit,
        }
    except (OpenRouterError, ClientError, TimeoutError, ValueError) as error:
        return result | {"recognition_error": str(error)}


@app.get("/api/order-photos/{filename}")
def order_photo(
    filename: str, context: Annotated[dict[str, object], Depends(require_user)],
) -> FileResponse:
    if Path(filename).name != filename or not filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не найдено")
    if not db.user_owns_order_photo(int(context["data_owner_user_id"]), filename):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не найдено")
    path = UPLOAD_DIR / filename
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не найдено")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


def _vision_settings() -> tuple[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key or api_key == "your_openrouter_api_key":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Распознавание не настроено")
    return api_key, os.getenv("OPENROUTER_VISION_MODEL", "google/gemini-2.5-flash")


@app.post("/api/vehicle-recognition/image")
async def recognize_vehicle_image(
    request: Request, _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Поддерживаются JPG, PNG и WebP")
    content = await request.body()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Фото должно быть не больше 10 МБ")
    if not _valid_image_content(content_type, content):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Содержимое файла не соответствует формату изображения")
    api_key, model = _vision_settings()
    try:
        response = await analyze_vehicle_document(
            api_key, model, image=content, mime_type=content_type,
        )
    except (OpenRouterError, ClientError, TimeoutError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось распознать документ: {error}") from error
    db.log_ai_usage("vehicle_recognition", response.model, response.input_tokens, response.output_tokens, response.cost_usd)
    return asdict(response.value)


@app.post("/api/vehicle-recognition/vin")
async def recognize_vehicle_vin(
    data: VinRecognitionPayload, _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    vin = "".join(char for char in data.vin.upper() if char.isalnum())
    if len(vin) != 17 or any(char in "IOQ" for char in vin):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "VIN должен содержать 17 допустимых символов")
    api_key, model = _vision_settings()
    try:
        response = await analyze_vehicle_document(api_key, model, vin_hint=vin)
    except (OpenRouterError, ClientError, TimeoutError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось определить автомобиль: {error}") from error
    db.log_ai_usage("vin_decode", response.model, response.input_tokens, response.output_tokens, response.cost_usd)
    return asdict(response.value)


@app.get("/api/parts-catalog/status")
def parts_catalog_status(context: Annotated[dict[str, object], Depends(require_user)]) -> dict[str, object]:
    return {
        "suppliers": configured_suppliers() if context["platform_admin"] else {"rossko": False, "profit_liga": False},
        "default_markup_percent": max(0.0, float(os.getenv("PARTS_MARKUP_PERCENT", "40"))),
    }


@app.get("/api/parts-catalog/search")
async def parts_catalog_search(
    q: str, _: Annotated[dict[str, object], Depends(require_platform_admin)], markup_percent: float | None = None,
    supplier: str | None = None,
) -> dict[str, object]:
    query = q.strip()
    if len(query) < 3 or len(query) > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Введите артикул или название от 3 до 100 символов")
    markup = max(0.0, min(300.0, markup_percent if markup_percent is not None else float(os.getenv("PARTS_MARKUP_PERCENT", "40"))))
    if supplier not in {None, "rossko", "profit_liga"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный поставщик")
    offers, errors = await search_suppliers(query, supplier)
    serialized = [serialize_offer(offer, markup, 50) for offer in offers]
    serialized.sort(key=lambda item: (int(item["sale_price"]), int(item["delivery_days"])))
    return {"query": query, "offers": serialized, "errors": errors, "suppliers": configured_suppliers(), "markup_percent": markup, "round_to": 50}


@app.post("/api/parts-catalog/add-to-order")
def add_catalog_item_to_order(
    data: CatalogAddPayload, _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    require_order(data.order_id)
    if not data.name.strip() or not data.article.strip() or not 1 <= data.quantity <= 999:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Проверьте наименование, артикул и количество")
    if data.purchase_price <= 0 or not 0 <= data.markup_percent <= 300:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Проверьте цену и наценку")
    item = db.add_catalog_part(
        data.order_id, data.name.strip(), data.article.strip(), data.quantity,
        data.purchase_price, data.markup_percent, 50,
    )
    return asdict(item) | {
        "sale_total": rounded_sale_price(data.purchase_price, data.markup_percent, 50) * data.quantity,
    }


@app.get("/api/parts-catalog/rossko-orders")
async def rossko_orders(
    order_id: int, _: Annotated[dict[str, object], Depends(require_platform_admin)], limit: int = 20,
) -> dict[str, object]:
    require_order(order_id)
    if not configured_suppliers()["rossko"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ROSSKO не подключён")
    try:
        orders = await get_rossko_orders(limit=limit)
    except (ClientError, TimeoutError, ValueError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось получить заказы ROSSKO: {error}") from error
    imported = db.imported_supplier_order_ids(order_id, "rossko")
    return {
        "orders": [asdict(item) | {"imported": str(item.id) in imported} for item in orders],
        "markup_percent": max(0.0, float(os.getenv("PARTS_MARKUP_PERCENT", "40"))),
    }


@app.post("/api/parts-catalog/import-rossko-order")
async def import_rossko_order(
    data: RosskoImportPayload, _: Annotated[dict[str, object], Depends(require_platform_admin)],
) -> dict[str, object]:
    require_order(data.order_id)
    markup = max(0.0, min(300.0, data.markup_percent))
    try:
        orders = await get_rossko_orders(order_ids=[data.rossko_order_id])
    except (ClientError, TimeoutError, ValueError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось получить заказ ROSSKO: {error}") from error
    if not orders:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ ROSSKO не найден")
    order = orders[0]
    active_parts = [part for part in order.parts if part.status not in {7, 8, 9, 34, 35, 36}]
    if data.part_articles is not None:
        requested = {article.strip() for article in data.part_articles if article.strip()}
        active_parts = [part for part in active_parts if part.article in requested]
    if not active_parts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "В заказе нет доступных для импорта позиций")
    parts = [(f"{part.brand} {part.name}".strip(), part.article, part.quantity, part.purchase_price) for part in active_parts]
    try:
        count, purchase, sale = db.import_supplier_order(data.order_id, "rossko", str(order.id), parts, markup, 50)
    except ValueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот заказ ROSSKO уже импортирован") from error
    return {"items_count": count, "purchase_cost": purchase, "selling_price": sale, "rossko_order_id": order.id}


@app.get("/api/parts-catalog/profit-orders")
async def profit_liga_orders(
    order_id: int, _: Annotated[dict[str, object], Depends(require_platform_admin)], page: int = 1,
) -> dict[str, object]:
    require_order(order_id)
    if not configured_suppliers()["profit_liga"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Profit Liga не подключена")
    try:
        orders = await get_profit_liga_orders(page=page)
    except (ClientError, TimeoutError, ValueError, RuntimeError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось получить заказы Profit Liga: {error}") from error
    imported = db.imported_supplier_order_ids(order_id, "profit_liga")
    return {
        "orders": [asdict(item) | {"imported": str(item.id) in imported} for item in orders],
        "markup_percent": max(0.0, float(os.getenv("PARTS_MARKUP_PERCENT", "40"))),
    }


@app.post("/api/parts-catalog/import-profit-order")
async def import_profit_liga_order(
    data: ProfitLigaImportPayload, _: Annotated[dict[str, object], Depends(require_platform_admin)],
) -> dict[str, object]:
    require_order(data.order_id)
    markup = max(0.0, min(300.0, data.markup_percent))
    try:
        orders = await get_profit_liga_orders(order_id=data.profit_order_id)
    except (ClientError, TimeoutError, ValueError, RuntimeError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось получить заказ Profit Liga: {error}") from error
    if not orders:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ Profit Liga не найден")
    order = orders[0]
    inactive_words = ("отмен", "возврат", "отказ")
    active_parts = [part for part in order.parts if not any(word in part.status.lower() for word in inactive_words)]
    if data.part_articles is not None:
        requested = {article.strip() for article in data.part_articles if article.strip()}
        active_parts = [part for part in active_parts if part.article in requested]
    if not active_parts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "В заказе нет доступных для импорта позиций")
    parts = [(f"{part.brand} {part.name}".strip(), part.article, part.quantity, part.purchase_price) for part in active_parts]
    try:
        count, purchase, sale = db.import_supplier_order(data.order_id, "profit_liga", str(order.id), parts, markup, 50)
    except ValueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот заказ Profit Liga уже импортирован") from error
    return {"items_count": count, "purchase_cost": purchase, "selling_price": sale, "profit_order_id": order.id}


@app.get("/api/diagnostics")
def diagnostics(
    _: Annotated[str, Depends(require_user)], car_id: int | None = None,
) -> list[dict[str, object]]:
    return db.list_diagnostics(owner_user_id(), car_id)


@app.post("/api/diagnostics/start")
def start_diagnostic(
    data: DiagnosticStartPayload, _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    diagnostic = db.start_diagnostic(
        owner_user_id(), data.car_id, data.service_order_id, DIAGNOSTIC_CHECKLIST,
    )
    if diagnostic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автомобиль или заказ-наряд не найден")
    diagnostic["photos"] = [
        photo | {"url": f"/api/diagnostic-photos/{photo['filename']}"}
        for photo in diagnostic["photos"]  # type: ignore[index]
    ]
    return diagnostic


@app.get("/api/diagnostics/{diagnostic_id}")
def diagnostic(
    diagnostic_id: int, _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    result = db.get_diagnostic(owner_user_id(), diagnostic_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диагностическая карта не найдена")
    result["photos"] = [
        photo | {"url": f"/api/diagnostic-photos/{photo['filename']}"}
        for photo in result["photos"]  # type: ignore[index]
    ]
    return result


@app.get("/api/diagnostics/{diagnostic_id}/pdf")
def diagnostic_pdf(
    diagnostic_id: int, _: Annotated[str, Depends(require_user)],
) -> FastAPIResponse:
    result = db.get_diagnostic(owner_user_id(), diagnostic_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диагностическая карта не найдена")
    content = build_diagnostic_pdf(
        result,
        logo_path=BASE_DIR / "frontend" / "public" / "assets" / "brand" / "apex-report-logo-approved.png",
        photo_dir=DIAGNOSTIC_UPLOAD_DIR,
    )
    filename = f"apex-diagnostic-{diagnostic_id}.pdf"
    return FastAPIResponse(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/diagnostics/{diagnostic_id}/create-order")
def create_order_from_diagnostic(
    diagnostic_id: int, _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    result = db.create_order_from_diagnostic(owner_user_id(), diagnostic_id)
    if result is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Отметьте неисправности или добавьте рекомендации перед созданием заказа",
        )
    order, created = result
    return asdict(order) | {"profit": order.profit, "created_from_diagnostic": created}


@app.put("/api/diagnostics/{diagnostic_id}")
def update_diagnostic(
    diagnostic_id: int, data: DiagnosticPayload,
    _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    try:
        result = db.update_diagnostic(
            owner_user_id(), diagnostic_id, mileage=data.mileage,
            notes=data.notes, status=data.status,
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диагностическая карта не найдена")
    result["photos"] = [
        photo | {"url": f"/api/diagnostic-photos/{photo['filename']}"}
        for photo in result["photos"]  # type: ignore[index]
    ]
    return result


@app.delete("/api/diagnostics/{diagnostic_id}")
def delete_diagnostic(
    diagnostic_id: int, _: Annotated[str, Depends(require_user)],
) -> dict[str, str]:
    filenames = db.delete_diagnostic(owner_user_id(), diagnostic_id)
    if filenames is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диагностическая карта не найдена")
    for filename in filenames:
        path = DIAGNOSTIC_UPLOAD_DIR / filename
        if path.is_file():
            path.unlink()
    return {"status": "ok"}


@app.put("/api/diagnostics/{diagnostic_id}/items/{item_key}")
def update_diagnostic_item(
    diagnostic_id: int, item_key: str, data: DiagnosticItemPayload,
    _: Annotated[str, Depends(require_user)],
) -> dict[str, object]:
    try:
        result = db.update_diagnostic_item(
            owner_user_id(), diagnostic_id, item_key,
            **data.model_dump(exclude_unset=True),
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пункт диагностики не найден")
    return result


@app.post("/api/diagnostics/{diagnostic_id}/photos")
async def upload_diagnostic_photo(
    diagnostic_id: int, request: Request,
    _: Annotated[str, Depends(require_user)], caption: str | None = None,
) -> dict[str, object]:
    if caption is not None and len(caption) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Подпись должна быть не длиннее 500 символов")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if content_type not in extensions:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Поддерживаются JPG, PNG и WebP")
    content = await request.body()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Фото должно быть не больше 10 МБ")
    if not _valid_image_content(content_type, content):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Содержимое файла не соответствует формату изображения")
    filename = f"{uuid.uuid4().hex}{extensions[content_type]}"
    photo = db.add_diagnostic_photo(owner_user_id(), diagnostic_id, filename, caption)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диагностическая карта не найдена")
    DIAGNOSTIC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (DIAGNOSTIC_UPLOAD_DIR / filename).write_bytes(content)
    return photo | {"url": f"/api/diagnostic-photos/{filename}"}


@app.get("/api/diagnostic-photos/{filename}")
def diagnostic_photo(
    filename: str, context: Annotated[dict[str, object], Depends(require_user)],
) -> FileResponse:
    if Path(filename).name != filename or not filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не найдено")
    if not db.user_owns_diagnostic_photo(int(context["data_owner_user_id"]), filename):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не найдено")
    path = DIAGNOSTIC_UPLOAD_DIR / filename
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не найдено")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@app.get("/{spa_path:path}", include_in_schema=False)
def spa_fallback(spa_path: str) -> FileResponse:
    """Let React Router handle direct navigation to client-side routes."""
    if spa_path.startswith("api/"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})
