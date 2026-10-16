# ---------------------------------------------------------------
# TTS Module
# Описание: Озвучивание текста цепочкой движков. Если движок упал,
#           говорит следующий, а сломавшийся отключается на время.
# Движки:
#   - silero: Silero TTS (офлайн, PyTorch на CPU, живые русские голоса,
#             ~0.03 с на фразу; лицензия моделей CC BY-NC, только некоммерчески)
#   - edge  : Microsoft Edge TTS (онлайн, лучшее качество, но неофициальный
#             доступ и периодически ломается, лечится обновлением edge-tts)
#   - piper : Piper (офлайн, ONNX, хорошие русские голоса, ~60 МБ на голос)
#   - sapi  : голоса Windows (офлайн, ничего ставить не нужно, звучит роботизированно)
# ---------------------------------------------------------------

import asyncio
import io
import logging
import os
import sys
import tempfile
import time
import wave
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import pygame

# (аудио, формат для pygame: 'mp3' или 'wav')
Audio = Tuple[bytes, str]


class TTSEngine(ABC):
    name = "base"

    def available(self) -> bool:
        return True

    def warmup(self):
        """Тяжёлая подготовка (загрузка модели), вызывается заранее в фоне"""

    @abstractmethod
    async def synthesize(self, text: str) -> Audio:
        """Возвращает аудио. Бросает исключение при неудаче."""


def _pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Сырые 16-битные моно-сэмплы -> WAV"""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class SileroEngine(TTSEngine):
    name = "silero"

    def __init__(self, config: Dict[str, Any]):
        self.model_path = config.get('silero_model', 'voices/silero_v5_6_ru.pt')
        # aidar, baya, kseniya, xenia, eugene
        self.speaker = config.get('silero_speaker', 'xenia')
        self.sample_rate = config.get('silero_sample_rate', 48000)  # 8000, 24000, 48000
        # На многоядерных CPU быстрее всего ~8 потоков, дальше упирается в накладные расходы
        self.threads = config.get('silero_threads', 8)
        # SSML prosody: темп x-slow..x-fast, высота x-low..x-high (или проценты)
        self.rate = config.get('silero_rate', '')
        self.pitch = config.get('silero_pitch', '')
        self._model = None

    def available(self) -> bool:
        import importlib.util
        return importlib.util.find_spec('torch') is not None and os.path.exists(self.model_path)

    def warmup(self):
        if self._model is not None:
            return
        import torch
        torch.set_num_threads(self.threads)
        model = torch.package.PackageImporter(self.model_path).load_pickle("tts_models", "model")
        model.to(torch.device('cpu'))
        # Первый вызов в разы медленнее остальных (инициализация графа), отрабатываем его заранее
        model.apply_tts(text="Привет.", speaker=self.speaker, sample_rate=self.sample_rate)
        self._model = model

    def _synth(self, text: str) -> bytes:
        self.warmup()
        kwargs = {"speaker": self.speaker, "sample_rate": self.sample_rate}
        if self.rate or self.pitch:
            from xml.sax.saxutils import escape
            attrs = "".join(f' {k}="{v}"' for k, v in (("rate", self.rate), ("pitch", self.pitch)) if v)
            kwargs["ssml_text"] = f"<speak><prosody{attrs}>{escape(text)}</prosody></speak>"
        else:
            kwargs["text"] = text
        import torch
        audio = self._model.apply_tts(**kwargs)  # float-тензор -1..1
        pcm = (audio.clamp(-1, 1) * 32767).to(torch.int16).numpy().tobytes()
        return _pcm16_to_wav(pcm, self.sample_rate)

    async def synthesize(self, text: str) -> Audio:
        return await asyncio.to_thread(self._synth, text), "wav"


class EdgeEngine(TTSEngine):
    name = "edge"

    def __init__(self, config: Dict[str, Any]):
        self.voice = config.get('edge_tts_voice', "ru-RU-SvetlanaNeural")
        self.rate = config.get('edge_tts_rate', "+0%")
        self.timeout = config.get('edge_tts_timeout', 15)

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    async def synthesize(self, text: str) -> Audio:
        import edge_tts
        audio = io.BytesIO()

        async def run():
            async for chunk in edge_tts.Communicate(text, voice=self.voice, rate=self.rate).stream():
                if chunk["type"] == "audio":
                    audio.write(chunk["data"])

        await asyncio.wait_for(run(), self.timeout)
        if not audio.tell():
            raise RuntimeError("пустое аудио")
        return audio.getvalue(), "mp3"


class PiperEngine(TTSEngine):
    name = "piper"

    def __init__(self, config: Dict[str, Any]):
        self.model = config.get('piper_model', 'voices/ru_RU-irina-medium.onnx')
        # >1 медленнее, <1 быстрее
        self.length_scale = config.get('piper_length_scale', 1.0)
        self._voice = None

    def available(self) -> bool:
        try:
            import piper  # noqa: F401
        except ImportError:
            return False
        return os.path.exists(self.model)

    def warmup(self):
        from piper import PiperVoice
        if self._voice is None:
            self._voice = PiperVoice.load(self.model)

    def _synth(self, text: str) -> bytes:
        from piper import SynthesisConfig
        self.warmup()
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            self._voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=self.length_scale))
        return buf.getvalue()

    async def synthesize(self, text: str) -> Audio:
        return await asyncio.to_thread(self._synth, text), "wav"


class SapiEngine(TTSEngine):
    name = "sapi"

    def __init__(self, config: Dict[str, Any]):
        self.voice_name = config.get('sapi_voice', 'Irina')
        self.rate = config.get('sapi_rate', 0)  # -10..10

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import comtypes.client  # noqa: F401
            return True
        except ImportError:
            return False

    def _synth(self, text: str) -> bytes:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()  # COM нужно инициализировать в каждом потоке
        try:
            voice = comtypes.client.CreateObject('SAPI.SpVoice')
            voices = voice.GetVoices()
            for i in range(voices.Count):
                if self.voice_name.lower() in voices.Item(i).GetDescription().lower():
                    voice.Voice = voices.Item(i)
                    break
            voice.Rate = self.rate
            fmt = comtypes.client.CreateObject('SAPI.SpAudioFormat')
            fmt.Type = 22  # 22 кГц, 16 бит, моно
            stream = comtypes.client.CreateObject('SAPI.SpFileStream')
            stream.Format = fmt
            fd, path = tempfile.mkstemp(suffix='.wav')
            os.close(fd)
            try:
                stream.Open(path, 3)  # SSFMCreateForWrite
                voice.AudioOutputStream = stream
                voice.Speak(text)
                stream.Close()
                with open(path, 'rb') as f:
                    return f.read()
            finally:
                os.remove(path)
        finally:
            comtypes.CoUninitialize()

    async def synthesize(self, text: str) -> Audio:
        return await asyncio.to_thread(self._synth, text), "wav"


ENGINES = {'silero': SileroEngine, 'edge': EdgeEngine, 'piper': PiperEngine, 'sapi': SapiEngine}


class Speaker:
    """Озвучивает текст первым рабочим движком из цепочки tts_engines"""

    def __init__(self, config: Dict[str, Any]):
        # Сколько секунд не трогать движок после сбоя
        self.cooldown = config.get('tts_failure_cooldown', 600)
        self.engines: List[TTSEngine] = []
        for name in config.get('tts_engines', ['silero', 'edge', 'piper', 'sapi']):
            cls = ENGINES.get(name)
            if cls is None:
                logging.warning(f"[TTS] Неизвестный движок: {name}")
                continue
            engine = cls(config)
            if engine.available():
                self.engines.append(engine)
            else:
                logging.info(f"[TTS] Движок {name} недоступен (не установлен или нет модели)")
        self.disabled_until: Dict[str, float] = {}
        logging.info(f"[TTS] Цепочка движков: {[e.name for e in self.engines]}")

    async def warmup(self):
        """Загружает модели офлайн-движков заранее, чтобы первая реплика не ждала"""
        for engine in self.engines:
            try:
                started = time.time()
                await asyncio.to_thread(engine.warmup)
                logging.debug(f"[TTS] {engine.name} готов за {time.time() - started:.1f} с")
            except Exception as e:
                self.disabled_until[engine.name] = time.time() + self.cooldown
                logging.error(f"[TTS] Не удалось подготовить {engine.name}: {e!r}"[:400])

    async def synthesize(self, text: str) -> Optional[Audio]:
        now = time.time()
        for engine in self.engines:
            if self.disabled_until.get(engine.name, 0) > now:
                continue
            try:
                audio = await engine.synthesize(text)
                if engine.name in self.disabled_until:
                    logging.info(f"[TTS] Движок {engine.name} снова работает")
                    del self.disabled_until[engine.name]
                return audio
            except Exception as e:
                self.disabled_until[engine.name] = now + self.cooldown
                logging.error(f"[TTS] Движок {engine.name} не сработал, отключён на "
                              f"{self.cooldown // 60} мин: {e!r}"[:400])
        return None

    async def speak(self, text: str):
        audio = await self.synthesize(text)
        if audio is None:
            logging.error(f"[TTS] Ни один движок не смог озвучить: {text!r}")
            return
        data, fmt = audio
        try:
            # Sound декодирует и пересэмплирует фразу целиком один раз (без треска
            # от потокового ресэмплинга) и играет на своём канале, не мешая
            # звуку напоминания
            channel = pygame.mixer.Sound(file=io.BytesIO(data)).play()
            # Ожидание завершения воспроизведения без блокировки цикла событий
            while channel is not None and channel.get_busy():
                await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"[TTS] Ошибка воспроизведения: {e}")
