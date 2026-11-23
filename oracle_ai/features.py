"""Candle -> feature engineering. Pure pandas/numpy, no look-ahead: every feature at row t
uses only candles up to and including t."""
import numpy as np
import pandas as pd


def _rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def build_features(df):
    """df: columns ts, open, high, low, close, volume (sorted by ts). Returns DataFrame of features."""
    o, h, l, c, v = df.open, df.high, df.low, df.close, df.volume
    lc = np.log(c)
    r = lc.diff()
    f = pd.DataFrame(index=df.index)
    for k in (1, 2, 3, 5, 10, 20):
        f[f"ret{k}"] = lc.diff(k)
    for k in (5, 10, 20):
        f[f"vol{k}"] = r.rolling(k).std()
    f["vol_ratio"] = f["vol5"] / f["vol20"].replace(0, np.nan)
    f["rsi14"] = _rsi(c, 14)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = (ema12 - ema26) / c
    f["macd"] = macd
    f["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    f["sma10r"] = c / c.rolling(10).mean() - 1
    f["sma50r"] = c / c.rolling(50).mean() - 1
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    f["atr14"] = tr.rolling(14).mean() / c
    rng = (h - l).replace(0, np.nan)
    f["body"] = (c - o) / rng
    f["upper_wick"] = (h - np.maximum(o, c)) / rng
    f["lower_wick"] = (np.minimum(o, c) - l) / rng
    f["close_pos"] = (c - l) / rng
    f["gap"] = np.log(o / prev)
    m, s = c.rolling(20).mean(), c.rolling(20).std()
    f["bbp"] = (c - m) / (2 * s.replace(0, np.nan))
    if float(v.sum()) > 0:
        f["volz"] = (v - v.rolling(20).mean()) / v.rolling(20).std().replace(0, np.nan)
    else:
        f["volz"] = 0.0
    f["dow"] = pd.to_datetime(df.ts, unit="s").dt.dayofweek.astype(float)
    return f.replace([np.inf, -np.inf], np.nan)


def make_labels(df, h):
    """Forward log return over h candles and the up/down label (NaN-safe)."""
    fwd = np.log(df.close.shift(-h) / df.close)
    y = (fwd > 0).astype(float).where(fwd.notna())
    return y, fwd
