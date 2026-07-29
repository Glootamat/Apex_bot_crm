import tempfile
import unittest
from pathlib import Path

from database import Database


class DatabaseTest(unittest.TestCase):
    def test_user_and_car_are_linked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()

            user_id = db.add_or_update_user(123, "Иван Иванов", "ivan")
            db.add_car(user_id, "Toyota", "Camry", 2020, "А123АА77")

            cars = db.get_cars_for_telegram_user(123)
            self.assertEqual(len(cars), 1)
            self.assertEqual(cars[0].brand, "Toyota")
            self.assertEqual(cars[0].year, 2020)
