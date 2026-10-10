"""Gemini REST API. Credentials are sent only in the Google API-key header."""
import json
import os
import re
import httpx

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


def error_description(response):
    """Only display fixed interpretations of known codes, never raw server text."""
    status = response.status_code
    hints = {400: "Проверьте API-ключ, модель и параметры запроса.",
             401: "Проверьте GEMINI_API_KEY.",
             403: "Проверьте права ключа и доступность Gemini API в вашем регионе.",
             404: "Модель не найдена или недоступна этому ключу.",
             429: "Исчерпана квота или превышена частота запросов. Проверьте лимиты в Google AI Studio.",
             503: "Сервис временно недоступен. Повторите позже."}
    reasons = {
        "API_KEY_INVALID": "Google отклонил API-ключ как недействительный. Скопируйте ключ заново из Google AI Studio, без кавычек и пробелов.",
        "API_KEY_EXPIRED": "Срок действия API-ключа истёк. Создайте новый ключ в Google AI Studio.",
        "API_KEY_SERVICE_BLOCKED": "Ограничения ключа запрещают Gemini API. Проверьте разрешённые API для ключа.",
        "API_KEY_HTTP_REFERRER_BLOCKED": "Ключ ограничен веб-сайтами и не подходит для Python сервера. Проверьте ограничения ключа.",
        "API_KEY_IP_ADDRESS_BLOCKED": "Запрос отклонён ограничением IP-адресов ключа.",
        "API_KEY_PROJECT_INVALID": "Проект API-ключа недействителен. Проверьте проект в Google AI Studio.",
        "SERVICE_DISABLED": "Gemini API отключён в проекте ключа. Проверьте настройки проекта Google.",
        "CONSUMER_SUSPENDED": "Проект ключа приостановлен. Проверьте его состояние в Google.",
        "BILLING_DISABLED": "Google требует проверить условия биллинга этого проекта. Приложение не включает платный тариф автоматически.",
        "LOCATION_NOT_SUPPORTED": "Gemini API недоступен в регионе запроса."}
    description = hints.get(status, "Проверьте доступность сервиса Google.")
    code = None
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            details = error.get("details")
            if isinstance(details, list):
                code = next((entry.get("reason") for entry in details
                             if isinstance(entry, dict) and entry.get("reason") in reasons), None)
            if code:
                description = reasons[code]
            elif error.get("status") == "FAILED_PRECONDITION":
                code = "FAILED_PRECONDITION"
                description = "Google сообщает о невыполненном условии доступа. Проверьте доступность API в вашем регионе и условия проекта/тарифа."
    except (ValueError, TypeError):
        pass
    return f"Gemini API: HTTP {status}" + (f" [{code}]" if code else "") + f". {description}"


def available_models(key):
    """List model metadata without generating text or putting the key in the URL."""
    names, tokens = set(), set()
    token = None
    while True:
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        response = httpx.get(ENDPOINT, headers={"x-goog-api-key": key}, params=params, timeout=30)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("models"), list):
            raise ValueError("Gemini API вернул неверный список моделей")
        for item in body["models"]:
            if not isinstance(item, dict):
                continue
            methods = item.get("supportedGenerationMethods")
            name = item.get("name")
            if isinstance(name, str) and isinstance(methods, list) and "generateContent" in methods:
                name = name.removeprefix("models/")
                if re.fullmatch(r"[A-Za-z0-9._-]+", name):
                    names.add(name)
        token = body.get("nextPageToken")
        if not token:
            return sorted(names)
        if not isinstance(token, str) or token in tokens or len(tokens) >= 20:
            raise ValueError("Gemini API не завершил выдачу списка моделей")
        tokens.add(token)
