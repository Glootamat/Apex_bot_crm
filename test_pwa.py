import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import pwa
from database import Database
from openrouter import AIResponse, ReceiptAnalysis, ReceiptItem, VehicleDocumentAnalysis


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
            with patch.object(pwa, "db", db), patch.object(
                pwa, "UPLOAD_DIR", Path(directory) / "uploads"
            ), patch.dict(os.environ, environment):
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
            with patch.object(pwa, "db", db), patch.object(
                pwa, "UPLOAD_DIR", Path(directory) / "uploads"
            ), patch.dict(os.environ, environment):
                client = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(
                    client.post(
                        "/api/login",
                        json={"username": "admin", "password": "secret-password"},
                    ).status_code,
                    200,
                )
                vehicle_result = AIResponse(
                    VehicleDocumentAnalysis(
                        "pts", "Z94CB41AAGR123456", "О269ЕН126",
                        "Kia", "Rio", 2019, "high",
                    ),
                    "vision-test", 12, 6, 0.002,
                )
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch.object(
                    pwa, "analyze_vehicle_document", AsyncMock(return_value=vehicle_result)
                ):
                    recognized_vehicle = client.post(
                        "/api/vehicle-recognition/image",
                        content=b"vehicle-document-image",
                        headers={"content-type": "image/jpeg"},
                    )
                self.assertEqual(recognized_vehicle.status_code, 200)
                self.assertEqual(recognized_vehicle.json()["vin"], "Z94CB41AAGR123456")
                self.assertEqual(recognized_vehicle.json()["brand"], "Kia")
                self.assertEqual(recognized_vehicle.json()["model"], "Rio")
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
                diagnostic = client.post(
                    "/api/diagnostics/start",
                    json={"car_id": car.json()["id"]},
                )
                self.assertEqual(diagnostic.status_code, 200)
                self.assertGreater(len(diagnostic.json()["items"]), 40)
                diagnostic_id = diagnostic.json()["id"]
                first_item = diagnostic.json()["items"][0]
                checked = client.put(
                    f"/api/diagnostics/{diagnostic_id}/items/{first_item['item_key']}",
                    json={"status": "attention", "recommendation": "Проверить повторно"},
                )
                self.assertEqual(checked.status_code, 200)
                self.assertEqual(checked.json()["status"], "attention")
                completed_diagnostic = client.put(
                    f"/api/diagnostics/{diagnostic_id}",
                    json={"mileage": 100500, "notes": "Осмотр завершён", "status": "completed"},
                )
                self.assertEqual(completed_diagnostic.status_code, 200)
                self.assertEqual(completed_diagnostic.json()["status"], "completed")
                diagnostic_pdf = client.get(f"/api/diagnostics/{diagnostic_id}/pdf")
                self.assertEqual(diagnostic_pdf.status_code, 200)
                self.assertEqual(diagnostic_pdf.headers["content-type"], "application/pdf")
                self.assertTrue(diagnostic_pdf.content.startswith(b"%PDF-"))
                removable = client.post(
                    "/api/appointments",
                    json={
                        "car_id": car.json()["id"], "description": "Предварительная запись",
                        "starts_at": "2030-01-02T12:00:00",
                    },
                )
                self.assertEqual(removable.status_code, 200)
                self.assertEqual(
                    client.delete(f"/api/appointments/{removable.json()['id']}").status_code,
                    200,
                )
                self.assertEqual(
                    client.delete(f"/api/appointments/{removable.json()['id']}").status_code,
                    404,
                )
                trash = client.get("/api/trash")
                self.assertEqual(trash.status_code, 200)
                self.assertEqual(trash.json()["retention_days"], 30)
                self.assertEqual(trash.json()["items"][0]["kind"], "appointment")
                self.assertEqual(
                    client.post(
                        f"/api/trash/appointment/{removable.json()['id']}/restore"
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    client.delete(f"/api/appointments/{removable.json()['id']}").status_code,
                    200,
                )
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
                self.assertEqual(
                    client.delete(f"/api/appointments/{appointment.json()['id']}").status_code,
                    409,
                )
                snapshot = client.get("/api/crm")
                self.assertEqual(snapshot.status_code, 200)
                self.assertEqual(len(snapshot.json()["customers"]), 1)
                self.assertEqual(len(snapshot.json()["cars"]), 1)
                self.assertEqual(snapshot.json()["orders"][0]["status"], "ready")
                self.assertEqual(len(snapshot.json()["appointment_history"]), 1)

                search = client.get("/api/search", params={"q": "lada"})
                self.assertEqual(search.status_code, 200)
                self.assertIn("appointments", search.json())
                self.assertEqual(len(search.json()["appointments"]), 1)

                recognized = AIResponse(
                    ReceiptAnalysis(
                        "receipt",
                        [ReceiptItem("Масляный фильтр", "OF-1", 1, 1000, 1000)],
                        1000,
                    ),
                    "vision-test", 10, 5, 0.001,
                )
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch.object(
                    pwa, "analyze_receipt_image", AsyncMock(return_value=recognized)
                ):
                    photo = client.post(
                        f"/api/orders/{arrived.json()['id']}/photos",
                        params={"photo_type": "receipt"},
                        content=b"small-test-image",
                        headers={"content-type": "image/jpeg"},
                    )
                self.assertEqual(photo.status_code, 200)
                self.assertTrue(photo.json()["recognized"])
                self.assertEqual(photo.json()["purchase_cost"], 1000)
                self.assertEqual(photo.json()["markup_profit"], 400)
                self.assertEqual(photo.json()["selling_price"], 1400)
                self.assertEqual(client.get(photo.json()["url"]).content, b"small-test-image")
                with_photo = client.get("/api/crm").json()["orders"][0]
                self.assertEqual(with_photo["attachments"][0]["photo_type"], "receipt")
                self.assertEqual(with_photo["parts_cost"], 1000)
                self.assertEqual(with_photo["parts_revenue"], 1400)

                order_id = arrived.json()["id"]
                self.assertEqual(client.delete(f"/api/orders/{order_id}").status_code, 200)
                self.assertEqual(client.delete(f"/api/orders/{order_id}").status_code, 404)
                self.assertEqual(client.get("/api/crm").json()["orders"], [])

                self.assertEqual(client.delete(f"/api/cars/{car.json()['id']}").status_code, 200)
                self.assertEqual(client.delete(f"/api/customers/{customer.json()['id']}").status_code, 200)
                after_delete = client.get("/api/crm").json()
                self.assertEqual(after_delete["cars"], [])
                self.assertEqual(after_delete["customers"], [])


if __name__ == "__main__":
    unittest.main()
