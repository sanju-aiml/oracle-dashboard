"""Everything the gate checks. Two halves: (A) market signal quality on a never-trained-on holdout,
(B) LLM behaviour: valid JSON, correct arithmetic, tool-use instead of invented prices."""
from __future__ import annotations
import json, re
from typing import Callable
import numpy as np
import pandas as pd
from ..backtest.engine import run_long_short, metrics, buy_and_hold, deflated_sharpe
from ..signal.model import to_position
from ..data import calc

Generator = Callable[[list[dict]], str]     # messages -> assistant text

# ---------------- (A) market ----------------
def eval_market(preds: pd.DataFrame, cost_bps=10.0, n_trials=1, min_edge=0.05) -> dict:
    p = preds.copy()
    p["pred"] = p[["p_down", "p_flat", "p_up"]].values.argmax(axis=1)
    acc = float((p["pred"] == p["label"]).mean())
    naive = float((p["majority"] == p["label"]).mean())
    pos = to_position(p, min_edge=min_edge)
    fwd1 = p.pivot(index="date", columns="symbol", values="fwd1")
    strat = run_long_short(pos, fwd1, cost_bps=cost_bps).dropna()
    m = metrics(strat)
    bh = metrics(buy_and_hold(fwd1).dropna())
    # directional hit-rate where the model actually takes a view
    taken = p[(p["p_up"] - p["p_down"]).abs() >= min_edge]
    hit = float(((np.sign(taken["p_up"] - taken["p_down"])) == np.sign(taken["fwd_ret"])).mean()) if len(taken) else 0.0
    return {"direction_acc": acc, "naive_acc": naive, "acc_vs_naive": acc - naive, "hit_rate_when_trading": hit,
            "sharpe_after_costs": m["sharpe"], "max_drawdown": abs(m["max_dd"]), "cagr": m["cagr"],
            "bh_sharpe": bh["sharpe"], "deflated_sharpe_prob": deflated_sharpe(m["sharpe"], m["n"], n_trials),
            "n_days": m["n"]}

# ---------------- (B) LLM ----------------
NUM = re.compile(r"-?\d[\d,]*\.?\d*")

def _nums(text: str) -> list[float]:
    out = []
    for t in NUM.findall(text):
        try:
            out.append(float(t.replace(",", "")))
        except ValueError:
            pass
    return out

def calc_cases(n=200, seed=123) -> list[tuple[list[dict], float, str]]:
    """Held-out arithmetic cases with exact answers (different seed than training)."""
    from ..data.sft_builder import SYSTEM
    import random
    rng = random.Random(seed)
    cases = []
    for _ in range(n):
        k = rng.choice(["gst", "emi", "tax"])
        if k == "gst":
            amt, rate = rng.randrange(1000, 900000, 7), rng.choice([5, 12, 18, 28])
            q, ans = f"Invoice ₹{amt:,} excl. GST at {rate}%. Total payable including GST?", calc.gst(amt, rate)["total"]
        elif k == "emi":
            P, r, y = rng.randrange(100000, 9000000, 1000), rng.choice([7.9, 8.65, 9.5, 11.0]), rng.choice([3, 7, 12, 25])
            q, ans = f"Loan ₹{P:,}, {r}% p.a., {y} years, monthly reducing. EMI?", calc.emi(P, r, y)["emi"]
        else:
            inc = rng.randrange(500000, 3500000, 1000)
            q, ans = f"Salaried gross income ₹{inc:,}, new regime. Total tax with cess?", calc.tax_new_regime(inc)["total"]
        cases.append(([{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}], ans, k))
    return cases

def eval_llm(gen: Generator, n_calc=200, n_json=100, n_tool=60, tol=0.01) -> dict:
    from ..data.sft_builder import SYSTEM
    # arithmetic
    ok, fails = 0, []
    cases = calc_cases(n_calc)
    for msgs, ans, kind in cases:
        out = gen(msgs)
        hit = any(abs(x - ans) <= max(tol, abs(ans) * 1e-4) for x in _nums(out))
        ok += hit
        if not hit:
            fails.append({"kind": kind, "q": msgs[-1]["content"], "expected": ans, "got": out[:300]})
    # JSON validity on market prompts
    js_ok = 0
    for i in range(n_json):
        out = gen([{"role": "system", "content": SYSTEM},
                   {"role": "user", "content": f"As of 2024-0{1 + i % 9}-1{i % 9}, assess RELIANCE.NS over the next 5 sessions. Data: 21d return {(i%7-3)/100:.2%}, 63d vol 22.0%, RSI {30+i%40}, drawdown from 1y high -{i%15}.0%."}])
        try:
            d = json.loads(out)
            js_ok += all(k in d for k in ("view", "probabilities", "confidence", "action"))
        except Exception:
            pass
    # hallucination: live-price questions MUST become tool calls, never numbers
    tool_ok = 0
    for i in range(n_tool):
        s = ["TCS.NS", "GC=F", "BTC-USD", "CL=F", "^NSEI"][i % 5]
        out = gen([{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"What is {s} trading at right now?"}])
        try:
            d = json.loads(out)
            tool_ok += d.get("tool") == "get_quote" and d.get("args", {}).get("symbol") == s
        except Exception:
            pass
    return {"calc_accuracy": ok / n_calc, "json_validity": js_ok / n_json,
            "hallucination_rate": 1 - tool_ok / n_tool, "calc_failures": fails[:50]}
