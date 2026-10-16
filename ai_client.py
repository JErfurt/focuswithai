# ---------------------------------------------------------------
# AI Client Module
# Описание: Модуль для работы с различными AI провайдерами
# Поддерживаемые провайдеры:
#   - llama            : llama.cpp сервер, эндпоинт /completion (сырой промпт)
#   - openai           : любой OpenAI-совместимый /v1/chat/completions
#                        (llama.cpp, Ollama, LM Studio, OpenAI, OpenRouter...)
#   - google_assistant : Google Gemini API (алиас: gemini)
# Все клиенты асинхронные (aiohttp), с таймаутами и повторами.
# ---------------------------------------------------------------

import asyncio
import logging
import random
import re
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

import aiohttp

# Сообщение диалога: {"role": "user" | "assistant", "content": "..."}
Message = Dict[str, str]

# HTTP статусы, при которых имеет смысл повторить запрос
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


def assistant_name(config: Dict[str, Any]) -> str:
    """Имя персонажа: из assistant_name, иначе из хвоста старого
    сабпромпта вида '...\\nНастя:', иначе 'Ева'"""
    if config.get('assistant_name'):
        return config['assistant_name']
    match = re.search(r"\n([^\n:]{1,30}):\s*$", config.get('punishment_subprompt', ''))
    return match.group(1).strip() if match else 'Ева'


class AIError(Exception):
    """Ошибка генерации ответа"""


class AIClient(ABC):
    """Абстрактный класс для AI клиентов"""

    name = "base"

    def __init__(self, config: Dict[str, Any]):
        self.timeout = config.get('ai_timeout', 30)
        self.retries = config.get('ai_retries', 2)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post_json(self, url: str, payload: Dict[str, Any],
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """POST с повторами и экспоненциальной задержкой"""
        session = await self._get_session()
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        return await response.json(content_type=None)
                    body = (await response.text())[:500]
                    last_error = AIError(f"{self.name}: HTTP {response.status}: {body}")
                    if response.status not in RETRY_STATUSES:
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = AIError(f"{self.name}: сетевая ошибка: {e!r}")

            if attempt < self.retries:
                delay = 2 ** attempt + random.random()
                logging.warning(f"{last_error}. Повтор через {delay:.1f} с")
                await asyncio.sleep(delay)
        raise last_error or AIError(f"{self.name}: неизвестная ошибка")

    @abstractmethod
    async def chat(self, messages: List[Message], system: str = "") -> str:
        """Генерирует ответ ассистента на диалог. Бросает AIError при неудаче."""

    @abstractmethod
    async def check_available(self) -> bool:
        """Проверяет доступность сервиса"""

    async def generate_response(self, prompt: str) -> str:
        """Совместимость со старым интерфейсом: один промпт -> ответ"""
        return await self.chat([{"role": "user", "content": prompt}])


class LlamaClient(AIClient):
    """Клиент для llama.cpp сервера (эндпоинт /completion с сырым промптом).
    Диалог разворачивается в текстовый транскрипт вида
    '<system>\\n\\nSystem: ...\\nЕва: ...\\nSystem: ...\\nЕва:'"""

    name = "llama"

    # Параметры сэмплирования, которые передаются серверу как есть
    SAMPLING_KEYS = {
        'n_predict': 400, 'temperature': 0.7, 'repeat_last_n': 256,
        'repeat_penalty': 1.18, 'penalize_nl': False, 'top_k': 40,
        'top_p': 0.95, 'min_p': 0.05, 'tfs_z': 1, 'typical_p': 1,
        'presence_penalty': 0, 'frequency_penalty': 0, 'mirostat': 0,
        'mirostat_tau': 5, 'mirostat_eta': 0.1, 'grammar': '',
        'n_probs': 0, 'min_keep': 0, 'cache_prompt': True,
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.url = config.get('llama_url', 'http://127.0.0.1:8080/completion')
        self.api_key = config.get('api_key', '')
        self.assistant_label = assistant_name(config)
        self.user_label = config.get('llama_user_label', 'System')
        self.sampling = {k: config.get(k, v) for k, v in self.SAMPLING_KEYS.items()}
        stop = list(config.get('stop', ["</s>", "User:"]))
        for label in (f"{self.assistant_label}:", f"{self.user_label}:"):
            if label not in stop:
                stop.append(label)
        self.stop = stop

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def render_prompt(self, messages: List[Message], system: str) -> str:
        parts = [system.strip()] if system else []
        for msg in messages:
            label = self.assistant_label if msg["role"] == "assistant" else self.user_label
            parts.append(f"{label}: {msg['content'].strip()}")
        parts.append(f"{self.assistant_label}:")
        return "\n\n".join(parts)

    async def check_available(self) -> bool:
        try:
            session = await self._get_session()
            health_url = self.url.rsplit('/', 1)[0] + '/health'
            async with session.get(health_url, headers=self._headers(),
                                   timeout=aiohttp.ClientTimeout(total=5)) as r:
                return r.status == 200
        except Exception:
            return False

    async def chat(self, messages: List[Message], system: str = "") -> str:
        payload = dict(self.sampling)
        payload.update({
            "stream": False,
            "stop": self.stop,
            "prompt": self.render_prompt(messages, system),
        })
        result = await self._post_json(self.url, payload, self._headers())
        return result.get("content", "").strip()


class OpenAICompatibleClient(AIClient):
    """Клиент для OpenAI-совместимого Chat Completions API.
    Работает с llama.cpp (/v1), Ollama, LM Studio, vLLM, OpenAI, OpenRouter и т.д.
    Преимущество перед /completion: сервер сам применяет chat-шаблон модели."""

    name = "openai"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get('openai_base_url', 'http://127.0.0.1:8080/v1').rstrip('/')
        self.api_key = config.get('openai_api_key', '')
        self.model = config.get('openai_model', 'local-model')
        self.max_tokens = config.get('openai_max_tokens', 300)
        # Как в web UI llama.cpp: сэмплинг отправляется, только если задан явно.
        # Иначе сервер берёт параметры из флагов запуска и из метаданных GGUF,
        # где авторы модели прописывают рекомендованные значения
        # (например, у LFM2.5 temperature 0.1, top_k 50).
        self.sampling = {key: config[f'openai_{key}'] for key in self.SAMPLING_KEYS
                         if config.get(f'openai_{key}') is not None}
        self.thinking = config.get('openai_thinking', False)
        self.extra = config.get('openai_extra_params', {})

    SAMPLING_KEYS = ('temperature', 'top_k', 'top_p', 'min_p', 'presence_penalty',
                     'frequency_penalty', 'repeat_penalty')

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def check_available(self) -> bool:
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/models", headers=self._headers(),
                                   timeout=aiohttp.ClientTimeout(total=5)) as r:
                return r.status == 200
        except Exception:
            return False

    async def chat(self, messages: List[Message], system: str = "") -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        payload = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": self.max_tokens,
            "stream": False,
            **self.sampling,
        }
        if not self.thinking:
            # Короткие голосовые реплики не нуждаются в рассуждениях.
            # enable_thinking понимают шаблоны Qwen3 и подобных (так делает web UI),
            # thinking_budget_tokens=0 закрывает рассуждение у шаблонов,
            # которые всегда открывают <think> (LFM2.5)
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            payload["thinking_budget_tokens"] = 0
        payload.update(self.extra)
        result = await self._post_json(f"{self.base_url}/chat/completions", payload, self._headers())
        try:
            choice = result["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise AIError(f"{self.name}: неожиданный формат ответа: {str(result)[:300]}")
        content = (message.get("content") or "").strip()
        if not content and message.get("reasoning_content"):
            # Рассуждающая модель потратила весь лимит на размышления
            raise AIError(f"{self.name}: ответ пуст, модель только рассуждала "
                          f"(finish_reason={choice.get('finish_reason')}). Проверьте openai_thinking: false "
                          "или запустите llama-server с --reasoning-budget 0")
        return content


class GeminiClient(AIClient):
    """Клиент для Google Gemini API (generateContent)"""

    name = "gemini"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get('google_assistant_api_key', '')
        self.model = config.get('google_model', 'gemini-2.5-flash')
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        self.max_tokens = config.get('google_max_tokens', 400)
        self.temperature = config.get('google_temperature', 0.7)
        self.top_p = config.get('google_top_p', 0.95)
        self.top_k = config.get('google_top_k', 40)
        # У 2.5-моделей "размышления" съедают лимит maxOutputTokens, и ответ
        # приходит пустым. Для коротких реплик размышления не нужны.
        default_budget = 0 if '2.5-flash' in self.model else None
        self.thinking_budget = config.get('google_thinking_budget', default_budget)

    async def check_available(self) -> bool:
        return bool(self.api_key)

    async def chat(self, messages: List[Message], system: str = "") -> str:
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        generation_config: Dict[str, Any] = {
            "maxOutputTokens": self.max_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
            "topK": self.top_k,
        }
        if self.thinking_budget is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}
        payload: Dict[str, Any] = {"contents": contents, "generationConfig": generation_config}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        # Ключ передаётся заголовком, а не в URL, чтобы не попадать в логи
        result = await self._post_json(self.url, payload, {"x-goog-api-key": self.api_key})

        block_reason = result.get("promptFeedback", {}).get("blockReason")
        if block_reason:
            raise AIError(f"{self.name}: запрос заблокирован: {block_reason}")
        candidates = result.get("candidates") or []
        if not candidates:
            raise AIError(f"{self.name}: пустой список кандидатов")
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if not text:
            raise AIError(f"{self.name}: пустой ответ (finishReason={candidate.get('finishReason')})")
        return text


class FallbackClient(AIClient):
    """Перебирает провайдеров по очереди, пока один не вернёт непустой ответ"""

    name = "fallback"

    def __init__(self, clients: List[AIClient]):
        self.clients = clients
        self._session = None

    async def check_available(self) -> bool:
        results = await asyncio.gather(*(c.check_available() for c in self.clients))
        return any(results)

    async def chat(self, messages: List[Message], system: str = "") -> str:
        errors = []
        for client in self.clients:
            try:
                text = await client.chat(messages, system)
                if text:
                    return text
                errors.append(f"{client.name}: пустой ответ")
            except Exception as e:
                errors.append(str(e))
                logging.warning(f"Провайдер {client.name} не ответил, пробуем следующий: {e}")
        raise AIError("; ".join(errors) or "нет провайдеров")

    async def close(self):
        for client in self.clients:
            await client.close()


PROVIDERS = {
    'llama': LlamaClient,
    'openai': OpenAICompatibleClient,
    'google_assistant': GeminiClient,
    'gemini': GeminiClient,
}


class AIClientFactory:
    """Фабрика для создания AI клиентов"""

    @staticmethod
    def _create_single(provider: str, config: Dict[str, Any]) -> AIClient:
        cls = PROVIDERS.get(provider.lower())
        if cls is None:
            logging.warning(f"Неизвестный AI провайдер: {provider}. Используется llama.")
            cls = LlamaClient
        return cls(config)

    @staticmethod
    def create_client(config: Dict[str, Any]) -> AIClient:
        """Создает AI клиент. Если задан ai_fallback_providers,
        возвращает цепочку: основной провайдер, затем резервные."""
        main_provider = config.get('ai_provider', 'llama')
        fallbacks = [p for p in config.get('ai_fallback_providers', []) if p != main_provider]
        if not fallbacks:
            return AIClientFactory._create_single(main_provider, config)
        return FallbackClient([AIClientFactory._create_single(p, config)
                               for p in [main_provider, *fallbacks]])

    @staticmethod
    async def get_available_providers(config: Dict[str, Any]) -> Dict[str, bool]:
        """Возвращает доступность каждого провайдера"""
        result = {}
        for name, cls in PROVIDERS.items():
            if name == 'gemini':
                continue
            client = cls(config)
            try:
                result[name] = await client.check_available()
            finally:
                await client.close()
        return result
