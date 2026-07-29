"""OpenRouter integration for transcription and CRM data extraction."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import aiohttp


API_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class WorkshopRecord:
    customer_name: str
    customer_phone: str | None
    car_brand: str
    car_model: str
    car_year: int | None
    plate_number: str | None
    description: str
    labor_revenue: int
    parts_cost: int
    parts_revenue: int


RECORD_SCHEMA = {
    "name": "workshop_record",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "customer_name": {"type": "string", "description": "Имя клиента. Если не названо, пустая строка."},
            "customer_phone": {"type": ["string", "null"]},
            "car_brand": {"type": "string", "description": "Марка автомобиля. Если не указана, пустая строка."},
            "car_model": {"type": "string", "description": "Модель автомобиля. Если не указана, пустая строка."},
            "car_year": {"type": ["integer", "null"]},
            "plate_number": {"type": ["string", "null"]},
            "description": {"type": "string", "description": "Краткое описание выполненных работ."},
            "labor_revenue": {"type": "integer", "minimum": 0, "description": "Сколько клиент заплатил за работу, ₽."},
            "parts_cost": {"type": "integer", "minimum": 0, "description": "Себестоимость запчастей для сервиса, ₽."},
            "parts_revenue": {"type": "integer", "minimum": 0, "description": "Сколько клиент заплатил за запчасти, ₽."},
        },
        "required": [
            "customer_name", "customer_phone", "car_brand", "car_model", "car_year", "plate_number",
            "description", "labor_revenue", "parts_cost", "parts_revenue",
        ],
        "additionalProperties": False,
    },
}


class OpenRouterError(RuntimeError):
    pass


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


async def transcribe_voice(api_key: str, audio: bytes, model: str) -> str:
    payload = {
        "model": model,
        "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": "ogg"},
        "language": "ru",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/audio/transcriptions", headers=_headers(api_key), json=payload, timeout=aiohttp.ClientTimeout(total=90)) as response:
            body = await response.text()
    if response.status >= 400:
        raise OpenRouterError(f"OpenRouter вернул ошибку {response.status}: {body[:300]}")
    text = json.loads(body).get("text", "").strip()
    if not text:
        raise OpenRouterError("OpenRouter не вернул текст голосового сообщения.")
    return text


async def parse_workshop_record(api_key: str, text: str, model: str) -> WorkshopRecord:
    system_prompt = (
        "Ты помощник автосервиса. Извлеки из сообщения данные для создания заказ-наряда. "
        "Не придумывай значения: неизвестные строки оставляй пустыми, числа ставь 0, неизвестный год — null. "
        "Если указана только одна сумма запчастей без слов о закупке или продаже, считай её продажей клиенту. "
        "Описание работ напиши кратко по-русски."
    )
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
        "response_format": {"type": "json_schema", "json_schema": RECORD_SCHEMA},
        "provider": {"require_parameters": True},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/chat/completions", headers=_headers(api_key), json=payload, timeout=aiohttp.ClientTimeout(total=60)) as response:
            body = await response.text()
    if response.status >= 400:
        raise OpenRouterError(f"OpenRouter вернул ошибку {response.status}: {body[:300]}")
    try:
        content = json.loads(body)["choices"][0]["message"]["content"]
        data = json.loads(content) if isinstance(content, str) else content
        return WorkshopRecord(**data)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise OpenRouterError("Не удалось разобрать ответ OpenRouter.") from error
