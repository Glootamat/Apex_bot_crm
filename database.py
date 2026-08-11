"""SQLite storage for the workshop CRM."""

from __future__ import annotations

import sqlite3
import os
import math
from psycopg import IntegrityError as PostgresIntegrityError
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


_SEARCH_TRANSLITERATION = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}

_SEARCH_ALIASES = {
    "tiana": "teana", "kashkay": "qashqai",
    "shevrole": "chevrolet", "henday": "hyundai", "hunday": "hyundai",
    "folksvagen": "volkswagen", "reno": "renault", "shkoda": "skoda",
    "mersedes": "mercedes", "sitroen": "citroen", "pezho": "peugeot",
    "mitsubisi": "mitsubishi", "deu": "daewoo", "dzhili": "geely",
    "cheri": "chery", "bmv": "bmw", "kruz": "cruze", "fokus": "focus",
    "kamri": "camry", "korolla": "corolla", "solyaris": "solaris",
    "vaz": "lada",
}


def _timestamp_expired(value: object) -> bool:
    if not value:
        return False
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment <= datetime.now(timezone.utc)
    except ValueError:
        return False

_SEARCH_STOP_WORDS = {
    "mashina", "avtomobil", "avto", "klient", "klienta", "naydi", "nayti",
    "pokazhi", "poisk", "marka", "model", "nomer", "kartochka", "kartochku",
}

_PLATE_HOMOGLYPHS = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h",
    "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x",
})


def _search_tokens(value: object) -> list[str]:
    text = str(value or "").casefold().replace("ё", "е")
    transliterated = "".join(_SEARCH_TRANSLITERATION.get(char, char) for char in text)
    tokens = re.findall(r"[a-z0-9]+", transliterated)
    return [_SEARCH_ALIASES.get(token, token) for token in tokens]


def _plate_search_key(value: object) -> str:
    text = str(value or "").casefold().translate(_PLATE_HOMOGLYPHS)
    return re.sub(r"[^a-z0-9]", "", text)


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = long_index = differences = 0
    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
            continue
        differences += 1
        if differences > 1:
            return False
        long_index += 1
    return True


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
    parts_source: str | None = None
    mileage_at_visit: int | None = None

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
    no_shows: int
    labor_revenue: int
    parts_revenue: int
    parts_cost: int
    parts_profit: int
    today_profit: int = 0

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
    is_flexible: int = 0
    parts_source: str | None = None


@dataclass(frozen=True)
class AppointmentSaveResult:
    id: int
    created: bool


class Database:
    def __init__(self, path: str | Path = "workshop.sqlite3") -> None:
        database_url = os.getenv("DATABASE_URL", "").strip()
        self.database_url = database_url if database_url.startswith(("postgresql://", "postgres://")) else None
        self.path = Path(path)

    def connect(self):
        if self.database_url:
            from postgres_backend import PostgresConnection
            return PostgresConnection(self.database_url)
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

    def _find_duplicate_appointment(
        self, connection: sqlite3.Connection, car_id: int, description: str,
        starts_at: str, exclude_id: int | None = None,
    ) -> sqlite3.Row | None:
        """Prefer client phones for visit deduplication, then fall back to the car."""
        target_phone_rows = connection.execute(
            """SELECT cu.phone FROM cars c
               JOIN customers cu ON cu.id = c.customer_id
               WHERE c.id = ? AND cu.phone IS NOT NULL
               UNION ALL
               SELECT cp.phone FROM cars c
               JOIN customer_phones cp ON cp.customer_id = c.customer_id
               WHERE c.id = ?""",
            (car_id, car_id),
        ).fetchall()
        target_phones = {
            normalized for row in target_phone_rows
            if (normalized := self.normalize_phone(row["phone"]))
        }
        target_day = datetime.fromisoformat(starts_at).date()
        normalized_description = re.sub(r"\s+", " ", description).strip().casefold()
        params: tuple[object, ...] = () if exclude_id is None else (exclude_id,)
        exclude_sql = "" if exclude_id is None else "AND a.id != ?"
        rows = connection.execute(
            f"""SELECT a.id, a.car_id, a.starts_at, a.description, cu.phone,
                       (SELECT GROUP_CONCAT(cp.phone, '|') FROM customer_phones cp
                        WHERE cp.customer_id = c.customer_id) AS extra_phones
                FROM appointments a
                JOIN cars c ON c.id = a.car_id
                LEFT JOIN customers cu ON cu.id = c.customer_id
                WHERE a.status IN ('scheduled', 'in_progress') {exclude_sql}
                ORDER BY a.id""",
            params,
        ).fetchall()
        for row in rows:
            if int(row["car_id"]) == car_id and str(row["starts_at"]) == starts_at:
                return row
            if datetime.fromisoformat(str(row["starts_at"])).date() != target_day:
                continue
            candidate_description = re.sub(
                r"\s+", " ", str(row["description"])
            ).strip().casefold()
            if candidate_description != normalized_description:
                continue
            if target_phones:
                candidate_values = [row["phone"]]
                if row["extra_phones"]:
                    candidate_values.extend(str(row["extra_phones"]).split("|"))
                candidate_phones = {
                    normalized for value in candidate_values
                    if (normalized := self.normalize_phone(str(value or "")))
                }
                if target_phones & candidate_phones:
                    return row
            elif int(row["car_id"]) == car_id:
                return row
        return None

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

                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    data_owner_user_id INTEGER NOT NULL UNIQUE,
                    city TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    demo_expires_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (data_owner_user_id) REFERENCES users(id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS auth_accounts (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    platform_admin INTEGER NOT NULL DEFAULT 0,
                    password_changed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS organization_memberships (
                    id INTEGER PRIMARY KEY,
                    organization_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                    FOREIGN KEY (account_id) REFERENCES auth_accounts(id) ON DELETE CASCADE,
                    UNIQUE(organization_id, account_id)
                );

                CREATE TABLE IF NOT EXISTS refresh_sessions (
                    id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    organization_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    replaced_by TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT,
                    FOREIGN KEY (account_id) REFERENCES auth_accounts(id) ON DELETE CASCADE,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_refresh_sessions_account
                    ON refresh_sessions(account_id, organization_id);
                CREATE INDEX IF NOT EXISTS idx_refresh_sessions_family
                    ON refresh_sessions(family_id);

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
                    parts_source TEXT,
                    mileage_at_visit INTEGER,
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

                CREATE TABLE IF NOT EXISTS customer_notes (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    note_text TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                    UNIQUE(customer_id, note_text, source)
                );

                CREATE TABLE IF NOT EXISTS customer_phones (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    phone TEXT NOT NULL,
                    phone_normalized TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                    UNIQUE(customer_id, phone_normalized)
                );

                CREATE TABLE IF NOT EXISTS contact_imports (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    source_index INTEGER NOT NULL,
                    customer_id INTEGER NOT NULL,
                    car_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                    FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE SET NULL,
                    UNIQUE(user_id, source_fingerprint, source_index)
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

                CREATE TABLE IF NOT EXISTS supplier_order_imports (
                    id INTEGER PRIMARY KEY,
                    service_order_id INTEGER NOT NULL,
                    supplier TEXT NOT NULL,
                    external_order_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE CASCADE,
                    UNIQUE(service_order_id, supplier, external_order_id)
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
                    parts_source TEXT,
                    archived_at TEXT,
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

                CREATE TABLE IF NOT EXISTS service_message_cards (
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    appointment_id INTEGER,
                    service_order_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, message_id),
                    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS diagnostics (
                    id INTEGER PRIMARY KEY,
                    car_id INTEGER NOT NULL,
                    service_order_id INTEGER,
                    mileage INTEGER,
                    status TEXT NOT NULL DEFAULT 'draft',
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS diagnostic_items (
                    id INTEGER PRIMARY KEY,
                    diagnostic_id INTEGER NOT NULL,
                    section_key TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'unchecked',
                    left_status TEXT,
                    right_status TEXT,
                    comment TEXT,
                    recommendation TEXT,
                    estimated_cost INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (diagnostic_id) REFERENCES diagnostics(id) ON DELETE CASCADE,
                    UNIQUE(diagnostic_id, item_key)
                );

                CREATE TABLE IF NOT EXISTS diagnostic_photos (
                    id INTEGER PRIMARY KEY,
                    diagnostic_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    caption TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (diagnostic_id) REFERENCES diagnostics(id) ON DELETE CASCADE
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
                ("parts_source", "TEXT"),
                ("mileage_at_visit", "INTEGER"),
            ):
                if name not in order_columns:
                    connection.execute(f"ALTER TABLE service_orders ADD COLUMN {name} {declaration}")
            connection.execute("UPDATE service_orders SET status = 'ready' WHERE status = 'completed'")
            connection.execute(
                """UPDATE service_orders
                   SET mileage_at_visit = (SELECT mileage FROM cars WHERE cars.id = service_orders.car_id)
                   WHERE mileage_at_visit IS NULL"""
            )
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
            if "is_flexible" not in appointment_columns:
                connection.execute("ALTER TABLE appointments ADD COLUMN is_flexible INTEGER NOT NULL DEFAULT 0")
            if "parts_source" not in appointment_columns:
                connection.execute("ALTER TABLE appointments ADD COLUMN parts_source TEXT")
            if "archived_at" not in appointment_columns:
                connection.execute("ALTER TABLE appointments ADD COLUMN archived_at TEXT")
            connection.execute(
                """UPDATE appointments SET status = 'completed'
                   WHERE status = 'in_progress' AND service_order_id IN (
                       SELECT id FROM service_orders WHERE status IN ('ready', 'completed')
                   )"""
            )
            incoming_columns = {row["name"] for row in connection.execute("PRAGMA table_info(incoming_messages)")}
            if "message_id" not in incoming_columns:
                connection.execute("ALTER TABLE incoming_messages ADD COLUMN message_id INTEGER")
            organization_columns = {row["name"] for row in connection.execute("PRAGMA table_info(organizations)")}
            if "demo_expires_at" not in organization_columns:
                connection.execute("ALTER TABLE organizations ADD COLUMN demo_expires_at TEXT")
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_customers_user_active ON customers(user_id, archived_at);
                CREATE INDEX IF NOT EXISTS idx_customers_phone_normalized ON customers(user_id, phone_normalized);
                CREATE INDEX IF NOT EXISTS idx_customer_notes_customer ON customer_notes(customer_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_customer_phones_customer ON customer_phones(customer_id);
                CREATE INDEX IF NOT EXISTS idx_customer_phones_normalized ON customer_phones(phone_normalized);
                CREATE INDEX IF NOT EXISTS idx_contact_imports_customer ON contact_imports(customer_id);
                CREATE INDEX IF NOT EXISTS idx_cars_user_active ON cars(user_id, archived_at);
                CREATE INDEX IF NOT EXISTS idx_cars_customer ON cars(customer_id);
                CREATE INDEX IF NOT EXISTS idx_cars_plate_normalized ON cars(user_id, plate_normalized);
                CREATE INDEX IF NOT EXISTS idx_orders_car_status ON service_orders(car_id, status, archived_at);
                CREATE INDEX IF NOT EXISTS idx_orders_created ON service_orders(created_at);
                CREATE INDEX IF NOT EXISTS idx_appointments_start_status ON appointments(starts_at, status);
                CREATE INDEX IF NOT EXISTS idx_parts_order ON part_items(service_order_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_order_photos_unique_file
                    ON order_photos(service_order_id, telegram_file_id, photo_type);
                CREATE INDEX IF NOT EXISTS idx_receipts_order ON receipts(service_order_id);
                CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_chat_cleanup ON chat_messages(created_at, important);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_service_card_appointment
                    ON service_message_cards(chat_id, appointment_id)
                    WHERE appointment_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_service_card_order
                    ON service_message_cards(chat_id, service_order_id)
                    WHERE service_order_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_diagnostics_car ON diagnostics(car_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_diagnostics_order ON diagnostics(service_order_id);
                CREATE INDEX IF NOT EXISTS idx_memberships_account ON organization_memberships(account_id, active);
                CREATE INDEX IF NOT EXISTS idx_memberships_org ON organization_memberships(organization_id, active);
                CREATE INDEX IF NOT EXISTS idx_diagnostic_items_diagnostic ON diagnostic_items(diagnostic_id, section_key);
                INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
                """
            )
            # Archived appointments must not reserve calendar slots.
            connection.execute("DROP INDEX IF EXISTS idx_appointments_unique_active_slot")
            connection.execute(
                """CREATE UNIQUE INDEX idx_appointments_unique_active_slot
                   ON appointments(car_id, starts_at)
                   WHERE status IN ('scheduled', 'in_progress') AND archived_at IS NULL"""
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

    def bootstrap_web_owner(self, username: str, password_hash: str, full_name: str, telegram_id: int) -> dict[str, object]:
        """Create the first organization/account without moving existing CRM records."""
        data_owner_id = self.add_or_update_user(telegram_id, full_name, username)
        connection = self.connect()
        try:
            organization = connection.execute(
                "SELECT id FROM organizations WHERE data_owner_user_id = ?", (data_owner_id,),
            ).fetchone()
            if organization is None:
                cursor = connection.execute(
                    "INSERT INTO organizations (name, data_owner_user_id) VALUES (?, ?)",
                    (os.getenv("PWA_WORKSPACE_NAME", "Apex Auto"), data_owner_id),
                )
                organization_id = int(cursor.lastrowid)
            else:
                organization_id = int(organization["id"])
            account = connection.execute(
                "SELECT id FROM auth_accounts WHERE username = ?", (username.casefold(),),
            ).fetchone()
            if account is None:
                cursor = connection.execute(
                    """INSERT INTO auth_accounts
                       (username, password_hash, full_name, platform_admin, password_changed_at)
                       VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)""",
                    (username.casefold(), password_hash, full_name),
                )
                account_id = int(cursor.lastrowid)
            else:
                account_id = int(account["id"])
            connection.execute(
                """INSERT INTO organization_memberships (organization_id, account_id, role)
                   VALUES (?, ?, 'owner') ON CONFLICT(organization_id, account_id) DO NOTHING""",
                (organization_id, account_id),
            )
            connection.commit()
            return self.get_auth_account(username) or {}
        finally:
            connection.close()

    def get_auth_account(self, username: str) -> dict[str, object] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT a.id, a.username, a.password_hash, a.full_name, a.active,
                          a.platform_admin, a.password_changed_at, m.organization_id, m.role,
                          o.name AS organization_name, o.data_owner_user_id, o.demo_expires_at,
                          u.telegram_id AS data_owner_telegram_id
                   FROM auth_accounts a
                   JOIN organization_memberships m ON m.account_id = a.id AND m.active = 1
                   JOIN organizations o ON o.id = m.organization_id AND o.active = 1
                   JOIN users u ON u.id = o.data_owner_user_id
                   WHERE a.username = ? AND a.active = 1
                   ORDER BY m.id LIMIT 1""",
                (username.strip().casefold(),),
            ).fetchone()
            result = dict(row) if row else None
            return None if result and _timestamp_expired(result.get("demo_expires_at")) else result
        finally:
            connection.close()

    def get_auth_context(self, account_id: int, organization_id: int) -> dict[str, object] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT a.id, a.username, a.full_name, a.active, a.platform_admin,
                          a.password_hash, a.password_changed_at,
                          m.organization_id, m.role, o.name AS organization_name, o.demo_expires_at,
                          o.data_owner_user_id, u.telegram_id AS data_owner_telegram_id
                   FROM auth_accounts a
                   JOIN organization_memberships m ON m.account_id = a.id AND m.active = 1
                   JOIN organizations o ON o.id = m.organization_id AND o.active = 1
                   JOIN users u ON u.id = o.data_owner_user_id
                   WHERE a.id = ? AND m.organization_id = ? AND a.active = 1""",
                (account_id, organization_id),
            ).fetchone()
            result = dict(row) if row else None
            return None if result and _timestamp_expired(result.get("demo_expires_at")) else result
        finally:
            connection.close()

    def create_refresh_session(
        self, session_id: str, family_id: str, account_id: int,
        organization_id: int, token_hash: str, expires_at: str,
    ) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """INSERT INTO refresh_sessions
                   (id, family_id, account_id, organization_id, token_hash, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, family_id, account_id, organization_id, token_hash, expires_at),
            )
            connection.commit()
        finally:
            connection.close()

    def get_refresh_session(self, token_hash: str) -> dict[str, object] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT * FROM refresh_sessions WHERE token_hash = ?", (token_hash,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def refresh_family_active(
        self, family_id: str, account_id: int, organization_id: int,
    ) -> bool:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT expires_at FROM refresh_sessions
                   WHERE family_id = ? AND account_id = ? AND organization_id = ?
                     AND revoked_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (family_id, account_id, organization_id),
            ).fetchone()
            if row is None:
                return False
            expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return expires_at > datetime.now(timezone.utc)
        except ValueError:
            return False
        finally:
            connection.close()

    def rotate_refresh_session(
        self, current_id: str, new_id: str, family_id: str, account_id: int,
        organization_id: int, token_hash: str, expires_at: str,
    ) -> bool:
        connection = self.connect()
        try:
            cursor = connection.execute(
                """UPDATE refresh_sessions
                   SET revoked_at = CURRENT_TIMESTAMP, replaced_by = ?, last_used_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND revoked_at IS NULL""",
                (new_id, current_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            connection.execute(
                """INSERT INTO refresh_sessions
                   (id, family_id, account_id, organization_id, token_hash, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_id, family_id, account_id, organization_id, token_hash, expires_at),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def revoke_refresh_session(self, token_hash: str) -> None:
        connection = self.connect()
        try:
            connection.execute(
                "UPDATE refresh_sessions SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP) WHERE token_hash = ?",
                (token_hash,),
            )
            connection.commit()
        finally:
            connection.close()

    def revoke_refresh_family(self, family_id: str) -> None:
        connection = self.connect()
        try:
            connection.execute(
                "UPDATE refresh_sessions SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP) WHERE family_id = ?",
                (family_id,),
            )
            connection.commit()
        finally:
            connection.close()

    def revoke_account_sessions(self, account_id: int) -> None:
        connection = self.connect()
        try:
            connection.execute(
                "UPDATE refresh_sessions SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP) WHERE account_id = ?",
                (account_id,),
            )
            connection.commit()
        finally:
            connection.close()

    def list_staff(self, organization_id: int) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT a.id, a.username, a.full_name, a.active, m.role, m.created_at
                   FROM organization_memberships m JOIN auth_accounts a ON a.id = m.account_id
                   WHERE m.organization_id = ? AND m.active = 1 ORDER BY a.full_name""",
                (organization_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def create_staff(self, organization_id: int, username: str, password_hash: str, full_name: str, role: str) -> int:
        connection = self.connect()
        try:
            cursor = connection.execute(
                "INSERT INTO auth_accounts (username, password_hash, full_name) VALUES (?, ?, ?)",
                (username.strip().casefold(), password_hash, full_name.strip()),
            )
            account_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO organization_memberships (organization_id, account_id, role) VALUES (?, ?, ?)",
                (organization_id, account_id, role),
            )
            connection.commit()
            return account_id
        finally:
            connection.close()

    def update_staff(self, organization_id: int, account_id: int, role: str | None = None, active: bool | None = None, password_hash: str | None = None) -> bool:
        connection = self.connect()
        try:
            membership = connection.execute(
                "SELECT role FROM organization_memberships WHERE organization_id = ? AND account_id = ?",
                (organization_id, account_id),
            ).fetchone()
            if membership is None or membership["role"] == "owner":
                return False
            if role is not None:
                connection.execute(
                    "UPDATE organization_memberships SET role = ? WHERE organization_id = ? AND account_id = ?",
                    (role, organization_id, account_id),
                )
            if active is not None:
                connection.execute("UPDATE auth_accounts SET active = ? WHERE id = ?", (int(active), account_id))
            if password_hash is not None:
                connection.execute(
                    "UPDATE auth_accounts SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (password_hash, account_id),
                )
            connection.commit()
            return True
        finally:
            connection.close()

    def list_organizations(self) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT o.id, o.name, o.city, o.active, o.demo_expires_at, o.created_at,
                          owner.full_name AS owner_name, owner.username AS owner_username,
                          (SELECT COUNT(*) FROM organization_memberships m
                           WHERE m.organization_id = o.id AND m.active = 1) AS employees,
                          (SELECT COUNT(*) FROM service_orders so JOIN cars c ON c.id = so.car_id
                           WHERE c.user_id = o.data_owner_user_id AND so.archived_at IS NULL) AS orders
                   FROM organizations o
                   LEFT JOIN organization_memberships om ON om.organization_id = o.id AND om.role = 'owner' AND om.active = 1
                   LEFT JOIN auth_accounts owner ON owner.id = om.account_id
                   ORDER BY o.id"""
            ).fetchall()
            now = datetime.now(timezone.utc)
            result: list[dict[str, object]] = []
            for row in rows:
                item = dict(row)
                expires_at = item.get("demo_expires_at")
                expires = None
                if expires_at:
                    try:
                        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                        if expires.tzinfo is None:
                            expires = expires.replace(tzinfo=timezone.utc)
                    except ValueError:
                        expires = None
                if not item["active"]:
                    item["status"] = "blocked"
                elif expires is not None and expires <= now:
                    item["status"] = "expired"
                elif expires is not None:
                    item["status"] = "demo"
                else:
                    item["status"] = "active"
                item["demo_days_left"] = max(0, (expires - now).days + 1) if expires is not None else None
                result.append(item)
            return result
        finally:
            connection.close()

    def create_organization(self, name: str, city: str | None, owner_name: str, username: str, password_hash: str, demo_days: int = 7) -> int:
        connection = self.connect()
        try:
            row = connection.execute("SELECT MIN(telegram_id) AS value FROM users").fetchone()
            synthetic_telegram_id = min(-1, int(row["value"] or 0) - 1)
            cursor = connection.execute(
                "INSERT INTO users (telegram_id, username, full_name) VALUES (?, ?, ?)",
                (synthetic_telegram_id, username.strip().casefold(), owner_name.strip()),
            )
            data_owner_id = int(cursor.lastrowid)
            cursor = connection.execute(
                "INSERT INTO organizations (name, data_owner_user_id, city, demo_expires_at) VALUES (?, ?, ?, ?)",
                (name.strip(), data_owner_id, city.strip() if city else None,
                 (datetime.now(timezone.utc) + timedelta(days=demo_days)).isoformat() if demo_days > 0 else None),
            )
            organization_id = int(cursor.lastrowid)
            cursor = connection.execute(
                "INSERT INTO auth_accounts (username, password_hash, full_name) VALUES (?, ?, ?)",
                (username.strip().casefold(), password_hash, owner_name.strip()),
            )
            account_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO organization_memberships (organization_id, account_id, role) VALUES (?, ?, 'owner')",
                (organization_id, account_id),
            )
            connection.commit()
            return organization_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_organization_access(self, organization_id: int, action: str) -> bool:
        connection = self.connect()
        try:
            if action == "block":
                cursor = connection.execute(
                    "UPDATE organizations SET active = 0 WHERE id = ?", (organization_id,)
                )
            elif action == "activate":
                cursor = connection.execute(
                    "UPDATE organizations SET active = 1, demo_expires_at = NULL WHERE id = ?", (organization_id,)
                )
            elif action == "demo":
                cursor = connection.execute(
                    "UPDATE organizations SET active = 1, demo_expires_at = ? WHERE id = ?",
                    ((datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), organization_id),
                )
            else:
                raise ValueError("Неизвестное действие")
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def get_workspace(self, organization_id: int) -> dict[str, object] | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT id, name, city FROM organizations WHERE id = ?", (organization_id,)).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def update_workspace(self, organization_id: int, name: str, city: str | None) -> dict[str, object] | None:
        connection = self.connect()
        try:
            connection.execute("UPDATE organizations SET name = ?, city = ? WHERE id = ?", (name.strip(), city.strip() if city else None, organization_id))
            connection.commit()
        finally:
            connection.close()
        return self.get_workspace(organization_id)

    def update_account_password(self, account_id: int, password_hash: str) -> None:
        connection = self.connect()
        try:
            connection.execute("UPDATE auth_accounts SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP WHERE id = ?", (password_hash, account_id))
            connection.commit()
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

    def get_customer_notes(self, customer_id: int, limit: int = 10) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT note_text, source, created_at FROM customer_notes
                   WHERE customer_id = ? ORDER BY id DESC LIMIT ?""",
                (customer_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def get_customer_phones(self, customer_id: int) -> list[str]:
        connection = self.connect()
        try:
            customer = connection.execute(
                "SELECT phone, phone_normalized FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            if customer is None:
                return []
            phones: list[str] = []
            normalized: set[str] = set()
            if customer["phone"]:
                phones.append(str(customer["phone"]))
                key = str(customer["phone_normalized"] or self.normalize_phone(customer["phone"]) or "")
                normalized.add(key)
            rows = connection.execute(
                """SELECT phone, phone_normalized FROM customer_phones
                   WHERE customer_id = ? ORDER BY id""",
                (customer_id,),
            ).fetchall()
            for row in rows:
                key = str(row["phone_normalized"])
                if key not in normalized:
                    phones.append(str(row["phone"]))
                    normalized.add(key)
            return phones
        finally:
            connection.close()

    def add_customer_phone(self, customer_id: int, phone: str) -> bool:
        normalized = self.normalize_phone(phone)
        if not normalized:
            return False
        connection = self.connect()
        try:
            primary = connection.execute(
                "SELECT phone_normalized, phone FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            if primary is None:
                return False
            primary_normalized = primary["phone_normalized"] or self.normalize_phone(primary["phone"])
            if primary_normalized == normalized:
                return False
            cursor = connection.execute(
                """INSERT OR IGNORE INTO customer_phones (customer_id, phone, phone_normalized)
                   VALUES (?, ?, ?)""",
                (customer_id, phone, normalized),
            )
            connection.commit()
            return cursor.rowcount > 0
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

    def get_recent_incoming_texts(
        self, telegram_id: int, limit: int = 7
    ) -> list[str]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT message_text FROM incoming_messages
                   WHERE telegram_id = ? ORDER BY id DESC LIMIT ?""",
                (telegram_id, limit),
            ).fetchall()
            return [str(row["message_text"]) for row in reversed(rows)]
        finally:
            connection.close()

    def get_crm_snapshot(self, telegram_id: int) -> dict[str, object]:
        """Build a bounded read-only snapshot for semantic CRM questions."""
        connection = self.connect()
        try:
            customers = [dict(row) for row in connection.execute(
                """SELECT cu.id, cu.full_name, cu.phone
                   FROM customers cu JOIN users u ON u.id = cu.user_id
                   WHERE u.telegram_id = ? AND cu.archived_at IS NULL
                   ORDER BY cu.id DESC LIMIT 100""",
                (telegram_id,),
            ).fetchall()]
            cars = [dict(row) for row in connection.execute(
                """SELECT c.id, c.customer_id, c.brand, c.model, c.year, c.plate_number,
                          c.vin, c.mileage, c.next_service_date, c.next_service_mileage,
                          cu.full_name AS customer_name, cu.phone AS customer_phone
                   FROM cars c JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND c.archived_at IS NULL
                   ORDER BY c.id DESC LIMIT 150""",
                (telegram_id,),
            ).fetchall()]
            orders = [dict(row) for row in connection.execute(
                """SELECT o.id, o.car_id, o.status, o.description, o.concern,
                          o.labor_revenue, o.parts_cost, o.parts_revenue, o.parts_source,
                          o.recommendations, o.created_at, o.completed_at,
                          c.brand, c.model, c.plate_number, c.vin,
                          cu.id AS customer_id, cu.full_name AS customer_name, cu.phone,
                          (SELECT GROUP_CONCAT(pi.name, '; ')
                           FROM part_items pi WHERE pi.service_order_id = o.id) AS parts,
                          (SELECT COUNT(*) FROM order_photos op
                           WHERE op.service_order_id = o.id AND op.photo_type = 'work') AS work_photos
                   FROM service_orders o JOIN cars c ON c.id = o.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND o.archived_at IS NULL
                   ORDER BY o.id DESC LIMIT 150""",
                (telegram_id,),
            ).fetchall()]
            appointments = [dict(row) for row in connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description, a.starts_at,
                          a.status, a.is_flexible, c.brand, c.model, c.plate_number,
                          cu.id AS customer_id, cu.full_name AS customer_name, cu.phone
                   FROM appointments a JOIN cars c ON c.id = a.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND c.archived_at IS NULL AND a.archived_at IS NULL
                   ORDER BY a.id DESC LIMIT 150""",
                (telegram_id,),
            ).fetchall()]
            return {
                "customers": customers,
                "cars": cars,
                "orders": orders,
                "appointments": appointments,
            }
        finally:
            connection.close()

    def save_appointment(
        self, car_id: int, description: str, starts_at: str, service_order_id: int | None = None,
        agreed_amount: int | None = None, is_flexible: bool = False,
        parts_source: str | None = None,
    ) -> AppointmentSaveResult:
        connection = self.connect()
        try:
            # Serialize the read/check/write sequence. The unique index below
            # covers an identical time slot; this broader check also catches
            # the same visit when natural-language parsing shifts its time.
            connection.execute("BEGIN IMMEDIATE")
            existing = self._find_duplicate_appointment(
                connection, car_id, description, starts_at
            )
            if existing is not None:
                connection.rollback()
                return AppointmentSaveResult(int(existing["id"]), False)

            columns = {row["name"] for row in connection.execute("PRAGMA table_info(appointments)")}
            if "ends_at" in columns:
                ends_at = (datetime.fromisoformat(starts_at) + timedelta(hours=1)).isoformat()
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO appointments
                       (car_id, service_order_id, description, starts_at, ends_at, agreed_amount, is_flexible, parts_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (car_id, service_order_id, description, starts_at, ends_at, agreed_amount, int(is_flexible), parts_source),
                )
            else:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO appointments (car_id, service_order_id, description, starts_at, agreed_amount, is_flexible, parts_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (car_id, service_order_id, description, starts_at, agreed_amount, int(is_flexible), parts_source),
                )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    """SELECT id FROM appointments
                       WHERE car_id = ? AND starts_at = ? AND archived_at IS NULL
                         AND status IN ('scheduled', 'in_progress')
                       ORDER BY id LIMIT 1""",
                    (car_id, starts_at),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("Appointment insert was ignored without an active duplicate")
                return AppointmentSaveResult(int(existing["id"]), False)
            connection.commit()
            return AppointmentSaveResult(int(cursor.lastrowid), True)
        finally:
            connection.close()

    def add_appointment(
        self, car_id: int, description: str, starts_at: str, service_order_id: int | None = None,
        agreed_amount: int | None = None, is_flexible: bool = False,
        parts_source: str | None = None,
    ) -> int:
        """Backward-compatible appointment creation returning only the record id."""
        return self.save_appointment(
            car_id, description, starts_at, service_order_id, agreed_amount, is_flexible, parts_source
        ).id

    def find_active_appointment_id(self, car_id: int, starts_at: str) -> int | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT id FROM appointments
                   WHERE car_id = ? AND starts_at = ? AND archived_at IS NULL
                     AND status IN ('scheduled', 'in_progress')
                   ORDER BY id LIMIT 1""",
                (car_id, starts_at),
            ).fetchone()
            return int(row["id"]) if row is not None else None
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
                          cu.phone AS customer_phone, a.agreed_amount, a.is_flexible, a.parts_source
                   FROM appointments a
                   JOIN cars c ON c.id = a.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   LEFT JOIN service_orders o ON o.id = a.service_order_id
                   WHERE u.telegram_id = ?
                     AND a.status = 'scheduled' AND a.archived_at IS NULL
                   ORDER BY a.starts_at LIMIT ?""",
                (telegram_id, limit),
            ).fetchall()
            return [AppointmentOverview(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_recent_appointments_for_telegram_user(
        self, telegram_id: int, limit: int = 300
    ) -> list[AppointmentOverview]:
        """Return appointment history for CRM cards, newest visit first."""
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description, a.starts_at,
                          a.status, c.brand, c.model, c.plate_number,
                          cu.full_name AS customer_name, cu.phone AS customer_phone,
                          a.agreed_amount, a.is_flexible, a.parts_source
                   FROM appointments a
                   JOIN cars c ON c.id = a.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND c.archived_at IS NULL AND a.archived_at IS NULL
                   ORDER BY datetime(a.starts_at) DESC, a.id DESC LIMIT ?""",
                (telegram_id, limit),
            ).fetchall()
            return [AppointmentOverview(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_appointment_for_telegram_user(
        self, telegram_id: int, appointment_id: int
    ) -> AppointmentOverview | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description, a.starts_at,
                          a.status, c.brand, c.model, c.plate_number,
                          cu.full_name AS customer_name, cu.phone AS customer_phone,
                          a.agreed_amount, a.is_flexible, a.parts_source
                   FROM appointments a
                   JOIN cars c ON c.id = a.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND a.id = ? AND a.archived_at IS NULL""",
                (telegram_id, appointment_id),
            ).fetchone()
            return AppointmentOverview(**dict(row)) if row is not None else None
        finally:
            connection.close()

    def update_appointment(
        self, user_id: int, appointment_id: int, *, car_id: int | None = None,
        description: str | None = None, starts_at: str | None = None,
        agreed_amount: int | None = None, is_flexible: bool | None = None,
        parts_source: str | None = None, replace_nullable: bool = False,
    ) -> bool:
        connection = self.connect()
        try:
            current = connection.execute(
                """SELECT a.* FROM appointments a JOIN cars c ON c.id = a.car_id
                   WHERE a.id = ? AND c.user_id = ?""",
                (appointment_id, user_id),
            ).fetchone()
            if current is None:
                return False
            target_car_id = car_id if car_id is not None else int(current["car_id"])
            if connection.execute(
                "SELECT 1 FROM cars WHERE id = ? AND user_id = ?", (target_car_id, user_id)
            ).fetchone() is None:
                return False
            target_start = starts_at or str(current["starts_at"])
            target_description = description or str(current["description"])
            duplicate = self._find_duplicate_appointment(
                connection, target_car_id, target_description, target_start,
                exclude_id=appointment_id,
            )
            if duplicate is not None:
                raise ValueError(f"Duplicate active appointment #{duplicate['id']}")
            appointment_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(appointments)")
            }
            nullable_amount = "?" if replace_nullable else "COALESCE(?, agreed_amount)"
            nullable_source = "?" if replace_nullable else "COALESCE(?, parts_source)"
            if "ends_at" in appointment_columns:
                ends_at = (datetime.fromisoformat(target_start) + timedelta(hours=1)).isoformat()
                connection.execute(
                    f"""UPDATE appointments SET car_id = ?, description = ?, starts_at = ?,
                              ends_at = ?, agreed_amount = {nullable_amount},
                              is_flexible = COALESCE(?, is_flexible),
                              parts_source = {nullable_source}
                       WHERE id = ?""",
                    (
                        target_car_id, target_description, target_start, ends_at,
                        agreed_amount, int(is_flexible) if is_flexible is not None else None,
                        parts_source, appointment_id,
                    ),
                )
            else:
                connection.execute(
                    f"""UPDATE appointments SET car_id = ?, description = ?, starts_at = ?,
                              agreed_amount = {nullable_amount},
                              is_flexible = COALESCE(?, is_flexible),
                              parts_source = {nullable_source}
                       WHERE id = ?""",
                    (
                        target_car_id, target_description, target_start, agreed_amount,
                        int(is_flexible) if is_flexible is not None else None,
                        parts_source, appointment_id,
                    ),
                )
            if current["service_order_id"] is not None and target_car_id != int(current["car_id"]):
                connection.execute(
                    "UPDATE service_orders SET car_id = ? WHERE id = ?",
                    (target_car_id, current["service_order_id"]),
                )
            self._write_audit(
                connection, user_id, "appointment", appointment_id, "updated",
                f"car_id={target_car_id}; starts_at={target_start}; description={target_description!r}",
            )
            connection.commit()
            return True
        finally:
            connection.close()

    def get_appointment_for_order(self, service_order_id: int) -> dict[str, object] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT id, starts_at, is_flexible, description, status
                   FROM appointments WHERE service_order_id = ? ORDER BY id LIMIT 1""",
                (service_order_id,),
            ).fetchone()
            return dict(row) if row is not None else None
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

    def find_or_add_customer_by_phone(
        self, user_id: int, phone: str, full_name: str | None = None
    ) -> Customer:
        """Create a provisional customer from a phone number and enrich it with a name later."""
        customer = self.find_customer(user_id, full_name, phone)
        if customer is not None:
            if full_name and customer.full_name != full_name:
                self.update_customer(customer.id, full_name, phone)
                updated = self.find_customer(user_id, full_name, phone)
                assert updated is not None
                return updated
            return customer

        normalized = self.normalize_phone(phone) or phone
        customer_id = self.add_customer(user_id, full_name or f"Клиент +{normalized}", phone)
        created = self.find_customer(user_id, full_name, phone)
        assert created is not None and created.id == customer_id
        return created

    def find_customer(self, user_id: int, full_name: str | None, phone: str | None) -> Customer | None:
        connection = self.connect()
        try:
            normalized_phone = self.normalize_phone(phone)
            if normalized_phone:
                row = connection.execute(
                    """SELECT c.id, c.user_id, c.full_name, c.phone FROM customers c
                       WHERE c.user_id = ? AND c.archived_at IS NULL
                         AND (c.phone_normalized = ? OR EXISTS (
                             SELECT 1 FROM customer_phones cp
                             WHERE cp.customer_id = c.id AND cp.phone_normalized = ?
                         ))
                       ORDER BY c.id DESC LIMIT 1""",
                    (user_id, normalized_phone, normalized_phone),
                ).fetchone()
                if row is not None:
                    return Customer(**dict(row))
            rows = connection.execute(
                """SELECT id, user_id, full_name, phone FROM customers
                   WHERE user_id = ? AND archived_at IS NULL ORDER BY id DESC""", (user_id,)
            ).fetchall()
            for row in rows:
                if full_name and row["full_name"].casefold() == full_name.casefold():
                    return Customer(**dict(row))
            return None
        finally:
            connection.close()

    def find_customer_by_unique_first_name(
        self, user_id: int, first_name: str
    ) -> Customer | None:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT id, user_id, full_name, phone FROM customers
                   WHERE user_id = ? AND archived_at IS NULL ORDER BY id DESC""",
                (user_id,),
            ).fetchall()
            matches = [
                Customer(**dict(row)) for row in rows
                if row["full_name"].split()[0].casefold() == first_name.casefold()
            ]
            return matches[0] if len(matches) == 1 else None
        finally:
            connection.close()

    def update_customer(
        self, customer_id: int, full_name: str | None, phone: str | None,
        *, replace_nullable: bool = False,
    ) -> None:
        connection = self.connect()
        try:
            if replace_nullable:
                connection.execute(
                    """UPDATE customers SET full_name = COALESCE(?, full_name), phone = ?,
                       phone_normalized = ? WHERE id = ?""",
                    (full_name, phone, self.normalize_phone(phone), customer_id),
                )
            else:
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
                    """SELECT c.id, c.user_id, c.customer_id, c.brand, c.model, c.year,
                              c.plate_number, c.vin, c.mileage, c.next_service_date,
                              c.next_service_mileage,
                              COUNT(o.id) AS orders_total,
                              COALESCE(SUM(CASE WHEN o.status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress,
                              COALESCE(SUM(CASE WHEN o.status IN ('ready', 'completed') THEN 1 ELSE 0 END), 0) AS completed
                       FROM cars c LEFT JOIN service_orders o ON o.car_id = c.id
                       WHERE c.customer_id = ? AND c.archived_at IS NULL GROUP BY c.id ORDER BY c.id DESC""",
                    (customer.id,),
                ).fetchall()
                cars = [
                    CustomerCarOverview(
                        car=Car(**{key: row[key] for key in (
                            "id", "user_id", "customer_id", "brand", "model", "year",
                            "plate_number", "vin", "mileage", "next_service_date",
                            "next_service_mileage",
                        )}),
                        orders_total=int(row["orders_total"]), in_progress=int(row["in_progress"]), completed=int(row["completed"]),
                    )
                    for row in car_rows
                ]
                result.append(CustomerOverview(customer, cars))
            return result
        finally:
            connection.close()

    def get_unassigned_cars_for_telegram_user(
        self, telegram_id: int
    ) -> list[dict[str, object]]:
        """Return visible vehicles that are not yet linked to a customer card."""
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT c.id, c.brand, c.model, c.year, c.plate_number, c.vin, c.mileage,
                          COUNT(o.id) AS orders_total,
                          COALESCE(SUM(CASE WHEN o.status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress,
                          COALESCE(SUM(CASE WHEN o.status IN ('ready', 'completed') THEN 1 ELSE 0 END), 0) AS completed,
                          (SELECT so.id FROM service_orders so
                           WHERE so.car_id = c.id AND so.archived_at IS NULL
                           ORDER BY so.id DESC LIMIT 1) AS latest_order_id
                   FROM cars c JOIN users u ON u.id = c.user_id
                   LEFT JOIN service_orders o ON o.car_id = c.id AND o.archived_at IS NULL
                   WHERE u.telegram_id = ? AND c.customer_id IS NULL AND c.archived_at IS NULL
                   GROUP BY c.id ORDER BY c.id DESC""",
                (telegram_id,),
            ).fetchall()]
        finally:
            connection.close()

    def search(self, telegram_id: int, query: str) -> dict[str, list[dict[str, object]]]:
        """Rank token, transliterated, fuzzy and identifier matches across CRM fields."""
        query_tokens = _search_tokens(query)
        meaningful_tokens = [
            token for token in query_tokens if token not in _SEARCH_STOP_WORDS
        ]
        if meaningful_tokens:
            query_tokens = meaningful_tokens
        query_compact = "".join(query_tokens)
        query_digits = re.sub(r"\D", "", query)
        query_plate = _plate_search_key(query)
        connection = self.connect()
        try:
            customers = [dict(row) for row in connection.execute(
                """SELECT c.id, c.user_id, c.full_name, c.phone,
                          (SELECT GROUP_CONCAT(cp.phone, ' ') FROM customer_phones cp
                           WHERE cp.customer_id = c.id) AS extra_phones,
                          (SELECT GROUP_CONCAT(cn.note_text, ' ') FROM customer_notes cn
                           WHERE cn.customer_id = c.id) AS notes
                   FROM customers c JOIN users u ON u.id = c.user_id
                   WHERE u.telegram_id = ? AND c.archived_at IS NULL
                   ORDER BY c.id DESC""", (telegram_id,)
            ).fetchall()]
            cars = [dict(row) for row in connection.execute(
                """SELECT c.id, c.user_id, c.customer_id, c.brand, c.model, c.year,
                          c.plate_number, c.vin, c.mileage, c.next_service_date,
                          c.next_service_mileage,
                          cu.full_name AS customer_name, cu.phone AS customer_phone,
                          (SELECT GROUP_CONCAT(cp.phone, ' ') FROM customer_phones cp
                           WHERE cp.customer_id = cu.id) AS customer_extra_phones,
                          (SELECT GROUP_CONCAT(cn.note_text, ' ') FROM customer_notes cn
                           WHERE cn.customer_id = cu.id) AS customer_notes
                   FROM cars c JOIN users u ON u.id = c.user_id LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND c.archived_at IS NULL
                   ORDER BY c.id DESC""", (telegram_id,)
            ).fetchall()]
            orders = [dict(row) for row in connection.execute(
                """SELECT o.id, o.car_id, o.description, o.status, o.concern, o.agreed_amount,
                          o.recommendations, o.labor_revenue, o.parts_cost,
                          o.parts_revenue, o.parts_profit, o.parts_source,
                          o.created_at, o.completed_at, o.archived_at, o.mileage_at_visit,
                          c.brand, c.model, c.year, c.plate_number, c.vin, c.mileage,
                          c.next_service_date, c.next_service_mileage,
                          cu.full_name AS customer_name, cu.phone AS customer_phone,
                          (SELECT GROUP_CONCAT(cp.phone, ' ') FROM customer_phones cp
                           WHERE cp.customer_id = cu.id) AS customer_extra_phones,
                          (SELECT GROUP_CONCAT(cn.note_text, ' ') FROM customer_notes cn
                           WHERE cn.customer_id = cu.id) AS customer_notes,
                          (SELECT GROUP_CONCAT(op.caption, ' ')
                           FROM order_photos op
                           WHERE op.service_order_id = o.id
                             AND op.photo_type = 'work') AS photo_captions,
                          (SELECT GROUP_CONCAT(
                              pi.name || ' ' || COALESCE(pi.article, '') || ' ' ||
                              COALESCE(pi.quantity, '') || ' ' || COALESCE(pi.unit_cost, '') ||
                              ' ' || COALESCE(pi.total_cost, ''), ' '
                           ) FROM part_items pi
                           WHERE pi.service_order_id = o.id) AS part_details,
                          (SELECT GROUP_CONCAT(r.total_cost, ' ') FROM receipts r
                           WHERE r.service_order_id = o.id) AS receipt_totals
                   FROM service_orders o JOIN cars c ON c.id = o.car_id JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND o.archived_at IS NULL
                   ORDER BY o.id DESC""", (telegram_id,)
            ).fetchall()]
            appointments = [dict(row) for row in connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description,
                          a.starts_at, a.status, c.brand, c.model, c.plate_number,
                          cu.full_name AS customer_name, cu.phone AS customer_phone,
                          a.agreed_amount, a.is_flexible, a.parts_source
                   FROM appointments a
                   JOIN cars c ON c.id = a.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ? AND c.archived_at IS NULL AND a.archived_at IS NULL
                   ORDER BY a.id DESC""", (telegram_id,)
            ).fetchall()]
        finally:
            connection.close()

        def match_score(values: list[object]) -> int | None:
            haystack_tokens = [
                token for value in values for token in _search_tokens(value)
            ]
            if not haystack_tokens:
                return None
            score = 0
            haystack_compact = "".join(haystack_tokens)
            if query_compact and query_compact in haystack_compact:
                score += 100
            digits_match = len(query_digits) >= 4 and any(
                query_digits in re.sub(r"\D", "", str(value or ""))
                for value in values
            )
            if digits_match:
                score += 100
            plate_match = (
                any(char.isdigit() for char in query)
                and len(query_plate) >= 4
                and any(
                query_plate in _plate_search_key(value) for value in values
                )
            )
            if plate_match:
                score += 100

            for query_token in query_tokens:
                if digits_match and query_token.isdigit():
                    continue
                if plate_match and len(query_tokens) == 1:
                    continue
                if query_token.isdigit() and len(query_token) >= 4:
                    # Long numeric identifiers (phones, amounts, mileage, years)
                    # must match their full normalized digit sequence. Matching
                    # one formatted phone segment such as "919" creates noise.
                    return None
                best = 0
                for candidate in haystack_tokens:
                    if query_token == candidate:
                        best = max(best, 30)
                    elif not query_token.isdigit() and min(len(query_token), len(candidate)) >= 3 and (
                        query_token in candidate or candidate in query_token
                    ):
                        best = max(best, 20)
                    elif (
                        not query_token.isdigit()
                        and len(query_token) >= 4 and len(candidate) >= 4
                        and _edit_distance_at_most_one(query_token, candidate)
                    ):
                        best = max(best, 10)
                if best == 0:
                    return None
                score += best
            return score or None

        def ranked(
            rows: list[dict[str, object]],
            values_for: Callable[[dict[str, object]], list[object]],
        ) -> list[dict[str, object]]:
            matches: list[tuple[int, int, dict[str, object]]] = []
            for row in rows:
                values = values_for(row)
                score = match_score(values)
                if score is not None:
                    matches.append((score, int(row["id"]), row))
            matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return [row for _, _, row in matches[:10]]

        def order_search_values(row: dict[str, object]) -> list[object]:
            status_alias = {
                "in_progress": "в работе активный",
                "ready": "готов выполнен закрыт",
                "completed": "готов выполнен закрыт",
                "no_show": "не приехал неявка",
            }.get(str(row["status"]), "")
            parts_source_alias = {
                "customer": "запчасти клиента клиентские",
                "workshop": "запчасти сервиса наши",
            }.get(str(row["parts_source"]), "")
            return [
                row["id"], row["description"], row["status"], status_alias,
                row["concern"], row["agreed_amount"], row["recommendations"],
                row["labor_revenue"], row["parts_cost"], row["parts_revenue"],
                row["parts_profit"], row["parts_source"], parts_source_alias,
                row["created_at"], row["completed_at"], row["mileage_at_visit"],
                row["brand"], row["model"], row["year"], row["plate_number"],
                row["vin"], row["mileage"], row["next_service_date"],
                row["next_service_mileage"], row["customer_name"],
                row["customer_phone"], row["customer_extra_phones"],
                row["customer_notes"], row["photo_captions"],
                row["part_details"], row["receipt_totals"],
            ]

        ranked_orders = ranked(orders, order_search_values)
        for row in ranked_orders:
            parts_margin = (
                int(row["parts_profit"] or 0)
                if int(row["parts_revenue"] or 0) == 0
                else int(row["parts_revenue"] or 0) - int(row["parts_cost"] or 0)
                     + int(row["parts_profit"] or 0)
            )
            row["profit"] = int(row["labor_revenue"] or 0) + parts_margin
        return {
            "customers": ranked(customers, lambda row: [
                row["full_name"], row["phone"], row["extra_phones"], row["notes"],
            ]),
            "cars": ranked(cars, lambda row: [
                row["brand"], row["model"], row["year"], row["plate_number"],
                row["vin"], row["mileage"], row["next_service_date"],
                row["next_service_mileage"], row["customer_name"],
                row["customer_phone"], row["customer_extra_phones"],
                row["customer_notes"],
            ]),
            "orders": ranked_orders,
            "appointments": ranked(appointments, lambda row: [
                row["description"], row["starts_at"], row["status"],
                row["brand"], row["model"], row["plate_number"],
                row["customer_name"], row["customer_phone"],
            ]),
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

    def get_ai_usage_summary(self, days: int | None) -> dict[str, object]:
        connection = self.connect()
        try:
            where = "" if not days else " WHERE created_at >= datetime('now', ?)"
            params: tuple[object, ...] = () if not days else (f"-{days - 1} days",)
            total = connection.execute(
                f"SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd, COUNT(*) AS requests, "
                f"COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens "
                f"FROM ai_usage_log{where}", params,
            ).fetchone()
            by_task = connection.execute(
                f"SELECT task_type, model, COUNT(*) AS requests, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
                f"COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens "
                f"FROM ai_usage_log{where} GROUP BY task_type, model ORDER BY cost_usd DESC", params,
            ).fetchall()
            daily = connection.execute(
                f"SELECT substr(created_at, 1, 10) AS date, COALESCE(SUM(cost_usd), 0) AS cost_usd "
                f"FROM ai_usage_log{where} GROUP BY substr(created_at, 1, 10) ORDER BY date", params,
            ).fetchall()
            return {
                "cost_usd": float(total["cost_usd"]), "requests": int(total["requests"]),
                "input_tokens": int(total["input_tokens"]), "output_tokens": int(total["output_tokens"]),
                "by_task": [dict(row) for row in by_task],
                "daily": [dict(row) for row in daily],
            }
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
                WHERE users.telegram_id = ? AND cars.archived_at IS NULL ORDER BY cars.id DESC
                """,
                (telegram_id,),
            ).fetchall()
            return [Car(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_car_for_user(self, user_id: int, car_id: int) -> Car | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT id, user_id, customer_id, brand, model, year, plate_number,
                          vin, mileage, next_service_date, next_service_mileage
                   FROM cars WHERE user_id = ? AND id = ? AND archived_at IS NULL""",
                (user_id, car_id),
            ).fetchone()
            return Car(**dict(row)) if row is not None else None
        finally:
            connection.close()

    def reassign_order_car(self, user_id: int, order_id: int, car_id: int) -> ServiceOrder:
        connection = self.connect()
        try:
            owned_car = connection.execute(
                "SELECT 1 FROM cars WHERE id = ? AND user_id = ? AND archived_at IS NULL",
                (car_id, user_id),
            ).fetchone()
            order = connection.execute(
                """SELECT o.car_id FROM service_orders o JOIN cars c ON c.id = o.car_id
                   WHERE o.id = ? AND c.user_id = ? AND o.archived_at IS NULL""",
                (order_id, user_id),
            ).fetchone()
            if owned_car is None or order is None:
                raise ValueError("Order or car does not exist")
            connection.execute(
                "UPDATE service_orders SET car_id = ? WHERE id = ?", (car_id, order_id)
            )
            connection.execute(
                "UPDATE appointments SET car_id = ? WHERE service_order_id = ?",
                (car_id, order_id),
            )
            self._write_audit(
                connection, user_id, "order", order_id, "car_reassigned",
                f"car_id={order['car_id']} -> {car_id}",
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

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
                "SELECT id, user_id, customer_id, brand, model, year, plate_number, vin, mileage FROM cars WHERE user_id = ? AND archived_at IS NULL ORDER BY id DESC",
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
                matches = [
                    Car(**dict(row)) for row in rows
                    if row["brand"].casefold() == brand.casefold()
                    and row["model"].casefold() == model.casefold()
                ]
                return matches[0] if len(matches) == 1 else None
            return None
        finally:
            connection.close()

    def find_customer_car_by_details(
        self, user_id: int, customer_id: int, brand: str | None,
        model: str | None, plate_number: str | None, vin: str | None,
    ) -> Car | None:
        """Find a car only inside one customer card, never by another owner's model."""
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT id, user_id, customer_id, brand, model, year,
                          plate_number, vin, mileage
                   FROM cars
                   WHERE user_id = ? AND customer_id = ? AND archived_at IS NULL
                   ORDER BY id DESC""",
                (user_id, customer_id),
            ).fetchall()
            if vin:
                match = next(
                    (row for row in rows if row["vin"] and row["vin"].casefold() == vin.casefold()),
                    None,
                )
                if match is not None:
                    return Car(**dict(match))
            if plate_number:
                match = next(
                    (
                        row for row in rows
                        if row["plate_number"]
                        and row["plate_number"].casefold() == plate_number.casefold()
                    ),
                    None,
                )
                if match is not None:
                    return Car(**dict(match))
            if brand and model:
                matches = [
                    Car(**dict(row)) for row in rows
                    if row["brand"].casefold() == brand.casefold()
                    and row["model"].casefold() == model.casefold()
                ]
                return matches[0] if len(matches) == 1 else None
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

    def update_car(self, car_id: int, customer_id: int | None, brand: str | None, model: str | None, year: int | None, plate_number: str | None, vin: str | None, mileage: int | None, next_service_date: str | None = None, next_service_mileage: int | None = None, *, replace_nullable: bool = False) -> None:
        connection = self.connect()
        try:
            if replace_nullable:
                connection.execute(
                    """UPDATE cars SET customer_id = ?, brand = COALESCE(?, brand),
                       model = COALESCE(?, model), year = ?, plate_number = ?,
                       plate_normalized = ?, vin = ?, mileage = ?,
                       next_service_date = COALESCE(?, next_service_date),
                       next_service_mileage = COALESCE(?, next_service_mileage) WHERE id = ?""",
                    (customer_id, brand, model, year, plate_number, self.normalize_plate(plate_number), vin, mileage, next_service_date, next_service_mileage, car_id),
                )
            else:
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
        parts_source: str | None = None,
    ) -> ServiceOrder:
        connection = self.connect()
        try:
            cursor = connection.execute(
                """INSERT INTO service_orders
                   (car_id, description, labor_revenue, parts_cost, parts_revenue, parts_profit,
                    concern, agreed_amount, recommendations, parts_source, mileage_at_visit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, (SELECT mileage FROM cars WHERE id = ?))""",
                (car_id, description, labor_revenue, parts_cost, parts_revenue, parts_profit,
                 concern, agreed_amount, recommendations, parts_source, car_id),
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
                          , o.concern, o.agreed_amount, o.recommendations, o.completed_at, o.archived_at,
                          o.parts_source, o.mileage_at_visit
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
                          , o.concern, o.agreed_amount, o.recommendations, o.completed_at, o.archived_at, o.parts_source
                   FROM service_orders AS o JOIN cars AS c ON c.id = o.car_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id JOIN users AS u ON u.id = c.user_id
                   WHERE u.telegram_id = ? AND o.archived_at IS NULL AND c.archived_at IS NULL ORDER BY o.id DESC LIMIT ?""",
                (telegram_id, limit),
            ).fetchall()
            return [ServiceOrder(**dict(row)) for row in rows]
        finally:
            connection.close()

    def get_completed_orders_for_telegram_user(
        self, telegram_id: int, days: int
    ) -> list[ServiceOrder]:
        if days not in {1, 3, 7}:
            raise ValueError("Completed-order period must be 1, 3 or 7 days")
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT o.id, o.car_id, o.description, o.labor_revenue,
                          o.parts_cost, o.parts_revenue, o.parts_profit, o.status,
                          o.created_at, c.brand, c.model, c.plate_number, c.vin,
                          c.mileage, cu.full_name AS customer_name, o.concern,
                          o.agreed_amount, o.recommendations, o.completed_at,
                          o.archived_at, o.parts_source, o.mileage_at_visit
                   FROM service_orders o
                   JOIN cars c ON c.id = o.car_id
                   JOIN users u ON u.id = c.user_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE u.telegram_id = ?
                     AND o.status IN ('ready', 'completed')
                     AND o.archived_at IS NULL AND c.archived_at IS NULL
                     AND date(o.completed_at, 'localtime') >= date(
                         'now', 'localtime', ?
                     )
                   ORDER BY o.completed_at DESC, o.id DESC""",
                (telegram_id, f"-{days - 1} days"),
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
                          o.concern, o.agreed_amount, o.recommendations, o.completed_at, o.archived_at, o.parts_source
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
            current_description = str(current["description"] or "").strip()
            placeholder = current_description.casefold() == "работы уточняются"
            if not description:
                new_description = current_description
            elif placeholder or not current_description or not add_amounts:
                new_description = description
            elif description.casefold().strip(" .") in current_description.casefold():
                new_description = current_description
            else:
                new_description = f"{current_description}; {description}"
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

    def update_order_parts_source(
        self, order_id: int, parts_source: str | None, user_id: int | None = None
    ) -> ServiceOrder:
        if parts_source is not None and parts_source not in {"customer", "workshop"}:
            raise ValueError("Unknown parts source")
        connection = self.connect()
        try:
            connection.execute(
                "UPDATE service_orders SET parts_source = ? WHERE id = ?",
                (parts_source, order_id),
            )
            self._write_audit(
                connection, user_id, "order", order_id, "parts_source_changed", parts_source
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
                       WHERE service_order_id = ? AND status IN ('scheduled', 'in_progress')""",
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
                connection.execute("UPDATE appointments SET archived_at = CURRENT_TIMESTAMP WHERE car_id = ? AND archived_at IS NULL", (car_id,))
            connection.executemany("UPDATE cars SET archived_at = CURRENT_TIMESTAMP WHERE id = ?", [(car_id,) for car_id in car_ids])
            cursor = connection.execute("UPDATE customers SET archived_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND archived_at IS NULL", (customer_id, user_id))
            self._write_audit(connection, user_id, "customer", customer_id, "archived")
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def delete_appointment(self, user_id: int, appointment_id: int) -> bool:
        """Move an unstarted preliminary appointment to the trash."""
        connection = self.connect()
        try:
            cursor = connection.execute(
                """UPDATE appointments SET archived_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'scheduled' AND service_order_id IS NULL
                     AND archived_at IS NULL
                     AND car_id IN (SELECT id FROM cars WHERE user_id = ?)""",
                (appointment_id, user_id),
            )
            if cursor.rowcount:
                self._write_audit(connection, user_id, "appointment", appointment_id, "archived")
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def delete_car(self, user_id: int, car_id: int) -> bool:
        connection = self.connect()
        try:
            connection.execute("UPDATE service_orders SET archived_at = CURRENT_TIMESTAMP WHERE car_id = ?", (car_id,))
            connection.execute("UPDATE appointments SET archived_at = CURRENT_TIMESTAMP WHERE car_id = ? AND archived_at IS NULL", (car_id,))
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
            existing = connection.execute(
                """SELECT id FROM order_photos
                   WHERE service_order_id = ? AND telegram_file_id = ? AND photo_type = ?""",
                (service_order_id, telegram_file_id, photo_type),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
            cursor = connection.execute(
                """INSERT OR IGNORE INTO order_photos
                   (service_order_id, telegram_file_id, caption, photo_type)
                   VALUES (?, ?, ?, ?)""",
                (service_order_id, telegram_file_id, caption, photo_type),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    """SELECT id FROM order_photos
                       WHERE service_order_id = ? AND telegram_file_id = ? AND photo_type = ?""",
                    (service_order_id, telegram_file_id, photo_type),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("Photo insert was ignored without a duplicate")
                return int(existing["id"])
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

    def user_owns_order_photo(self, user_id: int, filename: str) -> bool:
        connection = self.connect()
        try:
            return connection.execute(
                """SELECT 1 FROM order_photos op
                   JOIN service_orders o ON o.id = op.service_order_id
                   JOIN cars c ON c.id = o.car_id
                   WHERE op.telegram_file_id = ? AND c.user_id = ?""",
                (f"pwa:{filename}", user_id),
            ).fetchone() is not None
        finally:
            connection.close()

    def user_owns_diagnostic_photo(self, user_id: int, filename: str) -> bool:
        connection = self.connect()
        try:
            return connection.execute(
                """SELECT 1 FROM diagnostic_photos dp
                   JOIN diagnostics d ON d.id = dp.diagnostic_id
                   JOIN cars c ON c.id = d.car_id
                   WHERE dp.filename = ? AND c.user_id = ?""",
                (filename, user_id),
            ).fetchone() is not None
        finally:
            connection.close()

    def get_order_photos_for_telegram_user(
        self, telegram_id: int
    ) -> dict[int, list[dict[str, object]]]:
        """Load all order attachments in one query for the PWA snapshot."""
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT op.id, op.service_order_id, op.telegram_file_id,
                          op.caption, op.photo_type, op.created_at
                   FROM order_photos op
                   JOIN service_orders o ON o.id = op.service_order_id
                   JOIN cars c ON c.id = o.car_id
                   JOIN users u ON u.id = c.user_id
                   WHERE u.telegram_id = ? AND o.archived_at IS NULL
                   ORDER BY op.id""",
                (telegram_id,),
            ).fetchall()
            result: dict[int, list[dict[str, object]]] = {}
            for row in rows:
                item = dict(row)
                result.setdefault(int(item["service_order_id"]), []).append(item)
            return result
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

    def add_catalog_part(
        self, service_order_id: int, name: str, article: str, quantity: int,
        unit_cost: int, markup_percent: float, round_to: int = 0,
    ) -> PartItem:
        """Add a priced catalog item and roll its purchase/sale totals into the order."""
        total_cost = unit_cost * quantity
        raw_unit_sale = unit_cost * (1 + markup_percent / 100)
        unit_sale = math.ceil(raw_unit_sale / round_to) * round_to if round_to else round(raw_unit_sale)
        sale_total = unit_sale * quantity
        connection = self.connect()
        try:
            cursor = connection.execute(
                """INSERT INTO part_items
                   (service_order_id, name, article, quantity, unit_cost, total_cost, markup_percent)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (service_order_id, name, article, quantity, unit_cost, total_cost, markup_percent),
            )
            connection.execute(
                """UPDATE service_orders
                   SET parts_cost = parts_cost + ?, parts_revenue = parts_revenue + ?, parts_source = 'workshop'
                   WHERE id = ?""",
                (total_cost, sale_total, service_order_id),
            )
            connection.commit()
            row = connection.execute(
                """SELECT id, service_order_id, name, article, quantity, unit_cost,
                          total_cost, markup_percent FROM part_items WHERE id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
            assert row is not None
            return PartItem(**dict(row))
        finally:
            connection.close()

    def imported_supplier_order_ids(self, service_order_id: int, supplier: str) -> set[str]:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT external_order_id FROM supplier_order_imports WHERE service_order_id = ? AND supplier = ?",
                (service_order_id, supplier),
            ).fetchall()
            return {str(row["external_order_id"]) for row in rows}
        finally:
            connection.close()

    def import_supplier_order(
        self, service_order_id: int, supplier: str, external_order_id: str,
        parts: list[tuple[str, str, int, int]], markup_percent: float, round_to: int = 50,
    ) -> tuple[int, int, int]:
        connection = self.connect()
        try:
            if connection.execute(
                "SELECT 1 FROM supplier_order_imports WHERE service_order_id = ? AND supplier = ? AND external_order_id = ?",
                (service_order_id, supplier, external_order_id),
            ).fetchone():
                raise ValueError("supplier order already imported")
            purchase_total = 0
            sale_total = 0
            for name, article, quantity, unit_cost in parts:
                quantity = max(1, int(quantity))
                unit_cost = int(unit_cost)
                total_cost = unit_cost * quantity
                unit_sale = math.ceil((unit_cost * (1 + markup_percent / 100)) / round_to) * round_to
                connection.execute(
                    """INSERT INTO part_items
                       (service_order_id, name, article, quantity, unit_cost, total_cost, markup_percent)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (service_order_id, name, article, quantity, unit_cost, total_cost, markup_percent),
                )
                purchase_total += total_cost
                sale_total += unit_sale * quantity
            connection.execute(
                """UPDATE service_orders SET parts_cost = parts_cost + ?, parts_revenue = parts_revenue + ?,
                       parts_source = 'workshop' WHERE id = ?""",
                (purchase_total, sale_total, service_order_id),
            )
            connection.execute(
                "INSERT INTO supplier_order_imports (service_order_id, supplier, external_order_id) VALUES (?, ?, ?)",
                (service_order_id, supplier, external_order_id),
            )
            connection.commit()
            return len(parts), purchase_total, sale_total
        except Exception:
            connection.rollback()
            raise
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
                """SELECT COUNT(o.id) AS orders,
                          (SELECT COUNT(*) FROM appointments a
                           JOIN cars ac ON ac.id = a.car_id
                           JOIN users au ON au.id = ac.user_id
                           WHERE au.telegram_id = ? AND a.status = 'no_show' AND a.archived_at IS NULL) AS no_shows,
                          COALESCE(SUM(o.labor_revenue), 0) AS labor_revenue,
                          COALESCE(SUM(o.parts_revenue), 0) AS parts_revenue, COALESCE(SUM(o.parts_cost), 0) AS parts_cost,
                          COALESCE(SUM(o.parts_profit), 0) AS parts_profit,
                          COALESCE(SUM(CASE
                            WHEN o.status IN ('ready', 'completed')
                             AND date(o.completed_at, 'localtime') = date('now', 'localtime')
                            THEN o.labor_revenue + CASE
                              WHEN o.parts_revenue = 0 THEN o.parts_profit
                              ELSE o.parts_revenue - o.parts_cost + o.parts_profit
                            END ELSE 0 END), 0) AS today_profit
                   FROM service_orders AS o JOIN cars AS c ON c.id = o.car_id JOIN users AS u ON u.id = c.user_id
                   WHERE u.telegram_id = ? AND o.status != 'no_show' AND o.archived_at IS NULL""",
                (telegram_id, telegram_id),
            ).fetchone()
            return Report(**dict(row))
        finally:
            connection.close()

    def start_appointment(self, user_id: int, appointment_id: int) -> ServiceOrder | None:
        """Mark arrival and create the working order from the appointment once."""
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description, a.agreed_amount, a.parts_source
                   FROM appointments a JOIN cars c ON c.id = a.car_id
                   WHERE a.id = ? AND c.user_id = ? AND a.status IN ('scheduled', 'in_progress')
                     AND a.archived_at IS NULL""",
                (appointment_id, user_id),
            ).fetchone()
            if row is None:
                return None
            order_id = row["service_order_id"]
            if order_id is None:
                cursor = connection.execute(
                    """INSERT INTO service_orders
                       (car_id, description, concern, agreed_amount, labor_revenue, parts_cost,
                        parts_revenue, parts_profit, status, parts_source, mileage_at_visit)
                       VALUES (?, ?, ?, ?, 0, 0, 0, 0, 'in_progress', ?,
                               (SELECT mileage FROM cars WHERE id = ?))""",
                    (
                        row["car_id"], row["description"], row["description"],
                        row["agreed_amount"], row["parts_source"], row["car_id"],
                    ),
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

    def mark_appointment_no_show(self, user_id: int, appointment_id: int) -> ServiceOrder | None:
        """Close a scheduled slot as a no-show and retain a zero-value client history entry."""
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT a.id, a.car_id, a.service_order_id, a.description, a.agreed_amount
                   FROM appointments a JOIN cars c ON c.id = a.car_id
                   WHERE a.id = ? AND c.user_id = ? AND a.status = 'scheduled'
                     AND a.archived_at IS NULL""",
                (appointment_id, user_id),
            ).fetchone()
            if row is None:
                return None

            order_id = row["service_order_id"]
            if order_id is None:
                cursor = connection.execute(
                    """INSERT INTO service_orders
                       (car_id, description, concern, agreed_amount, labor_revenue, parts_cost,
                        parts_revenue, parts_profit, status, mileage_at_visit)
                       VALUES (?, ?, ?, ?, 0, 0, 0, 0, 'no_show',
                               (SELECT mileage FROM cars WHERE id = ?))""",
                    (
                        row["car_id"], "Клиент не приехал", row["description"],
                        row["agreed_amount"], row["car_id"],
                    ),
                )
                order_id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """UPDATE service_orders
                       SET status = 'no_show', labor_revenue = 0, parts_cost = 0,
                           parts_revenue = 0, parts_profit = 0
                       WHERE id = ?""",
                    (order_id,),
                )
            connection.execute(
                "UPDATE appointments SET status = 'no_show', service_order_id = ? WHERE id = ?",
                (order_id, appointment_id),
            )
            self._write_audit(
                connection, user_id, "appointment", appointment_id, "no_show",
                f"service_order #{order_id}",
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

    def update_order_crm_fields(
        self, order_id: int, user_id: int | None = None, *, concern: str | None = None,
        agreed_amount: int | None = None, recommendations: str | None = None,
        replace_nullable: bool = False,
    ) -> ServiceOrder:
        connection = self.connect()
        try:
            current = connection.execute(
                "SELECT concern, agreed_amount, recommendations FROM service_orders WHERE id = ?", (order_id,)
            ).fetchone()
            if current is None:
                raise ValueError(f"Service order {order_id} does not exist")
            if replace_nullable:
                connection.execute(
                    """UPDATE service_orders SET concern = ?, agreed_amount = ?, recommendations = ?
                       WHERE id = ?""",
                    (concern, agreed_amount, recommendations, order_id),
                )
            else:
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
                          o.recommendations, o.completed_at, o.archived_at, o.parts_source,
                          o.mileage_at_visit
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

    def get_trash(self, user_id: int) -> list[dict[str, object]]:
        """Return all recoverable records owned by the user, newest first."""
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT 'customer' AS kind, cu.id, cu.full_name AS title,
                          COALESCE(cu.phone, '') AS subtitle, cu.archived_at
                   FROM customers cu
                   WHERE cu.user_id = ? AND cu.archived_at IS NOT NULL
                   UNION ALL
                   SELECT 'car', c.id, trim(c.brand || ' ' || c.model),
                          COALESCE(c.plate_number, ''), c.archived_at
                   FROM cars c
                   WHERE c.user_id = ? AND c.archived_at IS NOT NULL
                   UNION ALL
                   SELECT 'appointment', a.id, a.description,
                          trim(c.brand || ' ' || c.model), a.archived_at
                   FROM appointments a JOIN cars c ON c.id = a.car_id
                   WHERE c.user_id = ? AND a.archived_at IS NOT NULL
                   UNION ALL
                   SELECT 'order', o.id, o.description,
                          trim(c.brand || ' ' || c.model), o.archived_at
                   FROM service_orders o JOIN cars c ON c.id = o.car_id
                   WHERE c.user_id = ? AND o.archived_at IS NOT NULL
                   ORDER BY archived_at DESC""",
                (user_id, user_id, user_id, user_id),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def restore_archived(self, user_id: int, kind: str, entity_id: int) -> bool:
        """Restore one record and any archived parents required to make it visible."""
        tables = {"customer": "customers", "car": "cars", "appointment": "appointments", "order": "service_orders"}
        if kind not in tables:
            raise ValueError("Unknown archived entity type")
        connection = self.connect()
        try:
            if kind == "customer":
                cursor = connection.execute(
                    "UPDATE customers SET archived_at = NULL WHERE id = ? AND user_id = ? AND archived_at IS NOT NULL",
                    (entity_id, user_id),
                )
            elif kind == "car":
                row = connection.execute("SELECT customer_id FROM cars WHERE id = ? AND user_id = ? AND archived_at IS NOT NULL", (entity_id, user_id)).fetchone()
                if row is None:
                    return False
                if row["customer_id"] is not None:
                    connection.execute("UPDATE customers SET archived_at = NULL WHERE id = ? AND user_id = ?", (row["customer_id"], user_id))
                cursor = connection.execute("UPDATE cars SET archived_at = NULL WHERE id = ? AND user_id = ?", (entity_id, user_id))
            else:
                table = tables[kind]
                row = connection.execute(
                    f"""SELECT x.car_id, c.customer_id FROM {table} x JOIN cars c ON c.id = x.car_id
                        WHERE x.id = ? AND c.user_id = ? AND x.archived_at IS NOT NULL""",
                    (entity_id, user_id),
                ).fetchone()
                if row is None:
                    return False
                if row["customer_id"] is not None:
                    connection.execute("UPDATE customers SET archived_at = NULL WHERE id = ? AND user_id = ?", (row["customer_id"], user_id))
                connection.execute("UPDATE cars SET archived_at = NULL WHERE id = ? AND user_id = ?", (row["car_id"], user_id))
                try:
                    cursor = connection.execute(f"UPDATE {table} SET archived_at = NULL WHERE id = ?", (entity_id,))
                except (sqlite3.IntegrityError, PostgresIntegrityError):
                    connection.rollback()
                    return False
            if cursor.rowcount:
                self._write_audit(connection, user_id, kind, entity_id, "restored")
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def start_diagnostic(
        self, user_id: int, car_id: int, service_order_id: int | None,
        checklist: list[tuple[str, str, str, bool]],
    ) -> dict[str, object] | None:
        """Open the existing draft or create a ready-to-use diagnostic checklist."""
        connection = self.connect()
        try:
            car = connection.execute(
                "SELECT id, mileage FROM cars WHERE id = ? AND user_id = ? AND archived_at IS NULL",
                (car_id, user_id),
            ).fetchone()
            if car is None:
                return None
            if service_order_id is not None and connection.execute(
                """SELECT 1 FROM service_orders o JOIN cars c ON c.id = o.car_id
                   WHERE o.id = ? AND o.car_id = ? AND c.user_id = ? AND o.archived_at IS NULL""",
                (service_order_id, car_id, user_id),
            ).fetchone() is None:
                return None
            if service_order_id is not None:
                # An order has one current diagnostic card. Reopen it even after
                # completion so closing and returning never creates a blank card.
                existing = connection.execute(
                    """SELECT id FROM diagnostics WHERE car_id = ? AND service_order_id = ?
                       ORDER BY id DESC LIMIT 1""",
                    (car_id, service_order_id),
                ).fetchone()
            else:
                existing = connection.execute(
                    """SELECT id FROM diagnostics WHERE car_id = ? AND status = 'draft'
                       AND service_order_id IS NULL ORDER BY id DESC LIMIT 1""",
                    (car_id,),
                ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO diagnostics (car_id, service_order_id, mileage) VALUES (?, ?, ?)",
                    (car_id, service_order_id, car["mileage"]),
                )
                diagnostic_id = int(cursor.lastrowid)
                connection.executemany(
                    """INSERT INTO diagnostic_items
                       (diagnostic_id, section_key, item_key, label, left_status, right_status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (diagnostic_id, section, key, label, "unchecked" if sided else None, "unchecked" if sided else None)
                        for section, key, label, sided in checklist
                    ],
                )
                self._write_audit(connection, user_id, "diagnostic", diagnostic_id, "created")
                connection.commit()
            else:
                diagnostic_id = int(existing["id"])
        finally:
            connection.close()
        return self.get_diagnostic(user_id, diagnostic_id)

    def create_order_from_diagnostic(self, user_id: int, diagnostic_id: int) -> tuple[ServiceOrder, bool] | None:
        """Create and link one safe draft order from diagnostic findings."""
        connection = self.connect()
        try:
            diagnostic = connection.execute(
                """SELECT d.id, d.car_id, d.service_order_id, d.notes
                   FROM diagnostics d JOIN cars c ON c.id = d.car_id
                   WHERE d.id = ? AND c.user_id = ? AND c.archived_at IS NULL""",
                (diagnostic_id, user_id),
            ).fetchone()
            if diagnostic is None:
                return None
            rows = connection.execute(
                """SELECT label, status, left_status, right_status, recommendation,
                          estimated_cost
                   FROM diagnostic_items WHERE diagnostic_id = ? ORDER BY id""",
                (diagnostic_id,),
            ).fetchall()
            issue_statuses = {"attention", "critical"}
            works: list[str] = []
            required_parts: list[str] = []
            labor_revenue = 0
            for row in rows:
                recommendation = str(row["recommendation"] or "").strip()
                label = str(row["label"])
                sides: list[str] = []
                if row["left_status"] in issue_statuses:
                    sides.append("левая сторона")
                if row["right_status"] in issue_statuses:
                    sides.append("правая сторона")
                if sides:
                    side_lines = "\n".join(f"• {side.capitalize()}" for side in sides)
                    works.append(f"{recommendation or label}:\n{side_lines}")
                    required_parts.extend(f"• {label} — {side}" for side in sides)
                elif row["status"] in issue_statuses or recommendation:
                    works.append(recommendation or label)
                    required_parts.append(f"• {label}")
                if (sides or row["status"] in issue_statuses or recommendation) and row["estimated_cost"] is not None:
                    labor_revenue += max(0, int(row["estimated_cost"]))
            # Preserve order while removing identical recommendations.
            works = list(dict.fromkeys(works))
            required_parts = list(dict.fromkeys(required_parts))
            if not works:
                return None
            description = "\n\n".join(works)
            recommendations = "Требуется подобрать запчасти:\n" + "\n".join(required_parts)
            linked_order_id = diagnostic["service_order_id"]
            if linked_order_id is not None:
                linked_order_id = int(linked_order_id)
                expected_concern = f"По результатам диагностики №{diagnostic_id}"
                linked = connection.execute(
                    "SELECT concern FROM service_orders WHERE id = ? AND car_id = ? AND archived_at IS NULL",
                    (linked_order_id, diagnostic["car_id"]),
                ).fetchone()
                # Refresh only orders created by this workflow; never overwrite a manually linked order.
                if linked is not None and linked["concern"] == expected_concern:
                    connection.execute(
                        """UPDATE service_orders
                           SET description = ?, labor_revenue = ?, recommendations = ?
                           WHERE id = ?""",
                        (description, labor_revenue, recommendations, linked_order_id),
                    )
                    self._write_audit(connection, user_id, "service_order", linked_order_id, "synced_from_diagnostic")
                    connection.commit()
                return self.get_service_order(linked_order_id), False
            cursor = connection.execute(
                """INSERT INTO service_orders
                   (car_id, description, labor_revenue, parts_cost, parts_revenue,
                    parts_profit, concern, recommendations, mileage_at_visit)
                   VALUES (?, ?, ?, 0, 0, 0, ?, ?,
                           (SELECT COALESCE(d.mileage, c.mileage) FROM diagnostics d
                            JOIN cars c ON c.id = d.car_id WHERE d.id = ?))""",
                (
                    diagnostic["car_id"], description, labor_revenue,
                    f"По результатам диагностики №{diagnostic_id}",
                    recommendations,
                    diagnostic_id,
                ),
            )
            order_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE diagnostics SET service_order_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND service_order_id IS NULL",
                (order_id, diagnostic_id),
            )
            self._write_audit(connection, user_id, "service_order", order_id, "created_from_diagnostic")
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id), True

    def get_diagnostic(self, user_id: int, diagnostic_id: int) -> dict[str, object] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT d.*, c.brand, c.model, c.year, c.plate_number, c.vin,
                          cu.full_name AS customer_name
                   FROM diagnostics d JOIN cars c ON c.id = d.car_id
                   LEFT JOIN customers cu ON cu.id = c.customer_id
                   WHERE d.id = ? AND c.user_id = ?""",
                (diagnostic_id, user_id),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["items"] = [dict(item) for item in connection.execute(
                """SELECT id, section_key, item_key, label, status, left_status,
                          right_status, comment, recommendation, estimated_cost, updated_at
                   FROM diagnostic_items WHERE diagnostic_id = ? ORDER BY id""",
                (diagnostic_id,),
            ).fetchall()]
            result["photos"] = [dict(photo) for photo in connection.execute(
                "SELECT id, filename, caption, created_at FROM diagnostic_photos WHERE diagnostic_id = ? ORDER BY id",
                (diagnostic_id,),
            ).fetchall()]
            result["order_description"] = None
            result["labor_revenue"] = 0
            result["parts_revenue"] = 0
            result["part_names"] = []
            result["parts"] = []
            if result.get("service_order_id") is not None:
                order = connection.execute(
                    """SELECT description, labor_revenue, parts_revenue
                       FROM service_orders WHERE id = ?""",
                    (result["service_order_id"],),
                ).fetchone()
                if order is not None:
                    result["order_description"] = order["description"]
                    result["labor_revenue"] = int(order["labor_revenue"] or 0)
                    result["parts_revenue"] = int(order["parts_revenue"] or 0)
                part_rows = connection.execute(
                        """SELECT name, article, quantity, unit_cost, total_cost, markup_percent
                           FROM part_items WHERE service_order_id = ? ORDER BY id""",
                        (result["service_order_id"],),
                    ).fetchall()
                result["part_names"] = [str(item["name"]) for item in part_rows]
                result["parts"] = []
                for item in part_rows:
                    part = dict(item)
                    quantity = max(1, int(part.get("quantity") or 1))
                    unit_cost = int(part.get("unit_cost") or 0)
                    markup = part.get("markup_percent")
                    if unit_cost and markup is not None:
                        unit_sale = math.ceil((unit_cost * (1 + float(markup) / 100)) / 50) * 50
                        part["sale_unit"] = unit_sale
                        part["sale_total"] = unit_sale * quantity
                    else:
                        part["sale_unit"] = None
                        part["sale_total"] = None
                    result["parts"].append(part)
            return result
        finally:
            connection.close()

    def list_diagnostics(self, user_id: int, car_id: int | None = None) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            condition = " AND d.car_id = ?" if car_id is not None else ""
            params: tuple[object, ...] = (user_id, car_id) if car_id is not None else (user_id,)
            rows = connection.execute(
                f"""SELECT d.id, d.car_id, d.service_order_id, d.mileage, d.status,
                           d.created_at, d.updated_at, d.completed_at, c.brand, c.model,
                           c.plate_number, c.vin, cu.full_name AS customer_name, cu.phone AS customer_phone,
                           SUM(CASE WHEN di.status != 'unchecked' OR COALESCE(di.left_status, 'unchecked') != 'unchecked' OR COALESCE(di.right_status, 'unchecked') != 'unchecked' THEN 1 ELSE 0 END) AS checked,
                           COUNT(di.id) AS total,
                           SUM(CASE WHEN di.status = 'critical' OR di.left_status = 'critical' OR di.right_status = 'critical' THEN 1 ELSE 0 END) AS critical,
                           SUM(CASE WHEN di.status = 'attention' OR di.left_status = 'attention' OR di.right_status = 'attention' THEN 1 ELSE 0 END) AS attention
                    FROM diagnostics d JOIN cars c ON c.id = d.car_id
                    LEFT JOIN customers cu ON cu.id = c.customer_id
                    LEFT JOIN diagnostic_items di ON di.diagnostic_id = d.id
                    WHERE c.user_id = ?{condition}
                    GROUP BY d.id ORDER BY d.id DESC LIMIT 100""",
                params,
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def update_diagnostic_item(
        self, user_id: int, diagnostic_id: int, item_key: str, **values: object,
    ) -> dict[str, object] | None:
        allowed = {"status", "left_status", "right_status", "comment", "recommendation", "estimated_cost"}
        updates = {key: value for key, value in values.items() if key in allowed}
        for key in ("status", "left_status", "right_status"):
            if key in updates and updates[key] is not None and updates[key] not in {"unchecked", "ok", "attention", "critical"}:
                raise ValueError("Unknown diagnostic status")
        connection = self.connect()
        try:
            if connection.execute(
                """SELECT 1 FROM diagnostics d JOIN cars c ON c.id = d.car_id
                   WHERE d.id = ? AND c.user_id = ?""", (diagnostic_id, user_id)
            ).fetchone() is None:
                return None
            if updates:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                connection.execute(
                    f"UPDATE diagnostic_items SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE diagnostic_id = ? AND item_key = ?",
                    (*updates.values(), diagnostic_id, item_key),
                )
                connection.execute("UPDATE diagnostics SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (diagnostic_id,))
                connection.commit()
            row = connection.execute(
                "SELECT * FROM diagnostic_items WHERE diagnostic_id = ? AND item_key = ?",
                (diagnostic_id, item_key),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            connection.close()

    def update_diagnostic(
        self, user_id: int, diagnostic_id: int, *, mileage: int | None,
        notes: str | None, status: str,
    ) -> dict[str, object] | None:
        if status not in {"draft", "completed"}:
            raise ValueError("Unknown diagnostic state")
        connection = self.connect()
        try:
            cursor = connection.execute(
                """UPDATE diagnostics SET mileage = ?, notes = ?, status = ?,
                          updated_at = CURRENT_TIMESTAMP,
                          completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END
                   WHERE id = ? AND car_id IN (SELECT id FROM cars WHERE user_id = ?)""",
                (mileage, notes, status, status, diagnostic_id, user_id),
            )
            if cursor.rowcount:
                self._write_audit(connection, user_id, "diagnostic", diagnostic_id, status)
            connection.commit()
        finally:
            connection.close()
        return self.get_diagnostic(user_id, diagnostic_id) if cursor.rowcount else None

    def delete_diagnostic(self, user_id: int, diagnostic_id: int) -> list[str] | None:
        """Delete a diagnostic owned by the user and return its stored photo names."""
        connection = self.connect()
        try:
            owned = connection.execute(
                """SELECT 1 FROM diagnostics d JOIN cars c ON c.id = d.car_id
                   WHERE d.id = ? AND c.user_id = ?""",
                (diagnostic_id, user_id),
            ).fetchone()
            if owned is None:
                return None
            filenames = [
                str(row["filename"])
                for row in connection.execute(
                    "SELECT filename FROM diagnostic_photos WHERE diagnostic_id = ?",
                    (diagnostic_id,),
                ).fetchall()
            ]
            connection.execute("DELETE FROM diagnostic_photos WHERE diagnostic_id = ?", (diagnostic_id,))
            connection.execute("DELETE FROM diagnostic_items WHERE diagnostic_id = ?", (diagnostic_id,))
            connection.execute("DELETE FROM diagnostics WHERE id = ?", (diagnostic_id,))
            self._write_audit(connection, user_id, "diagnostic", diagnostic_id, "deleted")
            connection.commit()
            return filenames
        finally:
            connection.close()

    def add_diagnostic_photo(
        self, user_id: int, diagnostic_id: int, filename: str, caption: str | None,
    ) -> dict[str, object] | None:
        connection = self.connect()
        try:
            if connection.execute(
                """SELECT 1 FROM diagnostics d JOIN cars c ON c.id = d.car_id
                   WHERE d.id = ? AND c.user_id = ?""", (diagnostic_id, user_id)
            ).fetchone() is None:
                return None
            cursor = connection.execute(
                "INSERT INTO diagnostic_photos (diagnostic_id, filename, caption) VALUES (?, ?, ?)",
                (diagnostic_id, filename, caption),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id, filename, caption, created_at FROM diagnostic_photos WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return dict(row)
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
            appointments = connection.execute(
                f"""SELECT COUNT(*) FROM appointments WHERE archived_at IS NOT NULL
                    AND car_id IN (SELECT id FROM cars WHERE user_id = ?){age_sql}""",
                params,
            ).fetchone()[0]
            return {"orders": int(orders), "cars": int(cars), "customers": int(customers), "appointments": int(appointments)}
        finally:
            connection.close()

    def purge_archived(self, user_id: int, older_than_days: int | None = None) -> dict[str, int]:
        """Permanently delete archived records, deepest children first."""
        connection = self.connect()
        try:
            age_sql = "" if older_than_days is None else " AND datetime(archived_at) < datetime('now', ?)"
            params: tuple[object, ...] = (user_id,) if older_than_days is None else (user_id, f"-{older_than_days} days")
            appointment_cursor = connection.execute(
                f"""DELETE FROM appointments WHERE archived_at IS NOT NULL
                    AND car_id IN (SELECT id FROM cars WHERE user_id = ?){age_sql}""",
                params,
            )
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
                "appointments": int(appointment_cursor.rowcount),
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

    def remember_service_message_card(
        self, chat_id: int, message_id: int, *, appointment_id: int | None = None,
        service_order_id: int | None = None,
    ) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """INSERT OR IGNORE INTO service_message_cards
                   (chat_id, message_id, appointment_id, service_order_id)
                   VALUES (?, ?, ?, ?)""",
                (chat_id, message_id, appointment_id, service_order_id),
            )
            connection.execute(
                """UPDATE service_message_cards SET
                       appointment_id = COALESCE(?, appointment_id),
                       service_order_id = COALESCE(?, service_order_id)
                   WHERE chat_id = ? AND message_id = ?""",
                (appointment_id, service_order_id, chat_id, message_id),
            )
            connection.commit()
        finally:
            connection.close()

    def bind_appointment_card_to_order(
        self, appointment_id: int, service_order_id: int
    ) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """UPDATE service_message_cards SET service_order_id = ?
                   WHERE appointment_id = ?""",
                (service_order_id, appointment_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_service_message_cards_for_order(
        self, service_order_id: int
    ) -> list[dict[str, int]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT chat_id, message_id FROM service_message_cards
                   WHERE service_order_id = ? ORDER BY created_at""",
                (service_order_id,),
            ).fetchall()]
        finally:
            connection.close()

    def get_service_message_cards_for_appointment(
        self, appointment_id: int
    ) -> list[dict[str, int]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT chat_id, message_id FROM service_message_cards
                   WHERE appointment_id = ? ORDER BY created_at""",
                (appointment_id,),
            ).fetchall()]
        finally:
            connection.close()

    def forget_service_message_card(self, chat_id: int, message_id: int) -> None:
        connection = self.connect()
        try:
            connection.execute(
                "DELETE FROM service_message_cards WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_disposable_chat_messages(self, chat_id: int) -> list[int]:
        return self.get_chat_messages(chat_id, include_important=False)

    def get_chat_messages(self, chat_id: int, include_important: bool = False) -> list[int]:
        connection = self.connect()
        try:
            importance_filter = "" if include_important else "AND important = 0"
            return [int(row[0]) for row in connection.execute(
                f"""SELECT message_id FROM chat_messages cm WHERE chat_id = ? {importance_filter}
                    AND datetime(created_at) >= datetime('now', '-47 hours')
                    AND NOT EXISTS (
                        SELECT 1 FROM service_message_cards sc
                        WHERE sc.chat_id = cm.chat_id AND sc.message_id = cm.message_id
                    )
                    ORDER BY message_id""",
                (chat_id,),
            ).fetchall()]
        finally:
            connection.close()

    def get_chat_messages_for_cleanup(
        self, chat_id: int, *, today_only: bool = False,
        keep_card_statuses: set[str] | None = None,
    ) -> list[int]:
        """Select temporary messages while optionally retaining chosen card statuses."""
        connection = self.connect()
        try:
            date_filter = (
                "date(cm.created_at) = date('now')"
                if today_only else
                "datetime(cm.created_at) >= datetime('now', '-47 hours')"
            )
            rows = connection.execute(
                f"""SELECT cm.message_id, sc.service_order_id, sc.appointment_id,
                           o.status AS order_status, a.status AS appointment_status
                    FROM chat_messages cm
                    LEFT JOIN service_message_cards sc
                      ON sc.chat_id = cm.chat_id AND sc.message_id = cm.message_id
                    LEFT JOIN service_orders o ON o.id = sc.service_order_id
                    LEFT JOIN appointments a ON a.id = sc.appointment_id
                    WHERE cm.chat_id = ? AND {date_filter}
                    ORDER BY cm.message_id""",
                (chat_id,),
            ).fetchall()
            result: list[int] = []
            for row in rows:
                is_card = row["service_order_id"] is not None or row["appointment_id"] is not None
                if not is_card:
                    result.append(int(row["message_id"]))
                    continue
                if keep_card_statuses is None:
                    continue
                status = row["order_status"] or row["appointment_status"]
                if status not in keep_card_statuses:
                    result.append(int(row["message_id"]))
            return result
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
