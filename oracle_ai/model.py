"""Candle model: walk-forward training + an untouched holdout gate.

Why a holdout gate instead of "retrain until it passes":
  Re-running until a test passes is p-hacking: some random model WILL pass eventually.
  Here configs are chosen on development data only (walk-forward). The best config is then
  scored ONCE on the final 20% of history it never saw. That single score is the gate.
  If the gate fails, ORACLE says "no proven edge" instead of pretending.
"""
import json
import logging
import math
import os
import time

import joblib
import numpy as np
from scipy.stats import binomtest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import log_loss, roc_auc_score

import config
import features
import store

log = logging.getLogger("oracle.model")
_cache = {}


def _path(symbol, interval, h):
    return os.path.join(config.MODEL_DIR, f"{symbol}_{interval}_h{h}.joblib")


def _gate_log(entry):
    entry["t"] = int(time.time())
    with open(config.GATE_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=float) + "\n")


def _fit(X, y, cfg):
    clf = HistGradientBoostingClassifier(
        max_depth=cfg["depth"], learning_rate=cfg["lr"], max_iter=cfg["iters"],
        l2_regularization=1.0, min_samples_leaf=30, random_state=0)
    clf.fit(X, y)
    return clf


def _dataset(candles, h, interval="1d"):
    """Closed candles -> aligned (X, y, fwd, feature_names, latest_feature_row)."""
    df = store.closed_only(candles, interval)
    f = features.build_features(df)
    y, fwd = features.make_labels(df, h)
    ok_feat = f.notna().all(axis=1)
    latest = f[ok_feat].iloc[[-1]] if ok_feat.any() else None
    valid = ok_feat & y.notna()
    X = f[valid].values.astype(float)
    return X, y[valid].values.astype(int), fwd[valid].values, list(f.columns), latest, df


def evaluate(p, y, fwd, h, cost):
    """Metrics on out-of-sample probabilities. Significance tests use every h-th sample so
    overlapping forward windows do not inflate the sample size."""
    n = len(y)
    if n < 20:
        return {"n": n, "insufficient": True}
    pred = (p > 0.5).astype(int)
    acc = float((pred == y).mean())
    base = float(max(y.mean(), 1 - y.mean()))
    auc = float(roc_auc_score(y, p)) if len(set(y)) > 1 else 0.5
    pc = np.clip(p, 1e-4, 1 - 1e-4)
    ll = float(log_loss(y, pc, labels=[0, 1]))
    prior = float(y.mean())
    ll_base = float(log_loss(y, np.full(n, np.clip(prior, 1e-4, 1 - 1e-4)), labels=[0, 1]))
    sub = slice(None, None, max(1, h))
    ys, ps = y[sub], pred[sub]
    k, ns = int((ys == ps).sum()), len(ys)
    pval = float(binomtest(k, ns, float(max(ys.mean(), 1 - ys.mean())), alternative="greater").pvalue)
    sig = np.where(p > 0.5 + 0.02, 1.0, np.where(p < 0.5 - 0.02, -1.0, 0.0))
    pnl = (sig * fwd - 2 * cost * np.abs(sig))[sub]
    traded = np.abs(sig[sub]) > 0
    net_mean = float(pnl.mean())
    net_t = float(pnl.mean() / (pnl.std(ddof=1) / math.sqrt(len(pnl)))) if len(pnl) > 2 and pnl.std() > 0 else 0.0
    return {"n": n, "n_independent": ns, "acc": acc, "base_acc": base, "auc": auc, "logloss": ll,
            "logloss_base": ll_base, "binom_p": pval, "net_mean_per_trade": net_mean, "net_t": net_t,
            "trade_rate": float(traded.mean()), "hit_when_traded": float(
                ((pnl + 2 * cost) > 0)[traded].mean()) if traded.any() else None}


def walk_forward(X, y, cfg, h, n_folds=5, start_frac=0.4):
    n = len(y)
    start = int(n * start_frac)
    step = max(1, (n - start) // n_folds)
    probs, idx = [], []
    for k in range(n_folds):
        te0 = start + k * step
        te1 = n if k == n_folds - 1 else te0 + step
        tr_end = te0 - h                       # embargo: labels look h candles ahead
        if tr_end < 100 or te0 >= n:
            continue
        clf = _fit(X[:tr_end], y[:tr_end], cfg)
        probs.append(clf.predict_proba(X[te0:te1])[:, 1])
        idx.append(np.arange(te0, te1))
    if not probs:
        return None, None
    return np.concatenate(probs), np.concatenate(idx)


def gate_check(m):
    """Return (passed, reasons). All conditions must hold on the holdout."""
    reasons = []
    if m.get("insufficient") or m["n"] < config.GATE_MIN_OOS:
        reasons.append(f"holdout too small ({m['n']} < {config.GATE_MIN_OOS})")
        return False, reasons
    if not m["binom_p"] < config.GATE_ALPHA:
        reasons.append(f"accuracy {m['acc']:.3f} not significantly above baseline {m['base_acc']:.3f} (p={m['binom_p']:.3f})")
    if m["auc"] < config.GATE_MIN_AUC:
        reasons.append(f"AUC {m['auc']:.3f} < {config.GATE_MIN_AUC}")
    if m["net_mean_per_trade"] <= 0:
        reasons.append("no profit after trading costs")
    return (not reasons), reasons


def train(symbol, interval="1d", horizons=None, verbose=False):
    """Train one model per horizon. Returns {h: report}."""
    horizons = horizons or config.HORIZONS
    asset = config.ASSETS[symbol]
    cost = config.COST_PER_SIDE.get(asset["cls"], 0.0005)
    candles = store.load_candles(symbol, interval)
    out = {}
    for h in horizons:
        X, y, fwd, cols, latest, df = _dataset(candles, h, interval)
        report = {"symbol": symbol, "interval": interval, "horizon": h, "n_bars": int(len(df)),
                  "n_samples": int(len(y))}
        if len(df) < config.MIN_BARS or len(y) < 300:
            report.update(status="insufficient_data", passed=False,
                          reasons=[f"only {len(df)} closed candles; need {config.MIN_BARS}"])
            store.save_model_meta(symbol, interval, h, False, report)
            _gate_log({"symbol": symbol, "h": h, "event": "skip", **report})
            out[h] = report
            continue

        n = len(y)
        dev_end = int(n * (1 - config.HOLDOUT_FRAC))
        Xd, yd, fd = X[:dev_end], y[:dev_end], fwd[:dev_end]
        best, best_score = None, -1.0
        for cfg in config.CONFIGS:
            p, idx = walk_forward(Xd, yd, cfg, h)
            if p is None:
                continue
            m = evaluate(p, yd[idx], fd[idx], h, cost)
            score = m.get("auc", 0.5)
            _gate_log({"symbol": symbol, "h": h, "event": "dev_trial", "cfg": cfg, "dev_auc": score,
                       "dev_acc": m.get("acc")})
            if score > best_score:
                best, best_score = cfg, score
        best = best or config.CONFIGS[0]

        # single look at the holdout, with an embargo of h candles after development data
        clf_dev = _fit(Xd[: max(100, dev_end - h)], yd[: max(100, dev_end - h)], best)
        Xh, yh, fh = X[dev_end:], y[dev_end:], fwd[dev_end:]
        ph = clf_dev.predict_proba(Xh)[:, 1]
        hold = evaluate(ph, yh, fh, h, cost)
        passed, reasons = gate_check(hold)

        final = _fit(X, y, best)                     # production model uses all history
        report.update(status="trained", passed=bool(passed), reasons=reasons, config=best,
                      dev_auc=best_score, holdout=hold, feature_names=cols,
                      trained_through_ts=int(df.ts.iloc[-1]))
        joblib.dump({"model": final, "cfg": best, "cols": cols, "report": report}, _path(symbol, interval, h))
        _cache.pop((symbol, interval, h), None)
        store.save_model_meta(symbol, interval, h, passed, {k: v for k, v in report.items() if k != "feature_names"})
        _gate_log({"symbol": symbol, "h": h, "event": "gate", "passed": bool(passed), "reasons": reasons,
                   "holdout": hold})
        if verbose:
            print(f"{symbol} h={h}: {'PASS' if passed else 'FAIL'} acc={hold.get('acc', 0):.3f} "
                  f"base={hold.get('base_acc', 0):.3f} auc={hold.get('auc', 0):.3f} p={hold.get('binom_p', 1):.3f}")
        out[h] = report
    return out


def load_model(symbol, interval, h):
    key = (symbol, interval, h)
    if key not in _cache:
        p = _path(symbol, interval, h)
        _cache[key] = joblib.load(p) if os.path.exists(p) else None
    return _cache[key]


def forecast(symbol, interval="1d", horizons=None):
    """Direction probabilities + volatility price ranges for each horizon. Always returns a result
    when candles exist; says plainly when the model has no proven edge."""
    horizons = horizons or config.HORIZONS
    candles = store.load_candles(symbol, interval)
    df = store.closed_only(candles, interval)
    if len(df) < 60:
        return {"symbol": symbol, "available": False, "reason": f"only {len(df)} stored candles"}
    last = float(df.close.iloc[-1])
    r = np.log(df.close).diff().dropna()
    sigma1 = float(r.ewm(span=20).std().iloc[-1]) if len(r) > 20 else float(r.std())
    f = features.build_features(df)
    out = {"symbol": symbol, "available": True, "last_close": last, "last_close_ts": int(df.ts.iloc[-1]),
           "interval": interval, "daily_vol": sigma1, "horizons": {}}
    for h in horizons:
        s = sigma1 * math.sqrt(h)
        item = {"h": h, "p_up": 0.5, "model": "none", "gate_passed": False,
                "range68": [last * math.exp(-s), last * math.exp(s)],
                "range95": [last * math.exp(-1.96 * s), last * math.exp(1.96 * s)]}
        art = load_model(symbol, interval, h)
        if art is not None:
            row = f.iloc[[-1]][art["cols"]]
            if not row.isna().all(axis=None):
                p = float(art["model"].predict_proba(row.values.astype(float))[0, 1])
                lo, hi = config.PROB_CLIP
                item["p_up"] = float(min(hi, max(lo, p)))
                item["model"] = "candle model"
                rep = art["report"]
                item["gate_passed"] = bool(rep.get("passed"))
                hold = rep.get("holdout") or {}
                item["holdout"] = {k: hold.get(k) for k in ("acc", "base_acc", "auc", "binom_p", "n")}
                item["gate_reasons"] = rep.get("reasons", [])
        out["horizons"][h] = item
    return out
