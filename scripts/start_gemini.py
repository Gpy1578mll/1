"""Interactive Windows-friendly launcher; never writes the API key to disk."""
import getpass
import os
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from app import gemini


def main():
    os.chdir(ROOT)
    print('Распознавание через Gemini API: текст документов отправляется Google.')
    print('Проверьте бесплатную квоту выбранной модели в Google AI Studio.')
    os.environ['LLM_PROVIDER'] = 'gemini'
    if not os.getenv('GEMINI_API_KEY', '').strip():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                os.environ['GEMINI_API_KEY'] = getpass.getpass('Введите API-ключ Gemini (ввод скрыт): ').strip()
        except getpass.GetPassWarning:
            print('Скрытый ввод недоступен. Запустите сценарий в обычном терминале или задайте GEMINI_API_KEY через окружение.')
            return 1
    # Check the key first: a models-list failure cannot be caused by a typed model name.
    try:
        key = gemini.api_key()
        models = gemini.available_models(key)
    except httpx.HTTPStatusError as exc:
        print(gemini.error_description(exc.response))
        return 1
    except httpx.RequestError:
        print('Не удалось подключиться к Gemini API. Проверьте интернет и доступ к generativelanguage.googleapis.com.')
        return 1
    except ValueError as exc:
        print(str(exc))
        return 1
    if not models:
        print('Для этого ключа не найдено моделей с поддержкой generateContent.')
        return 1
    selected = os.getenv('GEMINI_MODEL', '').strip().removeprefix('models/')
    if selected not in models:
        print('Доступные API-модели (наличие в списке не гарантирует бесплатную квоту):')
        for index, name in enumerate(models, 1):
            print(f'{index}. {name}')
        answer = input('Введите номер или точное имя текстовой модели с JSON-ответами: ').strip()
        if answer.isdecimal():
            index = int(answer) - 1
            selected = models[index] if 0 <= index < len(models) else ''
        else:
            selected = answer.removeprefix('models/')
        if selected not in models:
            print('Модель отсутствует в списке. Повторите запуск и выберите доступную модель.')
            return 1
    os.environ['GEMINI_MODEL'] = selected
    print('Доступ к модели проверен. Откройте в браузере http://127.0.0.1:8000')
    print('Для остановки нажмите Ctrl+C. Ключ не сохраняется в файлах.')
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nЗапуск остановлен.')
