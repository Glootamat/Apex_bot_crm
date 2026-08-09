"""One-time, repeatable migration from workshop.sqlite3 to PostgreSQL."""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql

from database import Database


TABLES = [
    "users", "customers", "customer_notes", "customer_phones", "cars",
    "contact_imports", "service_orders", "appointments", "order_photos",
    "receipts", "part_items", "ai_usage_log", "daily_reminders",
    "incoming_messages", "audit_log", "chat_messages", "service_message_cards",
    "diagnostics", "diagnostic_items", "diagnostic_photos", "schema_migrations",
]


def migrate(source: Path, database_url: str) -> None:
    if not source.is_file():
        raise SystemExit(f"SQLite database not found: {source}")
    os.environ["DATABASE_URL"] = database_url
    Database(source).initialize()
    sqlite = sqlite3.connect(source)
    sqlite.row_factory = sqlite3.Row
    with psycopg.connect(database_url) as postgres:
        for table in TABLES:
            exists = sqlite.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            rows = sqlite.execute(f'SELECT * FROM "{table}"').fetchall()
            if not rows:
                continue
            columns = list(rows[0].keys())
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            )
            postgres.executemany(statement, [tuple(row[column] for column in columns) for row in rows])
            if "id" in columns:
                postgres.execute(
                    sql.SQL("SELECT setval(pg_get_serial_sequence({}, 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {}").format(
                        sql.Literal(table), sql.Identifier(table)
                    )
                )
            print(f"{table}: {len(rows)}")
        postgres.commit()
    sqlite.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, default=Path(__file__).resolve().parents[1] / "workshop.sqlite3")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    migrate(args.sqlite, args.database_url)
