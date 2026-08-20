# llm_client.py
import logging
import time
from groq import Groq
import config

logger = logging.getLogger(__name__)

# Доступные модели (приоритет)
POWERFUL_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
]

FAST_MODELS = [
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
]

class GroqClientPool:
    def __init__(self, api_keys):
        self.keys = api_keys
        self.current_index = 0
        self.failed_keys = set()

    def get_next_key(self):
        if not self.keys:
            raise ValueError("No Groq API keys")
        start = self.current_index
        attempts = 0
        while attempts < len(self.keys):
            idx = (start + attempts) % len(self.keys)
            key = self.keys[idx]
            if key not in self.failed_keys:
                self.current_index = (idx + 1) % len(self.keys)
                return key
            attempts += 1
        self.failed_keys.clear()
        self.current_index = 0
        return self.keys[0]

    def mark_failed(self, key):
        self.failed_keys.add(key)
        logger.warning(f"Key {key[:8]}... marked failed")

_api_keys = config.GROQ_API_KEYS
_client_pool = GroqClientPool(_api_keys) if _api_keys else None

def get_client():
    if _client_pool is None:
        raise ValueError("No Groq API keys configured")
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
    if model == "powerful":
        models_to_try = POWERFUL_MODELS
    else:
        models_to_try = FAST_MODELS

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_exception = None
    current_num_predict = num_predict

    for model_name in models_to_try:
        for attempt in range(retries * len(_api_keys) + 1):
            try:
                client, current_key = get_client()
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=current_num_predict,
                    stream=False,
                    stop=None,
                )
                logger.info(f"✅ Used model: {model_name} with key {current_key[:8]}")
                return response.choices[0].message.content.strip()
            except Exception as e:
                error_msg = str(e).lower()
                if "model_not_found" in error_msg or "does not exist" in error_msg or "decommissioned" in error_msg:
                    logger.warning(f"❌ Model {model_name} unavailable: {e}. Trying next model.")
                    break
                if "rate_limit" in error_msg or "429" in error_msg or "quota" in error_msg:
                    _client_pool.mark_failed(current_key)
                    logger.warning(f"⛔ Key exhausted, trying next key.")
                    time.sleep(2)
                    continue
                if "payload too large" in error_msg or "413" in error_msg:
                    current_num_predict = max(500, current_num_predict // 2)
                    logger.warning(f"⚠️ Payload too large, reducing max_tokens to {current_num_predict} and retrying...")
                    continue
                last_exception = e
                logger.warning(f"⚠️ Error with {model_name} (attempt {attempt+1}): {e}")
                time.sleep(2 ** (attempt % 3))
        # Если не сработала модель – идём к следующей

    raise RuntimeError(f"All models failed. Last error: {last_exception}")