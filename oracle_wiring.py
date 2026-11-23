"""Connects the bot to ORACLE's real market, core, and provider functions.

In server.py (FastAPI branch), replace the old /api/chat route with:

    from oracle_wiring import build_bot_router
    import finllm_engine
    app.include_router(build_bot_router(
        app, market, core, get_current_user,
        signal_fn=finllm_engine.predict_signal,
        deeplob_fn=finllm_engine.run_deeplob_signal,
        place_order_fn=lambda rec: market.place_alpaca_order(rec["symbol"], rec["qty"], rec["side"])
    ))

Env: ORACLE_LLM_URL (default Ollama http://127.0.0.1:11434/v1/chat/completions), ORACLE_LLM_MODEL (default oracle-bot).
"""
from __future__ import annotations
import os, sys
cur_dir = os.path.dirname(os.path.abspath(__file__))
if cur_dir not in sys.path:
    sys.path.insert(0, cur_dir)

finllm_root = r"C:\Users\BOTTA THARUN\OneDrive\Pictures\Screenshots\finllm (1)1\finllm"
if os.path.exists(finllm_root) and finllm_root not in sys.path:
    sys.path.insert(0, finllm_root)

_repo_finllm = os.path.join(cur_dir, "uploaded_model", "finllm")
if os.path.exists(_repo_finllm) and _repo_finllm not in sys.path:
    sys.path.insert(0, _repo_finllm)

def _num(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        if isinstance(v, str):
            try:
                cleaned = v.replace(",", "").replace("$", "").replace("₹", "").replace("%", "").replace("+", "").strip()
                return float(cleaned)
            except ValueError:
                pass
    return None

def make_handlers(market, core, providers, signal_fn=None, deeplob_fn=None, news_fn=None, docs_fn=None, place_order_fn=None):
    def get_quote(symbol):
        try:
            r = market.get_live_quote("stock", symbol, mode="live") or {}
            price = _num(r, "price", "last", "c", "close")
            if price is not None and r.get("feed_status") not in ("unavailable", "not_configured") and r.get("status") == "ok":
                return {
                    "price": price,
                    "change_pct": _num(r, "change_pct", "percent_change", "dp", "change_percent"),
                    "ts": r.get("data_timestamp") or r.get("as_of") or r.get("ts") or "",
                    "source": r.get("provider_name") or r.get("source") or "oracle",
                    "status": r.get("feed_status", "live"),
                    "declared_delay_s": 0
                }
        except Exception:
            pass
        return providers.get_quote(symbol)

    def get_ohlcv(symbol, interval, outputsize):
        try:
            r = market.get_ohlcv(symbol, interval, outputsize, mode="live") or {}
            if r.get("candles"):
                return {
                    **r,
                    "source": r.get("source", "twelvedata"),
                    "status": r.get("feed_status", "live")
                }
        except Exception:
            pass
        return providers.ohlcv(symbol, interval, outputsize)

    def get_commodity(name):
        try:
            r = market.get_live_commodity(name, mode="live") or {}
            price = _num(r, "price", "last", "close")
            if price is not None and r.get("feed_status") not in ("unavailable", "not_configured") and r.get("status") == "ok":
                return {
                    "symbol": r.get("commodity", name),
                    "price": price,
                    "change_pct": _num(r, "change_pct", "change_percent"),
                    "ts": r.get("data_timestamp") or r.get("retrieval_timestamp") or "",
                    "source": r.get("source") or r.get("provider_name") or "oracle",
                    "status": r.get("feed_status", "live"),
                    "declared_delay_s": 0
                }
        except Exception:
            pass
        sym_map = {"gold": "GOLD", "silver": "SILVER", "brent": "BRENT", "wti": "WTI", "naturalgas": "NATURALGAS"}
        sym = sym_map.get(name.lower(), name.upper())
        return providers.get_quote(providers.resolve(sym))

    def get_dashboard(role):
        try:
            if isinstance(role, dict) and "ws" in role:
                d = core.workspace_dashboard(role)
                data_kind = "actual"
            else:
                d = core.dashboard(core.demo_df(), "demo")
                data_kind = "demo"
        except Exception as e:
            return {"status": "unavailable", "error": str(e)[:100]}
        
        kpis = {k.get("name", "").lower(): k.get("value") for k in d.get("kpis", [])}
        rev = kpis.get("total revenue") if "total revenue" in kpis else d.get("revenue")
        pro = kpis.get("profit") if "profit" in kpis else d.get("profit")
        mar = kpis.get("net margin") if "net margin" in kpis else d.get("margin_pct")
        fc = kpis.get("next 6 months (est.)") if "next 6 months (est.)" in kpis else d.get("forecast_6m")
        if not fc and d.get("forecast") and isinstance(d["forecast"].get("mean"), list):
            fc = sum(d["forecast"]["mean"][:6])

        return {
            "revenue": round(float(rev), 2) if rev is not None else None,
            "profit": round(float(pro), 2) if pro is not None else None,
            "margin_pct": round(float(mar), 1) if mar is not None else None,
            "forecast_6m": round(float(fc), 2) if fc is not None else None,
            "data_kind": data_kind
        }

    def get_inventory(role):
        try:
            if isinstance(role, dict) and "ws" in role:
                d = core.workspace_dashboard(role)
            else:
                d = core.dashboard(core.demo_df(), "demo")
        except Exception as e:
            return {"status": "unavailable", "error": str(e)[:100]}
        
        raw_items = d.get("inventory", [])
        items = []
        for it in raw_items:
            days = float(it.get("days_of_stock", 0))
            r_str = str(it.get("stockout_risk", "")).lower()
            risk = "high" if ("high" in r_str or "urgent" in r_str or days < 6.0) else "low"
            items.append({
                "sku": it.get("sku", ""),
                "product": it.get("name", ""),
                "days_left": round(days, 1),
                "risk": risk
            })
        return {"items": items}

    h = {
        "get_quote": get_quote,
        "get_ohlcv": get_ohlcv,
        "get_commodity": get_commodity,
        "get_dashboard": get_dashboard,
        "get_inventory": get_inventory
    }
    if signal_fn: h["get_signal"] = signal_fn
    if deeplob_fn: h["get_deeplob"] = deeplob_fn
    if news_fn: h["get_news"] = lambda query: news_fn(query)
    if docs_fn: h["search_docs"] = lambda query: docs_fn(query)
    if place_order_fn: h["place_order"] = place_order_fn
    return h

def build_bot_router(app, market, core, get_current_user, **handler_fns):
    import oracle_providers as providers
    from finllm.bot.api import make_router
    from finllm.bot.executor import OracleExecutor
    from finllm.bot.llm_clients import http_generator

    gen = http_generator(
        os.environ.get("ORACLE_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions"),
        os.environ.get("ORACLE_LLM_MODEL", "oracle-bot"),
        timeout=60
    )
    ex = OracleExecutor(make_handlers(market, core, providers, **handler_fns))

    def role_of(request):
        try:
            u = get_current_user(request)
            return "owner" if u else "demo"
        except Exception:
            return "demo"

    return make_router(gen, ex, role_of)
