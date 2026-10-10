"""YandexGPT synchronous Foundation Models REST API."""
import json
import os
import re
import httpx

BASE_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1"

def folder_id():
    value = os.getenv("YANDEX_FOLDER_ID", "").strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Задайте YANDEX_FOLDER_ID: идентификатор каталога Yandex Cloud")
    return value

def model_name():
    model = os.getenv("YANDEX_MODEL", "yandexgpt/latest").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", model):
        raise ValueError("YANDEX_MODEL должен иметь вид yandexgpt/latest")
    return f"gpt://{folder_id()}/{model}"

def api_key():
    value = os.getenv("YANDEX_API_KEY", "").strip()
    if not value:
        raise ValueError("Задайте YANDEX_API_KEY: секретный API-ключ сервисного аккаунта Yandex Cloud")
    return value

def headers():
    return {"Authorization": "Api-Key " + api_key(), "x-folder-id": folder_id(),
            "x-data-logging-enabled": "false"}

def error_description(response):
    hints = {
        400: "Проверьте идентификатор каталога, имя модели и поддержку JSON-схемы.",
        401: "Yandex Cloud отклонил авторизацию. Нужен секретный API-ключ, а не его ID или ключ Gemini.",
        403: "Проверьте права сервисного аккаунта на каталог, область действия API-ключа и состояние биллинга.",
        404: "Каталог, модель или API не найдены. Проверьте YANDEX_FOLDER_ID и YANDEX_MODEL.",
        429: "Превышена квота или частота запросов Yandex Cloud. Автоматических повторов нет.",
        503: "Сервис временно недоступен. Повторите позже."}
    return f"YandexGPT API: HTTP {response.status_code}. " + hints.get(response.status_code, "Проверьте доступность сервиса Yandex Cloud.")

def access_error_description(response):
    """Expose a scrubbed message only for the fixed, document-free startup probe."""
    description = error_description(response)
    if response.status_code == 400:
        description = "YandexGPT API: HTTP 400. Проверьте каталог, API-ключ и имя модели. Проверка доступа не содержит JSON-схему."
    # The startup request contains no operator document. The provider's message
    # helps diagnose catalog/auth/model problems; redact keys before displaying.
    try:
        body = response.json()
        # Error gateways can return strings, differently named JSON fields or
        # plain text. This fallback is restricted to the document-free probe.
        message = json.dumps(body, ensure_ascii=False)
        if isinstance(body, dict):
            for field in ("message", "error", "detail", "description"):
                value = body.get(field)
                if isinstance(value, str) and value.strip():
                    message = value
                    break
                if isinstance(value, dict):
                    message = json.dumps(value, ensure_ascii=False)
                    break
        elif isinstance(body, str):
            message = body
    except (ValueError, TypeError):
        message = response.text
    secret = os.getenv("YANDEX_API_KEY", "").strip()
    if secret:
        message = message.replace(secret, "[ключ скрыт]")
    message = re.sub(r"[A-Za-z0-9_+/=-]{24,}", "[идентификатор скрыт]", message)
    message = " ".join(message.split())[:600]
    description += " Сообщение Яндекса: " + (message or "пустой ответ сервера")
    return "Проверка доступа (tokenizeCompletion). " + description

def check_access():
    # Tokenization verifies the selected API/model access without generating a completion.
    response = httpx.post(BASE_URL + "/tokenizeCompletion", headers=headers(), timeout=30,
                          json={"modelUri": model_name(), "messages": [{"role": "user", "text": "Проверка подключения"}]})
    response.raise_for_status()

async def generate(client, prompt, text, schema):
    response = await client.post(BASE_URL + "/completion", json={
        "modelUri": model_name(),
        "completionOptions": {"stream": False, "temperature": 0, "maxTokens": "4096"},
        "messages": [{"role": "system", "text": prompt}, {"role": "user", "text": text}],
        "jsonSchema": {"schema": schema}})
    response.raise_for_status()
    body = response.json()
    result = body.get("result") if isinstance(body, dict) else None
    alternatives = result.get("alternatives") if isinstance(result, dict) else None
    if not isinstance(alternatives, list) or not alternatives or not isinstance(alternatives[0], dict):
        raise ValueError("YandexGPT API не вернул ожидаемые result.alternatives")
    candidate = alternatives[0]
    status = candidate.get("status")
    if status != "ALTERNATIVE_STATUS_FINAL":
        if status == "ALTERNATIVE_STATUS_TRUNCATED_FINAL":
            raise ValueError("Ответ YandexGPT не завершён: достигнут лимит токенов")
        if status == "ALTERNATIVE_STATUS_CONTENT_FILTER":
            raise ValueError("YandexGPT остановил ответ по ограничениям сервиса. Результаты не сохранены")
        raise ValueError("YandexGPT не завершил ответ")
    message = candidate.get("message")
    output = message.get("text") if isinstance(message, dict) else None
    if not isinstance(output, str) or not output:
        raise ValueError("YandexGPT API вернул ответ без текста")
    return json.loads(output)
