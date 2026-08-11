import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient as FastAPITestClient

import pwa
from database import Database
from openrouter import AIResponse, ReceiptAnalysis, ReceiptItem, VehicleDocumentAnalysis


class TestClient(FastAPITestClient):
    """Test browser that keeps the access JWT in memory like the PWA."""

    def request(self, method: str, url: str, **kwargs):
        response = super().request(method, url, **kwargs)
        try:
            access_token = response.json().get("access_token")
        except (AttributeError, ValueError):
            access_token = None
        if access_token:
            self.headers["Authorization"] = f"Bearer {access_token}"
        if url == "/api/logout" and response.is_success:
            self.headers.pop("Authorization", None)
        return response


def password_hash(password: str) -> str:
    salt = b"apex-crm-test-salt"
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return f"pbkdf2_sha256${iterations}${encode(salt)}${encode(digest)}"


class PwaTest(unittest.TestCase):
    def test_mechanic_can_edit_work_but_not_finances_or_delete_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(9101, "Owner", None)
            car_id = db.add_car(user_id, "Lada", "Vesta")
            order_id = db.add_service_order(car_id, "Диагностика", 1500, 0, 0).id
            environment = {
                "ADMIN_ID": "9101", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                owner = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(owner.post("/api/login", json={"username": "admin", "password": "secret-password"}).status_code, 200)
                self.assertEqual(owner.post("/api/settings/staff", json={
                    "username": "mechanic", "password": "mechanic-password",
                    "full_name": "Механик", "role": "mechanic",
                }).status_code, 201)
                mechanic = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(mechanic.post("/api/login", json={"username": "mechanic", "password": "mechanic-password"}).status_code, 200)
                payload = {
                    "car_id": car_id, "description": "Работы выполнены", "labor_revenue": 1500,
                    "parts_cost": 0, "parts_revenue": 0, "parts_profit": 0,
                    "concern": None, "agreed_amount": None, "recommendations": None,
                    "parts_source": None,
                }
                self.assertEqual(mechanic.put(f"/api/orders/{order_id}", json=payload).status_code, 200)
                self.assertEqual(mechanic.put(
                    f"/api/orders/{order_id}", json=payload | {"labor_revenue": 999_999},
                ).status_code, 403)
                self.assertEqual(mechanic.delete(f"/api/orders/{order_id}").status_code, 403)

    def test_password_change_revokes_previous_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.add_or_update_user(9201, "Owner", None)
            environment = {
                "ADMIN_ID": "9201", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                client = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(client.post("/api/login", json={"username": "admin", "password": "secret-password"}).status_code, 200)
                old_cookie = client.cookies.get(pwa.COOKIE_NAME)
                self.assertIsNotNone(old_cookie)
                changed = client.put("/api/settings/password", json={
                    "current_password": "secret-password", "new_password": "new-secret-password",
                })
                self.assertEqual(changed.status_code, 200)
                self.assertEqual(client.get("/api/dashboard").status_code, 200)
                stolen = TestClient(pwa.app, base_url="https://testserver")
                stolen.cookies.set(pwa.COOKIE_NAME, str(old_cookie))
                self.assertEqual(stolen.get("/api/dashboard").status_code, 401)

    def test_web_updates_can_clear_nullable_fields_and_validate_money(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.add_or_update_user(9301, "Owner", None)
            environment = {
                "ADMIN_ID": "9301", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                client = TestClient(pwa.app, base_url="https://testserver")
                client.post("/api/login", json={"username": "admin", "password": "secret-password"})
                customer = client.post("/api/customers", json={"full_name": "Иван", "phone": "+79990000000"}).json()
                car = client.post("/api/cars", json={
                    "customer_id": customer["id"], "brand": "Lada", "model": "Vesta",
                    "year": 2020, "plate_number": "А123АА77", "vin": "XTA12345678901234",
                    "mileage": 100000,
                }).json()
                cleared_customer = client.put(f"/api/customers/{customer['id']}", json={"full_name": "Иван", "phone": None})
                self.assertIsNone(cleared_customer.json()["phone"])
                cleared_car = client.put(f"/api/cars/{car['id']}", json={
                    "customer_id": None, "brand": "Lada", "model": "Vesta", "year": None,
                    "plate_number": None, "vin": None, "mileage": None,
                })
                self.assertEqual(cleared_car.status_code, 200)
                self.assertIsNone(cleared_car.json()["customer_id"])
                self.assertIsNone(cleared_car.json()["vin"])
                appointment = client.post("/api/appointments", json={
                    "car_id": car["id"], "description": "Диагностика",
                    "starts_at": "2030-01-01T10:00:00", "agreed_amount": 1500,
                    "parts_source": "workshop",
                }).json()
                cleared_appointment = client.put(f"/api/appointments/{appointment['id']}", json={
                    "car_id": car["id"], "description": "Диагностика",
                    "starts_at": "2030-01-01T10:00:00", "agreed_amount": None,
                    "parts_source": None, "is_flexible": False,
                })
                self.assertIsNone(cleared_appointment.json()["agreed_amount"])
                self.assertIsNone(cleared_appointment.json()["parts_source"])
                created_order = client.post("/api/orders", json={
                    "car_id": car["id"], "description": "Работы", "labor_revenue": 1000,
                    "concern": "Стук", "agreed_amount": 1000,
                    "recommendations": "Проверить", "parts_source": "customer",
                }).json()
                cleared_order = client.put(f"/api/orders/{created_order['id']}", json={
                    "car_id": car["id"], "description": "Работы", "labor_revenue": 1000,
                    "parts_cost": 0, "parts_revenue": 0, "parts_profit": 0,
                    "concern": None, "agreed_amount": None, "recommendations": None,
                    "parts_source": None,
                })
                self.assertIsNone(cleared_order.json()["concern"])
                self.assertIsNone(cleared_order.json()["agreed_amount"])
                self.assertIsNone(cleared_order.json()["parts_source"])
                invalid_order = client.post("/api/orders", json={
                    "car_id": car["id"], "description": "Работы", "labor_revenue": -1,
                })
                self.assertEqual(invalid_order.status_code, 422)

    def test_order_photo_is_private_to_organization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            user_id = db.add_or_update_user(9401, "Platform Owner", None)
            car_id = db.add_car(user_id, "Lada", "Vesta")
            order_id = db.add_service_order(car_id, "Работы", 1000, 0, 0).id
            environment = {
                "ADMIN_ID": "9401", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.object(
                pwa, "UPLOAD_DIR", Path(directory) / "uploads",
            ), patch.dict(os.environ, environment):
                admin = TestClient(pwa.app, base_url="https://testserver")
                admin.post("/api/login", json={"username": "admin", "password": "secret-password"})
                photo = admin.post(
                    f"/api/orders/{order_id}/photos", content=b"\xff\xd8\xffimage",
                    headers={"content-type": "image/jpeg"},
                )
                self.assertEqual(photo.status_code, 200)
                admin.post("/api/platform/organizations", json={
                    "name": "Other Service", "city": None, "owner_name": "Other Owner",
                    "username": "other-owner", "password": "other-password", "demo": False,
                })
                other = TestClient(pwa.app, base_url="https://testserver")
                other.post("/api/login", json={"username": "other-owner", "password": "other-password"})
                self.assertEqual(admin.get(photo.json()["url"]).status_code, 200)
                self.assertEqual(other.get(photo.json()["url"]).status_code, 404)

    def test_login_rate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.add_or_update_user(9501, "Owner", None)
            environment = {
                "ADMIN_ID": "9501", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                client = TestClient(pwa.app, base_url="https://rate-limit-test")
                pwa._clear_login_failures("testclient")
                try:
                    for _ in range(pwa.LOGIN_MAX_FAILURES):
                        self.assertEqual(client.post("/api/login", json={"username": "admin", "password": "wrong-password"}).status_code, 401)
                    self.assertEqual(client.post("/api/login", json={"username": "admin", "password": "secret-password"}).status_code, 429)
                finally:
                    pwa._clear_login_failures("testclient")

    def test_staff_activity_tracks_login_and_presence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.add_or_update_user(9601, "Owner", None)
            environment = {
                "ADMIN_ID": "9601", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                owner = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(owner.post("/api/login", json={"username": "admin", "password": "secret-password"}).status_code, 200)
                created = owner.post("/api/settings/staff", json={
                    "username": "mechanic", "password": "mechanic-password",
                    "full_name": "Mechanic", "role": "mechanic",
                })
                self.assertEqual(created.status_code, 201)
                mechanic = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(mechanic.post("/api/login", json={"username": "mechanic", "password": "mechanic-password"}).status_code, 200)
                self.assertEqual(mechanic.post("/api/presence").status_code, 200)
                member = next(item for item in owner.get("/api/settings/staff").json() if item["username"] == "mechanic")
                self.assertTrue(member["online"])
                self.assertEqual(member["logins_today"], 1)
                self.assertIsNotNone(member["last_seen_at"])

    def test_platform_owner_views_service_detail_and_manages_staff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.add_or_update_user(9701, "Platform Owner", None)
            environment = {
                "ADMIN_ID": "9701", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                admin = TestClient(pwa.app, base_url="https://testserver")
                admin.post("/api/login", json={"username": "admin", "password": "secret-password"})
                organization = admin.post("/api/platform/organizations", json={
                    "name": "Managed Service", "city": "Москва", "owner_name": "Owner",
                    "username": "managed-owner", "password": "managed-password", "demo": False,
                }).json()
                created = admin.post(f"/api/platform/organizations/{organization['id']}/staff", json={
                    "username": "managed-mechanic", "password": "mechanic-password",
                    "full_name": "Mechanic", "role": "mechanic",
                })
                self.assertEqual(created.status_code, 201)
                mechanic = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(mechanic.post("/api/login", json={"username": "managed-mechanic", "password": "mechanic-password"}).status_code, 200)
                detail = admin.get(f"/api/platform/organizations/{organization['id']}")
                self.assertEqual(detail.status_code, 200)
                member = next(item for item in detail.json()["staff"] if item["username"] == "managed-mechanic")
                self.assertTrue(member["online"])
                self.assertEqual(member["logins_today"], 1)
                disabled = admin.patch(f"/api/platform/organizations/{organization['id']}/staff/{member['id']}", json={"active": False})
                self.assertEqual(disabled.status_code, 200)
                self.assertFalse(disabled.json()["active"])
                self.assertEqual(mechanic.get("/api/dashboard").status_code, 401)

    def test_platform_owner_creates_demo_service_and_controls_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.sqlite3")
            db.initialize()
            db.add_or_update_user(7001, "Platform Owner", None)
            environment = {
                "ADMIN_ID": "7001",
                "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", db), patch.dict(os.environ, environment):
                admin = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(admin.post("/api/login", json={"username": "admin", "password": "secret-password"}).status_code, 200)
                created = admin.post("/api/platform/organizations", json={
                    "name": "Demo Service", "city": "Ставрополь", "owner_name": "Demo Owner",
                    "username": "demo-owner", "password": "demo-password", "demo": True,
                })
                self.assertEqual(created.status_code, 201)
                self.assertEqual(created.json()["status"], "demo")
                organization_id = created.json()["id"]

                owner = TestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(owner.post("/api/login", json={"username": "demo-owner", "password": "demo-password"}).status_code, 200)
                blocked = admin.post(f"/api/platform/organizations/{organization_id}/access", json={"action": "block"})
                self.assertEqual(blocked.json()["status"], "blocked")
                self.assertEqual(owner.get("/api/dashboard").status_code, 401)
                self.assertEqual(owner.post("/api/login", json={"username": "demo-owner", "password": "demo-password"}).status_code, 401)

                restored = admin.post(f"/api/platform/organizations/{organization_id}/access", json={"action": "activate"})
                self.assertEqual(restored.json()["status"], "active")
                self.assertEqual(owner.post("/api/login", json={"username": "demo-owner", "password": "demo-password"}).status_code, 200)

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
                        content=b"\xff\xd8\xffvehicle-document-image",
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
                        content=b"\xff\xd8\xffsmall-test-image",
                        headers={"content-type": "image/jpeg"},
                    )
                self.assertEqual(photo.status_code, 200)
                self.assertTrue(photo.json()["recognized"])
                self.assertEqual(photo.json()["purchase_cost"], 1000)
                self.assertEqual(photo.json()["markup_profit"], 400)
                self.assertEqual(photo.json()["selling_price"], 1400)
                self.assertEqual(client.get(photo.json()["url"]).content, b"\xff\xd8\xffsmall-test-image")
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

    def test_jwt_refresh_rotation_reuse_and_logout_revocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "auth.sqlite3")
            database.initialize()
            database.add_or_update_user(9901, "Owner", None)
            environment = {
                "ADMIN_ID": "9901", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", database), patch.dict(os.environ, environment):
                browser = FastAPITestClient(pwa.app, base_url="https://testserver")
                login = browser.post("/api/login", json={
                    "username": "admin", "password": "secret-password",
                })
                self.assertEqual(login.status_code, 200)
                access = login.json()["access_token"]
                self.assertEqual(len(access.split(".")), 3)
                self.assertEqual(login.json()["token_type"], "bearer")
                self.assertEqual(login.json()["expires_in"], pwa.ACCESS_TOKEN_SECONDS)
                old_refresh = browser.cookies.get(pwa.COOKIE_NAME)
                self.assertIsNotNone(old_refresh)
                self.assertNotIn(str(old_refresh), str(database.get_refresh_session(pwa._refresh_hash(str(old_refresh)))))
                self.assertEqual(browser.get(
                    "/api/dashboard", headers={"Authorization": f"Bearer {access}"},
                ).status_code, 200)

                rotated = browser.post("/api/refresh")
                self.assertEqual(rotated.status_code, 200)
                new_refresh = browser.cookies.get(pwa.COOKIE_NAME)
                self.assertNotEqual(old_refresh, new_refresh)

                replay = FastAPITestClient(pwa.app, base_url="https://testserver").post(
                    "/api/refresh", headers={"Cookie": f"{pwa.COOKIE_NAME}={old_refresh}"},
                )
                self.assertEqual(replay.status_code, 401)
                self.assertIn("reuse", replay.json()["detail"].lower())
                self.assertEqual(browser.post("/api/refresh").status_code, 401)

                second = FastAPITestClient(pwa.app, base_url="https://testserver")
                relogin = second.post("/api/login", json={
                    "username": "admin", "password": "secret-password",
                })
                second_access = relogin.json()["access_token"]
                self.assertEqual(second.post(
                    "/api/logout", headers={"Authorization": f"Bearer {second_access}"},
                ).status_code, 200)
                self.assertEqual(second.get(
                    "/api/dashboard", headers={"Authorization": f"Bearer {second_access}"},
                ).status_code, 401)

    def test_private_api_rejects_missing_tampered_and_wrong_algorithm_jwt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "auth.sqlite3")
            database.initialize()
            database.add_or_update_user(9902, "Owner", None)
            environment = {
                "ADMIN_ID": "9902", "PWA_ADMIN_USER": "admin",
                "PWA_PASSWORD_HASH": password_hash("secret-password"),
                "PWA_SESSION_SECRET": "s" * 48,
            }
            with patch.object(pwa, "db", database), patch.dict(os.environ, environment):
                client = FastAPITestClient(pwa.app, base_url="https://testserver")
                self.assertEqual(client.get("/api/dashboard").status_code, 401)
                token = client.post("/api/login", json={
                    "username": "admin", "password": "secret-password",
                }).json()["access_token"]
                tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
                self.assertEqual(client.get(
                    "/api/dashboard", headers={"Authorization": f"Bearer {tampered}"},
                ).status_code, 401)
                _, payload, signature = token.split(".")
                none_header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
                self.assertEqual(client.get(
                    "/api/dashboard",
                    headers={"Authorization": f"Bearer {none_header}.{payload}.{signature}"},
                ).status_code, 401)

    def test_every_non_auth_api_route_is_centrally_protected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "auth.sqlite3")
            database.initialize()
            client = FastAPITestClient(pwa.app, base_url="https://testserver")
            public = {"/api/login", "/api/refresh", "/api/logout"}
            values = {
                "account_id": "1", "organization_id": "1", "customer_id": "1",
                "car_id": "1", "appointment_id": "1", "order_id": "1",
                "filename": "x.jpg", "diagnostic_id": "1", "item_key": "x",
                "kind": "customer", "entity_id": "1",
            }
            with patch.object(pwa, "db", database):
                for route in pwa.app.routes:
                    path = getattr(route, "path", "")
                    if not path.startswith("/api/") or path in public:
                        continue
                    concrete = path
                    for name, value in values.items():
                        concrete = concrete.replace("{" + name + "}", value)
                    for method in (getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}:
                        with self.subTest(method=method, path=path):
                            response = client.request(
                                method, concrete,
                                json={} if method in {"POST", "PUT", "PATCH"} else None,
                            )
                            self.assertEqual(response.status_code, 401)
                            self.assertEqual(response.headers.get("www-authenticate"), "Bearer")


if __name__ == "__main__":
    unittest.main()
