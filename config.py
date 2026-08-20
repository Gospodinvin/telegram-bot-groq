# config.py
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
FONTS_DIR = BASE_DIR / "fonts"
SAMPLES_DIR = BASE_DIR / "samples"
TEMP_DIR = BASE_DIR / "temp"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "bot.db"

for d in (FONTS_DIR, SAMPLES_DIR, TEMP_DIR, DATA_DIR, LOGS_DIR):
    d.mkdir(exist_ok=True)

# === Telegram ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@Gospodinvin")

# === Groq API Keys (поддержка нескольких ключей) ===
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", "").split(",")
GROQ_API_KEYS = [k.strip() for k in GROQ_API_KEYS if k.strip()]
# Если задан GROQ_API_KEY как одиночный, добавляем его
if not GROQ_API_KEYS and os.getenv("GROQ_API_KEY"):
    GROQ_API_KEYS = [os.getenv("GROQ_API_KEY")]
if not GROQ_API_KEYS:
    raise ValueError("GROQ_API_KEYS (или GROQ_API_KEY) не задан")

# === PostgreSQL (для Railway) ===
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Если нет DATABASE_URL, можно использовать SQLite (для локальной разработки)
    # Но мы всё равно предупредим, чтобы не забыли
    logging.warning("DATABASE_URL не задан, будет использоваться SQLite (данные не сохранятся при перезапуске)")
    # В продакшене лучше явно требовать DATABASE_URL
    # raise ValueError("DATABASE_URL не задан (нужен для PostgreSQL)")

# === Whisper (локальное распознавание) ===
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_NUM_WORKERS = int(os.getenv("WHISPER_WORKERS", "1"))

# === PDF шрифты ===
PDF_FONT_REGULAR = os.getenv("PDF_FONT_REGULAR", str(FONTS_DIR / "LiberationSerif-Regular.ttf"))
PDF_FONT_BOLD = os.getenv("PDF_FONT_BOLD", str(FONTS_DIR / "LiberationSerif-Bold.ttf"))

FONT_CANDIDATES = [
    ("LiberationSerif", FONTS_DIR / "LiberationSerif-Regular.ttf", FONTS_DIR / "LiberationSerif-Bold.ttf"),
    ("PTAstraSerif", FONTS_DIR / "PTAstraSerif-Regular.ttf", FONTS_DIR / "PTAstraSerif-Bold.ttf"),
    ("DejaVuSerif", FONTS_DIR / "DejaVuSerif.ttf", FONTS_DIR / "DejaVuSerif-Bold.ttf"),
    ("DejaVu", FONTS_DIR / "DejaVuSans.ttf", FONTS_DIR / "DejaVuSans-Bold.ttf"),
]

# === Платежи (опционально) ===
PRODAMUS_SECRET_KEY = os.getenv("PRODAMUS_SECRET_KEY", "")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://ваш-адрес.ngrok.io")

ENCRYPTION_SALT = os.getenv("ENCRYPTION_SALT", "lecturex-salt-2024")
ENCRYPT_TRANSCRIPTIONS = os.getenv("ENCRYPT_TRANSCRIPTIONS", "true").lower() == "true"

CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "1000"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "604800"))
CHART_DPI = int(os.getenv("CHART_DPI", "120"))

HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
DATA_COLLECTOR_TIMEOUT = int(os.getenv("DATA_COLLECTOR_TIMEOUT", "20"))

# === Промпты для гуманизации ===
HUMANIZE_PROMPT = """Ты — студент-гуманитарий, пишешь конспект своими словами.
Перепиши текст ниже так, чтобы он звучал естественно, живо, по-человечески.
Добавь лёгкую небрежность, разнообразь длину предложений, используй разговорные вводные.
Не добавляй новых фактов, не теряй смысл. Убери шаблонные ИИ-фразы.

Текст:
{text}
"""

HUMANIZE_DIPLOMA_PROMPT = """Ты — опытный научный редактор. Перепиши следующий академический текст так, чтобы он звучал максимально естественно, живо и убедительно, как если бы его писал учёный с большим стажем.

Требования:
- Избегай шаблонных фраз: «следует отметить», «важно подчеркнуть», «в заключение хочется сказать», «таким образом», «во-первых», «во-вторых» — заменяй их на разнообразные вводные конструкции.
- Чередуй длину предложений: короткие для акцента, длинные для объяснений.
- Используй активный залог чаще, чем пассивный.
- Добавляй оценочные суждения, сомнения, сравнения — текст должен отражать живую мысль, а не сухой пересказ.
- Не теряй научную точность и фактологию.
- Сохрани структуру разделов, но сделай переходы между ними плавными.
- Старайся избегать повторений одних и тех же слов в соседних предложениях.

Текст для редактирования:
{text}
"""

# === Планы подписки и разовые услуги ===
SUBSCRIPTION_PLANS = {
    'trial': {
        'name': '🎁 Пробный (1 день)',
        'price': 0,
        'price_stars': 0,
        'days': 1,
        'limits': {'daily_summaries': 100, 'export_pdf': 100, 'handwrite': 100, 'diploma_access': False}
    },
    'basic': {
        'name': '📚 Базовый (1 месяц)',
        'price': 299,
        'price_stars': 428,
        'days': 30,
        'limits': {'daily_summaries': 99999, 'export_pdf': 99999, 'handwrite': 99999, 'diploma_access': True}
    },
    'pro': {
        'name': '🚀 Про (3 мес)',
        'price': 699,
        'price_stars': 999,
        'days': 90,
        'limits': {'daily_summaries': 99999, 'export_pdf': 99999, 'handwrite': 99999, 'diploma_access': True}
    },
    'unlimited': {
        'name': '💎 Безлимитный (12 мес)',
        'price': 1999,
        'price_stars': 2856,
        'days': 365,
        'limits': {'daily_summaries': 99999, 'export_pdf': 99999, 'handwrite': 99999, 'diploma_access': True}
    }
}

ONE_TIME_PRICES = {
    'transcribe': {'rub': 100, 'stars': 143},
    'summarize': {'rub': 150, 'stars': 215},
    'humanize': {'rub': 100, 'stars': 143},
    'handwrite': {'rub': 50, 'stars': 72},
    'quiz': {'rub': 80, 'stars': 115},
    'mindmap': {'rub': 80, 'stars': 115},
    'export_pdf': {'rub': 50, 'stars': 72},
    'export_docx': {'rub': 50, 'stars': 72},
    'export_pptx': {'rub': 50, 'stars': 72},
    'export_anki': {'rub': 50, 'stars': 72},
    'cheatsheet': {'rub': 80, 'stars': 115},
}

# === Импорт из gost_standards (оставляем в конце) ===
from gost_standards import STANDARDS, WORK_TYPES