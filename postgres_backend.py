"""Small DB-API compatibility layer for the CRM's existing qmark SQL."""

from __future__ import annotations

import re
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

_AUTO_ID_TABLES = {
    "users", "cars", "service_orders", "customers", "customer_notes",
    "customer_phones", "contact_imports", "order_photos", "part_items",
    "receipts", "ai_usage_log", "incoming_messages", "appointments",
    "audit_log", "diagnostics", "diagnostic_items", "diagnostic_photos",
}


class PostgresCursor:
    def __init__(self, cursor: psycopg.Cursor[Any], lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self):
        row = self._cursor.fetchone()
        return HybridRow(row) if row is not None else None

    def fetchall(self):
        return [HybridRow(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return (HybridRow(row) for row in self._cursor)


class HybridRow(dict[str, Any]):
    """Behaves like both sqlite3.Row and a normal mapping."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class PostgresConnection:
    def __init__(self, url: str) -> None:
        self._connection = psycopg.connect(url, row_factory=dict_row)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> PostgresCursor:
        translated = _translate(sql)
        insert = re.match(r"\s*INSERT\s+INTO\s+(\w+)", translated, re.I)
        returns_id = bool(insert and insert.group(1).lower() in _AUTO_ID_TABLES) and "RETURNING" not in translated.upper()
        if returns_id:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        self._connection.execute("SAVEPOINT apex_statement")
        try:
            cursor = self._connection.execute(translated, tuple(params))
            lastrowid = None
            if returns_id:
                row = cursor.fetchone()
                lastrowid = int(row["id"]) if row and "id" in row else None
            self._connection.execute("RELEASE SAVEPOINT apex_statement")
            return PostgresCursor(cursor, lastrowid)
        except Exception:
            self._connection.execute("ROLLBACK TO SAVEPOINT apex_statement")
            self._connection.execute("RELEASE SAVEPOINT apex_statement")
            raise

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> PostgresCursor:
        self._connection.execute("SAVEPOINT apex_statement")
        try:
            cursor = self._connection.cursor()
            cursor.executemany(_translate(sql), params)
            self._connection.execute("RELEASE SAVEPOINT apex_statement")
            return PostgresCursor(cursor)
        except Exception:
            self._connection.execute("ROLLBACK TO SAVEPOINT apex_statement")
            self._connection.execute("RELEASE SAVEPOINT apex_statement")
            raise

    def executescript(self, script: str) -> None:
        for statement in (part.strip() for part in script.split(";")):
            if statement:
                self.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def _translate(sql: str) -> str:
    value = sql.strip()
    if value.upper().startswith("PRAGMA FOREIGN_KEYS"):
        return "SELECT 1"
    match = re.match(r"PRAGMA\s+table_info\((\w+)\)", value, re.I)
    if match:
        return "SELECT column_name AS name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s".replace("%s", f"'{match.group(1)}'")
    value = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\b", "BIGSERIAL PRIMARY KEY", value, flags=re.I)
    value = re.sub(r"\bREAL\b", "DOUBLE PRECISION", value, flags=re.I)
    value = value.replace("GROUP_CONCAT(cp.phone, '|')", "STRING_AGG(cp.phone, '|')")
    value = re.sub(r"MAX\(0,\s*([^\)]+)\)", r"GREATEST(0, \1)", value, flags=re.I)
    value = re.sub(r"datetime\((\w+(?:\.\w+)?)\)", r"CAST(\1 AS TIMESTAMP)", value, flags=re.I)
    value = re.sub(r"datetime\('now',\s*'localtime',\s*\?\)", "CURRENT_TIMESTAMP + CAST(? AS INTERVAL)", value, flags=re.I)
    value = re.sub(r"datetime\('now',\s*\?\)", "CURRENT_TIMESTAMP + CAST(? AS INTERVAL)", value, flags=re.I)
    value = re.sub(r"date\('now',\s*'localtime',\s*\?\)", "CURRENT_DATE + CAST(? AS INTERVAL)", value, flags=re.I)
    value = re.sub(r"date\('now',\s*'localtime'\)", "CURRENT_DATE", value, flags=re.I)
    value = re.sub(r"date\((\w+(?:\.\w+)?),\s*'localtime'\)", r"CAST(\1 AS DATE)", value, flags=re.I)
    value = value.replace("HAVING last_visit IS NULL OR CAST(last_visit AS TIMESTAMP)", "HAVING MAX(COALESCE(o.completed_at, o.created_at)) IS NULL OR CAST(MAX(COALESCE(o.completed_at, o.created_at)) AS TIMESTAMP)")
    replace_match = re.match(r"INSERT\s+OR\s+REPLACE\s+INTO\s+chat_messages\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)", value, re.I | re.S)
    if replace_match:
        value = f"INSERT INTO chat_messages ({replace_match.group(1)}) VALUES ({replace_match.group(2)}) ON CONFLICT (chat_id, message_id) DO UPDATE SET important = EXCLUDED.important"
    elif re.match(r"INSERT\s+OR\s+IGNORE", value, re.I):
        value = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", value, count=1, flags=re.I).rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    value = value.replace("?", "%s")
    return value
