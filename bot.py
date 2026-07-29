"""Telegram entry point for the local car-workshop CRM."""

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

from database import Car, Database, ServiceOrder


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
db = Database(BASE_DIR / "workshop.sqlite3")
router = Router()

try:
    ADMIN_ID = int(os.environ["ADMIN_ID"])
except (KeyError, ValueError) as error:
    raise RuntimeError("Set a numeric ADMIN_ID in the .env file.") from error

router.message.filter(F.from_user.id == ADMIN_ID)

ADD_CAR = "➕ Добавить автомобиль"
ADD_CUSTOMER = "👤 Добавить клиента"
MY_CUSTOMERS = "👥 Клиенты"
MY_CARS = "🚗 Мои автомобили"
ADD_ORDER = "🧾 Добавить заказ-наряд"
ADD_PHOTO = "📷 Фото к заказу"
REPORT = "📊 Общая прибыль"
CANCEL = "Отмена"
SKIP = "-"

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=ADD_CUSTOMER), KeyboardButton(text=MY_CUSTOMERS)],
        [KeyboardButton(text=ADD_CAR), KeyboardButton(text=MY_CARS)],
        [KeyboardButton(text=ADD_ORDER), KeyboardButton(text=ADD_PHOTO)],
        [KeyboardButton(text=REPORT)],
    ],
    resize_keyboard=True,
)
cancel_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True)


class AddCar(StatesGroup):
    customer = State()
    brand = State()
    model = State()
    year = State()
    plate_number = State()


class AddCustomer(StatesGroup):
    full_name = State()
    phone = State()


class AddOrder(StatesGroup):
    car = State()
    description = State()
    labor_revenue = State()
    parts_cost = State()
    parts_revenue = State()


class AddPhoto(StatesGroup):
    order = State()
    upload = State()


def current_user_id(message: Message) -> int:
    assert message.from_user is not None
    return db.add_or_update_user(message.from_user.id, message.from_user.full_name, message.from_user.username)


def parse_amount(value: str) -> int | None:
    value = value.strip().replace(" ", "").replace("₽", "").replace("руб.", "").replace("руб", "")
    if not value.isdigit():
        return None
    return int(value)


def car_title(car: Car) -> str:
    title = f"{car.brand} {car.model}"
    if car.year:
        title += f", {car.year} г."
    if car.plate_number:
        title += f", {car.plate_number}"
    return title


def order_summary(order: ServiceOrder) -> str:
    car = f"{order.brand} {order.model}" + (f" ({order.plate_number})" if order.plate_number else "")
    return (
        "✅ Заказ-наряд сохранён\n\n"
        f"Автомобиль: {car}\n"
        f"Работы: {order.description}\n"
        f"Выручка за работы: {order.labor_revenue:,} ₽\n"
        f"Себестоимость запчастей: {order.parts_cost:,} ₽\n"
        f"Продажа запчастей: {order.parts_revenue:,} ₽\n"
        f"Прибыль: {order.profit:,} ₽"
    ).replace(",", " ")


@router.message(CommandStart())
async def start(message: Message) -> None:
    current_user_id(message)
    await message.answer(
        "Добро пожаловать в CRM автосервиса.\n"
        "Сначала добавьте автомобиль, затем создавайте заказ-наряды и смотрите прибыль.",
        reply_markup=main_keyboard,
    )


@router.message(F.text == CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Сейчас нечего отменять.", reply_markup=main_keyboard)
        return
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_keyboard)


@router.message(F.text == ADD_CAR)
async def add_car_start(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    customers = db.get_customers_for_telegram_user(message.from_user.id)
    if not customers:
        await message.answer("Сначала добавьте клиента.", reply_markup=main_keyboard)
        return
    await state.update_data(customers={str(customer.id): customer.id for customer in customers})
    await state.set_state(AddCar.customer)
    choices = "\n".join(f"{customer.id}. {customer.full_name}" + (f", {customer.phone}" if customer.phone else "") for customer in customers)
    await message.answer(f"Выберите клиента по номеру:\n{choices}", reply_markup=cancel_keyboard)


@router.message(AddCar.customer, F.text)
async def car_customer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected = message.text.strip()
    if selected not in data["customers"]:
        await message.answer("Выберите номер клиента из списка.")
        return
    await state.update_data(customer_id=data["customers"][selected])
    await state.set_state(AddCar.brand)
    await message.answer("Укажите марку автомобиля, например Toyota.")


@router.message(F.text == ADD_CUSTOMER)
async def add_customer_start(message: Message, state: FSMContext) -> None:
    current_user_id(message)
    await state.set_state(AddCustomer.full_name)
    await message.answer("Введите имя и фамилию клиента.", reply_markup=cancel_keyboard)


@router.message(AddCustomer.full_name, F.text)
async def customer_name(message: Message, state: FSMContext) -> None:
    await state.update_data(full_name=message.text.strip())
    await state.set_state(AddCustomer.phone)
    await message.answer("Введите телефон клиента или отправьте «-».")


@router.message(AddCustomer.phone, F.text)
async def customer_phone(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    phone = message.text.strip()
    db.add_customer(current_user_id(message), data["full_name"], None if phone == SKIP else phone)
    await state.clear()
    await message.answer("✅ Карточка клиента создана.", reply_markup=main_keyboard)


@router.message(F.text == MY_CUSTOMERS)
async def my_customers(message: Message) -> None:
    assert message.from_user is not None
    customers = db.get_customers_for_telegram_user(message.from_user.id)
    if not customers:
        await message.answer("Клиентов пока нет.")
        return
    lines = ["Клиенты:"]
    for customer in customers:
        lines.append(f"{customer.id}. {customer.full_name}" + (f" — {customer.phone}" if customer.phone else ""))
    await message.answer("\n".join(lines))


@router.message(AddCar.brand, F.text)
async def car_brand(message: Message, state: FSMContext) -> None:
    await state.update_data(brand=message.text.strip())
    await state.set_state(AddCar.model)
    await message.answer("Теперь укажите модель, например Camry.")


@router.message(AddCar.model, F.text)
async def car_model(message: Message, state: FSMContext) -> None:
    await state.update_data(model=message.text.strip())
    await state.set_state(AddCar.year)
    await message.answer("Укажите год выпуска или отправьте «-», если он неизвестен.")


@router.message(AddCar.year, F.text)
async def car_year(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    if value == SKIP:
        year = None
    elif value.isdigit() and 1886 <= int(value) <= 2100:
        year = int(value)
    else:
        await message.answer("Введите год из 4 цифр или «-».")
        return
    await state.update_data(year=year)
    await state.set_state(AddCar.plate_number)
    await message.answer("Введите госномер или отправьте «-».")


@router.message(AddCar.plate_number, F.text)
async def car_plate_number(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    plate = message.text.strip()
    db.add_car(current_user_id(message), data["brand"], data["model"], data["year"], None if plate == SKIP else plate.upper(), data["customer_id"])
    await state.clear()
    await message.answer("✅ Автомобиль добавлен.", reply_markup=main_keyboard)


@router.message(F.text == MY_CARS)
async def my_cars(message: Message) -> None:
    assert message.from_user is not None
    cars = db.get_cars_for_telegram_user(message.from_user.id)
    if not cars:
        await message.answer("Автомобилей пока нет. Нажмите «Добавить автомобиль».")
        return
    await message.answer("Ваши автомобили:\n" + "\n".join(f"{car.id}. {car_title(car)}" for car in cars))


@router.message(F.text == ADD_ORDER)
async def add_order_start(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    cars = db.get_cars_for_telegram_user(message.from_user.id)
    if not cars:
        await message.answer("Сначала добавьте автомобиль.", reply_markup=main_keyboard)
        return
    await state.update_data(cars={str(car.id): car.id for car in cars})
    await state.set_state(AddOrder.car)
    choices = "\n".join(f"{car.id}. {car_title(car)}" for car in cars)
    await message.answer(f"Для какого автомобиля создаём заказ-наряд? Отправьте его номер:\n{choices}", reply_markup=cancel_keyboard)


@router.message(AddOrder.car, F.text)
async def order_car(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected = message.text.strip()
    if selected not in data["cars"]:
        await message.answer("Выберите номер автомобиля из списка.")
        return
    await state.update_data(car_id=data["cars"][selected])
    await state.set_state(AddOrder.description)
    await message.answer("Опишите выполненные работы, например: Замена масла и фильтра.")


@router.message(AddOrder.description, F.text)
async def order_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip())
    await state.set_state(AddOrder.labor_revenue)
    await message.answer("Сколько получил за работы? Введите сумму в рублях, например 2500.")


async def collect_amount(message: Message, state: FSMContext, field: str, next_state: State, next_question: str) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer("Введите целую сумму в рублях, например 2500.")
        return
    await state.update_data(**{field: amount})
    await state.set_state(next_state)
    await message.answer(next_question)


@router.message(AddOrder.labor_revenue, F.text)
async def order_labor_revenue(message: Message, state: FSMContext) -> None:
    await collect_amount(message, state, "labor_revenue", AddOrder.parts_cost, "Сколько запчасти обошлись сервису? Если их не было, отправьте 0.")


@router.message(AddOrder.parts_cost, F.text)
async def order_parts_cost(message: Message, state: FSMContext) -> None:
    await collect_amount(message, state, "parts_cost", AddOrder.parts_revenue, "За какую сумму продали запчасти клиенту? Если их не было, отправьте 0.")


@router.message(AddOrder.parts_revenue, F.text)
async def order_parts_revenue(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer("Введите целую сумму в рублях, например 5000.")
        return
    data = await state.get_data()
    order = db.add_service_order(data["car_id"], data["description"], data["labor_revenue"], data["parts_cost"], amount)
    await state.clear()
    await message.answer(order_summary(order), reply_markup=main_keyboard)


@router.message(F.text == ADD_PHOTO)
async def add_photo_start(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    orders = db.get_recent_orders_for_telegram_user(message.from_user.id)
    if not orders:
        await message.answer("Сначала создайте хотя бы один заказ-наряд.", reply_markup=main_keyboard)
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
        await message.answer("Выберите номер заказ-наряда из списка.")
        return
    await state.update_data(order_id=data["orders"][selected])
    await state.set_state(AddPhoto.upload)
    await message.answer("Отправляйте фотографии работ или чеков. Когда закончите, нажмите «Отмена».")


@router.message(AddPhoto.upload, F.photo)
async def save_order_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photo = message.photo[-1]
    db.add_order_photo(data["order_id"], photo.file_id, message.caption)
    count = db.count_order_photos(data["order_id"])
    await message.answer(f"✅ Фото сохранено. Всего у этого заказ-наряда: {count}.")


@router.message(F.text == REPORT)
async def report(message: Message) -> None:
    assert message.from_user is not None
    data = db.get_report_for_telegram_user(message.from_user.id)
    await message.answer(
        "📊 Общая статистика\n\n"
        f"Заказ-нарядов: {data.orders}\n"
        f"Выручка за работы: {data.labor_revenue:,} ₽\n"
        f"Выручка за запчасти: {data.parts_revenue:,} ₽\n"
        f"Себестоимость запчастей: {data.parts_cost:,} ₽\n"
        f"Итого выручка: {data.revenue:,} ₽\n"
        f"Прибыль: {data.profit:,} ₽"
        .replace(",", " ")
    )


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
