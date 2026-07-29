"""Telegram entry point for the car-workshop CRM."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
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

NEW_ENTRY = "🤖 Новая запись"
ORDERS = "🧾 Заказ-наряды"
COMPLETE_ORDER = "✅ Закрыть заказ"
CUSTOMERS = "👥 Клиенты"
SEARCH = "🔎 Поиск"
AI_USAGE = "💳 ИИ-расходы"
WORK_PHOTO = "📷 Фото работ"
RECEIPT_PHOTO = "🧾 Чек / корзина"
REPORT = "📊 Финансы"
CANCEL = "Отмена"
CONFIRM_DELETE = "Удалить"
CONFIRM_RECEIPT = "Добавить запчасти"

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=NEW_ENTRY)],
        [KeyboardButton(text=SEARCH), KeyboardButton(text=CUSTOMERS)],
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


def current_user_id(message: Message) -> int:
    assert message.from_user is not None
    return db.add_or_update_user(message.from_user.id, message.from_user.full_name, message.from_user.username)


def order_summary(order: ServiceOrder, prefix: str = "✅ Заказ-наряд сохранён") -> str:
    car = f"{order.brand} {order.model}" + (f" ({order.plate_number})" if order.plate_number else "")
    return (
        f"{prefix}\n\nАвтомобиль: {car}\nРаботы: {order.description}\n"
        f"Работы: {order.labor_revenue:,} ₽\nСебестоимость запчастей: {order.parts_cost:,} ₽\n"
        f"Запчасти клиенту: {order.parts_revenue:,} ₽\nПрибыль на запчастях: {order.parts_margin:,} ₽\n"
        f"Общая прибыль: {order.profit:,} ₽\nСтатус: {'Выполнен' if order.status == 'completed' else 'В работе'}"
    ).replace(",", " ")


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
    lines = ["🧾 Последние заказ-наряды:"]
    for order in orders:
        car = f"{order.brand} {order.model}" + (f" · {order.plate_number}" if order.plate_number else "")
        status = "Выполнен" if order.status == "completed" else "В работе"
        lines.append(f"\n#{order.id} · {car}\n{order.description}\nСтатус: {status} · Прибыль: {order.profit:,} ₽".replace(",", " "))
    await message.answer("\n".join(lines), reply_markup=main_keyboard)


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


async def apply_command(message: Message, command: WorkshopCommand, state: FSMContext) -> None:
    if command.intent == "list_orders":
        await show_orders(message)
        return
    if command.intent == "unknown":
        await message.answer("Я могу записать или изменить клиента, автомобиль и заказ-наряд. Напишите или скажите это обычными словами.")
        return

    owner_id = current_user_id(message)

    if command.intent.startswith("delete_"):
        await request_delete(message, command, owner_id, state)
        return

    if command.intent == "set_order_status":
        car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, command.plate_number, command.vin)
        order = db.get_service_order(command.order_id) if command.order_id else (db.get_latest_order_for_car(car.id) if car else None)
        if order is None or command.order_status is None:
            await message.answer("Укажите номер заказ-наряда или автомобиль и статус: «в работе» либо «выполнен».")
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


@router.message(F.text == NEW_ENTRY)
async def new_entry(message: Message) -> None:
    await message.answer("Отправьте текст или голосовое в любой форме. Например: «Приехал Иван на Kia Rio, поменяли масло, работа 1500»." )


@router.message(F.text == SEARCH)
async def search_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Search.query)
    await message.answer("Введите имя, телефон, госномер или VIN.", reply_markup=cancel_keyboard)


@router.message(Search.query, F.text)
async def search_query(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_search_result(message, message.text.strip())


@router.message(F.text == ORDERS)
async def orders_button(message: Message) -> None:
    await show_orders(message)


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
    data = await state.get_data()
    selected = message.text.strip()
    if selected not in data["active_orders"]:
        await message.answer("Выберите номер из списка или нажмите «Отмена».")
        return
    order = db.set_order_status(data["active_orders"][selected], "completed")
    await state.clear()
    await message.answer(order_summary(order, "✅ Заказ-наряд закрыт"), reply_markup=main_keyboard)


@router.message(F.text == CUSTOMERS)
async def customers_button(message: Message) -> None:
    assert message.from_user is not None
    customers = db.get_customer_overviews(message.from_user.id)
    if not customers:
        await message.answer("Клиентов пока нет.")
        return
    lines = ["👥 Клиенты:"]
    for overview in customers[:20]:
        customer = overview.customer
        lines.append(f"\n{customer.full_name}" + (f" · {customer.phone}" if customer.phone else " · телефон не указан"))
        if not overview.cars:
            lines.append("Автомобили не добавлены")
        for item in overview.cars:
            car = item.car
            title = f"{car.brand} {car.model}" + (f" · {car.plate_number}" if car.plate_number else " · без номера")
            lines.append(f"{title}\nЗаказов: {item.orders_total} · В работе: {item.in_progress} · Выполнено: {item.completed}")
    await message.answer("\n".join(lines))


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
    else:
        deleted = db.delete_service_order(owner_id, target_id)
    await state.clear()
    await message.answer("✅ Удалено." if deleted else "Запись уже удалена или не найдена.", reply_markup=main_keyboard)


@router.message(ConfirmDelete.waiting)
async def delete_waiting(message: Message) -> None:
    await message.answer("Нажмите «Удалить» для подтверждения или «Отмена».")


async def add_photo_start(message: Message, state: FSMContext, recognize: bool) -> None:
    assert message.from_user is not None
    orders = db.get_recent_orders_for_telegram_user(message.from_user.id)
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
    await add_photo_start(message, state, recognize=True)


@router.message(AddPhoto.order, F.text)
async def photo_order(message: Message, state: FSMContext) -> None:
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
    db.add_order_photo(order_id, file_id, message.caption)
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
            receipt_items=[(item.name, item.quantity, item.unit_cost, item.total_cost) for item in items],
            receipt_total=total_cost,
        )
        lines = ["🧾 Распознано как закупка запчастей:"]
        for item in items[:12]:
            quantity = f" × {item.quantity:g}" if item.quantity is not None else ""
            amount = f" — {item.total_cost:,} ₽".replace(",", " ") if item.total_cost is not None else ""
            lines.append(f"• {item.name}{quantity}{amount}")
        lines.append(f"\nСебестоимость к добавлению: {total_cost:,} ₽".replace(",", " "))
        lines.append("Добавить позиции и сумму в заказ? Выручка и работы не изменятся.")
        await state.set_state(ConfirmReceipt.waiting)
        await message.answer("\n".join(lines), reply_markup=confirm_receipt_keyboard)
    except OpenRouterError as error:
        await message.answer(f"✅ Фото сохранено, но распознать его не удалось: {error}")


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


@router.message(ConfirmReceipt.waiting, F.text == CONFIRM_RECEIPT)
async def confirm_receipt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data["receipt_order_id"])
    items = data.get("receipt_items", [])
    db.add_part_items(order_id, [(str(name), quantity, unit_cost, total_cost) for name, quantity, unit_cost, total_cost in items])
    total_cost = int(data["receipt_total"])
    updated = db.update_service_order(order_id, None, None, total_cost, None, None, add_amounts=True)
    await state.clear()
    await message.answer(
        f"✅ В заказ #{order_id} добавлены запчасти и себестоимость {total_cost:,} ₽.\n"
        f"Текущая себестоимость запчастей: {updated.parts_cost:,} ₽.".replace(",", " "),
        reply_markup=main_keyboard,
    )


@router.message(ConfirmReceipt.waiting)
async def receipt_waiting(message: Message) -> None:
    await message.answer("Нажмите «Добавить запчасти» или «Отмена».")


@router.message(F.text == REPORT)
async def report(message: Message) -> None:
    assert message.from_user is not None
    data = db.get_report_for_telegram_user(message.from_user.id)
    await message.answer(
        f"📊 Финансы\n\nЗаказ-нарядов: {data.orders}\nРаботы: {data.labor_revenue:,} ₽\n"
        f"Запчасти: {data.parts_revenue:,} ₽\nСебестоимость: {data.parts_cost:,} ₽\nПрибыль на запчастях: {data.parts_margin:,} ₽\n"
        f"Выручка: {data.revenue:,} ₽\nПрибыль: {data.profit:,} ₽".replace(",", " ")
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
        await apply_command(message, response.value, state)
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

    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    asyncio.create_task(backup_loop())
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
