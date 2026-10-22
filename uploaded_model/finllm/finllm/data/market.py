"""Live + historical market data: Indian stocks (NSE/BSE), indices, gold, oil, FX, crypto."""
from __future__ import annotations
import pandas as pd

try:
    import curl_cffi.requests as _c_req
    _orig_c_init = _c_req.Session.__init__
    def _safe_c_init(self, *args, **kwargs):
        kwargs.setdefault("verify", False)
        return _orig_c_init(self, *args, **kwargs)
    _c_req.Session.__init__ = _safe_c_init
except Exception:
    pass

UNIVERSE = {
    "india_equity": ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS",
                     "ITC.NS", "LT.NS", "BHARTIARTL.NS", "ADANIENT.NS", "^NSEI", "^BSESN", "^NSEBANK"],
    "global_equity": ["^GSPC", "^IXIC", "^DJI", "^FTSE", "^N225"],
    "commodities": ["GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F"],   # gold, silver, WTI, Brent, gas, copper
    "fx": ["USDINR=X", "EURINR=X", "DX-Y.NYB"],
    "rates_vol": ["^TNX", "^INDIAVIX"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD"],
}

def all_symbols() -> list[str]:
    return [s for v in UNIVERSE.values() for s in v]

def fetch_history(symbols: list[str], start="2010-01-01", end=None, interval="1d") -> pd.DataFrame:
    """Long-format OHLCV: columns [date, symbol, open, high, low, close, volume]. Uses adjusted prices."""
    import yfinance as yf
    frames = []
    for s in symbols:
        try:
            d = yf.download(s, start=start, end=end, interval=interval, auto_adjust=True, progress=False)
            if d.empty:
                continue
            d.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in d.columns]
            d = d.reset_index().rename(columns={"Date": "date", "Datetime": "date"})
            d["symbol"] = s
            frames.append(d[["date", "symbol", "open", "high", "low", "close", "volume"]])
        except Exception as e:  # keep going: one bad ticker must not kill a run
            print(f"[warn] {s}: {e}")
    if not frames:
        raise RuntimeError("no market data fetched")
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)

def fetch_crypto_live(symbol="BTC/USDT", exchange="binance", limit=200, timeframe="1m") -> pd.DataFrame:
    """Realtime candles via ccxt (public endpoints, no key needed)."""
    import ccxt
    ex = getattr(ccxt, exchange)()
    rows = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df.pop("ts"), unit="ms")
    return df

def fetch_quote(symbol: str) -> dict:
    """Latest quote for the agent's live-data tool."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    fi = t.fast_info
    return {"symbol": symbol, "price": float(fi["last_price"]), "prev_close": float(fi["previous_close"]),
            "currency": fi.get("currency"), "ts": pd.Timestamp.now("UTC").isoformat()}
