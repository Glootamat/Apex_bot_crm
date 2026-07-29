"""Telegram bot entry point for a car workshop."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from dotenv import load_dotenv

from database import Database


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
db = Database(BASE_DIR / "workshop.sqlite3")
router = Router()

try:
    ADMIN_ID = int(os.environ["ADMIN_ID"])
except (KeyError, ValueError) as error:
    raise RuntimeError("Set a numeric ADMIN_ID in the .env file.") from error

# This root filter applies to every handler below. Messages from anyone else are ignored.
router.message.filter(F.from_user.id == ADMIN_ID)

ADD_CAR = "➕ Добавить автомобиль"
MY_CARS = "🚗 Мои автомобили"
CANCEL = "Отмена"

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=ADD_CAR)], [KeyboardButton(text=MY_CARS)]],
    resize_keyboard=True,
)
cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True
)


class AddCar(StatesGroup):
    brand = State()
    model = State()
    year = State()
    plate_number = State()


def current_user_id(message: Message) -> int:
    """Register/update a Telegram user and return the local database ID."""
    assert message.from_user is not None
    return db.add_or_update_user(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )


@router.message(CommandStart())
async def start(message: Message) -> None:
    current_user_id(message)
    await message.answer(
        "Здравствуй, Грандмастер Микаил!\n"
        "Вы зарегистрированы в системе автомастерской.\n"
        "Добавьте свой автомобиль, чтобы мы могли сохранить его данные.",
        reply_markup=main_keyboard,
    )


@router.message(F.text == ADD_CAR)
async def add_car_start(message: Message, state: FSMContext) -> None:
    current_user_id(message)
    await state.set_state(AddCar.brand)
    await message.answer("Укажите марку автомобиля (например, Toyota).", reply_markup=cancel_keyboard)


@router.message(F.text == CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Сейчас нечего отменять.", reply_markup=main_keyboard)
        return
    await state.clear()
    await message.answer("Добавление автомобиля отменено.", reply_markup=main_keyboard)


@router.message(AddCar.brand, F.text)
async def car_brand(message: Message, state: FSMContext) -> None:
    await state.update_data(brand=message.text.strip())
    await state.set_state(AddCar.model)
    await message.answer("Теперь укажите модель (например, Camry).")


@router.message(AddCar.model, F.text)
async def car_model(message: Message, state: FSMContext) -> None:
    await state.update_data(model=message.text.strip())
    await state.set_state(AddCar.year)
    await message.answer("Укажите год выпуска или отправьте «-», если он неизвестен.")


@router.message(AddCar.year, F.text)
async def car_year(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    if value != "-":
        try:
            year = int(value)
        except ValueError:
            await message.answer("Год должен быть числом из 4 цифр или «-».")
            return
        if not 1886 <= year <= 2100:
            await message.answer("Укажите корректный год выпуска или «-».")
            return
    else:
        year = None
    await state.update_data(year=year)
    await state.set_state(AddCar.plate_number)
    await message.answer("Введите госномер или отправьте «-», если не хотите указывать.")


@router.message(AddCar.plate_number, F.text)
async def car_plate_number(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plate_number = message.text.strip()
    user_id = current_user_id(message)
    db.add_car(
        user_id=user_id,
        brand=data["brand"],
        model=data["model"],
        year=data["year"],
        plate_number=None if plate_number == "-" else plate_number.upper(),
    )
    await state.clear()
    await message.answer("Автомобиль добавлен!", reply_markup=main_keyboard)


@router.message(F.text == MY_CARS)
async def my_cars(message: Message) -> None:
    assert message.from_user is not None
    cars = db.get_cars_for_telegram_user(message.from_user.id)
    if not cars:
        await message.answer("У вас пока нет добавленных автомобилей.")
        return
    lines = ["Ваши автомобили:"]
    for car in cars:
        details = f"{car.brand} {car.model}"
        if car.year:
            details += f", {car.year} г."
        if car.plate_number:
            details += f", {car.plate_number}"
        lines.append(f"• {details}")
    await message.answer("\n".join(lines))


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
