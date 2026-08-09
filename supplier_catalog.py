"""Server-side supplier catalog adapters. Credentials never leave the backend."""

from __future__ import annotations

import asyncio
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any

import aiohttp


@dataclass(frozen=True)
class SupplierOffer:
    supplier: str
    offer_id: str
    brand: str
    article: str
    name: str
    purchase_price: int
    quantity: int
    delivery_days: int
    warehouse: str | None = None


def configured_suppliers() -> dict[str, bool]:
    return {
        "rossko": bool(os.getenv("ROSSKO_KEY1") and os.getenv("ROSSKO_KEY2")),
        "profit_liga": bool(os.getenv("PROFIT_LIGA_API_KEY")),
    }


async def search_suppliers(query: str) -> tuple[list[SupplierOffer], dict[str, str]]:
    tasks: list[tuple[str, Any]] = []
    configured = configured_suppliers()
    if configured["rossko"]:
        tasks.append(("rossko", search_rossko(query)))
    if configured["profit_liga"]:
        tasks.append(("profit_liga", search_profit_liga(query)))
    if not tasks:
        return [], {}
    results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
    offers: list[SupplierOffer] = []
    errors: dict[str, str] = {}
    for (supplier, _), result in zip(tasks, results):
        if isinstance(result, BaseException):
            errors[supplier] = "Поставщик временно недоступен"
        else:
            offers.extend(result)
    return offers, errors


async def search_rossko(query: str) -> list[SupplierOffer]:
    delivery_id = os.getenv("ROSSKO_DELIVERY_ID") or "000000001"
    envelope = f'''<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:api="https://api.rossko.ru/">
 <soapenv:Body><api:GetSearch><api:KEY1>{_xml(os.environ["ROSSKO_KEY1"])}</api:KEY1><api:KEY2>{_xml(os.environ["ROSSKO_KEY2"])}</api:KEY2><api:text>{_xml(query)}</api:text><api:delivery_id>{_xml(delivery_id)}</api:delivery_id>{_optional_xml("address_id", os.getenv("ROSSKO_ADDRESS_ID"))}</api:GetSearch></soapenv:Body>
</soapenv:Envelope>'''
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.rossko.ru/service/v2.1/GetSearch",
            data=envelope.encode(),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "https://api.rossko.ru/service/v2.1/GetSearch"},
        ) as response:
            response.raise_for_status()
            payload = await response.text()
    root = ET.fromstring(payload)
    offers: list[SupplierOffer] = []
    for part in _elements(root, "Part"):
        brand, article, name = (_child_text(part, key) for key in ("brand", "partnumber", "name"))
        guid = _child_text(part, "guid") or article
        for stock in _descendants(part, "stock"):
            price = _number(_child_text(stock, "price"))
            if not article or price <= 0:
                continue
            stock_id = _child_text(stock, "id")
            offers.append(SupplierOffer("ROSSKO", f"{guid}:{stock_id}", brand, article, name, round(price), int(_number(_child_text(stock, "count"))), int(_number(_child_text(stock, "delivery"))), _child_text(stock, "description") or None))
    return offers[:100]


async def search_profit_liga(query: str) -> list[SupplierOffer]:
    """Search Profit Liga stock offers using the documented /search/items API."""
    url = os.getenv("PROFIT_LIGA_SEARCH_URL", "https://api.pr-lg.ru/search/items")
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params={"secret": os.environ["PROFIT_LIGA_API_KEY"], "article": query}) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    return _parse_profit_liga(data)


def _parse_profit_liga(data: Any) -> list[SupplierOffer]:
    if isinstance(data, dict) and str(data.get("status", "")).lower() == "error":
        raise RuntimeError(str(data.get("err") or "Profit Liga отклонила запрос"))
    rows = data.get("data", data.get("items", data)) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    offers: list[SupplierOffer] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        article = str(_pick(row, "article", "code") or "").strip()
        brand = str(_pick(row, "brand", "manufacturer") or "")
        name = str(_pick(row, "description", "name") or article)
        products = row.get("products")
        if isinstance(products, dict):
            products = list(products.values())
        if not isinstance(products, list):
            products = [row]
        for product_index, product in enumerate(products):
            if not isinstance(product, dict):
                continue
            price = _number(_pick(product, "price", "cost"))
            quantity = int(_number(_pick(product, "quantity", "count")))
            if not article or price <= 0 or quantity <= 0:
                continue
            article_id = _pick(product, "article_id") or _pick(row, "id") or row_index
            warehouse_id = _pick(product, "warehouse_id") or product_index
            delivery_hours = _number(_pick(product, "delivery_time"))
            delivery_days = max(0, math.ceil(delivery_hours / 24))
            warehouse = str(_pick(product, "custom_warehouse_name", "warehouse", "description") or "") or None
            offers.append(SupplierOffer(
                "Profit Liga", f"{article_id}:{warehouse_id}", brand, article, name,
                round(price), quantity, delivery_days, warehouse,
            ))
    return offers[:100]


def rounded_sale_price(purchase_price: int, markup_percent: float, round_to: int = 0) -> int:
    raw_sale = purchase_price * (1 + markup_percent / 100)
    return math.ceil(raw_sale / round_to) * round_to if round_to else round(raw_sale)


def serialize_offer(offer: SupplierOffer, markup_percent: float, round_to: int = 0) -> dict[str, object]:
    sale = rounded_sale_price(offer.purchase_price, markup_percent, round_to)
    return asdict(offer) | {
        "sale_price": sale,
        "profit": sale - offer.purchase_price,
        "markup_percent": markup_percent,
        "round_to": round_to,
    }


def _pick(value: dict[str, Any], *keys: str) -> Any:
    return next((value[key] for key in keys if key in value), None)


def _number(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except ValueError:
        return 0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _elements(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _local(element.tag) == name]


def _descendants(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if element is not root and _local(element.tag) == name]


def _child_text(root: ET.Element, name: str) -> str:
    child = next((element for element in root if _local(element.tag) == name), None)
    return (child.text or "").strip() if child is not None else ""


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def _optional_xml(name: str, value: str | None) -> str:
    return f"<api:{name}>{_xml(value)}</api:{name}>" if value else ""
