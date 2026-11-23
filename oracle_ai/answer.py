"""Question -> answer. Always answers from ORACLE's own data layer: live quote if possible,
otherwise the stored price (labeled stale). Never says "unavailable" while any stored data exists,
and never invents a number. Works without any LLM; an LLM can polish the text but not change numbers."""
import datetime as dt
import re
import time

import config
import market_data as md
import model
import store

_STOP = {"I", "A", "THE", "AND", "FOR", "WILL", "WHAT", "IS", "IN", "ON", "OF", "TO", "IT", "MY", "ME", "DO",
         "CAN", "YOU", "ARE", "BUY", "SELL", "HOLD", "PRICE", "NEXT", "WEEK", "DAY", "ANY", "ALL", "NOW",
         "HOW", "WHY", "WHO", "YES", "NO", "OK", "AI", "USD", "INR", "SIP", "EMI", "GST", "IPO", "ETF"}

_INVEST = re.compile(r"\b(invest|buy|sell|should i|worth|hold|profit)\b", re.I)


def resolve_assets(question):
    """Match known aliases first; then try Yahoo tickers like TSLA, RELIANCE.NS, SOL-USD."""
    q = question.lower()
    hits = []
    for sym, a in config.ASSETS.items():
        for al in sorted(a["aliases"], key=len, reverse=True):
            if re.search(rf"(?<![a-z0-9]){re.escape(al)}(?![a-z0-9])", q):
                hits.append(sym)
                break
    if hits:
        # "oil" must not also match "crude oil"+"brent" duplicates; keep order, unique
        return list(dict.fromkeys(hits))[:3]
    for tok in re.findall(r"\b[A-Z][A-Z0-9]{1,9}(?:\.(?:NS|BO)|-USD)?\b", question):
        if tok in _STOP:
            continue
        sym = md.register_dynamic(tok)
        if sym:
            return [sym]
    return []


def _fmt(p):
    if p is None:
        return "n/a"
    return f"{p:,.2f}" if abs(p) >= 1 else f"{p:,.6f}"


def _ago(sec):
    if sec is None:
        return "unknown age"
    if sec < 90:
        return "just now"
    if sec < 5400:
        return f"{int(sec / 60)} min ago"
    if sec < 172800:
        return f"{sec / 3600:.1f} h ago"
    return f"{sec / 86400:.1f} days ago"


def _returns(df):
    out = {}
    c = df.close
    for label, n in (("7d", 7), ("30d", 30), ("90d", 90), ("1y", 252)):
        if len(c) > n:
            out[label] = (c.iloc[-1] / c.iloc[-1 - n] - 1) * 100
    return out


def _ensure_data(sym):
    """If nothing is stored yet for this asset, fetch history now (first-time asset)."""
    df = store.load_candles(sym, "1d")
    if len(df) < 60:
        md.seed_history(sym, "1d", 1500)
        df = store.load_candles(sym, "1d")
    return df


def asset_block(sym, detail=True):
    a = config.ASSETS[sym]
    q = md.get_quote(sym)
    df = _ensure_data(sym)
    lines = []
    if q["price"] is None:
        lines.append(f"{a['name']} ({sym}): I have no stored price for this yet. "
                     "ORACLE needs one online data sync (seed_history.py) before it can answer for this asset.")
        return "\n".join(lines), {"symbol": sym, "quote": q}

    status = {"fresh": "live", "backup": "live, backup source", "stale": "last stored price"}[q["status"]]
    stamp = dt.datetime.fromtimestamp(q["ts"], dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"**{a['name']} ({sym})**: {_fmt(q['price'])}  ({status}; {q['source']}; {stamp}, {_ago(q['age_sec'])})")
    if q.get("note"):
        lines.append(f"Note: {q['note']}.")
    if q.get("warning"):
        lines.append(f"Note: {q['warning']}.")

    data = {"symbol": sym, "quote": q}
    if len(df) >= 30:
        r = _returns(df)
        if r:
            lines.append("Past: " + " | ".join(f"{k} {v:+.1f}%" for k, v in r.items()))
        yr = df.tail(252)
        lines.append(f"52-week range: {_fmt(yr.low.min())} to {_fmt(yr.high.max())}")
        data["returns"] = r

    fc = model.forecast(sym) if len(df) >= 60 else {"available": False}
    data["forecast"] = fc
    if fc.get("available") and detail:
        for h, it in fc["horizons"].items():
            unit = "day" if h == 1 else "days"
            if it["model"] == "none":
                lines.append(f"Next {h} {unit}: no trained model yet, so direction is a coin flip (50/50).")
            elif it["gate_passed"]:
                ho = it["holdout"]
                lines.append(f"Next {h} {unit}: Up {it['p_up'] * 100:.0f}% / Down {(1 - it['p_up']) * 100:.0f}%  "
                             f"(model passed validation: {ho['acc'] * 100:.1f}% accuracy vs {ho['base_acc'] * 100:.1f}% baseline "
                             f"on {ho['n']} unseen days)")
            else:
                lines.append(f"Next {h} {unit}: Up {it['p_up'] * 100:.0f}% / Down {(1 - it['p_up']) * 100:.0f}%  "
                             "(model has NOT proven an edge on unseen data; treat direction as close to a coin flip)")
            lo68, hi68 = it["range68"]
            lo95, hi95 = it["range95"]
            lines.append(f"  Likely range (68%): {_fmt(lo68)} to {_fmt(hi68)}; (95%): {_fmt(lo95)} to {_fmt(hi95)}")
    elif detail:
        lines.append("Forecast: not enough stored history yet (needs 60+ daily candles).")

    live = store.prediction_stats(origin="bot", symbol=sym)
    if live["total"] >= 20:
        lines.append(f"Live track record of ORACLE's own calls on {sym}: {live['wins']}/{live['total']} correct "
                     f"({live['win_rate'] * 100:.0f}%).")
    return "\n".join(lines), data


def answer(question):
    """Returns {"answer": str, "assets": [...], "confidence_note": str}."""
    question = (question or "").strip()
    if not question:
        return {"answer": "Ask me about any market: Bitcoin, gold, crude oil, natural gas, Nifty, Apple, "
                          "or any stock ticker.", "assets": []}
    syms = resolve_assets(question)
    if not syms:
        names = ", ".join(sorted({a["name"] for a in config.ASSETS.values() if not a.get("dynamic")})[:14])
        return {"answer": "I could not match an asset in your question. Try a name or ticker, for example: "
                          f"{names}, or a Yahoo ticker like TSLA or RELIANCE.NS.", "assets": []}
    blocks, assets = [], []
    for s in syms:
        text, data = asset_block(s, detail=True)
        blocks.append(text)
        assets.append(data)
    out = "\n\n".join(blocks)
    if _INVEST.search(question):
        out += ("\n\nI cannot tell you to buy or sell. The numbers above show the recent move, the likely range and "
                "how reliable the model has been. Decide with your own goals and risk limit, and never invest money "
                "you cannot afford to lose.")
    out += ("\n\nAll forecasts are probabilities, not promises; markets can move against any model. "
            "Educational use only, not financial advice.")
    return {"answer": out, "assets": assets}
