# llama.cpp на Windows ARM64 (Microsoft SQ1)

LM Studio на проверяемом компьютере не нашла совместимого GGUF runtime. Используем отдельный `llama-server` с CPU. Совместимость готовой сборки с SQ1 нужно проверить на самом компьютере — облачная Linux-среда этого не подтверждает.

## Сборка и проверка

Официальный репозиторий: https://github.com/ggml-org/llama.cpp/releases/tag/b11550

Проверенный адрес архива Windows CPU ARM64:
https://github.com/ggml-org/llama.cpp/releases/download/b11550/llama-b11550-bin-win-cpu-arm64.zip

Распакуйте **весь** архив в `C:\Tools\llama-cpp`. DLL должны остаться вместе с EXE. Если Windows сообщает о недостающих библиотеках Visual C++, установите официальный Visual C++ Redistributable ARM64: https://aka.ms/vs/17/release/vc_redist.arm64.exe. Ранее установленный x64 runtime для Python не удаляйте.

В PowerShell:

```powershell
cd "C:\Tools\llama-cpp"
.\llama-server.exe --version
```

Если EXE находится во вложенной папке, перейдите в неё. Ошибка запуска на этом этапе — отдельный блокер; пока не пытайтесь запускать модель.

## Модель

Нужен локальный файл Qwen2.5-1.5B-Instruct GGUF Q4_K_M. Файл, уже скачанный LM Studio, можно использовать напрямую: найдите его в Library через доступное действие открытия папки модели. Не меняйте расширение другого формата на GGUF. Скопируйте полный путь к `.gguf`.

Остановите API-сервер LM Studio, чтобы освободить порт 1235. Запустите в PowerShell, заменив путь к модели:

```powershell
.\llama-server.exe -m "C:\Models\qwen2.5-1.5b-instruct-q4_k_m.gguf" --alias qwen-local --host 127.0.0.1 --port 1235 -c 4096 -t 4 -ngl 0
```

4096 — начальный размер контекста, 4 — число CPU потоков, `-ngl 0` отключает перенос слоёв на GPU. Для короткого контрольного документа этого достаточно; длинные фрагменты вместе с промптом могут превысить контекст. Не запускайте одновременно вторую копию модели в LM Studio. Окно сервера оставьте открытым. На SQ1 скорость нужно измерить, она заранее не установлена.

В другом PowerShell проверьте:

```powershell
Invoke-RestMethod "http://localhost:1235/health"
(Invoke-RestMethod "http://localhost:1235/v1/models").data | Select-Object id
```

Дождитесь готовности сервера: `/health` должен сообщить `ok`, идентификатор модели — `qwen-local`.

## Приложение

Существующий клиент использует OpenAI-совместимый API, поэтому подходит и для llama.cpp. Имена переменных `LM_STUDIO_*` сохраняются для совместимости, но теперь указывают на сервер llama.cpp.

```powershell
cd "C:\Projects\1-main"
$env:LM_STUDIO_URL="http://localhost:1235/v1"
$env:LM_STUDIO_MODEL="qwen-local"
$env:LM_STUDIO_TIMEOUT="600"
.\.venv312\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте страницу приложения на порту 8000. Загрузите короткий TXT с известными ФИО, датой рождения и организацией. Проверьте ответ модели, исправьте сведения и нажмите OK. До подтверждения данные в SQLite не сохраняются. Если возникает HTTP 400, проверьте журнал llama-server: увеличение тайм-аута не решает ошибки схемы или контекста.

## Что подтверждено

Адрес официальной ARM64 CPU-сборки и наличие `llama-server.exe` в архиве проверены. Запуск Windows ARM64 EXE, модели на SQ1 и распознавание реальным llama-server в облачной Linux-среде не проверены. Нужны локальные проверки выше. Надписи LM Studio в диагностике приложения пока относятся к выбранному совместимому LLM API и не означают, что обязательно используется LM Studio.
