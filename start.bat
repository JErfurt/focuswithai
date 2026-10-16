@echo off
chcp 65001 >nul
setlocal

rem ================== Настройки ==================
rem Папка с llama.cpp (llama-server.exe) и модель из её папки Models
set "LLAMA_DIR=C:\OtherPrograms\llama-b10727-bin-win-cuda-12.4-x64"
set "MODEL=Qwen3-4B-Q8_0.gguf"
rem Порт должен совпадать с openai_base_url в config.json
set "PORT=8080"
set "CTX=8192"
rem 1 = закрыть llama-server при выходе, если его запустил этот скрипт
set "STOP_SERVER_ON_EXIT=1"
rem ===============================================

cd /d "%~dp0"

rem --- Первый запуск: виртуальное окружение и зависимости ---
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Создаю виртуальное окружение .venv ...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo [ошибка] Не найден Python. Установите Python 3.10+ с python.org
        pause
        exit /b 1
    )
    echo [setup] Устанавливаю зависимости ...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

rem --- Silero: основной офлайн-голос. Нужен PyTorch, ставим CPU-сборку (~500 МБ),
rem --- а не CUDA (~2.5 ГБ): видеокарта остаётся под LLM, а на CPU Silero и так быстрый
if not exist ".venv\Lib\site-packages\torch" (
    echo [setup] Устанавливаю PyTorch для CPU, ~200 МБ загрузки ...
    ".venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
)
if not exist "voices\silero_v5_6_ru.pt" (
    echo [setup] Скачиваю модель Silero v5_6_ru, ~150 МБ ...
    if not exist voices mkdir voices
    curl -L --fail -o "voices\silero_v5_6_ru.pt" "https://models.silero.ai/models/tts/ru/v5_6_ru.pt" || (
        del "voices\silero_v5_6_ru.pt" 2>nul
        echo [setup] Не удалось скачать Silero, будут использованы другие голоса
    )
)

rem --- Офлайн-голос Piper (резерв, когда онлайн-озвучка Edge недоступна) ---
set "PIPER_URL=https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium"
if not exist "voices\ru_RU-irina-medium.onnx" (
    echo [setup] Скачиваю офлайн-голос Piper irina, ~60 МБ ...
    if not exist voices mkdir voices
    curl -L --fail -s -o "voices\ru_RU-irina-medium.onnx.json" "%PIPER_URL%/ru_RU-irina-medium.onnx.json"
    curl -L --fail -o "voices\ru_RU-irina-medium.onnx" "%PIPER_URL%/ru_RU-irina-medium.onnx" || (
        del "voices\ru_RU-irina-medium.onnx" 2>nul
        echo [setup] Не удалось скачать голос, офлайн-резервом будет голос Windows
    )
)

if not exist "config.json" (
    echo [ошибка] Нет config.json рядом со скриптом
    pause
    exit /b 1
)

rem --- llama-server: используем уже запущенный или поднимаем свой ---
set "STARTED_SERVER=0"
curl -s -f "http://127.0.0.1:%PORT%/health" >nul 2>&1
if not errorlevel 1 (
    echo [llama] Сервер на порту %PORT% уже запущен, используем его
    goto :run
)

if not exist "%LLAMA_DIR%\llama-server.exe" (
    echo [ошибка] Не найден %LLAMA_DIR%\llama-server.exe, поправьте LLAMA_DIR в start.bat
    pause
    exit /b 1
)
if not exist "%LLAMA_DIR%\Models\%MODEL%" (
    echo [ошибка] Не найдена модель %LLAMA_DIR%\Models\%MODEL%, поправьте MODEL в start.bat
    pause
    exit /b 1
)

echo [llama] Запускаю %MODEL% на порту %PORT% (свёрнутое окно) ...
start "llama-server %PORT%" /min /D "%LLAMA_DIR%" llama-server.exe -m "Models\%MODEL%" -ngl 99 -c %CTX% --jinja --port %PORT%
set "STARTED_SERVER=1"

rem Пока модель грузится, /health отвечает 503
for /l %%i in (1,1,180) do (
    curl -s -f "http://127.0.0.1:%PORT%/health" >nul 2>&1 && goto :ready
    rem Пауза 1 с; ping вместо timeout, потому что timeout падает без интерактивной консоли
    ping -n 2 127.0.0.1 >nul
)
echo [ошибка] Сервер не поднялся за 3 минуты, смотрите окно "llama-server %PORT%"
pause
goto :cleanup

:ready
echo [llama] Модель загружена

:run
echo [app] Запускаю workReminder. Остановка: Ctrl+C
".venv\Scripts\python.exe" main.py

:cleanup
if "%STARTED_SERVER%"=="1" if "%STOP_SERVER_ON_EXIT%"=="1" (
    echo [llama] Останавливаю llama-server ...
    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | Where-Object { $_.CommandLine -match '--port %PORT%' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
)
endlocal
