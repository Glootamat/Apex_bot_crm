"""SQLite storage for the workshop CRM."""

from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class Car:
    id: int
    user_id: int
    customer_id: int | None
    brand: str
    model: str
    year: int | None
    plate_number: str | None
    vin: str | None
    mileage: int | None
    next_service_date: str | None = None
    next_service_mileage: int | None = None


@dataclass(frozen=True)
class Customer:
    id: int
    user_id: int
    full_name: str
    phone: str | None


@dataclass(frozen=True)
class ServiceOrder:
    id: int
    car_id: int
    description: str
    labor_revenue: int
    parts_cost: int
    parts_revenue: int
    parts_profit: int
    status: str
    created_at: str
    brand: str
    model: str
    plate_number: str | None
    vin: str | None
    mileage: int | None
    customer_name: str | None
    concern: str | None = None
    agreed_amount: int | None = None
    recommendations: str | None = None
    completed_at: str | None = None
    archived_at: str | None = None

    @property
    def profit(self) -> int:
        return self.labor_revenue + self.parts_margin

    @property
    def parts_margin(self) -> int:
        # A saved receipt is a purchase awaiting a selling price. Until markup is
        # chosen it must not turn paid labor into a negative profit.
        if self.parts_revenue == 0:
            return self.parts_profit
        return self.parts_revenue - self.parts_cost + self.parts_profit


@dataclass(frozen=True)
class Report:
    orders: int
    labor_revenue: int
    parts_revenue: int
    parts_cost: int
    parts_profit: int

    @property
    def revenue(self) -> int:
        return self.labor_revenue + self.parts_revenue

    @property
    def profit(self) -> int:
        return self.labor_revenue + self.parts_margin

    @property
    def parts_margin(self) -> int:
        if self.parts_revenue == 0:
            return self.parts_profit
        return self.parts_revenue - self.parts_cost + self.parts_profit


@dataclass(frozen=True)
class CustomerCarOverview:
    car: Car
    orders_total: int
    in_progress: int
    completed: int


@dataclass(frozen=True)
class CustomerOverview:
    customer: Customer
    cars: list[CustomerCarOverview]


@dataclass(frozen=True)
class PartItem:
    id: int
    service_order_id: int
    name: str
    article: str | None
    quantity: float | None
    unit_cost: int | None
    total_cost: int | None
    markup_percent: float | None


@dataclass(frozen=True)
class Receipt:
    id: int
    service_order_id: int
    total_cost: int
    created_at: str


@dataclass(frozen=True)
class ReceiptOverview:
    receipt: Receipt
    brand: str
    model: str
    plate_number: str | None
    customer_name: str | None
    items: list[PartItem]

    @property
    def markup_applied(self) -> bool:
        return bool(self.items) and all(item.markup_percent is not None for item in self.items)


@dataclass(frozen=True)
class AppointmentOverview:
    id: int
    car_id: int
    service_order_id: int | None
    description: str
    starts_at: str
    status: str
    brand: str
    model: str
    plate_number: str | None
    customer_name: str | None
    customer_phone: str | None
    agreed_amount: int | None = None


class Database:
    def __init__(self, path: str | Path = "workshop.sqlite3") -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def normalize_phone(value: str | None) -> str | None:
        if not value:
            return None
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        return digits or None

    @staticmethod
    def normalize_plate(value: str | None) -> str | None:
        return re.sub(r"[^0-9A-ZА-Я]", "", value.upper().replace("Ё", "Е")) if value else None

    @staticmethod
    def _write_audit(
        connection: sqlite3.Connection, user_id: int | None, entity_type: str,
        entity_id: int, action: str, details: str | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO audit_log (user_id, entity_type, entity_id, action, details) VALUES (?, ?, ?, ?, ?)",
            (user_id, entity_type, entity_id, action, details),
        )

    def initialize(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS cars (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    year INTEGER,
                    plate_number TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS service_orders (
                    id INTEGER PRIMARY KEY,
                    car_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    labor_revenue INTEGER NOT NULL DEFAULT 0 CHECK (labor_revenue >= 0),
                    parts_cost INTEGER NOT NULL DEFAULT 0 CHECK (parts_cost >= 0),
                    parts_revenue INTEGER NOT NULL DEFAULT 0 CHECK (parts_revenue >= 0),
                    parts_profit INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    concern TEXT,
                    agreed_amount INTEGER CHECK (agreed_amount IS NULL OR agreed_amount >= 0),
                    recommendations TEXT,
                    completed_at TEXT,
                    archived_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT,
                    phone_normalized TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    archived_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS order_photos (
                    id INTEGER PRIMARY KEY,
                    service_order_id INTEGER NOT NULL,
                    telegram_file_id TEXT NOT NULL,
                    caption TEXT,
                    photo_type TEXT NOT NULL DEFAULT 'work',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS part_items (
                    id INTEGER PRIMARY KEY,
                    service_order_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    article TEXT,
                    quantity REAL,
                    unit_cost INTEGER,
                    total_cost INTEGER,
                    markup_percent REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY,
                    service_order_id INTEGER NOT NULL,
                    total_cost INTEGER NOT NULL CHECK (total_cost >= 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS ai_usage_log (
                    id INTEGER PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS daily_reminders (
                    reminder_date TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS incoming_messages (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    message_id INTEGER,
                    message_text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS appointments (
                    id INTEGER PRIMARY KEY,
                    car_id INTEGER NOT NULL,
                    service_order_id INTEGER,
                    description TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    agreed_amount INTEGER CHECK (agreed_amount IS NULL OR agreed_amount >= 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    important INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(cars)")}
            if "customer_id" not in columns:
                connection.execute("ALTER TABLE cars ADD COLUMN customer_id INTEGER REFERENCES customers(id)")
            if "vin" not in columns:
                connection.execute("ALTER TABLE cars ADD COLUMN vin TEXT")
            if "mileage" not in columns:
                connection.execute("ALTER TABLE cars ADD COLUMN mileage INTEGER")
            if "archived_at" not in columns:
                connection.execute("ALTER TABLE cars ADD COLUMN archived_at TEXT")
            if "plate_normalized" not in columns:
                connection.execute("ALTER TABLE cars ADD COLUMN plate_normalized TEXT")
            if "next_service_date" not in columns:
                connection.execute("ALTER TABLE cars ADD COLUMN next_service_date TEXT")
            if "next_service_mileage" not in columns:
                connection.execute("ALTER TABLE cars ADD COLUMN next_service_mileage INTEGER")
            order_columns = {row["name"] for row in connection.execute("PRAGMA table_info(service_orders)")}
            if "parts_profit" not in order_columns:
                connection.execute("ALTER TABLE service_orders ADD COLUMN parts_profit INTEGER NOT NULL DEFAULT 0")
            if "status" not in order_columns:
                connection.execute("ALTER TABLE service_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'in_progress'")
            for name, declaration in (
                ("concern", "TEXT"),
                ("agreed_amount", "INTEGER"),
                ("recommendations", "TEXT"),
                ("completed_at", "TEXT"),
                ("archived_at", "TEXT"),
            ):
                if name not in order_columns:
                    connection.execute(f"ALTER TABLE service_orders ADD COLUMN {name} {declaration}")
            connection.execute("UPDATE service_orders SET status = 'ready' WHERE status = 'completed'")
            customer_columns = {row["name"] for row in connection.execute("PRAGMA table_info(customers)")}
            if "archived_at" not in customer_columns:
                connection.execute("ALTER TABLE customers ADD COLUMN archived_at TEXT")
            if "phone_normalized" not in customer_columns:
                connection.execute("ALTER TABLE customers ADD COLUMN phone_normalized TEXT")
            photo_columns = {row["name"] for row in connection.execute("PRAGMA table_info(order_photos)")}
            if "photo_type" not in photo_columns:
                connection.execute("ALTER TABLE order_photos ADD COLUMN photo_type TEXT NOT NULL DEFAULT 'work'")
            part_columns = {row["name"] for row in connection.execute("PRAGMA table_info(part_items)")}
            if "markup_percent" not in part_columns:
                connection.execute("ALTER TABLE part_items ADD COLUMN markup_percent REAL")
            if "receipt_id" not in part_columns:
                connection.execute("ALTER TABLE part_items ADD COLUMN receipt_id INTEGER REFERENCES receipts(id) ON DELETE CASCADE")
            if "article" not in part_columns:
                connection.execute("ALTER TABLE part_items ADD COLUMN article TEXT")
            appointment_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(appointments)")
            }
            if "service_order_id" not in appointment_columns:
                connection.execute(
                    "ALTER TABLE appointments ADD COLUMN service_order_id INTEGER REFERENCES service_orders(id) ON DELETE SET NULL"
                )
            if "status" not in appointment_columns:
                connection.execute(
                    "ALTER TABLE appointments ADD COLUMN status TEXT NOT NULL DEFAULT 'scheduled'"
                )
            if "agreed_amount" not in appointment_columns:
                connection.execute("ALTER TABLE appointments ADD COLUMN agreed_amount INTEGER")
            incoming_columns = {row["name"] for row in connection.execute("PRAGMA table_info(incoming_messages)")}
            if "message_id" not in incoming_columns:
                connection.execute("ALTER TABLE incoming_messages ADD COLUMN message_id INTEGER")
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_customers_user_active ON customers(user_id, archived_at);
                CREATE INDEX IF NOT EXISTS idx_customers_phone_normalized ON customers(user_id, phone_normalized);
                CREATE INDEX IF NOT EXISTS idx_cars_user_active ON cars(user_id, archived_at);
                CREATE INDEX IF NOT EXISTS idx_cars_customer ON cars(customer_id);
                CREATE INDEX IF NOT EXISTS idx_cars_plate_normalized ON cars(user_id, plate_normalized);
                CREATE INDEX IF NOT EXISTS idx_orders_car_status ON service_orders(car_id, status, archived_at);
                CREATE INDEX IF NOT EXISTS idx_orders_created ON service_orders(created_at);
                CREATE INDEX IF NOT EXISTS idx_appointments_start_status ON appointments(starts_at, status);
                CREATE INDEX IF NOT EXISTS idx_parts_order ON part_items(service_order_id);
                CREATE INDEX IF NOT EXISTS idx_receipts_order ON receipts(service_order_id);
                CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_chat_cleanup ON chat_messages(created_at, important);
                INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
                """
            )
            for row in connection.execute("SELECT id, phone FROM customers WHERE phone IS NOT NULL"):
                connection.execute(
                    "UPDATE customers SET phone_normalized = ? WHERE id = ?",
                    (self.normalize_phone(row["phone"]), row["id"]),
                )
            for row in connection.execute("SELECT id, plate_number FROM cars WHERE plate_number IS NOT NULL"):
                connection.execute(
                    "UPDATE cars SET plate_normalized = ? WHERE id = ?",
                    (self.normalize_plate(row["plate_number"]), row["id"]),
                )
            connection.commit()
        finally:
            connection.close()

    def add_or_update_user(self, telegram_id: int, full_name: str, username: str | None) -> int:
        connection = self.connect()
        try:
            connection.execute(
                """
                INSERT INTO users (telegram_id, username, full_name)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username, full_name = excluded.full_name
                """,
                (telegram_id, username, full_name),
            )
            row = connection.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            connection.commit()
            return int(row["id"])
        finally:
            connection.close()

    def add_customer(self, user_id: int, full_name: str, phone: str | None = None) -> int:
        connection = self.connect()
        try:
            cursor = connection.execute(
                "INSERT INTO customers (user_id, full_name, phone, phone_normalized) VALUES (?, ?, ?, ?)",
                (user_id, full_name, phone, self.normalize_phone(phone)),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def get_customers_for_telegram_user(self, telegram_id: int) -> list[Customer]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT c.id, c.user_id, c.full_name, c.phone FROM customers AS c
                   JOIN users AS u ON u.id = c.user_id WHERE u.telegram_id = ? AND c.archived_at IS NULL ORDER BY c.id DESC""",
                (telegram_id,),
            ).fetchall()
            return [Customer(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_customer_for_telegram_user(self, telegram_id: int, customer_id: int) -> Customer | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT c.id, c.user_id, c.full_name, c.phone
                   FROM customers c JOIN users u ON u.id = c.user_id
                   WHERE u.telegram_id = ? AND c.id = ? AND c.archived_at IS NULL""",
                (telegram_id, customer_id),
            ).fetchone()
            return Customer(**dict(row)) if row is not None else None
        finally:
            connection.close()

    def claim_daily_reminder(self, reminder_date: str) -> bool:
        """Atomically claim one daily reminder, returning False if already sent."""
        connection = self.connect()
        try:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO daily_reminders (reminder_date) VALUES (?)",
                (reminder_date,),
            )
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def log_incoming_message(self, telegram_id: int, message_text: str, message_id: int | None = None) -> None:
        connection = self.connect()
        try:
            connection.execute(
                "INSERT INTO incoming_messages (telegram_id, message_id, message_text) VALUES (?, ?, ?)",
                (telegram_id, message_id, message_text),
            )
            connection.commit()
        finally:
            connection.close()

    def add_appointment(
        self, car_id: int, description: str, starts_at: str, service_order_id: int | None = None,
        agreed_amount: int | None = None,
    ) -> int:
        connection = self.connect()
        try:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(appointments)")}
            if "ends_at" in columns:
                ends_at = (datetime.fromisoformat(starts_at) + timedelta(hours=1)).isoformat()
                cursor = connection.execute(
                    """INSERT INTO appointments
                       (car_id, service_order_id, description, starts_at, ends_at, agreed_amount)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (car_id, service_order_id, description, starts_at, ends_at, agreed_amount),
                )
            else:
                cursor = connection.execute(
                    """INSERT INTO appointments (car_id, service_order_id, description, starts_at, agreed_amount)
                       VALUES (?, ?, ?, ?, ?)""",
                    (car_id, service_order_id, description, starts_at, agreed_amount),
                )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def get_upcoming_appointments_for_telegram_user(
        self, telegram_id: int, limit: int = 20
    ) -> list[AppointmentOverview]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description, a.starts_at, a.status,
                          c.brand, c.model, c.plate_number, cu.full_name AS customer_name,
                          cu.phone AS customer_phone, a.agreed_amount
                   FROM appointments a
                   JOIN cars c ON c.id = a.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   LEFT JOIN service_orders o ON o.id = a.service_order_id
                   WHERE u.telegram_id = ?
                     AND a.status IN ('scheduled', 'in_progress')
                     AND (a.service_order_id IS NULL OR o.status NOT IN ('ready', 'completed'))
                   ORDER BY a.starts_at LIMIT ?""",
                (telegram_id, limit),
            ).fetchall()
            return [AppointmentOverview(**dict(row)) for row in rows]
        finally:
            connection.close()

    def find_or_add_customer(self, user_id: int, full_name: str, phone: str | None) -> int:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT id, full_name FROM customers WHERE user_id = ? ORDER BY id DESC", (user_id,)
            ).fetchall()
            row = next((item for item in rows if item["full_name"].casefold() == full_name.casefold()), None)
            if row is not None:
                if phone:
                    connection.execute("UPDATE customers SET phone = COALESCE(phone, ?) WHERE id = ?", (phone, row["id"]))
                    connection.commit()
                return int(row["id"])
        finally:
            connection.close()
        return self.add_customer(user_id, full_name, phone)

    def find_customer(self, user_id: int, full_name: str | None, phone: str | None) -> Customer | None:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT id, user_id, full_name, phone FROM customers WHERE user_id = ? ORDER BY id DESC", (user_id,)
            ).fetchall()
            for row in rows:
                if full_name and row["full_name"].casefold() == full_name.casefold():
                    return Customer(**dict(row))
                if phone and row["phone"] and row["phone"].replace(" ", "") == phone.replace(" ", ""):
                    return Customer(**dict(row))
            return None
        finally:
            connection.close()

    def update_customer(self, customer_id: int, full_name: str | None, phone: str | None) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """UPDATE customers SET full_name = COALESCE(?, full_name), phone = COALESCE(?, phone),
                   phone_normalized = COALESCE(?, phone_normalized) WHERE id = ?""",
                (full_name, phone, self.normalize_phone(phone), customer_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_customer_overviews(self, telegram_id: int) -> list[CustomerOverview]:
        connection = self.connect()
        try:
            customer_rows = connection.execute(
                """SELECT c.id, c.user_id, c.full_name, c.phone FROM customers c
                   JOIN users u ON u.id = c.user_id WHERE u.telegram_id = ? AND c.archived_at IS NULL ORDER BY c.id DESC""",
                (telegram_id,),
            ).fetchall()
            result: list[CustomerOverview] = []
            for row in customer_rows:
                customer = Customer(**dict(row))
                car_rows = connection.execute(
                    """SELECT c.id, c.user_id, c.customer_id, c.brand, c.model, c.year, c.plate_number, c.vin, c.mileage,
                              COUNT(o.id) AS orders_total,
                              COALESCE(SUM(CASE WHEN o.status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress,
                              COALESCE(SUM(CASE WHEN o.status IN ('ready', 'completed') THEN 1 ELSE 0 END), 0) AS completed
                       FROM cars c LEFT JOIN service_orders o ON o.car_id = c.id
                       WHERE c.customer_id = ? AND c.archived_at IS NULL GROUP BY c.id ORDER BY c.id DESC""",
                    (customer.id,),
                ).fetchall()
                cars = [
                    CustomerCarOverview(
                        car=Car(**{key: row[key] for key in ("id", "user_id", "customer_id", "brand", "model", "year", "plate_number", "vin", "mileage")} ),
                        orders_total=int(row["orders_total"]), in_progress=int(row["in_progress"]), completed=int(row["completed"]),
                    )
                    for row in car_rows
                ]
                result.append(CustomerOverview(customer, cars))
            return result
        finally:
            connection.close()

    def search(self, telegram_id: int, query: str) -> dict[str, list[dict[str, object]]]:
        """Search client, car and order data without relying on SQLite's limited Unicode collation."""
        needle = query.casefold().replace(" ", "")
        connection = self.connect()
        try:
            customers = [dict(row) for row in connection.execute(
                """SELECT c.id, c.full_name, c.phone FROM customers c JOIN users u ON u.id = c.user_id
                   WHERE u.telegram_id = ? ORDER BY c.id DESC""", (telegram_id,)
            ).fetchall()]
            cars = [dict(row) for row in connection.execute(
                """SELECT c.id, c.brand, c.model, c.plate_number, c.vin, c.mileage, cu.full_name AS customer_name
                   FROM cars c JOIN users u ON u.id = c.user_id LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? ORDER BY c.id DESC""", (telegram_id,)
            ).fetchall()]
            orders = [dict(row) for row in connection.execute(
                """SELECT o.id, o.description, o.status, c.brand, c.model, c.plate_number,
                          cu.full_name AS customer_name,
                          (SELECT GROUP_CONCAT(op.caption, ' ')
                           FROM order_photos op
                           WHERE op.service_order_id = o.id
                             AND op.photo_type = 'work') AS photo_captions
                   FROM service_orders o JOIN cars c ON c.id = o.car_id JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id WHERE u.telegram_id = ? ORDER BY o.id DESC""", (telegram_id,)
            ).fetchall()]
        finally:
            connection.close()

        def matches(values: list[object]) -> bool:
            return any(needle in str(value or "").casefold().replace(" ", "") for value in values)

        return {
            "customers": [row for row in customers if matches([row["full_name"], row["phone"]])][:10],
            "cars": [row for row in cars if matches([row["brand"], row["model"], row["plate_number"], row["vin"], row["customer_name"]])][:10],
            "orders": [row for row in orders if matches([
                row["description"], row["brand"], row["model"], row["plate_number"],
                row["customer_name"], row["photo_captions"],
            ])][:10],
        }

    def log_ai_usage(self, task_type: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """INSERT INTO ai_usage_log (task_type, model, input_tokens, output_tokens, cost_usd)
                   VALUES (?, ?, ?, ?, ?)""",
                (task_type, model, input_tokens, output_tokens, cost_usd),
            )
            connection.commit()
        finally:
            connection.close()

    def get_ai_usage(self, period_sql: str) -> tuple[float, int]:
        connection = self.connect()
        try:
            row = connection.execute(
                f"SELECT COALESCE(SUM(cost_usd), 0) AS cost, COUNT(*) AS requests FROM ai_usage_log WHERE created_at >= {period_sql}"
            ).fetchone()
            return float(row["cost"]), int(row["requests"])
        finally:
            connection.close()

    def add_car(self, user_id: int, brand: str, model: str, year: int | None = None, plate_number: str | None = None, customer_id: int | None = None, vin: str | None = None, mileage: int | None = None, next_service_date: str | None = None, next_service_mileage: int | None = None) -> int:
        connection = self.connect()
        try:
            cursor = connection.execute(
                """INSERT INTO cars (user_id, customer_id, brand, model, year, plate_number, plate_normalized, vin, mileage, next_service_date, next_service_mileage)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, customer_id, brand, model, year, plate_number, self.normalize_plate(plate_number), vin, mileage, next_service_date, next_service_mileage),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def get_cars_for_telegram_user(self, telegram_id: int) -> list[Car]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """
                SELECT cars.id, cars.user_id, cars.customer_id, cars.brand, cars.model, cars.year, cars.plate_number, cars.vin, cars.mileage
                FROM cars JOIN users ON users.id = cars.user_id
                WHERE users.telegram_id = ? ORDER BY cars.id DESC
                """,
                (telegram_id,),
            ).fetchall()
            return [Car(**dict(row)) for row in rows]
        finally:
            connection.close()

    def find_car(self, user_id: int, brand: str, model: str, plate_number: str | None) -> Car | None:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT id, user_id, customer_id, brand, model, year, plate_number, vin, mileage FROM cars WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
            normalized_plate = plate_number.casefold() if plate_number else None
            row = next(
                (
                    item for item in rows
                    if item["brand"].casefold() == brand.casefold()
                    and item["model"].casefold() == model.casefold()
                    and (item["plate_number"].casefold() if item["plate_number"] else None) == normalized_plate
                ),
                None,
            )
            return Car(**dict(row)) if row is not None else None
        finally:
            connection.close()

    def find_car_by_details(self, user_id: int, brand: str | None, model: str | None, plate_number: str | None, vin: str | None) -> Car | None:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT id, user_id, customer_id, brand, model, year, plate_number, vin, mileage FROM cars WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
            if vin:
                found = next((Car(**dict(row)) for row in rows if row["vin"] and row["vin"].casefold() == vin.casefold()), None)
                if found is not None:
                    return found
            if plate_number:
                found = next((Car(**dict(row)) for row in rows if row["plate_number"] and row["plate_number"].casefold() == plate_number.casefold()), None)
                if found is not None:
                    return found
            if brand and model:
                return next((Car(**dict(row)) for row in rows if row["brand"].casefold() == brand.casefold() and row["model"].casefold() == model.casefold()), None)
            return None
        finally:
            connection.close()

    def find_single_car_for_customer(self, user_id: int, customer_id: int) -> Car | None:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT id, user_id, customer_id, brand, model, year, plate_number, vin, mileage
                   FROM cars WHERE user_id = ? AND customer_id = ? ORDER BY id DESC""",
                (user_id, customer_id),
            ).fetchall()
            return Car(**dict(rows[0])) if len(rows) == 1 else None
        finally:
            connection.close()

    def update_car(self, car_id: int, customer_id: int | None, brand: str | None, model: str | None, year: int | None, plate_number: str | None, vin: str | None, mileage: int | None, next_service_date: str | None = None, next_service_mileage: int | None = None) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """UPDATE cars SET customer_id = COALESCE(?, customer_id), brand = COALESCE(?, brand),
                   model = COALESCE(?, model), year = COALESCE(?, year), plate_number = COALESCE(?, plate_number),
                   plate_normalized = COALESCE(?, plate_normalized), vin = COALESCE(?, vin),
                   mileage = COALESCE(?, mileage), next_service_date = COALESCE(?, next_service_date),
                   next_service_mileage = COALESCE(?, next_service_mileage) WHERE id = ?""",
                (customer_id, brand, model, year, plate_number, self.normalize_plate(plate_number), vin, mileage, next_service_date, next_service_mileage, car_id),
            )
            connection.commit()
        finally:
            connection.close()

    def add_service_order(
        self, car_id: int, description: str, labor_revenue: int, parts_cost: int,
        parts_revenue: int, parts_profit: int = 0, concern: str | None = None,
        agreed_amount: int | None = None, recommendations: str | None = None,
    ) -> ServiceOrder:
        connection = self.connect()
        try:
            cursor = connection.execute(
                """INSERT INTO service_orders
                   (car_id, description, labor_revenue, parts_cost, parts_revenue, parts_profit,
                    concern, agreed_amount, recommendations)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (car_id, description, labor_revenue, parts_cost, parts_revenue, parts_profit,
                 concern, agreed_amount, recommendations),
            )
            order_id = int(cursor.lastrowid)
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

    def get_service_order(self, order_id: int) -> ServiceOrder:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT o.id, o.car_id, o.description, o.labor_revenue, o.parts_cost, o.parts_revenue, o.parts_profit, o.status, o.created_at,
                          c.brand, c.model, c.plate_number, c.vin, c.mileage, cu.full_name AS customer_name
                          , o.concern, o.agreed_amount, o.recommendations, o.completed_at, o.archived_at
                   FROM service_orders AS o JOIN cars AS c ON c.id = o.car_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id WHERE o.id = ?""",
                (order_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Service order {order_id} does not exist")
            return ServiceOrder(**dict(row))
        finally:
            connection.close()

    def get_recent_orders_for_telegram_user(self, telegram_id: int, limit: int = 10) -> list[ServiceOrder]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT o.id, o.car_id, o.description, o.labor_revenue, o.parts_cost, o.parts_revenue, o.parts_profit, o.status, o.created_at,
                          c.brand, c.model, c.plate_number, c.vin, c.mileage, cu.full_name AS customer_name
                          , o.concern, o.agreed_amount, o.recommendations, o.completed_at, o.archived_at
                   FROM service_orders AS o JOIN cars AS c ON c.id = o.car_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id JOIN users AS u ON u.id = c.user_id
                   WHERE u.telegram_id = ? AND o.archived_at IS NULL AND c.archived_at IS NULL ORDER BY o.id DESC LIMIT ?""",
                (telegram_id, limit),
            ).fetchall()
            return [ServiceOrder(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_latest_order_for_car(self, car_id: int) -> ServiceOrder | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT id FROM service_orders WHERE car_id = ? ORDER BY id DESC LIMIT 1", (car_id,)).fetchone()
            return self.get_service_order(int(row["id"])) if row is not None else None
        finally:
            connection.close()

    def get_active_orders_for_customer(self, user_id: int, customer_id: int) -> list[ServiceOrder]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT o.id, o.car_id, o.description, o.labor_revenue, o.parts_cost,
                          o.parts_revenue, o.parts_profit, o.status, o.created_at,
                          c.brand, c.model, c.plate_number, c.vin, c.mileage, cu.full_name AS customer_name,
                          o.concern, o.agreed_amount, o.recommendations, o.completed_at, o.archived_at
                   FROM service_orders o
                   JOIN cars c ON c.id = o.car_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE c.user_id = ? AND c.customer_id = ? AND o.status = 'in_progress' AND o.archived_at IS NULL
                   ORDER BY o.id DESC""",
                (user_id, customer_id),
            ).fetchall()
            return [ServiceOrder(**dict(row)) for row in rows]
        finally:
            connection.close()

    def update_service_order(self, order_id: int, description: str | None, labor_revenue: int | None, parts_cost: int | None, parts_revenue: int | None, parts_profit: int | None, add_amounts: bool) -> ServiceOrder:
        connection = self.connect()
        try:
            current = connection.execute("SELECT * FROM service_orders WHERE id = ?", (order_id,)).fetchone()
            if current is None:
                raise ValueError(f"Service order {order_id} does not exist")
            new_description = current["description"] if not description else f"{current['description']}; {description}"
            def value(field: str, incoming: int | None) -> int:
                if incoming is None:
                    return int(current[field])
                return int(current[field]) + incoming if add_amounts else incoming
            connection.execute(
                """UPDATE service_orders SET description = ?, labor_revenue = ?, parts_cost = ?, parts_revenue = ?, parts_profit = ? WHERE id = ?""",
                (new_description, value("labor_revenue", labor_revenue), value("parts_cost", parts_cost), value("parts_revenue", parts_revenue), value("parts_profit", parts_profit), order_id),
            )
            self._write_audit(
                connection, None, "order", order_id, "updated",
                f"description={description!r}; labor={labor_revenue!r}; parts_cost={parts_cost!r}; parts_revenue={parts_revenue!r}; parts_profit={parts_profit!r}",
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

    def set_order_status(self, order_id: int, status: str, user_id: int | None = None) -> ServiceOrder:
        if status == "completed":
            status = "ready"
        if status not in {"planned", "in_progress", "ready"}:
            raise ValueError("Unknown order status")
        connection = self.connect()
        try:
            previous = connection.execute("SELECT status FROM service_orders WHERE id = ?", (order_id,)).fetchone()
            connection.execute(
                "UPDATE service_orders SET status = ?, completed_at = CASE WHEN ? = 'ready' THEN CURRENT_TIMESTAMP ELSE completed_at END WHERE id = ?",
                (status, status, order_id),
            )
            if status == "ready":
                connection.execute(
                    """UPDATE appointments SET status = 'completed'
                       WHERE service_order_id = ? AND status = 'scheduled'""",
                    (order_id,),
                )
            self._write_audit(connection, user_id, "order", order_id, "status_changed", f"{previous['status'] if previous else '?'} -> {status}")
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

    def delete_customer(self, user_id: int, customer_id: int) -> bool:
        connection = self.connect()
        try:
            car_ids = [row["id"] for row in connection.execute("SELECT id FROM cars WHERE user_id = ? AND customer_id = ?", (user_id, customer_id)).fetchall()]
            for car_id in car_ids:
                connection.execute("UPDATE service_orders SET archived_at = CURRENT_TIMESTAMP WHERE car_id = ?", (car_id,))
            connection.executemany("UPDATE cars SET archived_at = CURRENT_TIMESTAMP WHERE id = ?", [(car_id,) for car_id in car_ids])
            cursor = connection.execute("UPDATE customers SET archived_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND archived_at IS NULL", (customer_id, user_id))
            self._write_audit(connection, user_id, "customer", customer_id, "archived")
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def delete_car(self, user_id: int, car_id: int) -> bool:
        connection = self.connect()
        try:
            connection.execute("UPDATE service_orders SET archived_at = CURRENT_TIMESTAMP WHERE car_id = ?", (car_id,))
            cursor = connection.execute("UPDATE cars SET archived_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND archived_at IS NULL", (car_id, user_id))
            self._write_audit(connection, user_id, "car", car_id, "archived")
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def delete_service_order(self, user_id: int, order_id: int) -> bool:
        connection = self.connect()
        try:
            cursor = connection.execute(
                "UPDATE service_orders SET archived_at = CURRENT_TIMESTAMP WHERE id = ? AND archived_at IS NULL AND car_id IN (SELECT id FROM cars WHERE user_id = ?)",
                (order_id, user_id),
            )
            self._write_audit(connection, user_id, "order", order_id, "archived")
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def add_order_photo(
        self,
        service_order_id: int,
        telegram_file_id: str,
        caption: str | None,
        photo_type: str = "work",
    ) -> int:
        if photo_type not in {"work", "receipt"}:
            raise ValueError("Unknown order photo type")
        connection = self.connect()
        try:
            cursor = connection.execute(
                """INSERT INTO order_photos
                   (service_order_id, telegram_file_id, caption, photo_type)
                   VALUES (?, ?, ?, ?)""",
                (service_order_id, telegram_file_id, caption, photo_type),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def count_order_photos(self, service_order_id: int) -> int:
        connection = self.connect()
        try:
            return int(connection.execute(
                """SELECT COUNT(*) FROM order_photos
                   WHERE service_order_id = ? AND photo_type = 'work'""",
                (service_order_id,),
            ).fetchone()[0])
        finally:
            connection.close()

    def get_order_photos(self, service_order_id: int) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT id, telegram_file_id, caption, created_at
                   FROM order_photos
                   WHERE service_order_id = ? AND photo_type = 'work'
                   ORDER BY id""",
                (service_order_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def add_part_items(self, service_order_id: int, items: list[tuple[str, float | None, int | None, int | None]], receipt_id: int | None = None) -> None:
        if not items:
            return
        connection = self.connect()
        try:
            connection.executemany(
                "INSERT INTO part_items (service_order_id, name, article, quantity, unit_cost, total_cost, receipt_id) VALUES (?, ?, NULL, ?, ?, ?, ?)",
                [(service_order_id, name, quantity, unit_cost, total_cost, receipt_id) for name, quantity, unit_cost, total_cost in items],
            )
            connection.commit()
        finally:
            connection.close()

    def add_receipt(self, service_order_id: int, total_cost: int, items: list[tuple[str, str | None, float | None, int | None, int | None]]) -> Receipt:
        connection = self.connect()
        try:
            cursor = connection.execute(
                "INSERT INTO receipts (service_order_id, total_cost) VALUES (?, ?)",
                (service_order_id, total_cost),
            )
            receipt_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO part_items (service_order_id, name, article, quantity, unit_cost, total_cost, receipt_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(service_order_id, name, article, quantity, unit_cost, item_total, receipt_id) for name, article, quantity, unit_cost, item_total in items],
            )
            connection.execute(
                "UPDATE service_orders SET parts_cost = parts_cost + ? WHERE id = ?",
                (total_cost, service_order_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id, service_order_id, total_cost, created_at FROM receipts WHERE id = ?",
                (receipt_id,),
            ).fetchone()
            return Receipt(**dict(row))
        finally:
            connection.close()

    def get_recent_receipts_for_telegram_user(self, telegram_id: int, limit: int = 10) -> list[ReceiptOverview]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT r.id, r.service_order_id, r.total_cost, r.created_at,
                          c.brand, c.model, c.plate_number, cu.full_name AS customer_name
                   FROM receipts r
                   JOIN service_orders o ON o.id = r.service_order_id
                   JOIN cars c ON c.id = o.car_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   JOIN users u ON u.id = c.user_id
                   WHERE u.telegram_id = ?
                   ORDER BY r.id DESC LIMIT ?""",
                (telegram_id, limit),
            ).fetchall()
            result: list[ReceiptOverview] = []
            for row in rows:
                item_rows = connection.execute(
                    """SELECT id, service_order_id, name, article, quantity, unit_cost, total_cost, markup_percent
                       FROM part_items WHERE receipt_id = ? ORDER BY id""",
                    (row["id"],),
                ).fetchall()
                result.append(
                    ReceiptOverview(
                        receipt=Receipt(row["id"], row["service_order_id"], row["total_cost"], row["created_at"]),
                        brand=row["brand"],
                        model=row["model"],
                        plate_number=row["plate_number"],
                        customer_name=row["customer_name"],
                        items=[PartItem(**dict(item)) for item in item_rows],
                    )
                )
            return result
        finally:
            connection.close()

    def update_receipt_total(self, user_id: int, receipt_id: int, total_cost: int) -> bool:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT r.total_cost, r.service_order_id FROM receipts r
                   JOIN service_orders o ON o.id = r.service_order_id
                   JOIN cars c ON c.id = o.car_id
                   WHERE r.id = ? AND c.user_id = ?""",
                (receipt_id, user_id),
            ).fetchone()
            if row is None:
                return False
            difference = total_cost - int(row["total_cost"])
            connection.execute("UPDATE receipts SET total_cost = ? WHERE id = ?", (total_cost, receipt_id))
            connection.execute(
                "UPDATE service_orders SET parts_cost = MAX(0, parts_cost + ?) WHERE id = ?",
                (difference, row["service_order_id"]),
            )
            connection.commit()
            return True
        finally:
            connection.close()

    def delete_receipt(self, user_id: int, receipt_id: int) -> bool:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT r.total_cost, r.service_order_id FROM receipts r
                   JOIN service_orders o ON o.id = r.service_order_id
                   JOIN cars c ON c.id = o.car_id
                   WHERE r.id = ? AND c.user_id = ?""",
                (receipt_id, user_id),
            ).fetchone()
            if row is None:
                return False
            marked_items = connection.execute(
                "SELECT total_cost, markup_percent FROM part_items WHERE receipt_id = ? AND markup_percent IS NOT NULL",
                (receipt_id,),
            ).fetchall()
            receipt_revenue = sum(
                int(item["total_cost"] or 0)
                + int(float(item["total_cost"] or 0) * float(item["markup_percent"]) / 100 + 0.5)
                for item in marked_items
            )
            connection.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
            connection.execute(
                """UPDATE service_orders
                   SET parts_cost = MAX(0, parts_cost - ?),
                       parts_revenue = MAX(0, parts_revenue - ?)
                   WHERE id = ?""",
                (row["total_cost"], receipt_revenue, row["service_order_id"]),
            )
            connection.commit()
            return True
        finally:
            connection.close()

    def get_part_items(self, service_order_id: int) -> list[PartItem]:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT id, service_order_id, name, article, quantity, unit_cost, total_cost, markup_percent FROM part_items WHERE service_order_id = ? ORDER BY id",
                (service_order_id,),
            ).fetchall()
            return [PartItem(**dict(row)) for row in rows]
        finally:
            connection.close()

    def apply_markup_to_unmarked_parts(self, service_order_id: int, percent: float) -> tuple[int, int, int]:
        """Apply a margin once to receipt-derived positions not marked up before."""
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT id, total_cost FROM part_items WHERE service_order_id = ? AND markup_percent IS NULL AND total_cost IS NOT NULL",
                (service_order_id,),
            ).fetchall()
            purchase_cost = sum(int(row["total_cost"]) for row in rows)
            profit = sum(int(float(row["total_cost"]) * percent / 100 + 0.5) for row in rows)
            if rows:
                connection.execute(
                    "UPDATE part_items SET markup_percent = ? WHERE service_order_id = ? AND markup_percent IS NULL AND total_cost IS NOT NULL",
                    (percent, service_order_id),
                )
                connection.commit()
            return len(rows), purchase_cost, profit
        finally:
            connection.close()

    def apply_markup_to_receipt(self, user_id: int, receipt_id: int, percent: float) -> tuple[int, int, int, int] | None:
        """Apply markup once to one receipt and add its selling price to the order."""
        connection = self.connect()
        try:
            receipt = connection.execute(
                """SELECT r.service_order_id FROM receipts r
                   JOIN service_orders o ON o.id = r.service_order_id
                   JOIN cars c ON c.id = o.car_id
                   WHERE r.id = ? AND c.user_id = ?""",
                (receipt_id, user_id),
            ).fetchone()
            if receipt is None:
                return None
            rows = connection.execute(
                """SELECT id, total_cost FROM part_items
                   WHERE receipt_id = ? AND markup_percent IS NULL AND total_cost IS NOT NULL""",
                (receipt_id,),
            ).fetchall()
            purchase_cost = sum(int(row["total_cost"]) for row in rows)
            markup_profit = sum(int(float(row["total_cost"]) * percent / 100 + 0.5) for row in rows)
            if rows:
                connection.execute(
                    "UPDATE part_items SET markup_percent = ? WHERE receipt_id = ? AND markup_percent IS NULL",
                    (percent, receipt_id),
                )
                connection.execute(
                    "UPDATE service_orders SET parts_revenue = parts_revenue + ? WHERE id = ?",
                    (purchase_cost + markup_profit, receipt["service_order_id"]),
                )
                connection.commit()
            return int(receipt["service_order_id"]), len(rows), purchase_cost, markup_profit
        finally:
            connection.close()

    def get_report_for_telegram_user(self, telegram_id: int) -> Report:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT COUNT(o.id) AS orders, COALESCE(SUM(o.labor_revenue), 0) AS labor_revenue,
                          COALESCE(SUM(o.parts_revenue), 0) AS parts_revenue, COALESCE(SUM(o.parts_cost), 0) AS parts_cost,
                          COALESCE(SUM(o.parts_profit), 0) AS parts_profit
                   FROM service_orders AS o JOIN cars AS c ON c.id = o.car_id JOIN users AS u ON u.id = c.user_id
                   WHERE u.telegram_id = ?""",
                (telegram_id,),
            ).fetchone()
            return Report(**dict(row))
        finally:
            connection.close()

    def start_appointment(self, user_id: int, appointment_id: int) -> ServiceOrder | None:
        """Mark arrival and create the working order from the appointment once."""
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description, a.agreed_amount
                   FROM appointments a JOIN cars c ON c.id = a.car_id
                   WHERE a.id = ? AND c.user_id = ? AND a.status IN ('scheduled', 'in_progress')""",
                (appointment_id, user_id),
            ).fetchone()
            if row is None:
                return None
            order_id = row["service_order_id"]
            if order_id is None:
                cursor = connection.execute(
                    """INSERT INTO service_orders
                       (car_id, description, concern, agreed_amount, labor_revenue, parts_cost, parts_revenue, parts_profit, status)
                       VALUES (?, ?, ?, ?, 0, 0, 0, 0, 'in_progress')""",
                    (row["car_id"], "Работы уточняются", row["description"], row["agreed_amount"]),
                )
                order_id = int(cursor.lastrowid)
                connection.execute(
                    "UPDATE appointments SET service_order_id = ?, status = 'in_progress' WHERE id = ?",
                    (order_id, appointment_id),
                )
                self._write_audit(connection, user_id, "order", order_id, "created_from_appointment", f"appointment #{appointment_id}")
            else:
                connection.execute("UPDATE appointments SET status = 'in_progress' WHERE id = ?", (appointment_id,))
                connection.execute("UPDATE service_orders SET status = 'in_progress' WHERE id = ?", (order_id,))
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(int(order_id))

    def update_order_crm_fields(
        self, order_id: int, user_id: int | None = None, *, concern: str | None = None,
        agreed_amount: int | None = None, recommendations: str | None = None,
    ) -> ServiceOrder:
        connection = self.connect()
        try:
            current = connection.execute(
                "SELECT concern, agreed_amount, recommendations FROM service_orders WHERE id = ?", (order_id,)
            ).fetchone()
            if current is None:
                raise ValueError(f"Service order {order_id} does not exist")
            connection.execute(
                """UPDATE service_orders SET concern = COALESCE(?, concern),
                   agreed_amount = COALESCE(?, agreed_amount), recommendations = COALESCE(?, recommendations)
                   WHERE id = ?""",
                (concern, agreed_amount, recommendations, order_id),
            )
            details = f"concern={concern!r}; agreed_amount={agreed_amount!r}; recommendations={recommendations!r}"
            self._write_audit(connection, user_id, "order", order_id, "crm_fields_updated", details)
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

    def get_car_service_history(self, car_id: int, limit: int = 20) -> list[ServiceOrder]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT o.id, o.car_id, o.description, o.labor_revenue, o.parts_cost,
                          o.parts_revenue, o.parts_profit, o.status, o.created_at,
                          c.brand, c.model, c.plate_number, c.vin, c.mileage,
                          cu.full_name AS customer_name, o.concern, o.agreed_amount,
                          o.recommendations, o.completed_at, o.archived_at
                   FROM service_orders o JOIN cars c ON c.id = o.car_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE o.car_id = ? AND o.archived_at IS NULL ORDER BY o.id DESC LIMIT ?""",
                (car_id, limit),
            ).fetchall()
            return [ServiceOrder(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_audit_log(self, user_id: int, limit: int = 30) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT entity_type, entity_id, action, details, created_at FROM audit_log
                   WHERE user_id = ? OR user_id IS NULL ORDER BY id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()]
        finally:
            connection.close()

    def get_archived(self, user_id: int, limit: int = 30) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT o.id, o.description, o.archived_at, c.brand, c.model, c.plate_number
                   FROM service_orders o JOIN cars c ON c.id = o.car_id
                   WHERE c.user_id = ? AND o.archived_at IS NOT NULL ORDER BY o.archived_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()]
        finally:
            connection.close()

    def count_archived(self, user_id: int, older_than_days: int | None = None) -> dict[str, int]:
        connection = self.connect()
        try:
            age_sql = "" if older_than_days is None else " AND datetime(archived_at) < datetime('now', ?)"
            params: tuple[object, ...] = (user_id,) if older_than_days is None else (user_id, f"-{older_than_days} days")
            orders = connection.execute(
                f"""SELECT COUNT(*) FROM service_orders WHERE archived_at IS NOT NULL
                    AND car_id IN (SELECT id FROM cars WHERE user_id = ?){age_sql}""",
                params,
            ).fetchone()[0]
            cars = connection.execute(
                f"SELECT COUNT(*) FROM cars WHERE user_id = ? AND archived_at IS NOT NULL{age_sql}",
                params,
            ).fetchone()[0]
            customers = connection.execute(
                f"SELECT COUNT(*) FROM customers WHERE user_id = ? AND archived_at IS NOT NULL{age_sql}",
                params,
            ).fetchone()[0]
            return {"orders": int(orders), "cars": int(cars), "customers": int(customers)}
        finally:
            connection.close()

    def purge_archived(self, user_id: int, older_than_days: int | None = None) -> dict[str, int]:
        """Permanently delete archived records, deepest children first."""
        connection = self.connect()
        try:
            age_sql = "" if older_than_days is None else " AND datetime(archived_at) < datetime('now', ?)"
            params: tuple[object, ...] = (user_id,) if older_than_days is None else (user_id, f"-{older_than_days} days")
            order_cursor = connection.execute(
                f"""DELETE FROM service_orders WHERE archived_at IS NOT NULL
                    AND car_id IN (SELECT id FROM cars WHERE user_id = ?){age_sql}""",
                params,
            )
            car_cursor = connection.execute(
                f"""DELETE FROM cars WHERE user_id = ? AND archived_at IS NOT NULL{age_sql}
                    AND NOT EXISTS (SELECT 1 FROM service_orders o WHERE o.car_id = cars.id)""",
                params,
            )
            customer_cursor = connection.execute(
                f"""DELETE FROM customers WHERE user_id = ? AND archived_at IS NOT NULL{age_sql}
                    AND NOT EXISTS (SELECT 1 FROM cars c WHERE c.customer_id = customers.id)""",
                params,
            )
            result = {
                "orders": int(order_cursor.rowcount),
                "cars": int(car_cursor.rowcount),
                "customers": int(customer_cursor.rowcount),
            }
            connection.commit()
            return result
        finally:
            connection.close()

    def get_inactive_customers(self, user_id: int, days: int = 180) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT cu.id, cu.full_name, cu.phone, c.brand, c.model, c.plate_number,
                          MAX(COALESCE(o.completed_at, o.created_at)) AS last_visit
                   FROM customers cu JOIN cars c ON c.customer_id = cu.id
                   LEFT JOIN service_orders o ON o.car_id = c.id AND o.archived_at IS NULL
                   WHERE cu.user_id = ? AND cu.archived_at IS NULL AND c.archived_at IS NULL
                   GROUP BY cu.id, c.id
                   HAVING last_visit IS NULL OR datetime(last_visit) < datetime('now', ?)
                   ORDER BY last_visit""",
                (user_id, f"-{days} days"),
            ).fetchall()]
        finally:
            connection.close()

    def get_due_services(self, user_id: int) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT c.id, c.brand, c.model, c.plate_number, c.mileage,
                          c.next_service_date, c.next_service_mileage, cu.full_name AS customer_name
                   FROM cars c LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE c.user_id = ? AND c.archived_at IS NULL
                     AND ((c.next_service_date IS NOT NULL AND date(c.next_service_date) <= date('now', '+7 days'))
                       OR (c.next_service_mileage IS NOT NULL AND c.mileage IS NOT NULL
                           AND c.mileage >= c.next_service_mileage))
                   ORDER BY c.next_service_date""",
                (user_id,),
            ).fetchall()]
        finally:
            connection.close()

    def remember_chat_message(self, chat_id: int, message_id: int, important: bool = False) -> None:
        connection = self.connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO chat_messages(chat_id, message_id, important) VALUES (?, ?, ?)",
                (chat_id, message_id, int(important)),
            )
            connection.commit()
        finally:
            connection.close()

    def get_disposable_chat_messages(self, chat_id: int) -> list[int]:
        connection = self.connect()
        try:
            return [int(row[0]) for row in connection.execute(
                """SELECT message_id FROM chat_messages WHERE chat_id = ? AND important = 0
                   AND datetime(created_at) >= datetime('now', '-2 days') ORDER BY message_id""",
                (chat_id,),
            ).fetchall()]
        finally:
            connection.close()

    def forget_chat_messages(self, chat_id: int, message_ids: list[int]) -> None:
        if not message_ids:
            return
        connection = self.connect()
        try:
            connection.executemany(
                "DELETE FROM chat_messages WHERE chat_id = ? AND message_id = ?",
                [(chat_id, message_id) for message_id in message_ids],
            )
            connection.commit()
        finally:
            connection.close()
