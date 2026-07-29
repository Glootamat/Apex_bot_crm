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

from database import Database, ServiceOrder
from openrouter import OpenRouterError, WorkshopCommand, parse_workshop_command, transcribe_voice


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
CUSTOMERS = "👥 Клиенты"
ADD_PHOTO = "📷 Фото к заказу"
REPORT = "📊 Финансы"
CANCEL = "Отмена"

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=NEW_ENTRY)],
        [KeyboardButton(text=ORDERS), KeyboardButton(text=CUSTOMERS)],
        [KeyboardButton(text=ADD_PHOTO), KeyboardButton(text=REPORT)],
    ],
    resize_keyboard=True,
)
cancel_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True)


class AddPhoto(StatesGroup):
    order = State()
    upload = State()


def current_user_id(message: Message) -> int:
    assert message.from_user is not None
    return db.add_or_update_user(message.from_user.id, message.from_user.full_name, message.from_user.username)


def order_summary(order: ServiceOrder, prefix: str = "✅ Заказ-наряд сохранён") -> str:
    car = f"{order.brand} {order.model}" + (f" ({order.plate_number})" if order.plate_number else "")
    return (
        f"{prefix}\n\nАвтомобиль: {car}\nРаботы: {order.description}\n"
        f"Работы: {order.labor_revenue:,} ₽\nСебестоимость запчастей: {order.parts_cost:,} ₽\n"
        f"Запчасти клиенту: {order.parts_revenue:,} ₽\nПрибыль: {order.profit:,} ₽"
    ).replace(",", " ")


def openrouter_settings() -> tuple[str, str, str] | None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_openrouter_api_key":
        return None
    return api_key, os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"), os.getenv("OPENROUTER_TRANSCRIBE_MODEL", "openai/gpt-4o-mini-transcribe")


async def show_orders(message: Message) -> None:
    assert message.from_user is not None
    orders = db.get_recent_orders_for_telegram_user(message.from_user.id, limit=15)
    if not orders:
        await message.answer("Заказ-нарядов пока нет.")
        return
    lines = ["🧾 Последние заказ-наряды:"]
    for order in orders:
        car = f"{order.brand} {order.model}" + (f" · {order.plate_number}" if order.plate_number else "")
        lines.append(f"\n#{order.id} · {car}\n{order.description}\nПрибыль: {order.profit:,} ₽".replace(",", " "))
    await message.answer("\n".join(lines))


async def apply_command(message: Message, command: WorkshopCommand) -> None:
    if command.intent == "list_orders":
        await show_orders(message)
        return
    if command.intent == "unknown":
        await message.answer("Я могу записать или изменить клиента, автомобиль и заказ-наряд. Напишите или скажите это обычными словами.")
        return

    owner_id = current_user_id(message)
    customer = db.find_customer(owner_id, command.customer_name, command.customer_phone)
    if customer is None and command.customer_name:
        customer_id = db.add_customer(owner_id, command.customer_name, command.customer_phone)
    elif customer is not None:
        customer_id = customer.id
        db.update_customer(customer_id, command.customer_name, command.customer_phone)
    else:
        customer_id = None

    plate = command.plate_number.upper() if command.plate_number else None
    car = db.find_car_by_details(owner_id, command.car_brand, command.car_model, plate)
    if car is None and command.car_brand and command.car_model:
        car_id = db.add_car(owner_id, command.car_brand, command.car_model, command.car_year, plate, customer_id)
    elif car is not None:
        car_id = car.id
        db.update_car(car_id, customer_id, command.car_brand, command.car_model, command.car_year, plate)
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
        order = db.add_service_order(car_id, command.description, command.labor_revenue or 0, command.parts_cost or 0, command.parts_revenue or 0)
        await message.answer(order_summary(order, "🤖 Запись создана автоматически"), reply_markup=main_keyboard)
        return

    if command.intent == "update_order":
        order = db.get_latest_order_for_car(car_id)
        if order is None:
            await message.answer("У этого автомобиля пока нет заказ-нарядов. Опишите выполненные работы, и я создам первый.")
            return
        updated = db.update_service_order(order.id, command.description, command.labor_revenue, command.parts_cost, command.parts_revenue, add_amounts=True)
        await message.answer(order_summary(updated, "✅ Заказ-наряд дополнен"), reply_markup=main_keyboard)


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


@router.message(F.text == ORDERS)
async def orders_button(message: Message) -> None:
    await show_orders(message)


@router.message(F.text == CUSTOMERS)
async def customers_button(message: Message) -> None:
    assert message.from_user is not None
    customers = db.get_customers_for_telegram_user(message.from_user.id)
    if not customers:
        await message.answer("Клиентов пока нет.")
        return
    await message.answer("👥 Клиенты:\n" + "\n".join(f"{item.full_name}" + (f" · {item.phone}" if item.phone else "") for item in customers[:30]))


@router.message(F.text == CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Готово.", reply_markup=main_keyboard)


@router.message(F.text == ADD_PHOTO)
async def add_photo_start(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    orders = db.get_recent_orders_for_telegram_user(message.from_user.id)
    if not orders:
        await message.answer("Сначала создайте заказ-наряд.")
        return
    await state.update_data(orders={str(order.id): order.id for order in orders})
    await state.set_state(AddPhoto.order)
    choices = "\n".join(f"{order.id}. {order.brand} {order.model}: {order.description}" for order in orders)
    await message.answer(f"Выберите номер заказ-наряда:\n{choices}", reply_markup=cancel_keyboard)


@router.message(AddPhoto.order, F.text)
async def photo_order(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected = message.text.strip()
    if selected not in data["orders"]:
        await message.answer("Выберите номер из списка.")
        return
    await state.update_data(order_id=data["orders"][selected])
    await state.set_state(AddPhoto.upload)
    await message.answer("Отправляйте фото работ или чеков. Нажмите «Отмена», когда закончите.")


@router.message(AddPhoto.upload, F.photo)
async def save_order_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    db.add_order_photo(data["order_id"], message.photo[-1].file_id, message.caption)
    await message.answer(f"✅ Фото сохранено. Всего: {db.count_order_photos(data['order_id'])}.")


@router.message(F.text == REPORT)
async def report(message: Message) -> None:
    assert message.from_user is not None
    data = db.get_report_for_telegram_user(message.from_user.id)
    await message.answer(
        f"📊 Финансы\n\nЗаказ-нарядов: {data.orders}\nРаботы: {data.labor_revenue:,} ₽\n"
        f"Запчасти: {data.parts_revenue:,} ₽\nСебестоимость: {data.parts_cost:,} ₽\n"
        f"Выручка: {data.revenue:,} ₽\nПрибыль: {data.profit:,} ₽".replace(",", " ")
    )


async def process_text(message: Message, text: str) -> None:
    settings = openrouter_settings()
    if settings is None:
        await message.answer("Добавьте OPENROUTER_API_KEY в .env и перезапустите бота.")
        return
    api_key, model, _ = settings
    try:
        command = await parse_workshop_command(api_key, text, model)
        await apply_command(message, command)
    except OpenRouterError as error:
        await message.answer(f"Не удалось обработать запрос: {error}")


@router.message(F.voice)
async def voice_to_crm(message: Message, bot: Bot) -> None:
    settings = openrouter_settings()
    if settings is None:
        await message.answer("Добавьте OPENROUTER_API_KEY в .env и перезапустите бота.")
        return
    api_key, _, transcription_model = settings
    await message.answer("🎙️ Расшифровываю голосовое…")
    try:
        audio = await bot.download(message.voice)
        if audio is None:
            raise OpenRouterError("Не удалось скачать голосовое из Telegram.")
        transcript = await transcribe_voice(api_key, audio.getvalue(), transcription_model)
        await message.answer(f"Распознано: {transcript}")
        await process_text(message, transcript)
    except OpenRouterError as error:
        await message.answer(f"Не удалось обработать голосовое: {error}")


@router.message(F.text)
async def text_to_crm(message: Message) -> None:
    await message.answer("🤖 Обрабатываю…")
    await process_text(message, message.text)


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token or token == "your_telegram_bot_token":
        raise RuntimeError("Set BOT_TOKEN in the .env file before starting the bot.")
    db.initialize()
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
