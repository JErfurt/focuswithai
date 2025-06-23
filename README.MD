## STOP PROCRASTINATION
### BE PRODUCTIVE!

# Window Focus Reminder

Скрипт для отслеживания активных окон и напоминания пользователю о необходимости вернуться к рабочему окну.

## Возможности

- ✅ Отслеживание активных окон
- ✅ Звуковые напоминания при отвлечении
- ✅ Голосовые уведомления через Edge TTS
- ✅ Интеграция с AI для персонализированных сообщений
- ✅ Система сессий (фокус/отдых)
- ✅ Discord Rich Presence
- ✅ Поддержка разных AI провайдеров (Llama, Google Assistant)

## Поддерживаемые AI провайдеры

### 1. Llama (локальный)
Для использования локального Llama сервера:
```json
{
  "ai_provider": "llama",
  "llama_url": "http://127.0.0.1:8080/completion"
}
```

### 2. Google Assistant API
Для использования Google Assistant API:
```json
{
  "ai_provider": "google_assistant",
  "google_assistant_api_key": "YOUR_API_KEY",
  "google_project_id": "YOUR_PROJECT_ID"
}
```

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Настройте `config.json`:
   - Выберите AI провайдера (`ai_provider`)
   - Настройте параметры для выбранного провайдера
   - Укажите целевые приложения в `target_apps`

3. Создайте файл сессий `sessions.jsonl`:
```json
{"name": "Фокус", "focus": true, "min": 25}
{"name": "Отдых", "focus": false, "min": 5}
{"name": "Фокус", "focus": true, "min": 25}
```

## Использование

Запустите скрипт:
```bash
python main.py
```

## Конфигурация

### Основные параметры:
- `ai_provider`: Выбор AI провайдера (`llama` или `google_assistant`)
- `target_apps`: Список целевых приложений
- `reminder_interval`: Время до напоминания (секунды)
- `punishment_interval`: Время до AI-наказания (секунды)
- `praise_interval`: Время для похвалы (секунды)

### Параметры Llama:
- `llama_url`: URL локального Llama сервера
- `temperature`: Температура генерации
- `n_predict`: Максимальное количество токенов

### Параметры Google Assistant:
- `google_assistant_api_key`: API ключ Google
- `google_project_id`: ID проекта Google
- `google_max_tokens`: Максимальное количество токенов

## Структура файлов

```
workReminder/
├── main.py              # Основной скрипт
├── ai_client.py         # Модуль AI клиентов
├── config.json          # Конфигурация
├── sessions.jsonl       # Файл сессий
├── session_stats.json   # Статистика сессий
├── requirements.txt     # Зависимости
└── README.MD           # Документация
```

## Лицензия

MIT License

Python script to stay focus on applications for work.
One timer alert you every 5 second to get back to work,
second one uses AI to generate "Punishment" message
third one pushes AI to generate "Praise" message.

***I was abandoned by one of my friends and no one can moral support me to work so I was trying enchanse my AI interface that was too much work, but one day I found out this solution and make it in one python script.*** 

*Hope u'll well stay focus!*

*JErfurt*

[YT video (old)](https://www.youtube.com/watch?v=AqjlrRfCPb8)

## Installation
Use Conda or Venv for reqs don't make mess with system. 
As an AI backend I use llama.cpp server, please checkout [llama.cpp](https://github.com/ggerganov/llama.cpp) it's incredibly easy to use!

**Okay, I'll add simple step-by-step guide for windows**

Copy repository, unpack, open folder with CMD

Create virtual environment
```
python -m venv venv
```
Apply environment
```
venv\Scripts\activate
```
Install dependencies
```
pip install -r requirements.txt
```
Go to [llama.cpp/releases](https://github.com/ggerganov/llama.cpp/releases) and download "..cu.." if you have CUDA or avx2 if only CPU or other compatible for your system, ok?.

Unpack llama.cpp release some where and you can start llama-server.exe with some params, but not that fast.

Firstly find some llama .GGUF models on [HuggingFace](https://huggingface.co/) recomend llama-3B, I hope I don't need to explain about quantization in here, if you need it find it with your self.

Finally start server and then main.py

If have CUDA set --n-gpu-layers
```
llama-server.exe -m Models/NAME_OF_YOUR_MODEL.gguf --n-gpu-layers 29 --split-mode layer --main-gpu 0 --ctx-size 4096
```

If CPU only
```
llama-server.exe -m Models/NAME_OF_YOUR_MODEL.gguf --ctx-size 4096
```

If you lose python virtual environment, let's get back to it
```
venv\Scripts\activate
```

Run main.py
```
python main.py
```

### It's easy to init, anyway I did some explain
