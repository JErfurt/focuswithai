# ---------------------------------------------------------------
# Focus Assistant
# Описание: Логика общения с нейросетью: сборка системного промпта
#           с контекстом, память диалога, статистика отвлечений,
#           очистка ответа для TTS и запасные фразы при сбоях.
# ---------------------------------------------------------------

import logging
import random
import re
import time
from collections import Counter, deque
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ai_client import AIClient, Message, assistant_name

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

# Какой контекст нужен модели для каждого события. Лишний контекст
# маленькие модели пересказывают в каждой реплике.
EVENT_CONTEXT = {
    "punishment": {"distractions"},
    "praise": {"session"},
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
        self.history: deque = deque(maxlen=max(0, config.get('ai_history_size', 10)))
        self.recent_facts: deque = deque(maxlen=10)

        self.fallbacks = {**DEFAULT_FALLBACKS, **config.get('fallback_phrases', {})}
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

    # ---------- контекст ----------

    def set_session(self, name: str, elapsed_min: int, total_min: int, focus: bool):
        kind = "фокус" if focus else "отдых"
        label = f" «{name}»" if name else ""
        self.session_info = f"Текущая сессия{label}: {kind}, прошло {elapsed_min} из {total_min} минут."

    def reset_session_stats(self):
        self.distractions.clear()

    def _system_prompt(self, event: str) -> str:
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
        return (f"{self.persona.strip()}\n\n{self.rules}\n\n"
                "Справочный контекст (упоминай только если это к месту, "
                "не пересказывай его):\n" + "\n".join(context))

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
        await self._handle("punishment", values, (values["target"], distraction))

    async def praise(self, target: str, focused_seconds: float):
        values = {
            "target": _short(target),
            "minutes": max(1, int(focused_seconds // 60)),
            "seconds": int(focused_seconds),
        }
        await self._handle("praise", values, (values["target"], values["seconds"]))

    async def fact(self):
        await self._handle("fact", {}, ())

    async def _handle(self, event: str, values: Dict[str, Any], legacy_args: tuple):
        template = self.templates[event]
        try:
            if self.legacy[event]:
                instruction = template.format(*legacy_args)
            else:
                instruction = template.format_map(_SafeDict(values))
        except (IndexError, KeyError, ValueError) as e:
            logging.warning(f"Ошибка в шаблоне '{event}': {e}. Используется шаблон по умолчанию.")
            instruction = DEFAULT_INSTRUCTIONS[event].format_map(_SafeDict(values))

        if event == "fact" and self.recent_facts:
            told = "; ".join(self.recent_facts)
            instruction += f"\nНе повторяй уже рассказанные факты: {told}"
        instruction += INSTRUCTION_SUFFIX

        text = await self._ask(instruction, event)
        if text and event == "fact":
            self.recent_facts.append(text[:80])
        if not text:
            options = self.fallbacks.get(event) or []
            text = random.choice(options) if options else None
        if text:
            await self.speak(text)

    async def _ask(self, instruction: str, event: str) -> Optional[str]:
        # Факты не зависят от диалога, а маленькие модели с историей
        # начинают отвечать на прошлые реплики вместо задания.
        # Повторы фактов отсекает recent_facts.
        history = [] if event == "fact" else list(self.history)
        messages: List[Message] = [*history, {"role": "user", "content": instruction}]
        system = self._system_prompt(event)
        logging.debug(f"[AI SYSTEM] {system}\n[AI USER] {instruction}")
        started = time.monotonic()
        try:
            raw = await self.client.chat(messages, system)
        except Exception as e:
            logging.error(f"[AI] Ошибка генерации: {e}")
            return None
        text = self.clean_for_tts(raw)
        logging.info(f"[AI RESPONSE {time.monotonic() - started:.1f}s] {text!r}")
        if not text:
            logging.warning(f"[AI] Пустой ответ после очистки. Сырой ответ: {raw!r}")
            return None
        if self.history.maxlen:
            self.history.append({"role": "user", "content": instruction})
            self.history.append({"role": "assistant", "content": text})
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
