"""Quant signal model the LLM calls as a TOOL (LLM = reasoning/explanation; numbers come from here).
Gradient boosting on the features, purged walk-forward, calibrated probabilities -> position sizing.
Also includes DeepLOB (paper 1808.03668) for users who have limit-order-book data."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..features.ta import build_features, make_labels
from ..backtest.engine import walk_forward_splits

FEATURE_EXCLUDE = {"date", "symbol", "close", "fwd_ret", "label", "alpha"}

def build_panel(prices: pd.DataFrame, horizon=5) -> pd.DataFrame:
    parts = []
    for sym, g in prices.groupby("symbol"):
        g = g.sort_values("date")
        if len(g) < 400:
            continue
        f = build_features(g)
        lab = make_labels(f["close"], horizon=horizon)
        f = pd.concat([f, lab], axis=1)
        f["fwd1"] = f["close"].shift(-1) / f["close"] - 1
        parts.append(f)
    return pd.concat(parts, ignore_index=True)

def feature_cols(panel: pd.DataFrame) -> list[str]:
    return [c for c in panel.columns if c not in FEATURE_EXCLUDE and c != "fwd1"]

def _model(seed=0, **kw):
    from sklearn.ensemble import HistGradientBoostingClassifier
    p = dict(max_depth=4, learning_rate=0.05, max_iter=200, l2_regularization=1.0,
             min_samples_leaf=200, random_state=seed)
    p.update(kw)
    return HistGradientBoostingClassifier(**p)

def walk_forward_predict(panel: pd.DataFrame, n_splits=5, horizon=5, seed=0, **kw) -> pd.DataFrame:
    """Out-of-sample probabilities for every test row. Nothing in a test window is ever trained on."""
    cols = feature_cols(panel)
    p = panel[panel["label"] >= 0].dropna(subset=cols).copy()
    out = []
    for tr_dates, te_dates in walk_forward_splits(p["date"], n_splits=n_splits, horizon=horizon):
        tr = p[p["date"].isin(tr_dates)]
        te = p[p["date"].isin(te_dates)]
        if len(tr) < 1000 or te.empty or tr["label"].nunique() < 3:
            continue
        m = _model(seed, **kw).fit(tr[cols], tr["label"])
        pr = m.predict_proba(te[cols])
        cls = list(m.classes_)
        res = te[["date", "symbol", "label", "fwd_ret", "fwd1"]].copy()
        for k, nm in ((0, "p_down"), (1, "p_flat"), (2, "p_up")):
            res[nm] = pr[:, cls.index(k)] if k in cls else 0.0
        res["majority"] = tr["label"].mode().iloc[0]
        out.append(res)
    if not out:
        raise RuntimeError("no walk-forward folds produced; need more history")
    return pd.concat(out, ignore_index=True)

def to_position(preds: pd.DataFrame, min_edge=0.05) -> pd.DataFrame:
    """Position = (p_up - p_down), zeroed below an edge threshold (confidence routing -> abstain)."""
    s = preds["p_up"] - preds["p_down"]
    s = s.where(s.abs() >= min_edge, 0.0)
    return preds.assign(position=s.clip(-1, 1)).pivot(index="date", columns="symbol", values="position")

# ---------------- DeepLOB (arXiv 1808.03668) ----------------
def make_deeplob(n_classes=3, T=100, n_feat=40):
    import torch.nn as nn
    class DeepLOB(nn.Module):
        def __init__(self):
            super().__init__()
            lr = nn.LeakyReLU(0.01)
            def blk(i, o, k, s=(1, 1), pad=(0, 0)):
                return [nn.Conv2d(i, o, k, s, pad), nn.LeakyReLU(0.01), nn.BatchNorm2d(o)]
            self.conv = nn.Sequential(
                *blk(1, 32, (1, 2), (1, 2)), *blk(32, 32, (4, 1), pad=(2, 0)), *blk(32, 32, (4, 1), pad=(1, 0)),
                *blk(32, 32, (1, 2), (1, 2)), *blk(32, 32, (4, 1), pad=(2, 0)), *blk(32, 32, (4, 1), pad=(1, 0)),
                *blk(32, 32, (1, n_feat // 4)), *blk(32, 32, (4, 1), pad=(2, 0)), *blk(32, 32, (4, 1), pad=(1, 0)))
            def inc(k):
                return nn.Sequential(nn.Conv2d(32, 64, (1, 1), padding=(0, 0)), nn.LeakyReLU(0.01), nn.BatchNorm2d(64),
                                     nn.Conv2d(64, 64, (k, 1), padding=(k // 2, 0)), nn.LeakyReLU(0.01), nn.BatchNorm2d(64))
            self.i1, self.i2 = inc(3), inc(5)
            self.i3 = nn.Sequential(nn.MaxPool2d((3, 1), 1, (1, 0)), nn.Conv2d(32, 64, (1, 1)), nn.LeakyReLU(0.01), nn.BatchNorm2d(64))
            self.lstm = nn.LSTM(192, 64, batch_first=True)
            self.fc = nn.Linear(64, n_classes)
        def forward(self, x):                                     # x: (B, 1, T, n_feat)
            import torch
            h = self.conv(x)
            h = torch.cat([self.i1(h), self.i2(h), self.i3(h)], dim=1)   # (B,192,T',1)
            h = h.squeeze(-1).permute(0, 2, 1)
            o, _ = self.lstm(h)
            return self.fc(o[:, -1])
    return DeepLOB()
