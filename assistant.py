# ---------------------------------------------------------------
# Focus Assistant
# Описание: Логика общения с нейросетью: сборка системного промпта
#           с контекстом, память диалога и журнал событий (с сохранением
#           в файл), защита от повторов, бюджет контекста,
#           очистка ответа для TTS и запасные фразы при сбоях.
# ---------------------------------------------------------------

import json
import logging
import os
import random
import re
import time
from collections import Counter, deque
from difflib import SequenceMatcher
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ai_client import AIClient, Message, assistant_name, is_context_overflow

# Грубая оценка: русский текст ~2.5 символа на токен у типичных токенизаторов.
# Берём с запасом, точный подсчёт токенов тут не нужен.
CHARS_PER_TOKEN = 2.5
# Ниже этого бюджет не урезается даже после переполнений
MIN_CONTEXT_BUDGET = 400

RETRY_HINT = ("\nТвой вариант «{text}» слишком похож на то, что ты уже говорила. "
              "Скажи по-другому: другими словами и с другого начала.")

DEFAULT_RULES = (
    "Правила ответа: отвечай по-русски, одним-двумя короткими предложениями. "
    "Текст будет озвучен синтезатором речи, поэтому без эмодзи, звёздочек, "
    "списков, разметки и ремарок в скобках. Не здоровайся и не задавай вопросов: "
    "пользователь не может ответить. О пользователе говори в настоящем времени, "
    "а не в прошедшем. Каждый раз начинай реплику по-разному и не повторяй "
    "дословно свои прошлые реплики."
)

# Напоминание в конце каждой инструкции: маленькие модели лучше
# соблюдают ограничения, если они стоят рядом с самим заданием
INSTRUCTION_SUFFIX = " Ответь одним-двумя короткими предложениями, без вопросов."

DEFAULT_INSTRUCTIONS = {
    "punishment": (
        "Пользователь должен работать в '{target}', но уже {distracted_seconds} секунд "
        "сидит в '{distraction}'. Это {count}-е отвлечение за сессию. "
        "Строго, но с юмором верни его к работе."
    ),
    "praise": (
        "Пользователь {minutes} минут подряд работает в '{target}' без отвлечений. "
        "Искренне похвали его."
    ),
    "fact": (
        "Пользователь устал. Это часть твоей роли: расскажи один короткий "
        "необычный научный факт, чтобы он взбодрился."
    ),
}

# Случайная подсказка стиля к каждой реплике: просьба «не повторяйся»
# маленьким моделям почти не помогает, а конкретное задание стиля даёт
# разнообразие. Подряд одна и та же подсказка не выпадает.
DEFAULT_STYLES = {
    "punishment": [
        "Пошути над ситуацией.",
        "Будь строгой и краткой.",
        "Используй неожиданное сравнение.",
        "Поддразни по-дружески.",
        "Сделай вид, что обиделась.",
        "Предложи маленькую цель на ближайшие десять минут.",
        "Скажи это как спортивный комментатор.",
        "Напомни, что после работы будет отдых.",
    ],
    "praise": [
        "Используй неожиданное сравнение.",
        "Скажи коротко и тепло.",
        "Пошути.",
        "Скажи это как спортивный комментатор.",
        "Подбодри продолжать в том же темпе.",
    ],
    "fact": [],
}

# Темы фактов: случайная тема, кроме недавних, разводит факты лучше,
# чем список «не повторяй»
FACT_TOPICS = [
    "космос", "животные", "насекомые", "океан", "растения", "история",
    "человеческое тело", "мозг", "химия", "физика", "география", "языки",
    "техника и изобретения", "еда", "музыка", "математика", "погода", "птицы",
]

# Какой контекст нужен модели для каждого события. Лишний контекст
# маленькие модели пересказывают в каждой реплике.
EVENT_CONTEXT = {
    "punishment": {"distractions", "events"},
    "praise": {"session", "events"},
    "fact": set(),
}

# Старые ключи конфига с позиционными подстановками '{}'
LEGACY_KEYS = {
    "punishment": "punishment_subprompt",
    "praise": "praise_subprompt",
    "fact": "interesting_fact_subprompt",
}

DEFAULT_FALLBACKS = {
    "punishment": [
        "Эй, хватит отвлекаться. Возвращайся к работе.",
        "Так, работа сама себя не сделает.",
        "Вернись к задаче, она тебя ждёт.",
    ],
    "praise": [
        "Отличная работа, ты долго держишь фокус. Так держать!",
        "Ты молодец, продолжай в том же темпе.",
    ],
    "fact": [],
}

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF️‍]+"
)


GREETING_RE = re.compile(r"^(привет|здравствуй(те)?|хай|добр(ый|ое|ого) \w+)[!,.]?\s*", re.I)


class _SafeDict(dict):
    """Не падает на неизвестных плейсхолдерах в шаблоне"""

    def __missing__(self, key):
        return "{" + key + "}"


def _clean_legacy(template: str) -> str:
    """Превращает старый completion-сабпромпт вида
    '\\n\\nSystem: текст\\nЕва:' в чистую инструкцию 'текст'."""
    text = template.strip()
    text = re.sub(r"^\w+:\s*", "", text)          # ведущая метка "System:"/"User:"
    text = re.sub(r"\n[^\n]{1,30}:\s*$", "", text)  # хвостовая метка "Ева:"
    return text.strip()


def _short(title: Optional[str], limit: int = 80) -> str:
    title = (title or "неизвестное окно").strip()
    return title if len(title) <= limit else title[:limit - 1] + "…"


def _words(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


def similarity(a: str, b: str) -> float:
    """Похожесть реплик 0..1: максимум из посимвольного сходства,
    пересечения слов и совпадения начала (первые 3 слова)"""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    seq = SequenceMatcher(None, " ".join(wa), " ".join(wb)).ratio()
    sa, sb = set(wa), set(wb)
    jaccard = len(sa & sb) / len(sa | sb)
    same_start = 0.7 if len(wa) >= 3 and wa[:3] == wb[:3] else 0.0
    return max(seq, jaccard, same_start)


def _tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 4


class FocusAssistant:
    def __init__(self, client: AIClient, config: Dict[str, Any],
                 speak: Callable[[str], Awaitable[None]]):
        self.client = client
        self.speak = speak
        self.persona = config.get('prompt', "You are helpful assistant")
        self.rules = config.get('ai_response_rules', DEFAULT_RULES)
        self.max_chars = config.get('ai_max_chars', 400)
        self.max_sentences = config.get('ai_max_sentences', 2)
        self.drop_questions = config.get('ai_drop_questions', True)
        self.assistant_name = assistant_name(config)
        self.repeat_threshold = config.get('ai_repeat_threshold', 0.6)
        # Сколько токенов можно потратить на промпт. Если сервер всё равно
        # сообщит о переполнении, бюджет урезается автоматически.
        self.context_budget = config.get('ai_context_budget', 1500)

        # Вся память ограничена по размеру и не растёт со временем
        self.history: deque = deque(maxlen=max(0, config.get('ai_history_size', 0)))
        self.events: deque = deque(maxlen=max(0, config.get('ai_event_log_size', 8)))
        self.recent_replies: deque = deque(maxlen=20)
        self.recent_facts: deque = deque(maxlen=10)

        self.fallbacks = {**DEFAULT_FALLBACKS, **config.get('fallback_phrases', {})}
        self.styles = {**DEFAULT_STYLES, **config.get('ai_style_hints', {})}
        self.fact_topics = config.get('ai_fact_topics', FACT_TOPICS)
        self.last_style: Dict[str, str] = {}
        self.recent_topics: deque = deque(maxlen=max(1, len(self.fact_topics) // 2))
        self.templates: Dict[str, str] = {}
        self.legacy: Dict[str, bool] = {}
        for event, default in DEFAULT_INSTRUCTIONS.items():
            new_key = f"{event}_instruction"
            legacy_key = LEGACY_KEYS[event]
            if new_key in config:
                self.templates[event], self.legacy[event] = config[new_key], False
            elif legacy_key in config:
                self.templates[event], self.legacy[event] = _clean_legacy(config[legacy_key]), True
            else:
                self.templates[event], self.legacy[event] = default, False

        # Контекст сессии, обновляется из main
        self.session_info: Optional[str] = None
        self.distractions: Counter = Counter()

        self.memory_file = config.get('ai_memory_file', 'assistant_memory.json')
        self._load_memory()

    # ---------- память на диске ----------

    def _load_memory(self):
        """Восстанавливает память. Факты помнятся всегда (чтобы не повторяться),
        остальное только в пределах текущего дня."""
        if not self.memory_file or not os.path.exists(self.memory_file):
            return
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.recent_facts.extend(data.get('recent_facts', []))
            if data.get('date') == time.strftime('%Y-%m-%d'):
                self.history.extend(data.get('history', []))
                self.events.extend(tuple(e) for e in data.get('events', []))
                self.recent_replies.extend(data.get('recent_replies', []))
                self.distractions.update(data.get('distractions', {}))
            logging.info(f"[AI] Память загружена: {len(self.history)} сообщений, "
                         f"{len(self.events)} событий, {len(self.recent_facts)} фактов")
        except Exception as e:
            logging.warning(f"[AI] Не удалось загрузить память из {self.memory_file}: {e}")

    def _save_memory(self):
        if not self.memory_file:
            return
        data = {
            'date': time.strftime('%Y-%m-%d'),
            'history': list(self.history),
            'events': list(self.events),
            'recent_replies': list(self.recent_replies),
            'recent_facts': list(self.recent_facts),
            'distractions': dict(self.distractions),
        }
        try:
            tmp = self.memory_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.memory_file)  # атомарно: файл не побьётся при падении
        except Exception as e:
            logging.warning(f"[AI] Не удалось сохранить память: {e}")

    def memory_snapshot(self) -> Dict[str, Any]:
        return {
            'date': time.strftime('%Y-%m-%d'),
            'history': list(self.history),
            'events': [list(e) for e in self.events],
            'recent_replies': list(self.recent_replies),
            'recent_facts': list(self.recent_facts),
            'distractions': dict(self.distractions),
        }

    def forget(self, kind: str, index: int):
        """Удаляет одну запись памяти (из веб-панели)"""
        store = {'events': self.events, 'recent_replies': self.recent_replies,
                 'recent_facts': self.recent_facts}[kind]
        items = list(store)
        del items[index]
        store.clear()
        store.extend(items)
        self._save_memory()

    def clear_memory(self, scope: str):
        """scope='today': всё, кроме фактов; scope='facts': только факты"""
        if scope == 'facts':
            self.recent_facts.clear()
        else:
            for store in (self.history, self.events, self.recent_replies, self.distractions):
                store.clear()
        self._save_memory()

    # ---------- контекст ----------

    def set_session(self, name: str, elapsed_min: int, total_min: int, focus: bool):
        kind = "фокус" if focus else "отдых"
        label = f" «{name}»" if name else ""
        self.session_info = f"Текущая сессия{label}: {kind}, прошло {elapsed_min} из {total_min} минут."

    def reset_session_stats(self):
        self.distractions.clear()

    def log_event(self, text: str):
        """Записывает событие в журнал, который видит модель"""
        if self.events.maxlen:
            self.events.append((time.time(), text))
            self._save_memory()

    def _system_prompt(self, event: str, events_limit: int) -> str:
        include = EVENT_CONTEXT.get(event, set())
        now = time.localtime()
        hour = now.tm_hour
        part = ("ночь" if hour < 5 else "утро" if hour < 12
                else "день" if hour < 18 else "вечер")
        context = [f"Сейчас {time.strftime('%H:%M', now)}, {part}."]
        if self.session_info and "session" in include:
            context.append(self.session_info)
        total = sum(self.distractions.values())
        if total and "distractions" in include:
            top = ", ".join(f"{t} ({n})" for t, n in self.distractions.most_common(3))
            context.append(f"Отвлечений за сессию: {total}. Чаще всего: {top}.")
        if "events" in include and events_limit > 0 and self.events:
            recent = list(self.events)[-events_limit:]
            lines = [f"{time.strftime('%H:%M', time.localtime(ts))} {text}" for ts, text in recent]
            context.append("Недавние события (можно сослаться, если это к месту):\n" + "\n".join(lines))
        return (f"{self.persona.strip()}\n\n{self.rules}\n\n"
                "Справочный контекст (упоминай только если это к месту, "
                "не пересказывай его):\n" + "\n".join(context))

    def _build_request(self, event: str, instruction: str) -> Tuple[str, List[Message]]:
        """Собирает промпт в пределах бюджета: сначала выкидывает самые
        старые реплики диалога, затем самые старые события журнала."""
        # Факты не зависят от диалога, а маленькие модели с историей
        # начинают отвечать на прошлые реплики вместо задания.
        history = [] if event == "fact" else list(self.history)
        events_limit = len(self.events)
        user = {"role": "user", "content": instruction}
        while True:
            system = self._system_prompt(event, events_limit)
            messages = [*history, user]
            used = _tokens(system) + sum(_tokens(m["content"]) for m in messages)
            if used <= self.context_budget:
                break
            if history:
                history = history[2:]  # пара «событие → реплика»
            elif events_limit > 0:
                events_limit -= 1
            else:
                logging.warning(f"[AI] Промпт ({used} ток.) больше бюджета "
                                f"{self.context_budget} даже без истории")
                break
        return system, messages

    # ---------- события ----------

    async def punish(self, distraction: str, target: Optional[str], distracted_seconds: float):
        distraction = _short(distraction)
        self.distractions[_short(distraction, 40)] += 1
        values = {
            "target": _short(target or "рабочем окне"),
            "distraction": distraction,
            "distracted_seconds": int(distracted_seconds),
            "count": sum(self.distractions.values()),
        }
        await self._handle("punishment", values, (values["target"], distraction),
                           f"отвлечение на {_short(distraction, 40)} ({int(distracted_seconds)} с)")

    async def praise(self, target: str, focused_seconds: float):
        values = {
            "target": _short(target),
            "minutes": max(1, int(focused_seconds // 60)),
            "seconds": int(focused_seconds),
        }
        await self._handle("praise", values, (values["target"], values["seconds"]),
                           f"похвала за {values['minutes']} мин работы без отвлечений")

    async def fact(self):
        await self._handle("fact", {}, (), "рассказан факт")

    def _instruction(self, event: str, values: Dict[str, Any], legacy_args: tuple) -> Tuple[str, Optional[str]]:
        """Задание для модели: шаблон события, тема факта и случайная подсказка стиля"""
        template = self.templates[event]
        try:
            if self.legacy[event]:
                instruction = template.format(*legacy_args)
            else:
                instruction = template.format_map(_SafeDict(values))
        except (IndexError, KeyError, ValueError) as e:
            logging.warning(f"Ошибка в шаблоне '{event}': {e}. Используется шаблон по умолчанию.")
            instruction = DEFAULT_INSTRUCTIONS[event].format_map(_SafeDict(values))

        if event == "fact":
            topics = [t for t in self.fact_topics if t not in self.recent_topics] or self.fact_topics
            if topics:
                topic = random.choice(topics)
                self.recent_topics.append(topic)
                instruction += f" Тема факта: {topic}."
            if self.recent_facts:
                told = "; ".join(self.recent_facts)
                instruction += f"\nНе повторяй уже рассказанные факты: {told}"
        style = None
        styles = [s for s in self.styles.get(event, []) if s != self.last_style.get(event)]
        if styles:
            style = random.choice(styles)
            self.last_style[event] = style
            instruction += f" {style}"
        instruction += INSTRUCTION_SUFFIX
        return instruction, style

    async def preview(self, event: str, values: Dict[str, Any], legacy_args: tuple = ()) -> Dict[str, Any]:
        """Пробная реплика для веб-панели: без озвучки и без записи в память"""
        instruction, style = self._instruction(event, values, legacy_args)
        text = await self._ask(instruction, event)
        return {"text": text, "style": style, "instruction": instruction}

    async def _handle(self, event: str, values: Dict[str, Any], legacy_args: tuple, log_text: str):
        instruction, _ = self._instruction(event, values, legacy_args)
        text = await self._ask(instruction, event)

        # Защита от повторов: один переспрос, потом запасная фраза
        if text and self._is_repeat(text):
            logging.info(f"[AI] Повтор, переспрашиваем: {text!r}")
            retry = await self._ask(instruction + RETRY_HINT.format(text=text), event)
            text = retry if retry and not self._is_repeat(retry, strict=True) else None
            if text is None:
                logging.info("[AI] Повтор после переспроса, используется запасная фраза")

        if text:
            self._remember(instruction, text)
            if event == "fact":
                self.recent_facts.append(text[:80])
        else:
            text = self._pick_fallback(event)

        if text:
            self.recent_replies.append(text)
        if self.events.maxlen:
            self.events.append((time.time(), log_text))
        self._save_memory()
        if text:
            await self.speak(text)

    def _is_repeat(self, text: str, strict: bool = False) -> bool:
        threshold = 0.85 if strict else self.repeat_threshold
        return any(similarity(text, old) >= threshold for old in self.recent_replies)

    def _pick_fallback(self, event: str) -> Optional[str]:
        options = self.fallbacks.get(event) or []
        fresh = [o for o in options if o not in self.recent_replies]
        pool = fresh or options
        return random.choice(pool) if pool else None

    def _remember(self, instruction: str, text: str):
        if self.history.maxlen:
            # В историю — инструкция без служебного хвоста, он лишь тратит контекст
            short = instruction.split("\nНе повторяй уже")[0].replace(INSTRUCTION_SUFFIX, "")
            self.history.append({"role": "user", "content": short})
            self.history.append({"role": "assistant", "content": text})

    async def _ask(self, instruction: str, event: str) -> Optional[str]:
        while True:
            system, messages = self._build_request(event, instruction)
            logging.debug(f"[AI SYSTEM] {system}\n[AI MESSAGES] {messages}")
            started = time.monotonic()
            try:
                raw = await self.client.chat(messages, system)
                break
            except Exception as e:
                if is_context_overflow(e) and self.context_budget > MIN_CONTEXT_BUDGET:
                    # Сервер запущен с маленьким окном: ужимаемся, пока не влезем.
                    # Урезанный бюджет сохраняется, следующие запросы сразу короче.
                    self.context_budget = max(MIN_CONTEXT_BUDGET, self.context_budget // 2)
                    logging.warning(f"[AI] Переполнен контекст сервера, бюджет урезан "
                                    f"до {self.context_budget} токенов")
                    continue
                logging.error(f"[AI] Ошибка генерации: {e}")
                return None
        text = self.clean_for_tts(raw)
        logging.info(f"[AI RESPONSE {time.monotonic() - started:.1f}s] {text!r}")
        if not text:
            logging.warning(f"[AI] Пустой ответ после очистки. Сырой ответ: {raw!r}")
            return None
        return text

    # ---------- постобработка ----------

    def clean_for_tts(self, text: str) -> str:
        if not text:
            return ""
        # Рассуждения reasoning-моделей
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        if "</think>" in text:
            text = text.split("</think>")[-1]
        text = re.sub(r"</?\w+[^>]*>", "", text)
        # Метка имени в начале: "Ева: ..."
        text = re.sub(rf"^\s*{re.escape(self.assistant_name)}\s*:\s*", "", text)
        # Ремарки *улыбается* и разметка markdown
        text = re.sub(r"(?<!\*)\*(?!\*)[^*\n]{1,60}(?<!\*)\*(?!\*)", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[*_#`~>|]+", "", text)
        text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
        text = EMOJI_RE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()

        return self._limit_sentences(text)

    def _limit_sentences(self, text: str) -> str:
        """Жёстко ограничивает длину: маленькие модели игнорируют просьбы
        отвечать коротко и задают вопросы, хотя пользователь не ответит."""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]
        # Последний фрагмент без точки обрезан лимитом токенов
        if len(sentences) > 1 and not re.search(r"[.!?…]$", sentences[-1]):
            sentences.pop()
        # Приветствие в начале реплики не нужно
        if len(sentences) > 1 and GREETING_RE.match(sentences[0]):
            sentences.pop(0)
        elif sentences:
            sentences[0] = GREETING_RE.sub("", sentences[0]) or sentences[0]
        # Вопросы в конце убираем, а вопрос-вступление («Знаешь ли ты, что...?»)
        # оставляем: в нём часто и есть смысл реплики
        if self.drop_questions:
            while len(sentences) > 1 and sentences[-1].endswith("?"):
                sentences.pop()
        if self.max_sentences > 0:
            sentences = sentences[:self.max_sentences]
        text = " ".join(sentences)

        if len(text) > self.max_chars:
            cut = text[:self.max_chars]
            end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            text = cut[:end + 1] if end > self.max_chars // 3 else cut.rsplit(" ", 1)[0] + "."
        return text
