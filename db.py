# db.py — PostgreSQL с пулом соединений и retry-логикой
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import json
import logging
import time
from datetime import datetime, timedelta
import threading
import config

logger = logging.getLogger(__name__)

# Глобальный пул соединений
_pool = None
_lock = threading.Lock()

def get_pool(max_retries=10, delay=2):
    """Создаёт пул соединений с повторными попытками, если БД ещё не готова."""
    global _pool
    if _pool is not None:
        return _pool

    with _lock:
        if _pool is not None:
            return _pool

        last_exception = None
        for attempt in range(max_retries):
            try:
                _pool = psycopg2.pool.SimpleConnectionPool(
                    1, 10,
                    dsn=config.DATABASE_URL
                )
                logger.info("PostgreSQL пул соединений создан")
                return _pool
            except psycopg2.OperationalError as e:
                if "database system is starting up" in str(e):
                    wait = delay * (attempt + 1)
                    logger.warning(f"БД ещё запускается, ждём {wait} сек... (попытка {attempt+1}/{max_retries})")
                    time.sleep(wait)
                    last_exception = e
                    continue
                else:
                    logger.error(f"Ошибка создания пула PostgreSQL: {e}")
                    raise
            except Exception as e:
                logger.error(f"Неизвестная ошибка: {e}")
                raise

        logger.critical(f"Не удалось подключиться к БД после {max_retries} попыток")
        raise last_exception or RuntimeError("Не удалось подключиться к PostgreSQL")

def _conn():
    """Возвращает соединение из пула."""
    pool = get_pool()
    return pool.getconn()

def _release_conn(conn):
    """Возвращает соединение в пул."""
    pool = get_pool()
    pool.putconn(conn)

def init_db(max_retries=10, delay=2):
    """Инициализация таблиц с повторными попытками."""
    for attempt in range(max_retries):
        try:
            conn = _conn()
            break
        except psycopg2.OperationalError as e:
            if "database system is starting up" in str(e):
                wait = delay * (attempt + 1)
                logger.warning(f"БД ещё запускается, ждём {wait} сек... (попытка {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            else:
                raise
    else:
        raise RuntimeError("Не удалось инициализировать БД после нескольких попыток")

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT,
                    font_style TEXT DEFAULT 'cursive',
                    flags TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id BIGINT PRIMARY KEY,
                    plan TEXT DEFAULT 'trial',
                    start_date TEXT,
                    end_date TEXT,
                    active INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS usage_log (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    action TEXT,
                    date TEXT,
                    count INTEGER DEFAULT 0,
                    UNIQUE(user_id, action, date)
                );
                CREATE TABLE IF NOT EXISTS transcription_cache (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT,
                    text TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS task_queue (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    task_type TEXT,
                    payload TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    service_type TEXT,
                    plan TEXT,
                    service_name TEXT,
                    amount_rub INTEGER,
                    amount_stars INTEGER,
                    status TEXT DEFAULT 'pending',
                    screenshot_file_id TEXT,
                    created_at TEXT,
                    confirmed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status);
                CREATE INDEX IF NOT EXISTS idx_task_queue_created ON task_queue(created_at);
                CREATE INDEX IF NOT EXISTS idx_usage_log_user_date ON usage_log(user_id, date);
                CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
                CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
            """)
            conn.commit()
            logger.info("Таблицы PostgreSQL созданы/проверены")
    finally:
        _release_conn(conn)

# ---- Функции работы с пользователями ----
def ensure_user(user_id: int, username: str = None, first_name: str = None):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id=%s", (user_id,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO users (user_id, username, first_name, created_at, font_style, flags) VALUES (%s,%s,%s,%s,%s,%s)",
                    (user_id, username, first_name, datetime.now().isoformat(), 'cursive', '{}')
                )
                end = datetime.now() + timedelta(days=7)
                cur.execute(
                    "INSERT INTO subscriptions (user_id, plan, start_date, end_date, active) VALUES (%s,%s,%s,%s,1)",
                    (user_id, 'trial', datetime.now().isoformat(), end.isoformat())
                )
                conn.commit()
    finally:
        _release_conn(conn)

def get_user_prefs(user_id: int) -> dict:
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT font_style FROM users WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return {'font_style': row['font_style'] if row else 'cursive'}
    finally:
        _release_conn(conn)

def set_user_pref(user_id: int, key: str, value: str):
    allowed = {'font_style': 'font_style'}
    if key not in allowed:
        raise ValueError(f"Недопустимый ключ: {key}")
    col = allowed[key]
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {col}=%s WHERE user_id=%s", (value, user_id))
            conn.commit()
    finally:
        _release_conn(conn)

def get_user_flag(user_id: int, flag: str) -> bool:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT flags FROM users WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            if row:
                try:
                    flags = json.loads(row[0])
                    return flags.get(flag, False)
                except:
                    pass
            return False
    finally:
        _release_conn(conn)

def set_user_flag(user_id: int, flag: str, value: bool):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT flags FROM users WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            flags = {}
            if row:
                try:
                    flags = json.loads(row[0])
                except:
                    pass
            flags[flag] = value
            cur.execute("UPDATE users SET flags=%s WHERE user_id=%s", (json.dumps(flags), user_id))
            conn.commit()
    finally:
        _release_conn(conn)

# ---- Подписки ----
def get_subscription(user_id: int) -> dict:
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT plan, start_date, end_date, active FROM subscriptions WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            if not row:
                return {'plan': 'trial', 'start_date': datetime.now().isoformat(),
                        'end_date': (datetime.now() + timedelta(days=7)).isoformat(), 'active': True}
            sub = dict(row)
            if sub.get('active'):
                end = datetime.fromisoformat(sub['end_date'])
                if datetime.now() > end:
                    sub['active'] = False
                    cur.execute("UPDATE subscriptions SET active=0 WHERE user_id=%s", (user_id,))
                    conn.commit()
            return sub
    finally:
        _release_conn(conn)

def set_subscription(user_id: int, plan: str, days: int):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            start = datetime.now()
            end = start + timedelta(days=days)
            cur.execute(
                """INSERT INTO subscriptions (user_id, plan, start_date, end_date, active)
                   VALUES (%s,%s,%s,%s,1)
                   ON CONFLICT (user_id) DO UPDATE SET
                   plan=EXCLUDED.plan, start_date=EXCLUDED.start_date,
                   end_date=EXCLUDED.end_date, active=1""",
                (user_id, plan, start.isoformat(), end.isoformat())
            )
            conn.commit()
    finally:
        _release_conn(conn)

# ---- Лимиты ----
def check_limit(user_id: int, action: str, max_val: int) -> bool:
    if max_val == 99999:
        return True
    today = datetime.now().strftime('%Y-%m-%d')
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count FROM usage_log WHERE user_id=%s AND action=%s AND date=%s", (user_id, action, today))
            row = cur.fetchone()
            used = row[0] if row else 0
            return used < max_val
    finally:
        _release_conn(conn)

def use_limit(user_id: int, action: str):
    today = datetime.now().strftime('%Y-%m-%d')
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO usage_log (user_id, action, date, count) VALUES (%s,%s,%s,1)
                   ON CONFLICT (user_id, action, date) DO UPDATE SET count = usage_log.count + 1""",
                (user_id, action, today)
            )
            conn.commit()
    finally:
        _release_conn(conn)

def get_usage(user_id: int) -> dict:
    today = datetime.now().strftime('%Y-%m-%d')
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT action, count FROM usage_log WHERE user_id=%s AND date=%s", (user_id, today))
            rows = cur.fetchall()
            return {r['action']: r['count'] for r in rows}
    finally:
        _release_conn(conn)

# ---- Кеш транскрипций ----
def get_cached_transcription(url_hash: str) -> str | None:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT text FROM transcription_cache WHERE url_hash=%s", (url_hash,))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        _release_conn(conn)

def set_cached_transcription(url_hash: str, url: str, text: str):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO transcription_cache (url_hash, url, text, created_at) VALUES (%s,%s,%s,%s) ON CONFLICT (url_hash) DO UPDATE SET text=EXCLUDED.text, created_at=EXCLUDED.created_at",
                (url_hash, url, text, datetime.now().isoformat())
            )
            conn.commit()
    finally:
        _release_conn(conn)

# ---- Очередь задач ----
def add_task(user_id: int, task_type: str, payload: dict) -> int:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO task_queue (user_id, task_type, payload, status, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (user_id, task_type, json.dumps(payload, ensure_ascii=False), 'pending', datetime.now().isoformat())
            )
            task_id = cur.fetchone()[0]
            conn.commit()
            return task_id
    finally:
        _release_conn(conn)

def get_pending_task():
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM task_queue WHERE status='pending' ORDER BY created_at LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        _release_conn(conn)

def update_task_status(task_id: int, status: str):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            now = datetime.now().isoformat()
            if status == 'running':
                cur.execute("UPDATE task_queue SET status=%s, started_at=%s WHERE id=%s", (status, now, task_id))
            elif status == 'done':
                cur.execute("UPDATE task_queue SET status=%s, completed_at=%s WHERE id=%s", (status, now, task_id))
            else:
                cur.execute("UPDATE task_queue SET status=%s WHERE id=%s", (status, task_id))
            conn.commit()
    finally:
        _release_conn(conn)

def get_task_status(task_id: int) -> dict | None:
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, user_id, status FROM task_queue WHERE id=%s", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        _release_conn(conn)

def reset_running_tasks():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE task_queue SET status='pending' WHERE status='running'")
            conn.commit()
    finally:
        _release_conn(conn)

# ---- Платежи ----
def add_payment(user_id: int, service_type: str, plan: str = None, service_name: str = None,
                amount_rub: int = 0, amount_stars: int = 0, screenshot_file_id: str = None) -> int:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO payments
                   (user_id, service_type, plan, service_name, amount_rub, amount_stars, screenshot_file_id, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (user_id, service_type, plan, service_name, amount_rub, amount_stars, screenshot_file_id, datetime.now().isoformat())
            )
            payment_id = cur.fetchone()[0]
            conn.commit()
            return payment_id
    finally:
        _release_conn(conn)

def get_pending_payments() -> list:
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT p.*, u.username, u.first_name
                   FROM payments p
                   JOIN users u ON p.user_id = u.user_id
                   WHERE p.status = 'pending'
                   ORDER BY p.created_at ASC"""
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    finally:
        _release_conn(conn)

def confirm_payment(payment_id: int) -> bool:
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM payments WHERE id=%s AND status='pending'", (payment_id,))
            row = cur.fetchone()
            if not row:
                return False
            payment = dict(row)
            if payment['service_type'] == 'subscription':
                from config import SUBSCRIPTION_PLANS
                plan = payment['plan']
                days = SUBSCRIPTION_PLANS.get(plan, {}).get('days', 30)
                set_subscription(payment['user_id'], plan, days)
            elif payment['service_type'] == 'one_time':
                set_user_flag(payment['user_id'], f"one_time_{payment['service_name']}", True)
            cur.execute("UPDATE payments SET status='confirmed', confirmed_at=%s WHERE id=%s", (datetime.now().isoformat(), payment_id))
            conn.commit()
            return True
    finally:
        _release_conn(conn)

def reject_payment(payment_id: int) -> bool:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM payments WHERE id=%s", (payment_id,))
            row = cur.fetchone()
            if not row or row[0] != 'pending':
                return False
            cur.execute("UPDATE payments SET status='rejected' WHERE id=%s", (payment_id,))
            conn.commit()
            return True
    finally:
        _release_conn(conn)

def get_payments_for_user(user_id: int, limit: int = 10) -> list:
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM payments WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    finally:
        _release_conn(conn)

# ---- Очистка старых записей ----
def cleanup_old_records(days: int = 30):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usage_log WHERE date < %s", (cutoff[:10],))
            cur.execute("DELETE FROM transcription_cache WHERE created_at < %s", (cutoff,))
            cur.execute("DELETE FROM task_queue WHERE status IN ('done', 'error', 'cancelled') AND completed_at < %s", (cutoff,))
            conn.commit()
    finally:
        _release_conn(conn)

# Инициализация при импорте (с retry)
init_db()