"""Maps bot tool calls to ORACLE functions. Inject handlers from server/market/core; this file never talks to the network itself.
handlers = {"get_quote": fn(symbol)->dict, "get_ohlcv": fn(symbol, interval, outputsize)->dict, "get_commodity": fn(name)->dict,
            "get_signal": fn(symbol), "get_deeplob": fn(symbol), "get_dashboard": fn(role)->dict, "get_inventory": fn(role)->dict,
            "search_docs": fn(query)->dict, "get_news": fn(query)->dict, "place_order": fn(order)->dict (called ONLY after human approval)}"""
from __future__ import annotations
import itertools, time
from ..data import calc as calc_mod

def short_ts(ts) -> str:
    import pandas as pd
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%d %H:%M UTC") if getattr(pd.Timestamp(ts), "tzinfo", None) else str(ts)[:16] + " UTC"

def normalize_quote(d: dict, symbol: str) -> dict:
    """providers.Quote.to_dict() or any ORACLE quote -> the exact shape the bot was trained on."""
    if d.get("status") == "unavailable" or "price" not in d:
        return {"symbol": symbol, "status": "unavailable", "error": str(d.get("error", "no data"))[:120]}
    return {"symbol": symbol, "price": round(float(d["price"]), 2), "change_pct": round(float(d.get("change_pct") or 0.0), 2), "ts": short_ts(d["ts"]),
            "source": str(d.get("source", "unknown")), "status": d.get("status", "delayed"), "delay_min": int(d.get("declared_delay_s", 0)) // 60}

def summarize_ohlcv(d: dict, symbol: str) -> dict:
    c = d.get("candles") or []
    if not c: return {"symbol": symbol, "status": "unavailable", "error": "no candles"}
    hi = max(float(x["high"]) for x in c); lo = min(float(x["low"]) for x in c)
    return {"symbol": symbol, "candle_count": len(c), "high": round(hi, 2), "low": round(lo, 2), "last_close": round(float(c[0]["close"]), 2), "source": d.get("source", "unknown"),
            "ts": short_ts(d.get("last_ts", c[0]["datetime"])), "status": d.get("status", "delayed"), "delay_min": int(d.get("declared_delay_s", 0)) // 60}

class OracleExecutor:
    def __init__(self, handlers: dict, on_pending=None):
        self.h, self.pending, self._ids, self.on_pending = handlers, {}, itertools.count(100), on_pending

    def __call__(self, name: str, args: dict, role: str = "demo") -> dict:
        if name == "calc":
            r = getattr(calc_mod, args["kind"])(**args["params"])
            return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k != "explain"}
        if name == "propose_order":
            if role == "demo": return {"status": "denied", "error": "login required to propose orders"}
            oid = f"A{next(self._ids)}"; rec = {"status": "pending_approval", "id": oid, **args, "created": time.time()}
            self.pending[oid] = rec
            if self.on_pending: self.on_pending(rec)
            return {k: rec[k] for k in ("status", "id", "symbol", "side", "qty")}
        if name not in self.h: return {"status": "unavailable", "error": f"tool {name} not wired"}
        if name in ("get_dashboard", "get_inventory"): return self.h[name](role)
        out = self.h[name](**args)
        if name == "get_quote": return normalize_quote(out, args["symbol"])
        if name == "get_ohlcv": return summarize_ohlcv(out, args["symbol"])
        return out

    def approve(self, oid: str, approver: str) -> dict:
        rec = self.pending.pop(oid, None)
        if not rec: return {"status": "not_found"}
        if "place_order" not in self.h: return {"status": "rejected", "error": "order placement not wired"}
        return self.h["place_order"]({**rec, "approved_by": approver})

    def reject(self, oid: str) -> dict:
        return {"status": "rejected" if self.pending.pop(oid, None) else "not_found"}
