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

if sys.platform == "darwin":
    from AppKit import NSWorkspace, NSApplicationActivateIgnoringOtherApps
elif sys.platform == "win32":
    import pygetwindow as gw
    from pywinauto.application import Application

import time
import pygame
import edge_tts
from io import BytesIO
import asyncio
import json
import discord


# Инициализация звука
pygame.mixer.init()

# Открываем и читаем файл config.json
with open('config.json', 'r', encoding="UTF-8") as config_file:
    config = json.load(config_file)

# Задаем список целевых приложений
target_apps = config.get('target_apps', ["Visual Studio Code"])
# Время бездействия в "нецелевых" окнах перед напоминанием, в секундах
reminder_interval = config.get('reminder_interval', 30)
# Время бездействия перед отправкой запроса к AI (punishment), в секундах
punishment_interval = config.get('punishment_interval', 60)
# Голос edge_tts
edge_tts_voice = config.get('edge_tts_voice', "ru-RU-SvetlanaNeural")
# Загрузка промпта
ext_prompt = config.get('prompt', "You are helpfull assistant")
# Загрузка сабпромпта для наказания
punishment_subprompt = config.get('punishment_subprompt', "\n\nUser: Я отвлекся от своей работы в окне '{}' и переключился на '{}' без нужды.\nЕва:")
# Загрузка сабпромпта для похвалы
praise_subprompt = config.get('praise_subprompt', "\n\nUser: Я работал сфокусированно в окне '{}' без отвлечений целых '{}' секунд!\nЕва:")
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
# Переменная для хранения последнего активного целевого окна
last_target_window = None

# Чтение уровня дебага
debug_level = config.get('debug_level', 0)

# Функция для вывода сообщений в зависимости от уровня дебага
def log_message(level, message):
    if level <= debug_level:
        print(message)

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
    return None

# Функция для воспроизведения аудио файла
def play_reminder_sound():
    try:
        pygame.mixer.music.load(reminder_sound)
        pygame.mixer.music.play()
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

import edge_tts

# Функция для озвучивания текста
async def speak_text(text, voice):
    # Инициализация Pygame микшера для воспроизведения аудио
    pygame.mixer.init()
    
    # Используем edge-tts для генерации аудио
    tts = edge_tts.Communicate(text, voice=voice)
    
    # Получаем аудио в формате MP3 через асинхронный генератор
    audio = BytesIO()
    async for chunk in tts.stream():
        if chunk["type"] == "audio":
            audio.write(chunk["data"])
    
    # Перематываем поток в начало
    audio.seek(0)

    # Инициализация Pygame микшера для воспроизведения
    pygame.mixer.music.load(audio)
    pygame.mixer.music.play()

    # Ожидание завершения воспроизведения
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

import requests

# Функция для отправки запроса к локальному AI для "punishment" текста
async def generate_punishment_message(non_target_window, target_window):
    # Формируем prompt для запроса. Персонаж промпта выдуман и все совпадения случайны!
    prompt = ext_prompt + punishment_subprompt.format(target_window, non_target_window)
    await send_to_llama(prompt)

# Функция для похвалы за длительную работу без отвлечений
async def generate_praise_message(active_window):
    # Формируем prompt для запроса. Персонаж промпта выдуман и все совпадения случайны!
    prompt = ext_prompt + praise_subprompt.format(active_window, last_focus_time)
    await send_to_llama(prompt)

async def send_to_llama(prompt):
    try:
        # Данные для POST-запроса
        payload = {
            "stream": config.get("stream", False),
            "n_predict": config.get("n_predict", 400),
            "temperature": config.get("temperature", 0.7),
            "stop": config.get("stop", ["</s>", "Ева:", "Георгий:", "User:"]),
            "repeat_last_n": config.get("repeat_last_n", 256),
            "repeat_penalty": config.get("repeat_penalty", 1.18),
            "penalize_nl": config.get("penalize_nl", False),
            "top_k": config.get("top_k", 40),
            "top_p": config.get("top_p", 0.95),
            "min_p": config.get("min_p", 0.05),
            "tfs_z": config.get("tfs_z", 1),
            "typical_p": config.get("typical_p", 1),
            "presence_penalty": config.get("presence_penalty", 0),
            "frequency_penalty": config.get("frequency_penalty", 0),
            "mirostat": config.get("mirostat", 0),
            "mirostat_tau": config.get("mirostat_tau", 5),
            "mirostat_eta": config.get("mirostat_eta", 0.1),
            "grammar": config.get("grammar", ""),
            "n_probs": config.get("n_probs", 0),
            "min_keep": config.get("min_keep", 0),
            "image_data": config.get("image_data", []),
            "cache_prompt": config.get("cache_prompt", True),
            "api_key": config.get("api_key", ""),  # Можно добавить ключ API, если он есть
            "prompt": prompt
        }

        # URL-адрес для запроса
        url = "http://127.0.0.1:8080/completion"

        # Выполнение POST-запроса
        response = requests.post(url, json=payload)

        # Проверяем статус ответа
        if response.status_code == 200:
            # Получаем текст из ответа
            result = response.json()
            punishment_text = result.get("content", "").strip()  # Извлекаем текст ответа
            log_message(2, f"[AI RESPONSE] {punishment_text}")

            # Озвучиваем текст
            await speak_text(punishment_text, edge_tts_voice)
        else:
            log_message(1, f"[ERROR] Запрос вернул ошибку: {response.status_code}")

    except Exception as e:
        log_message(1, f"[ERROR] Ошибка при запросе к локальному AI: {e}")


status_focus = False
status_unfocus = False
async def main():
    global last_active_time, last_target_window, last_focus_time, start_focus_time, status_focus, status_unfocus  # Объявляем переменные глобальными
    # Основной цикл отслеживания окон
    while True:
        try:
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
                    if time_inactive >= punishment_interval:
                        # Сброс таймера фокусировки
                        last_focus_time = time.time()
                        start_focus_time = time.time()
                        # Генерация наказания через AI
                        switch_back_to_last_target()  # Переключаем обратно на последнее целевое окно
                        await generate_punishment_message(active_window, last_target_window)


                else:
                    # Если активное окно целевое, обновляем время последней активности и сохраняем его
                    last_active_time = time.time()
                    last_target_window = active_window

                    # Проверка, если пользователь долго работал без отвлечений
                    time_focused = time.time() - last_focus_time
                    log_message(2, f"[INFO] Целевое окно активно: {active_window}, {time_focused} секунд")
                    if time_focused >= praise_interval:
                        await generate_praise_message(active_window)
                        last_focus_time = time.time()  # Сброс времени после похвалы

                    status_unfocus = False
                    if not status_focus and discord_presence_state:
                        discord.restart_rpc(1133456581988732970, "Time in full focus:", "Focus State", int(time.mktime(time.localtime(start_focus_time))), "cat")
                        status_focus = True

            time.sleep(5)  # Интервал между проверками

        except Exception as e:
            log_message(1, f"[ERROR] Неожиданная ошибка: {e}")
            time.sleep(5)

# Запуск программы
if __name__ == "__main__":
    asyncio.run(main())
    discord.stop_rpc()