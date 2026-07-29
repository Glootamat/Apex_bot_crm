"""OpenRouter integration for flexible workshop CRM requests."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Generic, TypeVar

import aiohttp


API_URL = "https://openrouter.ai/api/v1"
T = TypeVar("T")


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
    order_id: int | None
    order_status: str | None


COMMAND_SCHEMA = {
    "name": "workshop_command",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["upsert_customer", "create_order", "update_order", "set_order_status", "list_orders", "delete_customer", "delete_car", "delete_order", "unknown"]},
            "customer_name": {"type": ["string", "null"]},
            "customer_phone": {"type": ["string", "null"]},
            "car_brand": {"type": ["string", "null"]},
            "car_model": {"type": ["string", "null"]},
            "car_year": {"type": ["integer", "null"]},
            "plate_number": {"type": ["string", "null"]},
            "vin": {"type": ["string", "null"]},
            "mileage": {"type": ["integer", "null"], "minimum": 0},
            "description": {"type": ["string", "null"]},
            "labor_revenue": {"type": ["integer", "null"], "minimum": 0},
            "parts_cost": {"type": ["integer", "null"], "minimum": 0},
            "parts_revenue": {"type": ["integer", "null"], "minimum": 0},
            "parts_profit": {"type": ["integer", "null"], "minimum": 0, "description": "Явно указанная прибыль на запчастях, без выручки за работы."},
            "order_id": {"type": ["integer", "null"], "minimum": 1},
            "order_status": {"type": ["string", "null"], "enum": ["in_progress", "completed", None]},
        },
        "required": ["intent", "customer_name", "customer_phone", "car_brand", "car_model", "car_year", "plate_number", "vin", "mileage", "description", "labor_revenue", "parts_cost", "parts_revenue", "parts_profit", "order_id", "order_status"],
        "additionalProperties": False,
    },
}


class OpenRouterError(RuntimeError):
    pass


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


async def parse_workshop_command(api_key: str, text: str, model: str) -> AIResponse[WorkshopCommand]:
    prompt = """Ты помощник CRM автосервиса. Разбери русское сообщение в структуру.
intent:
- upsert_customer: добавляют или меняют имя, телефон либо данные автомобиля, без работ;
- create_order: описывают новый визит, выполненные работы, оплату или запчасти;
- update_order: дополняют уже существующий заказ для указанной машины (например «добавь фильтр»); суммы должны быть только добавляемыми суммами;
- set_order_status: меняют статус заказа («выполнен», «в работе»). Фразы «закрой заказ», «заверши заказ», «машина готова», «ремонт закончен», «Kia Rio готова» означают order_status=completed. Фразы «открой заказ», «снова в работе» означают order_status=in_progress. Если назван номер заказа, заполни order_id;
- list_orders: просят показать заказ-наряды/историю;
- delete_customer, delete_car, delete_order: просят удалить клиента, автомобиль или заказ; извлеки максимум идентификаторов;
- unknown: запрос не относится к CRM.
Не придумывай данные: отсутствующие значения ставь null. Номер телефона, имя, марку, модель, госномер, VIN и пробег извлекай независимо от порядка слов. Суммы указывай в рублях. Если сказано «на масле/запчастях заработали 500», укажи parts_profit=500, а labor_revenue не заполняй. Описание оставляй null, если работ нет."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
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
        command = WorkshopCommand(**(json.loads(content) if isinstance(content, str) else content))
        actual_model, input_tokens, output_tokens, cost_usd = _response_meta(data, model)
        return AIResponse(command, actual_model, input_tokens, output_tokens, cost_usd)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise OpenRouterError("Не удалось разобрать ответ OpenRouter.") from error
