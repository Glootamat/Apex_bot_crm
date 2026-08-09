import unittest

from supplier_catalog import SupplierOffer, _parse_profit_liga, serialize_offer


class SupplierCatalogTest(unittest.TestCase):
    def test_offer_markup_is_calculated_for_customer(self) -> None:
        offer = SupplierOffer("ROSSKO", "stock-1", "KIA", "26300", "Oil filter", 2450, 12, 0)
        result = serialize_offer(offer, 40)
        self.assertEqual(result["sale_price"], 3430)
        self.assertEqual(result["profit"], 980)
        self.assertEqual(serialize_offer(offer, 40, 50)["sale_price"], 3450)
        self.assertEqual(serialize_offer(offer, 40, 100)["sale_price"], 3500)

    def test_profit_liga_nested_stock_response_is_mapped(self) -> None:
        offers = _parse_profit_liga([{
            "id": 17, "article": "26300", "brand": "KIA", "description": "Фильтр",
            "products": {"offer-hash": {"article_id": 17, "warehouse_id": 4, "quantity": 8,
                          "price": "2450.50", "delivery_time": 25,
                          "custom_warehouse_name": "Основной склад"}},
        }])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].purchase_price, 2450)
        self.assertEqual(offers[0].delivery_days, 2)
        self.assertEqual(offers[0].offer_id, "17:4")


if __name__ == "__main__":
    unittest.main()
