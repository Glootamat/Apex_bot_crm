import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bot
from database import Database


class FakeMessage:
    def __init__(self, sender_id: int) -> None:
        self.from_user = SimpleNamespace(id=sender_id)
        self.answers: list[str] = []
        self.markups: list[object | None] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)
        self.markups.append(kwargs.get("reply_markup"))


class FakeState:
    def __init__(self) -> None:
        self.value: object | None = None

    async def set_state(self, value: object) -> None:
        self.value = value


class BotHandlerTest(unittest.TestCase):
    def test_technical_phone_name_is_displayed_as_not_specified(self) -> None:
        self.assertEqual(
            bot.customer_name_label("Клиент +79197507170"),
            "Имя не указано",
        )
        self.assertEqual(bot.customer_name_label(None), "Имя не указано")
        self.assertEqual(bot.customer_name_label("Александр"), "Александр")

    def test_search_uses_force_reply_without_persistent_cancel_keyboard(self) -> None:
        message = FakeMessage(sender_id=7000)
        state = FakeState()

        asyncio.run(bot.search_start(message, state))

        self.assertEqual(state.value, bot.Search.query)
        self.assertIsInstance(message.markups[0], bot.ForceReply)

    def test_completed_order_callback_uses_clicking_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(7001, "Owner", None)
            car_id = db.add_car(user_id, "Nissan", "Teana")
            order = db.add_service_order(car_id, "Service", 2500, 0, 0)
            db.set_order_status(order.id, "ready", user_id)
            bot_authored_message = FakeMessage(sender_id=999999)

            with patch.object(bot, "db", db):
                asyncio.run(
                    bot.show_orders(
                        bot_authored_message, "closed", completed_days=1,
                        telegram_id=7001,
                    )
                )

            self.assertTrue(
                any("Выполненные заказ-наряды за сегодня" in text
                    for text in bot_authored_message.answers)
            )
            self.assertTrue(
                any(f"#{order.id}" in text for text in bot_authored_message.answers)
            )

    def test_exact_phone_search_renders_one_customer_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(7002, "Owner", None)
            customer_id = db.add_customer(
                user_id, "Phone Client", "+7 919 750-71-70"
            )
            car_id = db.add_car(
                user_id, "Lada", "Priora", customer_id=customer_id
            )
            db.add_service_order(car_id, "Service", 2000, 0, 0)
            message = FakeMessage(sender_id=7002)

            with patch.object(bot, "db", db):
                asyncio.run(bot.show_search_result(message, "+79197507170"))

            self.assertEqual(len(message.answers), 1)
            self.assertIn("Phone Client", message.answers[0])
            self.assertIn("Lada Priora", message.answers[0])
            self.assertNotIn("Заказ #", message.answers[0])

    def test_phone_search_hides_technical_customer_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(7003, "Owner", None)
            db.add_customer(user_id, "Клиент +79197507170", "+79197507170")
            message = FakeMessage(sender_id=7003)

            with patch.object(bot, "db", db):
                asyncio.run(bot.show_search_result(message, "+79197507170"))

            self.assertEqual(len(message.answers), 1)
            self.assertIn("Имя не указано", message.answers[0])
            self.assertNotIn("Клиент +79197507170", message.answers[0])


if __name__ == "__main__":
    unittest.main()
