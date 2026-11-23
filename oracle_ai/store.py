"""SQLite store: candles, quotes, predictions, paper account. This is ORACLE's own data,
so answers keep working (clearly labeled stale) even when every live source is down."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

import pandas as pd

import config

_lock = threading.RLock()
_inited = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles(
  symbol TEXT, interval TEXT, ts INTEGER, open REAL, high REAL, low REAL, close REAL,
  volume REAL, source TEXT, PRIMARY KEY(symbol, interval, ts));
CREATE TABLE IF NOT EXISTS quotes(
  symbol TEXT, ts INTEGER, price REAL, source TEXT, PRIMARY KEY(symbol, ts));
CREATE TABLE IF NOT EXISTS predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT, user_id TEXT, symbol TEXT, interval TEXT,
  horizon INTEGER, duration_sec INTEGER, made_at INTEGER, candle_ts INTEGER, entry_price REAL,
  p_up REAL, call TEXT, resolve_after INTEGER, resolved INTEGER DEFAULT 0, exit_price REAL,
  outcome TEXT, pnl_pct REAL, image_path TEXT, raster_path TEXT, consent INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS paper_account(
  id INTEGER PRIMARY KEY CHECK(id=1), cash REAL, equity_peak REAL, halted INTEGER DEFAULT 0,
  halt_reason TEXT, updated_at INTEGER);
CREATE TABLE IF NOT EXISTS paper_positions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT, qty REAL, entry_price REAL,
  stop REAL, target REAL, opened_at INTEGER, expire_at INTEGER, status TEXT DEFAULT 'open',
  exit_price REAL, closed_at INTEGER, pnl REAL, reason TEXT, fees REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS model_meta(
  symbol TEXT, interval TEXT, horizon INTEGER, trained_at INTEGER, passed INTEGER, report TEXT,
  PRIMARY KEY(symbol, interval, horizon));
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS watch_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, symbol TEXT, kind TEXT, threshold REAL,
  cooldown_sec INTEGER DEFAULT 21600, active INTEGER DEFAULT 1, last_fired INTEGER DEFAULT 0, created_at INTEGER);
CREATE TABLE IF NOT EXISTS holdings(
  user_id TEXT, symbol TEXT, qty REAL, avg_price REAL, stop_pct REAL DEFAULT 8, target_pct REAL DEFAULT 15,
  PRIMARY KEY(user_id, symbol));
CREATE TABLE IF NOT EXISTS alerts_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, ts INTEGER, symbol TEXT, kind TEXT, title TEXT,
  body TEXT, delivered TEXT);
CREATE TABLE IF NOT EXISTS user_channels(user_id TEXT PRIMARY KEY, ntfy_topic TEXT, telegram_chat_id TEXT);
CREATE TABLE IF NOT EXISTS ipos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, open_date TEXT, close_date TEXT, price_band TEXT,
  lot_size TEXT, notes TEXT);
"""


def _connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db():
    with _lock:
        conn = _connect()
        try:
            if config.DB_PATH not in _inited:
                conn.executescript(SCHEMA)
                _inited.add(config.DB_PATH)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ---- candles ---------------------------------------------------------------
def upsert_candles(df, symbol, interval, source):
    """df columns: ts (epoch seconds), open, high, low, close, volume. Invalid rows are dropped."""
    if df is None or len(df) == 0:
        return 0
    d = df.copy()
    for c in ("open", "high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    if "volume" not in d:
        d["volume"] = 0.0
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["ts", "open", "high", "low", "close"])
    d = d[(d.open > 0) & (d.high > 0) & (d.low > 0) & (d.close > 0)]
    d = d[d.high >= d.low]
    d = d.drop_duplicates("ts")
    rows = [(symbol, interval, int(r.ts), float(r.open), float(r.high), float(r.low),
             float(r.close), float(r.volume), source) for r in d.itertuples(index=False)]
    if not rows:
        return 0
    with db() as c:
        c.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_candles(symbol, interval="1d", limit=None):
    q = "SELECT ts,open,high,low,close,volume FROM candles WHERE symbol=? AND interval=? ORDER BY ts"
    with db() as c:
        rows = c.execute(q, (symbol, interval)).fetchall()
    df = pd.DataFrame([tuple(r) for r in rows], columns=["ts", "open", "high", "low", "close", "volume"])
    if limit:
        df = df.tail(limit).reset_index(drop=True)
    return df


def last_candle_ts(symbol, interval="1d"):
    with db() as c:
        r = c.execute("SELECT MAX(ts) m FROM candles WHERE symbol=? AND interval=?", (symbol, interval)).fetchone()
    return r["m"]


def closed_only(df, interval="1d", now=None):
    """Drop the newest candle if it is still forming (its period has not ended)."""
    if df is None or len(df) == 0:
        return df
    now = now or time.time()
    if now < df.ts.iloc[-1] + config.INTERVAL_SEC[interval]:
        return df.iloc[:-1].reset_index(drop=True)
    return df


# ---- quotes ----------------------------------------------------------------
def save_quote(symbol, price, source, ts=None):
    ts = int(ts or time.time())
    with db() as c:
        c.execute("INSERT OR REPLACE INTO quotes VALUES (?,?,?,?)", (symbol, ts, float(price), source))


def latest_quote(symbol):
    with db() as c:
        r = c.execute("SELECT ts,price,source FROM quotes WHERE symbol=? ORDER BY ts DESC LIMIT 1", (symbol,)).fetchone()
    return dict(r) if r else None


# ---- key/value -------------------------------------------------------------
def kv_get(k, default=None):
    with db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def kv_set(k, v):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))


# ---- model metadata ----------------------------------------------------------
def save_model_meta(symbol, interval, horizon, passed, report):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO model_meta VALUES (?,?,?,?,?,?)",
                  (symbol, interval, horizon, int(time.time()), int(bool(passed)), json.dumps(report)))


def load_model_meta(symbol, interval, horizon):
    with db() as c:
        r = c.execute("SELECT * FROM model_meta WHERE symbol=? AND interval=? AND horizon=?",
                      (symbol, interval, horizon)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["report"] = json.loads(d["report"])
    return d


# ---- predictions -----------------------------------------------------------
def add_prediction(**kw):
    cols = ["origin", "user_id", "symbol", "interval", "horizon", "duration_sec", "made_at",
            "candle_ts", "entry_price", "p_up", "call", "resolve_after", "image_path",
            "raster_path", "consent"]
    vals = [kw.get(c) for c in cols]
    with db() as c:
        cur = c.execute(f"INSERT INTO predictions({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        return cur.lastrowid


def open_predictions():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM predictions WHERE resolved=0").fetchall()]


def resolve_prediction(pid, exit_price, outcome, pnl_pct):
    with db() as c:
        c.execute("UPDATE predictions SET resolved=1, exit_price=?, outcome=?, pnl_pct=? WHERE id=?",
                  (exit_price, outcome, pnl_pct, pid))


def prediction_stats(origin=None, user_id=None, symbol=None):
    q = "SELECT outcome, COUNT(*) n, AVG(pnl_pct) avg_pnl FROM predictions WHERE resolved=1 AND outcome IN ('win','loss')"
    args = []
    for col, val in (("origin", origin), ("user_id", user_id), ("symbol", symbol)):
        if val:
            q += f" AND {col}=?"
            args.append(val)
    q += " GROUP BY outcome"
    with db() as c:
        rows = {r["outcome"]: dict(r) for r in c.execute(q, args).fetchall()}
    wins = rows.get("win", {}).get("n", 0)
    losses = rows.get("loss", {}).get("n", 0)
    total = wins + losses
    return {"wins": wins, "losses": losses, "total": total,
            "win_rate": (wins / total) if total else None}


def user_history(user_id, limit=50):
    with db() as c:
        rows = c.execute("SELECT id,symbol,call,duration_sec,made_at,entry_price,exit_price,outcome,pnl_pct,resolved "
                         "FROM predictions WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    return [dict(r) for r in rows]
