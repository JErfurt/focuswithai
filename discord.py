import discordrpc
from discordrpc.button import Button
import threading
import time

# Глобальная переменная для остановки потока
stop_event = threading.Event()
rpc = None

button = Button(
  button_one_label="Repository",
  button_one_url="https://github.com/JErfurt/focuswithai",
  button_two_label="Example",
  button_two_url="https://www.youtube.com/watch?v=AqjlrRfCPb8"
  )

# Функция для запуска Discord RPC
def start_rpc(app_id, state, details, _time, img):
    global rpc
    rpc = discordrpc.RPC(app_id=app_id)
    rpc.set_activity(
        state=state,
        details=details,
        large_image=img,
        large_text="https://github.com/JErfurt/focuswithai",
        # small_image="watching",
        # small_text="JE Focus Stats",
        ts_start=_time,
        buttons=button
    )

    # Пока не установлен флаг остановки, поддерживаем RPC сессию
    try:
        while not stop_event.is_set():
            # Просто выполняем паузу, чтобы поток не завершался мгновенно
            time.sleep(1)
    except Exception as e:
        print(f"Error in RPC thread: {e}")

# Функция для остановки RPC
def stop_rpc():
    if stop_event:
        stop_event.set()

# Функция для перезапуска RPC с новыми параметрами
def restart_rpc(app_id, state, details, _time, img):
    global stop_event

    # Останавливаем текущий поток RPC, если он есть
    stop_rpc()
    time.sleep(1)  # Небольшая задержка для завершения текущего потока

    # Создаем новый stop_event для нового запуска
    stop_event = threading.Event()
    rpc_thread = threading.Thread(target=start_rpc, args=(app_id, state, details, _time, img))
    rpc_thread.start()
    return rpc_thread

# Основной поток
if __name__ == "__main__":
    # Первый запуск
    rpc_thread = restart_rpc(1133456581988732970, "A super simple rpc", "simple RPC", int(time.mktime(time.localtime(time.time()))))

    # Даем поработать RPC некоторое время
    time.sleep(10)

    # Перезапуск RPC с новыми параметрами
    print("Restarting RPC with new parameters...")
    rpc_thread = restart_rpc(1133456581988732970, "New state", "Updated details", int(time.mktime(time.localtime(time.time()))))

    # Даем поработать RPC некоторое время
    time.sleep(10)

    # Остановка RPC перед завершением
    stop_rpc()
    print("RPC stopped.")
