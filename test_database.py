import tempfile
import unittest
from pathlib import Path

from database import Database


class DatabaseTest(unittest.TestCase):
    def test_user_car_and_service_order_are_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(123, "Иван Иванов", "ivan")
            customer_id = db.add_customer(user_id, "Пётр Петров", "+79990000000")
            car_id = db.add_car(user_id, "Toyota", "Camry", 2020, "А123АА77", customer_id)
            order = db.add_service_order(car_id, "Замена масла", 1500, 3650, 5000)

            self.assertEqual(order.profit, 2850)
            self.assertEqual(order.brand, "Toyota")
            report = db.get_report_for_telegram_user(123)
            self.assertEqual(report.orders, 1)
            self.assertEqual(report.revenue, 6500)
            self.assertEqual(report.profit, 2850)
            self.assertEqual(db.get_customers_for_telegram_user(123)[0].full_name, "Пётр Петров")
            db.add_order_photo(order.id, "telegram-file-id", "После ремонта")
            self.assertEqual(db.count_order_photos(order.id), 1)

    def test_find_or_add_customer_and_car(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(456, "Мастер", None)
            customer_id = db.find_or_add_customer(user_id, "Иван Петров", None)
            self.assertEqual(customer_id, db.find_or_add_customer(user_id, "иван петров", "+79990000000"))
            car_id = db.add_car(user_id, "Kia", "Rio", 2020, "А123АА77", customer_id)
            car = db.find_car(user_id, "kia", "rio", "а123аа77")
            self.assertEqual(car.id, car_id)
