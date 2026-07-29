"""SQLite storage for workshop clients and their cars."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Car:
    id: int
    user_id: int
    brand: str
    model: str
    year: int | None
    plate_number: str | None


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
                """
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
                    username = excluded.username,
                    full_name = excluded.full_name
                """,
                (telegram_id, username, full_name),
            )
            row = connection.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            connection.commit()
        finally:
            connection.close()
        return int(row["id"])

    def add_car(
        self,
        user_id: int,
        brand: str,
        model: str,
        year: int | None = None,
        plate_number: str | None = None,
    ) -> int:
        connection = self.connect()
        try:
            cursor = connection.execute(
                """
                INSERT INTO cars (user_id, brand, model, year, plate_number)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, brand, model, year, plate_number),
            )
            car_id = int(cursor.lastrowid)
            connection.commit()
        finally:
            connection.close()
        return car_id

    def get_cars_for_telegram_user(self, telegram_id: int) -> list[Car]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """
                SELECT cars.id, cars.user_id, cars.brand, cars.model, cars.year, cars.plate_number
                FROM cars
                JOIN users ON users.id = cars.user_id
                WHERE users.telegram_id = ?
                ORDER BY cars.id DESC
                """,
                (telegram_id,),
            ).fetchall()
        finally:
            connection.close()
        return [Car(**dict(row)) for row in rows]
