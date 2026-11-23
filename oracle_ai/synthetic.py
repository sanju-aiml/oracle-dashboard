"""Synthetic candle generator. ONLY for tests and offline demos; never mixed into live answers."""
import numpy as np
import pandas as pd


def make_candles(n=2000, seed=0, phi=0.0, vol=0.02, start_price=100.0, start_ts=1_420_070_400):
    """Daily candles. phi = lag-1 autocorrelation of returns (0 => pure random walk, no edge)."""
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    v = np.full(n, vol)
    for t in range(1, n):
        v[t] = 0.9 * v[t - 1] + 0.1 * vol * (1 + 0.5 * abs(rng.normal()))
        r[t] = phi * r[t - 1] + rng.normal() * v[t]
    close = start_price * np.exp(np.cumsum(r))
    open_ = np.concatenate([[start_price], close[:-1]]) * np.exp(rng.normal(0, v * 0.1))
    hi = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, v * 0.4)))
    lo = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, v * 0.4)))
    return pd.DataFrame({"ts": start_ts + 86400 * np.arange(n), "open": open_, "high": hi, "low": lo,
                         "close": close, "volume": rng.integers(1_000, 100_000, n).astype(float)})
