# db.py — SQLite с поддержкой флагов, кеша, очереди задач и платежей
import sqlite3
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from config import DB_PATH

_lock = threading.Lock()
ALLOWED_USER_PREFS = {'font_style': 'font_style'}

def _conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT,
            font_style TEXT DEFAULT 'cursive',
            flags TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan TEXT DEFAULT 'trial',
            start_date TEXT,
            end_date TEXT,
            active INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_type TEXT,
            payload TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service_type TEXT,
            plan TEXT,
            service_name TEXT,
            amount_rub INTEGER,
            amount_stars INTEGER,
            status TEXT DEFAULT 'pending',
            screenshot_file_id TEXT,
            created_at TEXT,
            confirmed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status);
        CREATE INDEX IF NOT EXISTS idx_task_queue_created ON task_queue(created_at);
        CREATE INDEX IF NOT EXISTS idx_usage_log_user_date ON usage_log(user_id, date);
        CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
        CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
        """)
        cur = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cur.fetchall()]
        if 'flags' not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN flags TEXT DEFAULT '{}'")
        conn.commit()

def ensure_user(user_id: int, username: str = None, first_name: str = None):
    with _lock, _conn() as conn:
        cur = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if not cur.fetchone():
            conn.execute(
                "INSERT INTO users (user_id, username, first_name, created_at, font_style, flags) VALUES (?,?,?,?,?,?)",
                (user_id, username, first_name, datetime.now().isoformat(), 'cursive', '{}')
            )
            end = datetime.now() + timedelta(days=7)
            conn.execute(
                "INSERT INTO subscriptions (user_id, plan, start_date, end_date, active) VALUES (?,?,?,?,1)",
                (user_id, 'trial', datetime.now().isoformat(), end.isoformat())
            )
            conn.commit()

def get_user_prefs(user_id: int) -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT font_style FROM users WHERE user_id=?", (user_id,)).fetchone()
        return {'font_style': row['font_style'] if row else 'cursive'}

def set_user_pref(user_id: int, key: str, value: str):
    if key not in ALLOWED_USER_PREFS:
        raise ValueError(f"Недопустимый ключ: {key}")
    real_column = ALLOWED_USER_PREFS[key]
    with _lock, _conn() as conn:
        conn.execute(f"UPDATE users SET {real_column}=? WHERE user_id=?", (value, user_id))
        conn.commit()

def get_user_flag(user_id: int, flag: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT flags FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and row['flags']:
            try:
                flags = json.loads(row['flags'])
                return flags.get(flag, False)
            except:
                return False
        return False

def set_user_flag(user_id: int, flag: str, value: bool):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT flags FROM users WHERE user_id=?", (user_id,)).fetchone()
        flags = {}
        if row and row['flags']:
            try:
                flags = json.loads(row['flags'])
            except:
                pass
        flags[flag] = value
        conn.execute("UPDATE users SET flags=? WHERE user_id=?", (json.dumps(flags), user_id))
        conn.commit()

def get_subscription(user_id: int) -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT plan, start_date, end_date, active FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {'plan': 'trial', 'start_date': datetime.now().isoformat(),
                    'end_date': (datetime.now() + timedelta(days=7)).isoformat(), 'active': True}
        sub = dict(row)
        if sub.get('active'):
            end = datetime.fromisoformat(sub['end_date'])
            if datetime.now() > end:
                sub['active'] = False
                conn.execute("UPDATE subscriptions SET active=0 WHERE user_id=?", (user_id,))
                conn.commit()
        return sub

def set_subscription(user_id: int, plan: str, days: int):
    with _lock, _conn() as conn:
        start = datetime.now()
        end = start + timedelta(days=days)
        conn.execute(
            """INSERT INTO subscriptions (user_id, plan, start_date, end_date, active)
               VALUES (?,?,?,?,1)
               ON CONFLICT(user_id) DO UPDATE SET
               plan=excluded.plan, start_date=excluded.start_date,
               end_date=excluded.end_date, active=1""",
            (user_id, plan, start.isoformat(), end.isoformat())
        )
        conn.commit()

def check_limit(user_id: int, action: str, max_val: int) -> bool:
    if max_val == 99999:
        return True
    today = datetime.now().strftime('%Y-%m-%d')
    with _lock, _conn() as conn:
        row = conn.execute("SELECT count FROM usage_log WHERE user_id=? AND action=? AND date=?", (user_id, action, today)).fetchone()
        used = row['count'] if row else 0
        return used < max_val

def use_limit(user_id: int, action: str):
    today = datetime.now().strftime('%Y-%m-%d')
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO usage_log (user_id, action, date, count) VALUES (?,?,?,1)
               ON CONFLICT(user_id, action, date) DO UPDATE SET count = count + 1""",
            (user_id, action, today)
        )
        conn.commit()

def get_usage(user_id: int) -> dict:
    today = datetime.now().strftime('%Y-%m-%d')
    with _conn() as conn:
        rows = conn.execute("SELECT action, count FROM usage_log WHERE user_id=? AND date=?", (user_id, today)).fetchall()
        return {r['action']: r['count'] for r in rows}

def get_cached_transcription(url_hash: str) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT text FROM transcription_cache WHERE url_hash=?", (url_hash,)).fetchone()
        return row['text'] if row else None

def set_cached_transcription(url_hash: str, url: str, text: str):
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO transcription_cache (url_hash, url, text, created_at) VALUES (?,?,?,?)",
            (url_hash, url, text, datetime.now().isoformat())
        )
        conn.commit()

def add_task(user_id: int, task_type: str, payload: dict) -> int:
    with _lock, _conn() as conn:
        cur = conn.execute(
            "INSERT INTO task_queue (user_id, task_type, payload, status, created_at) VALUES (?,?,?,?,?)",
            (user_id, task_type, json.dumps(payload, ensure_ascii=False), 'pending', datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid

def get_pending_task():
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()
        return dict(row) if row else None

def update_task_status(task_id: int, status: str):
    with _lock, _conn() as conn:
        now = datetime.now().isoformat()
        if status == 'running':
            conn.execute("UPDATE task_queue SET status=?, started_at=? WHERE id=?", (status, now, task_id))
        elif status == 'done':
            conn.execute("UPDATE task_queue SET status=?, completed_at=? WHERE id=?", (status, now, task_id))
        else:
            conn.execute("UPDATE task_queue SET status=? WHERE id=?", (status, task_id))
        conn.commit()

def get_task_status(task_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT id, user_id, status FROM task_queue WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

def reset_running_tasks():
    with _lock, _conn() as conn:
        conn.execute("UPDATE task_queue SET status='pending' WHERE status='running'")
        conn.commit()

# ---- Платежи ----
def add_payment(user_id: int, service_type: str, plan: str = None, service_name: str = None,
                amount_rub: int = 0, amount_stars: int = 0, screenshot_file_id: str = None) -> int:
    with _lock, _conn() as conn:
        cur = conn.execute(
            """INSERT INTO payments
               (user_id, service_type, plan, service_name, amount_rub, amount_stars, screenshot_file_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, service_type, plan, service_name, amount_rub, amount_stars, screenshot_file_id, datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid

def get_pending_payments() -> list:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT p.*, u.username, u.first_name
               FROM payments p
               JOIN users u ON p.user_id = u.user_id
               WHERE p.status = 'pending'
               ORDER BY p.created_at ASC"""
        ).fetchall()
        return [dict(row) for row in rows]

def confirm_payment(payment_id: int) -> bool:
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id=? AND status='pending'", (payment_id,)).fetchone()
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
        conn.execute("UPDATE payments SET status='confirmed', confirmed_at=? WHERE id=?", (datetime.now().isoformat(), payment_id))
        conn.commit()
        return True

def reject_payment(payment_id: int) -> bool:
    with _lock, _conn() as conn:
        row = conn.execute("SELECT status FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row or row['status'] != 'pending':
            return False
        conn.execute("UPDATE payments SET status='rejected' WHERE id=?", (payment_id,))
        conn.commit()
        return True

def get_payments_for_user(user_id: int, limit: int = 10) -> list:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(row) for row in rows]

# ---- Очистка старых записей ----
def cleanup_old_records(days: int = 30):
    """Удаляет записи старше указанного количества дней из логов, кеша и выполненных задач."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with _lock, _conn() as conn:
        # Удаляем старые usage_log
        conn.execute("DELETE FROM usage_log WHERE date < ?", (cutoff[:10],))  # date в формате YYYY-MM-DD
        # Удаляем старые транскрипции
        conn.execute("DELETE FROM transcription_cache WHERE created_at < ?", (cutoff,))
        # Удаляем завершённые задачи (статус done или error), старше дней
        conn.execute("DELETE FROM task_queue WHERE status IN ('done', 'error', 'cancelled') AND completed_at < ?", (cutoff,))
        conn.commit()

init_db()