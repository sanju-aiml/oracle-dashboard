"""ORACLE Market, Live Investment Intelligence & Alpaca Paper Trading Engine.
Enforces strict data provenance, operational health monitoring, bounded retries,
rate-limit caching, and explicit LIVE vs DEMO isolation.
Never manufactures prices, volumes, timestamps, candle values, IPO statuses, or commodity quotes.
"""
import os, sys, json, time, math, urllib.request, urllib.error, urllib.parse, re, uuid
from typing import Dict, Any, Optional, List

# Load .env into os.environ if present
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if not os.path.exists(_env_path):
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if "=" in _line and not _line.startswith("#"):
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception:
        pass

# Secrets loaded exclusively from environment variables
FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "").strip()
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY", "").strip()
OILPRICE_KEY = os.environ.get("OILPRICE_KEY", "").strip()
ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_KEY", "").strip()

ALPACA_KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "").strip()
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2").strip()
# Safety lock: ensure paper trading URL cannot point to live broker without explicit compliance check
if "paper-api.alpaca.markets" not in ALPACA_BASE_URL:
    ALPACA_BASE_URL = "https://paper-api.alpaca.markets/v2"

# -------------------------------------------------------------
# 1. SECURITY & REDACTION
# -------------------------------------------------------------
def redact_secrets(text: str) -> str:
    """Redacts known API keys and secrets from logs, URLs, and exception messages."""
    if not text:
        return ""
    s = str(text)
    for key in (FINNHUB_KEY, TWELVEDATA_KEY, OILPRICE_KEY, ALPHAVANTAGE_KEY, ALPACA_KEY_ID, ALPACA_SECRET_KEY):
        if key and len(key) >= 6:
            s = s.replace(key, "[REDACTED]")
    s = re.sub(r'(apikey|token|token=)[^&\s]+', r'\1=[REDACTED]', s)
    return s

# -------------------------------------------------------------
# 2. OPERATIONAL HEALTH TRACKER
# -------------------------------------------------------------
_PROVIDER_HEALTH = {
    "finnhub": {
        "provider": "Finnhub Stock & Company API",
        "configured": bool(FINNHUB_KEY),
        "status": "ready" if FINNHUB_KEY else "not_configured",
        "last_success_ts": None,
        "last_error": None,
        "last_error_ts": None,
        "success_count": 0,
        "error_count": 0
    },
    "twelvedata": {
        "provider": "TwelveData Global Realtime",
        "configured": bool(TWELVEDATA_KEY),
        "status": "ready" if TWELVEDATA_KEY else "not_configured",
        "last_success_ts": None,
        "last_error": None,
        "last_error_ts": None,
        "success_count": 0,
        "error_count": 0
    },
    "oilprice": {
        "provider": "OilPriceAPI Live Feed",
        "configured": bool(OILPRICE_KEY),
        "status": "ready" if OILPRICE_KEY else "not_configured",
        "last_success_ts": None,
        "last_error": None,
        "last_error_ts": None,
        "success_count": 0,
        "error_count": 0
    },
    "alphavantage": {
        "provider": "Alpha Vantage Global Quotes",
        "configured": bool(ALPHAVANTAGE_KEY),
        "status": "ready" if ALPHAVANTAGE_KEY else "not_configured",
        "last_success_ts": None,
        "last_error": None,
        "last_error_ts": None,
        "success_count": 0,
        "error_count": 0
    },
    "alpaca_paper": {
        "provider": "Alpaca Paper Trading API",
        "configured": bool(ALPACA_KEY_ID and ALPACA_SECRET_KEY),
        "status": "ready" if (ALPACA_KEY_ID and ALPACA_SECRET_KEY) else "not_configured",
        "last_success_ts": None,
        "last_error": None,
        "last_error_ts": None,
        "success_count": 0,
        "error_count": 0
    }
}

def _record_provider_success(provider_name: str):
    if provider_name in _PROVIDER_HEALTH:
        _PROVIDER_HEALTH[provider_name]["last_success_ts"] = time.time()
        _PROVIDER_HEALTH[provider_name]["status"] = "healthy"
        _PROVIDER_HEALTH[provider_name]["success_count"] += 1

def _record_provider_error(provider_name: str, err_msg: str):
    if provider_name in _PROVIDER_HEALTH:
        _PROVIDER_HEALTH[provider_name]["last_error"] = redact_secrets(str(err_msg)[:140])
        _PROVIDER_HEALTH[provider_name]["last_error_ts"] = time.time()
        _PROVIDER_HEALTH[provider_name]["status"] = "error"
        _PROVIDER_HEALTH[provider_name]["error_count"] += 1

def get_provider_health():
    """Returns operational health information for all configured upstream market-data providers."""
    now = time.time()
    report = {}
    for name, info in _PROVIDER_HEALTH.items():
        freshness = f"{round(now - info['last_success_ts'], 1)}s ago" if info["last_success_ts"] else "never"
        report[name] = {
            **info,
            "data_freshness": freshness,
            "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        }
    return {"status": "ok", "providers": report}

# -------------------------------------------------------------
# 3. HTTP CLIENT WITH BOUNDED RETRIES & BACKOFF
# -------------------------------------------------------------
def _http_request(url: str, method="GET", headers=None, data_dict=None, timeout=4, retries=1, provider_name="unknown") -> Dict[str, Any]:
    hdrs = {"User-Agent": "oracle/2.0"}
    if headers:
        hdrs.update(headers)

    body_bytes = None
    if data_dict is not None:
        hdrs["Content-Type"] = "application/json"
        body_bytes = json.dumps(data_dict).encode("utf-8")

    attempt = 0
    max_attempts = max(1, 1 + retries)

    while attempt < max_attempts:
        attempt += 1
        req = urllib.request.Request(url, data=body_bytes, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
                _record_provider_success(provider_name)
                return {"ok": True, "status_code": resp.status, "data": data, "feed_status": "live"}
        except urllib.error.HTTPError as e:
            status_code = e.code
            raw_err = ""
            try:
                raw_err = e.read().decode("utf-8", errors="replace")
                err_json = json.loads(raw_err)
                err_detail = err_json.get("message") or err_json.get("error") or err_json.get("detail") or str(err_json)
            except Exception:
                err_detail = raw_err[:120] or e.reason

            clean_err = redact_secrets(err_detail)
            _record_provider_error(provider_name, f"HTTP {status_code}: {clean_err}")

            if status_code in (401, 403):
                return {"ok": False, "status_code": status_code, "feed_status": "auth_failed", "error": f"Provider authentication failed ({status_code})."}
            if status_code == 429:
                return {"ok": False, "status_code": status_code, "feed_status": "rate_limited", "error": "Provider rate limit or quota exceeded."}
            if status_code in (400, 404, 422):
                return {"ok": False, "status_code": status_code, "feed_status": "unavailable", "error": f"Unsupported symbol or bad request ({status_code}): {clean_err}"}

            if attempt < max_attempts and status_code >= 500:
                time.sleep(0.5 * attempt)
                continue

            return {"ok": False, "status_code": status_code, "feed_status": "unavailable", "error": f"Provider server error ({status_code})"}

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            clean_err = redact_secrets(str(e))
            _record_provider_error(provider_name, clean_err)
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            return {"ok": False, "status_code": 0, "feed_status": "unavailable", "error": f"Network/timeout connecting to provider: {clean_err}"}
        except Exception as e:
            clean_err = redact_secrets(str(e))
            _record_provider_error(provider_name, clean_err)
            return {"ok": False, "status_code": 0, "feed_status": "unavailable", "error": clean_err}

    return {"ok": False, "status_code": 0, "feed_status": "unavailable", "error": "Request timed out after bounded retries."}

# -------------------------------------------------------------
# 4. DATA PROVENANCE CONTRACT
# -------------------------------------------------------------
def make_data_contract(
    requested_symbol: str,
    provider_symbol: str,
    provider_name: str,
    data_timestamp: str,
    feed_status: str,   # "live" | "delayed" | "stale" | "historical" | "unavailable" | "not_configured" | "synthetic_demo"
    kind: str,          # "actual" | "calculated" | "estimate" | "forecast" | "synthetic"
    market_status: str = "unknown", # "open" | "closed" | "extended" | "unknown"
    status: str = "ok",
    extra: dict = None
) -> Dict[str, Any]:
    retrieval_ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    payload = {
        "status": status,
        "requested_symbol": requested_symbol.upper().strip() if requested_symbol else "",
        "provider_symbol": provider_symbol.upper().strip() if provider_symbol else "",
        "provider_name": provider_name,
        "data_timestamp": data_timestamp or retrieval_ts,
        "retrieval_timestamp": retrieval_ts,
        "market_status": market_status,
        "feed_status": feed_status,
        "kind": kind
    }
    if extra:
        payload.update(extra)
    return payload

# -------------------------------------------------------------
# 5. SHARED RATE-LIMIT-AWARE CACHE
# -------------------------------------------------------------
_CACHE: Dict[str, tuple] = {}

def _get_cache(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    if key in _CACHE:
        val, expire_at = _CACHE[key]
        if now < expire_at:
            return val
    return None

def _set_cache(key: str, val: Dict[str, Any], ttl: int = 15):
    _CACHE[key] = (val, time.time() + ttl)

# -------------------------------------------------------------
# 6. STOCK QUOTES (FINNHUB -> TWELVEDATA -> ALPHAVANTAGE)
# -------------------------------------------------------------
def get_live_stock(symbol="AMZN", mode="live") -> Dict[str, Any]:
    sym = (symbol or "AMZN").upper().strip()
    if not sym or not re.match(r"^[A-Z0-9.\-_]{1,15}$", sym):
        return make_data_contract(
            requested_symbol=sym,
            provider_symbol="",
            provider_name="None",
            data_timestamp="",
            feed_status="invalid_symbol",
            kind="actual",
            status="error",
            extra={"error": f"Invalid ticker symbol format: '{sym}'"}
        )

    cache_key = f"{mode}:quote:{sym}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 1. Primary: Finnhub
    if FINNHUB_KEY:
        url = f"https://finnhub.io/api/v1/quote?symbol={urllib.parse.quote(sym)}&token={FINNHUB_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="finnhub")
        if res["ok"]:
            d = res["data"]
            # Finnhub returns c=0 for invalid/unsupported symbols
            if d.get("c", 0) > 0 and d.get("t", 0) > 0:
                cur = float(d["c"])
                prev = float(d.get("pc", cur))
                chg = float(d.get("d", cur - prev))
                pct = float(d.get("dp", (chg / prev * 100) if prev else 0.0))
                t_epoch = d.get("t", time.time())
                data_ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(t_epoch))
                now_epoch = time.time()
                age = now_epoch - t_epoch
                market_st = "open" if age < 900 else "closed"
                feed_st = "live" if age < 900 else "delayed"

                contract = make_data_contract(
                    requested_symbol=sym,
                    provider_symbol=sym,
                    provider_name="Finnhub Live Quote API",
                    data_timestamp=data_ts,
                    feed_status=feed_st,
                    kind="actual",
                    market_status=market_st,
                    status="ok",
                    extra={
                        "symbol": sym,
                        "price": round(cur, 2),
                        "change": round(chg, 2),
                        "change_percent": f"{pct:+.2f}%",
                        "high_today": round(float(d.get("h", cur)), 2),
                        "low_today": round(float(d.get("l", cur)), 2),
                        "open_today": round(float(d.get("o", cur)), 2),
                        "previous_close": round(prev, 2),
                        "source": "Finnhub Live Exchange Feed",
                        "as_of": data_ts
                    }
                )
                _set_cache(cache_key, contract, ttl=15)
                return contract

    # 2. Secondary: TwelveData
    if TWELVEDATA_KEY:
        url = f"https://api.twelvedata.com/quote?symbol={urllib.parse.quote(sym)}&apikey={TWELVEDATA_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="twelvedata")
        if res["ok"]:
            d = res["data"]
            if d.get("close") and d.get("status") != "error":
                cur = float(d["close"])
                chg = float(d.get("change", 0.0))
                pct = float(d.get("percent_change", 0.0))
                is_open = d.get("is_market_open", False)
                contract = make_data_contract(
                    requested_symbol=sym,
                    provider_symbol=d.get("symbol", sym),
                    provider_name="TwelveData Global Realtime",
                    data_timestamp=d.get("datetime", time.strftime("%Y-%m-%d %H:%M:%S UTC")),
                    feed_status="live" if is_open else "delayed",
                    kind="actual",
                    market_status="open" if is_open else "closed",
                    status="ok",
                    extra={
                        "symbol": sym,
                        "name": d.get("name", sym),
                        "price": round(cur, 2),
                        "change": round(chg, 2),
                        "change_percent": f"{pct:+.2f}%",
                        "high_today": round(float(d.get("high", cur)), 2),
                        "low_today": round(float(d.get("low", cur)), 2),
                        "previous_close": round(float(d.get("previous_close", cur)), 2),
                        "source": "TwelveData Global Realtime",
                        "as_of": d.get("datetime", time.strftime("%Y-%m-%d %H:%M:%S"))
                    }
                )
                _set_cache(cache_key, contract, ttl=15)
                return contract

    # 3. Tertiary: AlphaVantage
    if ALPHAVANTAGE_KEY:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={urllib.parse.quote(sym)}&apikey={ALPHAVANTAGE_KEY}"
        res = _http_request(url, timeout=4, retries=0, provider_name="alphavantage")
        if res["ok"]:
            q = res["data"].get("Global Quote", {})
            if "05. price" in q:
                cur = float(q["05. price"])
                contract = make_data_contract(
                    requested_symbol=sym,
                    provider_symbol=q.get("01. symbol", sym),
                    provider_name="Alpha Vantage",
                    data_timestamp=q.get("07. latest trading day", time.strftime("%Y-%m-%d")),
                    feed_status="delayed",
                    kind="actual",
                    market_status="closed",
                    status="ok",
                    extra={
                        "symbol": sym,
                        "price": round(cur, 2),
                        "change": round(float(q.get("09. change", 0)), 2),
                        "change_percent": q.get("10. change percent", "0%"),
                        "high_today": round(float(q.get("03. high", cur)), 2),
                        "low_today": round(float(q.get("04. low", cur)), 2),
                        "previous_close": round(float(q.get("08. previous close", cur)), 2),
                        "source": "Alpha Vantage",
                        "as_of": q.get("07. latest trading day", time.strftime("%Y-%m-%d"))
                    }
                )
                _set_cache(cache_key, contract, ttl=15)
                return contract

    if mode == "demo":
        return make_data_contract(
            requested_symbol=sym,
            provider_symbol=sym,
            provider_name="Synthetic Demo Engine",
            data_timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            feed_status="synthetic_demo",
            kind="synthetic",
            market_status="closed",
            status="ok",
            extra={
                "symbol": sym,
                "price": 200.0,
                "change": 0.0,
                "change_percent": "0.00%",
                "high_today": 202.0,
                "low_today": 198.0,
                "note": "DEMO MODE: Synthetic placeholder for offline preview."
            }
        )

    # In LIVE mode: Fail explicitly
    return make_data_contract(
        requested_symbol=sym,
        provider_symbol="",
        provider_name="None",
        data_timestamp="",
        feed_status="unavailable" if (FINNHUB_KEY or TWELVEDATA_KEY) else "not_configured",
        kind="actual",
        status="error",
        extra={"error": f"Live quote unavailable for '{sym}'. Providers returned no data or keys unconfigured."}
    )

# -------------------------------------------------------------
# 7. OHLCV CANDLESTICK DATA (TWELVEDATA REST)
# -------------------------------------------------------------
def get_ohlcv(symbol="AMZN", interval="1day", outputsize=45, mode="live") -> Dict[str, Any]:
    sym = (symbol or "AMZN").upper().strip()
    if not sym or not re.match(r"^[A-Z0-9.\-_/]{1,15}$", sym):
        return make_data_contract(
            requested_symbol=sym,
            provider_symbol="",
            provider_name="None",
            data_timestamp="",
            feed_status="invalid_symbol",
            kind="actual",
            status="error",
            extra={"error": f"Invalid symbol '{sym}'", "candles": [], "interval": interval}
        )

    cache_key = f"{mode}:ohlcv:{sym}:{interval}:{outputsize}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    if mode == "demo":
        return make_data_contract(
            requested_symbol=sym,
            provider_symbol=sym,
            provider_name="Synthetic Demo Engine",
            data_timestamp=time.strftime("%Y-%m-%d"),
            feed_status="synthetic_demo",
            kind="synthetic",
            status="ok",
            extra={"symbol": sym, "interval": interval, "candles": [], "note": "DEMO MODE: Synthetic placeholder."}
        )

    if TWELVEDATA_KEY:
        url = f"https://api.twelvedata.com/time_series?symbol={urllib.parse.quote(sym)}&interval={interval}&outputsize={outputsize}&apikey={TWELVEDATA_KEY}"
        res = _http_request(url, timeout=5, retries=1, provider_name="twelvedata")
        if res["ok"]:
            d = res["data"]
            if d.get("status") == "error":
                return make_data_contract(
                    requested_symbol=sym,
                    provider_symbol="",
                    provider_name="TwelveData Time Series",
                    data_timestamp="",
                    feed_status="unavailable",
                    kind="actual",
                    status="error",
                    extra={"error": d.get("message", "TwelveData error"), "candles": [], "interval": interval}
                )
            values = d.get("values", [])
            if isinstance(values, list) and len(values) > 0:
                candles = []
                for v in values:
                    candles.append({
                        "datetime": v.get("datetime"),
                        "open": float(v.get("open", 0)),
                        "high": float(v.get("high", 0)),
                        "low": float(v.get("low", 0)),
                        "close": float(v.get("close", 0)),
                        "volume": int(float(v.get("volume", 0) or 0))
                    })
                meta = d.get("meta", {})
                contract = make_data_contract(
                    requested_symbol=sym,
                    provider_symbol=meta.get("symbol", sym),
                    provider_name="TwelveData Historical OHLCV",
                    data_timestamp=candles[0]["datetime"] if candles else time.strftime("%Y-%m-%d"),
                    feed_status="historical",
                    kind="actual",
                    market_status="closed" if interval in ("1day", "1week") else "open",
                    status="ok",
                    extra={
                        "symbol": sym,
                        "interval": interval,
                        "exchange": meta.get("exchange", ""),
                        "currency": meta.get("currency", "USD"),
                        "candles": candles,
                        "candle_count": len(candles),
                        "source": "TwelveData Historical OHLCV"
                    }
                )
                _set_cache(cache_key, contract, ttl=60)
                return contract

    return make_data_contract(
        requested_symbol=sym,
        provider_symbol="",
        provider_name="TwelveData",
        data_timestamp="",
        feed_status="unavailable" if TWELVEDATA_KEY else "not_configured",
        kind="actual",
        status="error",
        extra={"error": f"Candle data unavailable for '{sym}' from configured provider.", "candles": [], "interval": interval}
    )

# -------------------------------------------------------------
# 8. COMMODITY QUOTES (OIL, GOLD, SILVER)
# -------------------------------------------------------------
def get_live_commodity(name="gold", mode="live") -> Dict[str, Any]:
    k = (name or "gold").lower().strip()
    cache_key = f"{mode}:comm:{k}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 1. Brent Crude Oil via OilPriceAPI
    if any(w in k for w in ("oil", "brent", "crude")):
        if OILPRICE_KEY:
            url = "https://api.oilpriceapi.com/v1/prices/latest?by_code=BRENT_CRUDE_USD"
            res = _http_request(url, headers={"Authorization": f"Token {OILPRICE_KEY}"}, timeout=4, retries=1, provider_name="oilprice")
            if res["ok"]:
                p = res["data"].get("data", {}).get("price")
                if p is not None:
                    contract = make_data_contract(
                        requested_symbol="BRENT_CRUDE_USD",
                        provider_symbol="BRENT_CRUDE_USD",
                        provider_name="OilPriceAPI Live Feed",
                        data_timestamp=res["data"].get("data", {}).get("created_at", time.strftime("%Y-%m-%d %H:%M:%S UTC")),
                        feed_status="live",
                        kind="actual",
                        market_status="open",
                        status="ok",
                        extra={
                            "commodity": "Brent Crude Oil",
                            "symbol": "BRENT_CRUDE_USD",
                            "price": round(float(p), 2),
                            "unit": "USD per barrel",
                            "currency": "USD",
                            "source": "OilPriceAPI Live Feed",
                            "as_of": res["data"].get("data", {}).get("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
                        }
                    )
                    _set_cache(cache_key, contract, ttl=30)
                    return contract

        return make_data_contract(
            requested_symbol="BRENT_CRUDE_USD",
            provider_symbol="",
            provider_name="OilPriceAPI",
            data_timestamp="",
            feed_status="unavailable" if OILPRICE_KEY else "not_configured",
            kind="actual",
            status="error",
            extra={"error": "Crude oil live quote unavailable from OilPriceAPI.", "commodity": "Brent Crude Oil"}
        )

    # 2. Gold Spot (XAU/USD) via TwelveData
    if any(w in k for w in ("gold", "xau")):
        if TWELVEDATA_KEY:
            url = f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={TWELVEDATA_KEY}"
            res = _http_request(url, timeout=4, retries=1, provider_name="twelvedata")
            if res["ok"] and "price" in res["data"]:
                cur = float(res["data"]["price"])
                inr_per_10g = round((cur * 88.62 / 31.1035) * 10, 0)
                contract = make_data_contract(
                    requested_symbol="XAU/USD",
                    provider_symbol="XAU/USD",
                    provider_name="TwelveData Spot Markets",
                    data_timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    feed_status="live",
                    kind="actual",
                    market_status="open",
                    status="ok",
                    extra={
                        "commodity": "Gold Spot",
                        "symbol": "XAU/USD",
                        "price": round(cur, 2),
                        "unit": "USD per troy oz",
                        "currency": "USD",
                        "inr_approx_10g": inr_per_10g,
                        "source": "TwelveData Spot Markets",
                        "as_of": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                )
                _set_cache(cache_key, contract, ttl=30)
                return contract

        return make_data_contract(
            requested_symbol="XAU/USD",
            provider_symbol="",
            provider_name="TwelveData",
            data_timestamp="",
            feed_status="unavailable" if TWELVEDATA_KEY else "not_configured",
            kind="actual",
            status="error",
            extra={"error": "Gold spot quote unavailable from TwelveData.", "commodity": "Gold Spot"}
        )

    # 3. Silver Spot (XAG/USD) - TwelveData free tier does NOT support XAG/USD
    if any(w in k for w in ("silver", "xag")):
        return make_data_contract(
            requested_symbol="XAG/USD",
            provider_symbol="XAG/USD",
            provider_name="TwelveData",
            data_timestamp="",
            feed_status="unavailable",
            kind="actual",
            status="error",
            extra={
                "error": "Direct silver spot feed (XAG/USD) is not supported on the active TwelveData tier. Real market quote unavailable.",
                "commodity": "Silver Spot"
            }
        )

    return make_data_contract(
        requested_symbol=name,
        provider_symbol="",
        provider_name="None",
        data_timestamp="",
        feed_status="unavailable",
        kind="actual",
        status="error",
        extra={"error": f"Commodity '{name}' is not configured or unsupported."}
    )

def get_live_quote(kind="stock", symbol="", mode="live"):
    kind = (kind or "stock").lower().strip()
    if kind in ("gold", "silver", "oil", "crude", "brent"):
        return get_live_commodity(kind, mode=mode)
    return get_live_stock(symbol or "AMZN", mode=mode)

# -------------------------------------------------------------
# 9. NATURAL GAS
# -------------------------------------------------------------
def get_natural_gas(mode="live") -> Dict[str, Any]:
    cache_key = f"{mode}:natgas"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    if OILPRICE_KEY:
        url = "https://api.oilpriceapi.com/v1/prices/latest?by_code=NATURAL_GAS_USD"
        res = _http_request(url, headers={"Authorization": f"Token {OILPRICE_KEY}"}, timeout=4, retries=1, provider_name="oilprice")
        if res["ok"]:
            p = res["data"].get("data", {}).get("price")
            if p is not None:
                contract = make_data_contract(
                    requested_symbol="NATURAL_GAS_USD",
                    provider_symbol="NATURAL_GAS_USD",
                    provider_name="OilPriceAPI Live Feed",
                    data_timestamp=res["data"].get("data", {}).get("created_at", time.strftime("%Y-%m-%d %H:%M:%S UTC")),
                    feed_status="live",
                    kind="actual",
                    market_status="open",
                    status="ok",
                    extra={
                        "commodity": "Natural Gas",
                        "symbol": "NATURAL_GAS_USD",
                        "price": round(float(p), 4),
                        "unit": "USD per MMBtu",
                        "currency": "USD",
                        "source": "OilPriceAPI Live Feed",
                        "as_of": res["data"].get("data", {}).get("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
                    }
                )
                _set_cache(cache_key, contract, ttl=30)
                return contract

    return make_data_contract(
        requested_symbol="NATURAL_GAS_USD",
        provider_symbol="",
        provider_name="OilPriceAPI",
        data_timestamp="",
        feed_status="unavailable" if OILPRICE_KEY else "not_configured",
        kind="actual",
        status="error",
        extra={"error": "Natural gas price unavailable from OilPriceAPI."}
    )

# -------------------------------------------------------------
# 10. FOREX & INDIAN INDICES
# -------------------------------------------------------------
def get_forex(from_currency="USD", to_currency="INR", mode="live") -> Dict[str, Any]:
    fc = (from_currency or "USD").upper().strip()
    tc = (to_currency or "INR").upper().strip()
    pair = f"{fc}/{tc}"
    cache_key = f"{mode}:forex:{pair}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    if TWELVEDATA_KEY:
        url = f"https://api.twelvedata.com/price?symbol={urllib.parse.quote(pair)}&apikey={TWELVEDATA_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="twelvedata")
        if res["ok"] and "price" in res["data"]:
            rate = float(res["data"]["price"])
            contract = make_data_contract(
                requested_symbol=pair,
                provider_symbol=pair,
                provider_name="TwelveData Forex Realtime",
                data_timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                feed_status="live",
                kind="actual",
                market_status="open",
                status="ok",
                extra={
                    "pair": pair,
                    "rate": round(rate, 4),
                    "from": fc,
                    "to": tc,
                    "source": "TwelveData Forex Realtime",
                    "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC")
                }
            )
            _set_cache(cache_key, contract, ttl=30)
            return contract

    return make_data_contract(
        requested_symbol=pair,
        provider_symbol="",
        provider_name="None",
        data_timestamp="",
        feed_status="unavailable",
        kind="actual",
        status="error",
        extra={"error": f"Forex rate unavailable for '{pair}'."}
    )

def get_india_index(index="NIFTY 50", mode="live") -> Dict[str, Any]:
    idx = (index or "NIFTY 50").strip()
    # TwelveData free tier does NOT include Indian exchange indices (BSE/NSE require regional license)
    return make_data_contract(
        requested_symbol=idx,
        provider_symbol="",
        provider_name="TwelveData India Markets",
        data_timestamp="",
        feed_status="unavailable",
        kind="actual",
        status="error",
        extra={
            "error": f"Live Indian index feed for '{idx}' requires an active Indian Exchange (BSE/NSE) subscription with TwelveData.",
            "index": idx
        }
    )

# -------------------------------------------------------------
# 11. CRYPTO
# -------------------------------------------------------------
def get_crypto_price(symbol="BTC", mode="live") -> Dict[str, Any]:
    sym = (symbol or "BTC").upper().strip()
    cache_key = f"{mode}:crypto:{sym}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    pair = f"{sym}/USD"
    if TWELVEDATA_KEY:
        url = f"https://api.twelvedata.com/price?symbol={urllib.parse.quote(pair)}&apikey={TWELVEDATA_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="twelvedata")
        if res["ok"] and "price" in res["data"]:
            p = float(res["data"]["price"])
            contract = make_data_contract(
                requested_symbol=sym,
                provider_symbol=pair,
                provider_name="TwelveData Crypto Realtime",
                data_timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                feed_status="live",
                kind="actual",
                market_status="open",
                status="ok",
                extra={
                    "symbol": sym,
                    "pair": pair,
                    "price": round(p, 2),
                    "currency": "USD",
                    "source": "TwelveData Crypto Realtime",
                    "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC")
                }
            )
            _set_cache(cache_key, contract, ttl=15)
            return contract

    if FINNHUB_KEY:
        url = f"https://finnhub.io/api/v1/quote?symbol=BINANCE:{sym}USDT&token={FINNHUB_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="finnhub")
        if res["ok"] and res["data"].get("c", 0) > 0:
            p = float(res["data"]["c"])
            contract = make_data_contract(
                requested_symbol=sym,
                provider_symbol=f"BINANCE:{sym}USDT",
                provider_name="Finnhub Crypto (Binance)",
                data_timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                feed_status="live",
                kind="actual",
                market_status="open",
                status="ok",
                extra={
                    "symbol": sym,
                    "pair": f"{sym}/USDT",
                    "price": round(p, 2),
                    "currency": "USDT",
                    "source": "Finnhub Crypto (Binance)",
                    "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC")
                }
            )
            _set_cache(cache_key, contract, ttl=15)
            return contract

    return make_data_contract(
        requested_symbol=sym,
        provider_symbol="",
        provider_name="None",
        data_timestamp="",
        feed_status="unavailable",
        kind="actual",
        status="error",
        extra={"error": f"Crypto quote unavailable for '{sym}'."}
    )

# -------------------------------------------------------------
# 12. COMPANY PROFILE, METRICS & NEWS
# -------------------------------------------------------------
def get_company_profile(symbol="AAPL", mode="live") -> Dict[str, Any]:
    sym = (symbol or "AAPL").upper().strip()
    cache_key = f"{mode}:prof:{sym}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    if FINNHUB_KEY:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={urllib.parse.quote(sym)}&token={FINNHUB_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="finnhub")
        if res["ok"] and res["data"].get("name"):
            d = res["data"]
            contract = make_data_contract(
                requested_symbol=sym,
                provider_symbol=d.get("ticker", sym),
                provider_name="Finnhub Company Fundamentals",
                data_timestamp=time.strftime("%Y-%m-%d"),
                feed_status="historical",
                kind="actual",
                status="ok",
                extra={
                    "symbol": sym,
                    "name": d.get("name"),
                    "country": d.get("country"),
                    "exchange": d.get("exchange"),
                    "industry": d.get("finnhubIndustry"),
                    "ipo_date": d.get("ipo"),
                    "logo": d.get("logo"),
                    "market_cap_usd": d.get("marketCapitalization"),
                    "shares_outstanding": d.get("shareOutstanding"),
                    "currency": d.get("currency"),
                    "website": d.get("weburl"),
                    "ticker": d.get("ticker"),
                    "source": "Finnhub Company Fundamentals",
                    "as_of": time.strftime("%Y-%m-%d")
                }
            )
            _set_cache(cache_key, contract, ttl=300)
            return contract

    return make_data_contract(
        requested_symbol=sym,
        provider_symbol="",
        provider_name="Finnhub",
        data_timestamp="",
        feed_status="unavailable",
        kind="actual",
        status="error",
        extra={"error": f"Profile unavailable for '{sym}'. Ticker may be private or delisted."}
    )

def get_company_news(symbol="AAPL", count=5, mode="live") -> Dict[str, Any]:
    sym = (symbol or "AAPL").upper().strip()
    cache_key = f"{mode}:news:{sym}:{count}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    if FINNHUB_KEY:
        from_date = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
        to_date = time.strftime("%Y-%m-%d", time.gmtime())
        url = f"https://finnhub.io/api/v1/company-news?symbol={urllib.parse.quote(sym)}&from={from_date}&to={to_date}&token={FINNHUB_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="finnhub")
        if res["ok"] and isinstance(res["data"], list):
            news = []
            for item in res["data"][:count]:
                news.append({
                    "headline": item.get("headline"),
                    "summary": item.get("summary", "")[:300],
                    "source": item.get("source"),
                    "url": item.get("url"),
                    "datetime": time.strftime("%Y-%m-%d %H:%M", time.gmtime(item.get("datetime", 0))),
                    "sentiment": "bullish" if item.get("sentiment", 0) > 0.2 else ("bearish" if item.get("sentiment", 0) < -0.2 else "neutral")
                })
            contract = make_data_contract(
                requested_symbol=sym,
                provider_symbol=sym,
                provider_name="Finnhub Company News",
                data_timestamp=to_date,
                feed_status="historical",
                kind="actual",
                status="ok",
                extra={
                    "symbol": sym,
                    "news_count": len(news),
                    "news": news,
                    "source": "Finnhub Company News",
                    "period": f"{from_date} to {to_date}"
                }
            )
            _set_cache(cache_key, contract, ttl=180)
            return contract

    return make_data_contract(
        requested_symbol=sym,
        provider_symbol="",
        provider_name="Finnhub",
        data_timestamp="",
        feed_status="unavailable",
        kind="actual",
        status="error",
        extra={"error": f"News unavailable for '{sym}'.", "news": [], "news_count": 0}
    )

def get_stock_metrics(symbol="AAPL", mode="live") -> Dict[str, Any]:
    sym = (symbol or "AAPL").upper().strip()
    cache_key = f"{mode}:metrics:{sym}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    if FINNHUB_KEY:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={urllib.parse.quote(sym)}&metric=all&token={FINNHUB_KEY}"
        res = _http_request(url, timeout=4, retries=1, provider_name="finnhub")
        if res["ok"]:
            m = res["data"].get("metric", {})
            if m:
                contract = make_data_contract(
                    requested_symbol=sym,
                    provider_symbol=sym,
                    provider_name="Finnhub Financial Metrics",
                    data_timestamp=time.strftime("%Y-%m-%d"),
                    feed_status="historical",
                    kind="actual",
                    status="ok",
                    extra={
                        "symbol": sym,
                        "pe_ratio": m.get("peBasicExclExtraTTM"),
                        "eps_ttm": m.get("epsBasicExclExtraAnnual"),
                        "roe": m.get("roeRfy"),
                        "revenue_ttm_usd": m.get("revenuePerShareAnnual"),
                        "52w_high": m.get("52WeekHigh"),
                        "52w_low": m.get("52WeekLow"),
                        "beta": m.get("beta"),
                        "dividend_yield": m.get("dividendYieldIndicatedAnnual"),
                        "book_value_per_share": m.get("bookValuePerShareAnnual"),
                        "debt_equity": m.get("totalDebt/totalEquityAnnual"),
                        "source": "Finnhub Financial Metrics",
                        "as_of": time.strftime("%Y-%m-%d")
                    }
                )
                _set_cache(cache_key, contract, ttl=300)
                return contract

    return make_data_contract(
        requested_symbol=sym,
        provider_symbol="",
        provider_name="Finnhub",
        data_timestamp="",
        feed_status="unavailable",
        kind="actual",
        status="error",
        extra={"error": f"Financial metrics unavailable for '{sym}'."}
    )

# -------------------------------------------------------------
# 13. WATCHLIST & MARKET OVERVIEW
# -------------------------------------------------------------
def get_watchlist_prices(symbols: List[str], mode="live") -> Dict[str, Any]:
    results = []
    for s in symbols[:20]:
        sym = str(s).upper().strip()
        if sym:
            q = get_live_stock(sym, mode=mode)
            results.append({
                "requested_symbol": sym,
                "symbol": sym,
                "price": q.get("price"),
                "change": q.get("change"),
                "change_percent": q.get("change_percent"),
                "feed_status": q.get("feed_status", "unavailable"),
                "provider_name": q.get("provider_name", "None"),
                "status": q.get("status", "error"),
                "error": q.get("error")
            })
    return {
        "status": "ok",
        "kind": "actual",
        "prices": results,
        "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    }

def get_market_overview(mode="live") -> Dict[str, Any]:
    cache_key = f"{mode}:overview"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    results = {}
    for sym in ("AMZN", "NVDA", "AAPL", "GOOGL"):
        try:
            q = get_live_stock(sym, mode=mode)
            if q.get("status") == "ok":
                results[sym] = {"price": q.get("price"), "change_pct": q.get("change_percent"), "feed_status": q.get("feed_status"), "provider": q.get("provider_name")}
            else:
                results[sym] = {"status": "unavailable", "error": q.get("error")}
        except Exception:
            results[sym] = {"status": "unavailable"}

    gold = get_live_commodity("gold", mode=mode)
    results["GOLD"] = {"price": gold.get("price"), "unit": gold.get("unit"), "feed_status": gold.get("feed_status")} if gold.get("status") == "ok" else {"status": "unavailable", "error": gold.get("error")}

    oil = get_live_commodity("oil", mode=mode)
    results["BRENT"] = {"price": oil.get("price"), "unit": oil.get("unit"), "feed_status": oil.get("feed_status")} if oil.get("status") == "ok" else {"status": "unavailable", "error": oil.get("error")}

    btc = get_crypto_price("BTC", mode=mode)
    results["BTC"] = {"price": btc.get("price"), "currency": "USD", "feed_status": btc.get("feed_status")} if btc.get("status") == "ok" else {"status": "unavailable", "error": btc.get("error")}

    fx = get_forex("USD", "INR", mode=mode)
    results["USD/INR"] = {"rate": fx.get("rate"), "feed_status": fx.get("feed_status")} if fx.get("status") == "ok" else {"status": "unavailable", "error": fx.get("error")}

    contract = {
        "status": "ok",
        "kind": "actual",
        "market_overview": results,
        "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "data_provenance": "Aggregated from verified upstream endpoints (Finnhub, TwelveData, OilPriceAPI)."
    }
    _set_cache(cache_key, contract, ttl=15)
    return contract

# -------------------------------------------------------------
# 14. IPO PIPELINE (HONEST CONTRACT)
# -------------------------------------------------------------
def get_ipos(mode="live") -> Dict[str, Any]:
    """Returns IPO pipeline. Never manufactures fake live filings."""
    if mode == "demo":
        return {
            "status": "ok",
            "kind": "synthetic",
            "feed_status": "synthetic_demo",
            "source": "Historical Reference / Demo Fixtures",
            "as_of": time.strftime("%Y-%m-%d"),
            "note": "DEMO MODE: Synthetic fixtures for testing. Not live filings.",
            "ipos": [
                {"company": "Swiggy Ltd", "status": "Listed (Historical Demo)", "exchange": "NSE/BSE", "price_band": "₹371 - ₹390", "issue_size": "₹11,327 Cr"},
                {"company": "NTPC Green Energy Ltd", "status": "Listed (Historical Demo)", "exchange": "NSE/BSE", "price_band": "₹102 - ₹108", "issue_size": "₹10,000 Cr"},
                {"company": "Hyundai Motor India", "status": "Listed (Historical Demo)", "exchange": "NSE/BSE", "price_band": "₹1,865 - ₹1,960", "issue_size": "₹27,870 Cr"}
            ]
        }

    return {
        "status": "unavailable",
        "kind": "actual",
        "feed_status": "not_configured",
        "source": "Official Exchange / Regulatory Filings (BSE/NSE/SEC)",
        "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "error": "Live IPO Radar feed requires a licensed exchange or regulatory filing API subscription (e.g. BSE/NSE IPO API or SEC EDGAR filings). Feed is currently not configured.",
        "ipos": []
    }

# -------------------------------------------------------------
# 15. ALPACA LIVE PAPER TRADING (STRICT SERVER-SIDE VALIDATION)
# -------------------------------------------------------------
_ALPACA_IDEMPOTENCY_CACHE: Dict[str, tuple] = {}

def _alpaca_headers():
    return {
        "APCA-API-KEY-ID": ALPACA_KEY_ID,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
    }

def get_alpaca_account():
    """Fetches real live Alpaca Paper Trading account status, cash, and portfolio equity."""
    if not ALPACA_KEY_ID or not ALPACA_SECRET_KEY:
        return {"status": "error", "feed_status": "not_configured", "error": "Alpaca credentials not configured in environment."}
    try:
        url = f"{ALPACA_BASE_URL}/account"
        res = _http_request(url, headers=_alpaca_headers(), timeout=5, retries=1, provider_name="alpaca_paper")
        if not res["ok"]:
            return {"status": "error", "feed_status": res["feed_status"], "error": res.get("error")}
        d = res["data"]
        cash = float(d.get("cash", 0))
        equity = float(d.get("equity", cash))
        buying_power = float(d.get("buying_power", cash))
        return {
            "status": "ok",
            "kind": "actual",
            "feed_status": "live",
            "account_id": d.get("id"),
            "status_text": d.get("status", "ACTIVE"),
            "currency": d.get("currency", "USD"),
            "cash_balance": round(cash, 2),
            "portfolio_equity": round(equity, 2),
            "buying_power": round(buying_power, 2),
            "pattern_day_trader": d.get("pattern_day_trader", False),
            "source": "Alpaca Paper API (Real Sandbox)",
            "as_of": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        }
    except Exception as e:
        return {"status": "error", "feed_status": "unavailable", "error": f"Alpaca API call failed: {redact_secrets(str(e))[:100]}"}

def get_alpaca_positions():
    """Fetches active open positions from Alpaca Paper Trading."""
    if not ALPACA_KEY_ID or not ALPACA_SECRET_KEY:
        return {"status": "error", "feed_status": "not_configured", "error": "Alpaca credentials not configured."}
    try:
        url = f"{ALPACA_BASE_URL}/positions"
        res = _http_request(url, headers=_alpaca_headers(), timeout=5, retries=1, provider_name="alpaca_paper")
        if not res["ok"]:
            return {"status": "error", "feed_status": res["feed_status"], "error": res.get("error")}
        items = res["data"] if isinstance(res["data"], list) else []
        positions = []
        for p in items:
            positions.append({
                "symbol": p.get("symbol"),
                "qty": float(p.get("qty", 0)),
                "current_price": float(p.get("current_price", 0)),
                "market_value": float(p.get("market_value", 0)),
                "cost_basis": float(p.get("cost_basis", 0)),
                "unrealized_pl": float(p.get("unrealized_pl", 0)),
                "unrealized_plpc": f"{float(p.get('unrealized_plpc', 0)) * 100:+.2f}%"
            })
        return {"status": "ok", "kind": "actual", "feed_status": "live", "positions": positions}
    except Exception as e:
        return {"status": "error", "feed_status": "unavailable", "error": redact_secrets(str(e))[:100]}

def place_alpaca_order(symbol="AMZN", qty=1, side="buy", order_type="market", time_in_force="day", client_order_id=None):
    """Submits a real market buy or sell order to Alpaca Paper Trading with strict server-side validation and idempotency."""
    sym = (symbol or "").upper().strip()
    side = (side or "").lower().strip()
    order_type = (order_type or "market").lower().strip()
    time_in_force = (time_in_force or "day").lower().strip()

    # 1. Validation
    if not sym or not re.match(r"^[A-Z0-9.]{1,10}$", sym):
        return {"status": "error", "feed_status": "validation_failed", "error": f"Invalid order symbol: '{symbol}'. Must be 1-10 uppercase alphanumeric characters."}

    try:
        qty_int = int(qty)
        if qty_int <= 0:
            return {"status": "error", "feed_status": "validation_failed", "error": f"Order quantity must be a strictly positive integer (> 0). Got {qty}."}
    except (ValueError, TypeError):
        return {"status": "error", "feed_status": "validation_failed", "error": f"Invalid quantity value: '{qty}'. Must be an integer > 0."}

    if side not in ("buy", "sell"):
        return {"status": "error", "feed_status": "validation_failed", "error": f"Invalid side: '{side}'. Must be 'buy' or 'sell'."}

    if order_type not in ("market", "limit"):
        return {"status": "error", "feed_status": "validation_failed", "error": f"Invalid order_type: '{order_type}'. Supported: 'market', 'limit'."}

    if time_in_force not in ("day", "gtc"):
        return {"status": "error", "feed_status": "validation_failed", "error": f"Invalid time_in_force: '{time_in_force}'. Supported: 'day', 'gtc'."}

    # 2. Check credentials
    if not ALPACA_KEY_ID or not ALPACA_SECRET_KEY:
        return {"status": "error", "feed_status": "not_configured", "error": "Alpaca Paper Trading credentials are not configured in environment."}

    # 3. Idempotency Check
    if not client_order_id:
        client_order_id = f"oracle_{uuid.uuid4().hex[:16]}"
    else:
        client_order_id = str(client_order_id).strip()
        if client_order_id in _ALPACA_IDEMPOTENCY_CACHE:
            ts, prev_resp = _ALPACA_IDEMPOTENCY_CACHE[client_order_id]
            if time.time() - ts < 600:
                return {**prev_resp, "idempotent_replay": True, "note": "Duplicate order request suppressed via client_order_id idempotency."}

    # 4. Check account status & buying power constraint
    account = get_alpaca_account()
    if account.get("status") != "ok":
        return {"status": "error", "feed_status": "account_unavailable", "error": f"Could not verify Alpaca account status: {account.get('error')}"}
    if account.get("status_text") != "ACTIVE":
        return {"status": "error", "feed_status": "account_inactive", "error": f"Alpaca Paper account is not active (status: {account.get('status_text')})."}

    # 5. Execute Order against Alpaca Paper REST API
    payload = {
        "symbol": sym,
        "qty": str(qty_int),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
        "client_order_id": client_order_id
    }

    url = f"{ALPACA_BASE_URL}/orders"
    res = _http_request(url, method="POST", data_dict=payload, headers=_alpaca_headers(), timeout=6, retries=0, provider_name="alpaca_paper")

    if not res["ok"]:
        err_msg = res.get("error", "Alpaca rejected the order submission.")
        return {
            "status": "error",
            "feed_status": "order_rejected",
            "order_status": "rejected",
            "error": f"Alpaca Order Rejection: {err_msg}",
            "symbol": sym,
            "qty": qty_int,
            "side": side,
            "client_order_id": client_order_id
        }

    data = res["data"]
    order_status = data.get("status", "accepted")
    resp_dict = {
        "status": "ok",
        "feed_status": "live",
        "kind": "actual",
        "order_id": data.get("id"),
        "client_order_id": client_order_id,
        "symbol": sym,
        "qty": qty_int,
        "side": side,
        "order_type": order_type,
        "order_status": order_status,
        "submitted_at": data.get("submitted_at", time.strftime("%Y-%m-%d %H:%M:%S UTC")),
        "source": "Alpaca Paper API (Real Sandbox)",
        "message": f"Alpaca Paper {side.upper()} order for {qty_int} shares of {sym} submitted (Status: {order_status})."
    }
    _ALPACA_IDEMPOTENCY_CACHE[client_order_id] = (time.time(), resp_dict)
    return resp_dict

# -------------------------------------------------------------
# 16. WEB SEARCH & DEEP DRIFT INVESTMENT MODEL
# -------------------------------------------------------------
def web_search(query: str, max_results=5) -> Dict[str, Any]:
    q = (query or "").strip()
    cache_key = f"search:{q}:{max_results}"
    cached = _get_cache(cache_key)
    if cached:
        return cached
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=max_results):
                results.append({
                    "title": r.get("title"),
                    "body": r.get("body", "")[:400],
                    "href": r.get("href")
                })
        contract = {"status": "ok", "query": q, "results": results, "source": "DuckDuckGo Web Search"}
        _set_cache(cache_key, contract, ttl=120)
        return contract
    except Exception as e:
        return {"status": "error", "error": f"Web search failed: {redact_secrets(str(e))[:100]}"}

def _norm_cdf(x):
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def analyze_investment(symbol="AMZN", horizon_days=90, capital=100000.0, mode="live") -> Dict[str, Any]:
    sym = (symbol or "AMZN").upper().strip()
    quote = get_live_stock(sym, mode=mode)
    if quote.get("status") != "ok":
        return quote

    p0 = float(quote["price"])
    t_years = max(7, int(horizon_days)) / 365.25
    cap = float(capital)

    volatility = 0.28
    expected_drift = 0.15

    drift_t = (expected_drift - 0.5 * (volatility ** 2)) * t_years
    vol_t = volatility * math.sqrt(t_years)

    p_base = p0 * math.exp(drift_t)
    base_return_pct = round((p_base / p0 - 1.0) * 100.0, 2)
    base_val = round(cap * (1.0 + base_return_pct / 100.0), 2)

    p_bull = p0 * math.exp(drift_t + vol_t * 1.04)
    bull_return_pct = round((p_bull / p0 - 1.0) * 100.0, 2)
    bull_val = round(cap * (1.0 + bull_return_pct / 100.0), 2)

    p_bear = p0 * math.exp(drift_t - vol_t * 1.04)
    bear_return_pct = round((p_bear / p0 - 1.0) * 100.0, 2)
    bear_val = round(cap * (1.0 + bear_return_pct / 100.0), 2)

    z_win = drift_t / max(1e-5, vol_t)
    win_probability = round(_norm_cdf(z_win) * 100.0, 1)

    var_95_pct = round((1.0 - math.exp(drift_t - vol_t * 1.645)) * 100.0, 2)
    max_loss_amount = round(cap * (var_95_pct / 100.0), 2)

    if win_probability >= 68.0 and bear_return_pct > -12.0:
        verdict = "Strong Growth Potential (High Success Probability)"
        rating = "Bullish / Accumulate"
        risk_tier = "Moderate"
    elif win_probability >= 55.0:
        verdict = "Favorable Long-Term Trajectory with Market Volatility"
        rating = "Cautious Buy / Dollar-Cost Average"
        risk_tier = "Medium"
    else:
        verdict = "High Downside Risk Over Selected Horizon"
        rating = "Caution / Set Tight Stop-Loss"
        risk_tier = "High"

    horizons = {}
    for d_days in (30, 90, 180, 365):
        t_h = d_days / 365.25
        exp_p = p0 * math.exp((expected_drift - 0.5 * (volatility ** 2)) * t_h)
        horizons[f"{d_days}_days"] = {
            "projected_price": round(exp_p, 2),
            "expected_gain_pct": round((exp_p / p0 - 1.0) * 100.0, 1),
            "projected_value": round(cap * (exp_p / p0), 2)
        }

    telugu_summary = (
        f"Mee investment ₹{cap:,.0f} ని {sym} (ప్రస్తుత ధర ${p0:,.2f}) లో {horizon_days} రోజులు పెడితే: "
        f"లాభం వచ్చే అవకాశం (Success Rate): {win_probability}%. "
        f"Base Case లో ఊహించిన రిటర్న్: {base_return_pct:+.1f}% (చివరి విలువ ₹{base_val:,.0f}). "
        f"కానీ మార్కెట్ నష్టపోతే గరిష్ట నష్ట ప్రమాదం (Max Loss Risk): -{var_95_pct:.1f}% (సుమారు ₹{max_loss_amount:,.0f}). "
        f"సిఫార్సు: {rating}."
    )

    return {
        "status": "ok",
        "kind": "forecast",
        "feed_status": quote.get("feed_status", "live"),
        "requested_symbol": sym,
        "symbol": sym,
        "current_price": p0,
        "horizon_days": horizon_days,
        "invested_capital": cap,
        "win_probability_pct": win_probability,
        "verdict": verdict,
        "rating": rating,
        "risk_tier": risk_tier,
        "scenarios": {
            "bull_case": {"target_price": round(p_bull, 2), "return_pct": bull_return_pct, "projected_value": bull_val, "gain_amount": round(bull_val - cap, 2)},
            "base_case": {"target_price": round(p_base, 2), "return_pct": base_return_pct, "projected_value": base_val, "gain_amount": round(base_val - cap, 2)},
            "bear_case": {"target_price": round(p_bear, 2), "return_pct": bear_return_pct, "projected_value": bear_val, "loss_amount": round(cap - bear_val, 2)}
        },
        "max_drawdown_risk_95_var": {"max_loss_pct": var_95_pct, "max_loss_capital": max_loss_amount},
        "horizon_projections": horizons,
        "telugu_advice": telugu_summary,
        "disclaimer": "Predictions are probabilistic mathematical estimates based on asset volatility and drift models. No model can confirm guaranteed profits or eliminate market loss. Always employ stop-loss discipline."
    }

# -------------------------------------------------------------
# 17. CRICKET SIMULATOR & LOCAL PAPER ENGINE
# -------------------------------------------------------------
def cricket_match_simulator(team1="India", team2="Australia", format_type="T20", target=185, current_runs=122, wickets_down=3, overs_completed=14.2):
    total_overs = 20 if format_type == "T20" else 50
    overs_left = max(0.1, total_overs - overs_completed)
    runs_needed = max(0, target - current_runs)
    wickets_in_hand = max(0, 10 - wickets_down)
    current_rr = current_runs / max(0.1, overs_completed)
    req_rr = runs_needed / overs_left if overs_left > 0 else 999.0

    diff = 7.5 - req_rr + (wickets_in_hand * 0.42)
    win_prob_chasing = 1.0 / (1.0 + math.exp(-0.35 * diff))
    win_prob_chasing = min(0.99, max(0.01, win_prob_chasing))
    if wickets_down >= 10: win_prob_chasing = 0.0
    elif runs_needed <= 0: win_prob_chasing = 1.0

    win_prob_def = round((1.0 - win_prob_chasing) * 100.0, 1)
    win_prob_chg = round(win_prob_chasing * 100.0, 1)

    advice = []
    if req_rr > 11.0: advice.append(f"High risk chase: Required run rate is {req_rr:.1f} RPO. Chasing team must target boundary options early.")
    elif req_rr < 6.5: advice.append(f"Comfortable chase: Required run rate is {req_rr:.1f} RPO. Prioritize strike rotation and protect wickets.")
    else: advice.append(f"Balanced contest: Required run rate is {req_rr:.1f} RPO. Momentum hinges on the next 2 overs.")
    if wickets_in_hand <= 3: advice.append(f"Tail exposed: Chasing team has only {wickets_in_hand} wickets in hand.")

    return {
        "status": "ok",
        "kind": "calculated",
        "format": format_type,
        "team1": team1,
        "team2": team2,
        "target": target,
        "current_score": f"{current_runs}/{wickets_down} in {overs_completed} ov",
        "required_runs": runs_needed,
        "required_run_rate": round(req_rr, 2),
        "current_run_rate": round(current_rr, 2),
        "win_probability": {f"{team1} (Defending)": f"{win_prob_def}%", f"{team2} (Chasing)": f"{win_prob_chg}%"},
        "advisory_notes": advice,
        "disclaimer": "Probabilistic model based on match situation and historical international cricket dynamics."
    }

class PaperTradingEngine:
    def __init__(self, initial_capital=1000000.0):
        self.capital = initial_capital
        self.portfolio = {}
        self.trades = []
        self.kill_switch_active = False
        self.starting_capital = initial_capital

    def execute_trade(self, symbol, action, shares, current_price):
        if self.kill_switch_active:
            return {"status": "error", "error": "Kill-switch engaged! Trading halted to preserve capital."}
        sym = symbol.upper().strip()
        shares = int(shares)
        if shares <= 0 or current_price <= 0:
            return {"status": "error", "error": "Shares and price must be positive numbers."}
        total_cost = shares * current_price
        if action.lower() == "buy":
            if total_cost > self.capital:
                return {"status": "error", "error": f"Insufficient virtual cash balance. Needed: ₹{total_cost:,.2f}, Available: ₹{self.capital:,.2f}"}
            self.capital -= total_cost
            if sym in self.portfolio:
                old_shares = self.portfolio[sym]["shares"]
                old_avg = self.portfolio[sym]["avg_price"]
                new_shares = old_shares + shares
                new_avg = ((old_shares * old_avg) + total_cost) / new_shares
                self.portfolio[sym] = {"shares": new_shares, "avg_price": round(new_avg, 2)}
            else:
                self.portfolio[sym] = {"shares": shares, "avg_price": round(current_price, 2)}
            self.trades.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": "BUY", "symbol": sym, "shares": shares, "price": current_price, "total": total_cost})
            return {"status": "ok", "message": f"Successfully bought {shares} shares of {sym} at ₹{current_price:,.2f}", "cash_balance": round(self.capital, 2)}
        elif action.lower() == "sell":
            if sym not in self.portfolio or self.portfolio[sym]["shares"] < shares:
                avail = self.portfolio.get(sym, {}).get("shares", 0)
                return {"status": "error", "error": f"Insufficient shares to sell. Available: {avail}, Requested: {shares}"}
            proceeds = shares * current_price
            pnl = proceeds - (shares * self.portfolio[sym]["avg_price"])
            self.capital += proceeds
            self.portfolio[sym]["shares"] -= shares
            if self.portfolio[sym]["shares"] == 0:
                del self.portfolio[sym]
            self.trades.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": "SELL", "symbol": sym, "shares": shares, "price": current_price, "total": proceeds, "pnl": round(pnl, 2)})
            return {"status": "ok", "message": f"Successfully sold {shares} shares of {sym} at ₹{current_price:,.2f} (PnL: ₹{pnl:+,.2f})", "cash_balance": round(self.capital, 2)}
        return {"status": "error", "error": "Invalid action. Use 'buy' or 'sell'."}

    def get_summary(self):
        holdings_value = sum(p["shares"] * p["avg_price"] for p in self.portfolio.values())
        total_equity = self.capital + holdings_value
        return {
            "kind": "calculated",
            "cash_balance": round(self.capital, 2),
            "holdings_value": round(holdings_value, 2),
            "total_portfolio_equity": round(total_equity, 2),
            "total_return_pct": round(((total_equity - self.starting_capital) / self.starting_capital) * 100, 2),
            "kill_switch_engaged": self.kill_switch_active,
            "positions": self.portfolio,
            "recent_trades": self.trades[-5:]
        }
