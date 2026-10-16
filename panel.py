# ---------------------------------------------------------------
# Веб-панель workReminder
# Описание: локальный веб-сервер (только 127.0.0.1), через который
#           настраиваются config.json, sessions.jsonl и память ассистента.
#   - внутри main.py: видит живое состояние трекера и управляет им
#     (пауза, пропуск блока, перезапуск);
#   - отдельно (python panel.py): только редактирование файлов.
# ---------------------------------------------------------------

import asyncio
import copy
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
from collections import deque
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import web

CONFIG_FILE = 'config.json'
SESSIONS_FILE = 'sessions.jsonl'
STATS_FILE = 'session_stats.json'
BACKUP_DIR = 'backups'
SOUNDS_DIR = 'sounds'
BACKUPS_KEPT = 10
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'panel_web')

DEFAULT_PORT = 8765
# Код выхода, по которому main.py перезапускает сам себя
RESTART_CODE = 75

# Ключи API в панель не отдаются, вместо них приходит маска
SECRET_KEYS = ('api_key', 'openai_api_key', 'google_assistant_api_key')
MASK = '••••••••'

TTS_ENGINES = ('silero', 'edge', 'piper', 'sapi')


# ---------- захват вывода для просмотра логов в панели ----------

class LogBuffer:
    LEVEL_RE = re.compile(r"\[(ERROR|WARNING|WARN|INFO|DEBUG)\b")

    def __init__(self, size: int = 500):
        self.lines: deque = deque(maxlen=size)
        self.seq = 0
        self._lock = threading.Lock()

    def add(self, text: str):
        with self._lock:
            for line in text.splitlines():
                if not line.strip():
                    continue
                match = self.LEVEL_RE.search(line)
                level = match.group(1) if match else 'INFO'
                self.seq += 1
                self.lines.append((self.seq, time.time(), 'WARNING' if level == 'WARN' else level, line))

    def since(self, seq: int) -> List[Dict[str, Any]]:
        with self._lock:
            return [{'seq': s, 'ts': ts, 'level': lv, 'text': tx}
                    for s, ts, lv, tx in self.lines if s > seq]


class _Tee:
    """Пишет в исходный поток и копирует строки в LogBuffer"""

    def __init__(self, stream, buffer: LogBuffer):
        self.stream = stream
        self.buffer = buffer
        self.partial = ''

    def write(self, text):
        try:
            self.stream.write(text)
        except Exception:
            pass
        self.partial += text
        if '\n' in self.partial:
            done, self.partial = self.partial.rsplit('\n', 1)
            self.buffer.add(done)
        return len(text)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self.stream, name)


LOGS = LogBuffer()


def capture_output():
    """Вызывается из main.py до настройки logging"""
    if sys.stdout is not None and not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, LOGS)
    if sys.stderr is not None and not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(sys.stderr, LOGS)


# ---------- файлы ----------

def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_text_atomic(path: str, text: str):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def write_json_atomic(path: str, data: Any, indent: int = 4):
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=indent) + '\n')


def load_config() -> Dict[str, Any]:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def mask_config(config: Dict[str, Any]) -> Dict[str, Any]:
    masked = copy.deepcopy(config)
    for key in SECRET_KEYS:
        if masked.get(key):
            masked[key] = MASK
    return masked


def unmask(draft: Dict[str, Any], stored: Dict[str, Any]) -> Dict[str, Any]:
    """Черновик из панели с масками вместо ключей -> настоящий конфиг"""
    config = copy.deepcopy(draft)
    for key in SECRET_KEYS:
        if config.get(key) == MASK:
            config[key] = stored.get(key, '')
    return config


def set_path(data: Dict[str, Any], path: str, value: Any):
    parts = path.split('.')
    for part in parts[:-1]:
        if not isinstance(data.get(part), dict):
            data[part] = {}
        data = data[part]
    data[parts[-1]] = value


def del_path(data: Dict[str, Any], path: str):
    parts = path.split('.')
    for part in parts[:-1]:
        data = data.get(part)
        if not isinstance(data, dict):
            return
    data.pop(parts[-1], None)


def backup_config():
    """Копия config.json перед каждой записью, хранятся последние BACKUPS_KEPT"""
    if not os.path.exists(CONFIG_FILE):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    path = os.path.join(BACKUP_DIR, f'config-{stamp}.json')
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(BACKUP_DIR, f'config-{stamp}-{n}.json')
    shutil.copy2(CONFIG_FILE, path)
    for old in list_backups()[BACKUPS_KEPT:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old['name']))
        except OSError:
            pass


def list_backups() -> List[Dict[str, Any]]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    items = [{'name': n, 'mtime': os.path.getmtime(os.path.join(BACKUP_DIR, n))}
             for n in os.listdir(BACKUP_DIR) if re.fullmatch(r'config-[\d-]+\.json', n)]
    return sorted(items, key=lambda b: b['mtime'], reverse=True)


def write_config(config: Dict[str, Any]):
    backup_config()
    write_json_atomic(CONFIG_FILE, config)


def read_sessions() -> List[Dict[str, Any]]:
    items = []
    try:
        with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    raw = json.loads(line)
                    items.append({'name': raw.get('name', ''), 'focus': bool(raw.get('focus', True)),
                                  'min': int(raw.get('min', 25))})
    except FileNotFoundError:
        pass
    return items


def validate_sessions(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError('Ожидается список блоков')
    result = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f'Блок {i}: ожидается объект')
        minutes = item.get('min')
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= 600:
            raise ValueError(f'Блок {i}: длительность должна быть целым числом от 1 до 600 минут')
        result.append({'name': str(item.get('name', '')), 'focus': bool(item.get('focus', True)),
                       'min': minutes})
    return result


def write_sessions(items: List[Dict[str, Any]]):
    lines = [json.dumps(item, ensure_ascii=False) for item in validate_sessions(items)]
    write_text_atomic(SESSIONS_FILE, '\n'.join(lines) + '\n' if lines else '')


def memory_path(config: Dict[str, Any]) -> Optional[str]:
    return config.get('ai_memory_file', 'assistant_memory.json')


# ---------- значения по умолчанию (как в коде, через config.get) ----------

def defaults_for(config: Dict[str, Any]) -> Dict[str, Any]:
    from ai_client import LlamaClient, assistant_name
    from assistant import (DEFAULT_FALLBACKS, DEFAULT_INSTRUCTIONS, DEFAULT_RULES,
                           DEFAULT_STYLES, FACT_TOPICS, LEGACY_KEYS, _clean_legacy)
    defaults = {
        'debug_level': 0,
        'target_apps': ["Visual Studio Code"],
        'reminder_interval': 30,
        'punishment_interval': 60,
        'punishment_cooldown': config.get('punishment_interval', 60),
        'praise_interval': 1800,
        'interesting_fact_interval': 60,
        'reminder_sound': 'H_WARNING.mp3',
        'reminder_volume': 1.0,
        'discord_presence': False,
        'audio_frequency': 48000,
        'audio_buffer': 2048,
        'ai_provider': 'llama',
        'ai_fallback_providers': [],
        'ai_timeout': 30,
        'ai_retries': 2,
        'llama_url': 'http://127.0.0.1:8080/completion',
        'llama_user_label': 'System',
        'api_key': '',
        'stop': ["</s>", "User:"],
        **LlamaClient.SAMPLING_KEYS,
        'openai_base_url': 'http://127.0.0.1:8080/v1',
        'openai_model': 'local-model',
        'openai_api_key': '',
        'openai_max_tokens': 300,
        'openai_thinking': False,
        'google_assistant_api_key': '',
        'google_model': 'gemini-2.5-flash',
        'google_max_tokens': 400,
        'google_temperature': 0.7,
        'google_top_p': 0.95,
        'google_top_k': 40,
        'prompt': "You are helpful assistant",
        'assistant_name': assistant_name(config),
        'ai_response_rules': DEFAULT_RULES,
        'ai_max_chars': 400,
        'ai_max_sentences': 2,
        'ai_drop_questions': True,
        'ai_repeat_threshold': 0.6,
        'ai_context_budget': 1500,
        'ai_history_size': 0,
        'ai_event_log_size': 8,
        'ai_memory_file': 'assistant_memory.json',
        'ai_style_hints': DEFAULT_STYLES,
        'fallback_phrases': DEFAULT_FALLBACKS,
        'ai_fact_topics': FACT_TOPICS,
        'tts_engines': list(TTS_ENGINES),
        'tts_failure_cooldown': 600,
        'silero_model': 'voices/silero_v5_6_ru.pt',
        'silero_speaker': 'xenia',
        'silero_sample_rate': 48000,
        'silero_threads': 8,
        'silero_rate': '',
        'silero_pitch': '',
        'edge_tts_voice': 'ru-RU-SvetlanaNeural',
        'edge_tts_rate': '+0%',
        'piper_model': 'voices/ru_RU-irina-medium.onnx',
        'piper_length_scale': 1.0,
        'sapi_voice': 'Irina',
        'sapi_rate': 0,
        'panel_enabled': True,
        'panel_port': DEFAULT_PORT,
        'panel_open_browser': False,
    }
    for event, text in DEFAULT_INSTRUCTIONS.items():
        legacy = config.get(LEGACY_KEYS[event])
        defaults[f'{event}_instruction'] = _clean_legacy(legacy) if legacy else text
    return defaults


# Ключи, которые читает программа, но которых нет в defaults_for
EXTRA_KNOWN = {
    'openai_temperature', 'openai_top_k', 'openai_top_p', 'openai_min_p',
    'openai_presence_penalty', 'openai_frequency_penalty', 'openai_repeat_penalty',
    'openai_extra_params', 'google_thinking_budget', 'edge_tts_timeout',
    'punishment_subprompt', 'praise_subprompt', 'interesting_fact_subprompt',
}


def unknown_keys(config: Dict[str, Any]) -> List[str]:
    known = set(defaults_for(config)) | EXTRA_KNOWN
    return [key for key in config if key not in known]


# ---------- окружение ----------

def open_windows(targets: List[str]) -> List[Dict[str, str]]:
    """Открытые окна, которые не попадают в рабочие приложения"""
    if sys.platform != 'win32':
        return []
    import pygetwindow as gw
    skip = {'Program Manager', 'Windows Input Experience', 'Параметры', 'Settings'}
    seen, result = set(), []
    for title in gw.getAllTitles():
        title = title.strip()
        if not title or any(app in title for app in targets):
            continue
        # «Документ — Приложение»: предлагаем название приложения
        name = re.split(r"\s[-—–]\s", title)[-1].strip()
        if not name or name in seen or name in skip:
            continue
        seen.add(name)
        result.append({'title': title, 'name': name})
    return result[:30]


def engine_status(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    has = lambda module: importlib.util.find_spec(module) is not None  # noqa: E731
    if name == 'silero':
        model = config.get('silero_model', 'voices/silero_v5_6_ru.pt')
        if not has('torch'):
            return {'ok': False, 'note': 'не установлен PyTorch'}
        if not os.path.exists(model):
            return {'ok': False, 'note': f'нет модели {model}'}
        return {'ok': True, 'note': f"модель на месте · голос {config.get('silero_speaker', 'xenia')}"}
    if name == 'edge':
        if not has('edge_tts'):
            return {'ok': False, 'note': 'не установлен edge-tts'}
        return {'ok': True, 'note': config.get('edge_tts_voice', 'ru-RU-SvetlanaNeural')}
    if name == 'piper':
        model = config.get('piper_model', 'voices/ru_RU-irina-medium.onnx')
        if not has('piper'):
            return {'ok': False, 'note': 'не установлен piper-tts'}
        if not os.path.exists(model):
            return {'ok': False, 'note': f'нет модели {model}'}
        return {'ok': True, 'note': os.path.splitext(os.path.basename(model))[0]}
    if name == 'sapi':
        if sys.platform != 'win32':
            return {'ok': False, 'note': 'только Windows'}
        if not has('comtypes'):
            return {'ok': False, 'note': 'не установлен comtypes'}
        return {'ok': True, 'note': config.get('sapi_voice', 'Irina')}
    return {'ok': False, 'note': 'неизвестный движок'}


async def play_audio(data: bytes, volume: float = 1.0):
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048)
    sound = pygame.mixer.Sound(file=io.BytesIO(data))
    sound.set_volume(max(0.0, min(1.0, volume)))
    channel = sound.play()
    while channel is not None and channel.get_busy():
        await asyncio.sleep(0.1)


# ---------- сервер ----------

def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status,
                             dumps=lambda o: json.dumps(o, ensure_ascii=False))


def _handler(func):
    """Ошибки обработчика -> JSON {error}, чтобы панель могла их показать"""
    async def wrapper(self, request):
        try:
            return await func(self, request)
        except web.HTTPException:
            raise
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            return _json({'error': str(e)}, 400)
        except Exception as e:
            logging.exception('[PANEL] Ошибка запроса')
            return _json({'error': f'{type(e).__name__}: {e}'}, 500)
    return wrapper


class Panel:
    def __init__(self, runtime=None):
        self.rt = runtime
        self._engines: Dict[tuple, Any] = {}
        self._tts_lock = asyncio.Lock()
        self.app = web.Application(middlewares=[self._guard], client_max_size=20 * 1024 * 1024)
        r = self.app.router
        r.add_get('/', self.index)
        r.add_static('/static/', WEB_DIR)
        r.add_get('/api/status', self.status)
        r.add_get('/api/config', self.get_config)
        r.add_put('/api/config', self.put_config)
        r.add_get('/api/sessions', self.get_sessions)
        r.add_put('/api/sessions', self.put_sessions)
        r.add_get('/api/memory', self.get_memory)
        r.add_post('/api/memory/forget', self.memory_forget)
        r.add_post('/api/memory/clear', self.memory_clear)
        r.add_post('/api/stats/reset', self.stats_reset)
        r.add_get('/api/raw', self.get_raw)
        r.add_put('/api/raw', self.put_raw)
        r.add_get('/api/backups', self.get_backups)
        r.add_post('/api/backups/restore', self.restore_backup)
        r.add_get('/api/export', self.export)
        r.add_get('/api/windows', self.windows)
        r.add_get('/api/tts', self.tts_status)
        r.add_post('/api/test/tts', self.test_tts)
        r.add_post('/api/test/sound', self.test_sound)
        r.add_post('/api/test/ai', self.test_ai)
        r.add_post('/api/test/reply', self.test_reply)
        r.add_post('/api/models', self.models)
        r.add_post('/api/control', self.control)
        r.add_post('/api/process', self.process)
        r.add_get('/api/logs', self.logs)
        r.add_post('/api/upload/sound', self.upload_sound)

    @web.middleware
    async def _guard(self, request, handler):
        # Только localhost: чужой сайт не достучится через DNS rebinding,
        # а изменения без заголовка X-Panel не пройдут без CORS-разрешения
        host = request.host.rsplit(':', 1)[0] if not request.host.startswith('[') else request.host.split(']')[0] + ']'
        if host not in ('127.0.0.1', 'localhost', '[::1]'):
            return web.Response(status=403, text='forbidden host')
        if request.method not in ('GET', 'HEAD') and request.headers.get('X-Panel') != '1':
            return web.Response(status=403, text='missing X-Panel header')
        response = await handler(request)
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def _live(self):
        if not self.rt:
            raise ValueError('Трекер не запущен: запусти start.bat или python main.py')
        return self.rt

    async def _body(self, request) -> Dict[str, Any]:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('Ожидается JSON-объект')
        return data

    def _draft(self, body: Dict[str, Any]) -> Dict[str, Any]:
        stored = load_config()
        draft = body.get('draft')
        return unmask(draft, stored) if isinstance(draft, dict) else stored

    # --- страницы ---

    async def index(self, request):
        with open(os.path.join(WEB_DIR, 'index.html'), 'r', encoding='utf-8') as f:
            html = f.read()
        version = str(int(max(os.path.getmtime(os.path.join(WEB_DIR, n))
                              for n in ('app.js', 'app.css'))))
        return web.Response(text=html.replace('{{v}}', version), content_type='text/html',
                            headers={'Cache-Control': 'no-store'})

    # --- состояние ---

    @_handler
    async def status(self, request):
        config = read_json(CONFIG_FILE, {}) or {}
        data = {
            'live': self.rt is not None,
            'pid': os.getpid(),
            'now': time.time(),
            'config_mtime': os.path.getmtime(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else None,
            'sessions': read_sessions(),
        }
        if self.rt:
            data.update(self.rt.state())
        else:
            stats = read_json(STATS_FILE, {}) or {}
            today = stats.pop('today', None)
            memory = read_json(memory_path(config) or '', {}) if memory_path(config) else {}
            is_today = (memory or {}).get('date') == time.strftime('%Y-%m-%d')
            data.update({
                'stats': stats,
                'today': today if today and today.get('date') == time.strftime('%Y-%m-%d') else None,
                'events': memory.get('events', []) if is_today else [],
                'block_distractions': memory.get('distractions', {}) if is_today else {},
            })
        return _json(data)

    @_handler
    async def control(self, request):
        body = await self._body(request)
        self._live().control(body.get('action'), body.get('value'))
        return _json({'ok': True})

    @_handler
    async def process(self, request):
        rt = self._live()
        action = (await self._body(request)).get('action')
        if action not in ('restart', 'stop'):
            raise ValueError('Неизвестное действие')
        # Сначала ответить панели, потом завершаться
        loop = asyncio.get_running_loop()
        loop.call_later(0.3, rt.request_restart if action == 'restart' else rt.request_stop)
        return _json({'ok': True})

    @_handler
    async def logs(self, request):
        after = int(request.query.get('after', 0))
        return _json({'live': self.rt is not None, 'lines': LOGS.since(after)})

    # --- конфиг ---

    def _config_payload(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'config': mask_config(config),
            'defaults': defaults_for(config),
            'unknown': unknown_keys(config),
            'mtime': os.path.getmtime(CONFIG_FILE),
            'live': self.rt is not None,
        }

    @_handler
    async def get_config(self, request):
        return _json(self._config_payload(load_config()))

    @_handler
    async def put_config(self, request):
        body = await self._body(request)
        config = load_config()
        for path, value in (body.get('set') or {}).items():
            if path in SECRET_KEYS and value == MASK:
                continue
            set_path(config, path, value)
        for path in body.get('unset') or []:
            del_path(config, path)
        write_config(config)
        logging.info(f"[PANEL] config.json сохранён: {', '.join([*(body.get('set') or {}), *(body.get('unset') or [])])}")
        return _json(self._config_payload(config))

    @_handler
    async def get_sessions(self, request):
        return _json({'sessions': read_sessions()})

    @_handler
    async def put_sessions(self, request):
        body = await self._body(request)
        write_sessions(body.get('sessions'))
        if self.rt:
            self.rt.reload_sessions()
        logging.info('[PANEL] sessions.jsonl сохранён')
        return _json({'sessions': read_sessions(), 'applied': self.rt is not None})

    # --- файлы вручную ---

    @_handler
    async def get_raw(self, request):
        name = request.query.get('file')
        if name == 'config':
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                text = f.read()
            config = json.loads(text)
            for key in SECRET_KEYS:
                if config.get(key):
                    text = re.sub(rf'("{key}"\s*:\s*)"(?:[^"\\]|\\.)*"', lambda m: m.group(1) + json.dumps(MASK, ensure_ascii=False), text)
            return _json({'text': text, 'lines': text.count('\n') + 1})
        if name == 'sessions':
            text = open(SESSIONS_FILE, 'r', encoding='utf-8').read() if os.path.exists(SESSIONS_FILE) else ''
            return _json({'text': text, 'lines': text.count('\n') + 1})
        raise ValueError('Неизвестный файл')

    @_handler
    async def put_raw(self, request):
        body = await self._body(request)
        name, text = body.get('file'), body.get('text', '')
        if name == 'config':
            try:
                config = json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(f'Ошибка JSON, строка {e.lineno}, позиция {e.colno}: {e.msg}')
            if not isinstance(config, dict):
                raise ValueError('config.json должен быть объектом { ... }')
            stored = load_config()
            for key in SECRET_KEYS:
                if config.get(key) == MASK:
                    text = re.sub(rf'("{key}"\s*:\s*)"{re.escape(MASK)}"',
                                  lambda m: m.group(1) + json.dumps(stored.get(key, ''), ensure_ascii=False), text)
            json.loads(text)
            backup_config()
            write_text_atomic(CONFIG_FILE, text if text.endswith('\n') else text + '\n')
            logging.info('[PANEL] config.json сохранён вручную')
            return _json(self._config_payload(load_config()))
        if name == 'sessions':
            items = []
            for n, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        raise ValueError(f'Строка {n}: {e.msg}')
            write_sessions(items)
            if self.rt:
                self.rt.reload_sessions()
            return _json({'sessions': read_sessions()})
        raise ValueError('Неизвестный файл')

    @_handler
    async def get_backups(self, request):
        return _json({'backups': list_backups()})

    @_handler
    async def restore_backup(self, request):
        name = (await self._body(request)).get('name', '')
        if not re.fullmatch(r'config-[\d-]+\.json', name):
            raise ValueError('Неверное имя копии')
        path = os.path.join(BACKUP_DIR, name)
        with open(path, 'r', encoding='utf-8') as f:
            json.load(f)
        backup_config()
        shutil.copy2(path, CONFIG_FILE)
        logging.info(f'[PANEL] config.json восстановлен из {name}')
        return _json(self._config_payload(load_config()))

    @_handler
    async def export(self, request):
        config = load_config()
        for key in SECRET_KEYS:
            if key in config:
                config[key] = ''
        return web.Response(text=json.dumps(config, ensure_ascii=False, indent=4), content_type='application/json',
                            headers={'Content-Disposition': 'attachment; filename="workreminder-config.json"'})

    # --- память ---

    def _memory(self) -> Dict[str, Any]:
        config = read_json(CONFIG_FILE, {}) or {}
        path = memory_path(config)
        if self.rt:
            data = self.rt.assistant.memory_snapshot()
            stats = {k: v for k, v in self.rt.state()['stats'].items()}
        else:
            data = (read_json(path, {}) if path else {}) or {}
            stats = read_json(STATS_FILE, {}) or {}
        stats.pop('today', None)
        return {
            'live': self.rt is not None,
            'file': path,
            'date': data.get('date'),
            'is_today': data.get('date') == time.strftime('%Y-%m-%d'),
            'events': data.get('events', []),
            'recent_replies': data.get('recent_replies', []),
            'recent_facts': data.get('recent_facts', []),
            'distractions': data.get('distractions', {}),
            'history': len(data.get('history', [])),
            'event_log_size': config.get('ai_event_log_size', 8),
            'stats': stats,
        }

    def _edit_memory_file(self, change):
        path = memory_path(read_json(CONFIG_FILE, {}) or {})
        if not path:
            raise ValueError('Память выключена (ai_memory_file = null)')
        data = read_json(path, {}) or {}
        change(data)
        write_json_atomic(path, data, indent=1)

    @_handler
    async def get_memory(self, request):
        return _json(self._memory())

    @_handler
    async def memory_forget(self, request):
        body = await self._body(request)
        kind, index = body.get('kind'), int(body.get('index'))
        if kind not in ('events', 'recent_replies', 'recent_facts'):
            raise ValueError('Неизвестный раздел памяти')
        if self.rt:
            self.rt.assistant.forget(kind, index)
        else:
            self._edit_memory_file(lambda d: d.get(kind, []).pop(index))
        return _json(self._memory())

    @_handler
    async def memory_clear(self, request):
        scope = (await self._body(request)).get('scope')
        if scope not in ('today', 'facts'):
            raise ValueError('Неизвестная область очистки')
        if self.rt:
            self.rt.assistant.clear_memory(scope)
        else:
            def change(d):
                keys = ['recent_facts'] if scope == 'facts' else ['history', 'events', 'recent_replies']
                for key in keys:
                    d[key] = []
                if scope == 'today':
                    d['distractions'] = {}
            self._edit_memory_file(change)
        return _json(self._memory())

    @_handler
    async def stats_reset(self, request):
        if self.rt:
            self.rt.reset_stats()
        else:
            stats = read_json(STATS_FILE, {}) or {}
            stats.update({'total_focus_time': 0, 'total_break_time': 0, 'completed_sessions': 0})
            write_json_atomic(STATS_FILE, stats, indent=2)
        return _json(self._memory())

    # --- окружение и проверки ---

    @_handler
    async def windows(self, request):
        # Фильтр по рабочим приложениям делает панель: там несохранённый черновик списка
        items = await asyncio.to_thread(open_windows, [])
        return _json({'windows': items})

    @_handler
    async def tts_status(self, request):
        config = load_config()
        disabled = self.rt.speaker.disabled_until if self.rt else {}
        now = time.time()
        engines = []
        for name in TTS_ENGINES:
            item = {'name': name, **engine_status(name, config)}
            if disabled.get(name, 0) > now:
                item['failed_until'] = disabled[name]
            engines.append(item)
        return _json({'engines': engines})

    def _engine(self, name: str, config: Dict[str, Any]):
        """Движок с настройками черновика; уже загруженная модель берётся повторно"""
        from tts import ENGINES
        if name not in ENGINES:
            raise ValueError(f'Неизвестный движок {name}')
        engine = ENGINES[name](config)
        key = (name, getattr(engine, 'model_path', None) or getattr(engine, 'model', None))
        cached = self._engines.get(key)
        if cached is None and self.rt:
            cached = next((e for e in self.rt.speaker.engines if e.name == name and
                           (getattr(e, 'model_path', None) or getattr(e, 'model', None)) == key[1]), None)
        if cached is not None:
            for attr in ('_model', '_voice'):
                if getattr(cached, attr, None) is not None:
                    setattr(engine, attr, getattr(cached, attr))
        return engine, key

    @_handler
    async def test_tts(self, request):
        body = await self._body(request)
        config = self._draft(body)
        text = (body.get('text') or '').strip()[:400]
        if not text:
            raise ValueError('Пустая фраза')
        names = [body['engine']] if body.get('engine') else config.get('tts_engines', list(TTS_ENGINES))
        errors = []
        async with self._tts_lock:
            for name in names:
                if not engine_status(name, config)['ok']:
                    errors.append(f"{name}: {engine_status(name, config)['note']}")
                    continue
                try:
                    engine, key = self._engine(name, config)
                    started = time.monotonic()
                    data, _ = await engine.synthesize(text)
                    seconds = time.monotonic() - started
                    self._engines[key] = engine
                    await play_audio(data)
                    return _json({'ok': True, 'engine': name, 'seconds': round(seconds, 2)})
                except Exception as e:
                    errors.append(f'{name}: {e!r}'[:300])
        return _json({'ok': False, 'error': '; '.join(errors) or 'нет доступных движков'})

    @_handler
    async def test_sound(self, request):
        config = self._draft(await self._body(request))
        path = config.get('reminder_sound', 'H_WARNING.mp3')
        with open(path, 'rb') as f:
            data = f.read()
        await play_audio(data, float(config.get('reminder_volume', 1.0)))
        return _json({'ok': True})

    @_handler
    async def test_ai(self, request):
        from ai_client import AIClientFactory
        body = await self._body(request)
        config = self._draft(body)
        provider = body.get('provider') or config.get('ai_provider', 'llama')
        config = {**config, 'ai_retries': 0, 'ai_timeout': min(int(config.get('ai_timeout', 30)), 30)}
        client = AIClientFactory._create_single(provider, config)
        started = time.monotonic()
        try:
            reply = await client.chat([{"role": "user", "content": "Ответь одним словом: на связи."}],
                                      "Это проверка связи. Ответь одним-двумя словами.")
            return _json({'ok': True, 'seconds': round(time.monotonic() - started, 2),
                          'reply': (reply or '')[:200]})
        except Exception as e:
            return _json({'ok': False, 'error': str(e)[:400]})
        finally:
            await client.close()

    @_handler
    async def models(self, request):
        config = self._draft(await self._body(request))
        base = config.get('openai_base_url', 'http://127.0.0.1:8080/v1').rstrip('/')
        key = config.get('openai_api_key', '')
        headers = {'Authorization': f'Bearer {key}'} if key else {}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(f'{base}/models', headers=headers) as response:
                    data = await response.json(content_type=None)
        except Exception as e:
            return _json({'ok': False, 'error': f'{e!r}'[:300]})
        items = data.get('data') or data.get('models') or []
        ids = [m.get('id') or m.get('name') for m in items if isinstance(m, dict)]
        return _json({'ok': True, 'models': [i for i in ids if i]})

    @_handler
    async def test_reply(self, request):
        from ai_client import AIClientFactory
        from assistant import FocusAssistant
        body = await self._body(request)
        config = {**self._draft(body), 'ai_memory_file': None, 'ai_retries': 0}
        event = body.get('event')
        if event not in ('punishment', 'praise', 'fact'):
            raise ValueError('Неизвестное событие')
        values = body.get('values') or {}
        client = AIClientFactory.create_client(config)

        async def silent(_text):
            pass

        helper = FocusAssistant(client, config, silent)
        target = (self.rt.target_window if self.rt else None) or (config.get('target_apps') or ['рабочем окне'])[0]
        if self.rt:
            live = self.rt.assistant
            helper.events.extend(live.events)
            helper.recent_replies.extend(live.recent_replies)
            helper.recent_facts.extend(live.recent_facts)
            helper.distractions.update(live.distractions)
            helper.session_info = live.session_info
        log_from = LOGS.seq
        try:
            if event == 'punishment':
                distraction = str(values.get('window') or 'Telegram')
                seconds = int(values.get('seconds') or 75)
                result = await helper.preview(event, {
                    'target': target, 'distraction': distraction, 'distracted_seconds': seconds,
                    'count': sum(helper.distractions.values()) + 1}, (target, distraction))
            elif event == 'praise':
                minutes = int(values.get('minutes') or 60)
                result = await helper.preview(event, {'target': target, 'minutes': minutes,
                                                      'seconds': minutes * 60}, (target, minutes * 60))
            else:
                result = await helper.preview(event, {})
        finally:
            await client.close()
        if not result['text']:
            # Ассистент глотает ошибки и пишет их в лог: достаём причину оттуда
            problems = [l['text'] for l in LOGS.since(log_from) if l['level'] in ('ERROR', 'WARNING')]
            result['error'] = problems[-1][:400] if problems else 'Модель вернула пустой ответ'
        return _json({'ok': bool(result['text']), **result})

    @_handler
    async def upload_sound(self, request):
        name = os.path.basename(request.query.get('name', 'sound.mp3'))
        stem, ext = os.path.splitext(name)
        if ext.lower() not in ('.mp3', '.wav', '.ogg'):
            raise ValueError('Подходят только mp3, wav и ogg')
        data = await request.read()
        if not data:
            raise ValueError('Пустой файл')
        os.makedirs(SOUNDS_DIR, exist_ok=True)
        safe = re.sub(r'[^\w.\-]+', '_', stem)[:60] or 'sound'
        path = f'{SOUNDS_DIR}/{safe}{ext.lower()}'
        with open(path, 'wb') as f:
            f.write(data)
        return _json({'path': path})


async def start_panel(runtime, config: Dict[str, Any]) -> Optional[web.AppRunner]:
    """Запускает панель на 127.0.0.1. Возвращает runner для остановки или None"""
    if not config.get('panel_enabled', True):
        return None
    port = int(config.get('panel_port', DEFAULT_PORT))
    runner = web.AppRunner(Panel(runtime).app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, '127.0.0.1', port).start()
    except OSError as e:
        logging.error(f"[PANEL] Веб-панель не запущена, порт {port} занят: {e}")
        await runner.cleanup()
        return None
    url = f'http://127.0.0.1:{port}/'
    print(f"[INFO] Веб-панель: {url}")
    if config.get('panel_open_browser'):
        webbrowser.open(url)
    return runner


if __name__ == '__main__':
    # Без трекера: только правка файлов, когда main.py не запущен
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    async def run():
        config = read_json(CONFIG_FILE, {}) or {}
        runner = await start_panel(None, {**config, 'panel_enabled': True,
                                          'panel_open_browser': '--no-browser' not in sys.argv})
        if runner is None:
            return
        print("Трекер не запущен, доступна только правка файлов. Остановка: Ctrl+C")
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            await runner.cleanup()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
