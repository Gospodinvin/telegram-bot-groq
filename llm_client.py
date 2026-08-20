# llm_client.py
import os
import logging
import time
import random
from groq import Groq
import config

logger = logging.getLogger(__name__)

# Доступные модели Groq
MODELS = {
    "powerful": "llama-3.3-70b-versatile",   # для диплома, сложных задач
    "fast": "llama-3.1-8b-instant",          # для конспектов, гуманизации, шпаргалок
}

class GroqClientPool:
    """Управление несколькими API-ключами с автоматическим переключением."""
    def __init__(self, api_keys):
        self.keys = api_keys
        self.current_index = 0
        self.failed_keys = set()
        self._lock = False  # упрощённо, при многопоточности использовать threading.Lock

    def get_next_key(self):
        """Возвращает следующий рабочий ключ, циклически."""
        if not self.keys:
            raise ValueError("Нет доступных API-ключей Groq")
        start = self.current_index
        attempts = 0
        while attempts < len(self.keys):
            idx = (start + attempts) % len(self.keys)
            key = self.keys[idx]
            if key not in self.failed_keys:
                self.current_index = (idx + 1) % len(self.keys)
                return key
            attempts += 1
        # Все ключи помечены как failed – сбросим и попробуем ещё раз (может, лимит восстановился)
        self.failed_keys.clear()
        self.current_index = 0
        return self.keys[0]

    def mark_failed(self, key):
        """Пометить ключ как исчерпанный."""
        self.failed_keys.add(key)
        logger.warning(f"Ключ {key[:8]}... помечен как исчерпанный. Осталось рабочих: {len(self.keys)-len(self.failed_keys)}")

# Инициализация пула
_api_keys = config.GROQ_API_KEYS  # список строк
_client_pool = GroqClientPool(_api_keys) if _api_keys else None

def get_client():
    if _client_pool is None:
        raise ValueError("Не заданы API-ключи Groq (GROQ_API_KEYS)")
    key = _client_pool.get_next_key()
    return Groq(api_key=key), key

def call_llm(
    prompt: str,
    system: str = None,
    model: str = "fast",
    num_predict: int = 4000,
    temperature: float = 0.85,
    top_p: float = 0.9,
    retries: int = 2
) -> str:
    """
    Универсальная функция вызова Groq с автоматическим переключением ключей.
    model: 'powerful' или 'fast' (или можно передать точное имя модели)
    """
    model_name = MODELS.get(model, model)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_exception = None
    # Пытаемся использовать разные ключи
    for attempt in range(retries * len(_api_keys)):
        try:
            client, current_key = get_client()
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                max_tokens=num_predict,
                stream=False,
                stop=None,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            error_msg = str(e).lower()
            if "rate_limit" in error_msg or "insufficient_quota" in error_msg or "quota" in error_msg:
                _client_pool.mark_failed(current_key)
                logger.warning(f"Ключ исчерпан, переключаемся на следующий. Ошибка: {e}")
                continue
            last_exception = e
            logger.warning(f"Ошибка при вызове Groq (попытка {attempt+1}): {e}")
            time.sleep(2 ** (attempt % 3))
    raise RuntimeError(f"Groq не ответил после всех попыток") from last_exception