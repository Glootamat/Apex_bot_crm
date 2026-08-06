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
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
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
        STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


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
    return {
        "customers": [asdict(item) for item in db.get_customers_for_telegram_user(telegram_id)],
        "cars": [asdict(item) for item in db.get_cars_for_telegram_user(telegram_id)],
        "appointments": [
            asdict(item) for item in db.get_upcoming_appointments_for_telegram_user(telegram_id, limit=200)
        ],
        "orders": [
            asdict(item) | {"profit": item.profit}
            for item in db.get_recent_orders_for_telegram_user(telegram_id, limit=300)
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
