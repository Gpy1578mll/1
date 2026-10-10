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

## Если сервер завершается с кодом -1073741795

Код Windows `0xC000001D` означает недопустимую инструкцию. На SQ1 запуск `--version` прошёл, но инициализация сервера завершилась с этим кодом. Это не подтверждает совместимость готового архива с SQ1. В исходниках проверенного commit `abee0c847` файл `cmake/arm64-windows-llvm.cmake` устанавливает глобальный `-march=armv8.7-a`; это согласуется с несовместимостью на более старом SQ1, хотя конкретная аварийная инструкция не определена отладчиком.

Нужна сборка с более низким базовым набором инструкций. Следующие команды подготовлены по официальным CMake-настройкам; в облачной Linux-среде Windows-сборка и её запуск не выполнялись.

1. Установите Visual Studio 2022 Build Tools с рабочей нагрузкой C++ и компонентами ARM64 C++ build tools, Windows SDK, CMake, Clang compiler и Ninja. Официальная документация сборки: https://github.com/ggml-org/llama.cpp/blob/b11550/docs/build.md .
2. Скачайте исходники https://github.com/ggml-org/llama.cpp/archive/refs/tags/b11550.zip и распакуйте в отдельную папку, например `C:\Projects\llama.cpp-b11550`.
3. Откройте ARM64 Native Tools Command Prompt for VS 2022 и перейдите в папку исходников. Убедитесь, что доступны `cmake` и `clang`. Не используйте обычный MSVC для этой конфигурации: upstream требует Clang для `GGML_NATIVE=OFF` на ARM.
4. Настройте отдельный каталог сборки, явно заменяя глобальные флаги toolchain:

```bat
cmake --preset arm64-windows-llvm-release -DCMAKE_C_FLAGS="-march=armv8-a" -DCMAKE_CXX_FLAGS="-march=armv8-a" -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8-a -DGGML_CPU_ALL_VARIANTS=OFF -DGGML_CPU_KLEIDIAI=OFF -DGGML_OPENMP=OFF
cmake --build build-arm64-windows-llvm-release --target llama-server -j 2
```

Если конфигурация не завершилась успешно, остановитесь и разберите ошибку — запуск сборки после неудачной конфигурации не является проверкой.

5. Найдите созданный `llama-server.exe` в каталоге сборки, оставьте его DLL рядом. Сначала проверьте `--version`, затем запуск GGUF и `/health`. Не смешивайте DLL нового и прежнего архивов. Сборка отключает дополнительные ускорения и может работать медленнее.
