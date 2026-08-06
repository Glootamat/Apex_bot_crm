import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import pwa
from database import Database


def password_hash(password: str) -> str:
    salt = b"apex-crm-test-salt"
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return f"pbkdf2_sha256${iterations}${encode(salt)}${encode(digest)}"


class PwaTest(unittest.TestCase):
    def test_health_login_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(8001, "Owner", None)
            customer_id = db.add_customer(user_id, "Иван", "+79990000001")
            car_id = db.add_car(user_id, "Lada", "Vesta", customer_id=customer_id)
            db.add_service_order(car_id, "Диагностика", 1500, 0, 0)
            environment = {
                "ADMIN_ID": "8001",
                "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                client = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(client.get("/health").json(), {"status": "ok"})
                self.assertEqual(client.get("/api/dashboard").status_code, 401)
                self.assertEqual(
                    client.post(
                        "/api/login",
                        json={"username": "admin", "password": "wrong"},
                    ).status_code,
                    401,
                )
                response = client.post(
                    "/api/login",
                    json={"username": "admin", "password": "secret-password"},
                )
                self.assertEqual(response.status_code, 200)
                dashboard = client.get("/api/dashboard")
                self.assertEqual(dashboard.status_code, 200)
                self.assertEqual(dashboard.json()["active_orders"], 1)
                self.assertIn("no-store", dashboard.headers["cache-control"])

                db.set_order_status(1, "ready")
                refreshed = client.get("/api/dashboard")
                self.assertEqual(refreshed.json()["active_orders"], 0)

    def test_crm_crud_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.add_or_update_user(9001, "Owner", None)
            environment = {
                "ADMIN_ID": "9001",
                "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                client = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(
                    client.post(
                        "/api/login",
                        json={"username": "admin", "password": "secret-password"},
                    ).status_code,
                    200,
                )
                customer = client.post(
                    "/api/customers", json={"full_name": "Артём", "phone": "+79990001122"}
                )
                self.assertEqual(customer.status_code, 200)
                car = client.post(
                    "/api/cars",
                    json={
                        "customer_id": customer.json()["id"],
                        "brand": "Lada", "model": "Vesta", "plate_number": "А123АА26",
                    },
                )
                self.assertEqual(car.status_code, 200)
                appointment = client.post(
                    "/api/appointments",
                    json={
                        "car_id": car.json()["id"], "description": "Диагностика",
                        "starts_at": "2030-01-01T10:00:00", "agreed_amount": 1500,
                    },
                )
                self.assertEqual(appointment.status_code, 200)
                arrived = client.post(
                    f"/api/appointments/{appointment.json()['id']}/action",
                    json={"action": "arrived"},
                )
                self.assertEqual(arrived.status_code, 200)
                completed = client.post(
                    f"/api/orders/{arrived.json()['id']}/status", json={"action": "ready"}
                )
                self.assertEqual(completed.status_code, 200)
                snapshot = client.get("/api/crm")
                self.assertEqual(snapshot.status_code, 200)
                self.assertEqual(len(snapshot.json()["customers"]), 1)
                self.assertEqual(len(snapshot.json()["cars"]), 1)
                self.assertEqual(snapshot.json()["orders"][0]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
