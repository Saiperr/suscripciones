import os, sqlite3, threading, datetime as dt
from contextlib import closing
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DB = os.environ.get("DB_PATH", "/data/app.db")
_lock = threading.RLock()


def today():
    return dt.datetime.now(TZ).date()


def now():
    return dt.datetime.now(TZ).replace(tzinfo=None)


def conn():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def q(sql, args=()):
    with _lock, closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def ex(sql, args=()):
    """Ejecuta y confirma. Devuelve (lastrowid, filas afectadas)."""
    with _lock, closing(conn()) as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid, cur.rowcount


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with _lock, closing(conn()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '', base_currency TEXT NOT NULL DEFAULT 'EUR',
            alerts_on INTEGER NOT NULL DEFAULT 1, alert_days INTEGER NOT NULL DEFAULT 3,
            ics_token TEXT NOT NULL, created TEXT);
        CREATE TABLE IF NOT EXISTS subs(
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
            amount_cents INTEGER NOT NULL, currency TEXT NOT NULL,
            period_n INTEGER NOT NULL, period_unit TEXT NOT NULL,
            start_date TEXT NOT NULL, trial_end TEXT, payment_method TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', cancel_url TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'activa', created TEXT);
        CREATE INDEX IF NOT EXISTS subs_user ON subs(user_id);
        CREATE TABLE IF NOT EXISTS price_history(
            id INTEGER PRIMARY KEY, sub_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            amount_cents INTEGER NOT NULL, currency TEXT NOT NULL, changed_on TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rates(cur TEXT PRIMARY KEY, rate TEXT NOT NULL, fetched TEXT NOT NULL, rate_date TEXT);
        CREATE TABLE IF NOT EXISTS sent_alerts(
            sub_id INTEGER NOT NULL, ref_date TEXT NOT NULL, kind TEXT NOT NULL, sent TEXT,
            PRIMARY KEY(sub_id, ref_date, kind));
        """)
        c.commit()
