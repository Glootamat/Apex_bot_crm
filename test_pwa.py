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


if __name__ == "__main__":
    unittest.main()
