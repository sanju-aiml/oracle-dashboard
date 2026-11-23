"""Multi-provider quote router. Fixes the three failure modes seen in the ORACLE UI:
 1. one provider (TwelveData free) lacks NSE/BSE, silver, gas  -> per-asset-class provider CHAINS with fallback
 2. a dead/rate-limited provider hangs or blanks the card       -> circuit breaker + timeouts, next provider is tried
 3. stale numbers shown as 'LIVE'                               -> every quote carries its own market timestamp and an
                                                                   honest status: live | delayed | last_close | unavailable
No synthetic fallback, ever. Env keys: FINNHUB_KEY, TWELVEDATA_KEY (optional)."""
from __future__ import annotations
import os, time
from dataclasses import dataclass, field, asdict
from typing import Callable
import pandas as pd

class DataUnavailable(Exception):
    pass

@dataclass
class Quote:
    symbol: str
    price: float
    ts: pd.Timestamp                 # time of the MARKET data (UTC), not time of fetch
    source: str
    declared_delay_s: int = 0        # provider's own stated delay (Yahoo NSE/BSE ~15 min)
    status: str = ""
    age_s: float = 0.0
    warnings: list = field(default_factory=list)
    prev_close: float | None = None
    def to_dict(self):
        d = asdict(self); d["ts"] = str(self.ts)
        d["change_pct"] = round((self.price / self.prev_close - 1) * 100, 3) if self.prev_close else None
        return d

ALIASES = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "SENSEX": "^BSESN", "BANKNIFTY": "^NSEBANK", "GOLD": "GC=F", "SILVER": "SI=F",
           "OIL": "BZ=F", "BRENT": "BZ=F", "WTI": "CL=F", "NATURALGAS": "NG=F", "NATGAS": "NG=F", "BTC/USD": "BTC-USD",
           "ETH/USD": "ETH-USD", "USD/INR": "USDINR=X", "BTC": "BTC-USD", "ETH": "ETH-USD"}
INTERVALS = {"1min": ("1m", "5d"), "5min": ("5m", "1mo"), "15min": ("15m", "1mo"), "30min": ("30m", "1mo"),
             "1h": ("60m", "3mo"), "1day": ("1d", "2y"), "1week": ("1wk", "5y")}

def resolve(name: str) -> str:
    """UI names (NIFTY, SENSEX, GOLD, BRENT, NATURALGAS, BTC/USD) -> tradable tickers."""
    n = (name or "").upper().replace(" ", "").replace("_", "")
    return ALIASES.get(n, (name or "").upper().strip())

def df_to_candles(df: pd.DataFrame, n: int) -> list[dict]:
    """TwelveData-compatible shape: newest first, string fields."""
    d = df.dropna(subset=["Close"]).tail(n).iloc[::-1]
    return [{"datetime": str(pd.Timestamp(i)), "open": f"{r.Open:.4f}", "high": f"{r.High:.4f}", "low": f"{r.Low:.4f}",
             "close": f"{r.Close:.4f}", "volume": str(int(r.Volume)) if r.Volume == r.Volume else "0"} for i, r in d.iterrows()]

def ohlcv(sym: str, interval: str = "1day", n: int = 60) -> dict:
    """Candles from Yahoo (free). Raises DataUnavailable instead of inventing data."""
    import yfinance as yf
    sym = resolve(sym)
    iv, per = INTERVALS.get(interval, INTERVALS["1day"])
    df = yf.Ticker(sym).history(period=per, interval=iv)
    if df.empty: raise DataUnavailable(f"yahoo: no candles for {sym}")
    c = df_to_candles(df, n)
    return {"symbol": sym, "interval": interval, "candles": c, "candle_count": len(c), "source": "yahoo",
            "last_ts": c[0]["datetime"], "declared_delay_s": 900 if classify(sym) == "india" else 0}

def classify(sym: str) -> str:
    s = sym.upper()
    if s.endswith((".NS", ".BO")) or s in ("^NSEI", "^BSESN", "^NSEBANK", "^INDIAVIX"): return "india"
    if s.endswith("-USD") or "/" in s and s.split("/")[0] in ("BTC", "ETH", "SOL", "BNB", "XRP"): return "crypto"
    if s.endswith("=X"): return "fx"
    if s.endswith("=F") or s in ("XAU/USD", "XAG/USD"): return "commodity"
    return "us"

# order matters: first healthy provider wins
DEFAULT_CHAINS = {
    "crypto": ["binance", "yahoo"],                 # free, truly realtime
    "india": ["broker", "yahoo"],                   # 'broker' = licensed NSE/BSE feed if you plug one in; Yahoo is ~15 min delayed
    "us": ["finnhub", "twelvedata", "yahoo"],
    "fx": ["twelvedata", "yahoo"],
    "commodity": ["twelvedata", "yahoo"],
}
LIVE_S = {"crypto": 30, "us": 90, "fx": 90, "commodity": 180, "india": 90}
DELAYED_S = 1200

# ---------------- concrete providers (need network; tested via fakes) ----------------
def yahoo(sym: str) -> Quote:
    import yfinance as yf
    t = yf.Ticker(sym)
    h = t.history(period="1d", interval="1m")
    if h.empty:
        h = t.history(period="7d", interval="1d")              # market closed -> honest last close
    if h.empty:
        raise DataUnavailable("yahoo: no data")
    ts = pd.Timestamp(h.index[-1]).tz_convert("UTC")
    prev = None
    try:
        d = t.history(period="7d", interval="1d")["Close"].dropna()
        same_day = len(d) and pd.Timestamp(d.index[-1]).date() == pd.Timestamp(h.index[-1]).date()
        prev = float(d.iloc[-2] if same_day and len(d) >= 2 else d.iloc[-1]) if len(d) else None
    except Exception:
        pass
    return Quote(sym, float(h["Close"].iloc[-1]), ts, "yahoo", 900 if classify(sym) == "india" else 0, prev_close=prev)

def binance(sym: str) -> Quote:
    import ccxt
    pair = sym.replace("-USD", "/USDT")
    tk = ccxt.binance({"timeout": 5000}).fetch_ticker(pair)
    return Quote(sym, float(tk["last"]), pd.Timestamp(tk["timestamp"], unit="ms", tz="UTC"), "binance", prev_close=tk.get("open"))

def finnhub(sym: str) -> Quote:
    import requests
    k = os.environ.get("FINNHUB_KEY")
    if not k or classify(sym) != "us": raise DataUnavailable("finnhub: no key / not US")
    j = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": sym, "token": k}, timeout=5).json()
    if not j.get("c") or not j.get("t"): raise DataUnavailable("finnhub: empty")
    return Quote(sym, float(j["c"]), pd.Timestamp(j["t"], unit="s", tz="UTC"), "finnhub")

TD_MAP = {"GC=F": "XAU/USD", "SI=F": "XAG/USD", "USDINR=X": "USD/INR", "EURINR=X": "EUR/INR"}
def twelvedata(sym: str) -> Quote:
    import requests
    k = os.environ.get("TWELVEDATA_KEY")
    if not k: raise DataUnavailable("twelvedata: no key")
    j = requests.get("https://api.twelvedata.com/quote", params={"symbol": TD_MAP.get(sym, sym), "apikey": k}, timeout=5).json()
    if j.get("status") == "error" or "close" not in j: raise DataUnavailable(f"twelvedata: {j.get('message', 'bad reply')}")
    return Quote(sym, float(j["close"]), pd.Timestamp(int(j["timestamp"]), unit="s", tz="UTC"), "twelvedata")

PROVIDERS = {"yahoo": yahoo, "binance": binance, "finnhub": finnhub, "twelvedata": twelvedata}
# plug a licensed Indian broker feed (Angel One SmartAPI / Upstox / Dhan / Kite) as PROVIDERS["broker"] = fn(sym)->Quote

# ---------------- router ----------------
class Router:
    def __init__(self, providers=None, chains=None, ttl_s=3, cooldown_s=60, fail_threshold=3, clock=time.time):
        self.p = dict(providers or PROVIDERS); self.chains = chains or DEFAULT_CHAINS
        self.ttl, self.cool, self.thr, self.clock = ttl_s, cooldown_s, fail_threshold, clock
        self.fails: dict[str, int] = {}; self.open_until: dict[str, float] = {}; self.cache: dict[str, tuple[float, Quote]] = {}

    def _try(self, name: str, sym: str) -> Quote:
        if self.clock() < self.open_until.get(name, 0): raise DataUnavailable(f"{name}: circuit open")
        try:
            q = self.p[name](sym)
            self.fails[name] = 0
            return q
        except Exception:
            self.fails[name] = self.fails.get(name, 0) + 1
            if self.fails[name] >= self.thr: self.open_until[name] = self.clock() + self.cool
            raise

    def _label(self, q: Quote, cls: str) -> Quote:
        q.age_s = max(0.0, self.clock() - q.ts.timestamp())
        if q.age_s > DELAYED_S: q.status = "last_close"
        elif q.declared_delay_s > 0 or q.age_s > LIVE_S[cls]: q.status = "delayed"
        else: q.status = "live"
        if q.status == "last_close": q.warnings.append("market closed or feed stale: showing last available price")
        if q.declared_delay_s: q.warnings.append(f"source delayed ~{q.declared_delay_s // 60} min")
        return q

    def get(self, sym: str, cross_check=False) -> Quote:
        c = self.cache.get(sym)
        if c and self.clock() - c[0] < self.ttl: return c[1]
        cls, errs, got = classify(sym), [], []
        for name in self.chains[cls]:
            if name not in self.p: continue
            try:
                got.append(self._label(self._try(name, sym), cls))
                if not cross_check: break
            except Exception as e:
                errs.append(f"{name}: {e}")
        if not got: raise DataUnavailable("; ".join(errs) or "no provider configured")
        q = got[0]
        if len(got) > 1 and abs(got[1].price / q.price - 1) > 0.01:
            q.warnings.append(f"{q.source} vs {got[1].source} differ by {abs(got[1].price / q.price - 1):.1%}")
        self.cache[sym] = (self.clock(), q)
        return q

    def get_safe(self, sym: str) -> dict:
        """For APIs/UI: never raises, never fabricates."""
        try: return self.get(sym).to_dict()
        except DataUnavailable as e: return {"symbol": sym, "status": "unavailable", "error": str(e)}

_default = Router()
def get_quote(sym: str) -> dict: return _default.get_safe(resolve(sym))
