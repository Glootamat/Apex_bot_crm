"""SQLite storage for the workshop CRM."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
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

    @property
    def profit(self) -> int:
        return self.labor_revenue + self.parts_revenue - self.parts_cost + self.parts_profit

    @property
    def parts_margin(self) -> int:
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
        return self.revenue - self.parts_cost + self.parts_profit

    @property
    def parts_margin(self) -> int:
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


class Database:
    def __init__(self, path: str | Path = "workshop.sqlite3") -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (car_id) REFERENCES cars(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS order_photos (
                    id INTEGER PRIMARY KEY,
                    service_order_id INTEGER NOT NULL,
                    telegram_file_id TEXT NOT NULL,
                    caption TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (service_order_id) REFERENCES service_orders(id) ON DELETE CASCADE
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
            order_columns = {row["name"] for row in connection.execute("PRAGMA table_info(service_orders)")}
            if "parts_profit" not in order_columns:
                connection.execute("ALTER TABLE service_orders ADD COLUMN parts_profit INTEGER NOT NULL DEFAULT 0")
            if "status" not in order_columns:
                connection.execute("ALTER TABLE service_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'in_progress'")
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
                "INSERT INTO customers (user_id, full_name, phone) VALUES (?, ?, ?)",
                (user_id, full_name, phone),
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
                   JOIN users AS u ON u.id = c.user_id WHERE u.telegram_id = ? ORDER BY c.id DESC""",
                (telegram_id,),
            ).fetchall()
            return [Customer(**dict(row)) for row in rows]
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
                "UPDATE customers SET full_name = COALESCE(?, full_name), phone = COALESCE(?, phone) WHERE id = ?",
                (full_name, phone, customer_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_customer_overviews(self, telegram_id: int) -> list[CustomerOverview]:
        connection = self.connect()
        try:
            customer_rows = connection.execute(
                """SELECT c.id, c.user_id, c.full_name, c.phone FROM customers c
                   JOIN users u ON u.id = c.user_id WHERE u.telegram_id = ? ORDER BY c.id DESC""",
                (telegram_id,),
            ).fetchall()
            result: list[CustomerOverview] = []
            for row in customer_rows:
                customer = Customer(**dict(row))
                car_rows = connection.execute(
                    """SELECT c.id, c.user_id, c.customer_id, c.brand, c.model, c.year, c.plate_number, c.vin, c.mileage,
                              COUNT(o.id) AS orders_total,
                              COALESCE(SUM(CASE WHEN o.status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress,
                              COALESCE(SUM(CASE WHEN o.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed
                       FROM cars c LEFT JOIN service_orders o ON o.car_id = c.id
                       WHERE c.customer_id = ? GROUP BY c.id ORDER BY c.id DESC""",
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
                """SELECT o.id, o.description, o.status, c.brand, c.model, c.plate_number, cu.full_name AS customer_name
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
            "orders": [row for row in orders if matches([row["description"], row["brand"], row["model"], row["plate_number"], row["customer_name"]])][:10],
        }

    def add_car(self, user_id: int, brand: str, model: str, year: int | None = None, plate_number: str | None = None, customer_id: int | None = None, vin: str | None = None, mileage: int | None = None) -> int:
        connection = self.connect()
        try:
            cursor = connection.execute(
                """INSERT INTO cars (user_id, customer_id, brand, model, year, plate_number, vin, mileage)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, customer_id, brand, model, year, plate_number, vin, mileage),
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

    def update_car(self, car_id: int, customer_id: int | None, brand: str | None, model: str | None, year: int | None, plate_number: str | None, vin: str | None, mileage: int | None) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """UPDATE cars SET customer_id = COALESCE(?, customer_id), brand = COALESCE(?, brand),
                   model = COALESCE(?, model), year = COALESCE(?, year), plate_number = COALESCE(?, plate_number),
                   vin = COALESCE(?, vin), mileage = COALESCE(?, mileage) WHERE id = ?""",
                (customer_id, brand, model, year, plate_number, vin, mileage, car_id),
            )
            connection.commit()
        finally:
            connection.close()

    def add_service_order(self, car_id: int, description: str, labor_revenue: int, parts_cost: int, parts_revenue: int, parts_profit: int = 0) -> ServiceOrder:
        connection = self.connect()
        try:
            cursor = connection.execute(
                """INSERT INTO service_orders (car_id, description, labor_revenue, parts_cost, parts_revenue, parts_profit)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (car_id, description, labor_revenue, parts_cost, parts_revenue, parts_profit),
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
                          c.brand, c.model, c.plate_number
                   FROM service_orders AS o JOIN cars AS c ON c.id = o.car_id WHERE o.id = ?""",
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
                          c.brand, c.model, c.plate_number
                   FROM service_orders AS o JOIN cars AS c ON c.id = o.car_id JOIN users AS u ON u.id = c.user_id
                   WHERE u.telegram_id = ? ORDER BY o.id DESC LIMIT ?""",
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
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

    def set_order_status(self, order_id: int, status: str) -> ServiceOrder:
        if status not in {"in_progress", "completed"}:
            raise ValueError("Unknown order status")
        connection = self.connect()
        try:
            connection.execute("UPDATE service_orders SET status = ? WHERE id = ?", (status, order_id))
            connection.commit()
        finally:
            connection.close()
        return self.get_service_order(order_id)

    def delete_customer(self, user_id: int, customer_id: int) -> bool:
        connection = self.connect()
        try:
            car_ids = [row["id"] for row in connection.execute("SELECT id FROM cars WHERE user_id = ? AND customer_id = ?", (user_id, customer_id)).fetchall()]
            connection.executemany("DELETE FROM cars WHERE id = ?", [(car_id,) for car_id in car_ids])
            cursor = connection.execute("DELETE FROM customers WHERE id = ? AND user_id = ?", (customer_id, user_id))
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def delete_car(self, user_id: int, car_id: int) -> bool:
        connection = self.connect()
        try:
            cursor = connection.execute("DELETE FROM cars WHERE id = ? AND user_id = ?", (car_id, user_id))
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def delete_service_order(self, user_id: int, order_id: int) -> bool:
        connection = self.connect()
        try:
            cursor = connection.execute(
                "DELETE FROM service_orders WHERE id = ? AND car_id IN (SELECT id FROM cars WHERE user_id = ?)",
                (order_id, user_id),
            )
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def add_order_photo(self, service_order_id: int, telegram_file_id: str, caption: str | None) -> int:
        connection = self.connect()
        try:
            cursor = connection.execute(
                "INSERT INTO order_photos (service_order_id, telegram_file_id, caption) VALUES (?, ?, ?)",
                (service_order_id, telegram_file_id, caption),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def count_order_photos(self, service_order_id: int) -> int:
        connection = self.connect()
        try:
            return int(connection.execute("SELECT COUNT(*) FROM order_photos WHERE service_order_id = ?", (service_order_id,)).fetchone()[0])
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
