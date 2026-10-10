import json
import os
from pathlib import Path
import httpx
from app.persons import PERSON_SCHEMA, parse_person

KINDS = ("persons", "organizations", "entrepreneurs", "communications")
ROOT = Path(__file__).resolve().parent.parent

ENTITY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"entities": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {key: {"type": "string"} for key in ("original_text", "normalized_value", "note")},
        "required": ["original_text", "normalized_value", "note"]}}},
    "required": ["entities"]}

def model_name():
    name = os.getenv("LM_STUDIO_MODEL", "").strip()
    if not name:
        raise ValueError("Задайте LM_STUDIO_MODEL: идентификатор загруженной модели из LM Studio")
    return name

def base_url():
    return os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")

async def extract_kind(text, kind):
    prompt = (ROOT / "prompts" / f"{kind}.txt").read_text()
    results = []
    headers = {}
    if os.getenv("LM_STUDIO_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LM_STUDIO_API_KEY"]
    async with httpx.AsyncClient(timeout=180, headers=headers) as client:
        for start in range(0, len(text), 5500):
            chunk = text[start:start + 6500]
            response = await client.post(base_url() + "/chat/completions", json={
                "model": model_name(), "stream": False, "temperature": 0,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "entities", "strict": True, "schema": PERSON_SCHEMA if kind == "persons" else ENTITY_SCHEMA}},
                "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": chunk}]})
            response.raise_for_status()
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("Ответ модели не завершён; уменьшите размер фрагмента или увеличьте лимит генерации")
            payload = json.loads(choice["message"]["content"])
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
