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
            photos = db.get_order_photos(order.id)
            self.assertEqual(photos[0]["telegram_file_id"], "telegram-file-id")
            self.assertEqual(db.search(123, "после ремонта")["orders"][0]["id"], order.id)
            db.add_order_photo(order.id, "receipt-file-id", None, photo_type="receipt")
            self.assertEqual(db.count_order_photos(order.id), 1)
            self.assertEqual(len(db.get_order_photos(order.id)), 1)

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

    def test_daily_reminder_is_claimed_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            self.assertTrue(db.claim_daily_reminder("2026-07-30"))
            self.assertFalse(db.claim_daily_reminder("2026-07-30"))
            self.assertTrue(db.claim_daily_reminder("2026-07-31"))

    def test_upcoming_appointment_keeps_client_car_and_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4001, "Master", None)
            customer_id = db.add_customer(user_id, "Sergey", "+79990000000")
            car_id = db.add_car(
                user_id, "Lada", "Granta", plate_number="A123AA", customer_id=customer_id
            )
            appointment_id = db.add_appointment(
                car_id, "Brake pads", "2026-07-31T11:00:00+03:00"
            )
            appointment = db.get_upcoming_appointments_for_telegram_user(4001)[0]
            self.assertEqual(appointment.id, appointment_id)
            self.assertEqual(appointment.customer_name, "Sergey")
            self.assertEqual(appointment.brand, "Lada")

    def test_completed_order_is_hidden_from_appointments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4002, "Master", None)
            car_id = db.add_car(user_id, "Lada", "Vesta")
            order = db.add_service_order(car_id, "Service", 1500, 0, 0)
            db.add_appointment(
                car_id,
                "Service",
                "2026-08-01T11:00:00+03:00",
                service_order_id=order.id,
            )
            db.set_order_status(order.id, "completed")
            self.assertEqual(db.get_upcoming_appointments_for_telegram_user(4002), [])

    def test_receipt_parts_are_saved_and_added_to_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(3001, "Master", None)
            car_id = db.add_car(user_id, "Kia", "Rio")
            order = db.add_service_order(car_id, "Oil service", 0, 100, 0)
            db.add_part_items(order.id, [("Oil filter", 1, 450, 450), ("Engine oil", 4, 800, 3200)])
            updated = db.update_service_order(order.id, None, None, 3650, None, None, add_amounts=True)

            self.assertEqual(len(db.get_part_items(order.id)), 2)
            self.assertEqual(updated.parts_cost, 3750)

    def test_receipt_parts_can_be_marked_up_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(3002, "Master", None)
            car_id = db.add_car(user_id, "Kia", "Rio")
            order = db.add_service_order(car_id, "Oil service", 0, 3650, 0)
            db.add_part_items(order.id, [("Oil filter", 1, 450, 450), ("Engine oil", 4, 800, 3200)])

            count, purchase_cost, profit = db.apply_markup_to_unmarked_parts(order.id, 40)
            self.assertEqual((count, purchase_cost, profit), (2, 3650, 1460))
            self.assertEqual(db.apply_markup_to_unmarked_parts(order.id, 40), (0, 0, 0))
            updated = db.update_service_order(order.id, None, None, None, purchase_cost + profit, None, add_amounts=True)
            self.assertEqual(updated.parts_margin, 1460)

    def test_receipt_total_can_be_edited_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(3003, "Master", None)
            car_id = db.add_car(user_id, "Kia", "Rio")
            order = db.add_service_order(car_id, "Oil service", 0, 100, 0)
            receipt = db.add_receipt(order.id, 450, [("Oil filter", "OF-1", 1, 450, 450)])

            self.assertEqual(db.get_service_order(order.id).parts_cost, 550)
            self.assertTrue(db.update_receipt_total(user_id, receipt.id, 500))
            self.assertEqual(db.get_service_order(order.id).parts_cost, 600)
            self.assertTrue(db.delete_receipt(user_id, receipt.id))
            self.assertEqual(db.get_service_order(order.id).parts_cost, 100)
            self.assertEqual(db.get_part_items(order.id), [])

    def test_receipt_purchase_does_not_reduce_labor_before_markup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(3004, "Master", None)
            car_id = db.add_car(user_id, "Audi", "Q3")
            order = db.add_service_order(car_id, "Brake pads", 1500, 0, 0)
            receipt = db.add_receipt(order.id, 1533, [("Pads", "BD3619", 1, 1310, 1310), ("Wiper", "AWBK600", 1, 223, 223)])

            self.assertEqual(db.get_service_order(order.id).profit, 1500)
            result = db.apply_markup_to_receipt(user_id, receipt.id, 40)
            self.assertEqual(result, (order.id, 2, 1533, 613))
            updated = db.get_service_order(order.id)
            self.assertEqual(updated.parts_margin, 613)
            self.assertEqual(updated.profit, 2113)
            self.assertEqual(db.apply_markup_to_receipt(user_id, receipt.id, 40), (order.id, 0, 0, 0))
            overview = db.get_recent_receipts_for_telegram_user(3004)[0]
            self.assertTrue(overview.markup_applied)
            self.assertEqual(overview.receipt.total_cost, 1533)
            self.assertEqual(len(overview.items), 2)
            self.assertEqual(overview.items[0].article, "BD3619")
