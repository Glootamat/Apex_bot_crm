import unittest

from openrouter import MAX_RECEIPT_ITEMS, _validate_receipt


class OpenRouterSecurityTest(unittest.TestCase):
    def test_receipt_total_is_recomputed_from_validated_lines(self) -> None:
        receipt = _validate_receipt({
            "document_type": "receipt",
            "items": [{"name": "Фильтр", "article": "A1", "quantity": 2, "unit_cost": 500, "total_cost": 1000}],
            "total_cost": 999_999_999,
        })
        self.assertEqual(receipt.total_cost, 1000)

    def test_receipt_rejects_excessive_item_count(self) -> None:
        item = {"name": "Деталь", "article": None, "quantity": 1, "unit_cost": 10, "total_cost": 10}
        with self.assertRaises(ValueError):
            _validate_receipt({"document_type": "receipt", "items": [item] * (MAX_RECEIPT_ITEMS + 1), "total_cost": 10})

    def test_receipt_rejects_negative_or_non_numeric_money(self) -> None:
        for invalid in (-1, "100"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                _validate_receipt({
                    "document_type": "receipt",
                    "items": [{"name": "Деталь", "article": None, "quantity": 1, "unit_cost": 10, "total_cost": invalid}],
                    "total_cost": 10,
                })


if __name__ == "__main__":
    unittest.main()
