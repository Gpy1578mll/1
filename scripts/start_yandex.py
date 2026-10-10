"""Windows console launcher for YandexGPT; the API key is never written to disk."""
import getpass
import os
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx
import uvicorn
from app import yandex


def main():
    os.chdir(ROOT)
    print('YandexGPT: текст документов отправляется Yandex Cloud.')
    print('Проверьте тариф и пробный грант. Бесплатная работа не гарантируется.')
    os.environ['LLM_PROVIDER'] = 'yandex'
    if not os.getenv('YANDEX_FOLDER_ID', '').strip():
        os.environ['YANDEX_FOLDER_ID'] = input('Введите ID каталога Yandex Cloud: ').strip()
    if not os.getenv('YANDEX_API_KEY', '').strip():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                os.environ['YANDEX_API_KEY'] = getpass.getpass('Введите секретный API-ключ Yandex Cloud (ввод скрыт): ').strip()
        except getpass.GetPassWarning:
            print('Скрытый ввод недоступен. Используйте обычный терминал или переменную YANDEX_API_KEY.')
            return 1
    if not os.getenv('YANDEX_MODEL', '').strip():
        os.environ['YANDEX_MODEL'] = 'yandexgpt/latest'
    try:
        yandex.check_access()
    except httpx.HTTPStatusError as exc:
        print(yandex.error_description(exc.response))
        return 1
    except httpx.RequestError:
        print('Не удалось подключиться к YandexGPT. Проверьте доступ к llm.api.cloud.yandex.net.')
        return 1
    except ValueError as exc:
        print(str(exc))
        return 1
    print('Проверка API выполнена без генерации ответа. JSON-распознавание проверяется при загрузке документа.')
    print('Откройте http://127.0.0.1:8000. Для остановки нажмите Ctrl+C.')
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nЗапуск остановлен.')
