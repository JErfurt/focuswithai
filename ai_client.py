# ---------------------------------------------------------------
# AI Client Module
# Описание: Модуль для работы с различными AI провайдерами
# Поддерживаемые провайдеры: Llama, Google Assistant
# ---------------------------------------------------------------

import json
import requests
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging

class AIClient(ABC):
    """Абстрактный класс для AI клиентов"""
    
    @abstractmethod
    async def generate_response(self, prompt: str) -> str:
        """Генерирует ответ на основе промпта"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Проверяет доступность сервиса"""
        pass

class LlamaClient(AIClient):
    """Клиент для работы с локальным Llama сервером"""
    
    def __init__(self, config: Dict[str, Any]):
        self.url = config.get('llama_url', 'http://127.0.0.1:8080/completion')
        self.stream = config.get('stream', False)
        self.n_predict = config.get('n_predict', 400)
        self.temperature = config.get('temperature', 0.7)
        self.stop = config.get('stop', ["</s>", "Ева:", "Георгий:", "User:"])
        self.repeat_last_n = config.get('repeat_last_n', 256)
        self.repeat_penalty = config.get('repeat_penalty', 1.18)
        self.penalize_nl = config.get('penalize_nl', False)
        self.top_k = config.get('top_k', 40)
        self.top_p = config.get('top_p', 0.95)
        self.min_p = config.get('min_p', 0.05)
        self.tfs_z = config.get('tfs_z', 1)
        self.typical_p = config.get('typical_p', 1)
        self.presence_penalty = config.get('presence_penalty', 0)
        self.frequency_penalty = config.get('frequency_penalty', 0)
        self.mirostat = config.get('mirostat', 0)
        self.mirostat_tau = config.get('mirostat_tau', 5)
        self.mirostat_eta = config.get('mirostat_eta', 0.1)
        self.grammar = config.get('grammar', '')
        self.n_probs = config.get('n_probs', 0)
        self.min_keep = config.get('min_keep', 0)
        self.image_data = config.get('image_data', [])
        self.cache_prompt = config.get('cache_prompt', True)
        self.api_key = config.get('api_key', '')
    
    def is_available(self) -> bool:
        """Проверяет доступность Llama сервера"""
        try:
            response = requests.get(self.url.replace('/completion', '/health'), timeout=5)
            return response.status_code == 200
        except:
            return False
    
    async def generate_response(self, prompt: str) -> str:
        """Генерирует ответ через Llama API"""
        try:
            payload = {
                "stream": self.stream,
                "n_predict": self.n_predict,
                "temperature": self.temperature,
                "stop": self.stop,
                "repeat_last_n": self.repeat_last_n,
                "repeat_penalty": self.repeat_penalty,
                "penalize_nl": self.penalize_nl,
                "top_k": self.top_k,
                "top_p": self.top_p,
                "min_p": self.min_p,
                "tfs_z": self.tfs_z,
                "typical_p": self.typical_p,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.frequency_penalty,
                "mirostat": self.mirostat,
                "mirostat_tau": self.mirostat_tau,
                "mirostat_eta": self.mirostat_eta,
                "grammar": self.grammar,
                "n_probs": self.n_probs,
                "min_keep": self.min_keep,
                "image_data": self.image_data,
                "cache_prompt": self.cache_prompt,
                "api_key": self.api_key,
                "prompt": prompt
            }
            
            response = requests.post(self.url, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return result.get("content", "").strip()
            else:
                logging.error(f"Llama API вернул ошибку: {response.status_code}")
                return "Извините, произошла ошибка при генерации ответа."
                
        except Exception as e:
            logging.error(f"Ошибка при запросе к Llama: {e}")
            return "Извините, не удалось подключиться к AI сервису."

class GoogleAssistantClient(AIClient):
    """Клиент для работы с Google Assistant API"""
    
    def __init__(self, config: Dict[str, Any]):
        self.api_key = config.get('google_assistant_api_key', '')
        self.project_id = config.get('google_project_id', '')
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
        self.max_tokens = config.get('google_max_tokens', 400)
        self.temperature = config.get('google_temperature', 0.7)
        self.top_p = config.get('google_top_p', 0.95)
        self.top_k = config.get('google_top_k', 40)
    
    def is_available(self) -> bool:
        """Проверяет доступность Google Assistant API"""
        return bool(self.api_key and self.project_id)
    
    async def generate_response(self, prompt: str) -> str:
        """Генерирует ответ через Google Assistant API"""
        try:
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "maxOutputTokens": self.max_tokens,
                    "temperature": self.temperature,
                    "topP": self.top_p,
                    "topK": self.top_k
                }
            }
            
            response = requests.post(self.url, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and len(result['candidates']) > 0:
                    content = result['candidates'][0]['content']
                    if 'parts' in content and len(content['parts']) > 0:
                        return content['parts'][0]['text'].strip()
                return "Извините, не удалось получить ответ от AI."
            else:
                logging.error(f"Google Assistant API вернул ошибку: {response.status_code}")
                return "Извините, произошла ошибка при генерации ответа."
                
        except Exception as e:
            logging.error(f"Ошибка при запросе к Google Assistant: {e}")
            return "Извините, не удалось подключиться к AI сервису."

class AIClientFactory:
    """Фабрика для создания AI клиентов"""
    
    @staticmethod
    def create_client(config: Dict[str, Any]) -> AIClient:
        """Создает AI клиент на основе конфигурации"""
        ai_provider = config.get('ai_provider', 'llama').lower()
        
        if ai_provider == 'llama':
            return LlamaClient(config)
        elif ai_provider == 'google_assistant':
            return GoogleAssistantClient(config)
        else:
            logging.warning(f"Неизвестный AI провайдер: {ai_provider}. Используется Llama.")
            return LlamaClient(config)
    
    @staticmethod
    def get_available_providers(config: Dict[str, Any]) -> Dict[str, bool]:
        """Возвращает список доступных провайдеров"""
        providers = {}
        
        # Проверяем Llama
        llama_client = LlamaClient(config)
        providers['llama'] = llama_client.is_available()
        
        # Проверяем Google Assistant
        google_client = GoogleAssistantClient(config)
        providers['google_assistant'] = google_client.is_available()
        
        return providers 