"""OpenRouter integration for flexible workshop CRM requests."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar
from zoneinfo import ZoneInfo

import aiohttp


API_URL = "https://openrouter.ai/api/v1"
T = TypeVar("T")
MAX_MONEY_RUB = 1_000_000_000
MAX_RECEIPT_ITEMS = 100


@dataclass(frozen=True)
class AIResponse(Generic[T]):
    value: T
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class WorkshopCommand:
    intent: str
    customer_name: str | None
    customer_phone: str | None
    car_brand: str | None
    car_model: str | None
    car_year: int | None
    plate_number: str | None
    vin: str | None
    mileage: int | None
    description: str | None
    labor_revenue: int | None
    parts_cost: int | None
    parts_revenue: int | None
    parts_profit: int | None
    parts_source: str | None
    parts_markup_percent: float | None
    order_id: int | None
    order_status: str | None
    order_list_scope: str | None
    query_entity: str | None
    query_status: str | None
    query_mode: str | None
    query_period: str | None
    query_has_recommendations: bool | None
    appointment_start: str | None
    concern: str | None
    agreed_amount: int | None
    recommendations: str | None
    next_service_date: str | None
    next_service_mileage: int | None


@dataclass(frozen=True)
class ReceiptItem:
    name: str
    article: str | None
    quantity: float | None
    unit_cost: int | None
    total_cost: int | None


@dataclass(frozen=True)
class ReceiptAnalysis:
    document_type: str
    items: list[ReceiptItem]
    total_cost: int | None


@dataclass(frozen=True)
class VehicleDocumentAnalysis:
    document_type: str
    vin: str | None
    plate_number: str | None
    brand: str | None
    model: str | None
    year: int | None
    confidence: str


COMMAND_SCHEMA = {
    "name": "workshop_command",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["upsert_customer", "create_order", "create_appointment", "update_order", "markup_parts", "set_order_status", "list_orders", "query_crm", "delete_customer", "delete_car", "delete_order", "unknown"]},
            "customer_name": {"type": ["string", "null"]},
            "customer_phone": {"type": ["string", "null"]},
            "car_brand": {"type": ["string", "null"]},
            "car_model": {"type": ["string", "null"]},
            "car_year": {"type": ["integer", "null"]},
            "plate_number": {"type": ["string", "null"]},
            "vin": {"type": ["string", "null"]},
            "mileage": {"type": ["integer", "null"]},
            "description": {"type": ["string", "null"]},
            "labor_revenue": {"type": ["integer", "null"]},
            "parts_cost": {"type": ["integer", "null"]},
            "parts_revenue": {"type": ["integer", "null"]},
            "parts_profit": {"type": ["integer", "null"], "description": "Явно указанная прибыль на запчастях, без выручки за работы."},
            "parts_source": {
                "anyOf": [
                    {"type": "string", "enum": ["customer", "workshop"]},
                    {"type": "null"},
                ],
                "description": "customer — запчасти привёз клиент; workshop — запчасти предоставляет сервис.",
            },
            "parts_markup_percent": {"type": ["number", "null"]},
            "order_id": {"type": ["integer", "null"]},
            "order_status": {
                "anyOf": [
                    {"type": "string", "enum": ["planned", "in_progress", "ready"]},
                    {"type": "null"},
                ]
            },
            "order_list_scope": {
                "anyOf": [
                    {"type": "string", "enum": ["in_progress", "closed", "no_show", "all"]},
                    {"type": "null"},
                ],
                "description": "Какие заказы показать при intent=list_orders: в работе, закрытые, неявки или все.",
            },
            "query_entity": {
                "anyOf": [
                    {"type": "string", "enum": ["customers", "cars", "orders", "appointments"]},
                    {"type": "null"},
                ]
            },
            "query_status": {
                "anyOf": [
                    {"type": "string", "enum": ["in_progress", "closed", "scheduled", "no_show", "all"]},
                    {"type": "null"},
                ]
            },
            "query_mode": {
                "anyOf": [
                    {"type": "string", "enum": ["list", "count", "summary"]},
                    {"type": "null"},
                ]
            },
            "query_period": {
                "anyOf": [
                    {"type": "string", "enum": ["today", "tomorrow", "week", "all"]},
                    {"type": "null"},
                ]
            },
            "query_has_recommendations": {"type": ["boolean", "null"]},
            "appointment_start": {"type": ["string", "null"]},
            "concern": {"type": ["string", "null"], "description": "Причина обращения или жалоба клиента до начала работ."},
            "agreed_amount": {"type": ["integer", "null"], "minimum": 0, "description": "Сумма, заранее озвученная или согласованная с клиентом."},
            "recommendations": {"type": ["string", "null"], "description": "Что рекомендуется сделать при следующем визите."},
            "next_service_date": {"type": ["string", "null"], "description": "Дата следующего ТО в ISO 8601, если названа."},
            "next_service_mileage": {"type": ["integer", "null"], "description": "Пробег следующего ТО, если назван."},
        },
        "required": ["intent", "customer_name", "customer_phone", "car_brand", "car_model", "car_year", "plate_number", "vin", "mileage", "description", "labor_revenue", "parts_cost", "parts_revenue", "parts_profit", "parts_source", "parts_markup_percent", "order_id", "order_status", "order_list_scope", "query_entity", "query_status", "query_mode", "query_period", "query_has_recommendations", "appointment_start", "concern", "agreed_amount", "recommendations", "next_service_date", "next_service_mileage"],
        "additionalProperties": False,
    },
}


class OpenRouterError(RuntimeError):
    pass


RECEIPT_SCHEMA = {
    "name": "workshop_receipt",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "document_type": {"type": "string", "enum": ["receipt", "supplier_cart", "unknown"]},
            "items": {"type": "array", "maxItems": MAX_RECEIPT_ITEMS, "items": {"type": "object", "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "article": {"type": ["string", "null"], "maxLength": 100},
                "quantity": {"type": ["number", "null"], "minimum": 0, "maximum": 100000},
                "unit_cost": {"type": ["integer", "null"], "minimum": 0, "maximum": MAX_MONEY_RUB},
                "total_cost": {"type": ["integer", "null"], "minimum": 0, "maximum": MAX_MONEY_RUB},
            }, "required": ["name", "article", "quantity", "unit_cost", "total_cost"], "additionalProperties": False}},
            "total_cost": {"type": ["integer", "null"], "minimum": 0, "maximum": MAX_MONEY_RUB},
        },
        "required": ["document_type", "items", "total_cost"],
        "additionalProperties": False,
    },
}


VEHICLE_DOCUMENT_SCHEMA = {
    "name": "vehicle_document_recognition",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "document_type": {"type": "string", "enum": ["vin_plate", "pts", "sts", "vin_text", "unknown"]},
            "vin": {"type": ["string", "null"]},
            "plate_number": {"type": ["string", "null"]},
            "brand": {"type": ["string", "null"]},
            "model": {"type": ["string", "null"]},
            "year": {"type": ["integer", "null"], "minimum": 1900, "maximum": 2100},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["document_type", "vin", "plate_number", "brand", "model", "year", "confidence"],
        "additionalProperties": False,
    },
}


async def analyze_vehicle_document(
    api_key: str, model: str, *, image: bytes | None = None,
    mime_type: str | None = None, vin_hint: str | None = None,
) -> AIResponse[VehicleDocumentAnalysis]:
    """Read a VIN plate or Russian PTS/STS and return only confident vehicle fields."""
    prompt = """Recognize vehicle data. The input is either a photo of a VIN marking,
Russian PTS/STS vehicle document, or a manually entered VIN. Return VIN as exactly 17
uppercase Latin letters/digits (VIN never contains I, O or Q), Russian plate when visible,
manufacturer brand, commercial model, and model year. For a VIN-only input, decode brand,
model and year only when confidently supported by the VIN structure; otherwise return null.
Never invent obscured or uncertain characters. Do not return owner personal data."""
    content: list[dict[str, object]] = [{"type": "text", "text": f"{prompt}\nVIN input: {vin_hint or 'not provided'}"}]
    if image is not None and mime_type:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"},
        })
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_schema", "json_schema": VEHICLE_DOCUMENT_SCHEMA},
        "provider": {"require_parameters": True},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{API_URL}/chat/completions", headers=_headers(api_key), json=payload,
            timeout=aiohttp.ClientTimeout(total=90),
        ) as response:
            body = await response.text()
    if response.status >= 400:
        raise OpenRouterError(f"OpenRouter returned error {response.status}: {body[:300]}")
    try:
        data = json.loads(body)
        raw = data["choices"][0]["message"]["content"]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        vin = re.sub(r"[^A-HJ-NPR-Z0-9]", "", str(parsed.get("vin") or "").upper()) or None
        if vin is not None and len(vin) != 17:
            vin = None
        document_type = parsed["document_type"]
        confidence = parsed["confidence"]
        year = parsed.get("year")
        if document_type not in {"vin_plate", "pts", "sts", "vin_text", "unknown"} or confidence not in {"high", "medium", "low"}:
            raise ValueError("Invalid vehicle recognition result")
        if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100):
            raise ValueError("Invalid vehicle year")
        analysis = VehicleDocumentAnalysis(
            document_type=document_type, vin=vin,
            plate_number=_optional_short_text(parsed.get("plate_number"), 20),
            brand=_optional_short_text(parsed.get("brand"), 200),
            model=_optional_short_text(parsed.get("model"), 200), year=year,
            confidence=confidence,
        )
        actual_model, input_tokens, output_tokens, cost_usd = _response_meta(data, model)
        return AIResponse(analysis, actual_model, input_tokens, output_tokens, cost_usd)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise OpenRouterError("Could not recognize vehicle data.") from error


async def analyze_receipt_image(api_key: str, image: bytes, mime_type: str, model: str) -> AIResponse[ReceiptAnalysis]:
    """Extract purchase positions from a receipt or supplier cart image."""
    prompt = """You extract auto-parts purchase positions from a receipt or supplier cart image.
For name return only a short generic Russian part name, without brand, article, compatibility,
dimensions, marketing text, separators, or other product description. Put the catalog/SKU code
in article separately. Return quantity and purchase costs in rubles. Never invent data. Treat
this as purchase cost only: do not include labor, customer revenue, or profit. Compute a line
total when unit price and quantity are visible; use the visible document total when available."""
    encoded = base64.b64encode(image).decode("ascii")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
        ]}],
        "response_format": {"type": "json_schema", "json_schema": RECEIPT_SCHEMA},
        "provider": {"require_parameters": True},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/chat/completions", headers=_headers(api_key), json=payload, timeout=aiohttp.ClientTimeout(total=90)) as response:
            body = await response.text()
    if response.status >= 400:
        raise OpenRouterError(f"OpenRouter returned error {response.status}: {body[:300]}")
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        analysis = _validate_receipt(parsed)
        actual_model, input_tokens, output_tokens, cost_usd = _response_meta(data, model)
        return AIResponse(analysis, actual_model, input_tokens, output_tokens, cost_usd)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise OpenRouterError("Could not recognize receipt data.") from error


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _response_meta(data: dict[str, object], requested_model: str) -> tuple[str, int, int, float]:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    assert isinstance(usage, dict)
    return (
        str(data.get("model") or requested_model),
        int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        float(usage.get("cost") or 0),
    )


async def transcribe_voice(api_key: str, audio: bytes, model: str) -> AIResponse[str]:
    payload = {"model": model, "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": "ogg"}, "language": "ru"}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/audio/transcriptions", headers=_headers(api_key), json=payload, timeout=aiohttp.ClientTimeout(total=90)) as response:
            body = await response.text()
    if response.status >= 400:
        raise OpenRouterError(f"OpenRouter вернул ошибку {response.status}: {body[:300]}")
    data = json.loads(body)
    text = data.get("text", "").strip()
    if not text:
        raise OpenRouterError("OpenRouter не вернул текст голосового сообщения.")
    actual_model, input_tokens, output_tokens, cost_usd = _response_meta(data, model)
    return AIResponse(text, actual_model, input_tokens, output_tokens, cost_usd)


async def parse_workshop_command(
    api_key: str, text: str, model: str, context: list[str] | None = None
) -> AIResponse[WorkshopCommand]:
    prompt = """Ты помощник CRM автосервиса. Разбери русское сообщение в структуру.
intent:
- upsert_customer: добавляют или меняют имя, телефон либо данные автомобиля, без работ;
- create_order: описывают новый визит, выполненные работы, оплату или запчасти;
- update_order: дополняют уже существующий заказ для указанной машины (например «добавь фильтр»); суммы должны быть только добавляемыми суммами;
- set_order_status: меняют статус заказа. Фразы «закрой заказ», «заверши заказ», «машина готова», «ремонт закончен», «Kia Rio готова» означают order_status=ready. Фразы «машина приехала», «принял машину», «в работу», «снова в работе» означают order_status=in_progress. Если назван номер заказа, заполни order_id;
- list_orders: просят показать заказ-наряды или историю. Обязательно учитывай смысл запроса:
  «в работе/активные» -> order_list_scope=in_progress,
  «закрытые/завершённые/готовые/выполненные» -> order_list_scope=closed,
  «не приехали/неявки/no-show» -> order_list_scope=no_show,
  «все» -> order_list_scope=all. Если ограничение не названо, используй all;
- query_crm: любой нестандартный запрос на просмотр, поиск, подсчёт, сравнение или анализ
  данных CRM, который не сводится только к списку заказ-нарядов. Примеры: «покажи клиентов
  в работе» -> query_entity=customers, query_status=in_progress, query_mode=list;
  «сколько машин ожидается» -> cars/scheduled/count; «кто из них уже готов» -> customers/closed/list;
  «у кого есть рекомендации» -> customers/all/list и query_has_recommendations=true.
  Периоды: сегодня=today, завтра=tomorrow, ближайшие 7 дней=week, без периода=all;
- delete_customer, delete_car, delete_order: просят удалить клиента, автомобиль или заказ; извлеки максимум идентификаторов;
- unknown: запрос не относится к CRM.
Сначала определи фактическую цель пользователя и ограничения запроса, даже если фраза нестандартная
или не совпадает с названием кнопки CRM. Не подменяй запрошенную выборку ближайшей доступной функцией.
Не придумывай данные: отсутствующие значения ставь null. Номер телефона, имя, марку, модель, госномер, VIN и пробег извлекай независимо от порядка слов. Никогда не включай в customer_name VIN, адрес/местность, описание работ или фразы о запчастях. Фразы «запчасти клиента», «со своими запчастями» означают parts_source=customer; «наши запчасти», «запчасти сервиса» означают parts_source=workshop. Имя клиента необязательно: запись с телефоном и автомобилем без ФИО допустима, поэтому не подставляй вымышленное имя. Суммы указывай в рублях. Если сказано «на масле/запчастях заработали 500», укажи parts_profit=500, а labor_revenue не заполняй. Описание оставляй null, если работ нет. Причину первоначального обращения положи в concern. Фразы «озвучил», «согласовали», «предварительно будет стоить» относятся к agreed_amount. Советы на следующий визит положи в recommendations. Дату или пробег следующего ТО положи в next_service_date/next_service_mileage."""
    now = datetime.now(ZoneInfo("Europe/Moscow")).isoformat(timespec="minutes")
    context_text = ""
    if context:
        context_text = (
            "\nКонтекст предыдущих сообщений пользователя, от старых к новым:\n- "
            + "\n- ".join(context[-6:])
            + "\nУчитывай его для местоимений и продолжений, но текущая команда важнее."
        )
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": prompt + context_text + f"""
- create_appointment: клиент записывается на будущую дату или время, а работы ещё не выполнены. Заполни appointment_start в ISO 8601 с часовым поясом +03:00. Текущее московское время: {now}.
- markup_parts: user asks to mark up parts from a receipt/cart by a percentage. Set parts_markup_percent, and extract order_id or vehicle details. Do not set parts_profit for this intent."""}, {"role": "user", "content": text}],
        "response_format": {"type": "json_schema", "json_schema": COMMAND_SCHEMA},
        "provider": {"require_parameters": True},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/chat/completions", headers=_headers(api_key), json=payload, timeout=aiohttp.ClientTimeout(total=60)) as response:
            body = await response.text()
    if response.status >= 400:
        raise OpenRouterError(f"OpenRouter вернул ошибку {response.status}: {body[:300]}")
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        command = _validate_workshop_command(
            json.loads(content) if isinstance(content, str) else content
        )
        actual_model, input_tokens, output_tokens, cost_usd = _response_meta(data, model)
        return AIResponse(command, actual_model, input_tokens, output_tokens, cost_usd)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise OpenRouterError("Не удалось разобрать ответ OpenRouter.") from error


def _validate_receipt(value: object) -> ReceiptAnalysis:
    if not isinstance(value, dict) or value.get("document_type") not in {"receipt", "supplier_cart", "unknown"}:
        raise ValueError("Invalid receipt")
    rows = value.get("items")
    if not isinstance(rows, list) or len(rows) > MAX_RECEIPT_ITEMS:
        raise ValueError("Invalid receipt items")
    items: list[ReceiptItem] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid receipt item")
        name = str(row.get("name") or "").strip()
        article = str(row["article"]).strip() if row.get("article") is not None else None
        quantity = _bounded_number(row.get("quantity"), 100_000, integer=False)
        unit_cost = _bounded_number(row.get("unit_cost"), MAX_MONEY_RUB)
        line_total = _bounded_number(row.get("total_cost"), MAX_MONEY_RUB)
        if not name or len(name) > 200 or (article is not None and len(article) > 100):
            raise ValueError("Invalid receipt text")
        if line_total is None and quantity is not None and unit_cost is not None:
            line_total = round(quantity * unit_cost)
        if line_total is None or line_total <= 0:
            continue
        items.append(ReceiptItem(name, article or None, quantity, unit_cost, int(line_total)))
    total = sum(item.total_cost or 0 for item in items)
    if total <= 0 or total > MAX_MONEY_RUB:
        raise ValueError("Invalid receipt total")
    return ReceiptAnalysis(str(value["document_type"]), items, total)


def _optional_short_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid text value")
    result = value.strip()
    if len(result) > maximum:
        raise ValueError("Text value is too long")
    return result or None


def _bounded_number(value: object, maximum: float, *, integer: bool = True) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid numeric value")
    number = float(value)
    if not 0 <= number <= maximum or (integer and not number.is_integer()):
        raise ValueError("Numeric value outside allowed range")
    return int(number) if integer else number


def _validate_workshop_command(value: object) -> WorkshopCommand:
    if not isinstance(value, dict):
        raise ValueError("Invalid command")
    command = WorkshopCommand(**value)
    for field in ("labor_revenue", "parts_cost", "parts_revenue", "parts_profit", "agreed_amount"):
        _bounded_number(getattr(command, field), MAX_MONEY_RUB)
    for field in ("mileage", "next_service_mileage", "order_id"):
        _bounded_number(getattr(command, field), 2_147_483_647)
    if command.parts_markup_percent is not None:
        _bounded_number(command.parts_markup_percent, 1000, integer=False)
    if command.car_year is not None and not 1900 <= command.car_year <= 2100:
        raise ValueError("Invalid vehicle year")
    for field, field_value in vars(command).items():
        limit = 4000 if field in {"description", "concern", "recommendations"} else 200
        if isinstance(field_value, str) and len(field_value) > limit:
            raise ValueError("Command text is too long")
    return command
