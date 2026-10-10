"""Gemini REST API. Credentials are sent only in the Google API-key header."""
import json
import os
import re

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

def model_name():
    name = os.getenv("GEMINI_MODEL", "").strip().removeprefix("models/")
    if not name:
        raise ValueError("Задайте GEMINI_MODEL: идентификатор доступной вам модели Gemini")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ValueError("Неверный идентификатор GEMINI_MODEL")
    return name

def api_key():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("Задайте GEMINI_API_KEY в окружении Python сервера")
    return key

def response_schema(schema):
    """Convert the app's narrow JSON schemas to Gemini's documented Schema."""
    kind = schema["type"]
    nullable = isinstance(kind, list) and "null" in kind
    if isinstance(kind, list):
        kind = next(value for value in kind if value != "null")
    result = {"type": kind.upper()}
    if nullable:
        result["nullable"] = True
    if "items" in schema:
        result["items"] = response_schema(schema["items"])
    if "properties" in schema:
        result["properties"] = {key: response_schema(value) for key, value in schema["properties"].items()}
        result["propertyOrdering"] = list(schema["properties"])
    if "required" in schema:
        result["required"] = schema["required"]
    return result

async def generate(client, prompt, text, schema):
    response = await client.post(f"{ENDPOINT}/{model_name()}:generateContent", json={
        "systemInstruction": {"parts": [{"text": prompt}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "responseSchema": response_schema(schema)}})
    response.raise_for_status()
    envelope = response.json()
    if not isinstance(envelope, dict):
        raise ValueError("Gemini API вернул неверный объект ответа")
    feedback = envelope.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        raise ValueError("Gemini заблокировал обработку документа. Результаты не сохранены")
    candidates = envelope.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ValueError("Gemini API не вернул результатов генерации")
    candidate = candidates[0]
    reason = candidate.get("finishReason")
    if reason != "STOP":
        if reason == "MAX_TOKENS":
            raise ValueError("Ответ Gemini не завершён: достигнут лимит токенов")
        if reason in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}:
            raise ValueError("Gemini остановил ответ по ограничениям сервиса. Результаты не сохранены")
        raise ValueError("Gemini не завершил генерацию ответа")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ValueError("Gemini API вернул ответ без текстового содержимого")
    output = "".join(part["text"] for part in parts
                     if isinstance(part, dict) and isinstance(part.get("text"), str) and not part.get("thought"))
    if not output:
        raise ValueError("Gemini API вернул пустой ответ")
    return json.loads(output)
