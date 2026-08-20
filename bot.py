"""Telegram entry point for the car-workshop CRM."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendMessage, SendPhoto, SendDocument
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, CopyTextButton, FSInputFile, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

from backup import create_backup, verify_backup
from database import AppointmentOverview, Database, ServiceOrder
from openrouter import OpenRouterError, WorkshopCommand, analyze_receipt_image, parse_workshop_command, transcribe_voice


BASE_DIR = Path(__file__).resolve().parent
ORDER_PHOTO_UPLOAD_DIR = BASE_DIR / "uploads" / "order_photos"
load_dotenv(BASE_DIR / ".env")
db = Database(BASE_DIR / "workshop.sqlite3")
router = Router()


class IncomingMessageTracker(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.from_user:
            text = event.text or event.caption or "[медиа/голосовое]"
            db.log_incoming_message(event.from_user.id, text, event.message_id)
            db.remember_chat_message(event.chat.id, event.message_id, important=False)
        return await handler(event, data)


class OutgoingMessageTracker(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        if isinstance(result, Message) and isinstance(method, (SendMessage, SendPhoto, SendDocument)):
            # Permanent visit cards are tracked explicitly in service_message_cards.
            # Everything else is temporary UI output and may be removed by cleanup.
            db.remember_chat_message(result.chat.id, result.message_id, important=False)
        return result

try:
    ADMIN_ID = int(os.environ["ADMIN_ID"])
except (KeyError, ValueError) as error:
    raise RuntimeError("Set a numeric ADMIN_ID in the .env file.") from error

router.message.filter(F.from_user.id == ADMIN_ID)
router.callback_query.filter(F.from_user.id == ADMIN_ID)

ORDERS = "🧾 Заказ-наряды"
COMPLETED_ORDERS = "✅ Выполненные заказ-наряды"
APPOINTMENTS = "📅 Записи"
COMPLETE_ORDER = "✅ Закрыть заказ"
CUSTOMERS = "👥 Клиенты"
SEARCH = "🔎 Поиск"
AI_USAGE = "💳 ИИ-расходы"
WORK_PHOTO = "📷 Фото работ"
RECEIPT_PHOTO = "🧾 Чек запчастей"
REPORT = "📊 Финансы"
CANCEL = "Отмена"
CONFIRM_DELETE = "Удалить"
CONFIRM_RECEIPT = "Добавить запчасти"

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=SEARCH)],
        [KeyboardButton(text=APPOINTMENTS), KeyboardButton(text=ORDERS)],
        [KeyboardButton(text=COMPLETED_ORDERS)],
        [KeyboardButton(text=COMPLETE_ORDER), KeyboardButton(text=WORK_PHOTO)],
        [KeyboardButton(text=RECEIPT_PHOTO)],
        [KeyboardButton(text=REPORT), KeyboardButton(text=AI_USAGE)],
    ],
    resize_keyboard=True,
)
cancel_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True)
confirm_delete_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CONFIRM_DELETE)], [KeyboardButton(text=CANCEL)]], resize_keyboard=True)
confirm_receipt_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CONFIRM_RECEIPT)], [KeyboardButton(text=CANCEL)]], resize_keyboard=True)


class AddPhoto(StatesGroup):
    order = State()
    upload = State()


class ConfirmReceipt(StatesGroup):
    waiting = State()


class ConfirmDelete(StatesGroup):
    waiting = State()


class CompleteOrder(StatesGroup):
    select = State()


class Search(StatesGroup):
    query = State()


class EditRecord(StatesGroup):
    waiting = State()


class DirectReceipt(StatesGroup):
    waiting_target = State()
    choosing_order = State()


class CloseOrderCost(StatesGroup):
    waiting = State()


class OrderRecommendations(StatesGroup):
    waiting = State()


def action_keyboard(kind: str, record_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{kind}:{record_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{kind}:{record_id}"),
        ]]
    )


def order_list_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Открыть заказ-наряд", callback_data=f"order:open:{order_id}")],
            [
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:order:{order_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:order:{order_id}"),
            ],
        ]
    )


def order_detail_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Текст для клиента", callback_data=f"order:client-text:{order_id}")],
            [InlineKeyboardButton(
                text="🩺 Дефектовка и рекомендации",
                callback_data=f"order:recommendations:{order_id}",
            )],
            [InlineKeyboardButton(
                text="🖼 Посмотреть фото работ",
                callback_data=f"order:photos:{order_id}",
            )],
            [InlineKeyboardButton(
                text="➕ Добавить фотографию",
                callback_data=f"order:add-photo:{order_id}",
            )],
            [
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:order:{order_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:order:{order_id}"),
            ],
        ]
    )


def completed_orders_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сегодня", callback_data="orders:completed:1"),
            InlineKeyboardButton(text="3 дня", callback_data="orders:completed:3"),
        ],
        [InlineKeyboardButton(text="7 дней", callback_data="orders:completed:7")],
    ])


def customer_action_keyboard(
    customer_id: int, has_phone: bool, vins: list[tuple[str, str]] | None = None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([
        InlineKeyboardButton(
            text="📋 Полная карточка", callback_data=f"customer:open:{customer_id}"
        )
    ])
    for label, vin in vins or []:
        rows.append([
            InlineKeyboardButton(
                text=f"📋 Копировать VIN · {label}",
                copy_text=CopyTextButton(text=vin),
            )
        ])
    rows.append([
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:customer:{customer_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:customer:{customer_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def customer_full_keyboard(
    customer_id: int, phone: str | None, vins: list[tuple[str, str]]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for label, vin in vins:
        rows.append([
            InlineKeyboardButton(
                text=f"📋 VIN · {label}", copy_text=CopyTextButton(text=vin)
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="📚 История обслуживания",
            callback_data=f"customer:history:{customer_id}",
        )
    ])
    rows.append([
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:customer:{customer_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:customer:{customer_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def unfinished_orders_keyboard(order_ids: list[int]) -> InlineKeyboardMarkup:
    rows = []
    for order_id in order_ids:
        rows.append([
            InlineKeyboardButton(text=f"✅ Закрыть #{order_id}", callback_data=f"reminder:close:{order_id}"),
            InlineKeyboardButton(text=f"🕒 Оставить #{order_id}", callback_data=f"reminder:keep:{order_id}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def receipt_action_keyboard(receipt_id: int, can_markup: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_markup:
        rows.append([InlineKeyboardButton(text="📈 Наценить 40%", callback_data=f"markup40:receipt:{receipt_id}")])
    rows.append([
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:receipt:{receipt_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:receipt:{receipt_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_receipt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить новый чек", callback_data="receipt:add")]]
    )


def receipt_order_choices(orders: list[ServiceOrder]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{order.brand} {order.model}" + (f" · {order.plate_number}" if order.plate_number else "") + f" · #{order.id}",
                callback_data=f"receipt:target:{order.id}",
            )]
            for order in orders
        ]
    )


async def show_receipts(message: Message) -> None:
    assert message.from_user is not None
    receipts = db.get_recent_receipts_for_telegram_user(message.from_user.id, limit=10)
    await message.answer("🧾 Последние чеки:", reply_markup=add_receipt_keyboard())
    if not receipts:
        await message.answer("Сохранённых чеков пока нет.", reply_markup=main_keyboard)
        return
    for overview in receipts:
        receipt = overview.receipt
        car = f"{overview.brand} {overview.model}" + (f" · {overview.plate_number}" if overview.plate_number else "")
        customer = customer_name_label(overview.customer_name)
        lines = [f"Чек #{receipt.id} · заказ #{receipt.service_order_id}", f"Клиент: {customer}", f"Автомобиль: {car}"]
        for item in overview.items[:12]:
            quantity = f" × {item.quantity:g}" if item.quantity is not None else ""
            amount = f" — {item.total_cost:,} ₽".replace(",", " ") if item.total_cost is not None else ""
            article = f" · арт. {item.article}" if item.article else ""
            lines.append(f"• {item.name}{quantity}{article}{amount}")
        lines.append(f"\nЗакупочная стоимость: {receipt.total_cost:,} ₽".replace(",", " "))
        if overview.markup_applied:
            percent = overview.items[0].markup_percent
            markup_profit = sum(
                int(float(item.total_cost or 0) * float(item.markup_percent or 0) / 100 + 0.5)
                for item in overview.items
            )
            lines.append(f"✅ Наценка применена: {percent:g}%")
            lines.append(f"Заработок на запчастях: {markup_profit:,} ₽".replace(",", " "))
        else:
            lines.append("⚠️ Наценка ещё не применена")
        await message.answer(
            "\n".join(lines),
            reply_markup=receipt_action_keyboard(receipt.id, can_markup=not overview.markup_applied),
        )


def current_user_id(message: Message) -> int:
    assert message.from_user is not None
    return db.add_or_update_user(message.from_user.id, message.from_user.full_name, message.from_user.username)


def money(value: int) -> str:
    """Keep a formatted amount together when Telegram wraps a line."""
    return f"{value:,}".replace(",", "\u00a0") + "\u00a0₽"


def known_customer_name(value: object) -> str | None:
    """Hide internal phone-derived placeholders from user-facing cards."""
    name = str(value or "").strip()
    normalized = name.casefold().replace("ё", "е")
    if not name or normalized in {
        "неизвестно", "не указан", "не указано", "имя неизвестно",
        "имя не указано", "клиент неизвестен", "клиент не указан",
    }:
        return None
    if normalized.startswith("клиент +") and len(re.sub(r"\D", "", name)) >= 7:
        return None
    return name


def customer_name_label(value: object, missing: str = "Имя не указано") -> str:
    return known_customer_name(value) or missing


VEHICLE_METADATA_MARKER_RE = re.compile(
    r"(?i)(?:\bvin\b|вин(?:\s*[- ]?код)?|гос(?:ударственный)?\s*номер|"
    r"номер\s+(?:авто|автомобиля|машины))"
)
PLATE_FROM_TEXT_RE = re.compile(
    r"(?<![A-ZА-Я0-9])([АВЕКМНОРСТУХABEKMHOPCTYX])\s*(\d{3})\s*"
    r"([АВЕКМНОРСТУХABEKMHOPCTYX]{2})(?:\s*(\d{2,3}))?(?![A-ZА-Я0-9])",
    re.IGNORECASE,
)


def empty_workshop_command(intent: str = "upsert_customer") -> WorkshopCommand:
    values = {
        name: None for name in WorkshopCommand.__dataclass_fields__ if name != "intent"
    }
    return WorkshopCommand(intent=intent, **values)


def customer_name_for_edit(
    command: WorkshopCommand, text: str, phone_text: str | None = None
) -> str | None:
    """Return an explicitly supplied customer name without leaking car metadata."""
    name = command.customer_name.strip() if command.customer_name else None
    if name and phone_text and phone_text in name:
        name = name.replace(phone_text, "").strip(" ,;|-") or None
    has_vehicle_data = any((
        command.car_brand, command.car_model, command.car_year,
        command.plate_number, command.vin, command.mileage,
    ))
    if name or has_vehicle_data or VEHICLE_METADATA_MARKER_RE.search(text):
        return name

    remaining = text
    if phone_text:
        remaining = remaining.replace(phone_text, " ")
    return re.sub(r"\s+", " ", remaining).strip(" ,;|-") or None


def fill_contact_and_appointment_from_text(
    command: WorkshopCommand, text: str
) -> WorkshopCommand:
    """Recover phone/date fields deterministically when the AI parser misses them."""
    values = {name: getattr(command, name) for name in command.__dataclass_fields__}
    normalized_text = text.casefold().replace("ё", "е")

    if any(phrase in normalized_text for phrase in (
        "запчасти клиента", "запчасти клиентские", "со своими запчастями",
        "с запчастями клиента", "детали клиента",
    )):
        values["parts_source"] = "customer"
    elif any(phrase in normalized_text for phrase in (
        "наши запчасти", "запчасти наши", "запчасти сервиса",
        "на запчастях сервиса", "детали сервиса",
    )):
        values["parts_source"] = "workshop"

    vin_match = re.search(
        r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])", text.upper()
    )
    if vin_match:
        values["vin"] = vin_match.group(0)

    plate_match = PLATE_FROM_TEXT_RE.search(text.upper())
    if plate_match:
        values["plate_number"] = "".join(part or "" for part in plate_match.groups())

    if command.customer_name:
        clean_name = re.split(
            r"\s*[,;.]?\s*(?:запчаст|детал|\bvin\b|вин(?:\s*[- ]?код)?|"
            r"гос(?:ударственный)?\s*номер|номер\s+(?:авто|автомобиля|машины))",
            command.customer_name,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,;.-")
        if clean_name.casefold() in {"vin", "вин", "вин код"} or not clean_name:
            values["customer_name"] = None
        else:
            values["customer_name"] = clean_name

    if not command.customer_phone:
        phone_match = re.search(r"(?<!\d)(?:\+?7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)", text)
        if phone_match:
            values["customer_phone"] = phone_match.group(0).strip()

    if not command.appointment_start:
        date_match = re.search(
            r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})"
            r"(?:\s*(?:г(?:ода)?\.?)?)?\s*(?:к|в)?\s*(\d{1,2})[:.](\d{2})(?!\d)",
            text.casefold(),
        )
        if date_match:
            day, month, year, hour, minute = map(int, date_match.groups())
            if year < 100:
                year += 2000
            try:
                starts_at = datetime(
                    year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Moscow")
                )
            except ValueError:
                pass
            else:
                values["appointment_start"] = starts_at.isoformat()
                if command.intent in {"unknown", "upsert_customer", "create_order"}:
                    values["intent"] = "create_appointment"

        if not values["appointment_start"]:
            normalized = text.casefold().replace("ё", "е")
            date_only = re.search(
                r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})(?!\d)",
                normalized,
            )
            if date_only:
                day, month, year = map(int, date_only.groups())
                if year < 100:
                    year += 2000
                try:
                    target = datetime(
                        year, month, day, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")
                    )
                except ValueError:
                    pass
                else:
                    values["appointment_start"] = target.isoformat()
                    if command.intent in {"unknown", "upsert_customer", "create_order"}:
                        values["intent"] = "create_appointment"

            weekday_names = {
                "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3,
                "пятниц": 4, "суббот": 5, "воскресень": 6,
            }
            target_weekday = next(
                (number for name, number in weekday_names.items() if name in normalized), None
            )
            if not values["appointment_start"] and target_weekday is not None:
                now = datetime.now(ZoneInfo("Europe/Moscow"))
                days_ahead = (target_weekday - now.weekday()) % 7 or 7
                target = now.replace(hour=12, minute=0, second=0, microsecond=0)
                values["appointment_start"] = (target + timedelta(days=days_ahead)).isoformat()
                if command.intent in {"unknown", "upsert_customer", "create_order"}:
                    values["intent"] = "create_appointment"

    return WorkshopCommand(**values)


def order_status_label(status: str) -> str:
    return {
        "planned": "🗓 Запланирован",
        "in_progress": "🟡 В работе",
        "ready": "✅ Готов",
        "completed": "✅ Готов",
        "no_show": "🚫 Не приехал",
    }.get(status, status)


def parts_source_label(parts_source: str | None) -> str:
    return {
        "customer": "👤 Запчасти клиента",
        "workshop": "🔧 Запчасти сервиса",
    }.get(parts_source, "Источник запчастей не указан")


def recommendations_block(value: str, indent: str = "") -> str:
    items = [
        re.sub(r"^(?:[-•—]|\d+[.)])\s*", "", item.strip())
        for item in re.split(r"[\r\n]+", value)
        if item.strip()
    ]
    uncertain_words = ("под вопрос", "провер", "диагност", "наблюд")
    replacement = [
        item for item in items
        if not any(word in item.casefold() for word in uncertain_words)
    ]
    inspection = [item for item in items if item not in replacement]
    lines = [f"{indent}🩺 Дефектовка и рекомендации"]
    if replacement:
        lines.append(f"{indent}К замене:")
        lines.extend(f"{indent}• {item}" for item in replacement)
    if inspection:
        lines.append(f"{indent}⚠️ Дополнительно проверить:")
        lines.extend(f"{indent}• {item}" for item in inspection)
    return "\n".join(lines)


def split_telegram_text(lines: list[str], limit: int = 3800) -> list[str]:
    """Split a long card without exceeding Telegram's message length limit."""
    chunks: list[str] = []
    current = ""
    for line in lines:
        pieces = [line[index:index + limit] for index in range(0, len(line), limit)] or [""]
        for piece in pieces:
            candidate = f"{current}\n{piece}" if current else piece
            if len(candidate) > limit:
                if current:
                    chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def appointment_datetime_label(value: datetime, is_flexible: bool = False) -> str:
    weekdays = (
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    )
    time_label = "в течение дня" if is_flexible else f"{value:%H:%M}"
    return f"{value:%d.%m.%Y}, {weekdays[value.weekday()]}, {time_label}"


def order_summary(order: ServiceOrder, prefix: str = "✅ Заказ-наряд сохранён") -> str:
    car = f"{order.brand} {order.model}" + (f" ({order.plate_number})" if order.plate_number else "")
    return (
        f"{prefix}\n\n"
        f"👤 {customer_name_label(order.customer_name)}\n"
        f"🚘 {car}\n"
        + (f"Причина обращения: {order.concern}\n" if order.concern else "")
        + f"🔧 {order.description}\n"
        + (f"Согласовано с клиентом: {money(order.agreed_amount)}\n" if order.agreed_amount is not None else "")
        + (f"{recommendations_block(order.recommendations)}\n" if order.recommendations else "")
        + f"{parts_source_label(order.parts_source)}\n"
        + "\n"
        f"Работы: {money(order.labor_revenue)}\n"
        f"Закупка: {money(order.parts_cost)}\n"
        f"Запчасти клиенту: {money(order.parts_revenue)}\n"
        f"Прибыль с запчастей: {money(order.parts_margin)}\n"
        f"💰 Итого: {money(order.profit)}\n"
        f"Статус: {order_status_label(order.status)}"
    )


def service_order_card_text(order: ServiceOrder) -> str:
    car = f"{order.brand} {order.model}" + (
        f" · {order.plate_number}" if order.plate_number else ""
    )
    lines = [
        f"📋 Основная карточка визита · заказ #{order.id}",
        f"Статус: {order_status_label(order.status)}",
    ]
    appointment = db.get_appointment_for_order(order.id)
    if appointment is not None:
        starts_at = datetime.fromisoformat(str(appointment["starts_at"]))
        lines.append(
            f"🗓 {appointment_datetime_label(starts_at, bool(appointment['is_flexible']))}"
        )
    lines.extend([
        f"👤 {customer_name_label(order.customer_name)}",
        f"🚘 {car}",
    ])
    if order.mileage_at_visit:
        lines.append(f"Пробег: {order.mileage_at_visit:,} км".replace(",", " "))
    if order.concern:
        lines.append(f"Причина обращения: {order.concern}")
    lines.extend(["", "🔧 Работы:"])
    lines.extend(
        f"• {work.strip()}" for work in re.split(r"[;\n]+", order.description)
        if work.strip()
    )
    lines.append(f"Стоимость работ: {money(order.labor_revenue)}")
    lines.extend(["", f"⚙️ {parts_source_label(order.parts_source)}"])
    parts = db.get_part_items(order.id)
    if parts:
        for part in parts[:12]:
            quantity = f" × {part.quantity:g}" if part.quantity is not None else ""
            article = f" · арт. {part.article}" if part.article else ""
            part_line = f"• {part.name}{quantity}{article}"
            purchase = int(part.total_cost or 0)
            if part.markup_percent is not None:
                client_price = purchase + int(
                    purchase * float(part.markup_percent) / 100 + 0.5
                )
                part_line += f" — клиенту {money(client_price)}"
            lines.append(part_line)
        if len(parts) > 12:
            lines.append(f"• Ещё позиций: {len(parts) - 12}")
    elif order.parts_source == "customer":
        lines.append("• Запчасти предоставил клиент")
    else:
        lines.append("• Запчасти пока не добавлены")
    lines.extend([
        f"Закупка запчастей: {money(order.parts_cost)}",
        f"Запчасти клиенту: {money(order.parts_revenue)}",
        "",
        f"💰 Итого к оплате: {money(order.labor_revenue + order.parts_revenue)}",
    ])
    if order.recommendations:
        lines.extend(["", recommendations_block(order.recommendations[:1200])])
    lines.append(f"🖼 Фото работ: {db.count_order_photos(order.id)}")
    return "\n".join(lines)


async def sync_service_order_cards(bot: Bot, order: ServiceOrder) -> int:
    cards = db.get_service_message_cards_for_order(order.id)
    updated = 0
    for card in cards:
        chat_id = int(card["chat_id"])
        message_id = int(card["message_id"])
        try:
            await bot.edit_message_text(
                service_order_card_text(order),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=order_detail_keyboard(order.id),
            )
            updated += 1
        except TelegramBadRequest as error:
            error_text = str(error).casefold()
            if "message is not modified" in error_text:
                updated += 1
            elif "message to edit not found" in error_text:
                db.forget_service_message_card(chat_id, message_id)
            else:
                logging.warning(
                    "Could not update service card %s/%s: %s",
                    chat_id, message_id, error,
                )
        except Exception:
            logging.exception("Could not update service card %s/%s", chat_id, message_id)
    return updated


async def publish_or_sync_service_order_card(
    message: Message, bot: Bot, order: ServiceOrder
) -> None:
    cards = db.get_service_message_cards_for_order(order.id)
    if cards:
        await sync_service_order_cards(bot, order)
        await message.answer(
            f"✅ Основная карточка заказа #{order.id} обновлена.",
            reply_markup=main_keyboard,
        )
        return
    sent = await message.answer(
        service_order_card_text(order),
        reply_markup=order_detail_keyboard(order.id),
    )
    db.remember_service_message_card(
        sent.chat.id, sent.message_id, service_order_id=order.id
    )


def appointment_keyboard(appointment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚘 Машина приехала · В работу",
            callback_data=f"appointment:start:{appointment_id}",
        )],
        [InlineKeyboardButton(
            text="🚫 Клиент не приехал",
            callback_data=f"appointment:no_show:{appointment_id}",
        )],
        [InlineKeyboardButton(
            text="✏️ Изменить запись",
            callback_data=f"edit:appointment:{appointment_id}",
        )],
    ])


def appointment_card_text(appointment: AppointmentOverview) -> str:
    starts_at = datetime.fromisoformat(appointment.starts_at)
    car = f"{appointment.brand} {appointment.model}" + (
        f" · {appointment.plate_number}" if appointment.plate_number else ""
    )
    return (
        f"📋 Основная карточка визита · запись #{appointment.id}\n"
        f"Статус: {order_status_label('planned')}\n"
        f"🗓 {appointment_datetime_label(starts_at, bool(appointment.is_flexible))}\n"
        f"👤 {customer_name_label(appointment.customer_name)}\n"
        + (f"📞 {appointment.customer_phone}\n" if appointment.customer_phone else "")
        + f"🚘 {car}\n"
        f"Причина обращения: {appointment.description}\n"
        f"{parts_source_label(appointment.parts_source)}"
        + (
            f"\nСогласовано: {money(appointment.agreed_amount)}"
            if appointment.agreed_amount is not None else ""
        )
    )


async def sync_appointment_cards(bot: Bot, appointment: AppointmentOverview) -> int:
    updated = 0
    for card in db.get_service_message_cards_for_appointment(appointment.id):
        chat_id = int(card["chat_id"])
        message_id = int(card["message_id"])
        try:
            await bot.edit_message_text(
                appointment_card_text(appointment),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=appointment_keyboard(appointment.id),
            )
            updated += 1
        except TelegramBadRequest as error:
            error_text = str(error).casefold()
            if "message is not modified" in error_text:
                updated += 1
            elif "message to edit not found" in error_text:
                db.forget_service_message_card(chat_id, message_id)
            else:
                logging.warning(
                    "Could not update appointment card %s/%s: %s",
                    chat_id, message_id, error,
                )
    return updated


def edit_removes_customer(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    return any(phrase in normalized for phrase in (
        "без имени", "без клиента", "клиент не указан", "имя не указано",
        "удали имя", "убери имя", "отвяжи клиента", "не назначал",
    ))


def resolve_visit_car_for_edit(
    user_id: int, current_car_id: int, command: WorkshopCommand, text: str
) -> int:
    """Resolve visit-specific car edits without mutating an unrelated contact's car."""
    current = db.get_car_for_user(user_id, current_car_id)
    if current is None:
        raise ValueError("Автомобиль не найден")
    remove_customer = edit_removes_customer(text)
    has_car_change = any((
        command.car_brand, command.car_model, command.car_year,
        command.plate_number, command.vin, command.mileage,
    ))
    has_customer_change = bool(command.customer_name or command.customer_phone or remove_customer)
    if not has_car_change and not has_customer_change:
        return current_car_id

    customer_id = current.customer_id
    if remove_customer:
        customer_id = None
    elif command.customer_name or command.customer_phone:
        customer = db.find_customer(user_id, command.customer_name, command.customer_phone)
        if customer is None and command.customer_phone:
            customer = db.find_or_add_customer_by_phone(
                user_id, command.customer_phone, command.customer_name
            )
        elif customer is None and command.customer_name:
            customer_id = db.add_customer(user_id, command.customer_name, None)
        if customer is not None:
            customer_id = customer.id

    brand = command.car_brand or current.brand
    model = command.car_model or current.model
    plate = command.plate_number.upper() if command.plate_number else current.plate_number
    vin = command.vin or current.vin
    candidate = db.find_car_by_details(user_id, brand, model, plate, vin)
    if candidate is not None and candidate.customer_id == customer_id:
        return candidate.id

    # A visit may have been accidentally attached to an existing contact. Make
    # a separate car card so correcting this visit cannot rewrite their history.
    return db.add_car(
        user_id, brand, model, command.car_year or current.year, plate, customer_id,
        vin, command.mileage or current.mileage, command.next_service_date,
        command.next_service_mileage,
    )


def openrouter_settings() -> tuple[str, str, str, str, str] | None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_openrouter_api_key":
        return None
    return (
        api_key,
        os.getenv("OPENROUTER_TEXT_MODEL", os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")),
        os.getenv("OPENROUTER_VISION_MODEL", "google/gemini-2.5-flash"),
        os.getenv("OPENROUTER_ADVANCED_MODEL", "anthropic/claude-sonnet-4.5"),
        os.getenv("OPENROUTER_TRANSCRIBE_MODEL", "openai/gpt-4o-mini-transcribe"),
    )


def infer_order_list_scope(text: str) -> str | None:
    normalized = text.casefold().replace("ё", "е")
    if any(word in normalized for word in ("не приех", "неяв", "no-show", "ноу шоу")):
        return "no_show"
    if any(word in normalized for word in (
        "закрыт", "заверш", "готов", "выполненн", "истори",
    )):
        return "closed"
    if any(word in normalized for word in ("в работе", "активн", "текущ")):
        return "in_progress"
    if any(word in normalized for word in ("все заказ", "весь список", "за все время")):
        return "all"
    return None


def is_order_list_request(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    wants_output = any(word in normalized for word in (
        "покаж", "вывед", "список", "какие", "найд", "отобраз",
    ))
    mentions_orders = "заказ" in normalized or "наряд" in normalized
    return wants_output and mentions_orders


def is_semantic_crm_read_request(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    if normalized.strip().startswith(("как ", "как мне ", "можно ли ")):
        return False
    read_words = (
        "покаж", "вывед", "кто", "какие", "сколько", "найд", "у кого",
        "есть ли", "сравни", "посчитай", "проанализ",
    )
    crm_words = (
        "клиент", "машин", "автомоб", "заказ", "наряд", "запис",
        "не приех", "рекомендац", "выруч", "прибыл", "работ",
    )
    if not any(word in normalized for word in read_words):
        return False
    if not any(word in normalized for word in crm_words):
        return False
    orders_only = (
        ("заказ" in normalized or "наряд" in normalized)
        and not any(word in normalized for word in (
            "клиент", "машин", "автомоб", "сколько", "у кого", "сравни", "посчитай",
        ))
    )
    return not orders_only


def safe_conversation_context(text: str) -> str:
    """Remove direct identifiers before a prior message is sent for intent parsing."""
    value = re.sub(
        r"(?<!\d)(?:\+?7|8)[\d\s()\-]{9,18}\d(?!\d)", "[телефон]", text
    )
    value = re.sub(r"(?i)\b[A-HJ-NPR-Z0-9]{17}\b", "[VIN]", value)
    return value[:500]


def configured_chat_cleanup_ids() -> set[int]:
    chat_ids = {ADMIN_ID}
    for value in os.getenv("CHAT_CLEANUP_CHAT_IDS", "").split(","):
        if not value.strip():
            continue
        try:
            chat_ids.add(int(value.strip()))
        except ValueError:
            logging.warning("Invalid CHAT_CLEANUP_CHAT_IDS value: %s", value)
    return chat_ids


def is_chat_cleanup_request(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    cleanup = any(word in normalized for word in ("очист", "почист", "убери сообщ", "удали сообщ"))
    chat = any(word in normalized for word in ("чат", "групп", "сообщени"))
    return cleanup and chat and "архив" not in normalized


def requested_cleanup_chat_ids(text: str, current_chat_id: int) -> set[int]:
    normalized = text.casefold().replace("ё", "е")
    configured = configured_chat_cleanup_ids()
    private_ids = {ADMIN_ID}
    group_ids = {chat_id for chat_id in configured if chat_id != ADMIN_ID}
    mentions_group = any(word in normalized for word in ("рабоч", "групп", "apex auto"))
    mentions_private = any(word in normalized for word in ("личн", "в боте", "с ботом"))
    mentions_all = any(word in normalized for word in ("оба", "обоих", "все чат", "чаты"))
    if mentions_all or (mentions_group and mentions_private):
        return configured
    if mentions_group:
        return group_ids or ({current_chat_id} if current_chat_id < 0 else set())
    if mentions_private:
        return private_ids
    return {current_chat_id}


def requested_cleanup_card_statuses(text: str) -> set[str] | None:
    normalized = text.casefold().replace("ё", "е")
    if not any(word in normalized for word in ("остав", "сохран", "не удал")):
        return None
    statuses: set[str] = set()
    if any(word in normalized for word in ("в работе", "рабочие машин", "активн")):
        statuses.add("in_progress")
    if any(word in normalized for word in ("готов", "закрыт", "заверш")):
        statuses.update({"ready", "completed"})
    if any(word in normalized for word in ("записан", "записи", "ожидают", "ожидающ")):
        statuses.add("scheduled")
    if any(word in normalized for word in ("не приех", "неяв", "no-show", "ноу шоу")):
        statuses.add("no_show")
    return statuses or None


async def ensure_cleanup_service_cards(
    bot: Bot, chat_ids: set[int], keep_statuses: set[str] | None
) -> None:
    if keep_statuses is None:
        return
    orders = [
        order for order in db.get_recent_orders_for_telegram_user(ADMIN_ID, limit=100)
        if order.status in keep_statuses
    ]
    for order in orders:
        await sync_service_order_cards(bot, order)
        cards = db.get_service_message_cards_for_order(order.id)
        for chat_id in chat_ids:
            if any(int(card["chat_id"]) == chat_id for card in cards):
                continue
            sent = await bot.send_message(
                chat_id,
                service_order_card_text(order),
                reply_markup=order_detail_keyboard(order.id),
            )
            db.remember_service_message_card(
                sent.chat.id, sent.message_id, service_order_id=order.id
            )
            cards.append({"chat_id": sent.chat.id, "message_id": sent.message_id})


async def append_upcoming_appointment_cards(
    bot: Bot, chat_ids: set[int]
) -> int:
    """Move current scheduled appointments to the bottom after a manual cleanup."""
    appointments = db.get_upcoming_appointments_for_telegram_user(ADMIN_ID, limit=100)
    appended = 0
    for appointment in appointments:
        cards = db.get_service_message_cards_for_appointment(appointment.id)
        for card in list(cards):
            chat_id = int(card["chat_id"])
            message_id = int(card["message_id"])
            if chat_id not in chat_ids:
                continue
            removed = False
            try:
                await bot.delete_message(chat_id, message_id)
                removed = True
            except TelegramBadRequest as error:
                if "message to delete not found" in str(error).casefold():
                    removed = True
            if removed:
                db.forget_service_message_card(chat_id, message_id)
                db.forget_chat_messages(chat_id, [message_id])
                cards.remove(card)
        for chat_id in chat_ids:
            if any(int(card["chat_id"]) == chat_id for card in cards):
                continue
            sent = await bot.send_message(
                chat_id,
                appointment_card_text(appointment),
                reply_markup=appointment_keyboard(appointment.id),
            )
            db.remember_service_message_card(
                sent.chat.id, sent.message_id, appointment_id=appointment.id
            )
            cards.append({"chat_id": sent.chat.id, "message_id": sent.message_id})
            appended += 1
    return appended


async def delete_tracked_chat_messages(
    bot: Bot, chat_ids: set[int], *, today_only: bool = False,
    keep_card_statuses: set[str] | None = None,
) -> tuple[int, int]:
    deleted_total = 0
    failed_total = 0
    for chat_id in chat_ids:
        deleted: list[int] = []
        for message_id in db.get_chat_messages_for_cleanup(
            chat_id,
            today_only=today_only,
            keep_card_statuses=keep_card_statuses,
        ):
            try:
                await bot.delete_message(chat_id, message_id)
                deleted.append(message_id)
                deleted_total += 1
            except TelegramBadRequest as error:
                if "message to delete not found" in str(error).casefold():
                    deleted.append(message_id)
                else:
                    failed_total += 1
            except Exception:
                failed_total += 1
        for message_id in deleted:
            db.forget_service_message_card(chat_id, message_id)
        db.forget_chat_messages(chat_id, deleted)
    return deleted_total, failed_total


async def run_manual_chat_cleanup(
    message: Message, bot: Bot, state: FSMContext, source_text: str
) -> None:
    targets = requested_cleanup_chat_ids(source_text, message.chat.id)
    if not targets:
        await message.answer(
            "Рабочая группа не настроена для очистки. Добавьте её ID в CHAT_CLEANUP_CHAT_IDS."
        )
        return
    await state.clear()
    keep_statuses = requested_cleanup_card_statuses(source_text)
    await ensure_cleanup_service_cards(bot, targets, keep_statuses)
    upcoming_count = await append_upcoming_appointment_cards(bot, targets)
    effective_keep_statuses = (
        None if keep_statuses is None else {*keep_statuses, "scheduled"}
    )
    deleted, failed = await delete_tracked_chat_messages(
        bot,
        targets,
        today_only=any(word in source_text.casefold() for word in ("сегодня", "сегодняш")),
        keep_card_statuses=effective_keep_statuses,
    )
    scope = "личном и рабочем чатах" if len(targets) > 1 else "указанном чате"
    result = f"🧹 Очистка выполнена сразу в {scope}. Удалено сообщений: {deleted}."
    if upcoming_count:
        result += f" Предстоящие записи добавлены в конец: {upcoming_count}."
    if failed:
        result += f" Не удалось удалить: {failed} (ограничение Telegram или права бота)."
    confirmation = await bot.send_message(
        message.chat.id, result, reply_markup=main_keyboard
    )
    if keep_statuses is not None and "только" in source_text.casefold():
        await asyncio.sleep(3)
        try:
            await bot.delete_message(confirmation.chat.id, confirmation.message_id)
        except TelegramBadRequest:
            pass
        db.forget_chat_messages(confirmation.chat.id, [confirmation.message_id])


async def chat_cleanup_text_filter(message: Message) -> bool:
    return bool(message.text and is_chat_cleanup_request(message.text))


@router.message(chat_cleanup_text_filter)
async def manual_chat_cleanup_text(
    message: Message, bot: Bot, state: FSMContext
) -> None:
    await run_manual_chat_cleanup(message, bot, state, message.text or "")


def ai_budget_available() -> bool:
    daily_limit = float(os.getenv("AI_DAILY_LIMIT_USD", "1.00"))
    monthly_limit = float(os.getenv("AI_MONTHLY_LIMIT_USD", "15.00"))
    daily_cost, _ = db.get_ai_usage("datetime('now', 'start of day')")
    monthly_cost, _ = db.get_ai_usage("datetime('now', 'start of month')")
    return daily_cost < daily_limit and monthly_cost < monthly_limit


def record_ai_usage(task_type: str, response: object) -> None:
    db.log_ai_usage(task_type, response.model, response.input_tokens, response.output_tokens, response.cost_usd)  # type: ignore[attr-defined]


async def show_orders(
    message: Message, scope: str = "in_progress", command: WorkshopCommand | None = None,
    completed_days: int | None = None, telegram_id: int | None = None,
) -> None:
    assert message.from_user is not None
    owner_telegram_id = telegram_id if telegram_id is not None else message.from_user.id
    if scope == "closed" and completed_days is not None:
        orders = db.get_completed_orders_for_telegram_user(
            owner_telegram_id, completed_days
        )
    else:
        orders = db.get_recent_orders_for_telegram_user(owner_telegram_id, limit=100)
    if scope == "closed":
        if completed_days is None:
            orders = [order for order in orders if order.status in {"ready", "completed"}]
    elif scope == "no_show":
        orders = [order for order in orders if order.status == "no_show"]
    elif scope == "all":
        pass
    else:
        scope = "in_progress"
        orders = [order for order in orders if order.status == "in_progress"]

    if command is not None:
        if command.order_id is not None:
            orders = [order for order in orders if order.id == command.order_id]
        if command.customer_name:
            needle = command.customer_name.casefold()
            orders = [order for order in orders if needle in (order.customer_name or "").casefold()]
        if command.car_brand:
            needle = command.car_brand.casefold()
            orders = [order for order in orders if needle in order.brand.casefold()]
        if command.car_model:
            needle = command.car_model.casefold()
            orders = [order for order in orders if needle in order.model.casefold()]
        if command.plate_number:
            plate = db.normalize_plate(command.plate_number)
            orders = [order for order in orders if db.normalize_plate(order.plate_number) == plate]
        if command.vin:
            vin = command.vin.replace(" ", "").upper()
            orders = [order for order in orders if (order.vin or "").replace(" ", "").upper() == vin]

    scope_labels = {
        "in_progress": "в работе",
        "closed": "закрытых",
        "no_show": "с неявкой клиента",
        "all": "за всё время",
    }
    period_label = (
        "за сегодня" if completed_days == 1
        else f"за последние {completed_days} дня" if completed_days == 3
        else f"за последние {completed_days} дней" if completed_days
        else ""
    )
    if not orders:
        await message.answer(
            f"Выполненных заказ-нарядов {period_label} не найдено."
            if completed_days else f"Заказ-нарядов {scope_labels[scope]} не найдено."
        )
        return
    await message.answer(
        (
            f"✅ Выполненные заказ-наряды {period_label}:"
            if completed_days else f"🧾 Заказ-наряды {scope_labels[scope]}:"
        ),
        reply_markup=main_keyboard,
    )
    for order in orders:
        car = f"{order.brand} {order.model}" + (f" · {order.plate_number}" if order.plate_number else "")
        status = order_status_label(order.status)
        text = (
            f"#{order.id} · {car}\n"
            f"👤 {customer_name_label(order.customer_name)}\n"
            f"{order.description}\n"
            f"{status} · Прибыль {money(order.profit)}"
        )
        await message.answer(text, reply_markup=order_list_keyboard(order.id))


def semantic_status_matches(status: str, requested: str) -> bool:
    return {
        "in_progress": status == "in_progress",
        "closed": status in {"ready", "completed"},
        "scheduled": status == "scheduled",
        "no_show": status == "no_show",
        "all": True,
    }.get(requested, True)


def semantic_period_matches(value: object, period: str) -> bool:
    if period == "all" or not value:
        return True
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    target = moment.date()
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    if period == "today":
        return target == today
    if period == "tomorrow":
        return target == today + timedelta(days=1)
    if period == "week":
        return today <= target <= today + timedelta(days=7)
    return True


async def show_semantic_crm_query(
    message: Message, command: WorkshopCommand, source_text: str
) -> None:
    assert message.from_user is not None
    normalized = source_text.casefold().replace("ё", "е")
    entity = command.query_entity
    if entity is None:
        if "клиент" in normalized or "кто" in normalized or "у кого" in normalized:
            entity = "customers"
        elif "машин" in normalized or "автомоб" in normalized:
            entity = "cars"
        elif "запис" in normalized:
            entity = "appointments"
        else:
            entity = "orders"
    status = command.query_status
    if status is None:
        status = infer_order_list_scope(source_text)
    if status is None and entity == "appointments":
        status = "scheduled"
    status = status or "all"
    mode = command.query_mode or ("count" if "сколько" in normalized else "list")
    period = command.query_period or (
        "tomorrow" if "завтра" in normalized else
        "today" if "сегодня" in normalized else
        "week" if "недел" in normalized else "all"
    )
    snapshot = db.get_crm_snapshot(message.from_user.id)
    orders = [
        item for item in snapshot["orders"]
        if semantic_status_matches(str(item["status"]), status)
        and semantic_period_matches(
            item["completed_at"] or item["created_at"], period
        )
    ]
    appointments = [
        item for item in snapshot["appointments"]
        if semantic_status_matches(str(item["status"]), status)
        and semantic_period_matches(item["starts_at"], period)
    ]
    if command.query_has_recommendations:
        orders = [item for item in orders if str(item["recommendations"] or "").strip()]

    def matches_identity(item: dict[str, object]) -> bool:
        if command.customer_name and command.customer_name.casefold() not in str(item.get("customer_name") or "").casefold():
            return False
        if command.car_brand and command.car_brand.casefold() not in str(item.get("brand") or "").casefold():
            return False
        if command.car_model and command.car_model.casefold() not in str(item.get("model") or "").casefold():
            return False
        if command.plate_number and db.normalize_plate(str(item.get("plate_number") or "")) != db.normalize_plate(command.plate_number):
            return False
        if command.vin and command.vin.replace(" ", "").upper() != str(item.get("vin") or "").replace(" ", "").upper():
            return False
        return True

    orders = [item for item in orders if matches_identity(item)]
    appointments = [item for item in appointments if matches_identity(item)]
    source_rows = appointments if status == "scheduled" or entity == "appointments" else orders
    if entity == "cars" and status == "all":
        source_rows = [
            item for item in snapshot["cars"] if matches_identity(item)
        ]
    if entity == "customers" and status == "all" and not command.query_has_recommendations:
        cars_by_customer: dict[int, dict[str, object]] = {}
        for car in snapshot["cars"]:
            if car["customer_id"] is not None:
                cars_by_customer.setdefault(int(car["customer_id"]), car)
        source_rows = []
        for customer in snapshot["customers"]:
            customer_id = int(customer["id"])
            car = cars_by_customer.get(customer_id, {})
            row = {
                **customer,
                **car,
                "customer_id": customer_id,
                "customer_name": customer["full_name"],
                "car_id": car.get("id", customer_id),
                "brand": car.get("brand", "Автомобиль"),
                "model": car.get("model", "не указан"),
                "plate_number": car.get("plate_number"),
            }
            if matches_identity(row):
                source_rows.append(row)

    if entity == "orders":
        unique = {int(item["id"]): item for item in source_rows}
        title = "Заказ-наряды"
    elif entity == "appointments":
        unique = {int(item["id"]): item for item in appointments}
        title = "Записи"
    elif entity == "cars":
        unique = {int(item["car_id"]): item for item in source_rows}
        title = "Автомобили"
    else:
        unique = {}
        for item in source_rows:
            customer_key = item.get("customer_id")
            key = int(customer_key) if customer_key is not None else -int(item["car_id"])
            unique.setdefault(key, item)
        title = "Клиенты"

    status_label = {
        "in_progress": "в работе", "closed": "закрытые", "scheduled": "записанные",
        "no_show": "не приехали", "all": "по выбранным условиям",
    }[status]
    if mode == "count":
        await message.answer(f"{title} · {status_label}: {len(unique)}", reply_markup=main_keyboard)
        return
    if mode == "summary":
        labor = sum(int(item.get("labor_revenue") or 0) for item in orders)
        parts = sum(int(item.get("parts_revenue") or 0) for item in orders)
        await message.answer(
            f"{title} · {status_label}: {len(unique)}\n"
            f"Работы: {money(labor)}\nЗапчасти клиенту: {money(parts)}\n"
            f"Итого: {money(labor + parts)}",
            reply_markup=main_keyboard,
        )
        return
    if not unique:
        await message.answer(f"{title} по этому запросу не найдены.", reply_markup=main_keyboard)
        return

    lines = [f"{title} · {status_label}: {len(unique)}"]
    for item in list(unique.values())[:30]:
        car = f"{item['brand']} {item['model']}" + (
            f" · {item['plate_number']}" if item.get("plate_number") else ""
        )
        if entity == "customers":
            lines.append(
                f"• {customer_name_label(item.get('customer_name'))} · {car}"
                + (f" · заказ #{item['id']}" if "description" in item else "")
            )
        elif entity == "cars":
            lines.append(
                f"• {car} · {customer_name_label(item.get('customer_name'))}"
            )
        elif entity == "appointments":
            starts_at = datetime.fromisoformat(str(item["starts_at"]))
            lines.append(
                f"• #{item['id']} · {appointment_datetime_label(starts_at, bool(item['is_flexible']))}"
                f" · {customer_name_label(item.get('customer_name'))} · {car}"
            )
        else:
            lines.append(
                f"• #{item['id']} · {customer_name_label(item.get('customer_name'))}"
                f" · {car} · {item['description']}"
            )
        if command.query_has_recommendations and item.get("recommendations"):
            lines.append("  " + str(item["recommendations"]).replace("\n", "; "))
    for chunk in split_telegram_text(lines):
        await message.answer(chunk, reply_markup=main_keyboard)


@router.callback_query(F.data.startswith("order:open:"))
async def open_order(callback: CallbackQuery) -> None:
    order_id = int(callback.data.rsplit(":", 1)[1])
    assert callback.from_user is not None
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=100)
    order = next((item for item in allowed if item.id == order_id), None)
    await callback.answer()
    if callback.message is None:
        return
    if order is None:
        await callback.message.answer("Заказ-наряд не найден.")
        return

    car = f"{order.brand} {order.model}" + (f" · {order.plate_number}" if order.plate_number else "")
    status = order_status_label(order.status)
    lines = [
        f"📋 Заказ-наряд #{order.id}",
        f"Клиент: {customer_name_label(order.customer_name, 'не указано')}",
        f"Автомобиль: {car}",
        f"Статус: {status}",
        "",
    ]
    if order.concern:
        lines.extend(["💬 Причина обращения:", order.concern, ""])
    if order.agreed_amount is not None:
        lines.extend([f"🤝 Согласовано с клиентом: {money(order.agreed_amount)}", ""])
    lines.extend([parts_source_label(order.parts_source), ""])
    lines.extend([
        "🔧 Работы:",
        f"• {order.description}",
        f"Стоимость работ: {money(order.labor_revenue)}",
        "",
        "⚙️ Запчасти:",
    ])
    items = db.get_part_items(order.id)
    if not items:
        lines.append("Запчасти из чеков не добавлены.")
    for item in items:
        purchase = int(item.total_cost or 0)
        quantity = f" × {item.quantity:g}" if item.quantity is not None else ""
        article = f" · арт. {item.article}" if item.article else ""
        lines.append(f"• {item.name}{quantity}{article}")
        lines.append(f"  Закупка: {money(purchase)}")
        if item.markup_percent is None:
            lines.append("  Наценка: не применена")
        else:
            profit = int(purchase * item.markup_percent / 100 + 0.5)
            lines.append(
                f"  Наценка {item.markup_percent:g}%\n"
                f"  Клиенту: {money(purchase + profit)}\n"
                f"  Прибыль: {money(profit)}"
            )
    lines.extend([
        "",
        "💰 Итого:",
        f"Работы: {money(order.labor_revenue)}",
        f"Закупка: {money(order.parts_cost)}",
        f"Продажа запчастей: {money(order.parts_revenue)}",
        f"Прибыль с запчастей: {money(order.parts_margin)}",
        f"💰 Общая прибыль: {money(order.profit)}",
    ])
    if order.recommendations:
        lines.extend(["", recommendations_block(order.recommendations)])
    history = [item for item in db.get_car_service_history(order.car_id, limit=6) if item.id != order.id]
    if history:
        lines.extend(["", "🕘 Предыдущие обращения:"])
        for previous in history[:5]:
            date = previous.completed_at or previous.created_at
            lines.append(f"• {date[:10]} · #{previous.id} · {previous.description}")
            previous_parts = db.get_part_items(previous.id)
            if previous_parts:
                lines.append("  Детали: " + ", ".join(item.name for item in previous_parts[:6]))
    await callback.message.answer("\n".join(lines), reply_markup=order_detail_keyboard(order.id))


@router.callback_query(F.data.startswith("order:recommendations:"))
async def order_recommendations_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    order_id = int(callback.data.rsplit(":", 1)[1])
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=100)
    order = next((item for item in allowed if item.id == order_id), None)
    if order is None:
        await callback.answer("Заказ-наряд не найден.", show_alert=True)
        return
    await state.set_state(OrderRecommendations.waiting)
    await state.update_data(recommendations_order_id=order_id)
    await callback.answer()
    if callback.message:
        current = (
            f"\n\nСейчас записано:\n{order.recommendations}"
            if order.recommendations else ""
        )
        await callback.message.answer(
            "🩺 Введите результаты дефектовки и рекомендации одним сообщением.\n"
            "Например:\n"
            "«Заменить передние рычаги, втулки стабилизатора и левый рулевой наконечник»."
            + current,
            reply_markup=cancel_keyboard,
        )


@router.message(OrderRecommendations.waiting, F.text)
async def order_recommendations_save(
    message: Message, bot: Bot, state: FSMContext
) -> None:
    if message.text == CANCEL:
        await state.clear()
        await message.answer("Добавление рекомендаций отменено.", reply_markup=main_keyboard)
        return
    recommendation = message.text.strip()
    if len(recommendation) < 3:
        await message.answer("Опишите дефектовку подробнее или нажмите «Отмена».")
        return
    data = await state.get_data()
    order_id = int(data["recommendations_order_id"])
    assert message.from_user is not None
    allowed = db.get_recent_orders_for_telegram_user(message.from_user.id, limit=100)
    if not any(item.id == order_id for item in allowed):
        await state.clear()
        await message.answer("Заказ-наряд не найден.", reply_markup=main_keyboard)
        return
    updated = db.update_order_crm_fields(
        order_id, current_user_id(message), recommendations=recommendation
    )
    await state.clear()
    await publish_or_sync_service_order_card(message, bot, updated)


@router.callback_query(F.data.startswith("order:photos:"))
async def show_order_photos(callback: CallbackQuery) -> None:
    order_id = int(callback.data.rsplit(":", 1)[1])
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=1000)
    order = next((item for item in allowed if item.id == order_id), None)
    await callback.answer()
    if callback.message is None:
        return
    if order is None:
        await callback.message.answer("Заказ-наряд не найден.")
        return
    photos = db.get_order_photos(order_id)
    if not photos:
        await callback.message.answer(
            "В этом заказ-наряде пока нет фото работ.",
            reply_markup=order_detail_keyboard(order_id),
        )
        return
    media: list[InputMediaPhoto] = []
    skipped = 0
    for photo in photos:
        stored_file_id = str(photo["telegram_file_id"])
        if stored_file_id.startswith("pwa:"):
            filename = stored_file_id[4:]
            path = ORDER_PHOTO_UPLOAD_DIR / filename
            if Path(filename).name != filename or not path.is_file():
                skipped += 1
                continue
            image: str | FSInputFile = FSInputFile(path)
        else:
            image = stored_file_id
        media.append(InputMediaPhoto(media=image))

    if not media:
        await callback.message.answer("Фото работ не найдены: файлы были удалены с сервера.")
        return

    title = f"🖼 Фото работ · заказ #{order_id} · {order.brand} {order.model}"
    if len(media) == 1:
        await callback.message.answer_photo(media[0].media, caption=title)
        if skipped:
            await callback.message.answer(f"Не удалось найти файлов: {skipped}.")
        return
    for start in range(0, len(media), 10):
        batch = media[start:start + 10]
        if start == 0:
            batch[0].caption = title
        await callback.message.answer_media_group(batch)
    if skipped:
        await callback.message.answer(f"Не удалось найти файлов: {skipped}.")


@router.callback_query(F.data.startswith("order:add-photo:"))
async def add_photo_to_order(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.rsplit(":", 1)[1])
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=1000)
    order = next((item for item in allowed if item.id == order_id), None)
    await callback.answer()
    if callback.message is None:
        return
    if order is None:
        await callback.message.answer("Заказ-наряд не найден.")
        return
    await state.clear()
    await state.update_data(order_id=order_id, recognize_image=False)
    await state.set_state(AddPhoto.upload)
    status = "готовый" if order.status in {"ready", "completed"} else "активный"
    await callback.message.answer(
        f"Отправляйте фото работ в {status} заказ #{order_id} · "
        f"{order.brand} {order.model}. Можно добавить подпись к каждому фото.",
        reply_markup=cancel_keyboard,
    )


@router.callback_query(F.data.startswith("order:client-text:"))
async def order_text_for_client(callback: CallbackQuery) -> None:
    order_id = int(callback.data.rsplit(":", 1)[1])
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=100)
    order = next((item for item in allowed if item.id == order_id), None)
    await callback.answer()
    if callback.message is None:
        return
    if order is None:
        await callback.message.answer("Заказ-наряд не найден.")
        return

    lines = [
        f"ЗАКАЗ-НАРЯД №{order.id}",
        "",
        f"Клиент: {customer_name_label(order.customer_name, 'не указано')}",
        f"Автомобиль: {order.brand} {order.model}",
        f"Госномер: {order.plate_number or 'не указан'}",
        f"VIN: {order.vin or 'не указан'}",
        f"Пробег: {f'{order.mileage:,}'.replace(',', ' ')} км" if order.mileage else "Пробег: не указан",
        "",
        "Выполненные работы:",
    ]
    works = [work.strip() for work in order.description.split(";") if work.strip()]
    lines.extend(f"• {work}" for work in works)
    lines.append(f"Стоимость работ: {money(order.labor_revenue)}")
    lines.extend(["", "Запчасти:"])

    parts_total = 0
    items = db.get_part_items(order.id)
    if not items:
        lines.append("• Запчасти не добавлены")
    for item in items:
        purchase = int(item.total_cost or 0)
        percent = float(item.markup_percent) if item.markup_percent is not None else 40.0
        client_price = purchase + int(purchase * percent / 100 + 0.5)
        parts_total += client_price
        quantity = f"{item.quantity:g}" if item.quantity is not None else "1"
        lines.append(f"• {item.name} × {quantity} — {money(client_price)}")

    total = order.labor_revenue + parts_total
    lines.extend([
        "",
        f"Запчасти: {money(parts_total)}",
        f"ИТОГО К ОПЛАТЕ: {money(total)}",
        "",
        "Спасибо за обращение!",
        "Автосервис Apex Auto",
    ])
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ К заказу", callback_data=f"order:open:{order.id}")]]
        ),
    )


async def show_search_result(message: Message, query: str) -> None:
    assert message.from_user is not None
    result = db.search(message.from_user.id, query)
    if not any(result.values()):
        await message.answer("Ничего не найдено.")
        return
    normalized_query_phone = db.normalize_phone(query)
    if normalized_query_phone and len(normalized_query_phone) >= 10:
        exact_customers = []
        for item in result["customers"]:
            phones = db.get_customer_phones(int(item["id"]))
            if any(
                db.normalize_phone(phone) == normalized_query_phone
                for phone in phones
            ):
                exact_customers.append((item, phones))
        if exact_customers:
            for item, phones in exact_customers:
                customer_id = int(item["id"])
                lines = [
                    "🔎 Клиент найден по точному номеру",
                    f"👤 {customer_name_label(item['full_name'])}",
                    f"📞 {' · '.join(phones)}",
                ]
                vins: list[tuple[str, str]] = []
                cars = [
                    car for car in result["cars"]
                    if car["customer_id"] is not None
                    and int(car["customer_id"]) == customer_id
                ]
                if not cars:
                    lines.append("🚘 Автомобили не добавлены")
                for car in cars:
                    title = f"🚘 {car['brand']} {car['model']}" + (
                        f" · {car['plate_number']}" if car["plate_number"] else ""
                    )
                    lines.append(title)
                    if car["vin"]:
                        lines.append(f"VIN: {car['vin']}")
                        vins.append((f"{car['brand']} {car['model']}", str(car["vin"])))
                await message.answer(
                    "\n".join(lines),
                    reply_markup=customer_action_keyboard(
                        customer_id, has_phone=bool(phones), vins=vins
                    ),
                )
            return
    lines = [f"🔎 Результаты: {query}"]
    vin_buttons: list[list[InlineKeyboardButton]] = []
    customer_buttons: list[list[InlineKeyboardButton]] = []
    linked_customers: set[int] = set()
    for item in result["customers"]:
        lines.append(
            f"\n👤 {customer_name_label(item['full_name'])}\n📞 {item['phone'] or 'телефон не указан'}"
        )
        customer_id = int(item["id"])
        linked_customers.add(customer_id)
        customer_buttons.append([
            InlineKeyboardButton(
                text=f"📋 Карточка · {customer_name_label(item['full_name'])}",
                callback_data=f"customer:open:{customer_id}",
            )
        ])
    for item in result["cars"]:
        title = f"{item['brand']} {item['model']}" + (f" · {item['plate_number']}" if item["plate_number"] else "")
        details = []
        if item["vin"]:
            details.append(f"VIN: {item['vin']}")
            vin_buttons.append([
                InlineKeyboardButton(
                    text=f"📋 Копировать VIN · {item['brand']} {item['model']}",
                    copy_text=CopyTextButton(text=str(item["vin"])),
                )
            ])
        if item["mileage"]:
            details.append(f"{item['mileage']} км")
        owner = f"\nКлиент: {customer_name_label(item['customer_name'], 'не указано')}"
        phone = f"\nТелефон: {item['customer_phone']}" if item["customer_phone"] else ""
        lines.append(f"\nАвтомобиль: {title}" + owner + phone + (f"\n{' · '.join(details)}" if details else ""))
        if item["customer_id"] is not None and int(item["customer_id"]) not in linked_customers:
            customer_id = int(item["customer_id"])
            linked_customers.add(customer_id)
            customer_buttons.append([
                InlineKeyboardButton(
                    text=f"📋 Карточка · {customer_name_label(item['customer_name'])}",
                    callback_data=f"customer:open:{customer_id}",
                )
            ])
    for item in result["orders"]:
        status = order_status_label(str(item["status"]))
        lines.append(f"\nЗаказ #{item['id']}: {item['brand']} {item['model']} · {item['description']}\nСтатус: {status}")
    await message.answer(
        "\n".join(lines),
        reply_markup=(
            InlineKeyboardMarkup(inline_keyboard=customer_buttons + vin_buttons)
            if customer_buttons or vin_buttons else main_keyboard
        ),
    )
    for item in result["orders"]:
        await message.answer(
            f"Заказ #{item['id']} · открыть карточку и фото работ",
            reply_markup=order_list_keyboard(int(item["id"])),
        )


async def apply_command(
    message: Message, command: WorkshopCommand, state: FSMContext, bot: Bot,
    source_text: str = "",
) -> None:
    if command.intent == "list_orders" or is_order_list_request(source_text):
        scope = infer_order_list_scope(source_text) or command.order_list_scope or "all"
        await show_orders(message, scope, command)
        return
    if command.intent == "unknown":
        await message.answer("Я могу записать или изменить клиента, автомобиль и заказ-наряд. Напишите или скажите это обычными словами.")
        return

    owner_id = current_user_id(message)

    if command.parts_source and not command.appointment_start:
        source_car = db.find_car_by_details(
            owner_id, command.car_brand, command.car_model, command.plate_number, command.vin
        )
        source_order = db.get_latest_order_for_car(source_car.id) if source_car else None
        if source_order is None and command.customer_name:
            source_customer = db.find_customer(
                owner_id, command.customer_name, command.customer_phone
            )
            if source_customer is None:
                source_customer = db.find_customer_by_unique_first_name(
                    owner_id, command.customer_name.split()[0]
                )
            if source_customer is not None:
                active_orders = db.get_active_orders_for_customer(owner_id, source_customer.id)
                source_order = active_orders[0] if len(active_orders) == 1 else None
        if source_order is not None:
            updated = db.update_order_parts_source(
                source_order.id, command.parts_source, owner_id
            )
            await publish_or_sync_service_order_card(message, bot, updated)
            return

    if command.intent == "create_order":
        has_car_identity = bool(
            (command.car_brand and command.car_model) or command.plate_number or command.vin
        )
        if not has_car_identity and command.customer_name:
            existing_customer = db.find_customer(
                owner_id, command.customer_name, command.customer_phone
            )
            if existing_customer is not None:
                active_orders = db.get_active_orders_for_customer(
                    owner_id, existing_customer.id
                )
                if len(active_orders) == 1 and command.description:
                    existing_order = active_orders[0]
                    same_work = (
                        command.description.casefold().strip(" .")
                        in existing_order.description.casefold()
                    )
                    updated = db.update_service_order(
                        existing_order.id,
                        None if same_work else command.description,
                        command.labor_revenue,
                        command.parts_cost,
                        command.parts_revenue,
                        command.parts_profit,
                        add_amounts=False,
                    )
                    await publish_or_sync_service_order_card(message, bot, updated)
                    return
        if not has_car_identity or not command.description:
            missing = []
            if not has_car_identity:
                missing.append("автомобиль — укажите марку и модель, госномер или VIN")
            if not command.description:
                missing.append("выполненные работы")
            await message.answer(
                "Заказ-наряд не создан. Не хватает данных:\n• " + "\n• ".join(missing)
            )
            return

    if command.intent.startswith("delete_"):
        await request_delete(message, command, owner_id, state)
        return

    if command.intent == "set_order_status":
        car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, command.plate_number, command.vin)
        order = db.get_service_order(command.order_id) if command.order_id else (db.get_latest_order_for_car(car.id) if car else None)
        if order is None or command.order_status is None:
            await message.answer("Укажите номер заказ-наряда или автомобиль и статус: «в работе» либо «готов».")
            return
        if command.order_status == "ready" and order.labor_revenue <= 0:
            await close_order_or_request_cost(message, state, order, bot)
            return
        updated = db.set_order_status(order.id, command.order_status, owner_id)
        await publish_or_sync_service_order_card(message, bot, updated)
        return
    if command.intent == "markup_parts":
        car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, command.plate_number, command.vin)
        order = db.get_service_order(command.order_id) if command.order_id else (db.get_latest_order_for_car(car.id) if car else None)
        if order is None or command.parts_markup_percent is None:
            await message.answer("Укажите номер заказ-наряда или автомобиль и процент. Например: «В заказе Kia Rio нацени запчасти из чека на 40%».")
            return
        count, purchase_cost, profit = db.apply_markup_to_unmarked_parts(order.id, command.parts_markup_percent)
        if count == 0:
            await message.answer("В этом заказе нет новых позиций из чеков или корзины для наценки. Повторно одни и те же позиции не нацениваю.")
            return
        updated = db.update_service_order(order.id, None, None, None, purchase_cost + profit, None, add_amounts=True)
        await publish_or_sync_service_order_card(message, bot, updated)
        return
    if command.intent == "update_order" and command.order_id is not None:
        assert message.from_user is not None
        allowed_orders = db.get_recent_orders_for_telegram_user(message.from_user.id, limit=100)
        order = next((item for item in allowed_orders if item.id == command.order_id), None)
        if order is None:
            await message.answer("Заказ-наряд не найден.")
            return
        updated = db.update_service_order(
            order.id,
            command.description,
            command.labor_revenue,
            command.parts_cost,
            command.parts_revenue,
            command.parts_profit,
            add_amounts=False,
        )
        if command.concern or command.agreed_amount is not None or command.recommendations:
            updated = db.update_order_crm_fields(
                updated.id, owner_id, concern=command.concern,
                agreed_amount=command.agreed_amount,
                recommendations=command.recommendations,
            )
        await publish_or_sync_service_order_card(message, bot, updated)
        return
    customer = db.find_customer(owner_id, command.customer_name, command.customer_phone)
    if command.customer_phone:
        customer = db.find_or_add_customer_by_phone(
            owner_id, command.customer_phone, command.customer_name
        )
        customer_id = customer.id
    elif customer is None and command.customer_name:
        customer_id = db.add_customer(owner_id, command.customer_name, None)
    elif customer is not None:
        customer_id = customer.id
        db.update_customer(customer_id, command.customer_name, command.customer_phone)
    else:
        customer_id = None

    plate = command.plate_number.upper() if command.plate_number else None
    has_car_identity = bool(
        command.car_brand or command.car_model or plate or command.vin
    )
    if customer_id is not None:
        car = db.find_customer_car_by_details(
            owner_id, customer_id, command.car_brand, command.car_model,
            plate, command.vin,
        )
    else:
        car = db.find_car_by_details(
            owner_id, command.car_brand, command.car_model, plate, command.vin
        )
    if car is None and customer_id is not None and not has_car_identity:
        car = db.find_single_car_for_customer(owner_id, customer_id)
    if car is None and command.car_brand and command.car_model:
        car_id = db.add_car(owner_id, command.car_brand, command.car_model, command.car_year, plate, customer_id, command.vin, command.mileage, command.next_service_date, command.next_service_mileage)
    elif car is not None:
        car_id = car.id
        db.update_car(car_id, customer_id, command.car_brand, command.car_model, command.car_year, plate, command.vin, command.mileage, command.next_service_date, command.next_service_mileage)
    else:
        car_id = None

    if command.intent == "create_appointment":
        appointment_reason = command.concern or command.description
        starts_at = None
        if command.appointment_start:
            try:
                starts_at = datetime.fromisoformat(command.appointment_start)
            except ValueError:
                await message.answer(
                    "Запись не создана: дата имеет неверный формат. Например: «03.08.2026 в 12:00» "
                    "или «в понедельник в течение дня»."
                )
                return

        is_flexible = not bool(
            re.search(r"(?<!\d)\d{1,2}[:.]\d{2}(?!\d)", source_text)
        )
        if car_id is not None and starts_at is not None:
            existing_id = db.find_active_appointment_id(car_id, starts_at.isoformat())
            if existing_id is not None:
                await message.answer(
                    f"⚠️ Повторная запись не создана. Запись #{existing_id} для этого автомобиля "
                    f"на {appointment_datetime_label(starts_at, is_flexible)} уже существует.",
                    reply_markup=appointment_keyboard(existing_id),
                )
                return

        if car_id is None or not appointment_reason or not command.appointment_start:
            missing = []
            if car_id is None:
                missing.append("автомобиль — укажите марку и модель, госномер или VIN")
            if not appointment_reason:
                missing.append("причина визита или планируемые работы")
            if not command.appointment_start:
                missing.append("дата визита — можно указать точное время или «в течение дня»")
            await message.answer(
                "Запись не создана. Не хватает данных:\n• " + "\n• ".join(missing)
            )
            return
        assert starts_at is not None
        saved = db.save_appointment(
            car_id, appointment_reason, starts_at.isoformat(),
            agreed_amount=command.agreed_amount,
            is_flexible=is_flexible,
            parts_source=command.parts_source,
        )
        appointment_id = saved.id
        if not saved.created:
            await message.answer(
                f"⚠️ Повторная запись не создана. Запись #{appointment_id} для этого автомобиля "
                f"на {appointment_datetime_label(starts_at, is_flexible)} уже существует.",
                reply_markup=appointment_keyboard(appointment_id),
            )
            return
        sent = await message.answer(
            f"📋 Основная карточка визита · запись #{appointment_id}\n"
            f"Статус: {order_status_label('planned')}\n"
            f"Когда: {appointment_datetime_label(starts_at, is_flexible)}\n"
            f"Клиент: {customer_name_label(customer.full_name if customer else command.customer_name, 'не указано')}\n"
            + (
                f"Телефон: {customer.phone if customer else command.customer_phone}\n"
                if (customer and customer.phone) or command.customer_phone else ""
            )
            + f"Автомобиль: {command.car_brand or ''} {command.car_model or ''}"
            + (f" · {plate}" if plate else "")
            + f"\nПричина обращения: {appointment_reason}"
            + f"\n{parts_source_label(command.parts_source)}"
            + (f"\nСогласовано: {money(command.agreed_amount)}" if command.agreed_amount is not None else ""),
            reply_markup=appointment_keyboard(appointment_id),
        )
        db.remember_service_message_card(
            sent.chat.id, sent.message_id, appointment_id=appointment_id
        )
        return

    if command.intent == "upsert_customer":
        if customer_id is None and car_id is None:
            await message.answer("Не понял, какую карточку изменить. Укажите хотя бы имя клиента, телефон или автомобиль.")
        else:
            if car_id is not None:
                for order in db.get_car_service_history(car_id, limit=20):
                    await sync_service_order_cards(bot, order)
            await message.answer("✅ Карточка клиента и автомобиля обновлена.", reply_markup=main_keyboard)
        return

    if car_id is None:
        await message.answer("Для заказ-наряда укажите марку и модель либо госномер автомобиля.")
        return

    if command.intent == "create_order":
        if not command.description:
            await message.answer("Напишите, какие работы выполнены — тогда создам заказ-наряд.")
            return
        order = db.add_service_order(
            car_id, command.description, command.labor_revenue or 0,
            command.parts_cost or 0, command.parts_revenue or 0,
            command.parts_profit or 0, concern=command.concern,
            agreed_amount=command.agreed_amount,
            recommendations=command.recommendations,
            parts_source=command.parts_source,
        )
        await publish_or_sync_service_order_card(message, bot, order)
        return

    if command.intent == "update_order":
        order = db.get_latest_order_for_car(car_id)
        if order is None:
            await message.answer("У этого автомобиля пока нет заказ-нарядов. Опишите выполненные работы, и я создам первый.")
            return
        updated = db.update_service_order(order.id, command.description, command.labor_revenue, command.parts_cost, command.parts_revenue, command.parts_profit, add_amounts=True)
        if command.parts_source:
            updated = db.update_order_parts_source(updated.id, command.parts_source, owner_id)
        if command.concern or command.agreed_amount is not None or command.recommendations:
            updated = db.update_order_crm_fields(
                updated.id, owner_id, concern=command.concern,
                agreed_amount=command.agreed_amount,
                recommendations=command.recommendations,
            )
        await publish_or_sync_service_order_card(message, bot, updated)


async def request_delete(message: Message, command: WorkshopCommand, owner_id: int, state: FSMContext) -> None:
    target_id: int | None = None
    label = ""
    if command.intent == "delete_customer":
        customer = db.find_customer(owner_id, command.customer_name, command.customer_phone)
        if customer:
            target_id, label = customer.id, f"клиента {customer_name_label(customer.full_name)} и все его автомобили с заказ-нарядами"
    elif command.intent == "delete_car":
        car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, command.plate_number, command.vin)
        if car:
            target_id, label = car.id, f"автомобиль {car.brand} {car.model}" + (f" ({car.plate_number})" if car.plate_number else "") + " и его заказ-наряды"
    elif command.intent == "delete_order":
        car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, command.plate_number, command.vin)
        order = db.get_service_order(command.order_id) if command.order_id else (db.get_latest_order_for_car(car.id) if car else None)
        if order:
            target_id, label = order.id, f"заказ-наряд #{order.id}: {order.description}"
    if target_id is None:
        await message.answer("Не нашёл запись для удаления. Укажите имя клиента, автомобиль с номером/VIN или номер заказ-наряда.")
        return
    await state.set_state(ConfirmDelete.waiting)
    await state.update_data(delete_kind=command.intent, delete_id=target_id)
    await message.answer(f"Подтвердите: переместить в архив {label}? Запись останется в журнале.", reply_markup=confirm_delete_keyboard)


@router.message(CommandStart())
async def start(message: Message) -> None:
    current_user_id(message)
    await message.answer(
        "CRM автосервиса готова. Пишите или говорите как удобно — я сам разберу клиента, автомобиль, работы и деньги.\n\n"
        "Можно добавлять сведения позже: например «у Ивана телефон +7999…» или «к Kia Rio добавить фильтр за 500».",
        reply_markup=main_keyboard,
    )


@router.message(F.text == SEARCH)
async def search_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Search.query)
    await message.answer(
        "Введите любые известные данные: имя или фамилию, телефон, автомобиль, "
        "госномер, VIN, пробег, работу, рекомендацию, запчасть или сумму.\n"
        "Если передумали — отправьте «Отмена».",
        reply_markup=ForceReply(
            selective=True,
            input_field_placeholder="Что найти?",
        ),
    )


@router.message(Search.query, F.text)
async def search_query(message: Message, state: FSMContext) -> None:
    if message.text == CANCEL:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_keyboard)
        return
    await state.clear()
    await show_search_result(message, message.text.strip())


@router.message(F.text == ORDERS)
async def orders_button(message: Message) -> None:
    await show_orders(message)


@router.message(F.text == COMPLETED_ORDERS)
async def completed_orders_button(message: Message) -> None:
    await message.answer(
        "За какой период показать выполненные заказ-наряды?",
        reply_markup=completed_orders_period_keyboard(),
    )


@router.callback_query(F.data.startswith("orders:completed:"))
async def completed_orders_period(callback: CallbackQuery) -> None:
    days = int(callback.data.rsplit(":", 1)[1])
    if days not in {1, 3, 7}:
        await callback.answer("Неизвестный период.", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await show_orders(
            callback.message, "closed", completed_days=days,
            telegram_id=callback.from_user.id,
        )


@router.message(F.text == APPOINTMENTS)
async def appointments_button(message: Message) -> None:
    await show_appointments(message)


async def show_appointments(message: Message, target_date: datetime | None = None) -> None:
    assert message.from_user is not None
    appointments = db.get_upcoming_appointments_for_telegram_user(message.from_user.id)
    if target_date is not None:
        appointments = [
            item for item in appointments
            if datetime.fromisoformat(item.starts_at).date() == target_date.date()
        ]
    if not appointments:
        period = "на выбранную дату" if target_date is not None else ""
        await message.answer(f"Предстоящих записей {period} пока нет.".replace("  ", " "), reply_markup=main_keyboard)
        return
    title = (
        f"📅 Записи на {target_date:%d.%m.%Y}:"
        if target_date is not None else "📅 Предстоящие записи:"
    )
    await message.answer(title, reply_markup=main_keyboard)
    for appointment in appointments:
        starts_at = datetime.fromisoformat(appointment.starts_at)
        car = f"{appointment.brand} {appointment.model}" + (
            f" · {appointment.plate_number}" if appointment.plate_number else ""
        )
        await message.answer(
            f"Запись #{appointment.id}\n"
            f"🗓 {appointment_datetime_label(starts_at, bool(appointment.is_flexible))}\n"
            f"👤 {customer_name_label(appointment.customer_name)}"
            + (f" · {appointment.customer_phone}" if appointment.customer_phone else "")
            + f"\n🚘 {car}\n"
            f"Причина обращения: {appointment.description}"
            + f"\n{parts_source_label(appointment.parts_source)}"
            + (f"\nСогласовано: {money(appointment.agreed_amount)}" if appointment.agreed_amount is not None else ""),
            reply_markup=appointment_keyboard(appointment.id) if appointment.status == "scheduled" else None,
        )


@router.callback_query(F.data.startswith("appointment:start:"))
async def start_appointment(callback: CallbackQuery, bot: Bot) -> None:
    appointment_id = int(callback.data.rsplit(":", 1)[1])
    owner_id = db.add_or_update_user(
        callback.from_user.id, callback.from_user.full_name, callback.from_user.username
    )
    order = db.start_appointment(owner_id, appointment_id)
    if order is None:
        await callback.answer("Запись не найдена или уже завершена.", show_alert=True)
        return
    await callback.answer("Машина принята в работу")
    if callback.message:
        db.remember_service_message_card(
            callback.message.chat.id, callback.message.message_id,
            appointment_id=appointment_id,
        )
        db.bind_appointment_card_to_order(appointment_id, order.id)
        await sync_service_order_cards(bot, order)


@router.callback_query(F.data.startswith("appointment:no_show:"))
async def appointment_no_show(callback: CallbackQuery, bot: Bot) -> None:
    appointment_id = int(callback.data.rsplit(":", 1)[1])
    owner_id = db.add_or_update_user(
        callback.from_user.id, callback.from_user.full_name, callback.from_user.username
    )
    order = db.mark_appointment_no_show(owner_id, appointment_id)
    if order is None:
        await callback.answer("Запись не найдена или уже обработана.", show_alert=True)
        return
    await callback.answer("Отмечено: клиент не приехал")
    if callback.message:
        db.remember_service_message_card(
            callback.message.chat.id, callback.message.message_id,
            appointment_id=appointment_id,
        )
        db.bind_appointment_card_to_order(appointment_id, order.id)
        await sync_service_order_cards(bot, order)


async def close_order_or_request_cost(
    message: Message, state: FSMContext, order: ServiceOrder, bot: Bot
) -> None:
    if order.labor_revenue <= 0:
        await state.set_state(CloseOrderCost.waiting)
        await state.update_data(close_order_id=order.id)
        await message.answer(
            f"В заказе #{order.id} не указана стоимость работ.\n"
            "Введите сумму работ, после чего заказ будет закрыт.",
            reply_markup=cancel_keyboard,
        )
        return
    closed = db.set_order_status(order.id, "ready")
    await state.clear()
    await publish_or_sync_service_order_card(message, bot, closed)


@router.message(F.text == COMPLETE_ORDER)
async def complete_order_start(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    orders = [order for order in db.get_recent_orders_for_telegram_user(message.from_user.id, limit=30) if order.status == "in_progress"]
    if not orders:
        await message.answer("Нет заказ-нарядов в работе.")
        return
    await state.update_data(active_orders={str(order.id): order.id for order in orders})
    await state.set_state(CompleteOrder.select)
    choices = "\n".join(f"{order.id}. {order.brand} {order.model}" + (f" · {order.plate_number}" if order.plate_number else "") + f" — {order.description}" for order in orders)
    await message.answer(f"Выберите номер заказ-наряда, который нужно закрыть:\n{choices}", reply_markup=cancel_keyboard)


@router.message(CompleteOrder.select, F.text)
async def complete_order_selected(
    message: Message, bot: Bot, state: FSMContext
) -> None:
    if message.text == CANCEL:
        await state.clear()
        await message.answer("Закрытие заказа отменено.", reply_markup=main_keyboard)
        return
    data = await state.get_data()
    selected = message.text.strip()
    if selected not in data["active_orders"]:
        await message.answer("Выберите номер из списка или нажмите «Отмена».")
        return
    order = db.get_service_order(data["active_orders"][selected])
    await close_order_or_request_cost(message, state, order, bot)


@router.message(CloseOrderCost.waiting, F.text)
async def close_order_cost(message: Message, bot: Bot, state: FSMContext) -> None:
    if message.text == CANCEL:
        await state.clear()
        await message.answer("Закрытие заказа отменено. Заказ остаётся в работе.", reply_markup=main_keyboard)
        return
    digits = re.sub(r"\D", "", message.text)
    if not digits or int(digits) <= 0:
        await message.answer("Введите стоимость работ целым положительным числом или нажмите «Отмена».")
        return
    data = await state.get_data()
    order_id = int(data["close_order_id"])
    updated = db.update_service_order(
        order_id, None, int(digits), None, None, None, add_amounts=False
    )
    closed = db.set_order_status(updated.id, "ready")
    await state.clear()
    await publish_or_sync_service_order_card(message, bot, closed)


@router.message(F.text == CUSTOMERS)
async def customers_button(message: Message, state: FSMContext) -> None:
    # Compatibility for an old Telegram keyboard that may still be visible.
    await state.set_state(Search.query)
    await message.answer(
        "Общий список заменён поиском, чтобы не засорять чат. Введите имя, "
        "телефон, автомобиль, номер, VIN или любые данные из карточки.",
        reply_markup=cancel_keyboard,
    )


@router.callback_query(F.data.startswith("customer:contact:"))
async def open_customer_contact(callback: CallbackQuery) -> None:
    customer_id = int(callback.data.rsplit(":", 1)[1])
    customer = db.get_customer_for_telegram_user(callback.from_user.id, customer_id)
    await callback.answer()
    if callback.message is None:
        return
    if customer is None or not customer.phone:
        await callback.message.answer("У клиента не указан номер телефона.")
        return
    await callback.message.answer_contact(
        phone_number=customer.phone,
        first_name=customer_name_label(customer.full_name),
    )


@router.callback_query(F.data.startswith("customer:open:"))
async def open_customer_card(callback: CallbackQuery) -> None:
    customer_id = int(callback.data.rsplit(":", 1)[1])
    customer = db.get_customer_for_telegram_user(callback.from_user.id, customer_id)
    await callback.answer()
    if callback.message is None:
        return
    if customer is None:
        await callback.message.answer("Карточка клиента не найдена.")
        return

    overview = next(
        (
            item for item in db.get_customer_overviews(callback.from_user.id)
            if item.customer.id == customer_id
        ),
        None,
    )
    lines = [
        "👤 Карточка клиента",
        "",
        f"Имя: {customer_name_label(customer.full_name, 'не указано')}",
        f"Телефоны: {' · '.join(db.get_customer_phones(customer.id)) or 'не указан'}",
    ]
    imported_notes = db.get_customer_notes(customer.id, limit=5)
    if imported_notes:
        lines.extend(["", "📝 Импортированные заметки:"])
        for note in imported_notes:
            lines.append(str(note["note_text"]))
    vins: list[tuple[str, str]] = []
    if overview is None or not overview.cars:
        lines.extend(["", "🚘 Автомобили не добавлены"])
    else:
        lines.extend(["", f"🚘 Автомобили: {len(overview.cars)}"])
        for number, item in enumerate(overview.cars, start=1):
            car = item.car
            lines.extend([
                "",
                f"{number}. {car.brand} {car.model}" + (f" · {car.year} г." if car.year else ""),
                f"Госномер: {car.plate_number or 'не указан'}",
                f"VIN: {car.vin or 'не указан'}",
                f"Пробег: {car.mileage:,} км".replace(",", " ") if car.mileage else "Пробег: не указан",
                f"Заказов: {item.orders_total} · В работе: {item.in_progress} · Готово: {item.completed}",
            ])
            if car.vin:
                vins.append((f"{car.brand} {car.model}", car.vin))
            if car.next_service_date or car.next_service_mileage:
                service = []
                if car.next_service_date:
                    service.append(f"дата {car.next_service_date}")
                if car.next_service_mileage:
                    service.append(f"пробег {car.next_service_mileage:,} км".replace(",", " "))
                lines.append("Следующее ТО: " + " · ".join(service))

            active_orders = [
                order for order in db.get_car_service_history(car.id, limit=10)
                if order.status == "in_progress"
            ]
            for order in active_orders:
                lines.append(f"Сейчас в работе: заказ #{order.id} · {order.description}")
                if order.recommendations:
                    lines.append(recommendations_block(order.recommendations))

    await callback.message.answer(
        "\n".join(lines),
        reply_markup=customer_full_keyboard(customer.id, customer.phone, vins),
    )


@router.callback_query(F.data.startswith("customer:history:"))
async def open_customer_history(callback: CallbackQuery) -> None:
    customer_id = int(callback.data.rsplit(":", 1)[1])
    customer = db.get_customer_for_telegram_user(callback.from_user.id, customer_id)
    await callback.answer()
    if callback.message is None:
        return
    if customer is None:
        await callback.message.answer("Карточка клиента не найдена.")
        return
    overview = next(
        (
            item for item in db.get_customer_overviews(callback.from_user.id)
            if item.customer.id == customer_id
        ),
        None,
    )
    lines = ["📚 История клиента", "", f"👤 {customer_name_label(customer.full_name)}"]
    buttons: list[list[InlineKeyboardButton]] = []
    history_count = 0
    if overview is not None:
        for item in overview.cars:
            if history_count >= 10:
                break
            car = item.car
            history = [
                order for order in db.get_car_service_history(car.id, limit=20)
                if order.status != "in_progress"
            ]
            if not history:
                continue
            lines.extend([
                "",
                f"🚘 {car.brand} {car.model}"
                + (f" · {car.plate_number}" if car.plate_number else ""),
            ])
            for order in history:
                if history_count >= 10:
                    break
                history_count += 1
                raw_date = (order.completed_at or order.created_at)[:10]
                try:
                    visit_date = datetime.fromisoformat(raw_date).strftime("%d.%m.%Y")
                except ValueError:
                    visit_date = raw_date
                lines.extend([
                    "",
                    f"📋 Заказ #{order.id} · {visit_date}",
                    f"Статус: {order_status_label(order.status)}",
                    (
                        f"Пробег: {order.mileage_at_visit:,} км".replace(",", " ")
                        if order.mileage_at_visit else "Пробег: не указан"
                    ),
                ])
                if order.concern:
                    lines.append(f"Причина обращения: {order.concern}")
                lines.append("🔧 Работы:")
                lines.extend(
                    f"• {work.strip()}"
                    for work in order.description.split(";") if work.strip()
                )
                lines.append(f"Стоимость работ: {money(order.labor_revenue)}")

                parts = db.get_part_items(order.id)
                lines.append(f"⚙️ {parts_source_label(order.parts_source)}")
                if parts:
                    for part in parts:
                        quantity = f" × {part.quantity:g}" if part.quantity is not None else ""
                        article = f" · арт. {part.article}" if part.article else ""
                        part_line = f"• {part.name}{quantity}{article}"
                        purchase = int(part.total_cost or 0)
                        if part.markup_percent is not None:
                            client_price = purchase + int(
                                purchase * float(part.markup_percent) / 100 + 0.5
                            )
                            part_line += f" — клиенту {money(client_price)}"
                        elif order.parts_source != "customer":
                            part_line += " — цена клиенту не указана"
                        lines.append(part_line)
                elif order.parts_source == "customer":
                    lines.append("• Детали предоставил клиент")
                else:
                    lines.append("• Запчасти не добавлены")
                lines.extend([
                    f"Запчасти клиенту: {money(order.parts_revenue)}",
                    f"💰 Итого: {money(order.labor_revenue + order.parts_revenue)}",
                ])
                if order.recommendations:
                    lines.append(recommendations_block(order.recommendations))
                if car.next_service_date or car.next_service_mileage:
                    next_service = []
                    if car.next_service_date:
                        next_service.append(f"дата {car.next_service_date}")
                    if car.next_service_mileage:
                        next_service.append(
                            f"пробег {car.next_service_mileage:,} км".replace(",", " ")
                        )
                    lines.append("📅 Следующее ТО: " + " · ".join(next_service))
                photo_count = db.count_order_photos(order.id)
                lines.append(f"🖼 Фотографий работ: {photo_count}")
                order_buttons = [
                    InlineKeyboardButton(
                        text=f"📋 Заказ #{order.id}", callback_data=f"order:open:{order.id}"
                    )
                ]
                if photo_count:
                    order_buttons.append(
                        InlineKeyboardButton(
                            text=f"🖼 Фото ({photo_count})",
                            callback_data=f"order:photos:{order.id}",
                        )
                    )
                buttons.append(order_buttons)
    if history_count == 0:
        lines.extend(["", "Завершённых заказ-нарядов пока нет."])
    messages = split_telegram_text(lines)
    final_keyboard = (
        InlineKeyboardMarkup(inline_keyboard=buttons)
        if buttons else customer_full_keyboard(customer.id, customer.phone, [])
    )
    for index, text in enumerate(messages):
        await callback.message.answer(
            text,
            reply_markup=final_keyboard if index == len(messages) - 1 else None,
        )


@router.callback_query(F.data.startswith("reminder:"))
async def handle_order_reminder(
    callback: CallbackQuery, bot: Bot, state: FSMContext
) -> None:
    _, action, raw_id = callback.data.split(":", 2)
    order_id = int(raw_id)
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=100)
    order = next((item for item in allowed if item.id == order_id), None)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if action == "close":
        if order.status in {"ready", "completed"}:
            await callback.answer("Заказ уже закрыт.")
            return
        if callback.message:
            await callback.answer()
            await close_order_or_request_cost(callback.message, state, order, bot)
    else:
        await callback.answer(f"Заказ #{order.id} оставлен в работе.")
        if callback.message:
            await callback.message.answer(f"🕒 Заказ-наряд #{order.id} остаётся в работе.")


@router.callback_query(F.data.startswith("edit:"))
async def edit_record(callback: CallbackQuery, state: FSMContext) -> None:
    _, kind, raw_id = callback.data.split(":", 2)
    await state.set_state(EditRecord.waiting)
    await state.update_data(edit_kind=kind, edit_id=int(raw_id))
    prompts = {
        "customer": (
            "Напишите изменения обычным сообщением. Например:\n"
            "«Алексей +79624322384»\n"
            "или «Алексей, Audi Q3, госномер А311АА»."
        ),
        "order": "Напишите, что изменить в заказе, например: «работы 5000, описание замена масла».",
        "appointment": (
            "Напишите все исправления обычным сообщением. Например:\n"
            "«Лада Веста, без имени, завтра в 11:00, замена бензонасоса»."
        ),
        "receipt": "Отправьте новую итоговую сумму чека одним числом.",
    }
    await callback.answer()
    if callback.message:
        await callback.message.answer(prompts.get(kind, "Отправьте новые данные."), reply_markup=cancel_keyboard)


@router.message(EditRecord.waiting, F.text)
async def edit_record_value(message: Message, bot: Bot, state: FSMContext) -> None:
    if message.text == CANCEL:
        await state.clear()
        await message.answer("Изменение отменено.", reply_markup=main_keyboard)
        return
    data = await state.get_data()
    kind, record_id = data["edit_kind"], int(data["edit_id"])
    owner_id = current_user_id(message)
    if kind == "customer":
        assert message.from_user is not None
        customer = db.get_customer_for_telegram_user(message.from_user.id, record_id)
        if customer is None:
            await state.clear()
            await message.answer("Клиент не найден.", reply_markup=main_keyboard)
            return

        text = message.text.strip()
        phone_match = re.search(r"(?<!\d)(?:\+?7|8)[\d\s()\-]{9,18}\d(?!\d)", text)
        phone = None
        if phone_match:
            digits = re.sub(r"\D", "", phone_match.group())
            if len(digits) == 11 and digits.startswith("8"):
                digits = "7" + digits[1:]
            phone = "+" + digits if len(digits) == 11 and digits.startswith("7") else phone_match.group().strip()

        parsed = None
        settings = openrouter_settings()
        if settings is not None and ai_budget_available():
            try:
                response = await parse_workshop_command(
                    settings[0],
                    f"Измени карточку существующего клиента. Новые данные: {text}",
                    settings[1],
                )
                record_ai_usage("text", response)
                parsed = response.value
            except OpenRouterError:
                parsed = None

        parsed = fill_contact_and_appointment_from_text(
            parsed or empty_workshop_command(), text
        )
        if phone is None and parsed.customer_phone:
            phone = parsed.customer_phone
        name = customer_name_for_edit(
            parsed, text, phone_match.group() if phone_match else None
        )

        db.update_customer(record_id, name, phone)

        car_changed = False
        if parsed.car_brand or parsed.car_model or parsed.plate_number or parsed.vin or parsed.mileage:
            car = db.find_car_by_details(
                owner_id, parsed.car_brand, parsed.car_model, parsed.plate_number, parsed.vin
            )
            if car is None:
                car = db.find_single_car_for_customer(owner_id, record_id)
            plate = parsed.plate_number.upper() if parsed.plate_number else None
            if car is not None:
                db.update_car(
                    car.id, record_id, parsed.car_brand, parsed.car_model, parsed.car_year,
                    plate, parsed.vin, parsed.mileage, parsed.next_service_date,
                    parsed.next_service_mileage,
                )
                car_changed = True
            elif parsed.car_brand and parsed.car_model:
                db.add_car(
                    owner_id, parsed.car_brand, parsed.car_model, parsed.car_year,
                    plate, record_id, parsed.vin, parsed.mileage,
                    parsed.next_service_date, parsed.next_service_mileage,
                )
                car_changed = True

        await state.clear()
        updated = db.get_customer_for_telegram_user(message.from_user.id, record_id)
        result = [
            "✅ Карточка клиента изменена.",
            f"Имя: {customer_name_label(updated.full_name, 'не указано')}",
            f"Телефон: {updated.phone or 'не указан'}",
        ]
        if car_changed:
            result.append("Автомобиль также обновлён.")
        overview = next(
            (
                item for item in db.get_customer_overviews(message.from_user.id)
                if item.customer.id == record_id
            ),
            None,
        )
        if overview is not None:
            for item in overview.cars:
                for order in db.get_car_service_history(item.car.id, limit=20):
                    await sync_service_order_cards(bot, order)
        await message.answer("\n".join(result), reply_markup=main_keyboard)
    elif kind == "receipt":
        try:
            total = int(message.text.replace(" ", "").replace("₽", ""))
            if total < 0:
                raise ValueError
        except ValueError:
            await message.answer("Введите сумму целым положительным числом.")
            return
        changed = db.update_receipt_total(owner_id, record_id, total)
        await state.clear()
        await message.answer("✅ Сумма чека изменена." if changed else "Чек не найден.", reply_markup=main_keyboard)
    elif kind in {"order", "appointment"}:
        assert message.from_user is not None
        text = message.text.strip()
        settings = openrouter_settings()
        if settings is None or not ai_budget_available():
            await message.answer(
                "Для изменения карточки обычным текстом нужен доступный ИИ-парсер. "
                "Проверьте API-ключ и лимит расходов."
            )
            return
        try:
            response = await parse_workshop_command(
                settings[0],
                f"Измени существующую карточку {kind} #{record_id}. "
                f"Извлеки только явно указанные новые данные: {text}",
                settings[1],
            )
            record_ai_usage("text", response)
            command = fill_contact_and_appointment_from_text(response.value, text)
        except OpenRouterError as error:
            await message.answer(f"Не удалось распознать изменения: {error}")
            return

        if kind == "appointment":
            appointment = db.get_appointment_for_telegram_user(
                message.from_user.id, record_id
            )
            if appointment is None:
                await state.clear()
                await message.answer("Запись не найдена.", reply_markup=main_keyboard)
                return
            car_id = resolve_visit_car_for_edit(owner_id, appointment.car_id, command, text)
            starts_at = command.appointment_start
            is_flexible = None
            if starts_at:
                is_flexible = not bool(
                    re.search(r"(?<!\d)\d{1,2}[:.]\d{2}(?!\d)", text)
                )
            try:
                changed = db.update_appointment(
                    owner_id, record_id, car_id=car_id,
                    description=command.concern or command.description,
                    starts_at=starts_at, agreed_amount=command.agreed_amount,
                    is_flexible=is_flexible, parts_source=command.parts_source,
                )
            except ValueError as error:
                await message.answer(f"Изменение не сохранено: {error}")
                return
            await state.clear()
            updated = db.get_appointment_for_telegram_user(message.from_user.id, record_id)
            if changed and updated is not None:
                await sync_appointment_cards(bot, updated)
                await message.answer(
                    "✅ Запись изменена.\n\n" + appointment_card_text(updated),
                    reply_markup=main_keyboard,
                )
            else:
                await message.answer("Запись не найдена.", reply_markup=main_keyboard)
            return

        try:
            order = db.get_service_order(record_id)
        except ValueError:
            await state.clear()
            await message.answer("Заказ не найден.", reply_markup=main_keyboard)
            return
        if db.get_car_for_user(owner_id, order.car_id) is None:
            await state.clear()
            await message.answer("Заказ не найден.", reply_markup=main_keyboard)
            return
        car_id = resolve_visit_car_for_edit(owner_id, order.car_id, command, text)
        if car_id != order.car_id:
            order = db.reassign_order_car(owner_id, record_id, car_id)
        order = db.update_service_order(
            record_id, command.description, command.labor_revenue,
            command.parts_cost, command.parts_revenue, command.parts_profit,
            add_amounts=False,
        )
        if command.concern or command.agreed_amount is not None or command.recommendations:
            order = db.update_order_crm_fields(
                record_id, owner_id, concern=command.concern,
                agreed_amount=command.agreed_amount,
                recommendations=command.recommendations,
            )
        if command.parts_source:
            order = db.update_order_parts_source(record_id, command.parts_source, owner_id)
        await state.clear()
        await sync_service_order_cards(bot, order)
        await message.answer(
            "✅ Карточка заказа изменена.\n\n" + service_order_card_text(order),
            reply_markup=main_keyboard,
        )
    else:
        await state.clear()
        await message.answer("Неизвестный тип карточки.", reply_markup=main_keyboard)


@router.callback_query(F.data.startswith("delete:"))
async def delete_record(callback: CallbackQuery, state: FSMContext) -> None:
    _, kind, raw_id = callback.data.split(":", 2)
    labels = {"customer": "клиента", "order": "заказ-наряд", "receipt": "чек"}
    await state.set_state(ConfirmDelete.waiting)
    await state.update_data(delete_kind=f"delete_{kind}", delete_id=int(raw_id))
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Переместить в архив: {labels.get(kind, 'запись')}? Запись останется в журнале.",
            reply_markup=confirm_delete_keyboard,
        )


@router.callback_query(F.data.startswith("markup40:receipt:"))
async def markup_receipt_40(callback: CallbackQuery, bot: Bot) -> None:
    receipt_id = int(callback.data.rsplit(":", 1)[1])
    assert callback.from_user is not None
    owner_id = db.add_or_update_user(
        callback.from_user.id, callback.from_user.full_name, callback.from_user.username
    )
    result = db.apply_markup_to_receipt(owner_id, receipt_id, 40)
    await callback.answer()
    if callback.message is None:
        return
    if result is None:
        await callback.message.answer("Чек не найден.")
        return
    order_id, count, purchase_cost, markup_profit = result
    if count == 0:
        await callback.message.answer("Наценка на этот чек уже была применена.")
        return
    updated = db.get_service_order(order_id)
    await sync_service_order_cards(bot, updated)
    await callback.message.edit_reply_markup(reply_markup=receipt_action_keyboard(receipt_id, can_markup=False))
    await callback.message.answer(
        f"✅ Наценка 40% применена к {count} позициям.\n"
        f"Закупка: {purchase_cost:,} ₽\n"
        f"Цена клиенту: {purchase_cost + markup_profit:,} ₽\n"
        f"Заработок на запчастях: {markup_profit:,} ₽\n"
        f"Общая прибыль заказа: {updated.profit:,} ₽".replace(",", " "),
        reply_markup=main_keyboard,
    )


@router.message(F.text == CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Готово.", reply_markup=main_keyboard)


@router.message(ConfirmDelete.waiting, F.text == CONFIRM_DELETE)
async def confirm_delete(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    owner_id = current_user_id(message)
    kind = data["delete_kind"]
    if kind == "purge_archive":
        backup_dir = Path(os.getenv("BACKUP_DIR", BASE_DIR / "backups"))
        retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
        try:
            backup_path = await asyncio.to_thread(
                create_backup, BASE_DIR / "workshop.sqlite3", backup_dir, retention_days
            )
            await asyncio.to_thread(verify_backup, backup_path)
            deleted = db.purge_archived(owner_id)
        except Exception as error:
            await state.clear()
            await message.answer(
                f"⚠️ Архив не очищен: резервная копия не прошла проверку ({type(error).__name__}).",
                reply_markup=main_keyboard,
            )
            return
        await state.clear()
        await message.answer(
            "✅ Архив очищен безвозвратно после создания резервной копии.\n"
            f"Заказов: {deleted['orders']} · автомобилей: {deleted['cars']} · клиентов: {deleted['customers']}",
            reply_markup=main_keyboard,
        )
        return
    target_id = int(data["delete_id"])
    if kind == "delete_customer":
        deleted = db.delete_customer(owner_id, target_id)
    elif kind == "delete_car":
        deleted = db.delete_car(owner_id, target_id)
    elif kind == "delete_receipt":
        deleted = db.delete_receipt(owner_id, target_id)
    else:
        deleted = db.delete_service_order(owner_id, target_id)
    await state.clear()
    await message.answer("✅ Перемещено в архив." if deleted else "Запись уже в архиве или не найдена.", reply_markup=main_keyboard)


@router.message(ConfirmDelete.waiting)
async def delete_waiting(message: Message) -> None:
    await message.answer("Нажмите «Удалить» для подтверждения или «Отмена».")


async def add_photo_start(
    message: Message, state: FSMContext, recognize: bool, telegram_id: int | None = None
) -> None:
    if telegram_id is None:
        assert message.from_user is not None
        telegram_id = message.from_user.id
    orders = db.get_recent_orders_for_telegram_user(telegram_id)
    if not orders:
        await message.answer("Сначала создайте заказ-наряд.")
        return
    await state.update_data(orders={str(order.id): order.id for order in orders}, recognize_image=recognize)
    await state.set_state(AddPhoto.order)
    choices = "\n".join(f"{order.id}. {order.brand} {order.model}: {order.description}" for order in orders)
    await message.answer(f"Выберите номер заказ-наряда:\n{choices}", reply_markup=cancel_keyboard)


@router.message(F.text == WORK_PHOTO)
async def add_work_photo_start(message: Message, state: FSMContext) -> None:
    await add_photo_start(message, state, recognize=False)


@router.message(F.text == RECEIPT_PHOTO)
async def add_receipt_photo_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_receipts(message)


@router.callback_query(F.data == "receipt:add")
async def add_receipt_from_history(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await add_photo_start(callback.message, state, recognize=True, telegram_id=callback.from_user.id)


@router.message(AddPhoto.order, F.text)
async def photo_order(message: Message, state: FSMContext) -> None:
    if message.text == CANCEL:
        await state.clear()
        await message.answer("Добавление фото отменено.", reply_markup=main_keyboard)
        return
    data = await state.get_data()
    selected = message.text.strip()
    if selected not in data["orders"]:
        await message.answer("Выберите номер из списка.")
        return
    await state.update_data(order_id=data["orders"][selected])
    await state.set_state(AddPhoto.upload)
    if data.get("recognize_image"):
        await message.answer("Отправьте чек или скриншот корзины с запчастями и ценами. Бот распознает только это изображение.")
    else:
        await message.answer("Отправляйте фото выполненных работ. Они будут только сохранены в заказе — распознавания не будет.")


async def recognize_order_image(message: Message, state: FSMContext, bot: Bot, file_id: str, mime_type: str) -> None:
    data = await state.get_data()
    order_id = int(data["order_id"])
    db.add_order_photo(order_id, file_id, message.caption, photo_type="receipt")
    settings = openrouter_settings()
    if settings is None or not ai_budget_available():
        await message.answer("✅ Фото сохранено. Распознавание сейчас недоступно: проверьте ключ OpenRouter или лимит ИИ.")
        return
    try:
        downloaded = await bot.download(file_id)
        if downloaded is None:
            raise OpenRouterError("Не удалось скачать изображение из Telegram.")
        image = downloaded.getvalue()
        if len(image) > 10 * 1024 * 1024:
            await message.answer("✅ Фото сохранено. Для распознавания отправьте изображение до 10 МБ.")
            return
        api_key, _, vision_model, _, _ = settings
        response = await analyze_receipt_image(api_key, image, mime_type, vision_model)
        record_ai_usage("vision", response)
        analysis = response.value
        items = [item for item in analysis.items if item.name and item.total_cost is not None]
        total_cost = analysis.total_cost if analysis.total_cost is not None else sum(item.total_cost or 0 for item in items)
        if not items and not total_cost:
            await message.answer("✅ Фото сохранено. Не удалось уверенно распознать позиции или итоговую сумму.")
            return
        await state.update_data(
            receipt_order_id=order_id,
            receipt_items=[(item.name, item.article, item.quantity, item.unit_cost, item.total_cost) for item in items],
            receipt_total=total_cost,
        )
        lines = ["🧾 Распознано как закупка запчастей:"]
        for item in items[:12]:
            quantity = f" × {item.quantity:g}" if item.quantity is not None else ""
            article = f" · арт. {item.article}" if item.article else ""
            lines.append(f"• {item.name}{quantity}{article}")
        lines.append(f"\nСебестоимость к добавлению: {total_cost:,} ₽".replace(",", " "))
        lines.append("Добавить позиции и сумму в заказ? Выручка и работы не изменятся.")
        await state.set_state(ConfirmReceipt.waiting)
        await message.answer("\n".join(lines), reply_markup=confirm_receipt_keyboard)
    except OpenRouterError as error:
        await message.answer(f"✅ Фото сохранено, но распознать его не удалось: {error}")


async def resolve_direct_receipt_target(
    message: Message, state: FSMContext, bot: Bot, target_text: str
) -> None:
    data = await state.get_data()
    file_id = str(data["direct_receipt_file_id"])
    mime_type = str(data.get("direct_receipt_mime_type", "image/jpeg"))
    settings = openrouter_settings()
    if settings is None:
        await message.answer("Для определения клиента или автомобиля нужен OPENROUTER_API_KEY.")
        return
    try:
        response = await parse_workshop_command(
            settings[0],
            f"Определи только клиента и автомобиль, к заказу которых нужно добавить чек: {target_text}",
            settings[1],
        )
        record_ai_usage("receipt_target", response)
        command = response.value
    except OpenRouterError as error:
        await message.answer(f"Не удалось определить заказ для чека: {error}")
        return

    owner_id = current_user_id(message)
    car = db.find_car_by_details(
        owner_id, command.car_brand, command.car_model, command.plate_number, command.vin
    )
    if car is not None:
        order = db.get_latest_order_for_car(car.id)
        if order is not None and order.status == "in_progress":
            await state.update_data(order_id=order.id, recognize_image=True)
            await recognize_order_image(message, state, bot, file_id, mime_type)
            return

    customer = db.find_customer(owner_id, command.customer_name, command.customer_phone)
    if customer is None:
        await message.answer("Не нашёл клиента или автомобиль. Укажите ФИО, госномер либо марку и модель.")
        return
    orders = db.get_active_orders_for_customer(owner_id, customer.id)
    if not orders:
        await message.answer(f"У клиента {customer_name_label(customer.full_name)} нет заказ-нарядов в работе.")
        return
    if len(orders) == 1:
        await state.update_data(order_id=orders[0].id, recognize_image=True)
        await recognize_order_image(message, state, bot, file_id, mime_type)
        return
    await state.set_state(DirectReceipt.choosing_order)
    await message.answer(
        f"У клиента {customer_name_label(customer.full_name)} несколько автомобилей в работе. Выберите заказ:",
        reply_markup=receipt_order_choices(orders),
    )


@router.callback_query(F.data.startswith("receipt:target:"))
async def choose_direct_receipt_order(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if "direct_receipt_file_id" not in data:
        await callback.answer("Фото чека уже не ожидает выбора.", show_alert=True)
        return
    order_id = int(callback.data.rsplit(":", 1)[1])
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=100)
    if not any(order.id == order_id and order.status == "in_progress" for order in allowed):
        await callback.answer("Заказ не найден или уже закрыт.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(order_id=order_id, recognize_image=True)
    if callback.message:
        await recognize_order_image(
            callback.message,
            state,
            bot,
            str(data["direct_receipt_file_id"]),
            str(data.get("direct_receipt_mime_type", "image/jpeg")),
        )


@router.message(DirectReceipt.waiting_target, F.text)
async def direct_receipt_target_text(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text == CANCEL:
        await state.clear()
        await message.answer("Добавление чека отменено.", reply_markup=main_keyboard)
        return
    await resolve_direct_receipt_target(message, state, bot, message.text)


@router.message(DirectReceipt.waiting_target, F.voice)
async def direct_receipt_target_voice(message: Message, state: FSMContext, bot: Bot) -> None:
    settings = openrouter_settings()
    if settings is None:
        await message.answer("Для голосовой команды нужен OPENROUTER_API_KEY.")
        return
    downloaded = await bot.download(message.voice)
    if downloaded is None:
        await message.answer("Не удалось скачать голосовое сообщение.")
        return
    try:
        response = await transcribe_voice(settings[0], downloaded.getvalue(), settings[4])
        record_ai_usage("transcription", response)
        await resolve_direct_receipt_target(message, state, bot, response.value)
    except OpenRouterError as error:
        await message.answer(f"Не удалось распознать голосовое сообщение: {error}")


@router.message(AddPhoto.upload, F.photo)
async def save_order_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if data.get("recognize_image"):
        await recognize_order_image(message, state, bot, message.photo[-1].file_id, "image/jpeg")
        return
    order_id = int(data["order_id"])
    db.add_order_photo(order_id, message.photo[-1].file_id, message.caption)
    await sync_service_order_cards(bot, db.get_service_order(order_id))
    await message.answer(f"✅ Фото работы сохранено. Всего: {db.count_order_photos(data['order_id'])}.")


@router.message(AddPhoto.upload, F.document)
async def save_order_document(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not data.get("recognize_image"):
        await message.answer("Для фото выполненных работ отправьте обычное фото, не файл-документ.")
        return
    document = message.document
    if document.mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        await message.answer("Пришлите изображение: JPG, PNG или WEBP.")
        return
    await recognize_order_image(message, state, bot, document.file_id, document.mime_type)


@router.message(F.photo)
async def direct_receipt_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.photo[-1].file_id
    await state.clear()
    await state.update_data(
        direct_receipt_file_id=file_id,
        direct_receipt_mime_type="image/jpeg",
    )
    await state.set_state(DirectReceipt.waiting_target)
    if message.caption and message.caption.strip():
        await resolve_direct_receipt_target(message, state, bot, message.caption.strip())
    else:
        await message.answer(
            "К какому клиенту или автомобилю добавить чек?\n"
            "Напишите или скажите голосом ФИО, госномер либо марку и модель.",
            reply_markup=cancel_keyboard,
        )


@router.message(ConfirmReceipt.waiting, F.text == CONFIRM_RECEIPT)
async def confirm_receipt(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data["receipt_order_id"])
    items = data.get("receipt_items", [])
    total_cost = int(data["receipt_total"])
    receipt = db.add_receipt(order_id, total_cost, [(str(name), article, quantity, unit_cost, item_total) for name, article, quantity, unit_cost, item_total in items])
    updated = db.get_service_order(order_id)
    await sync_service_order_cards(bot, updated)
    await state.clear()
    await message.answer(
        f"✅ В заказ #{order_id} добавлены запчасти и себестоимость {total_cost:,} ₽.\n"
        f"Текущая себестоимость запчастей: {updated.parts_cost:,} ₽.".replace(",", " "),
        reply_markup=receipt_action_keyboard(receipt.id),
    )


@router.message(ConfirmReceipt.waiting)
async def receipt_waiting(message: Message) -> None:
    await message.answer("Нажмите «Добавить запчасти» или «Отмена».")


@router.message(F.text == REPORT)
async def report(message: Message) -> None:
    assert message.from_user is not None
    data = db.get_report_for_telegram_user(message.from_user.id)
    await message.answer(
        f"📊 Финансы\n\n"
        f"Заказ-нарядов: {data.orders}\n"
        f"Не приехали (No-show): {data.no_shows}\n"
        f"Стоимость работ: {data.labor_revenue:,} ₽\n"
        f"Прибыль с запчастей: {data.parts_margin:,} ₽\n"
        f"💵 Заработок за сегодня: {data.today_profit:,} ₽\n"
        f"💰 Общая прибыль: {data.profit:,} ₽".replace(",", " ")
    )


@router.message(F.text == AI_USAGE)
async def ai_usage(message: Message) -> None:
    daily_cost, daily_requests = db.get_ai_usage("datetime('now', 'start of day')")
    monthly_cost, monthly_requests = db.get_ai_usage("datetime('now', 'start of month')")
    await message.answer(
        f"💳 Расходы ИИ\n\nСегодня: ${daily_cost:.4f} · запросов: {daily_requests}\n"
        f"За месяц: ${monthly_cost:.4f} · запросов: {monthly_requests}\n\n"
        f"Лимиты: ${float(os.getenv('AI_DAILY_LIMIT_USD', '1.00')):.2f}/день · "
        f"${float(os.getenv('AI_MONTHLY_LIMIT_USD', '15.00')):.2f}/месяц"
    )


async def process_text(
    message: Message, text: str, state: FSMContext, bot: Bot
) -> None:
    assert message.from_user is not None
    normalized_request = text.casefold().replace("ё", "е")
    owner_id = current_user_id(message)
    if is_chat_cleanup_request(text):
        await run_manual_chat_cleanup(message, bot, state, text)
        return
    if "кто записан" in normalized_request or "записи на" in normalized_request:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        if "завтра" in normalized_request:
            await show_appointments(message, now + timedelta(days=1))
            return
        if "сегодня" in normalized_request:
            await show_appointments(message, now)
            return
    if "очист" in normalized_request and "архив" in normalized_request:
        counts = db.count_archived(owner_id)
        total = sum(counts.values())
        if total == 0:
            await message.answer("Архив уже пуст.")
            return
        await state.set_state(ConfirmDelete.waiting)
        await state.update_data(delete_kind="purge_archive")
        await message.answer(
            "Безвозвратно очистить весь архив? Перед удалением будет создана и проверена резервная копия.\n"
            f"Заказов: {counts['orders']} · автомобилей: {counts['cars']} · клиентов: {counts['customers']}",
            reply_markup=confirm_delete_keyboard,
        )
        return
    if "журнал измен" in normalized_request or "что изменял" in normalized_request:
        entries = db.get_audit_log(owner_id)
        if not entries:
            await message.answer("Журнал изменений пока пуст.")
            return
        labels = {"order": "заказ", "car": "автомобиль", "customer": "клиент"}
        lines = ["🕘 Последние изменения:"]
        for entry in entries:
            title = labels.get(str(entry["entity_type"]), str(entry["entity_type"]))
            details = f" · {entry['details']}" if entry["details"] else ""
            lines.append(f"{str(entry['created_at'])[:16]} · {title} #{entry['entity_id']} · {entry['action']}{details}")
        await message.answer("\n".join(lines))
        return
    if normalized_request.strip() in {"покажи архив", "архив", "что в архиве"}:
        entries = db.get_archived(owner_id)
        if not entries:
            await message.answer("Архив пуст.")
            return
        lines = ["🗄 Архив заказов:"]
        for entry in entries:
            car = f"{entry['brand']} {entry['model']}" + (f" · {entry['plate_number']}" if entry["plate_number"] else "")
            lines.append(f"#{entry['id']} · {car} · {entry['description']} · {str(entry['archived_at'])[:16]}")
        await message.answer("\n".join(lines))
        return
    if "давно не приезжал" in normalized_request or "давно не приезжали" in normalized_request:
        entries = db.get_inactive_customers(owner_id)
        if not entries:
            await message.answer("Нет клиентов без визита более 180 дней.")
            return
        lines = ["📭 Клиенты без визита более 180 дней:"]
        for entry in entries:
            last_visit = str(entry["last_visit"])[:10] if entry["last_visit"] else "визитов ещё не было"
            car = f"{entry['brand']} {entry['model']}" + (f" · {entry['plate_number']}" if entry["plate_number"] else "")
            lines.append(f"• {customer_name_label(entry['full_name'])} · {car} · {last_visit}")
        await message.answer("\n".join(lines))
        return
    settings = openrouter_settings()
    if settings is None:
        await message.answer("Добавьте OPENROUTER_API_KEY в .env и перезапустите бота.")
        return
    if not ai_budget_available():
        await message.answer("Достигнут лимит расходов ИИ. Обычные кнопки и поиск продолжают работать.")
        return
    api_key, model, _, _, _ = settings
    recent_messages = db.get_recent_incoming_texts(message.from_user.id, limit=8)
    ignored_context = {
        SEARCH, CUSTOMERS, APPOINTMENTS, ORDERS, COMPLETED_ORDERS,
        COMPLETE_ORDER, WORK_PHOTO,
        RECEIPT_PHOTO, REPORT, AI_USAGE, CANCEL, "[медиа/голосовое]",
    }
    if recent_messages and recent_messages[-1].strip() in {text.strip(), "[медиа/голосовое]"}:
        recent_messages = recent_messages[:-1]
    conversation_context = [
        safe_conversation_context(item) for item in recent_messages
        if item.strip() not in ignored_context and not item.strip().isdigit()
    ][-4:]
    try:
        response = await parse_workshop_command(
            api_key, text, model, conversation_context
        )
        record_ai_usage("text", response)
        command = response.value

        if command.intent == "query_crm" or is_semantic_crm_read_request(text):
            await show_semantic_crm_query(message, command, text)
            return

        order_words = (
            "работ", "замен", "ремонт", "диагност", "стоим", "руб", "₽",
            "заказ", "сделал", "поменял", "установ",
        )
        looks_like_order = any(word in text.casefold() for word in order_words)
        missing_order_data = (
            command.intent == "create_order"
            and (
                not command.description
                or not (command.car_brand and command.car_model)
            )
        )
        suspicious_customer_only = (
            command.intent in {"upsert_customer", "unknown"} and looks_like_order
        )

        if missing_order_data or suspicious_customer_only:
            advanced_model = settings[3]
            advanced_response = await parse_workshop_command(
                api_key, text, advanced_model, conversation_context
            )
            record_ai_usage("text_advanced_retry", advanced_response)
            advanced = advanced_response.value
            merged: dict[str, object] = {}
            for field_name in command.__dataclass_fields__:
                advanced_value = getattr(advanced, field_name)
                original_value = getattr(command, field_name)
                merged[field_name] = advanced_value if advanced_value is not None else original_value
            if advanced.intent != "unknown":
                merged["intent"] = advanced.intent
            command = WorkshopCommand(**merged)

        brand = (command.car_brand or "").casefold()
        model_name = (command.car_model or "").casefold()
        if brand in {"нива", "niva"} and not command.car_model:
            command = WorkshopCommand(
                **{
                    **{name: getattr(command, name) for name in command.__dataclass_fields__},
                    "car_brand": "Lada",
                    "car_model": "Niva",
                }
            )
        elif model_name in {"нива", "niva"} and not command.car_brand:
            command = WorkshopCommand(
                **{
                    **{name: getattr(command, name) for name in command.__dataclass_fields__},
                    "car_brand": "Lada",
                    "car_model": "Niva",
                }
            )

        # The AI occasionally copies a labor amount into parts_profit.  Accept
        # that field only when the user explicitly talks about profit/earnings
        # from parts; phrases such as "работа 1500" must affect labor only.
        normalized_text = text.casefold().replace("ё", "е")
        mentions_parts = any(word in normalized_text for word in ("запчаст", "детал", "расходник"))
        mentions_parts_profit = mentions_parts and any(
            word in normalized_text for word in ("прибыл", "заработ", "марж")
        )
        if command.parts_profit is not None and not mentions_parts_profit:
            command = WorkshopCommand(
                **{
                    **{name: getattr(command, name) for name in command.__dataclass_fields__},
                    "parts_profit": None,
                }
            )

        command = fill_contact_and_appointment_from_text(command, text)

        await apply_command(message, command, state, bot, text)
    except OpenRouterError as error:
        await message.answer(f"Не удалось обработать запрос: {error}")
    except Exception:
        logging.exception("Unexpected error while processing CRM text request")
        await message.answer(
            "Не удалось обработать запрос: сервис распознавания временно недоступен. "
            "Повторите попытку позже; данные не были изменены."
        )


@router.message(F.voice)
async def voice_to_crm(message: Message, bot: Bot, state: FSMContext) -> None:
    settings = openrouter_settings()
    if settings is None:
        await message.answer("Добавьте OPENROUTER_API_KEY в .env и перезапустите бота.")
        return
    if not ai_budget_available():
        await message.answer("Достигнут лимит расходов ИИ. Попробуйте позже или увеличьте лимит в .env.")
        return
    api_key, _, _, _, transcription_model = settings
    try:
        audio = await bot.download(message.voice)
        if audio is None:
            raise OpenRouterError("Не удалось скачать голосовое из Telegram.")
        transcript_response = await transcribe_voice(api_key, audio.getvalue(), transcription_model)
        record_ai_usage("transcription", transcript_response)
        await process_text(message, transcript_response.value, state, bot)
    except OpenRouterError as error:
        await message.answer(f"Не удалось обработать голосовое: {error}")


@router.message(F.text)
async def text_to_crm(message: Message, bot: Bot, state: FSMContext) -> None:
    await process_text(message, message.text, state, bot)


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token or token == "your_telegram_bot_token":
        raise RuntimeError("Set BOT_TOKEN in the .env file before starting the bot.")
    db.initialize()
    backup_dir = Path(os.getenv("BACKUP_DIR", BASE_DIR / "backups"))
    retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))

    async def backup_loop() -> None:
        while True:
            try:
                backup_path = await asyncio.to_thread(
                    create_backup, BASE_DIR / "workshop.sqlite3", backup_dir, retention_days
                )
                await asyncio.to_thread(verify_backup, backup_path)
            except Exception as error:
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️ Не удалось создать или проверить резервную копию CRM: {type(error).__name__}: {error}",
                )
            await asyncio.sleep(24 * 60 * 60)

    async def chat_cleanup_loop() -> None:
        if os.getenv("CHAT_CLEANUP_ENABLED", "true").casefold() not in {"1", "true", "yes", "да"}:
            return
        timezone = ZoneInfo("Europe/Moscow")
        cleanup_hour = int(os.getenv("CHAT_CLEANUP_HOUR", "23"))
        cleanup_chat_ids = configured_chat_cleanup_ids()
        while True:
            now = datetime.now(timezone)
            if now.hour == cleanup_hour and now.minute >= 50:
                for chat_id in cleanup_chat_ids:
                    deleted: list[int] = []
                    for message_id in db.get_chat_messages(
                        chat_id, include_important=True
                    ):
                        try:
                            await bot.delete_message(chat_id, message_id)
                            deleted.append(message_id)
                        except TelegramBadRequest as error:
                            if "message to delete not found" in str(error).casefold():
                                deleted.append(message_id)
                            # The bot may lack delete rights or Telegram may reject service messages.
                            continue
                        except Exception:
                            # The bot may lack delete rights or Telegram may reject old/service messages.
                            continue
                    db.forget_chat_messages(chat_id, deleted)
            await asyncio.sleep(60)

    async def archive_cleanup_loop() -> None:
        archive_days = int(os.getenv("ARCHIVE_RETENTION_DAYS", "30"))
        timezone = ZoneInfo("Europe/Moscow")
        while True:
            now = datetime.now(timezone)
            claim = f"archive-cleanup:{now.date().isoformat()}"
            if now.hour == 3 and db.claim_daily_reminder(claim):
                owner = db.add_or_update_user(ADMIN_ID, "CRM owner", None)
                counts = db.count_archived(owner, older_than_days=archive_days)
                if sum(counts.values()) > 0:
                    try:
                        backup_path = await asyncio.to_thread(
                            create_backup, BASE_DIR / "workshop.sqlite3", backup_dir, retention_days
                        )
                        await asyncio.to_thread(verify_backup, backup_path)
                        db.purge_archived(owner, older_than_days=archive_days)
                    except Exception as error:
                        await bot.send_message(
                            ADMIN_ID,
                            "⚠️ Автоочистка архива отменена: не удалось создать или проверить "
                            f"резервную копию ({type(error).__name__}: {error}).",
                        )
            await asyncio.sleep(60)

    async def unfinished_orders_reminder_loop() -> None:
        timezone = ZoneInfo("Europe/Moscow")
        while True:
            now = datetime.now(timezone)
            service_claim = f"service:{now.date().isoformat()}"
            if now.hour == 9 and db.claim_daily_reminder(service_claim):
                owner = db.add_or_update_user(ADMIN_ID, "CRM owner", None)
                due = db.get_due_services(owner)
                if due:
                    lines = ["🔔 Ближайшее ТО:"]
                    for item in due:
                        car = f"{item['brand']} {item['model']}" + (
                            f" · {item['plate_number']}" if item["plate_number"] else ""
                        )
                        reason = []
                        if item["next_service_date"]:
                            reason.append(f"дата {str(item['next_service_date'])[:10]}")
                        if item["next_service_mileage"]:
                            reason.append(f"пробег {item['next_service_mileage']} км")
                        lines.append(f"• {customer_name_label(item['customer_name'])} · {car} · {', '.join(reason)}")
                    await bot.send_message(ADMIN_ID, "\n".join(lines))
            if now.hour == 20 and db.claim_daily_reminder(now.date().isoformat()):
                orders = [
                    order
                    for order in db.get_recent_orders_for_telegram_user(ADMIN_ID, limit=100)
                    if order.status == "in_progress"
                ]
                if orders:
                    lines = ["🌙 Конец рабочего дня", "", "Остались незакрытые заказ-наряды:"]
                    for order in orders:
                        car = f"{order.brand} {order.model}" + (
                            f" · {order.plate_number}" if order.plate_number else ""
                        )
                        lines.append(f"#{order.id} · {car} — {order.description}")
                    lines.append("\nЗакрыть их или оставить в работе?")
                    await bot.send_message(
                        ADMIN_ID,
                        "\n".join(lines),
                        reply_markup=unfinished_orders_keyboard([order.id for order in orders]),
                    )
            await asyncio.sleep(60)

    bot = Bot(token=token)
    bot.session.middleware(OutgoingMessageTracker())
    dispatcher = Dispatcher()
    router.message.outer_middleware(IncomingMessageTracker())
    dispatcher.include_router(router)
    asyncio.create_task(backup_loop())
    asyncio.create_task(unfinished_orders_reminder_loop())
    asyncio.create_task(chat_cleanup_loop())
    asyncio.create_task(archive_cleanup_loop())
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
