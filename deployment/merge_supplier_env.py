"""Merge only supplier settings into a deployed .env without touching other secrets."""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import dotenv_values


KEYS = (
    "PARTS_MARKUP_PERCENT", "ROSSKO_KEY1", "ROSSKO_KEY2",
    "ROSSKO_DELIVERY_ID", "ROSSKO_ADDRESS_ID", "PROFIT_LIGA_API_KEY",
    "PROFIT_LIGA_SEARCH_URL",
)


def merge(source: Path, target: Path) -> None:
    incoming = {key: value for key, value in dotenv_values(source).items() if key in KEYS and value is not None}
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    replaced: set[str] = set()
    result: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in incoming:
            result.append(f"{key}={incoming[key]}")
            replaced.add(key)
        else:
            result.append(line)
    if result and result[-1]:
        result.append("")
    result.extend(f"{key}={incoming[key]}" for key in KEYS if key in incoming and key not in replaced)
    target.write_text("\n".join(result) + "\n", encoding="utf-8")
    print("updated:", ", ".join(key for key in KEYS if key in incoming))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    merge(args.source, args.target)
