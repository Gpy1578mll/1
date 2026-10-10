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
    if not os.getenv('GEMINI_MODEL', '').strip():
        os.environ['GEMINI_MODEL'] = input('Введите идентификатор модели из Google AI Studio: ').strip()
    try:
        model = gemini.model_name()
        key = gemini.api_key()
    except ValueError as exc:
        print(str(exc))
        return 1
    # Verify access and model availability without uploading a document.
    try:
        response = httpx.get(f'{gemini.ENDPOINT}/{model}', headers={'x-goog-api-key': key}, timeout=30)
        response.raise_for_status()
        metadata = response.json()
        methods = metadata.get('supportedGenerationMethods') if isinstance(metadata, dict) else None
        if not isinstance(methods, list) or 'generateContent' not in methods:
            print('Эта модель не поддерживает generateContent. Выберите текстовую модель Gemini.')
            return 1
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        hints = {400:'Проверьте API-ключ и идентификатор модели.',
                 401:'Проверьте API-ключ.',403:'Проверьте доступ ключа и доступность API в вашем регионе.',
                 404:'Модель не найдена. Проверьте её идентификатор.',429:'Превышена квота сервиса.'}
        print(f'Gemini API: HTTP {status}. ' + hints.get(status, 'Проверьте доступность сервиса Google.'))
        return 1
    except (httpx.RequestError, ValueError, AttributeError):
        print('Не удалось проверить Gemini API. Проверьте интернет и доступ к generativelanguage.googleapis.com.')
        return 1
    print('Доступ к модели проверен. Откройте в браузере http://127.0.0.1:8000')
    print('Для остановки нажмите Ctrl+C. Ключ не сохраняется в файлах.')
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nЗапуск остановлен.')
