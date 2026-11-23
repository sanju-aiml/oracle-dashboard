"""Live + historical market data with a fallback chain, and a local store as the last resort.

Quote order (per asset): primary API -> backup APIs -> web backup (robots.txt respected)
-> last stored quote (labeled stale with its age) -> last stored candle close.
A price is never invented: the status field always says fresh / backup / stale / none.
"""
import io
import logging
import math
import os
import re
import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

import pandas as pd
import requests

import config
import store

log = logging.getLogger("oracle.data")
_HEADERS = {"User-Agent": config.USER_AGENT}


# ---------------------------------------------------------------------------
# low-level fetchers (each raises on failure; the chain catches and moves on)
# ---------------------------------------------------------------------------
def _get(url, params=None, headers=None):
    r = requests.get(url, params=params, headers=headers or _HEADERS, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    return r


def q_binance(pair):
    r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": pair},
                     headers=_HEADERS, timeout=2.5)
    r.raise_for_status()
    return float(r.json()["price"])


def q_coingecko(cg_id):
    return float(_get("https://api.coingecko.com/api/v3/simple/price",
                      {"ids": cg_id, "vs_currencies": "usd"}).json()[cg_id]["usd"])


def q_finnhub(symbol):
    p = _get("https://finnhub.io/api/v1/quote", {"symbol": symbol, "token": config.FINNHUB_KEY}).json().get("c")
    if not p:
        raise ValueError("finnhub empty")
    return float(p)


def q_yahoo(ticker):
    import yfinance as yf
    p = yf.Ticker(ticker).fast_info["last_price"]
    if p is None or not math.isfinite(float(p)):
        raise ValueError("yahoo empty")
    return float(p)


def q_stooq(code):
    r = _get("https://stooq.com/q/l/", {"s": code, "f": "c", "h": "", "e": "csv"})
    lines = r.text.strip().splitlines()
    return float(lines[1])


def q_upstox(asset):
    token = os.environ.get("UPSTOX_ACCESS_TOKEN") or os.environ.get("UPSTOX_API_KEY")
    if not token:
        raise ValueError("UPSTOX_ACCESS_TOKEN not configured in environment")
    sym = asset.get("nse") or asset.get("yf", "").replace(".NS", "").replace("^NSEI", "Nifty 50")
    inst_key = f"NSE_INDEX|{sym}" if sym == "Nifty 50" else f"NSE_EQ|{sym}"
    url = f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={inst_key}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json().get("data", {})
    for _, v in data.items():
        if "last_price" in v and _ok(v["last_price"]):
            return float(v["last_price"])
    raise ValueError("price not found in Upstox response")


def q_angel_one(asset):
    import smartapi_client
    return smartapi_client.q_angel_one(asset)


_robots = {}


def _robots_allows(url):
    """Web scraping is only attempted when the site's robots.txt allows it."""
    host = urlparse(url)
    base = f"{host.scheme}://{host.netloc}"
    rp, ts = _robots.get(base, (None, 0))
    if rp is None or time.time() - ts > 86400:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = requests.get(base + "/robots.txt", headers=_HEADERS, timeout=config.HTTP_TIMEOUT)
            rp.parse(resp.text.splitlines() if resp.ok else ["User-agent: *", "Disallow: /"])
        except Exception:
            rp.parse(["User-agent: *", "Disallow: /"])      # cannot verify => do not scrape
        _robots[base] = (rp, time.time())
    return rp.can_fetch(config.USER_AGENT, url)


def q_google_web(gf):
    from bs4 import BeautifulSoup
    url = f"https://www.google.com/finance/quote/{gf}"
    if not _robots_allows(url):
        raise PermissionError("robots.txt disallows scraping this page")
    html = _get(url, headers={"User-Agent": "Mozilla/5.0 " + config.USER_AGENT}).text
    el = BeautifulSoup(html, "html.parser").select_one("div.YMlKec.fxKbKc")
    if not el:
        raise ValueError("page layout changed")
    return float(re.sub(r"[^\d.]", "", el.text))


_nse = {"s": None, "ts": 0}


def _nse_get(path, params=None):
    """NSE website JSON, as its own pages use it. Obeys robots.txt, reuses one cookie session, and is only a
    backup: the site can block automated access or change at any time (then this source is skipped)."""
    base = "https://www.nseindia.com"
    url = base + path
    if not _robots_allows(url):
        raise PermissionError("robots.txt disallows this NSE path")
    if _nse["s"] is None or time.time() - _nse["ts"] > 600:
        s = requests.Session()
        s.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json",
                          "Accept-Language": "en-US,en;q=0.9", "Referer": base + "/"})
        s.get(base + "/", timeout=config.HTTP_TIMEOUT)          # cookies
        _nse["s"], _nse["ts"] = s, time.time()
    r = _nse["s"].get(url, params=params, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def q_nse_equity(symbol):
    return float(_nse_get("/api/quote-equity", {"symbol": symbol})["priceInfo"]["lastPrice"])


def q_nse_index(name):
    for d in _nse_get("/api/allIndices")["data"]:
        if str(d.get("index", "")).upper() == name.upper():
            return float(d["last"])
    raise ValueError("index not found on NSE page")


# ---- candle fetchers: return DataFrame[ts, open, high, low, close, volume] ----
def c_binance(pair, interval, bars):
    out, end = [], None
    while len(out) < bars:
        params = {"symbol": pair, "interval": interval, "limit": min(1000, bars - len(out))}
        if end:
            params["endTime"] = end
        rows = _get("https://api.binance.com/api/v3/klines", params).json()
        if not rows:
            break
        out = rows + out
        end = rows[0][0] - 1
        if len(rows) < 2:
            break
    df = pd.DataFrame(out, columns=["t", "open", "high", "low", "close", "volume", "_a", "_b", "_c", "_d", "_e", "_f"])
    df["ts"] = (df.t // 1000).astype("int64")
    return df[["ts", "open", "high", "low", "close", "volume"]].astype(float)


def c_yahoo(ticker, interval, bars):
    import yfinance as yf
    if interval == "1h":
        period = "730d"
    else:
        period = "1mo" if bars <= 20 else "3mo" if bars <= 60 else "2y" if bars <= 500 else "10y"
    h = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if h is None or len(h) == 0:
        raise ValueError("yahoo empty")
    df = pd.DataFrame({"ts": [int(t.timestamp()) for t in h.index], "open": h["Open"].values,
                       "high": h["High"].values, "low": h["Low"].values, "close": h["Close"].values,
                       "volume": h["Volume"].values})
    return df.tail(bars)


def c_stooq(code, interval, bars):
    if interval != "1d":
        raise ValueError("stooq daily only")
    r = _get("https://stooq.com/q/d/l/", {"s": code, "i": "d"})
    df = pd.read_csv(io.StringIO(r.text))
    if "Close" not in df:
        raise ValueError("stooq empty")
    df["ts"] = pd.to_datetime(df["Date"]).astype("int64") // 10**9
    df = df.rename(columns=str.lower)
    if "volume" not in df:
        df["volume"] = 0.0
    return df[["ts", "open", "high", "low", "close", "volume"]].tail(bars)


# ---------------------------------------------------------------------------
# source chains
# ---------------------------------------------------------------------------
def _quote_sources(asset):
    s = []
    # Angel One SmartAPI is the FIRST live quote source for Indian equities and indices (before Yahoo & NSE web)
    if _is_indian(asset):
        s.append(("Angel One SmartAPI", lambda a=asset: q_angel_one(a)))
        if os.environ.get("UPSTOX_ACCESS_TOKEN") or os.environ.get("UPSTOX_API_KEY"):
            s.append(("Upstox API", lambda a=asset: q_upstox(a)))
    if asset.get("binance"):
        s.append(("Binance", lambda a=asset: q_binance(a["binance"])))
    if asset.get("cg"):
        s.append(("CoinGecko", lambda a=asset: q_coingecko(a["cg"])))
    if config.FINNHUB_KEY and asset.get("fh"):
        s.append(("Finnhub", lambda a=asset: q_finnhub(a["fh"])))
    if asset.get("yf"):
        s.append(("Yahoo Finance", lambda a=asset: q_yahoo(a["yf"])))
    if asset.get("stooq"):
        s.append(("Stooq", lambda a=asset: q_stooq(a["stooq"])))
    if config.ALLOW_SCRAPING and asset.get("nse"):
        s.append(("NSE website (web)", lambda a=asset: q_nse_equity(a["nse"])))
    if config.ALLOW_SCRAPING and asset.get("nse_index"):
        s.append(("NSE website (web)", lambda a=asset: q_nse_index(a["nse_index"])))
    if config.ALLOW_SCRAPING and asset.get("gf"):
        s.append(("Google Finance (web)", lambda a=asset: q_google_web(a["gf"])))
    return s


def _candle_sources(asset, interval):
    s = []
    if asset.get("binance"):
        s.append(("Binance", lambda bars, a=asset: c_binance(a["binance"], interval, bars)))
    if asset.get("yf"):
        s.append(("Yahoo Finance", lambda bars, a=asset: c_yahoo(a["yf"], interval, bars)))
    if asset.get("stooq") and interval == "1d":
        s.append(("Stooq", lambda bars, a=asset: c_stooq(a["stooq"], interval, bars)))
    return s


def _ok(p):
    try:
        return math.isfinite(float(p)) and float(p) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def _is_indian(asset):
    y = asset.get("yf", "")
    return y.endswith((".NS", ".BO")) or y in ("^NSEI", "^BSESN", "^INDIAVIX")


def market_state(symbol, now=None):
    """'open' or 'closed' by normal trading hours. Exchange holidays are not tracked."""
    from datetime import datetime, time as dtime, timezone
    from zoneinfo import ZoneInfo
    a = config.ASSETS.get(symbol)
    if not a:
        return "closed"
    now = now or datetime.now(timezone.utc)
    if a["cls"] == "crypto":
        return "open"
    if _is_indian(a):
        t = now.astimezone(ZoneInfo("Asia/Kolkata"))
        return "open" if t.weekday() < 5 and dtime(9, 15) <= t.time() <= dtime(15, 30) else "closed"
    et = now.astimezone(ZoneInfo("America/New_York"))
    if a["cls"] == "stock":
        return "open" if et.weekday() < 5 and dtime(9, 30) <= et.time() <= dtime(16, 0) else "closed"
    # futures / forex: ~24h, Sun 18:00 ET to Fri 17:00 ET, daily break 17:00-18:00 ET
    wd, tm = et.weekday(), et.time()
    if wd == 5 or (wd == 6 and tm < dtime(18, 0)) or (wd == 4 and tm >= dtime(17, 0)):
        return "closed"
    return "closed" if dtime(17, 0) <= tm < dtime(18, 0) else "open"


def get_quote(symbol, max_fresh=None):
    """Best available price + market state. Never raises, never fabricates."""
    q = _get_quote(symbol, max_fresh)
    q["market"] = market_state(symbol)
    if q["market"] == "closed" and q["status"] in ("fresh", "backup"):
        q["note"] = "Market is closed; this is the last traded price"
    return q


def _get_quote(symbol, max_fresh=None):
    asset = config.ASSETS.get(symbol)
    if not asset:
        return {"symbol": symbol, "price": None, "source": None, "ts": None, "age_sec": None,
                "status": "none", "warning": f"Asset {symbol} not configured"}
    max_fresh = config.QUOTE_FRESH_SEC if max_fresh is None else max_fresh
    now = time.time()
    cached = store.latest_quote(symbol)
    if cached and now - cached["ts"] < max_fresh:
        return {"symbol": symbol, "price": cached["price"], "source": cached["source"], "ts": cached["ts"],
                "age_sec": int(now - cached["ts"]), "status": "fresh", "warning": None}

    last_known = (cached or {}).get("price")
    if last_known is None:
        c = store.load_candles(symbol, "1d", limit=1)
        last_known = float(c.close.iloc[-1]) if len(c) else None

    sources = _quote_sources(asset)
    got = []
    for idx, (name, fn) in enumerate(sources):
        try:
            p = float(fn())
            if not _ok(p):
                raise ValueError("bad price")
            if last_known and abs(p / last_known - 1) > config.SUSPICIOUS_JUMP:
                raise ValueError(f"suspicious jump vs last known {last_known}")
            got.append((idx, name, p))
            if len(got) == 2:
                break
        except Exception as e:
            log.info("quote source %s failed for %s: %s", name, symbol, e)

    if got:
        idx, name, price = got[0]
        warning = None
        if len(got) == 2 and abs(got[0][2] - got[1][2]) / got[0][2] > config.SOURCE_DISAGREE:
            warning = f"{got[0][1]} and {got[1][1]} differ by more than 2%; verify before acting"
        store.save_quote(symbol, price, name)
        return {"symbol": symbol, "price": price, "source": name, "ts": int(now), "age_sec": 0,
                "status": "fresh" if idx == 0 else "backup", "warning": warning}

    if cached:
        return {"symbol": symbol, "price": cached["price"], "source": cached["source"], "ts": cached["ts"],
                "age_sec": int(now - cached["ts"]), "status": "stale",
                "warning": "Live sources could not be reached; showing the last stored price"}
    c = store.load_candles(symbol, "1d", limit=1)
    if len(c):
        return {"symbol": symbol, "price": float(c.close.iloc[-1]), "source": "stored daily candle",
                "ts": int(c.ts.iloc[-1]), "age_sec": int(now - c.ts.iloc[-1]), "status": "stale",
                "warning": "Live sources could not be reached; showing the last stored close"}
    return {"symbol": symbol, "price": None, "source": None, "ts": None, "age_sec": None,
            "status": "none", "warning": "No stored data yet. Run seed_history.py once while online."}


def refresh_candles(symbol, interval="1d", bars=60):
    """Fetch recent candles from the first working source and store them. Returns (rows, source)."""
    asset = config.ASSETS[symbol]
    for name, fn in _candle_sources(asset, interval):
        try:
            df = fn(bars)
            n = store.upsert_candles(df, symbol, interval, name)
            if n:
                return n, name
        except Exception as e:
            log.info("candle source %s failed for %s: %s", name, symbol, e)
    return 0, None


def seed_history(symbol, interval="1d", bars=2000):
    return refresh_candles(symbol, interval, bars)


# ---------------------------------------------------------------------------
# dynamic assets: any Yahoo ticker a user asks about is registered and stored
# ---------------------------------------------------------------------------
_dyn_lock = threading.Lock()


def register_dynamic(ticker):
    """Add an unknown ticker if Yahoo knows it. Returns the symbol key or None."""
    t = ticker.upper()
    if t in config.ASSETS:
        return t
    with _dyn_lock:
        dyn = [s for s, a in config.ASSETS.items() if a.get("dynamic")]
        if len(dyn) >= config.MAX_DYNAMIC_ASSETS:
            return None
        try:
            q_yahoo(t)
        except Exception:
            return None
        extra = {"nse": t[:-3]} if t.endswith(".NS") else {}
        cls = "index" if t.startswith("^") else "crypto" if t.endswith("-USD") else "forex" if t.endswith("=X") \
            else "commodity" if t.endswith("=F") else "stock"
        config.ASSETS[t] = dict(name=t, cls=cls, aliases=[t.lower()], yf=t, dynamic=True, **extra)
        return t


def normalize_symbol(raw):
    """Turn UI spellings into an ORACLE key: BTC/USD, BTCUSD, BTC-USD, BTCUSDT -> BTC; 'NIFTY 50' -> NIFTY."""
    s = (raw or "").upper().strip().replace("%2F", "/")
    if s in config.ASSETS:
        return s
    flat = re.sub(r"[\s_]+", "", s)
    for sym, a in config.ASSETS.items():
        names = {sym, a.get("name", "").upper().replace(" ", "")} | {x.upper().replace(" ", "") for x in a.get("aliases", [])}
        if flat in names:
            return sym
    m = re.fullmatch(r"([A-Z0-9]{2,10})[/\-]?(USDT|USD|INR)", flat)
    if m and m.group(1) in config.ASSETS:
        return m.group(1)
    return s
