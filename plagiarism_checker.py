# plagiarism_checker.py
import hashlib
import sqlite3
import json
import logging
import re
from typing import Set, List, Dict, Optional, Tuple
from pathlib import Path
import config  # <-- ДОБАВЛЕНО

logger = logging.getLogger(__name__)
PLAGIARISM_DB = config.DATA_DIR / "plagiarism.db"
SHINGLE_SIZE = 10
MIN_TEXT_LENGTH = 100

STOPWORDS = set([
    'и', 'в', 'на', 'с', 'по', 'к', 'у', 'о', 'от', 'из', 'за', 'при',
    'для', 'без', 'через', 'над', 'под', 'об', 'про', 'до', 'после',
    'это', 'этот', 'эта', 'это', 'эти', 'тот', 'та', 'те', 'все',
    'весь', 'вся', 'все', 'всё', 'который', 'которая', 'которое', 'которые',
    'быть', 'являться', 'становиться', 'иметь', 'делать', 'сказать',
    'мочь', 'знать', 'хотеть', 'видеть', 'слышать', 'думать',
    'как', 'так', 'же', 'бы', 'не', 'ни', 'ли', 'только', 'ещё', 'уже',
    'где', 'когда', 'почему', 'зачем', 'какой', 'чей', 'сколько',
])


def _init_db():
    conn = sqlite3.connect(str(PLAGIARISM_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS text_hashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE,
            shingle_hashes TEXT,
            word_count INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


_init_db()


def tokenize_text(text: str) -> List[str]:
    text = re.sub(r'[^а-яА-Яa-zA-Z0-9\s]', ' ', text)
    return text.lower().split()


def compute_shingles(words: List[str], n: int = SHINGLE_SIZE) -> Set[int]:
    if len(words) < n:
        return set()
    shingles = set()
    for i in range(len(words) - n + 1):
        shingle = ' '.join(words[i:i+n])
        h = hashlib.sha1(shingle.encode('utf-8')).digest()
        shingle_hash = int.from_bytes(h[:8], byteorder='big')
        shingles.add(shingle_hash)
    return shingles


def compute_shingles_from_text(text: str, n: int = SHINGLE_SIZE) -> Set[int]:
    words = tokenize_text(text)
    return compute_shingles(words, n)


def save_text_hashes(doc_id: str, shingles: Set[int], word_count: int):
    conn = sqlite3.connect(str(PLAGIARISM_DB))
    hashes_json = json.dumps(list(shingles))
    conn.execute(
        "INSERT OR REPLACE INTO text_hashes (doc_id, shingle_hashes, word_count, created_at) VALUES (?, ?, ?, datetime('now'))",
        (doc_id, hashes_json, word_count)
    )
    conn.commit()
    conn.close()


def load_all_shingle_hashes() -> List[Tuple[str, Set[int], int]]:
    conn = sqlite3.connect(str(PLAGIARISM_DB))
    rows = conn.execute("SELECT doc_id, shingle_hashes, word_count FROM text_hashes").fetchall()
    conn.close()
    result = []
    for doc_id, hashes_json, word_count in rows:
        try:
            hashes = set(json.loads(hashes_json))
            result.append((doc_id, hashes, word_count))
        except:
            continue
    return result


def compute_uniqueness(text: str, existing_docs: Optional[List[Tuple[str, Set[int], int]]] = None,
                       n: int = SHINGLE_SIZE, threshold: float = 0.5) -> Dict:
    words = tokenize_text(text)
    word_count = len(words)
    if word_count < MIN_TEXT_LENGTH:
        return {"uniqueness_percent": 100.0, "total_shingles": 0, "unique_shingles": 0,
                "duplicates": [], "word_count": word_count, "status": "too_short",
                "message": "Текст слишком короткий"}

    shingles = compute_shingles(words, n)
    if not shingles:
        return {"uniqueness_percent": 100.0, "total_shingles": 0, "unique_shingles": 0,
                "duplicates": [], "word_count": word_count, "status": "no_shingles",
                "message": "Не удалось построить шинглы"}

    if existing_docs is None:
        existing_docs = load_all_shingle_hashes()

    overlaps = []
    total_shingles = len(shingles)
    duplicate_shingles = set()

    for doc_id, doc_shingles, doc_wc in existing_docs:
        intersection = shingles.intersection(doc_shingles)
        if intersection:
            overlap_ratio = len(intersection) / total_shingles
            overlaps.append((doc_id, overlap_ratio, len(intersection)))
            duplicate_shingles.update(intersection)

    unique_shingles = total_shingles - len(duplicate_shingles)
    uniqueness = (unique_shingles / total_shingles) * 100 if total_shingles > 0 else 100.0
    overlaps.sort(key=lambda x: x[1], reverse=True)
    duplicates_report = [
        {"doc_id": doc_id, "overlap": round(overlap * 100, 2), "common_shingles": common}
        for doc_id, overlap, common in overlaps[:5]
    ]

    if uniqueness >= 85:
        status = "unique"
        message = "Текст уникален"
    elif uniqueness >= 60:
        status = "maybe_plagiarized"
        message = "Обнаружены средние пересечения"
    else:
        status = "plagiarized"
        message = "Высокая степень пересечения"

    return {
        "uniqueness_percent": round(uniqueness, 2),
        "total_shingles": total_shingles,
        "unique_shingles": unique_shingles,
        "duplicates": duplicates_report,
        "word_count": word_count,
        "status": status,
        "message": message
    }


def compute_text_quality(text: str) -> Dict:
    words = tokenize_text(text)
    word_count = len(words)
    if word_count == 0:
        return {"error": "Текст пуст"}

    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    avg_sentence_len = sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0

    stopword_count = sum(1 for w in words if w in STOPWORDS)
    stopword_ratio = stopword_count / word_count if word_count > 0 else 0

    unique_words = len(set(words))
    diversity = unique_words / word_count if word_count > 0 else 0

    watery_score = (stopword_ratio * 0.5 + (1 - diversity) * 0.3 + (1 - min(avg_sentence_len / 20, 1)) * 0.2) * 100
    watery_score = min(100, watery_score)

    return {
        "word_count": word_count,
        "sentence_count": len(sentences),
        "avg_sentence_length": round(avg_sentence_len, 1),
        "unique_words": unique_words,
        "diversity": round(diversity * 100, 2),
        "stopword_ratio": round(stopword_ratio * 100, 2),
        "watery_score": round(watery_score, 1),
        "status": "good" if watery_score < 40 else "maybe_watery" if watery_score < 70 else "watery"
    }


def check_plagiarism(text: str, doc_id: Optional[str] = None) -> Dict:
    if len(text.strip()) < 50:
        return {"error": "Текст слишком короткий", "uniqueness_percent": 100, "status": "too_short"}
    uniqueness_result = compute_uniqueness(text)
    quality_result = compute_text_quality(text)
    result = {**uniqueness_result, **quality_result}
    if doc_id:
        words = tokenize_text(text)
        shingles = compute_shingles(words, SHINGLE_SIZE)
        if shingles:
            save_text_hashes(doc_id, shingles, len(words))
    return result


def get_plagiarism_report(result: Dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    lines = []
    lines.append("📊 **Отчёт о проверке уникальности**")
    lines.append(f"📝 Уникальность: **{result.get('uniqueness_percent', 0):.1f}%**")
    lines.append(f"📄 Статус: {result.get('message', '')}")
    lines.append(f"📏 Всего шинглов: {result.get('total_shingles', 0)}")
    lines.append(f"✅ Уникальных шинглов: {result.get('unique_shingles', 0)}")
    lines.append(f"📚 Слов в тексте: {result.get('word_count', 0)}")
    lines.append(f"📝 Предложений: {result.get('sentence_count', 0)}")
    lines.append(f"📏 Средняя длина предложения: {result.get('avg_sentence_length', 0)} слов")
    lines.append(f"🔤 Разнообразие слов: {result.get('diversity', 0):.1f}%")
    lines.append(f"📌 Доля стоп-слов: {result.get('stopword_ratio', 0):.1f}%")
    lines.append(f"💧 Водянистость: {result.get('watery_score', 0):.1f}%")
    if result.get('duplicates'):
        lines.append("🔍 **Найдены пересечения:**")
        for dup in result['duplicates'][:5]:
            lines.append(f"  • {dup['doc_id']} — совпадение {dup['overlap']:.1f}% ({dup['common_shingles']} шинглов)")
    else:
        lines.append("✅ Пересечений не обнаружено.")
    if result.get('status') == 'unique':
        lines.append("✅ Текст уникален.")
    elif result.get('status') == 'maybe_plagiarized':
        lines.append("⚠️ Рекомендуется доработать текст.")
    elif result.get('status') == 'plagiarized':
        lines.append("❌ Текст имеет высокую степень заимствования.")
    return "\n".join(lines)