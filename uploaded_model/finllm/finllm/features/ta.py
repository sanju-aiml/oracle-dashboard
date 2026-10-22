"""Features + labels. Techniques taken from the papers:
 - DeepLOB (1808.03668): rolling z-score using only the previous N days; smoothed-mean label with a dead-zone alpha.
 - Millea DRL survey: Sharpe/Sortino/differential-Sharpe as reward/metrics, multi-timescale inputs.
 - LLM-RL survey: strict temporal alignment of text and prices (no look-ahead), non-stationarity handling.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

def rolling_zscore(x: pd.Series, window: int = 5 * 63) -> pd.Series:
    """z-score from PAST data only (shifted by 1): adapts to regime shifts, cannot leak the future."""
    m = x.rolling(window, min_periods=window // 4).mean().shift(1)
    s = x.rolling(window, min_periods=window // 4).std().shift(1)
    return (x - m) / s.replace(0, np.nan)

def rsi(close: pd.Series, n=14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def atr(h, l, c, n=14) -> pd.Series:
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """df: single-symbol OHLCV sorted by date. Every feature at row t uses data <= t."""
    d = df.copy().sort_values("date").reset_index(drop=True)
    c = d["close"]
    r = np.log(c).diff()
    f = pd.DataFrame({"date": d["date"], "symbol": d["symbol"], "close": c})
    for k in (1, 5, 10, 21, 63, 126, 252):                       # multi-timescale returns
        f[f"ret_{k}"] = np.log(c).diff(k)
    for k in (10, 21, 63):
        f[f"vol_{k}"] = r.rolling(k).std() * np.sqrt(252)
    for k in (10, 20, 50, 200):
        f[f"dist_sma{k}"] = c / c.rolling(k).mean() - 1
    f["rsi14"] = rsi(c)
    f["atr_pct"] = atr(d["high"], d["low"], c) / c
    f["vol_ratio"] = d["volume"].replace(0, np.nan) / d["volume"].replace(0, np.nan).rolling(21).mean()
    f["dd_252"] = c / c.rolling(252, min_periods=20).max() - 1
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    f["macd_hist"] = (macd - macd.ewm(span=9).mean()) / c
    for col in [x for x in f.columns if x.startswith(("ret_", "vol_", "dist_", "macd"))]:
        f[col + "_z"] = rolling_zscore(f[col])
    return f

def make_labels(close: pd.Series, horizon: int = 5, alpha: float | None = None) -> pd.DataFrame:
    """DeepLOB-style label: l = (mean(p[t+1..t+k]) / p[t]) - 1, dead-zone alpha -> {down=0, flat=1, up=2}.
    Uses FUTURE prices by design: ONLY ever used as a target, never as a feature. alpha defaults to
    0.25*rolling daily vol*sqrt(h), computed from the past."""
    fut = sum(close.shift(-i) for i in range(1, horizon + 1)) / horizon
    l = fut / close - 1
    if alpha is None:
        a = (np.log(close).diff().rolling(63).std().shift(1) * np.sqrt(horizon) * 0.25)
    else:
        a = pd.Series(alpha, index=close.index)
    y = pd.Series(1, index=close.index)
    y[l > a] = 2
    y[l < -a] = 0
    y[l.isna() | a.isna()] = -1                                   # unknown -> dropped
    return pd.DataFrame({"fwd_ret": l, "label": y, "alpha": a})
