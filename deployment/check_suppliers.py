"""Check supplier connectivity without printing credentials or customer prices."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from supplier_catalog import configured_suppliers, search_profit_liga, search_rossko, search_suppliers, serialize_offer


async def main() -> None:
    configured = configured_suppliers()
    print("configured", configured)
    if configured["profit_liga"]:
        try:
            offers = await search_profit_liga("26300")
            print("profit_liga", "ok", "offers", len(offers))
        except Exception as error:
            print("profit_liga", "error", type(error).__name__, getattr(error, "status", ""))
    if configured["rossko"]:
        try:
            offers = await search_rossko("26300")
            print("rossko", "ok", "offers", len(offers))
        except Exception as error:
            print("rossko", "error", type(error).__name__, getattr(error, "status", ""))
    combined, errors = await search_suppliers("26300")
    priced = [serialize_offer(offer, 40) for offer in combined]
    print("combined", "ok", "offers", len(priced), "errors", errors)
    if priced:
        print("pricing", "ok", "sale_price", priced[0]["sale_price"], "profit", priced[0]["profit"])


if __name__ == "__main__":
    asyncio.run(main())
