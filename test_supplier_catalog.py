import unittest

from defusedxml.common import EntitiesForbidden

from supplier_catalog import SafeET, SupplierOffer, _parse_profit_liga, _require_https_url, serialize_offer


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

    def test_supplier_url_must_be_https(self) -> None:
        with self.assertRaises(RuntimeError):
            _require_https_url("http://127.0.0.1/internal")
        with self.assertRaises(RuntimeError):
            _require_https_url("https://user:password@example.com/api")

    def test_external_xml_entities_are_rejected(self) -> None:
        payload = b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>'
        with self.assertRaises(EntitiesForbidden):
            SafeET.fromstring(payload)


if __name__ == "__main__":
    unittest.main()
