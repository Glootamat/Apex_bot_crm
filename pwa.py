"""Authenticated web API and PWA shell for Apex CRM."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from aiohttp import ClientError
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import Database
from diagnostic_pdf import build_diagnostic_pdf
from openrouter import OpenRouterError, analyze_receipt_image, analyze_vehicle_document
from supplier_catalog import configured_suppliers, rounded_sale_price, search_suppliers, serialize_offer


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

COOKIE_NAME = "apex_crm_session"
SESSION_SECONDS = 12 * 60 * 60


@app.middleware("http")
async def prevent_api_caching(request: Request, call_next):
    """CRM API responses must always reflect the current shared SQLite database."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


class LoginRequest(BaseModel):
    username: str
    password: str


class CustomerPayload(BaseModel):
    full_name: str
    phone: str | None = None


class CarPayload(BaseModel):
    customer_id: int | None = None
    brand: str
    model: str
    year: int | None = None
    plate_number: str | None = None
    vin: str | None = None
    mileage: int | None = None


class AppointmentPayload(BaseModel):
    car_id: int
    description: str
    starts_at: str
    agreed_amount: int | None = None
    is_flexible: bool = False
    parts_source: str | None = None


class OrderPayload(BaseModel):
    car_id: int
    description: str
    labor_revenue: int = 0
    parts_cost: int = 0
    parts_revenue: int = 0
    parts_profit: int = 0
    concern: str | None = None
    agreed_amount: int | None = None
    recommendations: str | None = None
    parts_source: str | None = None


class ActionPayload(BaseModel):
    action: str


class DiagnosticStartPayload(BaseModel):
    car_id: int
    service_order_id: int | None = None


class DiagnosticItemPayload(BaseModel):
    status: str | None = None
    left_status: str | None = None
    right_status: str | None = None
    comment: str | None = None
    recommendation: str | None = None
    estimated_cost: int | None = None


class DiagnosticPayload(BaseModel):
    mileage: int | None = None
    notes: str | None = None
    status: str = "draft"


class VinRecognitionPayload(BaseModel):
    vin: str


class CatalogAddPayload(BaseModel):
    order_id: int
    name: str
    article: str
    quantity: int = 1
    purchase_price: int
    markup_percent: float = 40


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
    ("brakes", "front_pads", "Передние тормозные колодки", True),
    ("brakes", "rear_pads", "Задние тормозные колодки", True),
    ("brakes", "front_discs", "Передние тормозные диски", True),
    ("brakes", "rear_discs", "Задние диски или барабаны", True),
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


def owner_user_id() -> int:
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


@app.get("/api/crm")
def crm_data(_: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    telegram_id = owner_telegram_id()
    report = db.get_report_for_telegram_user(telegram_id)
    photos = db.get_order_photos_for_telegram_user(telegram_id)
    orders = db.get_recent_orders_for_telegram_user(telegram_id, limit=300)
    return {
        "customers": [asdict(item) for item in db.get_customers_for_telegram_user(telegram_id)],
        "cars": [asdict(item) for item in db.get_cars_for_telegram_user(telegram_id)],
        "appointments": [
            asdict(item) for item in db.get_upcoming_appointments_for_telegram_user(telegram_id, limit=200)
        ],
        "appointment_history": [
            asdict(item) for item in db.get_recent_appointments_for_telegram_user(telegram_id, limit=500)
        ],
        "orders": [
            asdict(item) | {
                "profit": item.profit,
                "attachments": [
                    photo | {
                        "url": f"/api/order-photos/{str(photo['telegram_file_id'])[4:]}"
                        if str(photo["telegram_file_id"]).startswith("pwa:") else None
                    }
                    for photo in photos.get(item.id, [])
                ],
            }
            for item in orders
        ],
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
    db.update_customer(customer_id, data.full_name.strip() or "Имя не указано", data.phone or None)
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
        data.plate_number or None, data.vin or None, data.mileage,
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
            parts_source=data.parts_source,
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
    )
    return asdict(order) | {"profit": order.profit}


@app.put("/api/orders/{order_id}")
def edit_order(
    order_id: int, data: OrderPayload, _: Annotated[str, Depends(require_user)]
) -> dict[str, object]:
    order = require_order(order_id)
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
    )
    if data.parts_source:
        order = db.update_order_parts_source(order_id, data.parts_source, owner_user_id())
    return asdict(order) | {"profit": order.profit}


@app.post("/api/orders/{order_id}/status")
def order_status(
    order_id: int, data: ActionPayload, _: Annotated[str, Depends(require_user)]
) -> dict[str, object]:
    require_order(order_id)
    try:
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
    if photo_type not in {"work", "receipt"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный тип фотографии")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if content_type not in extensions:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Поддерживаются JPG, PNG и WebP")
    content = await request.body()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Фото должно быть не больше 10 МБ")
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
    markup_percent = max(0.0, float(os.getenv("RECEIPT_MARKUP_PERCENT", "40")))
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
def order_photo(filename: str, _: Annotated[str, Depends(require_user)]) -> FileResponse:
    if Path(filename).name != filename or not filename:
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
def parts_catalog_status(_: Annotated[str, Depends(require_user)]) -> dict[str, object]:
    return {
        "suppliers": configured_suppliers(),
        "default_markup_percent": max(0.0, float(os.getenv("PARTS_MARKUP_PERCENT", "40"))),
    }


@app.get("/api/parts-catalog/search")
async def parts_catalog_search(
    q: str, _: Annotated[str, Depends(require_user)], markup_percent: float | None = None,
) -> dict[str, object]:
    query = q.strip()
    if len(query) < 3 or len(query) > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Введите артикул или название от 3 до 100 символов")
    markup = max(0.0, min(300.0, markup_percent if markup_percent is not None else float(os.getenv("PARTS_MARKUP_PERCENT", "40"))))
    offers, errors = await search_suppliers(query)
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
        logo_path=BASE_DIR / "frontend" / "public" / "assets" / "brand" / "apex-logo.png",
        photo_dir=DIAGNOSTIC_UPLOAD_DIR,
    )
    filename = f"apex-diagnostic-{diagnostic_id}.pdf"
    return FastAPIResponse(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if content_type not in extensions:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Поддерживаются JPG, PNG и WebP")
    content = await request.body()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Фото должно быть не больше 10 МБ")
    filename = f"{uuid.uuid4().hex}{extensions[content_type]}"
    photo = db.add_diagnostic_photo(owner_user_id(), diagnostic_id, filename, caption)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диагностическая карта не найдена")
    DIAGNOSTIC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (DIAGNOSTIC_UPLOAD_DIR / filename).write_bytes(content)
    return photo | {"url": f"/api/diagnostic-photos/{filename}"}


@app.get("/api/diagnostic-photos/{filename}")
def diagnostic_photo(filename: str, _: Annotated[str, Depends(require_user)]) -> FileResponse:
    if Path(filename).name != filename or not filename:
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
