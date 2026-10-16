# ---------------------------------------------------------------
# Скрипт: Window Focus Reminder
# Автор: JErfurt
# Дата: 16 октября 2024 года
# Описание: Скрипт отслеживает активные окна и напоминает пользователю
#           о необходимости вернуться к рабочему окну, если он отвлекся.
#
# Лицензия: MIT License
#
# Copyright (c) 2024 JErfurt
#
# Данная работа предоставляется "как есть", без каких-либо гарантий.
# Вы можете использовать, копировать, изменять и распространять её 
# для любых целей при указании оригинального автора.
#
# Этот проект использует библиотеки, лицензированные под MIT, BSD и LGPL лицензиями.
# ---------------------------------------------------------------

import sys
import signal

if sys.platform == "darwin":
    from AppKit import NSWorkspace, NSApplicationActivateIgnoringOtherApps
elif sys.platform == "win32":
    import pygetwindow as gw
    from pywinauto.application import Application

import time
import pygame
from tts import Speaker
import asyncio
import json
from dataclasses import dataclass
import logging
import discord
from ai_client import AIClientFactory
from assistant import FocusAssistant


# Открываем и читаем файл config.json
with open('config.json', 'r', encoding="UTF-8") as config_file:
    config = json.load(config_file)

# Инициализация звука. Дефолтный буфер pygame (512 сэмплов, ~11 мс) на Windows
# даёт потрескивание, а 48 кГц совпадает с частотой большинства устройств,
# поэтому системе не приходится пересэмплировать звук ещё раз.
pygame.mixer.pre_init(
    frequency=config.get('audio_frequency', 48000),
    size=-16,
    channels=2,
    buffer=config.get('audio_buffer', 2048),
)
pygame.mixer.init()

# Инициализация AI клиента
ai_client = AIClientFactory.create_client(config)

# Задаем список целевых приложений
target_apps = config.get('target_apps', ["Visual Studio Code"])
# Время бездействия в "нецелевых" окнах перед напоминанием, в секундах
reminder_interval = config.get('reminder_interval', 30)
# Время бездействия перед отправкой запроса к AI (punishment), в секундах
punishment_interval = config.get('punishment_interval', 60)
# Время интерестных фактов
interesting_fact_interval = config.get('interesting_fact_interval', 60)
# Минимальная пауза между AI-наказаниями, в секундах
punishment_cooldown = config.get('punishment_cooldown', punishment_interval)
# Звук предупреждения
reminder_sound = config.get('reminder_sound', 'H_WARNING.mp3')
# Время без отвлечений перед похвалой, в секундах
praise_interval = config.get('praise_interval', 1800)  # Например, 30 минут
# discord presence
discord_presence_state = config.get('discord_presence', False)

# Переменная для хранения времени начала фокусированного состояния
start_focus_time = time.time()
# Переменная для хранения времени последнего фокусированного состояния
last_focus_time = time.time()
# Время последнего бездействия
last_active_time = time.time()
# Время последнего факта
last_interesting_fact = time.time()
# Время последнего AI-наказания
last_punishment_time = 0
# Время начала текущей сессии
last_session_time = time.time()
# Индекс сессии
session_index = 0
# Статистика сессий
session_stats = {
    "total_focus_time": 0,
    "total_break_time": 0,
    "completed_sessions": 0,
    "current_session_start": time.time()
}

# Переменная для хранения последнего активного целевого окна
last_target_window = None

# Чтение уровня дебага
debug_level = config.get('debug_level', 0)

# Функция для вывода сообщений в зависимости от уровня дебага
def log_message(level, message):
    if level <= debug_level:
        print(message)

# Логи модулей ai_client/assistant выводятся по тому же уровню дебага
logging.basicConfig(
    level={0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO}.get(debug_level, logging.DEBUG),
    format="[%(levelname)s] %(message)s",
)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("comtypes").setLevel(logging.WARNING)

# Функция для проверки текущего активного окна
def get_active_window_title():
    if sys.platform == "darwin":
        active_app = NSWorkspace.sharedWorkspace().activeApplication()
        app_name = active_app['NSApplicationName']
        return app_name
    elif sys.platform == "win32":
        window = gw.getActiveWindow()
        if window:
            return window.title
    raise Exception("Unsupported platform")

# Звук напоминания декодируется один раз и играет на своём канале:
# не пересэмплируется на лету и не обрывает речь ассистента
_reminder = {"sound": None, "channel": None}

# Функция для воспроизведения аудио файла
def play_reminder_sound():
    try:
        if _reminder["sound"] is None:
            _reminder["sound"] = pygame.mixer.Sound(reminder_sound)
            _reminder["sound"].set_volume(config.get('reminder_volume', 1.0))
        channel = _reminder["channel"]
        if channel is not None and channel.get_busy():
            return  # прошлое напоминание ещё звучит, не перезапускаем
        _reminder["channel"] = _reminder["sound"].play()
        log_message(2, "[INFO] Напоминание: Воспроизведение звука.")
    except Exception as e:
        log_message(1, f"[ERROR] Ошибка при воспроизведении звука: {e}")

# Функция для переключения обратно на последнее целевое окно
def switch_back_to_last_target():
    global last_target_window
    if last_target_window:
        log_message(2, f"[INFO] Попытка переключиться на последнее активное окно: {last_target_window}")
        try:
            if sys.platform == "darwin":
                # Получаем список всех запущенных приложений
                running_apps = NSWorkspace.sharedWorkspace().runningApplications()
                
                find = False
                for app in running_apps:
                    if app.localizedName() == last_target_window:
                        # Если имя приложения совпадает, активируем его
                        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                        find = True
                        break
                if not find:
                    raise Exception("Приложение не найдено")
            elif sys.platform == "win32":
                # Подключаемся к окну через pywinauto
                app_window = Application(backend='uia').connect(title=last_target_window, timeout=10)
                app_window.top_window().set_focus()
            
            log_message(2, f"[INFO] Успешно переключились на окно: {last_target_window}")

        except Exception as e:
            log_message(1, f"[ERROR] Ошибка при переключении на {last_target_window}: {e}")
    else:
        log_message(2, "[INFO] Последнее целевое окно не найдено. Невозможно переключиться.")

# Озвучивание: цепочка движков edge -> piper -> sapi (см. tts.py)
speaker = Speaker(config)

async def speak_text(text):
    await speaker.speak(text)

# AI ассистент: промпты, контекст, память диалога и озвучивание ответов
assistant = FocusAssistant(ai_client, config, speak_text)

@dataclass
class MyData:
    name: str
    focus: bool
    min: int

class CachedJSONLReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.cache = {}
    
    def get_line_by_index(self, index):
        if index in self.cache:
            return self.cache[index]
        
        with open(self.file_path, 'r', encoding='utf-8') as file:
            for i, line in enumerate(file):
                if i == index:
                    self.cache[index] = MyData(**json.loads(line))
                    return self.cache[index]
        return None  # Cтрока с таким индексом не найдена
    
session_reader = CachedJSONLReader("sessions.jsonl")

def save_session_stats():
    """Сохраняет статистику сессий в файл"""
    try:
        with open('session_stats.json', 'w', encoding='utf-8') as f:
            json.dump(session_stats, f, ensure_ascii=False, indent=2)
        log_message(2, "[INFO] Статистика сессий сохранена")
    except Exception as e:
        log_message(1, f"[ERROR] Ошибка при сохранении статистики: {e}")

def load_session_stats():
    """Загружает статистику сессий из файла"""
    try:
        with open('session_stats.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "total_focus_time": 0,
            "total_break_time": 0,
            "completed_sessions": 0,
            "current_session_start": time.time()
        }
    except Exception as e:
        log_message(1, f"[ERROR] Ошибка при загрузке статистики: {e}")
        return {
            "total_focus_time": 0,
            "total_break_time": 0,
            "completed_sessions": 0,
            "current_session_start": time.time()
        }

# Загружаем статистику при запуске
session_stats = load_session_stats()

status_focus = False
status_unfocus = False

# Флаг для корректного завершения
shutdown_flag = False

def signal_handler(signum, frame):
    """Обработчик сигналов для корректного завершения"""
    global shutdown_flag
    log_message(1, "[INFO] Получен сигнал остановки. Завершаем работу...")
    shutdown_flag = True

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def main():
    global last_active_time, last_target_window, last_focus_time, start_focus_time, status_focus, status_unfocus, last_interesting_fact, last_session_time, session_index, session_stats, shutdown_flag, last_punishment_time  # Объявляем переменные глобальными
    available_providers = await AIClientFactory.get_available_providers(config)
    log_message(1, f"[INFO] Доступные AI провайдеры: {available_providers}")
    # Основной цикл отслеживания окон
    while not shutdown_flag:
        try:
            current_sesion = session_reader.get_line_by_index(session_index)
            if(current_sesion == None):
                # Все сессии завершены
                log_message(1, f"[INFO] Все сессии завершены! Статистика: {session_stats}")
                # Можно добавить уведомление или перезапуск
                session_index = 0
                session_stats = {
                    "total_focus_time": 0,
                    "total_break_time": 0,
                    "completed_sessions": 0,
                    "current_session_start": time.time()
                }
                last_session_time = time.time()
                continue
                
            current_session_time = int((time.time() - last_session_time)/60)
            assistant.set_session(current_sesion.name, current_session_time, current_sesion.min, current_sesion.focus)
            if(current_session_time >= current_sesion.min):
                # Сессия завершена
                session_stats["completed_sessions"] += 1
                if current_sesion.focus:
                    session_stats["total_focus_time"] += current_sesion.min
                    log_message(1, f"[INFO] Фокусная сессия завершена: {current_sesion.min} минут")
                    assistant.log_event(f"завершена фокус-сессия на {current_sesion.min} мин")
                    # Можно добавить уведомление о завершении фокусной сессии
                    await speak_text(f"Отличная работа! Фокусная сессия на {current_sesion.min} минут завершена.")
                else:
                    session_stats["total_break_time"] += current_sesion.min
                    log_message(1, f"[INFO] Сессия отдыха завершена: {current_sesion.min} минут")
                    assistant.log_event(f"закончился отдых {current_sesion.min} мин, снова работа")
                    # Можно добавить уведомление о завершении отдыха
                    await speak_text(f"Отдых завершен. Возвращаемся к работе!")
                
                # Сохраняем статистику
                save_session_stats()
                
                session_index += 1
                last_session_time = time.time()
                if current_sesion.focus:
                    assistant.reset_session_stats()
                session_stats["current_session_start"] = time.time()
                continue
                
            if(not current_sesion.focus):
                log_message(2, f"[INFO] Отдых: {current_session_time} из {current_sesion.min} минут")
                # Проверяем флаг завершения каждую секунду
                for _ in range(60):
                    if shutdown_flag:
                        break
                    await asyncio.sleep(1)
                continue

            # Отображаем прогресс текущей фокусной сессии
            log_message(2, f"[INFO] Фокусная сессия: {current_session_time} из {current_sesion.min} минут")

            active_window = get_active_window_title()

            if active_window:
                log_message(3, f"[DEBUG] Активное окно: {active_window}")

                # Если активное окно не целевое, увеличиваем таймер
                if not any(app in active_window for app in target_apps):
                    time_inactive = time.time() - last_active_time
                    log_message(3, f"[DEBUG] Время нецелевого окна: {time_inactive} секунд.")

                    # Проверяем, сколько времени прошло с последней активности в целевом приложении
                    if time_inactive >= reminder_interval:
                        play_reminder_sound()  # Воспроизводим напоминание
                        status_focus = False
                        if not status_unfocus and discord_presence_state:
                            discord.restart_rpc(1133456581988732970, "Time in full focus:", "Unfocus State", int(time.mktime(time.localtime(start_focus_time))), "fix")
                            status_unfocus = True
                    if time_inactive >= punishment_interval and time.time() - last_punishment_time >= punishment_cooldown:
                        # Сброс таймера фокусировки
                        last_focus_time = time.time()
                        start_focus_time = time.time()
                        # Генерация наказания через AI
                        switch_back_to_last_target()  # Переключаем обратно на последнее целевое окно
                        await assistant.punish(active_window, last_target_window, time_inactive)
                        last_punishment_time = time.time()


                else:
                    # Если активное окно целевое, обновляем время последней активности и сохраняем его
                    last_active_time = time.time()
                    last_target_window = active_window

                    # Проверка, если пользователь долго работал без отвлечений
                    time_focused = time.time() - last_focus_time
                    log_message(2, f"[INFO] Целевое окно активно: {active_window}, {time_focused} секунд")
                    if time_focused >= praise_interval:
                        await assistant.praise(active_window, time_focused)
                        last_focus_time = time.time()  # Сброс времени после похвалы


                    status_unfocus = False
                    if not status_focus and discord_presence_state:
                        discord.restart_rpc(1133456581988732970, "Time in full focus:", "Focus State", int(time.mktime(time.localtime(start_focus_time))), "cat")
                        status_focus = True
                        
                time_fact = time.time() - last_interesting_fact
                if time_fact >= interesting_fact_interval:
                    await assistant.fact()
                    last_interesting_fact = time.time()

            await asyncio.sleep(5)  # Интервал между проверками

        except Exception as e:
            log_message(1, f"[ERROR] Неожиданная ошибка: {e}")
            await asyncio.sleep(5)

        if shutdown_flag:
            break

    log_message(1, "[INFO] Приложение завершено корректно.")
    await ai_client.close()
    discord.stop_rpc()

# Запуск программы
if __name__ == "__main__":
    asyncio.run(main())