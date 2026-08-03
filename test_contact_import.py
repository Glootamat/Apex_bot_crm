import tempfile
import unittest
from pathlib import Path

from contact_import import (
    VCardContact, analyze_contact, apply_manual_decisions, apply_preview, format_phone, parse_vcards,
)
from database import Database


class ContactImportTests(unittest.TestCase):
    def test_vcard_parser_unfolds_lines_and_normalizes_phones(self) -> None:
        content = """BEGIN:VCARD
VERSION:3.0
FN:Александр Солярис Н990СЕ
TEL;TYPE=CELL:+7 968 277-42-82
NOTE:Замена масла\\nАКПП
CATEGORIES:ignored
END:VCARD
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.vcf"
            path.write_text(content, encoding="utf-8")
            contacts = parse_vcards(path)
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0].phones, ["79682774282"])
        self.assertIn("Замена масла\nАКПП", contacts[0].notes)

    def test_analyzer_separates_owner_car_plate_and_source_note(self) -> None:
        contact = VCardContact(1, "Александр Солярис Н990СЕ", ["79682774282"], [])
        item = analyze_contact(contact, {})
        self.assertEqual(item.customer_name, "Александр")
        self.assertEqual((item.brand, item.model), ("Hyundai", "Solaris"))
        self.assertEqual(item.plate_number, "Н990СЕ")
        self.assertEqual(item.action, "create")

    def test_plate_before_brand_is_not_part_of_customer_name(self) -> None:
        contact = VCardContact(10, "Андрей Н692ТХ Датсун", ["79187974443"], [])
        item = analyze_contact(contact, {})
        self.assertEqual(item.customer_name, "Андрей")
        self.assertEqual(item.plate_number, "Н692ТХ")

    def test_analyzer_uses_existing_customer_name_by_phone(self) -> None:
        contact = VCardContact(7, "Александ Ниссан Тиана", ["79886012650"], ["Замена масла АКПП"])
        item = analyze_contact(contact, {"79886012650": (1, "Александр")})
        self.assertEqual(item.customer_name, "Александр")
        self.assertEqual(item.existing_customer_id, 1)
        self.assertEqual(item.action, "merge_existing")

    def test_ambiguous_contact_is_never_ready_automatically(self) -> None:
        contact = VCardContact(1, "Михаил Киа Спектра Рено Лагуна", ["79990000000"], [])
        item = analyze_contact(contact, {})
        self.assertEqual(item.action, "review")
        self.assertIn("в одном контакте возможно несколько автомобилей", item.review_reasons)

    def test_phone_format(self) -> None:
        self.assertEqual(format_phone("79886012650"), "+7 988 601-26-50")

    def test_apply_imports_only_new_safe_contacts_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "crm.sqlite3"
            db = Database(db_path)
            db.initialize()
            user_id = db.add_or_update_user(123, "Owner", None)
            db.add_customer(user_id, "Existing", "+7 988 601-26-50")
            preview = {
                "contacts": [
                    {
                        "source_index": 1, "customer_name": "Анна",
                        "phones": ["+7 999 881-13-53"], "brand": "Ford", "model": "Fiesta",
                        "plate_number": None, "imported_note": "Source card", "action": "create",
                    },
                    {
                        "source_index": 2, "customer_name": "Existing",
                        "phones": ["+7 988 601-26-50"], "brand": "Nissan", "model": "Teana",
                        "plate_number": None, "imported_note": None, "action": "merge_existing",
                    },
                    {
                        "source_index": 3, "customer_name": None,
                        "phones": [], "brand": None, "model": None,
                        "plate_number": None, "imported_note": None, "action": "review",
                    },
                ]
            }
            result = apply_preview(preview, db_path, 123, "fingerprint")
            self.assertEqual(result["imported_customers"], 1)
            self.assertEqual(result["skipped_existing"], 1)
            self.assertEqual(result["skipped_review"], 1)
            self.assertEqual(len(db.get_customers_for_telegram_user(123)), 2)
            imported = db.find_customer(user_id, "Анна", "+7 999 881-13-53")
            self.assertIsNotNone(imported)
            assert imported is not None
            self.assertEqual(db.get_customer_notes(imported.id)[0]["note_text"], "Source card")

            second = apply_preview(preview, db_path, 123, "fingerprint")
            self.assertEqual(second["imported_customers"], 0)
            self.assertEqual(second["skipped_existing"], 1)
            self.assertEqual(second["skipped_already_imported"], 1)

    def test_manual_decision_supports_two_phones_and_two_cars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "crm.sqlite3"
            db = Database(db_path)
            db.initialize()
            db.add_or_update_user(321, "Owner", None)
            decisions = [{
                "source_indices": [20, 27],
                "customer_name": "Vadim Volga",
                "phones": ["+7 928 363-12-54", "+7 987 069-32-41"],
                "cars": [
                    {"brand": "Lada", "model": "2114"},
                    {"brand": "GAZ", "model": "Volga"},
                ],
                "note": "Reviewed",
            }]
            result = apply_manual_decisions(decisions, db_path, 321, "source")
            self.assertEqual(result["imported_customers"], 1)
            self.assertEqual(result["imported_cars"], 2)
            self.assertEqual(result["imported_extra_phones"], 1)
            customer = db.find_customer(1, None, "+79870693241")
            self.assertIsNotNone(customer)
            assert customer is not None
            self.assertEqual(db.get_customer_phones(customer.id)[1], "+7 987 069-32-41")


if __name__ == "__main__":
    unittest.main()
