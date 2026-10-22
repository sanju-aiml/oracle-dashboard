"""Builds the instruction-tuning corpus. Three families:
 (1) market-reasoning examples whose ANSWERS are derived from the quant tool + realised outcomes (time-safe),
 (2) CA/banking/tax Q&A with programmatically verified arithmetic (GST, TDS, EMI, SIP, compound interest),
 (3) structured-output / tool-call traces (JSON) so the model learns to CALL tools instead of guessing numbers.
Every example carries `as_of` so the gate can enforce 'no future data in the prompt'."""
from __future__ import annotations
import json, random
import numpy as np
import pandas as pd
from . import calc

SYSTEM = ("You are FinLLM, a financial analyst assistant for Indian and global markets, CAs and bankers. "
          "Never invent prices or figures: call tools for live data, show calculations, state uncertainty, "
          "never promise returns. Output is decision support, not guaranteed advice.")

def market_examples(preds: pd.DataFrame, feats: pd.DataFrame, max_n=20000, seed=0) -> list[dict]:
    """preds from walk_forward_predict (out-of-sample); the assistant turn reports the model's calibrated view,
    NOT the realised outcome (training the LLM on outcomes would teach it hindsight)."""
    rng = random.Random(seed)
    m = preds.merge(feats, on=["date", "symbol"], how="left")
    rows = m.sample(min(max_n, len(m)), random_state=seed).to_dict("records")
    out = []
    for r in rows:
        edge = r["p_up"] - r["p_down"]
        view = "bullish" if edge > 0.05 else "bearish" if edge < -0.05 else "neutral / no edge"
        conf = max(r["p_up"], r["p_down"], r["p_flat"])
        user = (f"As of {pd.Timestamp(r['date']).date()}, assess {r['symbol']} over the next 5 sessions. "
                f"Data: 21d return {r.get('ret_21', float('nan')):.2%}, 63d vol {r.get('vol_63', float('nan')):.1%}, "
                f"RSI {r.get('rsi14', float('nan')):.0f}, drawdown from 1y high {r.get('dd_252', float('nan')):.1%}.")
        ans = json.dumps({
            "view": view,
            "probabilities": {"up": round(r["p_up"], 3), "flat": round(r["p_flat"], 3), "down": round(r["p_down"], 3)},
            "confidence": round(conf, 3),
            "action": "abstain" if view.startswith("neutral") else ("long_bias" if edge > 0 else "short_or_reduce"),
            "risk_notes": ["Probabilities come from a walk-forward model; edges are small and non-stationary.",
                           "Size positions with a volatility budget and a stop; costs not included."],
            "disclaimer": "Decision support only. Not guaranteed."}, ensure_ascii=False)
        out.append({"as_of": str(pd.Timestamp(r["date"]).date()), "family": "market",
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                                 {"role": "assistant", "content": ans}]})
    rng.shuffle(out)
    return out

ALL_KINDS = ["gst", "emi", "sip", "ci", "tds_194c", "hra", "tax_new_regime"]

def calc_examples(n=6000, seed=0, kinds=None) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        kind = rng.choice(kinds or ALL_KINDS)
        if kind == "gst":
            amt, rate = rng.randrange(1000, 500000, 50), rng.choice([5, 12, 18, 28])
            q = f"Invoice value is ₹{amt:,} excluding GST at {rate}%. Intra-state. Give CGST, SGST and total."
            r = calc.gst(amt, rate)
            a = (f"GST = {amt:,} × {rate}% = ₹{r['gst']:,.2f}. CGST = SGST = ₹{r['cgst']:,.2f} each "
                 f"({rate/2}% each). Total payable = ₹{r['total']:,.2f}.")
        elif kind == "emi":
            P, rate, yrs = rng.randrange(100000, 10000000, 50000), rng.choice([7.5, 8.4, 9.0, 10.5, 12.0]), rng.choice([5, 10, 15, 20])
            q = f"Loan ₹{P:,} at {rate}% p.a. for {yrs} years, monthly reducing balance. What is the EMI and total interest?"
            r = calc.emi(P, rate, yrs)
            a = (f"EMI = P·r(1+r)^n/((1+r)^n−1) with r = {rate}/1200, n = {yrs*12}. EMI = ₹{r['emi']:,.2f}. "
                 f"Total paid = ₹{r['total_paid']:,.2f}; total interest = ₹{r['total_interest']:,.2f}.")
        elif kind == "sip":
            m, rate, yrs = rng.randrange(1000, 100000, 500), rng.choice([8, 10, 12, 15]), rng.choice([5, 10, 15, 20])
            q = f"SIP of ₹{m:,}/month at an assumed {rate}% annual return for {yrs} years (end-of-month). Future value?"
            r = calc.sip_fv(m, rate, yrs)
            a = (f"FV = m·((1+i)^n−1)/i with i = {rate}/1200, n = {yrs*12}. FV = ₹{r['fv']:,.0f}; invested ₹{r['invested']:,.0f}; "
                 f"gain ₹{r['gain']:,.0f}. This is an assumption, not a forecast.")
        elif kind == "ci":
            P, rate, yrs, k = rng.randrange(10000, 5000000, 10000), rng.choice([6, 7.1, 8, 9]), rng.choice([2, 5, 10]), rng.choice([1, 2, 4, 12])
            q = f"₹{P:,} at {rate}% p.a. compounded {k}x per year for {yrs} years. Maturity amount?"
            v = calc.compound(P, rate, yrs, k)
            a = f"A = P(1+r/k)^(kt) = {P:,}×(1+{rate/100}/{k})^({k*yrs}) = ₹{v:,.2f}."
        elif kind == "tds_194c":
            amt, pan = rng.randrange(20000, 3000000, 1000), rng.choice([True, False])
            q = f"Payment of ₹{amt:,} to a contractor (individual) under section 194C. PAN {'available' if pan else 'not available'}. TDS?"
            r = calc.tds_194c(amt, pan, payee="individual")
            a = r["explain"]
        elif kind == "hra":
            basic, hra, rent, metro = rng.randrange(20000, 200000, 1000), rng.randrange(5000, 100000, 1000), rng.randrange(5000, 100000, 500), rng.choice([True, False])
            q = f"Monthly basic+DA ₹{basic:,}, HRA received ₹{hra:,}, rent paid ₹{rent:,}, {'metro' if metro else 'non-metro'}. Exempt HRA per month (old regime)?"
            r = calc.hra_exemption(basic, hra, rent, metro)
            a = r["explain"]
        else:
            inc = rng.randrange(400000, 4000000, 10000)
            q = f"Salaried, gross income ₹{inc:,}, new tax regime. Tax payable including cess? (use the slabs in the tool config)"
            r = calc.tax_new_regime(inc)
            a = r["explain"]
        out.append({"as_of": "static", "family": "calc",
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q},
                                 {"role": "assistant", "content": a}]})
    return out

def tool_trace_examples(n=2000, seed=0) -> list[dict]:
    rng = random.Random(seed)
    syms = ["RELIANCE.NS", "TCS.NS", "^NSEI", "GC=F", "CL=F", "BTC-USD", "USDINR=X"]
    out = []
    for _ in range(n):
        s = rng.choice(syms)
        user = rng.choice([f"What is {s} trading at right now?", f"Give me the live price of {s}.", f"{s} ippudu entha undi?"])
        call = json.dumps({"tool": "get_quote", "args": {"symbol": s}})
        out.append({"as_of": "static", "family": "tool",
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                                 {"role": "assistant", "content": call}]})
    return out

def write_jsonl(rows: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
