"""Telegram entry point for the car-workshop CRM."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

from backup import create_backup
from database import Database, ServiceOrder
from openrouter import OpenRouterError, WorkshopCommand, analyze_receipt_image, parse_workshop_command, transcribe_voice


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
db = Database(BASE_DIR / "workshop.sqlite3")
router = Router()

try:
    ADMIN_ID = int(os.environ["ADMIN_ID"])
except (KeyError, ValueError) as error:
    raise RuntimeError("Set a numeric ADMIN_ID in the .env file.") from error

router.message.filter(F.from_user.id == ADMIN_ID)
router.callback_query.filter(F.from_user.id == ADMIN_ID)

ORDERS = "🧾 Заказ-наряды"
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
        [KeyboardButton(text=SEARCH), KeyboardButton(text=CUSTOMERS)],
        [KeyboardButton(text=APPOINTMENTS)],
        [KeyboardButton(text=ORDERS)],
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
            [
                InlineKeyboardButton(text="🖼 Фото работ", callback_data=f"order:photos:{order_id}"),
                InlineKeyboardButton(text="➕ Добавить фото", callback_data=f"order:add-photo:{order_id}"),
            ],
            [
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:order:{order_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:order:{order_id}"),
            ],
        ]
    )


def customer_action_keyboard(customer_id: int, has_phone: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_phone:
        rows.append([InlineKeyboardButton(text="📱 Открыть контакт", callback_data=f"customer:contact:{customer_id}")])
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
        customer = overview.customer_name or "клиент не указан"
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


def order_status_label(status: str) -> str:
    return "✅ Выполнен" if status == "completed" else "🟡 В работе"


def appointment_datetime_label(value: datetime) -> str:
    weekdays = (
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    )
    return f"{value:%d.%m.%Y}, {weekdays[value.weekday()]}, {value:%H:%M}"


def order_summary(order: ServiceOrder, prefix: str = "✅ Заказ-наряд сохранён") -> str:
    car = f"{order.brand} {order.model}" + (f" ({order.plate_number})" if order.plate_number else "")
    return (
        f"{prefix}\n\n"
        f"👤 {order.customer_name or 'Клиент не указан'}\n"
        f"🚘 {car}\n"
        f"🔧 {order.description}\n\n"
        f"Работы: {money(order.labor_revenue)}\n"
        f"Закупка: {money(order.parts_cost)}\n"
        f"Запчасти клиенту: {money(order.parts_revenue)}\n"
        f"Прибыль с запчастей: {money(order.parts_margin)}\n"
        f"💰 Итого: {money(order.profit)}\n"
        f"Статус: {order_status_label(order.status)}"
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


def ai_budget_available() -> bool:
    daily_limit = float(os.getenv("AI_DAILY_LIMIT_USD", "1.00"))
    monthly_limit = float(os.getenv("AI_MONTHLY_LIMIT_USD", "15.00"))
    daily_cost, _ = db.get_ai_usage("datetime('now', 'start of day')")
    monthly_cost, _ = db.get_ai_usage("datetime('now', 'start of month')")
    return daily_cost < daily_limit and monthly_cost < monthly_limit


def record_ai_usage(task_type: str, response: object) -> None:
    db.log_ai_usage(task_type, response.model, response.input_tokens, response.output_tokens, response.cost_usd)  # type: ignore[attr-defined]


async def show_orders(message: Message) -> None:
    assert message.from_user is not None
    orders = db.get_recent_orders_for_telegram_user(message.from_user.id, limit=15)
    if not orders:
        await message.answer("Заказ-нарядов пока нет.")
        return
    await message.answer("🧾 Последние заказ-наряды:", reply_markup=main_keyboard)
    for order in orders:
        car = f"{order.brand} {order.model}" + (f" · {order.plate_number}" if order.plate_number else "")
        status = order_status_label(order.status)
        text = (
            f"#{order.id} · {car}\n"
            f"👤 {order.customer_name or 'Клиент не указан'}\n"
            f"{order.description}\n"
            f"{status} · Прибыль {money(order.profit)}"
        )
        await message.answer(text, reply_markup=order_list_keyboard(order.id))


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
        f"Клиент: {order.customer_name or 'не указан'}",
        f"Автомобиль: {car}",
        f"Статус: {status}",
        "",
        "🔧 Работы:",
        f"• {order.description}",
        f"Стоимость работ: {money(order.labor_revenue)}",
        "",
        "⚙️ Запчасти:",
    ]
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
    await callback.message.answer("\n".join(lines), reply_markup=order_detail_keyboard(order.id))


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
    await callback.message.answer(
        f"🖼 Фото работ · заказ #{order_id} · {order.brand} {order.model}\n"
        f"Всего фотографий: {len(photos)}"
    )
    for number, photo in enumerate(photos, start=1):
        caption = str(photo["caption"] or "").strip()
        photo_caption = f"Фото {number}/{len(photos)}"
        if caption:
            photo_caption += f"\n{caption}"
        await callback.message.answer_photo(
            str(photo["telegram_file_id"]),
            caption=photo_caption,
        )


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
    status = "закрытый" if order.status == "completed" else "активный"
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
        f"Клиент: {order.customer_name or 'не указан'}",
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
    lines = [f"🔎 Результаты: {query}"]
    for item in result["customers"]:
        lines.append(f"\nКлиент: {item['full_name']}" + (f" · {item['phone']}" if item["phone"] else ""))
    for item in result["cars"]:
        title = f"{item['brand']} {item['model']}" + (f" · {item['plate_number']}" if item["plate_number"] else "")
        details = []
        if item["vin"]:
            details.append(f"VIN {item['vin']}")
        if item["mileage"]:
            details.append(f"{item['mileage']} км")
        lines.append(f"\nАвтомобиль: {title}" + (f" · {item['customer_name']}" if item["customer_name"] else "") + (f"\n{' · '.join(details)}" if details else ""))
    for item in result["orders"]:
        status = "Выполнен" if item["status"] == "completed" else "В работе"
        lines.append(f"\nЗаказ #{item['id']}: {item['brand']} {item['model']} · {item['description']}\nСтатус: {status}")
    await message.answer("\n".join(lines), reply_markup=main_keyboard)
    for item in result["orders"]:
        await message.answer(
            f"Заказ #{item['id']} · открыть карточку и фото работ",
            reply_markup=order_list_keyboard(int(item["id"])),
        )


async def apply_command(message: Message, command: WorkshopCommand, state: FSMContext) -> None:
    if command.intent == "list_orders":
        await show_orders(message)
        return
    if command.intent == "unknown":
        await message.answer("Я могу записать или изменить клиента, автомобиль и заказ-наряд. Напишите или скажите это обычными словами.")
        return

    owner_id = current_user_id(message)

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
                    await message.answer(
                        order_summary(updated, "✅ Активный заказ клиента обновлён"),
                        reply_markup=order_detail_keyboard(updated.id),
                    )
                    return
        if not has_car_identity or not command.description:
            await message.answer(
                "Не удалось надёжно выделить автомобиль или работы. Ничего не сохранено — отправьте сообщение ещё раз."
            )
            return

    if command.intent.startswith("delete_"):
        await request_delete(message, command, owner_id, state)
        return

    if command.intent == "set_order_status":
        car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, command.plate_number, command.vin)
        order = db.get_service_order(command.order_id) if command.order_id else (db.get_latest_order_for_car(car.id) if car else None)
        if order is None or command.order_status is None:
            await message.answer("Укажите номер заказ-наряда или автомобиль и статус: «в работе» либо «выполнен».")
            return
        if command.order_status == "completed" and order.labor_revenue <= 0:
            await close_order_or_request_cost(message, state, order)
            return
        updated = db.set_order_status(order.id, command.order_status)
        await message.answer(order_summary(updated, "✅ Статус заказ-наряда обновлён"), reply_markup=main_keyboard)
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
        await message.answer(
            f"✅ Наценка {command.parts_markup_percent:g}% применена к {count} позициям.\n"
            f"Цена запчастей клиенту: {purchase_cost + profit:,} ₽.\n"
            f"В прибыль по запчастям добавлено: {profit:,} ₽.\n"
            f"Текущая прибыль по запчастям: {updated.parts_margin:,} ₽.".replace(",", " "),
            reply_markup=main_keyboard,
        )
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
        await message.answer(
            order_summary(updated, "✅ Заказ-наряд изменён"),
            reply_markup=action_keyboard("order", updated.id),
        )
        return
    customer = db.find_customer(owner_id, command.customer_name, command.customer_phone)
    if customer is None and command.customer_name:
        customer_id = db.add_customer(owner_id, command.customer_name, command.customer_phone)
    elif customer is not None:
        customer_id = customer.id
        db.update_customer(customer_id, command.customer_name, command.customer_phone)
    else:
        customer_id = None

    plate = command.plate_number.upper() if command.plate_number else None
    car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, plate, command.vin)
    if car is None and customer_id is not None:
        car = db.find_single_car_for_customer(owner_id, customer_id)
    if car is None and command.car_brand and command.car_model:
        car_id = db.add_car(owner_id, command.car_brand, command.car_model, command.car_year, plate, customer_id, command.vin, command.mileage)
    elif car is not None:
        car_id = car.id
        db.update_car(car_id, customer_id, command.car_brand, command.car_model, command.car_year, plate, command.vin, command.mileage)
    else:
        car_id = None

    if command.intent == "create_appointment":
        if car_id is None or not command.description or not command.appointment_start:
            await message.answer(
                "Не удалось надёжно определить автомобиль, работы или дату записи. Ничего не сохранено."
            )
            return
        try:
            starts_at = datetime.fromisoformat(command.appointment_start)
        except ValueError:
            await message.answer("Не удалось разобрать дату и время записи. Ничего не сохранено.")
            return
        appointment_id = db.add_appointment(
            car_id, command.description, starts_at.isoformat()
        )
        await message.answer(
            f"✅ Запись #{appointment_id} создана\n"
            f"Когда: {appointment_datetime_label(starts_at)}\n"
            f"Клиент: {command.customer_name or 'не указан'}\n"
            f"Автомобиль: {command.car_brand or ''} {command.car_model or ''}"
            + (f" · {plate}" if plate else "")
            + f"\nРаботы: {command.description}",
            reply_markup=main_keyboard,
        )
        return

    if command.intent == "upsert_customer":
        if customer_id is None and car_id is None:
            await message.answer("Не понял, какую карточку изменить. Укажите хотя бы имя клиента, телефон или автомобиль.")
        else:
            await message.answer("✅ Карточка клиента и автомобиля обновлена.", reply_markup=main_keyboard)
        return

    if car_id is None:
        await message.answer("Для заказ-наряда укажите марку и модель либо госномер автомобиля.")
        return

    if command.intent == "create_order":
        if not command.description:
            await message.answer("Напишите, какие работы выполнены — тогда создам заказ-наряд.")
            return
        order = db.add_service_order(car_id, command.description, command.labor_revenue or 0, command.parts_cost or 0, command.parts_revenue or 0, command.parts_profit or 0)
        await message.answer(order_summary(order, "🤖 Запись создана автоматически"), reply_markup=main_keyboard)
        return

    if command.intent == "update_order":
        order = db.get_latest_order_for_car(car_id)
        if order is None:
            await message.answer("У этого автомобиля пока нет заказ-нарядов. Опишите выполненные работы, и я создам первый.")
            return
        updated = db.update_service_order(order.id, command.description, command.labor_revenue, command.parts_cost, command.parts_revenue, command.parts_profit, add_amounts=True)
        await message.answer(order_summary(updated, "✅ Заказ-наряд дополнен"), reply_markup=main_keyboard)


async def request_delete(message: Message, command: WorkshopCommand, owner_id: int, state: FSMContext) -> None:
    target_id: int | None = None
    label = ""
    if command.intent == "delete_customer":
        customer = db.find_customer(owner_id, command.customer_name, command.customer_phone)
        if customer:
            target_id, label = customer.id, f"клиента {customer.full_name} и все его автомобили с заказ-нарядами"
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
    await message.answer(f"Подтвердите: удалить {label}? Это действие нельзя отменить.", reply_markup=confirm_delete_keyboard)


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
    await message.answer("Введите имя, телефон, госномер или VIN.", reply_markup=cancel_keyboard)


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


@router.message(F.text == APPOINTMENTS)
async def appointments_button(message: Message) -> None:
    assert message.from_user is not None
    appointments = db.get_upcoming_appointments_for_telegram_user(message.from_user.id)
    if not appointments:
        await message.answer("Предстоящих записей пока нет.", reply_markup=main_keyboard)
        return
    await message.answer("📅 Предстоящие записи:", reply_markup=main_keyboard)
    for appointment in appointments:
        starts_at = datetime.fromisoformat(appointment.starts_at)
        car = f"{appointment.brand} {appointment.model}" + (
            f" · {appointment.plate_number}" if appointment.plate_number else ""
        )
        await message.answer(
            f"Запись #{appointment.id}\n"
            f"🗓 {appointment_datetime_label(starts_at)}\n"
            f"👤 {appointment.customer_name or 'Клиент не указан'}"
            + (f" · {appointment.customer_phone}" if appointment.customer_phone else "")
            + f"\n🚘 {car}\n"
            f"🔧 {appointment.description}"
        )


async def close_order_or_request_cost(
    message: Message, state: FSMContext, order: ServiceOrder
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
    closed = db.set_order_status(order.id, "completed")
    await state.clear()
    await message.answer(order_summary(closed, "✅ Заказ-наряд закрыт"), reply_markup=main_keyboard)


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
async def complete_order_selected(message: Message, state: FSMContext) -> None:
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
    await close_order_or_request_cost(message, state, order)


@router.message(CloseOrderCost.waiting, F.text)
async def close_order_cost(message: Message, state: FSMContext) -> None:
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
    closed = db.set_order_status(updated.id, "completed")
    await state.clear()
    await message.answer(order_summary(closed, "✅ Стоимость сохранена, заказ закрыт"), reply_markup=main_keyboard)


@router.message(F.text == CUSTOMERS)
async def customers_button(message: Message) -> None:
    assert message.from_user is not None
    customers = db.get_customer_overviews(message.from_user.id)
    if not customers:
        await message.answer("Клиентов пока нет.")
        return
    await message.answer("👥 Клиенты:", reply_markup=main_keyboard)
    for overview in customers[:20]:
        customer = overview.customer
        lines = [customer.full_name + (f" · {customer.phone}" if customer.phone else " · телефон не указан")]
        if not overview.cars:
            lines.append("Автомобили не добавлены")
        for item in overview.cars:
            car = item.car
            title = f"{car.brand} {car.model}" + (f" · {car.plate_number}" if car.plate_number else " · без номера")
            lines.append(f"{title}\nЗаказов: {item.orders_total} · В работе: {item.in_progress} · Выполнено: {item.completed}")
        await message.answer(
            "\n".join(lines),
            reply_markup=customer_action_keyboard(customer.id, has_phone=bool(customer.phone)),
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
        first_name=customer.full_name,
    )


@router.callback_query(F.data.startswith("reminder:"))
async def handle_order_reminder(callback: CallbackQuery, state: FSMContext) -> None:
    _, action, raw_id = callback.data.split(":", 2)
    order_id = int(raw_id)
    allowed = db.get_recent_orders_for_telegram_user(callback.from_user.id, limit=100)
    order = next((item for item in allowed if item.id == order_id), None)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if action == "close":
        if order.status == "completed":
            await callback.answer("Заказ уже закрыт.")
            return
        if callback.message:
            await callback.answer()
            await close_order_or_request_cost(callback.message, state, order)
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
        "receipt": "Отправьте новую итоговую сумму чека одним числом.",
    }
    await callback.answer()
    if callback.message:
        await callback.message.answer(prompts.get(kind, "Отправьте новые данные."), reply_markup=cancel_keyboard)


@router.message(EditRecord.waiting, F.text)
async def edit_record_value(message: Message, state: FSMContext) -> None:
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

        if phone is None and parsed and parsed.customer_phone:
            phone = parsed.customer_phone
        name = parsed.customer_name if parsed and parsed.customer_name else None
        if name and phone and phone in name:
            name = name.replace(phone, "").strip(" ,;|-")
        if not name:
            remaining = text
            if phone_match:
                remaining = remaining.replace(phone_match.group(), " ")
            name = re.sub(r"\s+", " ", remaining).strip(" ,;|-") or None

        db.update_customer(record_id, name, phone)

        car_changed = False
        if parsed and (parsed.car_brand or parsed.car_model or parsed.plate_number or parsed.vin or parsed.mileage):
            car = db.find_car_by_details(
                owner_id, parsed.car_brand, parsed.car_model, parsed.plate_number, parsed.vin
            )
            if car is None:
                car = db.find_single_car_for_customer(owner_id, record_id)
            plate = parsed.plate_number.upper() if parsed.plate_number else None
            if car is not None:
                db.update_car(
                    car.id, record_id, parsed.car_brand, parsed.car_model, parsed.car_year,
                    plate, parsed.vin, parsed.mileage,
                )
                car_changed = True
            elif parsed.car_brand and parsed.car_model:
                db.add_car(
                    owner_id, parsed.car_brand, parsed.car_model, parsed.car_year,
                    plate, record_id, parsed.vin, parsed.mileage,
                )
                car_changed = True

        await state.clear()
        updated = db.get_customer_for_telegram_user(message.from_user.id, record_id)
        result = [
            "✅ Карточка клиента изменена.",
            f"Имя: {updated.full_name}",
            f"Телефон: {updated.phone or 'не указан'}",
        ]
        if car_changed:
            result.append("Автомобиль также обновлён.")
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
    else:
        await state.clear()
        await process_text(message, f"Измени заказ #{record_id}: {message.text}", state)


@router.callback_query(F.data.startswith("delete:"))
async def delete_record(callback: CallbackQuery, state: FSMContext) -> None:
    _, kind, raw_id = callback.data.split(":", 2)
    labels = {"customer": "клиента", "order": "заказ-наряд", "receipt": "чек"}
    await state.set_state(ConfirmDelete.waiting)
    await state.update_data(delete_kind=f"delete_{kind}", delete_id=int(raw_id))
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Подтвердите удаление: {labels.get(kind, 'запись')}? Это действие нельзя отменить.",
            reply_markup=confirm_delete_keyboard,
        )


@router.callback_query(F.data.startswith("markup40:receipt:"))
async def markup_receipt_40(callback: CallbackQuery) -> None:
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
    kind, target_id = data["delete_kind"], int(data["delete_id"])
    if kind == "delete_customer":
        deleted = db.delete_customer(owner_id, target_id)
    elif kind == "delete_car":
        deleted = db.delete_car(owner_id, target_id)
    elif kind == "delete_receipt":
        deleted = db.delete_receipt(owner_id, target_id)
    else:
        deleted = db.delete_service_order(owner_id, target_id)
    await state.clear()
    await message.answer("✅ Удалено." if deleted else "Запись уже удалена или не найдена.", reply_markup=main_keyboard)


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
        await message.answer(f"У клиента {customer.full_name} нет заказ-нарядов в работе.")
        return
    if len(orders) == 1:
        await state.update_data(order_id=orders[0].id, recognize_image=True)
        await recognize_order_image(message, state, bot, file_id, mime_type)
        return
    await state.set_state(DirectReceipt.choosing_order)
    await message.answer(
        f"У клиента {customer.full_name} несколько автомобилей в работе. Выберите заказ:",
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
    db.add_order_photo(int(data["order_id"]), message.photo[-1].file_id, message.caption)
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
async def confirm_receipt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data["receipt_order_id"])
    items = data.get("receipt_items", [])
    total_cost = int(data["receipt_total"])
    receipt = db.add_receipt(order_id, total_cost, [(str(name), article, quantity, unit_cost, item_total) for name, article, quantity, unit_cost, item_total in items])
    updated = db.get_service_order(order_id)
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
        f"Стоимость работ: {data.labor_revenue:,} ₽\n"
        f"Прибыль с запчастей: {data.parts_margin:,} ₽\n"
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


async def process_text(message: Message, text: str, state: FSMContext) -> None:
    assert message.from_user is not None
    db.log_incoming_message(message.from_user.id, text)
    settings = openrouter_settings()
    if settings is None:
        await message.answer("Добавьте OPENROUTER_API_KEY в .env и перезапустите бота.")
        return
    if not ai_budget_available():
        await message.answer("Достигнут лимит расходов ИИ. Обычные кнопки и поиск продолжают работать.")
        return
    api_key, model, _, _, _ = settings
    try:
        response = await parse_workshop_command(api_key, text, model)
        record_ai_usage("text", response)
        command = response.value

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
            advanced_response = await parse_workshop_command(api_key, text, advanced_model)
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

        await apply_command(message, command, state)
    except OpenRouterError as error:
        await message.answer(f"Не удалось обработать запрос: {error}")


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
        await process_text(message, transcript_response.value, state)
    except OpenRouterError as error:
        await message.answer(f"Не удалось обработать голосовое: {error}")


@router.message(F.text)
async def text_to_crm(message: Message, state: FSMContext) -> None:
    await process_text(message, message.text, state)


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
                await asyncio.to_thread(create_backup, BASE_DIR / "workshop.sqlite3", backup_dir, retention_days)
            except Exception:
                pass
            await asyncio.sleep(24 * 60 * 60)

    async def unfinished_orders_reminder_loop() -> None:
        timezone = ZoneInfo("Europe/Moscow")
        while True:
            now = datetime.now(timezone)
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
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    asyncio.create_task(backup_loop())
    asyncio.create_task(unfinished_orders_reminder_loop())
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
