import json
import os
from pathlib import Path
import httpx
from app.persons import PERSON_SCHEMA, parse_person
from app import gemini, yandex

KINDS = ("persons", "organizations", "entrepreneurs", "communications")
ROOT = Path(__file__).resolve().parent.parent

ENTITY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"entities": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {key: {"type": "string"} for key in ("original_text", "normalized_value", "note")},
        "required": ["original_text", "normalized_value", "note"]}}},
    "required": ["entities"]}

def provider_name():
    provider = os.getenv("LLM_PROVIDER", "local").strip().lower()
    if provider not in {"local", "gemini", "yandex"}:
        raise ValueError("LLM_PROVIDER должен быть local, gemini или yandex")
    return provider

def validate_configuration():
    name = model_name()
    if provider_name() == "gemini":
        gemini.api_key()
    elif provider_name() == "yandex":
        yandex.api_key()
    return name

def model_name():
    if provider_name() == "yandex":
        return yandex.model_name()
    if provider_name() == "gemini":
        return gemini.model_name()
    name = os.getenv("LM_STUDIO_MODEL", "").strip()
    if not name:
        raise ValueError("Задайте LM_STUDIO_MODEL: идентификатор загруженной модели из LM Studio")
    return name

def base_url():
    return os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")

class ExtractionError(Exception):
    """A diagnostic safe to display without response bodies or document text."""

async def extract_kind(text, kind):
    try:
        return await _extract_kind(text, kind)
    except httpx.TimeoutException as exc:
        if provider_name() == "yandex":
            raise ExtractionError("YandexGPT API не ответил вовремя. Проверьте соединение; YANDEX_TIMEOUT задаёт тайм-аут запроса") from exc
        if provider_name() == "gemini":
            raise ExtractionError("Gemini API не ответил за отведённое время. Проверьте соединение; GEMINI_TIMEOUT задаёт тайм-аут в секундах") from exc
        raise ExtractionError("LM Studio не ответила за отведённое время. Проверьте журнал сервера и скорость генерации; LM_STUDIO_TIMEOUT задаёт тайм-аут в секундах (по умолчанию 180).") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if provider_name() == "yandex":
            raise ExtractionError(yandex.error_description(exc.response)) from exc
        if provider_name() == "gemini":
            raise ExtractionError(gemini.error_description(exc.response)) from exc
        hint = {
            400: "Проверьте в журнале LM Studio идентификатор модели, размер контекста и поддержку JSON-схемы.",
            401: "Сервер требует авторизацию. Проверьте настройку LM_STUDIO_API_KEY.",
            403: "Сервер отклонил доступ. Проверьте настройки авторизации и доступа.",
            404: "Проверьте LM_STUDIO_URL (он должен включать /v1) и идентификатор модели.",
            503: "Проверьте, что модель загружена и сервер готов к генерации."
        }.get(status, "Посмотрите журнал сервера LM Studio в момент запроса.")
        raise ExtractionError(f"LM Studio вернула HTTP {status}. {hint}") from exc
    except httpx.RequestError as exc:
        if provider_name() == "yandex":
            raise ExtractionError("Не удалось подключиться к YandexGPT API. Проверьте доступ к llm.api.cloud.yandex.net") from exc
        if provider_name() == "gemini":
            raise ExtractionError("Не удалось подключиться к Gemini API. Проверьте доступ к generativelanguage.googleapis.com") from exc
        raise ExtractionError("Не удалось подключиться к LM Studio. Проверьте, что сервер запущен, а LM_STUDIO_URL содержит правильный адрес и порт.") from exc
    except json.JSONDecodeError as exc:
        raise ExtractionError("Модель или API вернули невалидный JSON. Проверьте поддержку структурированных ответов выбранной моделью.") from exc
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc

async def _extract_kind(text, kind):
    prompt = (ROOT / "prompts" / f"{kind}.txt").read_text(encoding="utf-8")
    results = []
    provider = provider_name()
    headers = {}
    if provider == "yandex":
        headers = yandex.headers()
    elif provider == "gemini":
        headers["x-goog-api-key"] = gemini.api_key()
    elif os.getenv("LM_STUDIO_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LM_STUDIO_API_KEY"]
    timeout_var = {"gemini": "GEMINI_TIMEOUT", "yandex": "YANDEX_TIMEOUT", "local": "LM_STUDIO_TIMEOUT"}[provider]
    try:
        timeout = float(os.getenv(timeout_var, "180"))
    except ValueError as exc:
        raise ValueError(f"{timeout_var} должен быть числом от 1 до 3600") from exc
    if not 1 <= timeout <= 3600:
        raise ValueError(f"{timeout_var} должен быть числом от 1 до 3600")
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for start in range(0, len(text), 5500):
            chunk = text[start:start + 6500]
            schema = PERSON_SCHEMA if kind == "persons" else ENTITY_SCHEMA
            if provider == "yandex":
                payload = await yandex.generate(client, prompt, chunk, schema)
            elif provider == "gemini":
                payload = await gemini.generate(client, prompt, chunk, schema)
            else:
                response = await client.post(base_url() + "/chat/completions", json={
                    "model": model_name(), "stream": False, "temperature": 0,
                    "response_format": {"type": "json_schema", "json_schema": {
                        "name": "entities", "strict": True, "schema": PERSON_SCHEMA if kind == "persons" else ENTITY_SCHEMA}},
                    "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": chunk}]})
                response.raise_for_status()
                envelope = response.json()
                choices = envelope.get("choices") if isinstance(envelope, dict) else None
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError("API LM Studio вернул ответ без ожидаемого списка choices")
                choice = choices[0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("Ответ модели не завершён; уменьшите размер фрагмента или увеличьте лимит генерации")
                message = choice.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str):
                    raise ValueError("API LM Studio вернул ответ без текстового message.content")
                payload = json.loads(content)
            if kind == "persons":
                if not isinstance(payload, list):
                    raise ValueError("Модель должна вернуть массив сведений о людях")
                results.extend(parse_person(item, chunk, start) for item in payload)
                continue
            if not isinstance(payload, dict):
                raise ValueError("Модель вернула неверный JSON-объект")
            if not isinstance(payload.get("entities"), list):
                raise ValueError("Модель вернула неверный список сущностей")
            for item in payload["entities"]:
                if not isinstance(item, dict):
                    raise ValueError("Модель вернула неверную сущность")
                original = item.get("original_text")
                normalized = item.get("normalized_value")
                if not isinstance(original, str) or not original or not isinstance(normalized, str) or not normalized.strip():
                    raise ValueError("Модель вернула сущность без исходного или нормализованного значения")
                position = chunk.find(original)
                if position < 0:
                    raise ValueError("Выделенный моделью фрагмент отсутствует в исходном тексте")
                while position >= 0:
                    results.append({"kind": kind, "start": start + position, "end": start + position + len(original),
                                    "original_text": original, "normalized_value": normalized.strip(),
                                    "note": str(item.get("note", ""))})
                    position = chunk.find(original, position + len(original))
    return results
