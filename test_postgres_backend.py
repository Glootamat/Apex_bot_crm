import unittest

from postgres_backend import HybridRow, _translate


class PostgresCompatibilityTest(unittest.TestCase):
    def test_qmark_and_sqlite_upsert_are_translated(self) -> None:
        sql = _translate("INSERT OR IGNORE INTO daily_reminders (reminder_date) VALUES (?)")
        self.assertIn("ON CONFLICT DO NOTHING", sql)
        self.assertIn("%s", sql)

    def test_sqlite_date_and_scalar_max_are_translated(self) -> None:
        sql = _translate("SELECT MAX(0, parts_cost + ?) FROM service_orders WHERE date(completed_at, 'localtime') = date('now', 'localtime')")
        self.assertIn("GREATEST(0, parts_cost + %s)", sql)
        self.assertIn("CAST(completed_at AS DATE) = CURRENT_DATE", sql)

    def test_rows_support_names_and_numeric_indexes(self) -> None:
        row = HybridRow({"count": 7})
        self.assertEqual(row["count"], 7)
        self.assertEqual(row[0], 7)


if __name__ == "__main__":
    unittest.main()
