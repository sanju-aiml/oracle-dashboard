"""Angel One SmartAPI live quote source and Market Feeds SmartWebSocketV2 streaming.

Credentials (ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_SECRET) are read
exclusively from environment variables. Tokens and secrets are held in memory only.
Never logs or prints secrets, tokens, or TOTP secrets.
Never disables TLS verification.
"""
import datetime
import json
import logging
import os
import ssl
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import certifi
import pyotp
import requests
import websocket
from SmartApi.smartConnect import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

import config
import store

log = logging.getLogger("oracle.smartapi")

# Load .env if not loaded already
def _load_env_credentials():
    env_paths = [
        os.path.join(config.BASE, "..", ".env"),
        os.path.join(config.BASE, ".env"),
        os.path.abspath(".env")
    ]
    for p in env_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip()
                            if k not in os.environ and v:
                                os.environ[k] = v
            except Exception as e:
                log.debug("Error loading .env file: %s", e)
            break

_load_env_credentials()

# Credential readers
def get_angel_credentials() -> Dict[str, str]:
    _load_env_credentials()
    return {
        "api_key": os.getenv("ANGEL_API_KEY", "").strip(),
        "client_id": os.getenv("ANGEL_CLIENT_ID", "").strip(),
        "pin": os.getenv("ANGEL_PIN", "").strip(),
        "totp_secret": os.getenv("ANGEL_TOTP_SECRET", "").strip(),
    }

def has_angel_credentials() -> bool:
    c = get_angel_credentials()
    return bool(c["api_key"] and c["client_id"] and c["pin"] and c["totp_secret"])


# ---------------------------------------------------------------------------
# Instrument Master & Symbol Mapping
# ---------------------------------------------------------------------------
class SmartAPIInstrumentManager:
    """Maps ORACLE symbols to Angel One exchange and symbol tokens with daily disk caching."""

    CACHE_FILE = os.path.join(config.BASE, "data", "angel_instruments_cache.json")
    SCRIP_URL_PRIMARY = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
    SCRIP_URL_BACKUP = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

    # Static bootstrap map for instant lookup without network latency
    BOOTSTRAP_MAP: Dict[str, Dict[str, Any]] = {
        "NIFTY": {"token": "99926000", "tradingsymbol": "Nifty 50", "exchange": "NSE", "exchangeType": 1},
        "SENSEX": {"token": "99919000", "tradingsymbol": "SENSEX", "exchange": "BSE", "exchangeType": 3},
        "INDIAVIX": {"token": "99926017", "tradingsymbol": "India VIX", "exchange": "NSE", "exchangeType": 1},
        "RELIANCE": {"token": "2885", "tradingsymbol": "RELIANCE-EQ", "exchange": "NSE", "exchangeType": 1},
        "TCS": {"token": "11536", "tradingsymbol": "TCS-EQ", "exchange": "NSE", "exchangeType": 1},
        "INFY": {"token": "1594", "tradingsymbol": "INFY-EQ", "exchange": "NSE", "exchangeType": 1},
        "HDFCBANK": {"token": "1333", "tradingsymbol": "HDFCBANK-EQ", "exchange": "NSE", "exchangeType": 1},
        "ICICIBANK": {"token": "4963", "tradingsymbol": "ICICIBANK-EQ", "exchange": "NSE", "exchangeType": 1},
        "SBIN": {"token": "3045", "tradingsymbol": "SBIN-EQ", "exchange": "NSE", "exchangeType": 1},
        "BHARTIARTL": {"token": "10604", "tradingsymbol": "BHARTIARTL-EQ", "exchange": "NSE", "exchangeType": 1},
        "ITC": {"token": "1660", "tradingsymbol": "ITC-EQ", "exchange": "NSE", "exchangeType": 1},
        "LT": {"token": "11483", "tradingsymbol": "LT-EQ", "exchange": "NSE", "exchangeType": 1},
        "KOTAKBANK": {"token": "1922", "tradingsymbol": "KOTAKBANK-EQ", "exchange": "NSE", "exchangeType": 1},
    }

    def __init__(self):
        self._symbols: Dict[str, Dict[str, Any]] = dict(self.BOOTSTRAP_MAP)
        self._token_to_symbol: Dict[str, str] = {v["token"]: k for k, v in self.BOOTSTRAP_MAP.items()}
        self._cache_date: Optional[str] = None
        self._lock = threading.Lock()
        self.load_cache()

    def load_cache(self) -> bool:
        if not os.path.exists(self.CACHE_FILE):
            return False
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_symbols = data.get("symbols", {})
            cached_token_to_symbol = data.get("token_to_symbol", {})
            self._symbols.update(cached_symbols)
            self._token_to_symbol.update(cached_token_to_symbol)
            self._cache_date = data.get("date")
            return True
        except Exception as e:
            log.warning("Could not load Angel One instrument cache: %s", e)
            return False

    def is_cache_fresh(self) -> bool:
        today = datetime.date.today().isoformat()
        return self._cache_date == today and len(self._symbols) > 20

    def refresh_daily_cache(self) -> bool:
        """Downloads full ScripMaster and filters for NSE/BSE equities and indices."""
        with self._lock:
            if self.is_cache_fresh():
                return True
            try:
                res = None
                for url in (self.SCRIP_URL_PRIMARY, self.SCRIP_URL_BACKUP):
                    try:
                        r = requests.get(url, timeout=30, verify=certifi.where())
                        if r.status_code == 200:
                            res = r.json()
                            break
                    except Exception as e:
                        log.debug("Scrip master fetch failed from %s: %s", url, e)
                if not res or not isinstance(res, list):
                    return False

                symbols: Dict[str, Dict[str, Any]] = dict(self.BOOTSTRAP_MAP)
                token_to_symbol: Dict[str, str] = {v["token"]: k for k, v in self.BOOTSTRAP_MAP.items()}

                for item in res:
                    exch = item.get("exch_seg")
                    sym = item.get("symbol", "")
                    token = item.get("token", "")
                    if not token:
                        continue
                    if exch == "NSE" and sym.endswith("-EQ"):
                        base = sym[:-3]
                        symbols[base] = {"token": token, "tradingsymbol": sym, "exchange": "NSE", "exchangeType": 1}
                        token_to_symbol[token] = base
                    elif exch == "BSE" and sym == "SENSEX":
                        symbols["SENSEX"] = {"token": token, "tradingsymbol": sym, "exchange": "BSE", "exchangeType": 3}
                        token_to_symbol[token] = "SENSEX"

                today = datetime.date.today().isoformat()
                payload = {
                    "date": today,
                    "count": len(symbols),
                    "symbols": symbols,
                    "token_to_symbol": token_to_symbol
                }
                os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
                with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                self._symbols = symbols
                self._token_to_symbol = token_to_symbol
                self._cache_date = today
                log.info("Refreshed Angel One instrument master (%d symbols cached)", len(symbols))
                return True
            except Exception as e:
                log.warning("Failed to refresh Angel One instrument cache: %s", e)
                return False

    def resolve_symbol(self, raw_symbol: str) -> Optional[Dict[str, Any]]:
        """Maps symbol string or asset to token, exchange, and tradingsymbol."""
        sym = raw_symbol.upper().strip()
        # Clean Yahoo/NSE suffixes
        if sym.endswith(".NS") or sym.endswith(".BO"):
            sym = sym.split(".")[0]
        if sym == "^NSEI":
            sym = "NIFTY"
        elif sym == "^BSESN":
            sym = "SENSEX"
        elif sym == "^INDIAVIX":
            sym = "INDIAVIX"

        if sym in self._symbols:
            return self._symbols[sym]

        # Try dynamic lookup if cache not refreshed
        if not self.is_cache_fresh():
            self.refresh_daily_cache()
            if sym in self._symbols:
                return self._symbols[sym]
        return None

    def get_symbol_for_token(self, token: str) -> Optional[str]:
        return self._token_to_symbol.get(str(token))

    def get_active_token_list(self, symbols_list: List[str]) -> List[Dict[str, Any]]:
        """Builds tokenList grouped by exchangeType for SmartWebSocketV2."""
        by_exch: Dict[int, List[str]] = {}
        for s in symbols_list:
            info = self.resolve_symbol(s)
            if info:
                etype = info["exchangeType"]
                by_exch.setdefault(etype, []).append(info["token"])
        return [{"exchangeType": etype, "tokens": list(set(toks))} for etype, toks in by_exch.items()]


instrument_manager = SmartAPIInstrumentManager()


# ---------------------------------------------------------------------------
# Session & Authentication Manager
# ---------------------------------------------------------------------------
class SmartAPISessionManager:
    """Manages SmartConnect authenticated session in memory only with auto-relogin."""

    TOKEN_EXPIRY_SEC = 18 * 3600  # Proactively refresh after 18 hours

    def __init__(self):
        self._auth_token: Optional[str] = None
        self._feed_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._client: Optional[SmartConnect] = None
        self._login_time: float = 0.0
        self._lock = threading.Lock()
        self._login_failed: bool = False

    def invalidate(self):
        with self._lock:
            self._auth_token = None
            self._feed_token = None
            self._refresh_token = None
            self._client = None
            self._login_time = 0.0

    def login(self) -> bool:
        """Authenticates with Angel One using TOTP and generates session in memory."""
        with self._lock:
            creds = get_angel_credentials()
            if not all(creds.values()):
                self._login_failed = True
                store.kv_set("angel_one_status", "Angel One login failed (credentials not set in .env)")
                return False

            try:
                totp = pyotp.TOTP(creds["totp_secret"]).now()
                client = SmartConnect(api_key=creds["api_key"])
                session_data = client.generateSession(creds["client_id"], creds["pin"], totp)

                if not session_data or session_data.get("status") is False:
                    self._login_failed = True
                    msg = session_data.get("message", "Session generation rejected") if session_data else "Empty response"
                    log.warning("Angel One login failed: %s", msg)
                    store.kv_set("angel_one_status", "Angel One login failed")
                    return False

                data = session_data.get("data", {})
                jwt_token = data.get("jwtToken")
                if not jwt_token:
                    self._login_failed = True
                    store.kv_set("angel_one_status", "Angel One login failed")
                    return False

                feed_token = data.get("feedToken") or client.getfeedToken()
                refresh_token = data.get("refreshToken")

                # Store tokens in memory only
                self._auth_token = jwt_token
                self._feed_token = feed_token
                self._refresh_token = refresh_token
                self._client = client
                self._login_time = time.time()
                self._login_failed = False
                store.kv_set("angel_one_status", "connected")
                log.info("Angel One SmartAPI login successful (tokens kept in memory)")
                return True
            except Exception as e:
                self._login_failed = True
                log.warning("Angel One login exception: %s", type(e).__name__)
                store.kv_set("angel_one_status", "Angel One login failed")
                return False

    def get_client(self) -> Optional[SmartConnect]:
        """Returns active SmartConnect client, re-logging in if expired."""
        now = time.time()
        if self._client is None or (now - self._login_time > self.TOKEN_EXPIRY_SEC):
            if not self.login():
                return None
        return self._client

    def get_tokens(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Returns (auth_token, feed_token, client_id) for websocket connection."""
        if not self._auth_token or (time.time() - self._login_time > self.TOKEN_EXPIRY_SEC):
            if not self.login():
                return None, None, None
        creds = get_angel_credentials()
        return self._auth_token, self._feed_token, creds.get("client_id")


session_manager = SmartAPISessionManager()


# ---------------------------------------------------------------------------
# REST Quote Fetcher (First Quote Source for Indian Equities & Indices)
# ---------------------------------------------------------------------------
def q_angel_one(asset_or_symbol) -> float:
    """Fetches real-time LTP from Angel One SmartAPI REST endpoint."""
    sym = asset_or_symbol.get("name") if isinstance(asset_or_symbol, dict) else str(asset_or_symbol)
    if isinstance(asset_or_symbol, dict):
        # Prefer ticker base or name
        yf = asset_or_symbol.get("yf", "")
        if yf:
            sym = yf.split(".")[0]
        else:
            sym = asset_or_symbol.get("name", sym)

    info = instrument_manager.resolve_symbol(sym)
    if not info:
        raise ValueError(f"Unknown Angel One symbol: {sym}")

    client = session_manager.get_client()
    if client is None:
        raise RuntimeError("Angel One login failed; falling back to secondary source")

    try:
        res = client.ltpData(info["exchange"], info["tradingsymbol"], info["token"])
        if not res or res.get("status") is False:
            err = res.get("errorcode", "")
            if err in ("AG8001", "AG8002", "AG8003", "TokenException"):
                session_manager.invalidate()
                client = session_manager.get_client()
                if client:
                    res = client.ltpData(info["exchange"], info["tradingsymbol"], info["token"])
        if res and res.get("status") is True and res.get("data"):
            ltp = float(res["data"].get("ltp") or 0.0)
            if ltp > 0:
                return ltp
        raise ValueError(f"Angel One quote returned invalid data: {res.get('message') if res else 'Empty'}")
    except Exception as e:
        log.debug("Angel One REST ltpData failed for %s: %s", sym, e)
        raise e


# ---------------------------------------------------------------------------
# WebSocket V2 Streaming with Secure TLS & Key Rejection Detection
# ---------------------------------------------------------------------------
class SecureSmartWebSocketV2(SmartWebSocketV2):
    """Enforces strict TLS verification via certifi root certificates."""

    def connect(self):
        headers = {
            "Authorization": self.auth_token,
            "x-api-key": self.api_key,
            "x-client-code": self.client_code,
            "x-feed-token": self.feed_token
        }
        try:
            self.wsapp = websocket.WebSocketApp(
                self.ROOT_URI,
                header=headers,
                on_open=self._on_open,
                on_error=self._on_error,
                on_close=self._on_close,
                on_data=self._on_data,
                on_ping=self._on_ping,
                on_pong=self._on_pong
            )
            # Strictly verify SSL certificate bundle
            self.wsapp.run_forever(
                sslopt={"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": certifi.where()},
                ping_interval=self.HEART_BEAT_INTERVAL
            )
        except Exception as e:
            logger.error("Error occurred during Secure WebSocket connection: %s", e)
            raise e


class SmartAPIStreamManager:
    """Manages background WebSocket connection for real-time tick streaming."""

    TRADING_KEY_WARNING = (
        "Angel One rejected key: SmartWebSocketV2 requires a 'Market Feeds'-type app key. "
        "Trading-type keys cannot stream feeds. Please create a Market Feeds-type app on smartapi.angelbroking.com."
    )

    def __init__(self):
        self._sws: Optional[SecureSmartWebSocketV2] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._subscribed_symbols = [
            "NIFTY", "SENSEX", "INDIAVIX", "RELIANCE", "TCS", "INFY", "HDFCBANK",
            "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "LT", "KOTAKBANK"
        ]
        self._running = False
        self._last_tick_time = 0.0

    def start(self):
        if self._running:
            return
        if not has_angel_credentials():
            log.info("Angel One credentials not configured; websocket stream disabled")
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AngelSmartStream")
        self._thread.start()
        log.info("Started Angel One SmartStream background worker")

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._sws:
            try:
                self._sws.close_connection()
            except Exception:
                pass

    def _run_loop(self):
        backoff = 2
        while not self._stop_event.is_set():
            auth_token, feed_token, client_id = session_manager.get_tokens()
            creds = get_angel_credentials()
            if not auth_token or not feed_token or not client_id:
                log.warning("Angel One credentials or session unavailable; retrying in %ds", backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            try:
                sws = SecureSmartWebSocketV2(
                    auth_token=auth_token,
                    api_key=creds["api_key"],
                    client_code=client_id,
                    feed_token=feed_token,
                    max_retry_attempt=3,
                    retry_strategy=1,
                    retry_delay=2,
                    retry_multiplier=2,
                    retry_duration=10
                )
                self._sws = sws

                def on_open(wsapp):
                    log.info("Angel One SmartWebSocket opened; subscribing to symbols")
                    token_list = instrument_manager.get_active_token_list(self._subscribed_symbols)
                    sws.subscribe(correlation_id="oracle_ticks", mode=1, token_list=token_list)

                def on_data(wsapp, message):
                    if isinstance(message, dict):
                        self._process_tick(message)

                def on_error(wsapp, error):
                    err_str = str(error).lower()
                    log.warning("Angel One SmartWebSocket error: %s", error)
                    if any(term in err_str for term in ["market feeds", "trading app", "invalid api key", "401", "unauthorized"]):
                        log.error(self.TRADING_KEY_WARNING)
                        store.kv_set("angel_one_status", self.TRADING_KEY_WARNING)

                def on_close(wsapp):
                    log.info("Angel One SmartWebSocket connection closed")

                sws.on_open = on_open
                sws.on_data = on_data
                sws.on_error = on_error
                sws.on_close = on_close

                sws.connect()
                backoff = 2
            except Exception as e:
                err_str = str(e).lower()
                log.warning("Angel One WebSocket connection loop failed: %s", e)
                if any(term in err_str for term in ["market feeds", "trading app", "invalid api key", "401"]):
                    store.kv_set("angel_one_status", self.TRADING_KEY_WARNING)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _process_tick(self, msg: Dict[str, Any]):
        """Parses tick message, divides price by 100.0, and saves to quote store."""
        token = str(msg.get("token", ""))
        raw_price = msg.get("last_traded_price")
        if not token or raw_price is None:
            return

        symbol = instrument_manager.get_symbol_for_token(token)
        if not symbol:
            return

        try:
            # Prices arrive as integer in paise, divide by 100.0 to convert to rupees
            price = float(raw_price) / 100.0
            if price > 0:
                store.save_quote(symbol, price, source="Angel One")
                self._last_tick_time = time.time()
        except Exception as e:
            log.debug("Tick conversion error for token %s: %s", token, e)


stream_manager = SmartAPIStreamManager()
