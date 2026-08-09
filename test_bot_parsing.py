import unittest

from bot import (
    customer_name_for_edit,
    empty_workshop_command,
    fill_contact_and_appointment_from_text,
)
from openrouter import WorkshopCommand


def command(**changes: object) -> WorkshopCommand:
    values = {
        name: None for name in WorkshopCommand.__dataclass_fields__ if name != "intent"
    }
    values.update(changes)
    return WorkshopCommand(intent="upsert_customer", **values)


class BotParsingTests(unittest.TestCase):
    def test_vin_and_plate_are_extracted_and_removed_from_customer_name(self) -> None:
        text = "Добавь VIN XTA21124070412345, номер авто М278ОМ"
        parsed = fill_contact_and_appointment_from_text(
            command(customer_name="VIN XTA21124070412345 номер авто М278ОМ"), text
        )
        self.assertEqual(parsed.vin, "XTA21124070412345")
        self.assertEqual(parsed.plate_number, "М278ОМ")
        self.assertIsNone(parsed.customer_name)

    def test_real_name_before_plate_marker_is_preserved(self) -> None:
        parsed = fill_contact_and_appointment_from_text(
            command(customer_name="Алексей номер авто М278ОМ"),
            "Алексей, номер авто М278ОМ",
        )
        self.assertEqual(parsed.customer_name, "Алексей")
        self.assertEqual(parsed.plate_number, "М278ОМ")

    def test_vehicle_only_edit_does_not_replace_existing_customer_name(self) -> None:
        parsed = fill_contact_and_appointment_from_text(
            empty_workshop_command(), "Номер авто М278ОМ"
        )
        self.assertIsNone(customer_name_for_edit(parsed, "Номер авто М278ОМ"))

    def test_plain_name_edit_still_works_without_ai(self) -> None:
        parsed = empty_workshop_command()
        self.assertEqual(customer_name_for_edit(parsed, "Алексей"), "Алексей")


if __name__ == "__main__":
    unittest.main()
