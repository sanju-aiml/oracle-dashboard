"""Backtesting with the guards the surveys say most papers skip: purged walk-forward splits, transaction
costs, institutional baselines (buy&hold, UCRP, inverse-vol / MVO-lite), risk-adjusted metrics."""
from __future__ import annotations
import numpy as np
import pandas as pd

def walk_forward_splits(dates: pd.Series, n_splits=5, min_train_frac=0.4, horizon=5, embargo=5):
    """Anchored expanding-window splits. Train end is purged by `horizon+embargo` rows so labels that look
    `horizon` days ahead cannot overlap the test window."""
    u = np.sort(pd.Series(dates).unique())
    n = len(u)
    start = int(n * min_train_frac)
    step = (n - start) // n_splits
    for i in range(n_splits):
        te0 = start + i * step
        te1 = n if i == n_splits - 1 else te0 + step
        tr_end = max(0, te0 - horizon - embargo)
        yield u[:tr_end], u[te0:te1]

def metrics(returns: pd.Series, periods=252, rf=0.0) -> dict:
    r = returns.dropna()
    if len(r) < 5 or r.std() == 0:
        return {"sharpe": 0.0, "sortino": 0.0, "cagr": 0.0, "max_dd": 0.0, "vol": 0.0, "n": len(r)}
    ex = r - rf / periods
    dd_std = ex[ex < 0].std()
    eq = (1 + r).cumprod()
    years = len(r) / periods
    return {
        "sharpe": float(ex.mean() / ex.std() * np.sqrt(periods)),
        "sortino": float(ex.mean() / dd_std * np.sqrt(periods)) if dd_std and dd_std > 0 else 0.0,
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1) if years > 0 and eq.iloc[-1] > 0 else -1.0,
        "max_dd": float((eq / eq.cummax() - 1).min()),
        "vol": float(r.std() * np.sqrt(periods)),
        "n": int(len(r)),
    }

def deflated_sharpe(sr: float, n_obs: int, n_trials: int, skew=0.0, kurt=3.0) -> float:
    """Bailey & Lopez de Prado deflated Sharpe probability: chance the Sharpe is real after `n_trials`
    attempts (the 'train until it passes' loop is multiple testing, so this MUST be applied)."""
    from scipy.stats import norm
    if n_obs < 3:
        return 0.0
    emc = 0.5772156649
    sr_daily = sr / np.sqrt(252)
    z = norm.ppf(1 - 1 / max(n_trials, 2))
    z2 = norm.ppf(1 - 1 / (max(n_trials, 2) * np.e))
    sr0 = (1 - emc) * z + emc * z2
    sr0 = sr0 / np.sqrt(n_obs)                                    # expected max SR under the null (daily units)
    denom = np.sqrt(max(1e-12, 1 - skew * sr_daily + (kurt - 1) / 4 * sr_daily ** 2))
    return float(norm.cdf((sr_daily - sr0) * np.sqrt(n_obs - 1) / denom))

def run_long_short(signal: pd.DataFrame, fwd1: pd.DataFrame, cost_bps=10.0, max_gross=1.0) -> pd.Series:
    """signal: date x symbol in [-1, 1] (position decided at close t). fwd1: next-day return per symbol.
    Equal risk budget across symbols, turnover-based costs."""
    sig = signal.reindex_like(fwd1).fillna(0.0)
    gross = sig.abs().sum(axis=1).replace(0, np.nan)
    w = sig.div(gross, axis=0).mul(max_gross).fillna(0.0)
    turn = w.diff().abs().sum(axis=1).fillna(w.abs().sum(axis=1))
    gross_ret = (w * fwd1).sum(axis=1)
    return gross_ret - turn * cost_bps / 1e4

def buy_and_hold(fwd1: pd.DataFrame) -> pd.Series:
    return fwd1.mean(axis=1)                                      # equal-weight, daily rebalanced == UCRP

def inverse_vol(fwd1: pd.DataFrame, window=63) -> pd.Series:
    vol = fwd1.rolling(window).std().shift(1)
    w = (1 / vol).div((1 / vol).sum(axis=1), axis=0)
    return (w * fwd1).sum(axis=1)

def mvo_lite(fwd1: pd.DataFrame, window=252, ridge=1e-3) -> pd.Series:
    """Long-only-ish mean-variance baseline (Sood et al. critique: beat MVO, not just buy&hold)."""
    out = {}
    idx = fwd1.index
    for i in range(window, len(idx)):
        hist = fwd1.iloc[i - window:i].dropna(axis=1, how="any")
        if hist.shape[1] < 2:
            continue
        mu, cov = hist.mean().values, hist.cov().values + ridge * np.eye(hist.shape[1])
        w = np.linalg.solve(cov, mu)
        w = np.clip(w, 0, None)
        w = w / w.sum() if w.sum() > 0 else np.ones_like(w) / len(w)
        out[idx[i]] = float((fwd1.iloc[i][hist.columns].values * w).sum())
    return pd.Series(out)
