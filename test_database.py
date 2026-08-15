import tempfile
import unittest
from pathlib import Path

from backup import create_backup
from database import Database


class DatabaseTest(unittest.TestCase):
    def test_platform_can_manage_demo_and_organization_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            organization_id = db.create_organization(
                "Тестовый сервис", "Ставрополь", "Иван Владелец",
                "demo-owner", "password-hash", demo_days=7,
            )
            service = next(item for item in db.list_organizations() if item["id"] == organization_id)
            self.assertEqual(service["status"], "demo")
            self.assertEqual(service["demo_days_left"], 7)
            self.assertIsNotNone(db.get_auth_account("demo-owner"))

            self.assertTrue(db.update_organization_access(organization_id, "block"))
            self.assertEqual(db.list_organizations()[0]["status"], "blocked")
            self.assertIsNone(db.get_auth_account("demo-owner"))

            self.assertTrue(db.update_organization_access(organization_id, "activate"))
            self.assertEqual(db.list_organizations()[0]["status"], "active")
            self.assertIsNotNone(db.get_auth_account("demo-owner"))

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
            duplicate_id = db.add_order_photo(order.id, "telegram-file-id", "Повтор")
            self.assertEqual(duplicate_id, db.get_order_photos(order.id)[0]["id"])
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

    def test_same_model_cars_are_resolved_inside_the_customer_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(458, "Мастер", None)
            neighbor_id = db.add_customer(user_id, "Сосед", None)
            phone_customer_id = db.add_customer(
                user_id, "Клиент +79197507170", "+79197507170"
            )
            neighbor_car_id = db.add_car(
                user_id, "Lada", "Priora", customer_id=neighbor_id
            )
            phone_car_id = db.add_car(
                user_id, "Lada", "Priora", customer_id=phone_customer_id
            )

            self.assertIsNone(
                db.find_car_by_details(user_id, "Lada", "Priora", None, None)
            )
            self.assertEqual(
                db.find_customer_car_by_details(
                    user_id, neighbor_id, "Lada", "Priora", None, None
                ).id,
                neighbor_car_id,
            )
            self.assertEqual(
                db.find_customer_car_by_details(
                    user_id, phone_customer_id, "Lada", "Priora", None, None
                ).id,
                phone_car_id,
            )

    def test_phone_only_customer_can_be_named_after_first_visit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(457, "Мастер", None)

            provisional = db.find_or_add_customer_by_phone(user_id, "8 (988) 601-26-50")
            self.assertEqual(provisional.full_name, "Клиент +79886012650")

            enriched = db.find_or_add_customer_by_phone(
                user_id, "+7 988 601 26 50", "Алексей"
            )
            self.assertEqual(enriched.id, provisional.id)
            self.assertEqual(enriched.full_name, "Алексей")
            self.assertEqual(len(db.get_customers_for_telegram_user(457)), 1)

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

    def test_real_work_replaces_placeholder_instead_of_appending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(790, "Мастер", None)
            car_id = db.add_car(user_id, "Lada", "Kalina")
            order = db.add_service_order(car_id, "Работы уточняются", 0, 0, 0)

            updated = db.update_service_order(
                order.id, "Замена передних стоек", None, None, None, None, add_amounts=True
            )
            repeated = db.update_service_order(
                order.id, "Замена передних стоек", None, None, None, None, add_amounts=True
            )

            self.assertEqual(updated.description, "Замена передних стоек")
            self.assertEqual(repeated.description, "Замена передних стоек")

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
            self.assertEqual(order.mileage_at_visit, 126000)
            db.update_car(car_id, None, None, None, None, None, None, 130000)
            self.assertEqual(db.get_service_order(order.id).mileage_at_visit, 126000)
            later = db.add_service_order(car_id, "Замена масла", 1000, 0, 0, mileage_at_visit=140000)
            self.assertEqual(later.mileage_at_visit, 140000)
            self.assertEqual(db.find_car_by_details(user_id, None, None, None, "xta123").mileage, 140000)
            db.update_order_crm_fields(later.id, user_id, mileage_at_visit=141000)
            self.assertEqual(db.get_service_order(later.id).mileage_at_visit, 141000)
            self.assertEqual(db.get_service_order(order.id).mileage_at_visit, 126000)

    def test_completing_order_backfills_missing_visit_mileage_from_car(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(998, "Мастер", None)
            car_id = db.add_car(user_id, "Hyundai", "Solaris")
            order = db.add_service_order(car_id, "Замена масла", 0, 0, 0)
            self.assertIsNone(order.mileage_at_visit)

            db.update_car(car_id, None, None, None, None, None, None, 24500)
            completed = db.set_order_status(order.id, "ready", user_id)

            self.assertEqual(completed.mileage_at_visit, 24500)

    def test_deleting_order_restores_previous_vehicle_mileage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(997, "Мастер", None)
            car_id = db.add_car(user_id, "Hyundai", "Solaris", mileage=64500)
            previous = db.add_service_order(car_id, "Замена свечей", 0, 0, 0)
            temporary = db.add_service_order(car_id, "Тестовая замена масла", 0, 0, 0, mileage_at_visit=66000)

            self.assertEqual(db.find_car_by_details(user_id, "Hyundai", "Solaris", None, None).mileage, 66000)
            self.assertTrue(db.delete_service_order(user_id, temporary.id))

            self.assertEqual(db.get_service_order(previous.id).mileage_at_visit, 64500)
            self.assertEqual(db.find_car_by_details(user_id, "Hyundai", "Solaris", None, None).mileage, 64500)

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

    def test_unassigned_car_remains_visible_in_customer_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(1005, "Мастер", None)
            car_id = db.add_car(user_id, "Лада", "Калина", plate_number="В965СС")
            order = db.add_service_order(
                car_id, "Замена передних амортизаторов", 4000, 0, 0
            )
            db.set_order_status(order.id, "ready")

            cars = db.get_unassigned_cars_for_telegram_user(1005)

            self.assertEqual(len(cars), 1)
            self.assertEqual(cars[0]["model"], "Калина")
            self.assertEqual(cars[0]["latest_order_id"], order.id)
            self.assertEqual(cars[0]["completed"], 1)

    def test_manual_chat_cleanup_can_include_important_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(1006, "Мастер", None)
            car_id = db.add_car(user_id, "Nissan", "Teana")
            order = db.add_service_order(car_id, "Диагностика ходовой", 500, 0, 0)
            db.remember_chat_message(-1001, 10, important=False)
            db.remember_chat_message(-1001, 11, important=True)
            db.remember_chat_message(-1001, 12, important=False)
            db.remember_service_message_card(
                -1001, 12, service_order_id=order.id
            )
            appointment_id = db.add_appointment(
                car_id, "Повторная диагностика", "2026-08-10T10:00:00+03:00"
            )
            db.remember_chat_message(-1001, 13, important=False)
            db.remember_service_message_card(
                -1001, 13, appointment_id=appointment_id
            )

            self.assertEqual(db.get_disposable_chat_messages(-1001), [10])
            self.assertEqual(db.get_chat_messages(-1001, include_important=True), [10, 11])
            self.assertEqual(
                db.get_service_message_cards_for_order(order.id),
                [{"chat_id": -1001, "message_id": 12}],
            )
            self.assertEqual(
                db.get_chat_messages_for_cleanup(
                    -1001, today_only=True,
                    keep_card_statuses={"in_progress", "scheduled"},
                ),
                [10, 11],
            )
            self.assertEqual(
                db.get_chat_messages_for_cleanup(
                    -1001, today_only=True,
                    keep_card_statuses={"ready"},
                ),
                [10, 11, 12, 13],
            )

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

    def test_search_covers_all_customer_card_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(2020, "Мастер", None)
            customer_id = db.add_customer(user_id, "Пётр Сидоров", "+79990002020")
            car_id = db.add_car(
                user_id, "Lada", "Vesta", 2021, "А777АА26", customer_id,
                "XTA00000000002020", 85000, "2026-12-01", 95000,
            )
            order = db.add_service_order(
                car_id, "Замена помпы", 4500, 1200, 1800,
                concern="Перегрев двигателя", recommendations="Проверить термостат",
            )
            db.add_part_items(order.id, [("Водяной насос", 1, 1200, 1200)])
            connection = db.connect()
            try:
                connection.execute(
                    "INSERT INTO customer_notes(customer_id, note_text) VALUES (?, ?)",
                    (customer_id, "Предпочитает вечернее время"),
                )
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(db.search(2020, "Сидоров")["customers"][0]["id"], customer_id)
            self.assertEqual(db.search(2020, "95000")["cars"][0]["id"], car_id)
            self.assertEqual(db.search(2020, "термостат")["orders"][0]["id"], order.id)
            self.assertEqual(db.search(2020, "Водяной насос")["orders"][0]["id"], order.id)
            self.assertEqual(db.search(2020, "вечернее")["customers"][0]["id"], customer_id)

    def test_search_handles_multi_field_transliteration_and_typos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(2022, "Мастер", None)
            customer_id = db.add_customer(
                user_id, "Александр", "+7 968 277-42-82"
            )
            car_id = db.add_car(
                user_id, "Nissan", "Teana", plate_number="Н990СЕ",
                customer_id=customer_id,
            )

            queries = (
                "ниссан тиана",
                "тиана ниссан",
                "Nissan Teana",
                "нисан тиана",
                "машина Александр ниссан",
                "H990CE",
            )
            for query in queries:
                with self.subTest(query=query):
                    cars = db.search(2022, query)["cars"]
                    self.assertTrue(cars)
                    self.assertEqual(cars[0]["id"], car_id)

    def test_exact_phone_search_does_not_match_phone_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(2023, "Мастер", None)
            target_customer = db.add_customer(
                user_id, "Target", "+7 919 750-71-70"
            )
            target_car = db.add_car(
                user_id, "Lada", "Priora", customer_id=target_customer
            )
            target_order = db.add_service_order(
                target_car, "Service", 1000, 0, 0
            )
            other_customer = db.add_customer(
                user_id, "Other", "+7 919 735-10-41"
            )
            db.add_car(user_id, "Kia", "Sorento", customer_id=other_customer)

            result = db.search(2023, "+79197507170")

            self.assertEqual(
                [item["id"] for item in result["customers"]], [target_customer]
            )
            self.assertEqual([item["id"] for item in result["cars"]], [target_car])
            self.assertEqual(
                [item["id"] for item in result["orders"]], [target_order.id]
            )

    def test_completed_orders_can_be_filtered_by_recent_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(2021, "Мастер", None)
            car_id = db.add_car(user_id, "Lada", "Vesta")
            orders = [
                db.add_service_order(car_id, f"Service {number}", 1000, 0, 0)
                for number in range(3)
            ]
            for order in orders:
                db.set_order_status(order.id, "ready", user_id)
            connection = db.connect()
            try:
                connection.execute(
                    "UPDATE service_orders SET completed_at = datetime('now', '-2 days') WHERE id = ?",
                    (orders[1].id,),
                )
                connection.execute(
                    "UPDATE service_orders SET completed_at = datetime('now', '-5 days') WHERE id = ?",
                    (orders[2].id,),
                )
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(
                [item.id for item in db.get_completed_orders_for_telegram_user(2021, 1)],
                [orders[0].id],
            )
            self.assertEqual(
                {item.id for item in db.get_completed_orders_for_telegram_user(2021, 3)},
                {orders[0].id, orders[1].id},
            )
            self.assertEqual(
                len(db.get_completed_orders_for_telegram_user(2021, 7)), 3
            )

    def test_additional_customer_phone_is_displayed_found_and_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(2011, "Master", None)
            customer_id = db.add_customer(user_id, "Vadim Volga", "+7 928 363-12-54")
            self.assertTrue(db.add_customer_phone(customer_id, "+7 987 069-32-41"))
            self.assertFalse(db.add_customer_phone(customer_id, "+7 987 069-32-41"))
            self.assertEqual(
                db.get_customer_phones(customer_id),
                ["+7 928 363-12-54", "+7 987 069-32-41"],
            )
            found = db.find_customer(user_id, None, "+79870693241")
            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found.id, customer_id)
            self.assertEqual(db.search(2011, "9870693241")["customers"][0]["id"], customer_id)

    def test_semantic_crm_snapshot_contains_linked_work_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(2002, "Мастер", None)
            customer_id = db.add_customer(user_id, "Алексей", "+79990000002")
            car_id = db.add_car(
                user_id, "Opel", "Astra", customer_id=customer_id
            )
            db.add_service_order(car_id, "Замена масла", 1000, 0, 0)
            db.log_incoming_message(2002, "Покажи клиентов в работе", 10)

            snapshot = db.get_crm_snapshot(2002)

            self.assertEqual(snapshot["customers"][0]["full_name"], "Алексей")
            self.assertEqual(snapshot["orders"][0]["status"], "in_progress")
            self.assertEqual(snapshot["orders"][0]["customer_name"], "Алексей")
            self.assertEqual(
                db.get_recent_incoming_texts(2002),
                ["Покажи клиентов в работе"],
            )

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

    def test_flexible_appointment_is_marked_as_all_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4011, "Master", None)
            car_id = db.add_car(user_id, "Opel", "Astra")
            db.add_appointment(
                car_id, "Замена масла", "2026-08-03T12:00:00+03:00", is_flexible=True
            )

            appointment = db.get_upcoming_appointments_for_telegram_user(4011)[0]
            self.assertEqual(appointment.is_flexible, 1)

    def test_customer_parts_source_moves_from_appointment_to_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4013, "Master", None)
            customer_id = db.add_customer(user_id, "Коля", None)
            car_id = db.add_car(user_id, "Honda", "Stepwgn", customer_id=customer_id)
            appointment_id = db.add_appointment(
                car_id,
                "Замена масла",
                "2026-08-03T15:09:00+03:00",
                parts_source="customer",
            )

            appointment = db.get_upcoming_appointments_for_telegram_user(4013)[0]
            self.assertEqual(appointment.parts_source, "customer")
            order = db.start_appointment(user_id, appointment_id)
            self.assertIsNotNone(order)
            self.assertEqual(order.parts_source, "customer")
            self.assertEqual(db.get_upcoming_appointments_for_telegram_user(4013), [])
            updated = db.update_order_parts_source(order.id, "workshop", user_id)
            self.assertEqual(updated.parts_source, "workshop")

    def test_duplicate_active_appointment_returns_existing_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4012, "Master", None)
            car_id = db.add_car(user_id, "Nissan", "Teana")

            first_id = db.add_appointment(
                car_id, "Диагностика", "2026-08-03T12:00:00+03:00"
            )
            repeated_id = db.add_appointment(
                car_id, "диагностика", "2026-08-03T12:00:00+03:00"
            )

            self.assertEqual(repeated_id, first_id)
            self.assertEqual(len(db.get_upcoming_appointments_for_telegram_user(4012)), 1)
            repeated = db.save_appointment(
                car_id, "Диагностика", "2026-08-03T12:00:00+03:00"
            )
            self.assertFalse(repeated.created)
            self.assertEqual(repeated.id, first_id)
            self.assertEqual(
                db.find_active_appointment_id(car_id, "2026-08-03T12:00:00+03:00"),
                first_id,
            )

    def test_same_visit_is_not_duplicated_when_parsed_time_shifts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4020, "Master", None)
            car_id = db.add_car(user_id, "Lada", "Priora")

            first = db.save_appointment(
                car_id, "течь масла", "2026-08-05T10:00:00+03:00"
            )
            repeated = db.save_appointment(
                car_id, "  Течь   масла ", "2026-08-05T11:00:00+03:00"
            )

            self.assertTrue(first.created)
            self.assertFalse(repeated.created)
            self.assertEqual(repeated.id, first.id)

    def test_appointment_deduplication_prefers_customer_phone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4023, "Master", None)
            customer_id = db.add_customer(user_id, "Иван", "+7 999 123-45-67")
            first_car = db.add_car(
                user_id, "Lada", "Priora", customer_id=customer_id
            )
            second_car = db.add_car(
                user_id, "Lada", "Vesta", customer_id=customer_id
            )

            first = db.save_appointment(
                first_car, "течь масла", "2026-08-05T10:00:00+03:00"
            )
            repeated = db.save_appointment(
                second_car, "Течь масла", "2026-08-05T11:00:00+03:00"
            )
            other_visit = db.save_appointment(
                second_car, "диагностика подвески", "2026-08-05T12:00:00+03:00"
            )

            self.assertFalse(repeated.created)
            self.assertEqual(repeated.id, first.id)
            self.assertTrue(other_visit.created)
            self.assertNotEqual(other_visit.id, first.id)

    def test_visit_can_be_reassigned_to_anonymous_car_and_edited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4021, "Master", None)
            customer_id = db.add_customer(user_id, "Diana", None)
            wrong_car = db.add_car(user_id, "Hyundai", "Solaris", customer_id=customer_id)
            right_car = db.add_car(user_id, "Lada", "Vesta")
            appointment_id = db.add_appointment(
                wrong_car, "работа на выезде", "2026-08-04T17:10:00+03:00"
            )
            order = db.start_appointment(user_id, appointment_id)

            changed = db.update_appointment(
                user_id, appointment_id, car_id=right_car,
                description="замена бензонасоса",
            )

            self.assertTrue(changed)
            updated = db.get_service_order(order.id)
            self.assertEqual((updated.brand, updated.model), ("Lada", "Vesta"))
            self.assertIsNone(updated.customer_name)
            self.assertEqual(
                db.get_appointment_for_telegram_user(4021, appointment_id).car_id,
                right_car,
            )

    def test_finance_report_includes_profit_completed_today(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4022, "Master", None)
            car_id = db.add_car(user_id, "Lada", "Vesta")
            order = db.add_service_order(car_id, "Service", 4000, 1000, 1500)
            db.set_order_status(order.id, "ready", user_id)

            report = db.get_report_for_telegram_user(4022)

            self.assertEqual(report.today_profit, 4500)

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

    def test_appointment_arrival_creates_order_with_concern_and_agreed_amount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4003, "Master", None)
            customer_id = db.add_customer(user_id, "Sergey", "+7 999 000-00-00")
            car_id = db.add_car(user_id, "Lada", "Vesta", customer_id=customer_id)
            appointment_id = db.add_appointment(
                car_id, "Стук спереди", "2026-08-02T11:00:00+03:00", agreed_amount=5000
            )
            db.remember_service_message_card(
                -1001, 50, appointment_id=appointment_id
            )

            order = db.start_appointment(user_id, appointment_id)
            db.bind_appointment_card_to_order(appointment_id, order.id)

            self.assertIsNotNone(order)
            self.assertEqual(order.status, "in_progress")
            self.assertEqual(order.concern, "Стук спереди")
            self.assertEqual(order.agreed_amount, 5000)
            self.assertEqual(
                db.get_service_message_cards_for_order(order.id),
                [{"chat_id": -1001, "message_id": 50}],
            )
            ready = db.set_order_status(order.id, "ready", user_id)
            self.assertEqual(ready.status, "ready")
            self.assertEqual(db.get_upcoming_appointments_for_telegram_user(4003), [])

    def test_appointment_no_show_is_kept_in_history_and_excluded_from_finances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4010, "Master", None)
            customer_id = db.add_customer(user_id, "Repeat No-show", "+79990000010")
            car_id = db.add_car(
                user_id, "Lada", "Vesta", mileage=84000, customer_id=customer_id
            )
            appointment_id = db.add_appointment(
                car_id, "Диагностика", "2026-08-02T11:00:00+03:00", agreed_amount=5000
            )

            no_show = db.mark_appointment_no_show(user_id, appointment_id)

            self.assertIsNotNone(no_show)
            self.assertEqual(no_show.status, "no_show")
            self.assertEqual(no_show.labor_revenue, 0)
            self.assertEqual(no_show.mileage_at_visit, 84000)
            self.assertEqual(db.get_upcoming_appointments_for_telegram_user(4010), [])
            self.assertEqual(db.get_car_service_history(car_id)[0].status, "no_show")
            report = db.get_report_for_telegram_user(4010)
            self.assertEqual(report.orders, 0)
            self.assertEqual(report.revenue, 0)
            self.assertEqual(report.no_shows, 1)
            self.assertIsNone(db.mark_appointment_no_show(user_id, appointment_id))

    def test_archive_and_audit_keep_order_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4004, "Master", None)
            car_id = db.add_car(user_id, "Kia", "Rio")
            order = db.add_service_order(car_id, "Замена масла", 1500, 0, 0)

            self.assertTrue(db.delete_service_order(user_id, order.id))
            self.assertEqual(db.get_recent_orders_for_telegram_user(4004), [])
            self.assertEqual(db.get_archived(user_id)[0]["id"], order.id)
            self.assertEqual(db.get_audit_log(user_id)[0]["action"], "archived")

    def test_archive_can_be_purged_manually_or_after_retention_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4006, "Master", None)
            old_car = db.add_car(user_id, "Kia", "Rio")
            old_order = db.add_service_order(old_car, "Old service", 1000, 0, 0)
            new_car = db.add_car(user_id, "Lada", "Vesta")
            new_order = db.add_service_order(new_car, "Recent service", 1000, 0, 0)
            db.delete_service_order(user_id, old_order.id)
            db.delete_service_order(user_id, new_order.id)
            connection = db.connect()
            try:
                connection.execute(
                    "UPDATE service_orders SET archived_at = datetime('now', '-31 days') WHERE id = ?",
                    (old_order.id,),
                )
                connection.commit()
            finally:
                connection.close()

            deleted = db.purge_archived(user_id, older_than_days=30)

            self.assertEqual(deleted["orders"], 1)
            self.assertEqual(db.count_archived(user_id)["orders"], 1)
            self.assertEqual(db.purge_archived(user_id)["orders"], 1)
            self.assertEqual(db.count_archived(user_id)["orders"], 0)

    def test_deleted_appointment_can_be_restored_from_trash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4011, "Master", None)
            car_id = db.add_car(user_id, "Lada", "Vesta")
            appointment_id = db.add_appointment(car_id, "Diagnostics", "2030-01-01T10:00:00")

            self.assertTrue(db.delete_appointment(user_id, appointment_id))
            self.assertIsNone(db.get_appointment_for_telegram_user(4011, appointment_id))
            self.assertEqual(db.get_trash(user_id)[0]["kind"], "appointment")
            self.assertTrue(db.restore_archived(user_id, "appointment", appointment_id))
            self.assertIsNotNone(db.get_appointment_for_telegram_user(4011, appointment_id))

    def test_diagnostic_card_tracks_progress_and_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4012, "Master", None)
            car_id = db.add_car(user_id, "Kia", "Rio", mileage=125000)
            order = db.add_service_order(car_id, "Диагностика", 0, 0, 0)
            checklist = [
                ("general", "body", "Кузов", False),
                ("suspension", "bearings", "Подшипники", True),
            ]

            card = db.start_diagnostic(user_id, car_id, order.id, checklist)
            self.assertIsNotNone(card)
            assert card is not None
            self.assertEqual(card["mileage"], 125000)
            self.assertEqual(len(card["items"]), 2)
            updated = db.update_diagnostic_item(
                user_id, int(card["id"]), "bearings",
                left_status="ok", right_status="critical",
                recommendation="Заменить правый подшипник", estimated_cost=5000,
            )
            self.assertEqual(updated["right_status"], "critical")
            completed = db.update_diagnostic(
                user_id, int(card["id"]), mileage=125100,
                notes="Проверено", status="completed",
            )
            self.assertEqual(completed["status"], "completed")
            summary = db.list_diagnostics(user_id)[0]
            self.assertEqual(summary["checked"], 1)
            self.assertEqual(summary["critical"], 1)
            reopened = db.start_diagnostic(user_id, car_id, order.id, checklist)
            assert reopened is not None
            self.assertEqual(reopened["id"], card["id"])
            self.assertEqual(reopened["status"], "completed")
            self.assertEqual(reopened["items"][1]["right_status"], "critical")

            other_user_id = db.add_or_update_user(4013, "Other", None)
            self.assertIsNone(db.delete_diagnostic(other_user_id, int(card["id"])))
            self.assertEqual(db.delete_diagnostic(user_id, int(card["id"])), [])
            self.assertIsNone(db.get_diagnostic(user_id, int(card["id"])))
            self.assertEqual(db.list_diagnostics(user_id), [])

    def test_paired_brake_items_use_one_status_and_migrate_side_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            db = Database(path)
            db.initialize()
            user_id = db.add_or_update_user(4015, "Master", None)
            car_id = db.add_car(user_id, "Lada", "Vesta")
            card = db.start_diagnostic(
                user_id, car_id, None,
                [("brakes", "front_pads", "Передние тормозные колодки", False)],
            )
            assert card is not None
            item = card["items"][0]
            self.assertIsNone(item["left_status"])
            self.assertIsNone(item["right_status"])

            connection = db.connect()
            try:
                connection.execute(
                    "UPDATE diagnostic_items SET left_status = 'critical', right_status = 'unchecked' WHERE id = ?",
                    (item["id"],),
                )
                connection.commit()
            finally:
                connection.close()
            db.initialize()
            migrated = db.get_diagnostic(user_id, int(card["id"]))["items"][0]
            self.assertEqual(migrated["status"], "critical")
            self.assertIsNone(migrated["left_status"])
            self.assertIsNone(migrated["right_status"])

    def test_diagnostic_creates_one_safe_order_without_invented_parts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4014, "Master", None)
            car_id = db.add_car(user_id, "Kia", "Venga", mileage=198500)
            checklist = [("suspension", "rods", "Рулевые тяги", True)]
            card = db.start_diagnostic(user_id, car_id, None, checklist)
            assert card is not None
            db.update_diagnostic_item(
                user_id, int(card["id"]), "rods", left_status="critical",
                right_status="attention", recommendation="Заменить рулевую тягу",
                estimated_cost=2500,
            )

            result = db.create_order_from_diagnostic(user_id, int(card["id"]))
            assert result is not None
            order, created = result
            self.assertTrue(created)
            self.assertEqual(order.labor_revenue, 0)
            self.assertEqual(order.parts_cost, 0)
            self.assertEqual(order.parts_revenue, 0)
            self.assertEqual(order.description, "")
            self.assertIsNone(order.recommendations)
            self.assertIn("По результатам диагностики", order.concern or "")
            self.assertIn("• Рулевые тяги — левая сторона", order.concern or "")
            self.assertIn("• Рулевые тяги — правая сторона", order.concern or "")
            self.assertEqual(db.get_part_items(order.id), [])

            repeated = db.create_order_from_diagnostic(user_id, int(card["id"]))
            assert repeated is not None
            repeated_order, repeated_created = repeated
            self.assertFalse(repeated_created)
            self.assertEqual(repeated_order.id, order.id)
            self.assertEqual(repeated_order.description, order.description)

            self.assertTrue(db.delete_service_order(user_id, order.id))
            self.assertIsNone(db.get_diagnostic(user_id, int(card["id"]))["service_order_id"])
            recreated = db.create_order_from_diagnostic(user_id, int(card["id"]))
            assert recreated is not None
            recreated_order, recreated_created = recreated
            self.assertTrue(recreated_created)
            self.assertNotEqual(recreated_order.id, order.id)

    def test_phone_and_plate_are_normalized_for_future_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4005, "Master", None)
            db.add_customer(user_id, "Ivan", "8 (999) 000-00-00")
            db.add_car(user_id, "Kia", "Rio", plate_number="а 123 аа 77")
            connection = db.connect()
            try:
                self.assertEqual(connection.execute("SELECT phone_normalized FROM customers").fetchone()[0], "79990000000")
                self.assertEqual(connection.execute("SELECT plate_normalized FROM cars").fetchone()[0], "А123АА77")
            finally:
                connection.close()

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

    def test_catalog_part_updates_order_totals_with_markup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(4001, "Master", None)
            car_id = db.add_car(user_id, "Kia", "Rio")
            order = db.add_service_order(car_id, "Service", 1000, 0, 0)

            item = db.add_catalog_part(order.id, "Oil filter", "OF-1", 2, 500, 40)

            self.assertEqual(item.total_cost, 1000)
            self.assertEqual(item.markup_percent, 40)
            updated = db.get_service_order(order.id)
            self.assertEqual(updated.parts_cost, 1000)
            self.assertEqual(updated.parts_revenue, 1400)
            self.assertEqual(updated.profit, 1400)
