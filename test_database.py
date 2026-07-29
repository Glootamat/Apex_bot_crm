import tempfile
import unittest
from pathlib import Path

from backup import create_backup
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

    def test_existing_order_can_be_completed_later(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(789, "Мастер", None)
            car_id = db.add_car(user_id, "Kia", "Rio")
            original = db.add_service_order(car_id, "Замена масла", 1500, 0, 0)
            updated = db.update_service_order(original.id, "Фильтр", None, 400, 650, None, add_amounts=True)

            self.assertEqual(updated.description, "Замена масла; Фильтр")
            self.assertEqual(updated.parts_cost, 400)
            self.assertEqual(updated.parts_revenue, 650)
            self.assertEqual(updated.profit, 1750)

    def test_vin_mileage_and_direct_parts_profit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(999, "Мастер", None)
            car_id = db.add_car(user_id, "Toyota", "Camry", vin="XTA123", mileage=125000)
            car = db.find_car_by_details(user_id, None, None, None, "xta123")
            self.assertEqual(car.id, car_id)
            db.update_car(car_id, None, None, None, None, "А123АА77", None, 126000)
            order = db.add_service_order(car_id, "Масло", 0, 0, 0, parts_profit=500)

            self.assertEqual(order.parts_margin, 500)
            self.assertEqual(order.profit, 500)

    def test_customer_overview_status_and_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(1001, "Мастер", None)
            customer_id = db.add_customer(user_id, "Иван Петров", "+79990000000")
            car_id = db.add_car(user_id, "Kia", "Rio", plate_number="А123АА77", customer_id=customer_id)
            order = db.add_service_order(car_id, "Замена масла", 1500, 0, 0)
            db.set_order_status(order.id, "completed")

            overview = db.get_customer_overviews(1001)[0]
            self.assertEqual(overview.customer.phone, "+79990000000")
            self.assertEqual(overview.cars[0].car.plate_number, "А123АА77")
            self.assertEqual(overview.cars[0].orders_total, 1)
            self.assertEqual(overview.cars[0].completed, 1)
            self.assertTrue(db.delete_customer(user_id, customer_id))
            self.assertEqual(db.get_recent_orders_for_telegram_user(1001), [])

    def test_new_plate_falls_back_to_existing_brand_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(1002, "Мастер", None)
            car_id = db.add_car(user_id, "Kia", "Rio")
            car = db.find_car_by_details(user_id, "Kia", "Rio", "А123АА77", None)
            self.assertEqual(car.id, car_id)
            db.update_car(car_id, None, None, None, None, "А123АА77", None, None)
            self.assertEqual(db.find_car_by_details(user_id, None, None, "А123АА77", None).id, car_id)

    def test_search_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            db = Database(directory_path / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(2001, "Мастер", None)
            customer_id = db.add_customer(user_id, "Иван Петров", "+79990000000")
            db.add_car(user_id, "Kia", "Rio", plate_number="А123АА77", customer_id=customer_id, vin="XTA123")

            result = db.search(2001, "xta123")
            self.assertEqual(len(result["cars"]), 1)
            self.assertEqual(len(db.search(2001, "+7999")["customers"]), 1)
            backup = create_backup(directory_path / "test.sqlite3", directory_path / "backups")
            self.assertTrue(backup.exists())

    def test_ai_usage_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.log_ai_usage("text", "test-model", 100, 20, 0.0015)
            cost, requests = db.get_ai_usage("datetime('now', 'start of day')")
            self.assertEqual(requests, 1)
            self.assertAlmostEqual(cost, 0.0015)
