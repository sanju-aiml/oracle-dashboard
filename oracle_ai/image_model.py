"""Chart-image model.

Charts are rasterised into a 2-channel grid (channel 0 = up candles, channel 1 = down candles),
the same way for training data (rendered from ORACLE's own candles) and for user screenshots
(green/red candle pixels are extracted). One pooled model learns from all assets and is judged
on a time-based holdout with the same gate as the candle model.

Honest limit: a screenshot from another platform can differ in colours, zoom and indicators, so
the reader reports "could not read candles" instead of guessing when it cannot find them.
"""
import io
import json
import logging
import os
import time

import joblib
import numpy as np
from PIL import Image
from sklearn.decomposition import PCA
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline

import config
import model as cmodel
import store

log = logging.getLogger("oracle.image")
N_CANDLES, ROWS, PX = 24, 48, 2            # 24 candles x 2px wide = 48 columns, 48 rows
COLS = N_CANDLES * PX
MODEL_PATH = os.path.join(config.MODEL_DIR, "image_model.joblib")
_art = {}


def rasterize(o, h, l, c):
    """o,h,l,c arrays of the last N_CANDLES candles -> uint8 array (2, ROWS, COLS)."""
    lo, hi = float(np.min(l)), float(np.max(h))
    span = (hi - lo) or 1.0

    def row(p):
        return int(round((hi - p) / span * (ROWS - 1)))

    img = np.zeros((2, ROWS, COLS), dtype=np.uint8)
    for i in range(len(c)):
        ch = 0 if c[i] >= o[i] else 1
        x = i * PX
        img[ch, row(h[i]):row(l[i]) + 1, x + 1] = 1                         # wick
        top, bot = sorted((row(o[i]), row(c[i])))
        img[ch, top:bot + 1, x:x + PX] = 1                                   # body
    return img


def raster_from_image(pil_img):
    """Screenshot -> raster, or (None, reason). Looks for green (up) and red (down) candle pixels."""
    a = np.asarray(pil_img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    up = (g > r + 40) & (g > b + 15)
    down = (r > g + 50) & (r > b + 40)
    union = up | down
    if union.sum() < 200:
        return None, "Could not find green/red candles. Use a candlestick chart with green (up) and red (down) candles."
    cols = union.any(axis=0)
    runs, start = [], None
    for x, v in enumerate(cols):
        if v and start is None:
            start = x
        if not v and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(cols)))
    runs = [rn for rn in runs if rn[1] - rn[0] >= 1]
    if len(runs) < 8:
        return None, "Found fewer than 8 separate candles. Zoom out a little so at least 8 candles are visible."
    runs = runs[-N_CANDLES:]
    x0, x1 = runs[0][0], runs[-1][1]
    rows_any = union[:, x0:x1].any(axis=1)
    ys = np.where(rows_any)[0]
    y0, y1 = ys.min(), ys.max() + 1
    out = np.zeros((2, ROWS, COLS), dtype=np.uint8)
    for ch, m in enumerate((up, down)):
        crop = (m[y0:y1, x0:x1] * 255).astype(np.uint8)
        small = Image.fromarray(crop).resize((COLS, ROWS), Image.BOX)
        out[ch] = (np.asarray(small) > 40).astype(np.uint8)
    note = None if len(runs) == N_CANDLES else f"only {len(runs)} candles visible; accuracy is lower"
    return out, note


def _windows(df, h, stride=2, max_samples=700):
    d = store.closed_only(df, "1d")
    o, hi, lo, c = (d[k].values for k in ("open", "high", "low", "close"))
    X, y, ts, fwd = [], [], [], []
    idx = list(range(N_CANDLES, len(d) - h, stride))[-max_samples:]
    for t in idx:
        s = slice(t - N_CANDLES, t)
        X.append(rasterize(o[s], hi[s], lo[s], c[s]).ravel())
        f = float(np.log(c[t - 1 + h] / c[t - 1]))
        y.append(int(f > 0))
        fwd.append(f)
        ts.append(int(d.ts.iloc[t - 1]))
    return X, y, ts, fwd


def train(symbols=None, h=1, extra_labeled=True):
    symbols = symbols or list(config.ASSETS)
    X, y, ts, fwd, cost = [], [], [], [], []
    for sym in symbols:
        df = store.load_candles(sym, "1d")
        if len(df) < config.MIN_BARS:
            continue
        a, b, c_, d_ = _windows(df, h)
        X += a; y += b; ts += c_; fwd += d_
        cost += [config.COST_PER_SIDE.get(config.ASSETS[sym]["cls"], 0.0005)] * len(a)
    if len(y) < 600:
        rep = {"status": "insufficient_data", "passed": False, "n": len(y),
               "reasons": [f"need 600+ chart samples, have {len(y)}"]}
        cmodel._gate_log({"event": "image_skip", **rep})
        return rep
    X = np.asarray(X, dtype=np.uint8)
    y, ts, fwd, cost = map(np.asarray, (y, ts, fwd, cost))
    order = np.argsort(ts)
    X, y, ts, fwd, cost = X[order], y[order], ts[order], fwd[order], cost[order]
    cut = ts[int(len(ts) * (1 - config.HOLDOUT_FRAC))]
    embargo = cut - h * 86400
    tr = ts < embargo
    te = ts >= cut

    def build():
        return make_pipeline(PCA(n_components=40, random_state=0, svd_solver="randomized"),
                             MLPClassifier(hidden_layer_sizes=(64,), alpha=1e-2, max_iter=300,
                                           early_stopping=True, random_state=0))

    pipe = build().fit(X[tr].astype(np.float32), y[tr])
    p = pipe.predict_proba(X[te].astype(np.float32))[:, 1]
    mean_cost = float(cost[te].mean())
    # pooled, overlapping windows -> thin to every (h*PX)-th sample for the significance test
    hold = cmodel.evaluate(p, y[te], fwd[te], max(h, 3), mean_cost)
    passed, reasons = cmodel.gate_check(hold)
    final = build().fit(X.astype(np.float32), y)
    rep = {"status": "trained", "passed": bool(passed), "reasons": reasons, "holdout": hold, "h": h,
           "n_samples": int(len(y)), "trained_at": int(time.time())}
    joblib.dump({"model": final, "report": rep}, MODEL_PATH)
    _art.clear()
    cmodel._gate_log({"event": "image_gate", "passed": bool(passed), "reasons": reasons, "holdout": hold})
    return rep


def _load():
    if "m" not in _art:
        _art["m"] = joblib.load(MODEL_PATH) if os.path.exists(MODEL_PATH) else None
    return _art["m"]


def analyze_image(file_bytes):
    """Return dict with p_up (None if unreadable), validated flag, notes, and the raster."""
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()
    except Exception:
        return {"ok": False, "reason": "That file is not a readable image."}
    ras, note = raster_from_image(img)
    if ras is None:
        return {"ok": False, "reason": note}
    art = _load()
    res = {"ok": True, "note": note, "raster": ras, "model": "none", "validated": False, "p_up": 0.5}
    if art is not None:
        p = float(art["model"].predict_proba(ras.reshape(1, -1).astype(np.float32))[0, 1])
        lo, hi = config.PROB_CLIP
        ok = bool(art["report"].get("passed"))
        res.update(p_up=min(hi, max(lo, p)) if ok else 0.5, model="chart-image model",
                   validated=ok, holdout=art["report"].get("holdout"),
                   reasons=art["report"].get("reasons"))
    return res
